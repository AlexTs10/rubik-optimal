"""External RubikOptimal solver bridge.

Herbert Kociemba's ``RubikOptimal`` package is a separate public optimal
solver with a large Reid-style pruning table.  Importing ``optimal.solver``
creates or loads tables in the current working directory, so this bridge never
imports it in-process.  It runs the package in a controlled subprocess with a
dedicated table directory and independently verifies every returned solution.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import selectors
import shutil
import subprocess
import time
import threading
from collections import deque
from concurrent.futures import ThreadPoolExecutor, wait
from pathlib import Path

from rubik_optimal.cube import CubeState
from rubik_optimal.moves import parse_sequence
from rubik_optimal.solvers.base import SolverResult
from rubik_optimal.symmetry import CUBE_ROTATIONS, CubeRotation
from rubik_optimal.verify import verify_solution

_RESULT_MARKER = "RUBIKOPTIMAL_RESULT_JSON="
_BATCH_RESULT_MARKER = "RUBIKOPTIMAL_BATCH_RESULT_JSON="
_READY_MARKER = "RUBIKOPTIMAL_READY_JSON="
_SOLUTION_RE = re.compile(r"^(?P<moves>.*?)\s*\((?P<length>\d+)f\*\)\s*$")

RUBIKOPTIMAL_TABLE_SIZES = {
    "conj_twist": 69_984,
    "fs24_classidx": 97_320_960,
    "fs24_sym": 24_330_240,
    "fs24_rep": 6_095_456,
    "move_twist": 78_732,
    "move_flip": 73_728,
    "move_slice_sorted": 427_680,
    "move_corners": 1_451_520,
    "phase1x24_prun": 833_172_644,
    "cornerprun": 40_320,
}


def repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def default_rubikoptimal_table_dir(root: Path | None = None) -> Path:
    root = root or repository_root()
    env_path = os.environ.get("RUBIKOPTIMAL_TABLE_DIR")
    return Path(env_path) if env_path else root / ".codex_external" / "rubikoptimal_tables"


def default_rubikoptimal_pythonpath() -> str | None:
    env_path = os.environ.get("RUBIKOPTIMAL_PACKAGE_PATH")
    if env_path:
        return env_path
    spec = importlib.util.find_spec("optimal")
    if spec is None or spec.origin is None:
        return None
    package_dir = Path(spec.origin).resolve().parent
    return str(package_dir.parent)


def find_rubikoptimal_executable(executable: str | Path | None = None) -> Path | None:
    if executable is not None:
        path = Path(executable)
        return path if path.exists() else None
    env_path = os.environ.get("RUBIKOPTIMAL_PYTHON")
    if env_path:
        path = Path(env_path)
        return path if path.exists() else None
    for candidate in ("pypy3", "python"):
        found = shutil.which(candidate)
        if found:
            return Path(found)
    return None


def rubikoptimal_table_inventory(table_dir: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for name, expected_size in RUBIKOPTIMAL_TABLE_SIZES.items():
        path = table_dir / name
        actual_size = path.stat().st_size if path.exists() else None
        rows.append(
            {
                "name": name,
                "path": str(path),
                "expected_size_bytes": expected_size,
                "exists": path.exists(),
                "actual_size_bytes": actual_size,
                "size_matches": actual_size == expected_size,
            }
        )
    return rows


def rubikoptimal_tables_ready(table_dir: Path) -> bool:
    return all(row["size_matches"] is True for row in rubikoptimal_table_inventory(table_dir))


def rubikoptimal_table_bytes(table_dir: Path) -> int | None:
    if not table_dir.exists():
        return None
    return sum(path.stat().st_size for path in table_dir.iterdir() if path.is_file())


def parse_rubikoptimal_solution(text: str) -> tuple[list[str], int]:
    match = _SOLUTION_RE.match(text.strip())
    if not match:
        raise ValueError(f"RubikOptimal output is not an optimal solution line: {text!r}")
    tokens = []
    for token in match.group("moves").split():
        if len(token) != 2 or token[0] not in "URFDLB" or token[1] not in "123":
            raise ValueError(f"unsupported RubikOptimal move token: {token!r}")
        suffix = {"1": "", "2": "2", "3": "'"}[token[1]]
        tokens.append(token[0] + suffix)
    moves = parse_sequence(tokens)
    length = int(match.group("length"))
    if len(moves) != length:
        raise ValueError(f"RubikOptimal length marker {length} disagrees with {len(moves)} parsed moves")
    return moves, length


def parse_rubikoptimal_process_output(output: str) -> tuple[list[str], int, str]:
    for line in reversed(output.splitlines()):
        if not line.startswith(_RESULT_MARKER):
            continue
        payload = json.loads(line[len(_RESULT_MARKER) :])
        solution_line = str(payload.get("result", ""))
        moves, length = parse_rubikoptimal_solution(solution_line)
        return moves, length, solution_line
    raise ValueError("RubikOptimal subprocess output did not contain a result marker")


def parse_rubikoptimal_batch_process_output(output: str) -> dict[int, dict[str, object]]:
    rows: dict[int, dict[str, object]] = {}
    for line in output.splitlines():
        if not line.startswith(_BATCH_RESULT_MARKER):
            continue
        payload = json.loads(line[len(_BATCH_RESULT_MARKER) :])
        index = int(payload["index"])
        status = str(payload.get("status", "error"))
        if status == "ok":
            solution_line = str(payload.get("result", ""))
            moves, length = parse_rubikoptimal_solution(solution_line)
            rows[index] = {
                "status": "ok",
                "moves": moves,
                "length": length,
                "raw_solution": solution_line,
                "child_runtime_seconds": float(payload.get("runtime_seconds", 0.0)),
                "table_load_seconds": float(payload.get("table_load_seconds", 0.0)),
            }
        else:
            rows[index] = {
                "status": status,
                "error": str(payload.get("error", "unknown RubikOptimal batch row error")),
                "timeout_seconds": payload.get("timeout_seconds"),
                "child_runtime_seconds": float(payload.get("runtime_seconds", 0.0)),
                "table_load_seconds": float(payload.get("table_load_seconds", 0.0)),
            }
    return rows


def _rubikoptimal_env(pythonpath: str) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = pythonpath + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    return env


def _readline_with_timeout(
    stream,
    *,
    timeout_seconds: float | None,
    buffer: bytearray,
) -> bytes | None:
    newline = b"\n"
    if newline in buffer:
        line, _, rest = bytes(buffer).partition(newline)
        buffer[:] = rest
        return line + newline
    if timeout_seconds is not None and timeout_seconds <= 0.0:
        return None
    deadline = None if timeout_seconds is None else time.perf_counter() + timeout_seconds
    while True:
        remaining = None if deadline is None else max(0.0, deadline - time.perf_counter())
        if remaining is not None and remaining <= 0.0:
            return None
        selector = selectors.DefaultSelector()
        selector.register(stream, selectors.EVENT_READ)
        try:
            events = selector.select(remaining)
            if not events:
                return None
            chunk = os.read(stream.fileno(), 4096)
        finally:
            selector.close()
        if not chunk:
            if buffer:
                line = bytes(buffer)
                buffer.clear()
                return line
            return b""
        buffer.extend(chunk)
        if newline in buffer:
            line, _, rest = bytes(buffer).partition(newline)
            buffer[:] = rest
            return line + newline


def _missing_table_names(table_dir: Path) -> list[str]:
    return [str(row["name"]) for row in rubikoptimal_table_inventory(table_dir) if row["size_matches"] is not True]


def _resident_child_timeout_seconds(timeout_seconds: float) -> float:
    timeout = max(0.0, float(timeout_seconds))
    if timeout == 0.0:
        return 0.0
    margin = min(1.0, max(0.05, timeout * 0.05), timeout * 0.5)
    return max(0.001, timeout - margin)


def _resident_parent_query_wait_seconds(timeout_seconds: float) -> float:
    timeout = max(0.0, float(timeout_seconds))
    if timeout == 0.0:
        return 0.0
    child_timeout = _resident_child_timeout_seconds(timeout)
    protocol_grace = min(2.0, max(0.25, timeout * 0.20))
    return max(timeout, child_timeout + protocol_grace)


def _resident_startup_timeout_seconds(timeout_seconds: float) -> float:
    timeout = max(0.0, float(timeout_seconds))
    if timeout == 0.0:
        return 0.0
    return max(timeout, 3.0)


class RubikOptimalOracleSession:
    """Resident RubikOptimal subprocess that keeps the table set loaded.

    ``solve_rubikoptimal_external_batch`` already amortizes RubikOptimal table
    loading within one corpus command.  This resident session does the same for
    repeated package/API calls.  Individual query timeouts are enforced inside
    the child process so the loaded table set can survive timed-out rows; the
    parent still kills the child if startup or protocol reads wedge.
    """

    def __init__(
        self,
        *,
        executable: str | Path | None = None,
        package_path: str | Path | None = None,
        table_dir: str | Path | None = None,
        root: Path | None = None,
    ) -> None:
        self.root = root or repository_root()
        self.selected_table_dir = (
            Path(table_dir) if table_dir is not None else default_rubikoptimal_table_dir(self.root)
        )
        self.executable = executable
        self.package_path = package_path
        self._process: subprocess.Popen[bytes] | None = None
        self._stdout_buffer = bytearray()
        self._table_load_seconds: float | None = None
        self._request_index = 0
        self.start_count = 0

    def __enter__(self) -> "RubikOptimalOracleSession":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def close(self) -> None:
        process = self._process
        self._process = None
        if process is None:
            return
        try:
            if process.stdin is not None:
                process.stdin.close()
        except OSError:
            pass
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1.0)

    def solve(self, cube: CubeState, *, timeout_seconds: float = 300.0) -> SolverResult:
        begin = time.perf_counter()
        table_bytes = rubikoptimal_table_bytes(self.selected_table_dir)
        if cube.is_solved():
            return SolverResult(
                solver_name="rubikoptimal_external",
                input_state=cube.to_facelets(),
                solution_moves=[],
                solution_length=0,
                metric="HTM",
                runtime_seconds=time.perf_counter() - begin,
                expanded_nodes=None,
                generated_nodes=None,
                table_bytes=table_bytes,
                status="exact",
                is_verified=True,
                notes=(
                    "resident RubikOptimal backend not invoked for solved state; "
                    "selected_backend=rubikoptimal_resident; backend_solver=rubikoptimal_external"
                ),
            )

        start_result = self._ensure_started(
            timeout_seconds=_resident_startup_timeout_seconds(timeout_seconds)
        )
        if start_result is not None:
            return self._result_from_start_failure(cube, start_result, begin=begin)
        process = self._process
        if process is None or process.stdin is None or process.stdout is None:
            return SolverResult(
                solver_name="rubikoptimal_external",
                input_state=cube.to_facelets(),
                solution_moves=[],
                solution_length=None,
                metric="HTM",
                runtime_seconds=time.perf_counter() - begin,
                expanded_nodes=None,
                generated_nodes=None,
                table_bytes=rubikoptimal_table_bytes(self.selected_table_dir),
                status="failed",
                is_verified=False,
                notes=(
                    "RubikOptimal resident session was not available after start; "
                    "selected_backend=rubikoptimal_resident; backend_solver=rubikoptimal_external"
                ),
            )

        self._request_index += 1
        request_index = self._request_index
        child_timeout_seconds = _resident_child_timeout_seconds(timeout_seconds)
        try:
            process.stdin.write(
                (
                    json.dumps(
                        {
                            "index": request_index,
                            "state": cube.to_facelets(),
                            "timeout_seconds": child_timeout_seconds,
                        }
                    )
                    + "\n"
                ).encode()
            )
            process.stdin.flush()
        except OSError as exc:
            self.close()
            return SolverResult(
                solver_name="rubikoptimal_external",
                input_state=cube.to_facelets(),
                solution_moves=[],
                solution_length=None,
                metric="HTM",
                runtime_seconds=time.perf_counter() - begin,
                expanded_nodes=None,
                generated_nodes=None,
                table_bytes=rubikoptimal_table_bytes(self.selected_table_dir),
                status="failed",
                is_verified=False,
                notes=(
                    "RubikOptimal resident write failed; selected_backend=rubikoptimal_resident; "
                    f"backend_solver=rubikoptimal_external; error={exc}"
                ),
            )

        parent_query_wait_seconds = _resident_parent_query_wait_seconds(timeout_seconds)
        timeout_deadline = time.perf_counter() + parent_query_wait_seconds
        output_lines: list[str] = []
        while True:
            remaining = max(0.0, timeout_deadline - time.perf_counter())
            line = _readline_with_timeout(
                process.stdout,
                timeout_seconds=remaining,
                buffer=self._stdout_buffer,
            )
            if line is None:
                partial = self._stdout_buffer.decode(errors="replace")
                self.close()
                return SolverResult(
                    solver_name="rubikoptimal_external",
                    input_state=cube.to_facelets(),
                    solution_moves=[],
                    solution_length=None,
                    metric="HTM",
                    runtime_seconds=time.perf_counter() - begin,
                    expanded_nodes=None,
                    generated_nodes=None,
                    table_bytes=rubikoptimal_table_bytes(self.selected_table_dir),
                    status="timeout",
                    is_verified=False,
                    notes=(
                        "RubikOptimal resident query timed out and the resident process was stopped; "
                        "selected_backend=rubikoptimal_resident; backend_solver=rubikoptimal_external; "
                        f"timeout_seconds={timeout_seconds}; "
                        f"child_timeout_seconds={child_timeout_seconds}; "
                        f"parent_query_wait_seconds={parent_query_wait_seconds}; "
                        f"partial_output={' | '.join(output_lines + ([partial] if partial else []))}"
                    ),
                )
            if not line:
                self.close()
                return SolverResult(
                    solver_name="rubikoptimal_external",
                    input_state=cube.to_facelets(),
                    solution_moves=[],
                    solution_length=None,
                    metric="HTM",
                    runtime_seconds=time.perf_counter() - begin,
                    expanded_nodes=None,
                    generated_nodes=None,
                    table_bytes=rubikoptimal_table_bytes(self.selected_table_dir),
                    status="failed",
                    is_verified=False,
                    notes=(
                        "RubikOptimal resident process exited before returning a row; "
                        "selected_backend=rubikoptimal_resident; backend_solver=rubikoptimal_external; "
                        f"partial_output={' | '.join(output_lines)}"
                    ),
                )
            line_text = line.decode(errors="replace")
            if line_text.startswith(_BATCH_RESULT_MARKER):
                rows = parse_rubikoptimal_batch_process_output(line_text)
                row = rows.get(request_index)
                if row is not None:
                    return self._result_from_row(
                        cube,
                        row,
                        begin=begin,
                        request_index=request_index,
                        reused_process=self.start_count == 1 and request_index > 1,
                    )
            else:
                output_lines.append(line_text.strip())

    def _ensure_started(self, *, timeout_seconds: float) -> dict[str, object] | None:
        if self._process is not None and self._process.poll() is None:
            return None

        table_bytes = rubikoptimal_table_bytes(self.selected_table_dir)
        if not rubikoptimal_tables_ready(self.selected_table_dir):
            return {
                "status": "not_applicable",
                "table_bytes": table_bytes,
                "notes": (
                    "RubikOptimal tables are not ready in the dedicated table directory; "
                    f"missing_or_wrong={','.join(_missing_table_names(self.selected_table_dir))}; "
                    f"table_dir={self.selected_table_dir}"
                ),
            }
        selected_executable = find_rubikoptimal_executable(self.executable)
        if selected_executable is None:
            return {
                "status": "not_applicable",
                "table_bytes": table_bytes,
                "notes": "RubikOptimal Python executable not found; set RUBIKOPTIMAL_PYTHON or install pypy3",
            }
        pythonpath = str(self.package_path) if self.package_path is not None else default_rubikoptimal_pythonpath()
        if pythonpath is None:
            return {
                "status": "not_applicable",
                "table_bytes": table_bytes,
                "notes": "RubikOptimal package not found; install the RubikOptimal package or set RUBIKOPTIMAL_PACKAGE_PATH",
            }

        code = (
            "import json, signal, sys, time\n"
            "class QueryTimeout(Exception):\n"
            "    pass\n"
            "def _query_timeout_handler(signum, frame):\n"
            "    raise QueryTimeout('resident RubikOptimal query timed out')\n"
            "signal.signal(signal.SIGALRM, _query_timeout_handler)\n"
            "load_begin = time.perf_counter()\n"
            "import optimal.solver as solver\n"
            "table_load_seconds = time.perf_counter() - load_begin\n"
            f"print({_READY_MARKER!r} + json.dumps({{'status': 'ready', 'table_load_seconds': table_load_seconds}}), flush=True)\n"
            "for line in sys.stdin:\n"
            "    if not line.strip():\n"
            "        continue\n"
            "    item = json.loads(line)\n"
            "    query_timeout_seconds = float(item.get('timeout_seconds') or 0.0)\n"
            "    begin = time.perf_counter()\n"
            "    try:\n"
            "        if query_timeout_seconds <= 0.0:\n"
            "            raise QueryTimeout('non-positive resident RubikOptimal query timeout')\n"
            "        signal.setitimer(signal.ITIMER_REAL, query_timeout_seconds)\n"
            "        result = solver.solve(item['state'])\n"
            "        payload = {'index': item['index'], 'status': 'ok', 'result': result}\n"
            "    except QueryTimeout as exc:\n"
            "        payload = {'index': item['index'], 'status': 'timeout', 'error': str(exc), 'timeout_seconds': query_timeout_seconds}\n"
            "    except Exception as exc:\n"
            "        payload = {'index': item['index'], 'status': 'error', 'error': repr(exc)}\n"
            "    finally:\n"
            "        signal.setitimer(signal.ITIMER_REAL, 0.0)\n"
            "    payload['runtime_seconds'] = time.perf_counter() - begin\n"
            "    payload['table_load_seconds'] = table_load_seconds\n"
            f"    print({_BATCH_RESULT_MARKER!r} + json.dumps(payload), flush=True)\n"
        )
        self._stdout_buffer = bytearray()
        self._process = subprocess.Popen(
            [str(selected_executable), "-c", code],
            cwd=self.selected_table_dir,
            env=_rubikoptimal_env(pythonpath),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=0,
        )
        self.start_count += 1

        assert self._process.stdout is not None
        deadline = time.perf_counter() + max(0.0, timeout_seconds)
        output_lines: list[str] = []
        while True:
            remaining = max(0.0, deadline - time.perf_counter())
            line = _readline_with_timeout(
                self._process.stdout,
                timeout_seconds=remaining,
                buffer=self._stdout_buffer,
            )
            if line is None:
                partial = self._stdout_buffer.decode(errors="replace")
                self.close()
                return {
                    "status": "timeout",
                    "table_bytes": rubikoptimal_table_bytes(self.selected_table_dir),
                    "notes": (
                        "RubikOptimal resident startup timed out while importing/loading tables; "
                        f"timeout_seconds={timeout_seconds}; "
                        f"partial_output={' | '.join(output_lines + ([partial] if partial else []))}"
                    ),
                }
            if not line:
                return {
                    "status": "failed",
                    "table_bytes": rubikoptimal_table_bytes(self.selected_table_dir),
                    "notes": (
                        "RubikOptimal resident process exited before ready marker; "
                        f"partial_output={' | '.join(output_lines)}"
                    ),
                }
            line_text = line.decode(errors="replace")
            if line_text.startswith(_READY_MARKER):
                payload = json.loads(line_text[len(_READY_MARKER) :])
                self._table_load_seconds = float(payload.get("table_load_seconds", 0.0))
                return None
            output_lines.append(line_text.strip())

    def _result_from_start_failure(
        self,
        cube: CubeState,
        start_result: dict[str, object],
        *,
        begin: float,
    ) -> SolverResult:
        return SolverResult(
            solver_name="rubikoptimal_external",
            input_state=cube.to_facelets(),
            solution_moves=[],
            solution_length=None,
            metric="HTM",
            runtime_seconds=time.perf_counter() - begin,
            expanded_nodes=None,
            generated_nodes=None,
            table_bytes=start_result.get("table_bytes"),
            status=str(start_result["status"]),
            is_verified=False,
            notes=(
                "RubikOptimal resident session unavailable; selected_backend=rubikoptimal_resident; "
                f"backend_solver=rubikoptimal_external; {start_result['notes']}"
            ),
        )

    def _result_from_row(
        self,
        cube: CubeState,
        row: dict[str, object],
        *,
        begin: float,
        request_index: int,
        reused_process: bool,
    ) -> SolverResult:
        if row.get("status") != "ok":
            row_status = str(row.get("status", "error"))
            status = "timeout" if row_status == "timeout" else "failed"
            process_alive = self._process is not None and self._process.poll() is None
            if status == "timeout":
                summary = (
                    "RubikOptimal resident row timed out without stopping the resident process; "
                    "resident_timeout_without_process_stop=true; "
                )
            else:
                summary = "RubikOptimal resident row failed; "
            return SolverResult(
                solver_name="rubikoptimal_external",
                input_state=cube.to_facelets(),
                solution_moves=[],
                solution_length=None,
                metric="HTM",
                runtime_seconds=float(row.get("child_runtime_seconds", time.perf_counter() - begin)),
                expanded_nodes=None,
                generated_nodes=None,
                table_bytes=rubikoptimal_table_bytes(self.selected_table_dir),
                status=status,
                is_verified=False,
                notes=(
                    f"{summary}selected_backend=rubikoptimal_resident; "
                    f"backend_solver=rubikoptimal_external; error={row.get('error')}; "
                    f"child_timeout_seconds={row.get('timeout_seconds')}; "
                    f"resident_request_index={request_index}; resident_start_count={self.start_count}; "
                    f"resident_process_alive={str(process_alive).lower()}"
                ),
            )
        solution = list(row["moves"])
        verification = verify_solution(cube, solution)
        return SolverResult(
            solver_name="rubikoptimal_external",
            input_state=cube.to_facelets(),
            solution_moves=solution,
            solution_length=int(row["length"]) if verification.ok else None,
            metric="HTM",
            runtime_seconds=time.perf_counter() - begin,
            expanded_nodes=None,
            generated_nodes=None,
            table_bytes=rubikoptimal_table_bytes(self.selected_table_dir),
            status="exact" if verification.ok else "failed",
            is_verified=verification.ok,
            notes=(
                "resident RubikOptimal backend; selected_backend=rubikoptimal_resident; "
                "backend_solver=rubikoptimal_external; input_mode=facelet_state; "
                f"raw_solution={row.get('raw_solution')}; table_dir={self.selected_table_dir}; "
                f"table_load_seconds={row.get('table_load_seconds')}; "
                f"resident_table_load_seconds={self._table_load_seconds}; "
                f"resident_request_index={request_index}; resident_start_count={self.start_count}; "
                f"resident_process_reused={str(reused_process).lower()}"
            ),
        )


def solve_rubikoptimal_external(
    cube: CubeState,
    *,
    timeout_seconds: float = 300.0,
    executable: str | Path | None = None,
    package_path: str | Path | None = None,
    table_dir: str | Path | None = None,
    root: Path | None = None,
) -> SolverResult:
    """Solve a cube optimally through external RubikOptimal, if tables exist."""

    root = root or repository_root()
    begin = time.perf_counter()
    selected_table_dir = Path(table_dir) if table_dir is not None else default_rubikoptimal_table_dir(root)
    table_bytes = rubikoptimal_table_bytes(selected_table_dir)

    if cube.is_solved():
        return SolverResult(
            solver_name="rubikoptimal_external",
            input_state=cube.to_facelets(),
            solution_moves=[],
            solution_length=0,
            metric="HTM",
            runtime_seconds=time.perf_counter() - begin,
            expanded_nodes=None,
            generated_nodes=None,
            table_bytes=table_bytes,
            status="exact",
            is_verified=True,
            notes=(
                "external RubikOptimal backend not invoked for solved state; "
                "selected_backend=rubikoptimal_external; backend_solver=rubikoptimal_external"
            ),
        )

    if not rubikoptimal_tables_ready(selected_table_dir):
        missing = _missing_table_names(selected_table_dir)
        return SolverResult(
            solver_name="rubikoptimal_external",
            input_state=cube.to_facelets(),
            solution_moves=[],
            solution_length=None,
            metric="HTM",
            runtime_seconds=time.perf_counter() - begin,
            expanded_nodes=None,
            generated_nodes=None,
            table_bytes=table_bytes,
            status="not_applicable",
            is_verified=False,
            notes=(
                "RubikOptimal tables are not ready in the dedicated table directory; "
                "selected_backend=rubikoptimal_external; backend_solver=rubikoptimal_external; "
                "run scripts/generate_rubikoptimal_tables.py. "
                f"missing_or_wrong={','.join(missing)}; table_dir={selected_table_dir}"
            ),
        )

    selected_executable = find_rubikoptimal_executable(executable)
    if selected_executable is None:
        return SolverResult(
            solver_name="rubikoptimal_external",
            input_state=cube.to_facelets(),
            solution_moves=[],
            solution_length=None,
            metric="HTM",
            runtime_seconds=time.perf_counter() - begin,
            expanded_nodes=None,
            generated_nodes=None,
            table_bytes=table_bytes,
            status="not_applicable",
            is_verified=False,
            notes=(
                "RubikOptimal Python executable not found; "
                "selected_backend=rubikoptimal_external; backend_solver=rubikoptimal_external; "
                "set RUBIKOPTIMAL_PYTHON or install pypy3"
            ),
        )

    pythonpath = str(package_path) if package_path is not None else default_rubikoptimal_pythonpath()
    if pythonpath is None:
        return SolverResult(
            solver_name="rubikoptimal_external",
            input_state=cube.to_facelets(),
            solution_moves=[],
            solution_length=None,
            metric="HTM",
            runtime_seconds=time.perf_counter() - begin,
            expanded_nodes=None,
            generated_nodes=None,
            table_bytes=table_bytes,
            status="not_applicable",
            is_verified=False,
            notes=(
                "RubikOptimal package not found; "
                "selected_backend=rubikoptimal_external; backend_solver=rubikoptimal_external; "
                "install the RubikOptimal package or set RUBIKOPTIMAL_PACKAGE_PATH"
            ),
        )

    code = (
        "import json, sys\n"
        "import optimal.solver as solver\n"
        "result = solver.solve(sys.argv[1])\n"
        f"print({_RESULT_MARKER!r} + json.dumps({{'result': result}}))\n"
    )
    try:
        completed = subprocess.run(
            [str(selected_executable), "-c", code, cube.to_facelets()],
            cwd=selected_table_dir,
            env=_rubikoptimal_env(pythonpath),
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return SolverResult(
            solver_name="rubikoptimal_external",
            input_state=cube.to_facelets(),
            solution_moves=[],
            solution_length=None,
            metric="HTM",
            runtime_seconds=time.perf_counter() - begin,
            expanded_nodes=None,
            generated_nodes=None,
            table_bytes=rubikoptimal_table_bytes(selected_table_dir),
            status="timeout",
            is_verified=False,
            notes=(
                "RubikOptimal timed out; "
                "selected_backend=rubikoptimal_external; backend_solver=rubikoptimal_external; "
                f"timeout_seconds={timeout_seconds}; partial_output={exc.stdout or ''}"
            ),
        )

    output = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
    if completed.returncode != 0:
        return SolverResult(
            solver_name="rubikoptimal_external",
            input_state=cube.to_facelets(),
            solution_moves=[],
            solution_length=None,
            metric="HTM",
            runtime_seconds=time.perf_counter() - begin,
            expanded_nodes=None,
            generated_nodes=None,
            table_bytes=rubikoptimal_table_bytes(selected_table_dir),
            status="failed",
            is_verified=False,
            notes=(
                "RubikOptimal exited non-zero; "
                "selected_backend=rubikoptimal_external; backend_solver=rubikoptimal_external; "
                f"return_code={completed.returncode}; output={output.strip()}"
            ),
        )

    try:
        solution, length, raw_solution = parse_rubikoptimal_process_output(output)
        verification = verify_solution(cube, solution)
    except Exception as exc:
        return SolverResult(
            solver_name="rubikoptimal_external",
            input_state=cube.to_facelets(),
            solution_moves=[],
            solution_length=None,
            metric="HTM",
            runtime_seconds=time.perf_counter() - begin,
            expanded_nodes=None,
            generated_nodes=None,
            table_bytes=rubikoptimal_table_bytes(selected_table_dir),
            status="failed",
            is_verified=False,
            notes=(
                "RubikOptimal parse/verification failed; "
                "selected_backend=rubikoptimal_external; backend_solver=rubikoptimal_external; "
                f"error={exc}; output={output.strip()}"
            ),
        )

    return SolverResult(
        solver_name="rubikoptimal_external",
        input_state=cube.to_facelets(),
        solution_moves=solution,
        solution_length=length if verification.ok else None,
        metric="HTM",
        runtime_seconds=time.perf_counter() - begin,
        expanded_nodes=None,
        generated_nodes=None,
        table_bytes=rubikoptimal_table_bytes(selected_table_dir),
        status="exact" if verification.ok else "failed",
        is_verified=verification.ok,
        notes=(
            "external RubikOptimal backend; selected_backend=rubikoptimal_external; "
            "backend_solver=rubikoptimal_external; input_mode=facelet_state; "
            f"raw_solution={raw_solution}; executable={selected_executable}; "
            f"table_dir={selected_table_dir}; package_path={pythonpath}"
        ),
    )


def solve_rubikoptimal_external_batch(
    cubes: list[CubeState],
    *,
    timeout_seconds: float = 300.0,
    executable: str | Path | None = None,
    package_path: str | Path | None = None,
    table_dir: str | Path | None = None,
    root: Path | None = None,
) -> list[SolverResult]:
    """Solve multiple cubes through one resident RubikOptimal table load."""

    root = root or repository_root()
    begin = time.perf_counter()
    selected_table_dir = Path(table_dir) if table_dir is not None else default_rubikoptimal_table_dir(root)
    table_bytes = rubikoptimal_table_bytes(selected_table_dir)
    results: list[SolverResult | None] = [None] * len(cubes)
    pending: list[dict[str, object]] = []

    for index, cube in enumerate(cubes):
        if cube.is_solved():
            results[index] = SolverResult(
                solver_name="rubikoptimal_external",
                input_state=cube.to_facelets(),
                solution_moves=[],
                solution_length=0,
                metric="HTM",
                runtime_seconds=time.perf_counter() - begin,
                expanded_nodes=None,
                generated_nodes=None,
                table_bytes=table_bytes,
                status="exact",
                is_verified=True,
                notes=(
                    "external RubikOptimal batch backend not invoked for solved state; "
                    "selected_backend=rubikoptimal_external_batch; backend_solver=rubikoptimal_external"
                ),
            )
        else:
            pending.append({"index": index, "state": cube.to_facelets()})

    if not pending:
        return [result for result in results if result is not None]

    if not rubikoptimal_tables_ready(selected_table_dir):
        missing = _missing_table_names(selected_table_dir)
        for item in pending:
            index = int(item["index"])
            cube = cubes[index]
            results[index] = SolverResult(
                solver_name="rubikoptimal_external",
                input_state=cube.to_facelets(),
                solution_moves=[],
                solution_length=None,
                metric="HTM",
                runtime_seconds=time.perf_counter() - begin,
                expanded_nodes=None,
                generated_nodes=None,
                table_bytes=table_bytes,
                status="not_applicable",
                is_verified=False,
                notes=(
                    "RubikOptimal tables are not ready in the dedicated table directory; "
                    "selected_backend=rubikoptimal_external_batch; backend_solver=rubikoptimal_external; "
                    "run scripts/generate_rubikoptimal_tables.py. "
                    f"missing_or_wrong={','.join(missing)}; table_dir={selected_table_dir}"
                ),
            )
        return [result for result in results if result is not None]

    selected_executable = find_rubikoptimal_executable(executable)
    if selected_executable is None:
        for item in pending:
            index = int(item["index"])
            cube = cubes[index]
            results[index] = SolverResult(
                solver_name="rubikoptimal_external",
                input_state=cube.to_facelets(),
                solution_moves=[],
                solution_length=None,
                metric="HTM",
                runtime_seconds=time.perf_counter() - begin,
                expanded_nodes=None,
                generated_nodes=None,
                table_bytes=table_bytes,
                status="not_applicable",
                is_verified=False,
                notes=(
                    "RubikOptimal Python executable not found; "
                    "selected_backend=rubikoptimal_external_batch; backend_solver=rubikoptimal_external; "
                    "set RUBIKOPTIMAL_PYTHON or install pypy3"
                ),
            )
        return [result for result in results if result is not None]

    pythonpath = str(package_path) if package_path is not None else default_rubikoptimal_pythonpath()
    if pythonpath is None:
        for item in pending:
            index = int(item["index"])
            cube = cubes[index]
            results[index] = SolverResult(
                solver_name="rubikoptimal_external",
                input_state=cube.to_facelets(),
                solution_moves=[],
                solution_length=None,
                metric="HTM",
                runtime_seconds=time.perf_counter() - begin,
                expanded_nodes=None,
                generated_nodes=None,
                table_bytes=table_bytes,
                status="not_applicable",
                is_verified=False,
                notes=(
                    "RubikOptimal package not found; "
                    "selected_backend=rubikoptimal_external_batch; backend_solver=rubikoptimal_external; "
                    "install the RubikOptimal package or set RUBIKOPTIMAL_PACKAGE_PATH"
                ),
            )
        return [result for result in results if result is not None]

    def annotate_batch_result(
        result: SolverResult,
        *,
        index: int,
        row_timeout_seconds: float,
    ) -> SolverResult:
        batch_wall_seconds = time.perf_counter() - begin
        return SolverResult(
            solver_name=result.solver_name,
            input_state=result.input_state,
            solution_moves=result.solution_moves,
            solution_length=result.solution_length,
            metric=result.metric,
            runtime_seconds=result.runtime_seconds,
            expanded_nodes=result.expanded_nodes,
            generated_nodes=result.generated_nodes,
            table_bytes=result.table_bytes,
            status=result.status,
            is_verified=result.is_verified,
            notes=(
                "external RubikOptimal batch backend; selected_backend=rubikoptimal_external_batch; "
                "backend_solver=rubikoptimal_external; batch_uses_resident_session=true; "
                f"batch_row_index={index}; batch_row_timeout_seconds={row_timeout_seconds}; "
                f"batch_global_timeout_seconds={timeout_seconds}; batch_wall_seconds={batch_wall_seconds}; "
                f"executable={selected_executable}; table_dir={selected_table_dir}; package_path={pythonpath}; "
                f"resident_notes={result.notes}"
            ),
        )

    def exhausted_batch_result(
        cube: CubeState,
        *,
        index: int,
        row_begin: float,
    ) -> SolverResult:
        batch_wall_seconds = time.perf_counter() - begin
        return SolverResult(
            solver_name="rubikoptimal_external",
            input_state=cube.to_facelets(),
            solution_moves=[],
            solution_length=None,
            metric="HTM",
            runtime_seconds=time.perf_counter() - row_begin,
            expanded_nodes=None,
            generated_nodes=None,
            table_bytes=rubikoptimal_table_bytes(selected_table_dir),
            status="timeout",
            is_verified=False,
            notes=(
                "RubikOptimal batch row skipped because the global resident batch budget was exhausted; "
                "selected_backend=rubikoptimal_external_batch; backend_solver=rubikoptimal_external; "
                "batch_uses_resident_session=true; "
                f"batch_row_index={index}; batch_row_timeout_seconds=0.0; "
                f"batch_global_timeout_seconds={timeout_seconds}; batch_wall_seconds={batch_wall_seconds}; "
                f"executable={selected_executable}; table_dir={selected_table_dir}; package_path={pythonpath}"
            ),
        )

    total_timeout_seconds = max(0.0, float(timeout_seconds))
    per_row_timeout_seconds = total_timeout_seconds / max(1, len(pending))
    deadline = begin + total_timeout_seconds
    with RubikOptimalOracleSession(
        executable=selected_executable,
        package_path=pythonpath,
        table_dir=selected_table_dir,
        root=root,
    ) as session:
        startup_timeout_seconds = max(0.0, deadline - time.perf_counter())
        start_result = session._ensure_started(timeout_seconds=startup_timeout_seconds)
        if start_result is not None:
            batch_wall_seconds = time.perf_counter() - begin
            for item in pending:
                index = int(item["index"])
                cube = cubes[index]
                results[index] = SolverResult(
                    solver_name="rubikoptimal_external",
                    input_state=cube.to_facelets(),
                    solution_moves=[],
                    solution_length=None,
                    metric="HTM",
                    runtime_seconds=batch_wall_seconds,
                    expanded_nodes=None,
                    generated_nodes=None,
                    table_bytes=start_result.get("table_bytes"),
                    status=str(start_result["status"]),
                    is_verified=False,
                    notes=(
                        "RubikOptimal resident batch startup failed; "
                        "selected_backend=rubikoptimal_external_batch; backend_solver=rubikoptimal_external; "
                        "batch_uses_resident_session=true; "
                        f"batch_global_timeout_seconds={timeout_seconds}; "
                        f"batch_wall_seconds={batch_wall_seconds}; "
                        f"executable={selected_executable}; table_dir={selected_table_dir}; "
                        f"package_path={pythonpath}; startup_notes={start_result['notes']}"
                    ),
                )
            return [result for result in results if result is not None]

        for item in pending:
            index = int(item["index"])
            cube = cubes[index]
            row_begin = time.perf_counter()
            remaining_seconds = max(0.0, deadline - row_begin)
            row_timeout_seconds = min(per_row_timeout_seconds, remaining_seconds)
            if row_timeout_seconds <= 0.0:
                results[index] = exhausted_batch_result(cube, index=index, row_begin=row_begin)
                continue
            result = session.solve(cube, timeout_seconds=row_timeout_seconds)
            results[index] = annotate_batch_result(
                result,
                index=index,
                row_timeout_seconds=row_timeout_seconds,
            )

    return [result for result in results if result is not None]


def _rubikoptimal_race_rotations(
    *,
    variant_count: int,
    include_identity: bool,
) -> list[CubeRotation]:
    rotations: list[CubeRotation] = []
    if include_identity:
        rotations.extend(rotation for rotation in CUBE_ROTATIONS if rotation.is_identity)
    rotations.extend(
        rotation for rotation in CUBE_ROTATIONS if not rotation.is_identity
    )
    limit = max(0, int(variant_count)) + (1 if include_identity else 0)
    return rotations[:limit]


def solve_rubikoptimal_external_rotational_race(
    cube: CubeState,
    *,
    variant_count: int,
    include_identity: bool = False,
    rotations: list[CubeRotation] | None = None,
    rotation_order_note: str = "rubikoptimal_rotational_h48_lower_bound_rotation_order=false",
    timeout_seconds: float = 300.0,
    max_concurrency: int | None = None,
    executable: str | Path | None = None,
    package_path: str | Path | None = None,
    table_dir: str | Path | None = None,
    root: Path | None = None,
) -> SolverResult:
    """Race RubikOptimal over whole-cube rotations and verify the mapped result.

    The batch helper amortizes one table load but is sequential.  This helper is
    for hard-tail rows where orientation can dominate wall time: it starts a
    bounded number of independent RubikOptimal resident sessions, accepts only
    the first exact rotated solution that maps back and verifies on the original
    cube, then closes the remaining sessions.
    """

    root = root or repository_root()
    begin = time.perf_counter()
    selected_table_dir = Path(table_dir) if table_dir is not None else default_rubikoptimal_table_dir(root)
    table_bytes = rubikoptimal_table_bytes(selected_table_dir)
    rotations = (
        list(rotations)
        if rotations is not None
        else _rubikoptimal_race_rotations(
            variant_count=variant_count,
            include_identity=include_identity,
        )
    )

    if cube.is_solved():
        return SolverResult(
            solver_name="rubikoptimal_rotational_race",
            input_state=cube.to_facelets(),
            solution_moves=[],
            solution_length=0,
            metric="HTM",
            runtime_seconds=time.perf_counter() - begin,
            expanded_nodes=None,
            generated_nodes=None,
            table_bytes=table_bytes,
            status="exact",
            is_verified=True,
            notes=(
                "RubikOptimal rotational race not invoked for solved state; "
                "selected_backend=rubikoptimal_rotational_race; backend_solver=rubikoptimal_external"
            ),
        )

    if not rotations:
        return SolverResult(
            solver_name="rubikoptimal_rotational_race",
            input_state=cube.to_facelets(),
            solution_moves=[],
            solution_length=None,
            metric="HTM",
            runtime_seconds=time.perf_counter() - begin,
            expanded_nodes=None,
            generated_nodes=None,
            table_bytes=table_bytes,
            status="not_applicable",
            is_verified=False,
            notes="RubikOptimal rotational race has no configured rotations",
        )

    if not rubikoptimal_tables_ready(selected_table_dir):
        missing = _missing_table_names(selected_table_dir)
        return SolverResult(
            solver_name="rubikoptimal_rotational_race",
            input_state=cube.to_facelets(),
            solution_moves=[],
            solution_length=None,
            metric="HTM",
            runtime_seconds=time.perf_counter() - begin,
            expanded_nodes=None,
            generated_nodes=None,
            table_bytes=table_bytes,
            status="not_applicable",
            is_verified=False,
            notes=(
                "RubikOptimal tables are not ready for rotational race; "
                "selected_backend=rubikoptimal_rotational_race; backend_solver=rubikoptimal_external; "
                f"missing_or_wrong={','.join(missing)}; table_dir={selected_table_dir}"
            ),
        )

    selected_executable = find_rubikoptimal_executable(executable)
    if selected_executable is None:
        return SolverResult(
            solver_name="rubikoptimal_rotational_race",
            input_state=cube.to_facelets(),
            solution_moves=[],
            solution_length=None,
            metric="HTM",
            runtime_seconds=time.perf_counter() - begin,
            expanded_nodes=None,
            generated_nodes=None,
            table_bytes=table_bytes,
            status="not_applicable",
            is_verified=False,
            notes=(
                "RubikOptimal Python executable not found for rotational race; "
                "selected_backend=rubikoptimal_rotational_race; backend_solver=rubikoptimal_external"
            ),
        )

    selected_package_path = (
        str(package_path) if package_path is not None else default_rubikoptimal_pythonpath()
    )
    if selected_package_path is None:
        return SolverResult(
            solver_name="rubikoptimal_rotational_race",
            input_state=cube.to_facelets(),
            solution_moves=[],
            solution_length=None,
            metric="HTM",
            runtime_seconds=time.perf_counter() - begin,
            expanded_nodes=None,
            generated_nodes=None,
            table_bytes=table_bytes,
            status="not_applicable",
            is_verified=False,
            notes=(
                "RubikOptimal package not found for rotational race; "
                "selected_backend=rubikoptimal_rotational_race; backend_solver=rubikoptimal_external"
            ),
        )

    rotation_count = len(rotations)
    concurrency = (
        rotation_count
        if max_concurrency is None or max_concurrency <= 0
        else max(1, min(rotation_count, int(max_concurrency)))
    )
    global_timeout_seconds = max(0.0, float(timeout_seconds))
    deadline = begin + global_timeout_seconds
    pending_rotations: deque[CubeRotation] = deque(rotations)
    queue_lock = threading.Lock()
    result_lock = threading.Lock()
    stop_event = threading.Event()
    sessions: list[RubikOptimalOracleSession] = []
    sessions_lock = threading.Lock()
    completed_statuses: list[tuple[str, str]] = []
    timed_out_rotations: list[str] = []
    row_timeouts: list[tuple[str, float]] = []
    first_non_exact: SolverResult | None = None
    setup_errors: list[str] = []
    winner: tuple[CubeRotation, SolverResult, list[str]] | None = None
    global_timeout_expired = False

    def claim_next_rotation() -> CubeRotation | None:
        nonlocal global_timeout_expired
        with queue_lock:
            if stop_event.is_set() or not pending_rotations:
                return None
            if time.perf_counter() >= deadline:
                global_timeout_expired = True
                return None
            return pending_rotations.popleft()

    def close_losing_sessions(winning_session: RubikOptimalOracleSession | None = None) -> None:
        with sessions_lock:
            open_sessions = list(sessions)
        for session in open_sessions:
            if session is winning_session:
                continue
            session.close()

    def worker(_worker_index: int) -> None:
        nonlocal first_non_exact, winner, global_timeout_expired
        try:
            session = RubikOptimalOracleSession(
                executable=selected_executable,
                package_path=selected_package_path,
                table_dir=selected_table_dir,
                root=root,
            )
        except Exception as exc:  # pragma: no cover - defensive constructor guard
            with result_lock:
                setup_errors.append(f"worker_session_start:{exc!r}")
            return
        try:
            with sessions_lock:
                sessions.append(session)
            while not stop_event.is_set():
                rotation = claim_next_rotation()
                if rotation is None:
                    return
                row_timeout_seconds = max(0.0, deadline - time.perf_counter())
                with result_lock:
                    row_timeouts.append((rotation.name, row_timeout_seconds))
                if row_timeout_seconds <= 0.0:
                    with result_lock:
                        global_timeout_expired = True
                        timed_out_rotations.append(rotation.name)
                        completed_statuses.append((rotation.name, "timeout"))
                    return
                try:
                    rotated_result = session.solve(
                        rotation.transform_cube(cube),
                        timeout_seconds=row_timeout_seconds,
                    )
                except Exception as exc:  # pragma: no cover - defensive worker guard
                    with result_lock:
                        setup_errors.append(f"{rotation.name}:{exc!r}")
                        completed_statuses.append((rotation.name, "failed"))
                    continue

                with result_lock:
                    completed_statuses.append((rotation.name, rotated_result.status))
                    if rotated_result.status == "timeout":
                        timed_out_rotations.append(rotation.name)
                    if first_non_exact is None and rotated_result.status != "exact":
                        first_non_exact = rotated_result
                if rotated_result.status != "exact" or not rotated_result.is_verified:
                    continue

                solution = rotation.inverse_transform_sequence(rotated_result.solution_moves)
                verification = verify_solution(cube, solution)
                if not verification.ok:
                    with result_lock:
                        setup_errors.append(f"{rotation.name}:mapped_solution_failed_verification")
                    continue

                with result_lock:
                    if winner is None:
                        winner = (rotation, rotated_result, solution)
                        stop_event.set()
                close_losing_sessions(winning_session=session)
                return
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(worker, index) for index in range(concurrency)]
        wait(futures)
        for future in futures:
            try:
                future.result()
            except Exception as exc:  # pragma: no cover - defensive worker guard
                setup_errors.append(f"worker_unhandled:{exc!r}")
    close_losing_sessions()

    if winner is not None:
        completed_rotation, rotated_result, solution = winner
        return SolverResult(
            solver_name="rubikoptimal_rotational_race",
            input_state=cube.to_facelets(),
            solution_moves=solution,
            solution_length=len(solution),
            metric=rotated_result.metric,
            runtime_seconds=time.perf_counter() - begin,
            expanded_nodes=rotated_result.expanded_nodes,
            generated_nodes=rotated_result.generated_nodes,
            table_bytes=rubikoptimal_table_bytes(selected_table_dir),
            status="exact",
            is_verified=True,
            notes=(
                "RubikOptimal rotational race; "
                "selected_backend=rubikoptimal_rotational_race; "
                "backend_solver=rubikoptimal_external; "
                "resident_worker_pool=true; "
                "exactness_policy=first_rotated_exact_solution_mapped_back_and_verified; "
                f"identity_rotation_included={include_identity}; "
                f"symmetry_variants={rotation_count}; "
                f"max_concurrency={concurrency}; "
                f"resident_worker_count={concurrency}; "
                f"resident_session_count={len(sessions)}; "
                f"global_timeout_seconds={global_timeout_seconds}; "
                f"global_timeout_expired={global_timeout_expired}; "
                f"pending_rotations_not_started={len(pending_rotations)}; "
                f"row_timeouts={row_timeouts}; "
                f"selected_rotation={completed_rotation.name}; "
                f"completed_statuses={completed_statuses}; "
                f"timed_out_rotations={timed_out_rotations}; "
                f"rotated_runtime_seconds={rotated_result.runtime_seconds:.6f}; "
                f"rotated_solution_length={rotated_result.solution_length}; "
                f"{rotation_order_note}; "
                f"rotated_notes={rotated_result.notes}; "
                f"setup_errors={setup_errors}"
            ),
        )

    status = first_non_exact.status if first_non_exact is not None else "failed"
    if timed_out_rotations or global_timeout_expired:
        status = "timeout"
    return SolverResult(
        solver_name="rubikoptimal_rotational_race",
        input_state=cube.to_facelets(),
        solution_moves=[],
        solution_length=None,
        metric="HTM",
        runtime_seconds=time.perf_counter() - begin,
        expanded_nodes=first_non_exact.expanded_nodes if first_non_exact is not None else None,
        generated_nodes=first_non_exact.generated_nodes if first_non_exact is not None else None,
        table_bytes=rubikoptimal_table_bytes(selected_table_dir),
        status=status,
        is_verified=False,
        notes=(
            "RubikOptimal rotational race finished without a verified exact solution; "
            "selected_backend=rubikoptimal_rotational_race; backend_solver=rubikoptimal_external; "
            "resident_worker_pool=true; "
            f"identity_rotation_included={include_identity}; "
            f"symmetry_variants={rotation_count}; max_concurrency={concurrency}; "
            f"resident_worker_count={concurrency}; resident_session_count={len(sessions)}; "
            f"global_timeout_seconds={global_timeout_seconds}; "
            f"global_timeout_expired={global_timeout_expired}; "
            f"pending_rotations_not_started={len(pending_rotations)}; "
            f"row_timeouts={row_timeouts}; "
            f"completed_statuses={completed_statuses}; "
            f"timed_out_rotations={timed_out_rotations}; setup_errors={setup_errors}; "
            f"{rotation_order_note}; "
            f"first_non_exact_notes={first_non_exact.notes if first_non_exact is not None else ''}"
        ),
    )

"""External Nissy optimal-solver bridge.

This module intentionally treats Nissy as an external reference backend. It is
not part of the in-repository Korf implementation, but it can provide exact HTM
solutions when a local Nissy binary and its pruning tables are available.
"""

from __future__ import annotations

import functools
import os
import json
import re
import selectors
import signal
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from rubik_optimal.cube import CubeState
from rubik_optimal.moves import inverse_sequence, parse_sequence
from rubik_optimal.solvers.base import SolverResult
from rubik_optimal.solvers.h48_native import cube_to_nissy_string
from rubik_optimal.solvers.kociemba import solve_kociemba_adapter
from rubik_optimal.tables.h48 import canonical_h48_solver, h48_table_path
from rubik_optimal.verify import verify_solution


_FINAL_LINE = re.compile(r"^(?P<moves>.*?)\s*\((?P<length>\d+)\)\s*$")
_NISSY_OPTIMAL_TABLE = "pt_nxopt31_HTM"
_NISSY_OPTIMAL_REQUIRED_TABLES = ("pt_nxopt31_HTM", "pt_corners_HTM")
_DEFAULT_NISSY_CORE_PYTHON_MAX_TABLE_BYTES = 512 * 1024 * 1024
_NISSY2_VERSION_CFLAG = '-DVERSION="2.0.8"'


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _find_binary(root: Path, binary_path: str | Path | None) -> Path | None:
    if binary_path is not None:
        path = Path(binary_path)
        return path if path.exists() else None
    env_path = os.environ.get("NISSY_BINARY")
    if env_path:
        path = Path(env_path)
        return path if path.exists() else None
    local = root / ".codex_external" / "nissy-2.0.8" / "nissy"
    if local.exists():
        return local
    found = shutil.which("nissy")
    return Path(found) if found else None


def _find_nissy_core_shell(root: Path, binary_path: str | Path | None) -> Path | None:
    if binary_path is not None:
        path = Path(binary_path)
        return path if path.exists() else None
    env_path = os.environ.get("NISSY_CORE_BINARY")
    if env_path:
        path = Path(env_path)
        return path if path.exists() else None
    local = root / ".codex_external" / "nissy-core" / "run"
    if local.exists():
        return local
    found = shutil.which("nissy-core")
    return Path(found) if found else None


def _default_nissy_core_module_root(root: Path) -> Path:
    return root / ".codex_external" / "nissy-core"


def _nissy_core_python_module_available(module_root: Path) -> bool:
    python_dir = module_root / "python"
    return (
        (python_dir / "nissy.py").exists()
        or (python_dir / "nissy.so").exists()
        or any(p.name.startswith("nissy.") and p.suffix == ".so" for p in python_dir.glob("nissy*.so"))
    )


@functools.lru_cache(maxsize=8)
def _nissy_core_python_supports_solve_buffer(module_root: Path) -> bool:
    if not _nissy_core_python_module_available(module_root):
        return False
    script = (
        "import sys\n"
        "module_root = sys.argv[1]\n"
        "sys.path.insert(0, module_root)\n"
        "sys.path.insert(0, module_root + '/python')\n"
        "try:\n"
        "    import nissy\n"
        "except Exception:\n"
        "    raise SystemExit(2)\n"
        "print('1' if hasattr(nissy, 'solve_buffer') else '0')\n"
    )
    try:
        completed = subprocess.run(
            [sys.executable, "-c", script, str(module_root)],
            text=True,
            capture_output=True,
            timeout=5.0,
            check=False,
        )
    except Exception:
        return False
    return completed.returncode == 0 and completed.stdout.strip().splitlines()[-1:] == ["1"]


def _nissy_core_python_enabled_for_table(table_path: Path, module_root: Path) -> bool:
    mode = os.environ.get("RUBIK_OPTIMAL_NISSY_CORE_PYTHON", "auto").strip().lower()
    if mode in {"0", "false", "no", "off", "disabled"}:
        return False
    if mode in {"1", "true", "yes", "on", "force"}:
        return True
    if _nissy_core_python_supports_solve_buffer(module_root):
        return True
    raw_limit = os.environ.get("RUBIK_OPTIMAL_NISSY_CORE_PYTHON_MAX_TABLE_BYTES")
    try:
        limit = int(raw_limit) if raw_limit is not None else _DEFAULT_NISSY_CORE_PYTHON_MAX_TABLE_BYTES
    except ValueError:
        limit = _DEFAULT_NISSY_CORE_PYTHON_MAX_TABLE_BYTES
    if limit < 0:
        return True
    return table_path.stat().st_size <= limit


def _default_data_dir(root: Path, data_dir: str | Path | None) -> Path | None:
    if data_dir is not None:
        return Path(data_dir)
    env_path = os.environ.get("NISSYDATA")
    if env_path:
        return Path(env_path)
    local = root / ".codex_external" / "nissy_data"
    return local if local.exists() else None


def _directory_size(path: Path | None) -> int | None:
    if path is None or not path.exists():
        return None
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _table_path(data_dir: Path | None, table_name: str) -> Path | None:
    if data_dir is None:
        return None
    return data_dir / "tables" / table_name


def _nissy2_state_bridge_path(root: Path) -> Path:
    return root / "native" / "build" / "nissy2_state_bridge"


def _nissy2_state_bridge_source(root: Path) -> Path:
    return root / "native" / "nissy2_state_bridge" / "nissy2_state_bridge.c"


def _nissy2_vendor_source_dir(root: Path) -> Path:
    return root / ".codex_external" / "nissy-2.0.8" / "src"


def _nissy2_state_bridge_enabled() -> bool:
    mode = os.environ.get("RUBIK_OPTIMAL_NISSY2_STATE_BRIDGE", "auto").strip().lower()
    return mode not in {"0", "false", "no", "off", "disabled"}


def build_nissy2_state_bridge(*, root: Path | None = None, force: bool = False) -> Path:
    """Build the direct-state bridge for Nissy 2.x's public optimal backend."""

    root = root or _repository_root()
    bridge_source = _nissy2_state_bridge_source(root)
    vendor_source_dir = _nissy2_vendor_source_dir(root)
    output_path = _nissy2_state_bridge_path(root)
    if not bridge_source.exists():
        raise FileNotFoundError(f"missing Nissy 2.x state bridge source: {bridge_source}")
    if not vendor_source_dir.exists():
        raise FileNotFoundError(f"missing local Nissy 2.x source tree: {vendor_source_dir}")

    vendor_sources = sorted(
        path
        for path in vendor_source_dir.glob("*.c")
        if path.name != "shell.c"
    )
    sources = [bridge_source, *vendor_sources]
    if output_path.exists() and not force:
        output_mtime = output_path.stat().st_mtime
        if all(path.stat().st_mtime <= output_mtime for path in sources):
            return output_path

    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        os.environ.get("CC", "cc"),
        "-std=c99",
        "-pthread",
        "-pedantic",
        "-Wall",
        "-Wextra",
        "-Wno-unused-parameter",
        "-O3",
        _NISSY2_VERSION_CFLAG,
        "-I",
        str(vendor_source_dir),
        "-o",
        str(output_path),
        *[str(path) for path in sources],
    ]
    completed = subprocess.run(
        command,
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        output = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
        raise RuntimeError(f"Nissy 2.x state bridge build failed: {output.strip()}")
    return output_path


def _cubie_list(values: tuple[int, ...]) -> str:
    return ",".join(str(value) for value in values)


def _missing_nissy_tables(data_dir: Path | None, table_names: tuple[str, ...]) -> list[str]:
    if data_dir is None:
        return list(table_names)
    return [name for name in table_names if not (data_dir / "tables" / name).exists()]


def _representative_scramble(cube: CubeState, source_sequence: list[str] | tuple[str, ...] | str | None) -> tuple[list[str], str]:
    if cube.is_solved():
        return [], "solved"
    if source_sequence is not None:
        sequence = parse_sequence(source_sequence)
        if CubeState.from_sequence(sequence) == cube:
            return sequence, "source_sequence"

    seed = solve_kociemba_adapter(cube)
    if seed.status != "non_exact" or not seed.is_verified or not seed.solution_moves:
        raise RuntimeError(f"could not build representative scramble from verified seed solution: {seed.notes}")
    return inverse_sequence(seed.solution_moves), "inverse_verified_kociemba_solution"


def _parse_solution(output: str) -> tuple[list[str], int]:
    for line in reversed(output.splitlines()):
        match = _FINAL_LINE.match(line.strip())
        if not match:
            continue
        moves = parse_sequence(match.group("moves"))
        length = int(match.group("length"))
        if len(moves) != length:
            raise RuntimeError(f"Nissy length marker {length} disagrees with parsed move count {len(moves)}")
        return moves, length
    raise RuntimeError("Nissy output did not contain a final '(length)' solution line")


def _parse_plain_nissy_core_solution(output: str) -> tuple[list[str], int]:
    ignored_prefixes = (
        "[",
        "Reading tables",
        "Table file",
        "Cannot read data file",
        "Data written",
        "No solutions found",
        "Error",
        "---------",
        "Total time:",
    )
    for line in reversed(output.splitlines()):
        stripped = line.strip()
        if not stripped or stripped.startswith(ignored_prefixes):
            continue
        try:
            moves = parse_sequence(stripped)
        except Exception:
            continue
        return moves, len(moves)
    raise RuntimeError("nissy-core shell output did not contain a plain solution line")


def _parse_batch_solutions(output: str, expected_count: int) -> list[tuple[list[str], int]]:
    solutions = _parse_partial_batch_solutions(output)
    if len(solutions) != expected_count:
        raise RuntimeError(f"Nissy batch returned {len(solutions)} solution lines for {expected_count} inputs")
    return solutions


def _parse_partial_batch_solutions(output: str) -> list[tuple[list[str], int]]:
    solutions: list[tuple[list[str], int]] = []
    for line in output.splitlines():
        stripped = line.strip()
        if _FINAL_LINE.match(stripped):
            solutions.append(_parse_solution(stripped))
    return solutions


def _subprocess_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return str(value)


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except (AttributeError, ProcessLookupError, PermissionError):
        process.terminate()
    try:
        process.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (AttributeError, ProcessLookupError, PermissionError):
            process.kill()
        process.wait(timeout=1.0)


def _drain_pipe(pipe: object, chunks: list[bytes]) -> None:
    if pipe is None:
        return
    fd = pipe.fileno()
    while True:
        try:
            chunk = os.read(fd, 65536)
        except BlockingIOError:
            break
        except OSError:
            break
        if not chunk:
            break
        chunks.append(chunk)


def _run_text_process_streaming(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    input_text: str,
    timeout_seconds: float | None,
) -> tuple[int, str, str, bool]:
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    stdout_chunks: list[bytes] = []
    stderr_chunks: list[bytes] = []
    selector = selectors.DefaultSelector()
    try:
        if process.stdout is not None:
            os.set_blocking(process.stdout.fileno(), False)
            selector.register(process.stdout, selectors.EVENT_READ, stdout_chunks)
        if process.stderr is not None:
            os.set_blocking(process.stderr.fileno(), False)
            selector.register(process.stderr, selectors.EVENT_READ, stderr_chunks)
        if process.stdin is not None:
            try:
                process.stdin.write(input_text.encode())
                process.stdin.close()
            except BrokenPipeError:
                process.stdin.close()

        timed_out = False
        deadline = None if timeout_seconds is None else time.monotonic() + max(0.0, timeout_seconds)
        while selector.get_map():
            if deadline is None:
                wait_seconds = None
            else:
                wait_seconds = deadline - time.monotonic()
                if wait_seconds <= 0:
                    timed_out = True
                    break
            events = selector.select(wait_seconds)
            if not events:
                if deadline is not None and time.monotonic() >= deadline:
                    timed_out = True
                    break
                continue
            for key, _ in events:
                pipe = key.fileobj
                chunks = key.data
                try:
                    chunk = os.read(pipe.fileno(), 65536)
                except BlockingIOError:
                    continue
                if chunk:
                    chunks.append(chunk)
                else:
                    selector.unregister(pipe)

        if timed_out:
            _terminate_process_group(process)
        else:
            process.wait()
        _drain_pipe(process.stdout, stdout_chunks)
        _drain_pipe(process.stderr, stderr_chunks)
        return (
            int(process.returncode or 0),
            b"".join(stdout_chunks).decode(errors="replace"),
            b"".join(stderr_chunks).decode(errors="replace"),
            timed_out,
        )
    finally:
        selector.close()


def _solve_nissy_step_optimal(
    cube: CubeState,
    *,
    step: str,
    solver_name: str,
    required_table: str | None = None,
    source_sequence: list[str] | tuple[str, ...] | str | None = None,
    timeout_seconds: float = 300.0,
    threads: int = 8,
    binary_path: str | Path | None = None,
    data_dir: str | Path | None = None,
    root: Path | None = None,
) -> SolverResult:
    root = root or _repository_root()
    begin = time.perf_counter()
    selected_data_dir = _default_data_dir(root, data_dir)
    if cube.is_solved():
        return SolverResult(
            solver_name=solver_name,
            input_state=cube.to_facelets(),
            solution_moves=[],
            solution_length=0,
            metric="HTM",
            runtime_seconds=time.perf_counter() - begin,
            expanded_nodes=None,
            generated_nodes=None,
            table_bytes=_directory_size(selected_data_dir),
            status="exact",
            is_verified=True,
            notes=f"external Nissy `{step}` backend not invoked for solved state",
        )

    binary = _find_binary(root, binary_path)
    if binary is None:
        return SolverResult(
            solver_name=solver_name,
            input_state=cube.to_facelets(),
            solution_moves=[],
            solution_length=None,
            metric="HTM",
            runtime_seconds=time.perf_counter() - begin,
            expanded_nodes=None,
            generated_nodes=None,
            table_bytes=_directory_size(selected_data_dir),
            status="not_applicable",
            is_verified=False,
            notes="Nissy binary not found; set NISSY_BINARY or install nissy on PATH",
        )

    if required_table is not None:
        required_path = _table_path(selected_data_dir, required_table)
        if required_path is None or not required_path.exists():
            return SolverResult(
                solver_name=solver_name,
                input_state=cube.to_facelets(),
                solution_moves=[],
                solution_length=None,
                metric="HTM",
                runtime_seconds=time.perf_counter() - begin,
                expanded_nodes=None,
                generated_nodes=None,
                table_bytes=_directory_size(selected_data_dir),
                status="not_applicable",
                is_verified=False,
                notes=(
                    f"external Nissy `{step}` backend requires local pruning table "
                    f"{required_table}; run scripts/install_nissy_public_table.py"
                ),
            )

    try:
        scramble, scramble_source = _representative_scramble(cube, source_sequence)
        command = [
            str(binary),
            "solve",
            step,
            "-t",
            str(threads),
            "-o",
            "-n",
            "1",
            " ".join(scramble),
        ]
        env = os.environ.copy()
        if selected_data_dir is not None:
            env["NISSYDATA"] = str(selected_data_dir)
        completed = subprocess.run(
            command,
            cwd=root,
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
        output = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
        if completed.returncode != 0:
            raise RuntimeError(output.strip() or f"Nissy exited with status {completed.returncode}")
        solution, solution_length = _parse_solution(output)
        verification = verify_solution(cube, solution)
        status = "exact" if verification.ok else "failed"
        return SolverResult(
            solver_name=solver_name,
            input_state=cube.to_facelets(),
            solution_moves=solution,
            solution_length=solution_length if verification.ok else None,
            metric="HTM",
            runtime_seconds=time.perf_counter() - begin,
            expanded_nodes=None,
            generated_nodes=None,
            table_bytes=_directory_size(selected_data_dir),
            status=status,
            is_verified=verification.ok,
            notes=(
                f"external Nissy `solve {step} -o` backend; "
                "input_mode=representative_scramble; "
                f"source_sequence_provided={source_sequence is not None}; "
                f"scramble_source={scramble_source}; threads={threads}; "
                f"required_table={required_table or 'none'}; "
                f"return_code={completed.returncode}"
            ),
        )
    except subprocess.TimeoutExpired as exc:
        return SolverResult(
            solver_name=solver_name,
            input_state=cube.to_facelets(),
            solution_moves=[],
            solution_length=None,
            metric="HTM",
            runtime_seconds=time.perf_counter() - begin,
            expanded_nodes=None,
            generated_nodes=None,
            table_bytes=_directory_size(_default_data_dir(root, data_dir)),
            status="timeout",
            is_verified=False,
            notes=f"external Nissy `{step}` timed out after {timeout_seconds}s; partial_output={exc.stdout or ''}",
        )
    except Exception as exc:
        return SolverResult(
            solver_name=solver_name,
            input_state=cube.to_facelets(),
            solution_moves=[],
            solution_length=None,
            metric="HTM",
            runtime_seconds=time.perf_counter() - begin,
            expanded_nodes=None,
            generated_nodes=None,
            table_bytes=_directory_size(_default_data_dir(root, data_dir)),
            status="failed",
            is_verified=False,
            notes=str(exc),
        )


def _result_for_status(
    cube: CubeState,
    *,
    solver_name: str,
    status: str,
    runtime_seconds: float,
    table_bytes: int | None,
    notes: str,
) -> SolverResult:
    return SolverResult(
        solver_name=solver_name,
        input_state=cube.to_facelets(),
        solution_moves=[],
        solution_length=None,
        metric="HTM",
        runtime_seconds=runtime_seconds,
        expanded_nodes=None,
        generated_nodes=None,
        table_bytes=table_bytes,
        status=status,
        is_verified=False,
        notes=notes,
    )


class _NissyCorePythonUnavailable(RuntimeError):
    pass


class NissyCoreDirectPythonSession:
    """Resident nissy-core Python worker that loads table data once."""

    def __init__(
        self,
        *,
        solver: str,
        table_path: Path,
        threads: int,
        max_depth: int,
        root: Path,
        module_root: Path | None = None,
        startup_timeout_seconds: float = 30.0,
    ) -> None:
        self.solver = solver
        self.table_path = table_path
        self.threads = max(1, threads)
        self.max_depth = max_depth
        self.root = root
        self.module_root = module_root or _default_nissy_core_module_root(root)
        self.startup_timeout_seconds = startup_timeout_seconds
        self.table_bytes = table_path.stat().st_size
        self.table_data_mode = "unknown"
        self.solve_buffer_available = False
        self._process: subprocess.Popen[str] | None = None
        self._selector: selectors.BaseSelector | None = None
        self._request_id = 0

    def close(self) -> None:
        process = self._process
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1.0)
        if self._selector is not None:
            self._selector.close()
        self._process = None
        self._selector = None

    def __enter__(self) -> "NissyCoreDirectPythonSession":
        self._start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _start(self) -> None:
        if self._process is not None and self._process.poll() is None:
            return
        if not _nissy_core_python_module_available(self.module_root):
            raise _NissyCorePythonUnavailable(
                f"nissy-core Python module not found under {self.module_root / 'python'}"
            )
        src_path = self.root / "src"
        package_src_path = Path(__file__).resolve().parents[2]
        env = os.environ.copy()
        pythonpath_parts = [str(package_src_path)]
        if src_path.exists() and src_path != package_src_path:
            pythonpath_parts.append(str(src_path))
        if env.get("PYTHONPATH"):
            pythonpath_parts.append(env["PYTHONPATH"])
        if pythonpath_parts:
            env["PYTHONPATH"] = os.pathsep.join(pythonpath_parts)
        command = [
            sys.executable,
            "-u",
            "-m",
            "rubik_optimal.solvers.nissy_core_worker",
            "--module-root",
            str(self.module_root),
            "--table-path",
            str(self.table_path),
            "--solver",
            self.solver,
            "--threads",
            str(self.threads),
            "--max-depth",
            str(self.max_depth),
        ]
        self._process = subprocess.Popen(
            command,
            cwd=self.root,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        if self._process.stdout is None:
            self.close()
            raise _NissyCorePythonUnavailable("nissy-core Python worker stdout pipe is unavailable")
        self._selector = selectors.DefaultSelector()
        self._selector.register(self._process.stdout, selectors.EVENT_READ)
        try:
            line = self._readline(self.startup_timeout_seconds, kill_on_timeout=True)
        except (RuntimeError, TimeoutError) as exc:
            self.close()
            raise _NissyCorePythonUnavailable(f"nissy-core Python worker did not start: {exc}") from exc
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            self.close()
            raise _NissyCorePythonUnavailable(f"invalid nissy-core Python worker startup JSON: {exc}") from exc
        if message.get("event") != "ready":
            error = message.get("error", message)
            self.close()
            raise _NissyCorePythonUnavailable(f"nissy-core Python worker failed startup: {error}")
        self.table_bytes = int(message.get("table_bytes") or self.table_bytes)
        self.table_data_mode = str(message.get("table_data_mode") or self.table_data_mode)
        self.solve_buffer_available = bool(message.get("solve_buffer_available"))

    def _readline(self, timeout_seconds: float | None, *, kill_on_timeout: bool = True) -> str:
        process = self._process
        selector = self._selector
        if process is None or process.stdout is None or selector is None:
            raise RuntimeError("nissy-core Python worker is not running")
        if timeout_seconds is None:
            line = process.stdout.readline()
        else:
            events = selector.select(max(0.0, timeout_seconds))
            if not events:
                if kill_on_timeout:
                    self.close()
                raise TimeoutError("nissy-core Python worker timed out waiting for output")
            line = process.stdout.readline()
        if line:
            return line
        return_code = process.poll()
        stderr = ""
        if return_code is not None:
            try:
                _, stderr = process.communicate(timeout=0.1)
            except Exception:
                stderr = ""
        raise RuntimeError(
            f"nissy-core Python worker exited before response; return_code={return_code}; stderr={stderr.strip()}"
        )

    def solve(self, cube: CubeState, *, timeout_seconds: float | None = 300.0) -> SolverResult:
        begin = time.perf_counter()
        solver_name = f"nissy_core_python_resident_{self.solver}"
        if cube.is_solved():
            return SolverResult(
                solver_name=solver_name,
                input_state=cube.to_facelets(),
                solution_moves=[],
                solution_length=0,
                metric="HTM",
                runtime_seconds=0.0,
                expanded_nodes=None,
                generated_nodes=None,
                table_bytes=self.table_bytes,
                status="exact",
                is_verified=True,
                notes=(
                    "nissy-core Python resident backend not invoked for solved state; "
                    "input_mode=cube_state; table_loaded_once=true; "
                    f"table_data_mode={self.table_data_mode}; "
                    f"solve_buffer_available={self.solve_buffer_available}"
                ),
            )
        try:
            nissy_cube = cube_to_nissy_string(cube)
            self._start()
            process = self._process
            if process is None or process.stdin is None:
                raise RuntimeError("nissy-core Python worker stdin pipe is unavailable")
            self._request_id += 1
            request_id = self._request_id
            process.stdin.write(json.dumps({"id": request_id, "cube": nissy_cube}, separators=(",", ":")) + "\n")
            process.stdin.flush()
            line = self._readline(timeout_seconds, kill_on_timeout=True)
            response = json.loads(line)
            if response.get("id") != request_id:
                raise RuntimeError(f"nissy-core Python worker returned mismatched id: {response}")
            if response.get("status") != "ok":
                raise RuntimeError(response.get("error", response))
            solutions = response.get("solutions") or []
            if not solutions:
                raise RuntimeError("nissy-core Python worker returned no solution")
            solution = parse_sequence(str(solutions[0]))
            solution_length = len(solution)
            verification = verify_solution(cube, solution)
            return SolverResult(
                solver_name=solver_name,
                input_state=cube.to_facelets(),
                solution_moves=solution,
                solution_length=solution_length if verification.ok else None,
                metric="HTM",
                runtime_seconds=time.perf_counter() - begin,
                expanded_nodes=None,
                generated_nodes=None,
                table_bytes=self.table_bytes,
                status="exact" if verification.ok else "failed",
                is_verified=verification.ok,
                notes=(
                    "nissy-core Python resident backend; input_mode=cube_state; "
                    "table_loaded_once=true; process_per_batch=true; source_sequence_provided=false; "
                    f"table_data_mode={self.table_data_mode}; "
                    f"solve_buffer_available={self.solve_buffer_available}; "
                    f"solver={self.solver}; table_path={self.table_path}; max_depth={self.max_depth}; "
                    f"optimal=0; threads={self.threads}; worker_runtime_seconds="
                    f"{float(response.get('runtime_seconds') or 0.0):.6f}"
                ),
            )
        except TimeoutError as exc:
            timeout_label = "unbounded" if timeout_seconds is None else f"{timeout_seconds}s"
            return _result_for_status(
                cube,
                solver_name=solver_name,
                status="timeout",
                runtime_seconds=time.perf_counter() - begin,
                table_bytes=self.table_bytes,
                notes=(
                    f"nissy-core Python resident backend timed out after {timeout_label}; "
                    "input_mode=cube_state; table_loaded_once=true; process_per_batch=true; "
                    f"table_data_mode={self.table_data_mode}; "
                    f"solve_buffer_available={self.solve_buffer_available}; error={exc}"
                ),
            )
        except Exception as exc:
            return _result_for_status(
                cube,
                solver_name=solver_name,
                status="failed",
                runtime_seconds=time.perf_counter() - begin,
                table_bytes=self.table_bytes,
                notes=(
                    "nissy-core Python resident backend failed; input_mode=cube_state; "
                    f"table_loaded_once=true; process_per_batch=true; "
                    f"table_data_mode={self.table_data_mode}; "
                    f"solve_buffer_available={self.solve_buffer_available}; error={exc}"
                ),
            )

    def solve_many(
        self,
        cubes: list[CubeState],
        *,
        timeout_seconds: float | None = 300.0,
    ) -> list[SolverResult]:
        return [self.solve(cube, timeout_seconds=timeout_seconds) for cube in cubes]


def _solve_nissy_step_optimal_batch(
    cubes: list[CubeState],
    *,
    step: str,
    solver_name: str,
    required_table: str | None = None,
    source_sequences: list[list[str] | tuple[str, ...] | str | None] | None = None,
    timeout_seconds: float = 300.0,
    threads: int = 8,
    binary_path: str | Path | None = None,
    data_dir: str | Path | None = None,
    root: Path | None = None,
) -> list[SolverResult]:
    root = root or _repository_root()
    begin = time.perf_counter()
    selected_data_dir = _default_data_dir(root, data_dir)
    table_bytes = _directory_size(selected_data_dir)
    if source_sequences is None:
        source_sequences = [None] * len(cubes)
    if len(source_sequences) != len(cubes):
        raise ValueError("source_sequences length must match cubes length")

    results: list[SolverResult | None] = [None] * len(cubes)
    pending: list[tuple[int, CubeState, list[str], str]] = []
    for index, (cube, source_sequence) in enumerate(zip(cubes, source_sequences, strict=True)):
        if cube.is_solved():
            results[index] = SolverResult(
                solver_name=solver_name,
                input_state=cube.to_facelets(),
                solution_moves=[],
                solution_length=0,
                metric="HTM",
                runtime_seconds=0.0,
                expanded_nodes=None,
                generated_nodes=None,
                table_bytes=table_bytes,
                status="exact",
                is_verified=True,
                notes=f"external Nissy `{step}` batch backend not invoked for solved state",
            )
            continue
        try:
            scramble, scramble_source = _representative_scramble(cube, source_sequence)
            pending.append((index, cube, scramble, scramble_source))
        except Exception as exc:
            results[index] = _result_for_status(
                cube,
                solver_name=solver_name,
                status="failed",
                runtime_seconds=time.perf_counter() - begin,
                table_bytes=table_bytes,
                notes=str(exc),
            )

    if not pending:
        return [result for result in results if result is not None]

    binary = _find_binary(root, binary_path)
    if binary is None:
        runtime = time.perf_counter() - begin
        for index, cube, _, _ in pending:
            results[index] = _result_for_status(
                cube,
                solver_name=solver_name,
                status="not_applicable",
                runtime_seconds=runtime,
                table_bytes=table_bytes,
                notes="Nissy binary not found; set NISSY_BINARY or install nissy on PATH",
            )
        return [result for result in results if result is not None]

    if required_table is not None:
        required_path = _table_path(selected_data_dir, required_table)
        if required_path is None or not required_path.exists():
            runtime = time.perf_counter() - begin
            for index, cube, _, _ in pending:
                results[index] = _result_for_status(
                    cube,
                    solver_name=solver_name,
                    status="not_applicable",
                    runtime_seconds=runtime,
                    table_bytes=table_bytes,
                    notes=(
                        f"external Nissy `{step}` batch backend requires local pruning table "
                        f"{required_table}; run scripts/install_nissy_public_table.py"
                    ),
                )
            return [result for result in results if result is not None]

    command = [
        str(binary),
        "solve",
        step,
        "-t",
        str(threads),
        "-o",
        "-n",
        "1",
        "-i",
    ]
    env = os.environ.copy()
    if selected_data_dir is not None:
        env["NISSYDATA"] = str(selected_data_dir)
    ordered_pending = sorted(pending, key=lambda item: (len(item[2]), item[0]))
    stdin = "\n".join(" ".join(scramble) for _, _, scramble, _ in ordered_pending) + "\n"
    try:
        return_code, stdout, stderr, timed_out = _run_text_process_streaming(
            command,
            cwd=root,
            env=env,
            input_text=stdin,
            timeout_seconds=timeout_seconds,
        )
        batch_runtime = time.perf_counter() - begin
        output = "\n".join(part for part in (stdout, stderr) if part)
        if timed_out:
            partial_solutions = _parse_partial_batch_solutions(output)
            partial_count = min(len(partial_solutions), len(ordered_pending))
            for offset, (index, cube, _, scramble_source) in enumerate(ordered_pending):
                if offset < partial_count:
                    solution, solution_length = partial_solutions[offset]
                    verification = verify_solution(cube, solution)
                    results[index] = SolverResult(
                        solver_name=solver_name,
                        input_state=cube.to_facelets(),
                        solution_moves=solution,
                        solution_length=solution_length if verification.ok else None,
                        metric="HTM",
                        runtime_seconds=batch_runtime,
                        expanded_nodes=None,
                        generated_nodes=None,
                        table_bytes=table_bytes,
                        status="exact" if verification.ok else "failed",
                        is_verified=verification.ok,
                        notes=(
                            f"external Nissy `solve {step} -o -i` batch row completed before timeout; "
                            "partial_timeout_recovered=true; batch_ordered_by_scramble_length=true; "
                            f"batch_size={len(ordered_pending)}; batch_index={offset}; "
                            f"batch_original_index={index}; "
                            "input_mode=representative_scramble; "
                            f"source_sequence_provided={source_sequences[index] is not None}; "
                            f"scramble_source={scramble_source}; threads={threads}; "
                            f"required_table={required_table or 'none'}; "
                            f"timeout_seconds={timeout_seconds}; partial_completed_count={partial_count}"
                        ),
                    )
                    continue
                results[index] = _result_for_status(
                    cube,
                    solver_name=solver_name,
                    status="timeout",
                    runtime_seconds=batch_runtime,
                    table_bytes=table_bytes,
                    notes=(
                        f"external Nissy `{step}` batch timed out after {timeout_seconds}s; "
                        "batch_ordered_by_scramble_length=true; "
                        f"batch_size={len(ordered_pending)}; batch_index={offset}; "
                        f"batch_original_index={index}; "
                        f"partial_completed_count={partial_count}; partial_output={output}"
                    ),
                )
            return [result for result in results if result is not None]
        if return_code != 0:
            raise RuntimeError(output.strip() or f"Nissy batch exited with status {return_code}")
        parsed = _parse_batch_solutions(output, len(ordered_pending))
        for offset, (index, cube, _, scramble_source) in enumerate(ordered_pending):
            solution, solution_length = parsed[offset]
            verification = verify_solution(cube, solution)
            results[index] = SolverResult(
                solver_name=solver_name,
                input_state=cube.to_facelets(),
                solution_moves=solution,
                solution_length=solution_length if verification.ok else None,
                metric="HTM",
                runtime_seconds=batch_runtime,
                expanded_nodes=None,
                generated_nodes=None,
                table_bytes=table_bytes,
                status="exact" if verification.ok else "failed",
                is_verified=verification.ok,
                notes=(
                    f"external Nissy `solve {step} -o -i` batch backend; "
                    "batch_ordered_by_scramble_length=true; "
                    f"batch_size={len(ordered_pending)}; batch_index={offset}; "
                    f"batch_original_index={index}; "
                    "input_mode=representative_scramble; "
                    f"source_sequence_provided={source_sequences[index] is not None}; "
                    f"scramble_source={scramble_source}; threads={threads}; "
                    f"required_table={required_table or 'none'}; "
                    f"return_code={return_code}"
                ),
            )
    except Exception as exc:
        runtime = time.perf_counter() - begin
        for index, cube, _, _ in pending:
            if results[index] is None:
                results[index] = _result_for_status(
                    cube,
                    solver_name=solver_name,
                    status="failed",
                    runtime_seconds=runtime,
                    table_bytes=table_bytes,
                    notes=str(exc),
                )

    return [result for result in results if result is not None]


def solve_nissy_core_direct_optimal(
    cube: CubeState,
    *,
    solver: str = "optimal",
    profile: str = "thesis",
    seed: int = 2026,
    table_path: str | Path | None = None,
    timeout_seconds: float | None = 300.0,
    threads: int = 8,
    max_depth: int = 20,
    binary_path: str | Path | None = None,
    root: Path | None = None,
) -> SolverResult:
    """Solve a direct 3x3 cubie state through the local nissy-core shell.

    This is distinct from the older external Nissy 2.x wrapper above: it does
    not recover or pass a representative scramble. The cube is converted to
    nissy-core's compact cubie-state string and solved with ``-O 0`` so the
    returned solution must be optimal, then independently verified locally.
    """

    root = root or _repository_root()
    begin = time.perf_counter()
    canonical_solver = canonical_h48_solver(solver)
    solver_arg = solver if solver == "optimal" else canonical_solver
    if cube.is_solved():
        return SolverResult(
            solver_name=f"nissy_core_direct_{canonical_solver}",
            input_state=cube.to_facelets(),
            solution_moves=[],
            solution_length=0,
            metric="HTM",
            runtime_seconds=time.perf_counter() - begin,
            expanded_nodes=None,
            generated_nodes=None,
            table_bytes=0,
            status="exact",
            is_verified=True,
            notes="nissy-core direct H48 shell backend not invoked for solved state; input_mode=cube_state",
        )

    binary = _find_nissy_core_shell(root, binary_path)
    if binary is None:
        return SolverResult(
            solver_name=f"nissy_core_direct_{canonical_solver}",
            input_state=cube.to_facelets(),
            solution_moves=[],
            solution_length=None,
            metric="HTM",
            runtime_seconds=time.perf_counter() - begin,
            expanded_nodes=None,
            generated_nodes=None,
            table_bytes=0,
            status="not_applicable",
            is_verified=False,
            notes="nissy-core shell binary not found; set NISSY_CORE_BINARY or install nissy-core/run",
        )

    selected_table = Path(table_path) if table_path is not None else h48_table_path(
        root=root,
        profile=profile,
        seed=seed,
        solver=canonical_solver,
    )
    if not selected_table.exists():
        return SolverResult(
            solver_name=f"nissy_core_direct_{canonical_solver}",
            input_state=cube.to_facelets(),
            solution_moves=[],
            solution_length=None,
            metric="HTM",
            runtime_seconds=time.perf_counter() - begin,
            expanded_nodes=None,
            generated_nodes=None,
            table_bytes=0,
            status="not_applicable",
            is_verified=False,
            notes=f"nissy-core direct backend requires local H48 table {selected_table}",
        )

    try:
        nissy_cube = cube_to_nissy_string(cube)
    except Exception as exc:
        return SolverResult(
            solver_name=f"nissy_core_direct_{canonical_solver}",
            input_state=cube.to_facelets(),
            solution_moves=[],
            solution_length=None,
            metric="HTM",
            runtime_seconds=time.perf_counter() - begin,
            expanded_nodes=None,
            generated_nodes=None,
            table_bytes=selected_table.stat().st_size,
            status="failed",
            is_verified=False,
            notes=f"could not convert cube to nissy-core direct state: {exc}",
        )

    with tempfile.TemporaryDirectory(prefix="rubik-nissy-core-") as temp_name:
        temp_dir = Path(temp_name)
        link_path = temp_dir / canonical_solver
        try:
            link_path.symlink_to(selected_table.resolve())
        except OSError as exc:
            return SolverResult(
                solver_name=f"nissy_core_direct_{canonical_solver}",
                input_state=cube.to_facelets(),
                solution_moves=[],
                solution_length=None,
                metric="HTM",
                runtime_seconds=time.perf_counter() - begin,
                expanded_nodes=None,
                generated_nodes=None,
                table_bytes=selected_table.stat().st_size,
                status="failed",
                is_verified=False,
                notes=f"could not symlink H48 table for nissy-core shell: {exc}",
            )

        command = [
            str(binary),
            "solve",
            "-solver",
            solver_arg,
            "-M",
            str(max_depth),
            "-n",
            "1",
            "-O",
            "0",
            "-cube",
            nissy_cube,
            "-t",
            str(max(1, threads)),
        ]
        try:
            completed = subprocess.run(
                command,
                cwd=temp_dir,
                text=True,
                capture_output=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            timeout_label = "unbounded" if timeout_seconds is None else f"{timeout_seconds}s"
            return SolverResult(
                solver_name=f"nissy_core_direct_{canonical_solver}",
                input_state=cube.to_facelets(),
                solution_moves=[],
                solution_length=None,
                metric="HTM",
                runtime_seconds=time.perf_counter() - begin,
                expanded_nodes=None,
                generated_nodes=None,
                table_bytes=selected_table.stat().st_size,
                status="timeout",
                is_verified=False,
                notes=f"nissy-core direct backend timed out after {timeout_label}; partial_output={exc.stdout or ''}",
            )

    output = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
    if completed.returncode != 0:
        return SolverResult(
            solver_name=f"nissy_core_direct_{canonical_solver}",
            input_state=cube.to_facelets(),
            solution_moves=[],
            solution_length=None,
            metric="HTM",
            runtime_seconds=time.perf_counter() - begin,
            expanded_nodes=None,
            generated_nodes=None,
            table_bytes=selected_table.stat().st_size,
            status="failed",
            is_verified=False,
            notes=f"nissy-core direct backend exited with {completed.returncode}; output={output.strip()}",
        )

    try:
        solution, solution_length = _parse_plain_nissy_core_solution(output)
        verification = verify_solution(cube, solution)
    except Exception as exc:
        return SolverResult(
            solver_name=f"nissy_core_direct_{canonical_solver}",
            input_state=cube.to_facelets(),
            solution_moves=[],
            solution_length=None,
            metric="HTM",
            runtime_seconds=time.perf_counter() - begin,
            expanded_nodes=None,
            generated_nodes=None,
            table_bytes=selected_table.stat().st_size,
            status="failed",
            is_verified=False,
            notes=f"nissy-core direct parse/verification failed: {exc}; output={output.strip()}",
        )

    return SolverResult(
        solver_name=f"nissy_core_direct_{canonical_solver}",
        input_state=cube.to_facelets(),
        solution_moves=solution,
        solution_length=solution_length if verification.ok else None,
        metric="HTM",
        runtime_seconds=time.perf_counter() - begin,
        expanded_nodes=None,
        generated_nodes=None,
        table_bytes=selected_table.stat().st_size,
        status="exact" if verification.ok else "failed",
        is_verified=verification.ok,
        notes=(
            "nissy-core direct H48 shell backend; input_mode=cube_state; "
            "table_symlink=true; source_sequence_provided=false; "
            f"solver={solver_arg}; canonical_solver={canonical_solver}; "
            f"table_path={selected_table}; max_depth={max_depth}; optimal=0; "
            f"threads={threads}; return_code={completed.returncode}"
        ),
    )


def solve_nissy_core_direct_optimal_batch(
    cubes: list[CubeState],
    *,
    solver: str = "optimal",
    profile: str = "thesis",
    seed: int = 2026,
    table_path: str | Path | None = None,
    timeout_seconds: float | None = 300.0,
    threads: int = 8,
    max_depth: int = 20,
    binary_path: str | Path | None = None,
    root: Path | None = None,
) -> list[SolverResult]:
    """Solve direct 3x3 cubie states through the local nissy-core shell.

    The nissy-core shell currently accepts one ``-cube`` per process. This
    batch wrapper still prepares the H48 table symlink once, preserves input
    order, and independently verifies every row before reporting ``exact``.
    """

    root = root or _repository_root()
    begin = time.perf_counter()
    canonical_solver = canonical_h48_solver(solver)
    solver_arg = solver if solver == "optimal" else canonical_solver
    solver_name = f"nissy_core_direct_{canonical_solver}"
    results: list[SolverResult | None] = [None] * len(cubes)
    pending: list[tuple[int, CubeState, str]] = []

    for index, cube in enumerate(cubes):
        if cube.is_solved():
            results[index] = SolverResult(
                solver_name=solver_name,
                input_state=cube.to_facelets(),
                solution_moves=[],
                solution_length=0,
                metric="HTM",
                runtime_seconds=0.0,
                expanded_nodes=None,
                generated_nodes=None,
                table_bytes=0,
                status="exact",
                is_verified=True,
                notes=(
                    "nissy-core direct H48 shell batch backend not invoked for solved state; "
                    "input_mode=cube_state; batch_backend=true"
                ),
            )
            continue
        try:
            pending.append((index, cube, cube_to_nissy_string(cube)))
        except Exception as exc:
            results[index] = _result_for_status(
                cube,
                solver_name=solver_name,
                status="failed",
                runtime_seconds=time.perf_counter() - begin,
                table_bytes=0,
                notes=f"could not convert cube to nissy-core direct state: {exc}",
            )

    if not pending:
        return [result for result in results if result is not None]

    selected_table = Path(table_path) if table_path is not None else h48_table_path(
        root=root,
        profile=profile,
        seed=seed,
        solver=canonical_solver,
    )
    if not selected_table.exists():
        runtime = time.perf_counter() - begin
        for index, cube, _ in pending:
            results[index] = _result_for_status(
                cube,
                solver_name=solver_name,
                status="not_applicable",
                runtime_seconds=runtime,
                table_bytes=0,
                notes=f"nissy-core direct batch backend requires local H48 table {selected_table}",
            )
        return [result for result in results if result is not None]

    table_bytes = selected_table.stat().st_size
    module_root = _default_nissy_core_module_root(root)
    if _nissy_core_python_module_available(module_root) and _nissy_core_python_enabled_for_table(
        selected_table, module_root
    ):
        try:
            with NissyCoreDirectPythonSession(
                solver=solver_arg,
                table_path=selected_table,
                threads=max(1, threads),
                max_depth=max_depth,
                root=root,
                module_root=module_root,
            ) as session:
                python_results = session.solve_many(
                    [cube for _, cube, _ in pending],
                    timeout_seconds=timeout_seconds,
                )
            for (index, _, _), result in zip(pending, python_results, strict=True):
                results[index] = result
            return [result for result in results if result is not None]
        except _NissyCorePythonUnavailable:
            pass

    binary = _find_nissy_core_shell(root, binary_path)
    if binary is None:
        runtime = time.perf_counter() - begin
        for index, cube, _ in pending:
            results[index] = _result_for_status(
                cube,
                solver_name=solver_name,
                status="not_applicable",
                runtime_seconds=runtime,
                table_bytes=0,
                notes=(
                    "nissy-core shell binary not found and Python resident backend unavailable; "
                    "set NISSY_CORE_BINARY, install nissy-core/run, or build nissy-core/python/nissy.so"
                ),
            )
        return [result for result in results if result is not None]

    with tempfile.TemporaryDirectory(prefix="rubik-nissy-core-batch-") as temp_name:
        temp_dir = Path(temp_name)
        link_path = temp_dir / canonical_solver
        try:
            link_path.symlink_to(selected_table.resolve())
        except OSError as exc:
            runtime = time.perf_counter() - begin
            for index, cube, _ in pending:
                results[index] = _result_for_status(
                    cube,
                    solver_name=solver_name,
                    status="failed",
                    runtime_seconds=runtime,
                    table_bytes=table_bytes,
                    notes=f"could not symlink H48 table for nissy-core direct batch shell: {exc}",
                )
            return [result for result in results if result is not None]

        for offset, (index, cube, nissy_cube) in enumerate(pending):
            row_begin = time.perf_counter()
            command = [
                str(binary),
                "solve",
                "-solver",
                solver_arg,
                "-M",
                str(max_depth),
                "-n",
                "1",
                "-O",
                "0",
                "-cube",
                nissy_cube,
                "-t",
                str(max(1, threads)),
            ]
            try:
                completed = subprocess.run(
                    command,
                    cwd=temp_dir,
                    text=True,
                    capture_output=True,
                    timeout=timeout_seconds,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                timeout_label = "unbounded" if timeout_seconds is None else f"{timeout_seconds}s"
                partial_output = "\n".join(
                    part for part in (_subprocess_text(exc.stdout), _subprocess_text(exc.stderr)) if part
                )
                results[index] = _result_for_status(
                    cube,
                    solver_name=solver_name,
                    status="timeout",
                    runtime_seconds=time.perf_counter() - row_begin,
                    table_bytes=table_bytes,
                    notes=(
                        f"nissy-core direct batch backend timed out after {timeout_label}; "
                        "input_mode=cube_state; table_symlink_reused=true; "
                        "process_per_row=true; source_sequence_provided=false; "
                        f"batch_size={len(pending)}; batch_index={offset}; "
                        f"batch_original_index={index}; partial_output={partial_output}"
                    ),
                )
                continue

            output = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
            if completed.returncode != 0:
                results[index] = _result_for_status(
                    cube,
                    solver_name=solver_name,
                    status="failed",
                    runtime_seconds=time.perf_counter() - row_begin,
                    table_bytes=table_bytes,
                    notes=(
                        f"nissy-core direct batch backend exited with {completed.returncode}; "
                        "input_mode=cube_state; table_symlink_reused=true; "
                        "process_per_row=true; source_sequence_provided=false; "
                        f"batch_size={len(pending)}; batch_index={offset}; "
                        f"batch_original_index={index}; output={output.strip()}"
                    ),
                )
                continue

            try:
                solution, solution_length = _parse_plain_nissy_core_solution(output)
                verification = verify_solution(cube, solution)
            except Exception as exc:
                results[index] = _result_for_status(
                    cube,
                    solver_name=solver_name,
                    status="failed",
                    runtime_seconds=time.perf_counter() - row_begin,
                    table_bytes=table_bytes,
                    notes=(
                        f"nissy-core direct batch parse/verification failed: {exc}; "
                        "input_mode=cube_state; table_symlink_reused=true; "
                        "process_per_row=true; source_sequence_provided=false; "
                        f"batch_size={len(pending)}; batch_index={offset}; "
                        f"batch_original_index={index}; output={output.strip()}"
                    ),
                )
                continue

            results[index] = SolverResult(
                solver_name=solver_name,
                input_state=cube.to_facelets(),
                solution_moves=solution,
                solution_length=solution_length if verification.ok else None,
                metric="HTM",
                runtime_seconds=time.perf_counter() - row_begin,
                expanded_nodes=None,
                generated_nodes=None,
                table_bytes=table_bytes,
                status="exact" if verification.ok else "failed",
                is_verified=verification.ok,
                notes=(
                    "nissy-core direct H48 shell batch backend; input_mode=cube_state; "
                    "table_symlink_reused=true; process_per_row=true; "
                    "source_sequence_provided=false; "
                    f"batch_size={len(pending)}; batch_index={offset}; "
                    f"batch_original_index={index}; solver={solver_arg}; "
                    f"canonical_solver={canonical_solver}; table_path={selected_table}; "
                    f"max_depth={max_depth}; optimal=0; threads={threads}; "
                    f"return_code={completed.returncode}"
                ),
            )

    return [result for result in results if result is not None]


def solve_nissy_light_optimal(
    cube: CubeState,
    *,
    source_sequence: list[str] | tuple[str, ...] | str | None = None,
    timeout_seconds: float = 300.0,
    threads: int = 8,
    binary_path: str | Path | None = None,
    data_dir: str | Path | None = None,
    root: Path | None = None,
) -> SolverResult:
    """Solve a 3x3 state optimally through Nissy's small-table HTM step."""

    return _solve_nissy_step_optimal(
        cube,
        step="light",
        solver_name="nissy_light_external_optimal",
        source_sequence=source_sequence,
        timeout_seconds=timeout_seconds,
        threads=threads,
        binary_path=binary_path,
        data_dir=data_dir,
        root=root,
    )


def solve_nissy_light_optimal_batch(
    cubes: list[CubeState],
    *,
    source_sequences: list[list[str] | tuple[str, ...] | str | None] | None = None,
    timeout_seconds: float = 300.0,
    threads: int = 8,
    binary_path: str | Path | None = None,
    data_dir: str | Path | None = None,
    root: Path | None = None,
) -> list[SolverResult]:
    """Solve multiple 3x3 states through one Nissy light batch process."""

    return _solve_nissy_step_optimal_batch(
        cubes,
        step="light",
        solver_name="nissy_light_external_optimal",
        source_sequences=source_sequences,
        timeout_seconds=timeout_seconds,
        threads=threads,
        binary_path=binary_path,
        data_dir=data_dir,
        root=root,
    )


def solve_nissy2_state_optimal(
    cube: CubeState,
    *,
    timeout_seconds: float = 300.0,
    threads: int = 8,
    data_dir: str | Path | None = None,
    root: Path | None = None,
) -> SolverResult:
    """Solve a raw cubie state through Nissy 2.x's public optimal HTM backend."""

    root = root or _repository_root()
    begin = time.perf_counter()
    selected_data_dir = _default_data_dir(root, data_dir)
    table_bytes = _directory_size(selected_data_dir)
    solver_name = "nissy2_state_optimal_external"
    if cube.is_solved():
        return SolverResult(
            solver_name=solver_name,
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
            notes="Nissy 2.x direct-state optimal bridge not invoked for solved state",
        )

    missing_tables = _missing_nissy_tables(selected_data_dir, _NISSY_OPTIMAL_REQUIRED_TABLES)
    if missing_tables:
        return _result_for_status(
            cube,
            solver_name=solver_name,
            status="not_applicable",
            runtime_seconds=time.perf_counter() - begin,
            table_bytes=table_bytes,
            notes=(
                "Nissy 2.x direct-state optimal bridge requires local public pruning tables: "
                f"{','.join(missing_tables)}; run scripts/install_nissy_public_table.py and "
                "scripts/verify_nissy_public_tables.py"
            ),
        )

    try:
        bridge = build_nissy2_state_bridge(root=root)
    except Exception as exc:
        return _result_for_status(
            cube,
            solver_name=solver_name,
            status="not_applicable",
            runtime_seconds=time.perf_counter() - begin,
            table_bytes=table_bytes,
            notes=f"Nissy 2.x direct-state optimal bridge unavailable: {exc}",
        )

    command = [
        str(bridge),
        _cubie_list(cube.cp),
        _cubie_list(cube.co),
        _cubie_list(cube.ep),
        _cubie_list(cube.eo),
        str(max(1, int(threads))),
    ]
    env = os.environ.copy()
    if selected_data_dir is not None:
        env["NISSYDATA"] = str(selected_data_dir)
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
        output = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
        if completed.returncode != 0:
            return _result_for_status(
                cube,
                solver_name=solver_name,
                status="failed",
                runtime_seconds=time.perf_counter() - begin,
                table_bytes=table_bytes,
                notes=(
                    "Nissy 2.x direct-state optimal bridge failed; "
                    f"input_mode=cube_state; return_code={completed.returncode}; output={output.strip()}"
                ),
            )
        solution, solution_length = _parse_solution(output)
        verification = verify_solution(cube, solution)
        return SolverResult(
            solver_name=solver_name,
            input_state=cube.to_facelets(),
            solution_moves=solution,
            solution_length=solution_length if verification.ok else None,
            metric="HTM",
            runtime_seconds=time.perf_counter() - begin,
            expanded_nodes=None,
            generated_nodes=None,
            table_bytes=table_bytes,
            status="exact" if verification.ok else "failed",
            is_verified=verification.ok,
            notes=(
                "Nissy 2.x direct-state optimal bridge; input_mode=cube_state; "
                "step=optimal; optimal=0; source_sequence_provided=false; "
                f"threads={threads}; bridge={bridge}; required_tables="
                f"{','.join(_NISSY_OPTIMAL_REQUIRED_TABLES)}; return_code={completed.returncode}"
            ),
        )
    except subprocess.TimeoutExpired as exc:
        return _result_for_status(
            cube,
            solver_name=solver_name,
            status="timeout",
            runtime_seconds=time.perf_counter() - begin,
            table_bytes=table_bytes,
            notes=(
                f"Nissy 2.x direct-state optimal bridge timed out after {timeout_seconds}s; "
                f"input_mode=cube_state; partial_output={_subprocess_text(exc.stdout)}"
            ),
        )
    except Exception as exc:
        return _result_for_status(
            cube,
            solver_name=solver_name,
            status="failed",
            runtime_seconds=time.perf_counter() - begin,
            table_bytes=table_bytes,
            notes=f"Nissy 2.x direct-state optimal bridge error: {exc}",
        )


def solve_nissy_optimal(
    cube: CubeState,
    *,
    source_sequence: list[str] | tuple[str, ...] | str | None = None,
    timeout_seconds: float = 300.0,
    threads: int = 8,
    binary_path: str | Path | None = None,
    data_dir: str | Path | None = None,
    root: Path | None = None,
) -> SolverResult:
    """Solve a 3x3 state optimally through Nissy's full optimal HTM step."""

    if source_sequence is None and _nissy2_state_bridge_enabled():
        direct_result = solve_nissy2_state_optimal(
            cube,
            timeout_seconds=timeout_seconds,
            threads=threads,
            data_dir=data_dir,
            root=root,
        )
        if direct_result.status != "not_applicable":
            return direct_result

    return _solve_nissy_step_optimal(
        cube,
        step="optimal",
        solver_name="nissy_optimal_external",
        required_table=_NISSY_OPTIMAL_TABLE,
        source_sequence=source_sequence,
        timeout_seconds=timeout_seconds,
        threads=threads,
        binary_path=binary_path,
        data_dir=data_dir,
        root=root,
    )


def solve_nissy_optimal_batch(
    cubes: list[CubeState],
    *,
    source_sequences: list[list[str] | tuple[str, ...] | str | None] | None = None,
    timeout_seconds: float = 300.0,
    threads: int = 8,
    binary_path: str | Path | None = None,
    data_dir: str | Path | None = None,
    root: Path | None = None,
) -> list[SolverResult]:
    """Solve multiple 3x3 states through one Nissy full optimal batch process."""

    if (
        len(cubes) == 1
        and _nissy2_state_bridge_enabled()
        and (source_sequences is None or source_sequences == [None])
    ):
        direct_result = solve_nissy2_state_optimal(
            cubes[0],
            timeout_seconds=timeout_seconds,
            threads=threads,
            data_dir=data_dir,
            root=root,
        )
        if direct_result.status != "not_applicable":
            return [direct_result]

    return _solve_nissy_step_optimal_batch(
        cubes,
        step="optimal",
        solver_name="nissy_optimal_external",
        required_table=_NISSY_OPTIMAL_TABLE,
        source_sequences=source_sequences,
        timeout_seconds=timeout_seconds,
        threads=threads,
        binary_path=binary_path,
        data_dir=data_dir,
        root=root,
    )

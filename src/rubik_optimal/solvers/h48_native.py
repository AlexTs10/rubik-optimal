"""Native H48 optimal solver wrapper."""

from __future__ import annotations

import json
import select
import subprocess
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable

from rubik_optimal.cube import (
    BL,
    BR,
    DB,
    DBL,
    DF,
    DFR,
    DL,
    DLF,
    DR,
    DRB,
    FL,
    FR,
    CubeState,
    UB,
    UBR,
    UF,
    UFL,
    ULB,
    UR,
    URF,
    UL,
)
from rubik_optimal.moves import parse_sequence
from rubik_optimal.solvers.base import SolverResult
from rubik_optimal.symmetry import CUBE_ROTATIONS, CubeRotation
from rubik_optimal.tables.h48 import (
    DEFAULT_H48_SOLVER,
    build_h48_backend,
    h48_table_path,
    repository_root,
    validate_trusted_h48_table,
)
from rubik_optimal.verify import verify_solution

_NISSY_CORNER_TO_LOCAL = (URF, ULB, DLF, DRB, UFL, UBR, DFR, DBL)
_LOCAL_CORNER_TO_NISSY = {local: nissy for nissy, local in enumerate(_NISSY_CORNER_TO_LOCAL)}
_NISSY_EDGE_TO_LOCAL = (UF, UB, DB, DF, UR, UL, DL, DR, FR, FL, BL, BR)
_LOCAL_EDGE_TO_NISSY = {local: nissy for nissy, local in enumerate(_NISSY_EDGE_TO_LOCAL)}
_UINT32_MAX = 2**32 - 1
_H48_SYMMETRY_AXIS_GROUP_ORDER = ("FB", "RL", "UD")


@dataclass(frozen=True)
class H48LowerBoundResult:
    solver_name: str
    input_state: str
    lower_bound: int | None
    runtime_seconds: float
    table_bytes: int | None
    status: str
    notes: str


def _base32_piece(value: int) -> str:
    if value < 0 or value >= 32:
        raise ValueError(f"Nissy piece code must be in [0, 32), got {value}")
    return chr(ord("A") + value) if value < 26 else chr(ord("a") + value - 26)


def cube_to_nissy_string(cube: CubeState) -> str:
    """Convert the local cubie state to nissy-core's compact cube string.

    Nissy uses the cubie order UFR, UBL, DFL, DBR, UFL, UBR, DFR, DBL for
    corners and UF, UB, DB, DF, UR, UL, DL, DR, FR, FL, BL, BR for edges.
    Its compact string encodes corner orientation as cubie + 8 * twist and
    edge orientation as cubie + 16 * flip.
    """

    code, message = cube.verify_physical()
    if code != 0:
        raise ValueError(message)

    corners = []
    for local_position in _NISSY_CORNER_TO_LOCAL:
        local_cubie = cube.cp[local_position]
        nissy_cubie = _LOCAL_CORNER_TO_NISSY[local_cubie]
        corners.append(_base32_piece(nissy_cubie + 8 * cube.co[local_position]))

    edges = []
    for local_position in _NISSY_EDGE_TO_LOCAL:
        local_cubie = cube.ep[local_position]
        nissy_cubie = _LOCAL_EDGE_TO_NISSY[local_cubie]
        edges.append(_base32_piece(nissy_cubie + 16 * cube.eo[local_position]))

    return f"{''.join(corners)}={''.join(edges)}=A"


def _timeout_seconds_to_ms(timeout_seconds: float | None) -> int | None:
    if timeout_seconds is None or timeout_seconds <= 0:
        return None
    return max(1, min(_UINT32_MAX, int(round(timeout_seconds * 1000))))


def _process_timeout_with_grace(timeout_seconds: float | None) -> float | None:
    if timeout_seconds is None or timeout_seconds <= 0:
        return timeout_seconds
    return timeout_seconds + min(15.0, max(2.0, timeout_seconds * 0.10))


def _subprocess_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _resident_stdout_wait_timeout(
    *,
    request_timeout_seconds: float | None,
    search_timeout_seconds: float | None,
) -> float | None:
    """Wait long enough to receive native timeout rows without needless reloads."""

    if search_timeout_seconds is None or search_timeout_seconds <= 0:
        return request_timeout_seconds
    search_timeout_with_grace = _process_timeout_with_grace(search_timeout_seconds)
    if request_timeout_seconds is None or request_timeout_seconds <= 0:
        return search_timeout_with_grace
    if request_timeout_seconds + 1e-9 < search_timeout_seconds:
        return request_timeout_seconds
    if search_timeout_with_grace is None:
        return request_timeout_seconds
    return max(request_timeout_seconds, search_timeout_with_grace)


def _parse_h48_batch_payload_lines(output: str) -> list[dict[str, object]]:
    payloads: list[dict[str, object]] = []
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            payloads.append(parsed)
    return payloads


def _parse_h48_lower_bound_rows(
    output: str,
    rotations: list[CubeRotation],
) -> tuple[
    list[tuple[int, CubeRotation, int, float | None, dict[str, object]]],
    list[tuple[str, str, object]],
    list[tuple[str, str]],
    int,
]:
    rows: list[tuple[int, CubeRotation, int, float | None, dict[str, object]]] = []
    failed_rows: list[tuple[str, str, object]] = []
    parse_errors: list[tuple[str, str]] = []
    stdout_lines = [line for line in output.splitlines() if line.strip()]
    for index, (rotation, line) in enumerate(zip(rotations, stdout_lines, strict=False)):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            parse_errors.append((rotation.name, line.strip()))
            continue
        if not isinstance(payload, dict):
            parse_errors.append((rotation.name, line.strip()))
            continue
        status = str(payload.get("status", "failed"))
        lower_bound = payload.get("lower_bound")
        if status == "lower_bound" and lower_bound is not None:
            rows.append(
                (
                    index,
                    rotation,
                    int(lower_bound),
                    float(payload["runtime_seconds"]) if payload.get("runtime_seconds") is not None else None,
                    payload,
                )
            )
        else:
            failed_rows.append((rotation.name, status, payload.get("error", "")))
    return rows, failed_rows, parse_errors, len(stdout_lines)


def _result_from_payload(
    cube: CubeState,
    *,
    solver: str,
    payload: dict[str, object],
    runtime_seconds: float,
    table_path: Path,
    table_bytes: int,
    return_code: int,
    source_sequence_provided: bool,
    mode_note: str,
) -> SolverResult:
    status = str(payload.get("status", "failed"))
    solution = parse_sequence(str(payload.get("solution") or ""))
    verification = verify_solution(cube, solution) if status == "exact" else None
    solution_length = (
        int(payload["solution_length"])
        if payload.get("solution_length") is not None
        else None
    )
    return SolverResult(
        solver_name=f"h48_native_{solver}",
        input_state=cube.to_facelets(),
        solution_moves=solution,
        solution_length=solution_length,
        metric="HTM",
        runtime_seconds=runtime_seconds,
        expanded_nodes=int(payload["expanded_nodes"]) if payload.get("expanded_nodes") is not None else None,
        generated_nodes=None,
        table_bytes=int(payload.get("table_size_bytes") or table_bytes),
        status=status if status in {"exact", "timeout", "lower_bound"} else "failed",
        is_verified=bool(status == "exact" and verification and verification.ok),
        notes=(
            f"{mode_note}; solver={solver}; "
            f"input_mode=cube_state; "
            f"source_sequence_provided={source_sequence_provided}; "
            f"table={table_path}; return_code={return_code}; "
            f"table_check={payload.get('table_check')}; "
            f"table_storage={payload.get('table_storage')}; "
            f"table_preload={payload.get('table_preload')}; "
            f"backend_solve_seconds={payload.get('runtime_seconds')}; "
            f"table_lookups={payload.get('table_lookups')}; "
            f"table_fallbacks={payload.get('table_fallbacks')}; "
            f"proved_lower_bound={payload.get('proved_lower_bound')}; "
            f"auto_min_depth={payload.get('auto_min_depth')}; "
            f"lower_bound={payload.get('lower_bound')}; "
            f"min_depth={payload.get('min_depth')}; "
            f"max_depth={payload.get('max_depth')}; "
            f"search_timeout_ms={payload.get('search_timeout_ms')}; "
            f"timed_out_by_poll={payload.get('timed_out_by_poll')}; "
            f"search_deadline_expired={payload.get('search_deadline_expired')}; "
            f"error={payload.get('error', '')}"
        ),
    )


class H48NativeOracleSession:
    """Long-lived native H48 oracle process with one shared table load.

    The native backend already supports line-delimited batch solving. This
    wrapper keeps that process open across calls, which is the closest local
    interface to an interactive exact oracle: each non-solved cube is sent as a
    compact nissy-core cubie string and one JSON result is read back.
    """

    def __init__(
        self,
        *,
        solver: str = DEFAULT_H48_SOLVER,
        profile: str = "thesis",
        seed: int = 2026,
        table_path: Path | None = None,
        threads: int = 8,
        max_depth: int = 20,
        skip_table_check: bool = False,
        preload_table: bool = False,
        auto_min_depth: bool = False,
        search_timeout_seconds: float | None = None,
        root: Path | None = None,
    ) -> None:
        self.root = root or repository_root()
        self.solver = solver
        self.profile = profile
        self.seed = seed
        self.table_path = table_path or h48_table_path(
            root=self.root,
            profile=profile,
            seed=seed,
            solver=solver,
        )
        self.threads = max(1, threads)
        self.max_depth = max_depth
        self.skip_table_check = skip_table_check
        self.preload_table = preload_table
        self.auto_min_depth = auto_min_depth
        self.search_timeout_seconds = search_timeout_seconds
        self._process: subprocess.Popen[bytes] | None = None
        self._trusted_note = ""

    def __enter__(self) -> "H48NativeOracleSession":
        self.start()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def start(self) -> None:
        if self._process is not None:
            return
        if not self.table_path.exists():
            raise FileNotFoundError(f"missing required H48 table: {self.table_path}")
        if self.skip_table_check:
            trusted_ok, trusted_message = validate_trusted_h48_table(
                root=self.root,
                profile=self.profile,
                seed=self.seed,
                solver=self.solver,
                table_path=self.table_path,
            )
            if not trusted_ok:
                raise ValueError(f"trusted H48 table rejected: {trusted_message}")
            self._trusted_note = f"; trusted_table_metadata=valid; trusted_table_note={trusted_message}"

        binary = build_h48_backend(root=self.root, threads=self.threads)
        command = [
            str(binary),
            "--solve-batch",
            "--solver",
            self.solver,
            "--table",
            str(self.table_path),
            "--threads",
            str(self.threads),
            "--max-depth",
            str(self.max_depth),
        ]
        if self.skip_table_check:
            command.append("--skip-table-check")
        if self.preload_table:
            command.append("--preload-table")
        if self.auto_min_depth:
            command.append("--auto-min-depth")
        search_timeout_ms = _timeout_seconds_to_ms(self.search_timeout_seconds)
        if search_timeout_ms is not None:
            command.extend(["--search-timeout-ms", str(search_timeout_ms)])
        self._process = subprocess.Popen(
            command,
            cwd=self.root,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def close(self) -> None:
        process = self._process
        self._process = None
        if process is None:
            return
        if process.stdin is not None and not process.stdin.closed:
            process.stdin.close()
        try:
            process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2.0)

    def solve(self, cube: CubeState, *, timeout_seconds: float | None = None) -> SolverResult:
        if cube == CubeState.solved():
            return SolverResult(
                solver_name=f"h48_native_{self.solver}",
                input_state=cube.to_facelets(),
                solution_moves=[],
                solution_length=0,
                metric="HTM",
                runtime_seconds=0.0,
                expanded_nodes=0,
                generated_nodes=None,
                table_bytes=0,
                status="exact",
                is_verified=True,
                notes="solved state; resident H48 backend not invoked",
            )
        self.start()
        process = self._process
        if process is None or process.stdin is None or process.stdout is None:
            raise RuntimeError("resident H48 process is not available")

        nissy_cube = cube_to_nissy_string(cube)
        begin = time.perf_counter()
        try:
            process.stdin.write((nissy_cube + "\n").encode("utf-8"))
            process.stdin.flush()
        except BrokenPipeError:
            stderr = process.stderr.read().decode("utf-8", errors="replace") if process.stderr else ""
            return SolverResult(
                solver_name=f"h48_native_{self.solver}",
                input_state=cube.to_facelets(),
                solution_moves=[],
                solution_length=None,
                metric="HTM",
                runtime_seconds=time.perf_counter() - begin,
                expanded_nodes=None,
                generated_nodes=None,
                table_bytes=self.table_path.stat().st_size if self.table_path.exists() else 0,
                status="failed",
                is_verified=False,
                notes=f"resident H48 backend exited before accepting input; stderr={stderr.strip()}",
            )

        wait_timeout_seconds = _resident_stdout_wait_timeout(
            request_timeout_seconds=timeout_seconds,
            search_timeout_seconds=self.search_timeout_seconds,
        )
        ready, _, _ = select.select([process.stdout], [], [], wait_timeout_seconds)
        runtime_seconds = time.perf_counter() - begin
        if not ready:
            self.close()
            timeout_label = "unbounded" if timeout_seconds is None else f"{timeout_seconds}s"
            return SolverResult(
                solver_name=f"h48_native_{self.solver}",
                input_state=cube.to_facelets(),
                solution_moves=[],
                solution_length=None,
                metric="HTM",
                runtime_seconds=runtime_seconds,
                expanded_nodes=None,
                generated_nodes=None,
                table_bytes=self.table_path.stat().st_size if self.table_path.exists() else 0,
                status="timeout",
                is_verified=False,
                notes=(
                    f"resident H48 backend timed out after {timeout_label} and was stopped; "
                    f"stdout_wait_timeout_seconds={wait_timeout_seconds}; "
                    f"native_search_timeout_seconds={self.search_timeout_seconds}"
                ),
            )

        line = process.stdout.readline().decode("utf-8", errors="replace").strip()
        if not line:
            stderr = process.stderr.read().decode("utf-8", errors="replace") if process.stderr else ""
            return SolverResult(
                solver_name=f"h48_native_{self.solver}",
                input_state=cube.to_facelets(),
                solution_moves=[],
                solution_length=None,
                metric="HTM",
                runtime_seconds=runtime_seconds,
                expanded_nodes=None,
                generated_nodes=None,
                table_bytes=self.table_path.stat().st_size if self.table_path.exists() else 0,
                status="failed",
                is_verified=False,
                notes=f"resident H48 backend produced no output; stderr={stderr.strip()}",
            )
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            payload = {
                "status": "failed",
                "solution": "",
                "solution_length": None,
                "expanded_nodes": None,
                "table_lookups": None,
                "table_fallbacks": None,
                "error": line,
            }
        return _result_from_payload(
            cube,
            solver=self.solver,
            payload=payload,
            runtime_seconds=runtime_seconds,
            table_path=self.table_path,
            table_bytes=self.table_path.stat().st_size,
            return_code=process.poll() if process.poll() is not None else 0,
            source_sequence_provided=False,
            mode_note=(
                "resident in-repo native H48 backend; table_loaded_once=true"
                f"; stdout_wait_timeout_seconds={wait_timeout_seconds}"
                f"; native_search_timeout_seconds={self.search_timeout_seconds}"
                f"{self._trusted_note}"
            ),
        )

    def solve_many(self, cubes: Iterable[CubeState], *, timeout_seconds: float | None = None) -> list[SolverResult]:
        cube_list = list(cubes)
        results: list[SolverResult | None] = [None] * len(cube_list)
        pending: list[tuple[int, CubeState, str]] = []
        for index, cube in enumerate(cube_list):
            if cube == CubeState.solved():
                results[index] = SolverResult(
                    solver_name=f"h48_native_{self.solver}",
                    input_state=cube.to_facelets(),
                    solution_moves=[],
                    solution_length=0,
                    metric="HTM",
                    runtime_seconds=0.0,
                    expanded_nodes=0,
                    generated_nodes=None,
                    table_bytes=0,
                    status="exact",
                    is_verified=True,
                    notes="solved state; resident H48 multi-row backend not invoked for this row",
                )
                continue
            try:
                pending.append((index, cube, cube_to_nissy_string(cube)))
            except Exception as exc:
                results[index] = SolverResult(
                    solver_name=f"h48_native_{self.solver}",
                    input_state=cube.to_facelets(),
                    solution_moves=[],
                    solution_length=None,
                    metric="HTM",
                    runtime_seconds=0.0,
                    expanded_nodes=None,
                    generated_nodes=None,
                    table_bytes=self.table_path.stat().st_size if self.table_path.exists() else 0,
                    status="failed",
                    is_verified=False,
                    notes=f"could not convert cube to nissy-core state for resident H48 multi-row backend: {exc}",
                )
        if not pending:
            return [result for result in results if result is not None]

        self.start()
        process = self._process
        if process is None or process.stdin is None or process.stdout is None:
            raise RuntimeError("resident H48 process is not available")

        begin = time.perf_counter()
        table_bytes = self.table_path.stat().st_size if self.table_path.exists() else 0
        wait_timeout_seconds = _resident_stdout_wait_timeout(
            request_timeout_seconds=timeout_seconds,
            search_timeout_seconds=self.search_timeout_seconds,
        )
        try:
            process.stdin.write(
                ("\n".join(nissy_cube for _, _, nissy_cube in pending) + "\n").encode("utf-8")
            )
            process.stdin.flush()
        except BrokenPipeError:
            runtime_seconds = time.perf_counter() - begin
            stderr = process.stderr.read().decode("utf-8", errors="replace") if process.stderr else ""
            for index, cube, _ in pending:
                results[index] = SolverResult(
                    solver_name=f"h48_native_{self.solver}",
                    input_state=cube.to_facelets(),
                    solution_moves=[],
                    solution_length=None,
                    metric="HTM",
                    runtime_seconds=runtime_seconds,
                    expanded_nodes=None,
                    generated_nodes=None,
                    table_bytes=table_bytes,
                    status="failed",
                    is_verified=False,
                    notes=(
                        "resident H48 multi-row backend exited before accepting batch input; "
                        f"batch_input_count={len(pending)}; stderr={stderr.strip()}"
                    ),
                )
            return [result for result in results if result is not None]

        completed_count = 0
        completed_result_indexes: list[int] = []
        for batch_row, (index, cube, _) in enumerate(pending):
            ready, _, _ = select.select([process.stdout], [], [], wait_timeout_seconds)
            batch_wall_seconds = time.perf_counter() - begin
            if not ready:
                self.close()
                timeout_label = "unbounded" if timeout_seconds is None else f"{timeout_seconds}s"
                for completed_index in completed_result_indexes:
                    completed_result = results[completed_index]
                    if completed_result is not None:
                        results[completed_index] = replace(
                            completed_result,
                            notes=(
                                f"{completed_result.notes}; "
                                "resident_partial_timeout_recovered=true; "
                                "partial_timeout_recovered=true; "
                                f"partial_completed_count={completed_count}; "
                                f"timeout_batch_row={batch_row}; "
                                f"batch_wall_seconds_at_timeout={batch_wall_seconds:.6f}"
                            ),
                        )
                for timeout_row, (remaining_index, remaining_cube, _) in enumerate(
                    pending[batch_row:],
                    start=batch_row,
                ):
                    results[remaining_index] = SolverResult(
                        solver_name=f"h48_native_{self.solver}",
                        input_state=remaining_cube.to_facelets(),
                        solution_moves=[],
                        solution_length=None,
                        metric="HTM",
                        runtime_seconds=batch_wall_seconds,
                        expanded_nodes=None,
                        generated_nodes=None,
                        table_bytes=table_bytes,
                        status="timeout",
                        is_verified=False,
                        notes=(
                            f"resident H48 multi-row backend timed out after {timeout_label} and was stopped; "
                            "resident_batch_pipelined=true; table_loaded_once=true; "
                            "resident_partial_timeout_recovered=true; partial_timeout_recovered=true; "
                            f"batch_input_count={len(pending)}; batch_row={timeout_row}; "
                            f"partial_completed_count={completed_count}; "
                            f"batch_wall_seconds={batch_wall_seconds:.6f}; "
                            f"stdout_wait_timeout_seconds={wait_timeout_seconds}; "
                            f"native_search_timeout_seconds={self.search_timeout_seconds}"
                        ),
                    )
                break

            line = process.stdout.readline().decode("utf-8", errors="replace").strip()
            if not line:
                stderr = process.stderr.read().decode("utf-8", errors="replace") if process.stderr else ""
                payload: dict[str, object] = {
                    "status": "failed",
                    "solution": "",
                    "solution_length": None,
                    "expanded_nodes": None,
                    "table_lookups": None,
                    "table_fallbacks": None,
                    "error": f"resident H48 backend produced no output; stderr={stderr.strip()}",
                }
            else:
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    payload = {
                        "status": "failed",
                        "solution": "",
                        "solution_length": None,
                        "expanded_nodes": None,
                        "table_lookups": None,
                        "table_fallbacks": None,
                        "error": line,
                    }
            per_case_runtime = float(payload.get("runtime_seconds") or 0.0)
            results[index] = _result_from_payload(
                cube,
                solver=self.solver,
                payload=payload,
                runtime_seconds=per_case_runtime,
                table_path=self.table_path,
                table_bytes=table_bytes,
                return_code=process.poll() if process.poll() is not None else 0,
                source_sequence_provided=False,
                mode_note=(
                    "resident in-repo native H48 backend; "
                    "resident_multi_row_backend=true; resident_batch_pipelined=true; table_loaded_once=true; "
                    f"batch_input_count={len(pending)}; batch_row={batch_row}; "
                    f"batch_wall_seconds={batch_wall_seconds:.6f}; "
                    f"stdout_wait_timeout_seconds={wait_timeout_seconds}; "
                    f"native_search_timeout_seconds={self.search_timeout_seconds}"
                    f"{self._trusted_note}"
                ),
            )
            completed_count += 1
            completed_result_indexes.append(index)

        return [result for result in results if result is not None]

    def solve_rotated_variants(
        self,
        cube: CubeState,
        *,
        variant_count: int,
        include_identity: bool = False,
        timeout_seconds: float | None = None,
        rotations: Iterable[CubeRotation] | None = None,
        rotation_order_note: str = "h48_symmetry_h48_lower_bound_rotation_order=false",
    ) -> SolverResult:
        """Try exact H48 solves on whole-cube rotations of one state.

        H48 search cost can vary with the chosen cube axis.  This method keeps
        the proof rule simple: every returned rotated solution is mapped back
        and independently verified on the original cube before it is accepted.
        """

        begin = time.perf_counter()
        rotations = (
            list(rotations)
            if rotations is not None
            else _h48_symmetry_rotations(variant_count, include_identity=include_identity)
        )
        identity_rotation_included = any(rotation.is_identity for rotation in rotations)
        if not rotations:
            return SolverResult(
                solver_name=f"h48_native_{self.solver}_symmetry_batch",
                input_state=cube.to_facelets(),
                solution_moves=[],
                solution_length=None,
                metric="HTM",
                runtime_seconds=time.perf_counter() - begin,
                expanded_nodes=None,
                generated_nodes=None,
                table_bytes=self.table_path.stat().st_size if self.table_path.exists() else 0,
                status="not_applicable",
                is_verified=False,
                notes=(
                    "resident H48 rotational symmetry batch skipped; symmetry_variants=0; "
                    f"{rotation_order_note}"
                ),
            )

        configured_timeout_seconds = (
            None if timeout_seconds is None or timeout_seconds <= 0 else max(0.0, float(timeout_seconds))
        )
        global_timeout_seconds = configured_timeout_seconds
        deadline = None if global_timeout_seconds is None else begin + global_timeout_seconds
        global_timeout_expired = False
        completed: list[tuple[str, str, bool, float]] = []
        row_timeouts: list[tuple[str, float | None]] = []
        expanded_total = 0
        saw_timeout = False
        table_bytes = self.table_path.stat().st_size if self.table_path.exists() else 0
        completed_rotation_count = 0
        for rotation in rotations:
            now = time.perf_counter()
            if deadline is None:
                row_timeout_seconds = timeout_seconds
            else:
                remaining_seconds = max(0.0, deadline - now)
                if remaining_seconds <= 0.0:
                    global_timeout_expired = True
                    saw_timeout = True
                    break
                row_timeout_seconds = remaining_seconds
            row_timeouts.append((rotation.name, row_timeout_seconds))
            rotated_cube = rotation.transform_cube(cube)
            rotated_result = self.solve(rotated_cube, timeout_seconds=row_timeout_seconds)
            completed_rotation_count += 1
            completed.append(
                (
                    rotation.name,
                    rotated_result.status,
                    bool(rotated_result.is_verified),
                    rotated_result.runtime_seconds,
                )
            )
            if rotated_result.expanded_nodes is not None:
                expanded_total += rotated_result.expanded_nodes
            if rotated_result.status == "timeout":
                saw_timeout = True
            if rotated_result.status != "exact" or not rotated_result.is_verified:
                if deadline is not None and time.perf_counter() >= deadline:
                    global_timeout_expired = True
                    saw_timeout = True
                    break
                continue

            solution = rotation.inverse_transform_sequence(rotated_result.solution_moves)
            verification = verify_solution(cube, solution)
            if not verification.ok:
                continue
            return SolverResult(
                solver_name=f"h48_native_{self.solver}_symmetry_batch",
                input_state=cube.to_facelets(),
                solution_moves=solution,
                solution_length=len(solution),
                metric=rotated_result.metric,
                runtime_seconds=time.perf_counter() - begin,
                expanded_nodes=expanded_total,
                generated_nodes=None,
                table_bytes=rotated_result.table_bytes or table_bytes,
                status="exact",
                is_verified=True,
                notes=(
                    "resident H48 rotational symmetry batch; "
                    "exactness_policy=rotated_exact_solution_mapped_back_and_verified; "
                    f"identity_rotation_included={identity_rotation_included}; "
                    f"symmetry_variants={len(rotations)}; selected_rotation={rotation.name}; "
                    f"rotation_order={[candidate.name for candidate in rotations]}; "
                    f"{rotation_order_note}; "
                    f"configured_timeout_seconds={configured_timeout_seconds}; "
                    f"global_timeout_seconds={global_timeout_seconds}; "
                    f"global_timeout_expired={global_timeout_expired}; "
                    f"pending_rotations_not_started={len(rotations) - completed_rotation_count}; "
                    f"rotated_backend_solver={rotated_result.solver_name}; "
                    f"rotated_runtime_seconds={rotated_result.runtime_seconds:.6f}; "
                    f"rotated_solution_length={rotated_result.solution_length}; "
                    f"row_timeouts={row_timeouts}; "
                    f"completed_rotations={completed}; rotated_notes={rotated_result.notes}"
                ),
            )

        return SolverResult(
            solver_name=f"h48_native_{self.solver}_symmetry_batch",
            input_state=cube.to_facelets(),
            solution_moves=[],
            solution_length=None,
            metric="HTM",
            runtime_seconds=time.perf_counter() - begin,
            expanded_nodes=expanded_total if expanded_total else None,
            generated_nodes=None,
            table_bytes=table_bytes,
            status="timeout" if saw_timeout else "failed",
            is_verified=False,
            notes=(
                "resident H48 rotational symmetry batch finished without a verified exact rotated solution; "
                f"exactness_policy=rotated_exact_solution_mapped_back_and_verified; "
                f"identity_rotation_included={identity_rotation_included}; symmetry_variants={len(rotations)}; "
                f"rotation_order={[candidate.name for candidate in rotations]}; "
                f"{rotation_order_note}; "
                f"configured_timeout_seconds={configured_timeout_seconds}; "
                f"global_timeout_seconds={global_timeout_seconds}; "
                f"global_timeout_expired={global_timeout_expired}; "
                f"pending_rotations_not_started={len(rotations) - completed_rotation_count}; "
                f"row_timeouts={row_timeouts}; completed_rotations={completed}"
            ),
        )


@dataclass
class _H48RotationRaceCandidate:
    rotation: CubeRotation
    process: subprocess.Popen[str]
    started_at: float


def _stop_h48_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=1.0)


def solve_h48_native_rotational_race(
    cube: CubeState,
    *,
    variant_count: int,
    include_identity: bool = True,
    max_concurrency: int | None = None,
    solver: str = DEFAULT_H48_SOLVER,
    profile: str = "thesis",
    seed: int = 2026,
    table_path: Path | None = None,
    timeout_seconds: float | None = 60.0,
    threads: int = 1,
    max_depth: int = 20,
    skip_table_check: bool = False,
    preload_table: bool = False,
    auto_min_depth: bool = False,
    order_by_lower_bound: bool = False,
    lower_bound_order_timeout_seconds: float = 30.0,
    root: Path | None = None,
) -> SolverResult:
    """Race exact native H48 solves over whole-cube rotations.

    This is a wall-clock optimization for hard direct-state H48 searches.  It
    preserves the exactness rule by accepting a rotated result only after the
    mapped-back solution verifies on the original cube.
    """

    begin = time.perf_counter()
    root = root or repository_root()
    if cube == CubeState.solved():
        return SolverResult(
            solver_name=f"h48_native_{solver}_parallel_symmetry_race",
            input_state=cube.to_facelets(),
            solution_moves=[],
            solution_length=0,
            metric="HTM",
            runtime_seconds=0.0,
            expanded_nodes=0,
            generated_nodes=None,
            table_bytes=0,
            status="exact",
            is_verified=True,
            notes="solved state; parallel H48 rotational race not invoked",
        )

    rotations = _h48_symmetry_rotations(variant_count, include_identity=include_identity)
    if not rotations:
        return SolverResult(
            solver_name=f"h48_native_{solver}_parallel_symmetry_race",
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
            notes="parallel H48 rotational race skipped; symmetry_variants=0",
        )

    table_path = table_path or h48_table_path(root=root, profile=profile, seed=seed, solver=solver)
    table_bytes = table_path.stat().st_size if table_path.exists() else 0
    if not table_path.exists():
        return SolverResult(
            solver_name=f"h48_native_{solver}_parallel_symmetry_race",
            input_state=cube.to_facelets(),
            solution_moves=[],
            solution_length=None,
            metric="HTM",
            runtime_seconds=time.perf_counter() - begin,
            expanded_nodes=None,
            generated_nodes=None,
            table_bytes=0,
            status="failed",
            is_verified=False,
            notes=f"parallel H48 rotational race missing required table: {table_path}",
        )

    trusted_note = ""
    if skip_table_check:
        trusted_ok, trusted_message = validate_trusted_h48_table(
            root=root,
            profile=profile,
            seed=seed,
            solver=solver,
            table_path=table_path,
        )
        if not trusted_ok:
            return SolverResult(
                solver_name=f"h48_native_{solver}_parallel_symmetry_race",
                input_state=cube.to_facelets(),
                solution_moves=[],
                solution_length=None,
                metric="HTM",
                runtime_seconds=time.perf_counter() - begin,
                expanded_nodes=None,
                generated_nodes=None,
                table_bytes=table_bytes,
                status="failed",
                is_verified=False,
                notes=f"parallel H48 rotational race trusted table rejected: {trusted_message}",
            )
        trusted_note = f"; trusted_table_metadata=valid; trusted_table_note={trusted_message}"

    binary = build_h48_backend(root=root, threads=threads)
    lower_bound_order_note = "h48_lower_bound_rotation_order=false"
    if order_by_lower_bound:
        rotations, lower_bound_order_note = order_h48_rotations_by_lower_bound(
            cube,
            rotations,
            binary=binary,
            solver=solver,
            table_path=table_path,
            timeout_seconds=lower_bound_order_timeout_seconds,
            threads=threads,
            skip_table_check=skip_table_check,
            preload_table=preload_table,
            root=root,
        )
    candidates: list[_H48RotationRaceCandidate] = []
    setup_errors: list[tuple[str, str]] = []
    completed: list[tuple[str, str, bool, float]] = []
    expanded_total = 0
    saw_timeout = False
    per_candidate_timeouts: list[str] = []
    per_candidate_native_search_timeouts: list[tuple[str, int | None]] = []
    concurrency = len(rotations) if max_concurrency is None or max_concurrency <= 0 else max(1, int(max_concurrency))
    concurrency = min(concurrency, len(rotations))
    wave_count = (len(rotations) + concurrency - 1) // concurrency
    total_timeout_seconds = None if timeout_seconds is None or timeout_seconds <= 0 else timeout_seconds
    deadline = None if total_timeout_seconds is None else begin + total_timeout_seconds
    next_rotation_index = 0

    try:
        def can_start_more() -> bool:
            return deadline is None or time.perf_counter() < deadline

        def start_candidate(rotation: CubeRotation) -> _H48RotationRaceCandidate | None:
            rotated_cube = rotation.transform_cube(cube)
            native_timeout_seconds = timeout_seconds
            if deadline is not None:
                remaining_global_seconds = max(0.001, deadline - time.perf_counter())
                native_timeout_seconds = (
                    remaining_global_seconds
                    if native_timeout_seconds is None or native_timeout_seconds <= 0
                    else min(native_timeout_seconds, remaining_global_seconds)
                )
            native_search_timeout_ms = _timeout_seconds_to_ms(native_timeout_seconds)
            per_candidate_native_search_timeouts.append((rotation.name, native_search_timeout_ms))
            command = [
                str(binary),
                "--solve",
                "--solver",
                solver,
                "--table",
                str(table_path),
                "--cube",
                cube_to_nissy_string(rotated_cube),
                "--threads",
                str(max(1, threads)),
                "--max-depth",
                str(max_depth),
            ]
            if skip_table_check:
                command.append("--skip-table-check")
            if preload_table:
                command.append("--preload-table")
            if auto_min_depth:
                command.append("--auto-min-depth")
            if native_search_timeout_ms is not None:
                command.extend(["--search-timeout-ms", str(native_search_timeout_ms)])
            try:
                process = subprocess.Popen(
                    command,
                    cwd=root,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
            except Exception as exc:
                setup_errors.append((rotation.name, str(exc)))
                return None
            candidate = _H48RotationRaceCandidate(
                rotation=rotation,
                process=process,
                started_at=time.perf_counter(),
            )
            candidates.append(candidate)
            return candidate

        active: list[_H48RotationRaceCandidate] = []
        while next_rotation_index < len(rotations) and len(active) < concurrency and can_start_more():
            candidate = start_candidate(rotations[next_rotation_index])
            next_rotation_index += 1
            if candidate is not None:
                active.append(candidate)

        if not candidates:
            return SolverResult(
                solver_name=f"h48_native_{solver}_parallel_symmetry_race",
                input_state=cube.to_facelets(),
                solution_moves=[],
                solution_length=None,
                metric="HTM",
                runtime_seconds=time.perf_counter() - begin,
                expanded_nodes=None,
                generated_nodes=None,
                table_bytes=table_bytes,
                status="failed",
                is_verified=False,
                notes=f"parallel H48 rotational race could not start any candidate; setup_errors={setup_errors}",
            )

        while active or next_rotation_index < len(rotations):
            now = time.perf_counter()
            for candidate in list(active):
                return_code = candidate.process.poll()
                rotated_runtime = now - candidate.started_at
                global_timeout = deadline is not None and now >= deadline
                if (
                    return_code is None
                    and (
                        global_timeout
                        or (
                            timeout_seconds is not None
                            and timeout_seconds > 0
                            and rotated_runtime >= timeout_seconds
                        )
                    )
                ):
                    _stop_h48_process(candidate.process)
                    candidate.process.communicate()
                    active.remove(candidate)
                    saw_timeout = True
                    per_candidate_timeouts.append(candidate.rotation.name)
                    rotated_runtime = time.perf_counter() - candidate.started_at
                    completed.append((candidate.rotation.name, "timeout", False, rotated_runtime))
                    while (
                        next_rotation_index < len(rotations)
                        and len(active) < concurrency
                        and can_start_more()
                    ):
                        next_candidate = start_candidate(rotations[next_rotation_index])
                        next_rotation_index += 1
                        if next_candidate is not None:
                            active.append(next_candidate)
                    continue
                if return_code is None:
                    continue
                stdout, stderr = candidate.process.communicate()
                active.remove(candidate)
                rotated_runtime = time.perf_counter() - candidate.started_at
                rotated_cube = candidate.rotation.transform_cube(cube)
                try:
                    payload = json.loads(stdout)
                except json.JSONDecodeError:
                    payload = {
                        "status": "failed",
                        "solution": "",
                        "solution_length": None,
                        "expanded_nodes": None,
                        "table_lookups": None,
                        "table_fallbacks": None,
                        "error": stderr.strip() or stdout.strip(),
                    }
                rotated_result = _result_from_payload(
                    rotated_cube,
                    solver=solver,
                    payload=payload,
                    runtime_seconds=rotated_runtime,
                    table_path=table_path,
                    table_bytes=table_bytes,
                    return_code=return_code,
                    source_sequence_provided=False,
                    mode_note="parallel H48 rotational race candidate",
                )
                completed.append(
                    (
                        candidate.rotation.name,
                        rotated_result.status,
                        bool(rotated_result.is_verified),
                        rotated_result.runtime_seconds,
                    )
                )
                if rotated_result.expanded_nodes is not None:
                    expanded_total += rotated_result.expanded_nodes
                if rotated_result.status == "timeout":
                    saw_timeout = True
                if not _is_exact_verified_h48(rotated_result):
                    while (
                        next_rotation_index < len(rotations)
                        and len(active) < concurrency
                        and can_start_more()
                    ):
                        next_candidate = start_candidate(rotations[next_rotation_index])
                        next_rotation_index += 1
                        if next_candidate is not None:
                            active.append(next_candidate)
                    continue

                solution = candidate.rotation.inverse_transform_sequence(rotated_result.solution_moves)
                verification = verify_solution(cube, solution)
                if not verification.ok:
                    continue
                killed_rotations = [item.rotation.name for item in active if item.process.poll() is None]
                for loser in active:
                    _stop_h48_process(loser.process)
                return SolverResult(
                    solver_name=f"h48_native_{solver}_parallel_symmetry_race",
                    input_state=cube.to_facelets(),
                    solution_moves=solution,
                    solution_length=len(solution),
                    metric=rotated_result.metric,
                    runtime_seconds=time.perf_counter() - begin,
                    expanded_nodes=expanded_total if expanded_total else rotated_result.expanded_nodes,
                    generated_nodes=None,
                    table_bytes=rotated_result.table_bytes or table_bytes,
                    status="exact",
                    is_verified=True,
                    notes=(
                        "parallel H48 rotational symmetry race; "
                        "exactness_policy=first_rotated_exact_solution_mapped_back_and_verified; "
                        f"identity_rotation_included={include_identity}; "
                        f"symmetry_variants={len(rotations)}; started_rotations={[item.rotation.name for item in candidates]}; "
                        f"max_concurrency={concurrency}; parallel_wave_count={wave_count}; "
                        f"effective_total_timeout_seconds={total_timeout_seconds}; "
                        f"global_timeout_seconds={total_timeout_seconds}; "
                        f"pending_rotations_not_started={len(rotations) - next_rotation_index}; "
                        f"selected_rotation={candidate.rotation.name}; "
                        f"killed_rotations={killed_rotations if killed_rotations else 'none'}; "
                        f"per_candidate_timeouts={per_candidate_timeouts}; "
                        "native_search_timeout_clipped_to_remaining_global_budget=true; "
                        f"per_candidate_native_search_timeout_ms={per_candidate_native_search_timeouts}; "
                        f"rotated_backend_solver={rotated_result.solver_name}; "
                        f"rotated_runtime_seconds={rotated_result.runtime_seconds:.6f}; "
                        f"rotated_solution_length={rotated_result.solution_length}; "
                        f"race_timeout_seconds={timeout_seconds}; per_rotation_timeout_seconds={timeout_seconds}; "
                        f"per_candidate_threads={max(1, threads)}; "
                        f"{lower_bound_order_note}; "
                        f"setup_errors={setup_errors}; completed_rotations={completed}; "
                        f"rotated_notes={rotated_result.notes}{trusted_note}"
                    ),
                )

            if deadline is not None and time.perf_counter() >= deadline:
                saw_timeout = True
                break

            if active:
                sleep_for = 0.05
                if deadline is not None:
                    sleep_for = min(sleep_for, max(0.0, deadline - time.perf_counter()))
                time.sleep(sleep_for)
            else:
                while next_rotation_index < len(rotations) and len(active) < concurrency and can_start_more():
                    next_candidate = start_candidate(rotations[next_rotation_index])
                    next_rotation_index += 1
                    if next_candidate is not None:
                        active.append(next_candidate)
    finally:
        for candidate in candidates:
            _stop_h48_process(candidate.process)

    status = "timeout" if saw_timeout or candidates else "failed"
    return SolverResult(
        solver_name=f"h48_native_{solver}_parallel_symmetry_race",
        input_state=cube.to_facelets(),
        solution_moves=[],
        solution_length=None,
        metric="HTM",
        runtime_seconds=time.perf_counter() - begin,
        expanded_nodes=expanded_total if expanded_total else None,
        generated_nodes=None,
        table_bytes=table_bytes,
        status=status,
        is_verified=False,
        notes=(
            "parallel H48 rotational symmetry race finished without a verified exact rotated solution; "
            f"exactness_policy=first_rotated_exact_solution_mapped_back_and_verified; "
            f"identity_rotation_included={include_identity}; symmetry_variants={len(rotations)}; "
            f"started_rotations={[item.rotation.name for item in candidates]}; "
            f"max_concurrency={concurrency}; parallel_wave_count={wave_count}; "
            f"effective_total_timeout_seconds={total_timeout_seconds}; "
            f"global_timeout_seconds={total_timeout_seconds}; "
            f"pending_rotations_not_started={len(rotations) - next_rotation_index}; "
            f"race_timeout_seconds={timeout_seconds}; per_rotation_timeout_seconds={timeout_seconds}; "
            f"per_candidate_threads={max(1, threads)}; "
            "native_search_timeout_clipped_to_remaining_global_budget=true; "
            f"per_candidate_native_search_timeout_ms={per_candidate_native_search_timeouts}; "
            f"{lower_bound_order_note}; "
            f"per_candidate_timeouts={per_candidate_timeouts}; "
            f"setup_errors={setup_errors}; completed_rotations={completed}{trusted_note}"
        ),
    )


def _is_exact_verified_h48(result: SolverResult) -> bool:
    return result.status == "exact" and result.is_verified


def _h48_symmetry_rotations(variant_count: int, *, include_identity: bool) -> list[CubeRotation]:
    identity = next((rotation for rotation in CUBE_ROTATIONS if rotation.is_identity), None)
    non_identity = [rotation for rotation in CUBE_ROTATIONS if not rotation.is_identity]
    target_non_identity_count = max(0, int(variant_count))
    selected: list[CubeRotation] = []
    seen_matrices = set()

    def add(rotation: CubeRotation) -> bool:
        if rotation.matrix in seen_matrices:
            return False
        selected.append(rotation)
        seen_matrices.add(rotation.matrix)
        return True

    def selected_non_identity_count() -> int:
        return sum(1 for rotation in selected if not rotation.is_identity)

    if include_identity and identity is not None:
        add(identity)

    for axis_group in _H48_SYMMETRY_AXIS_GROUP_ORDER:
        if selected_non_identity_count() >= target_non_identity_count:
            break
        representative = next(
            (
                rotation
                for rotation in non_identity
                if _h48_symmetry_axis_key(rotation) == axis_group
            ),
            None,
        )
        if representative is not None:
            add(representative)

    for rotation in non_identity:
        if selected_non_identity_count() >= target_non_identity_count:
            break
        add(rotation)
    return selected


def order_h48_rotations_by_lower_bound(
    cube: CubeState,
    rotations: list[CubeRotation],
    *,
    binary: Path | None = None,
    solver: str,
    table_path: Path,
    timeout_seconds: float,
    threads: int,
    skip_table_check: bool,
    preload_table: bool,
    root: Path,
) -> tuple[list[CubeRotation], str]:
    """Order H48 race rotations by descending admissible lower bound."""

    if binary is None:
        binary = build_h48_backend(root=root, threads=threads)
    if len(rotations) <= 1:
        return rotations, "h48_lower_bound_rotation_order=true; order_status=skipped_single_rotation"
    try:
        rotated_input = "\n".join(cube_to_nissy_string(rotation.transform_cube(cube)) for rotation in rotations) + "\n"
    except Exception as exc:
        return rotations, f"h48_lower_bound_rotation_order=true; order_status=conversion_failed; order_error={exc}"

    command = [
        str(binary),
        "--lower-bound-batch",
        "--solver",
        solver,
        "--table",
        str(table_path),
        "--threads",
        str(max(1, threads)),
    ]
    if skip_table_check:
        command.append("--skip-table-check")
    if preload_table:
        command.append("--preload-table")

    begin = time.perf_counter()
    timed_out = False
    return_code: int | None = None
    stderr_text = ""
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            input=rotated_input,
            text=True,
            capture_output=True,
            timeout=max(0.001, float(timeout_seconds)),
            check=False,
        )
        stdout_text = completed.stdout
        stderr_text = completed.stderr.strip()
        return_code = completed.returncode
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout_text = _subprocess_text(exc.stdout)
        stderr_text = _subprocess_text(exc.stderr).strip()

    rows, failed_rows, parse_errors, stdout_line_count = _parse_h48_lower_bound_rows(stdout_text, rotations)

    if not rows:
        status = "timeout" if timed_out else "no_valid_bounds"
        return (
            rotations,
            (
                f"h48_lower_bound_rotation_order=true; order_status={status}; "
                f"order_timeout_seconds={timeout_seconds}; return_code={return_code}; "
                f"stdout_line_count={stdout_line_count}; parse_errors={parse_errors}; "
                f"failed_rows={failed_rows}; stderr={stderr_text}"
            ),
        )

    ranked = sorted(rows, key=lambda row: (-row[2], row[0]))
    ranked_indexes = {index for index, _rotation, _lower_bound, _runtime, _payload in ranked}
    remaining = [(index, rotation) for index, rotation in enumerate(rotations) if index not in ranked_indexes]
    ordered_rotations = [rotation for _index, rotation, _lower_bound, _runtime, _payload in ranked] + [
        rotation for _index, rotation in remaining
    ]
    valid_bounds = [
        (rotation.name, lower_bound, runtime_seconds)
        for _index, rotation, lower_bound, runtime_seconds, _payload in rows
    ]
    order_status = "partial_timeout_recovered" if timed_out else "applied"
    return (
        ordered_rotations,
        (
            f"h48_lower_bound_rotation_order=true; order_status={order_status}; "
            f"order_runtime_seconds={time.perf_counter() - begin:.6f}; "
            f"order_timeout_seconds={timeout_seconds}; return_code={return_code}; "
            f"partial_timeout_recovered={'true' if timed_out else 'false'}; "
            f"partial_completed_count={len(rows)}; rotation_count={len(rotations)}; "
            f"valid_bounds={valid_bounds}; failed_rows={failed_rows}; parse_errors={parse_errors}; "
            f"ordered_rotations={[rotation.name for rotation in ordered_rotations]}; "
            f"stdout_line_count={stdout_line_count}; stderr={stderr_text}"
        ),
    )


_order_h48_rotations_by_lower_bound = order_h48_rotations_by_lower_bound


def _h48_symmetry_axis_key(rotation: CubeRotation) -> str:
    target_up_face = rotation.face_map["U"]
    if target_up_face in {"F", "B"}:
        return "FB"
    if target_up_face in {"R", "L"}:
        return "RL"
    return "UD"


def solve_h48_native_resident_batch(
    cubes: Iterable[CubeState],
    *,
    solver: str = DEFAULT_H48_SOLVER,
    profile: str = "thesis",
    seed: int = 2026,
    table_path: Path | None = None,
    timeout_seconds: float | None = 300.0,
    threads: int = 8,
    max_depth: int = 20,
    skip_table_check: bool = False,
    preload_table: bool = False,
    auto_min_depth: bool = False,
    root: Path | None = None,
) -> list[SolverResult]:
    with H48NativeOracleSession(
        solver=solver,
        profile=profile,
        seed=seed,
        table_path=table_path,
        threads=threads,
        max_depth=max_depth,
        skip_table_check=skip_table_check,
        preload_table=preload_table,
        auto_min_depth=auto_min_depth,
        root=root,
        search_timeout_seconds=timeout_seconds,
    ) as session:
        return session.solve_many(cubes, timeout_seconds=timeout_seconds)


def solve_h48_native_optimal(
    cube: CubeState,
    *,
    source_sequence: list[str] | tuple[str, ...] | None = None,
    solver: str = DEFAULT_H48_SOLVER,
    profile: str = "thesis",
    seed: int = 2026,
    table_path: Path | None = None,
    timeout_seconds: float | None = 300.0,
    threads: int = 8,
    max_depth: int = 20,
    skip_table_check: bool = False,
    preload_table: bool = False,
    auto_min_depth: bool = False,
    root: Path | None = None,
) -> SolverResult:
    """Run the in-repo native H48 backend.

    This path returns only exact or timeout/failed statuses. Non-solved inputs
    are passed as a direct cubie-state conversion to nissy-core's compact cube
    string format, so it does not require the scramble sequence that produced
    the state.
    """

    root = root or repository_root()
    if cube == CubeState.solved():
        return SolverResult(
            solver_name=f"h48_native_{solver}",
            input_state=cube.to_facelets(),
            solution_moves=[],
            solution_length=0,
            metric="HTM",
            runtime_seconds=0.0,
            expanded_nodes=0,
            generated_nodes=None,
            table_bytes=0,
            status="exact",
            is_verified=True,
            notes="solved state; H48 backend not invoked",
        )

    table_path = table_path or h48_table_path(root=root, profile=profile, seed=seed, solver=solver)
    if not table_path.exists():
        return SolverResult(
            solver_name=f"h48_native_{solver}",
            input_state=cube.to_facelets(),
            solution_moves=[],
            solution_length=None,
            metric="HTM",
            runtime_seconds=0.0,
            expanded_nodes=None,
            generated_nodes=None,
            table_bytes=0,
            status="failed",
            is_verified=False,
            notes=f"missing required H48 table: {table_path}",
        )
    trusted_note = ""
    if skip_table_check:
        trusted_ok, trusted_message = validate_trusted_h48_table(
            root=root,
            profile=profile,
            seed=seed,
            solver=solver,
            table_path=table_path,
        )
        if not trusted_ok:
            return SolverResult(
                solver_name=f"h48_native_{solver}",
                input_state=cube.to_facelets(),
                solution_moves=[],
                solution_length=None,
                metric="HTM",
                runtime_seconds=0.0,
                expanded_nodes=None,
                generated_nodes=None,
                table_bytes=table_path.stat().st_size if table_path.exists() else 0,
                status="failed",
                is_verified=False,
                notes=f"trusted H48 table rejected: {trusted_message}",
            )
        trusted_note = f"; trusted_table_metadata=valid; trusted_table_note={trusted_message}"

    binary = build_h48_backend(root=root, threads=threads)
    nissy_cube = cube_to_nissy_string(cube)
    command = [
        str(binary),
        "--solve",
        "--solver",
        solver,
        "--table",
        str(table_path),
        "--cube",
        nissy_cube,
        "--threads",
        str(max(1, threads)),
        "--max-depth",
        str(max_depth),
    ]
    if skip_table_check:
        command.append("--skip-table-check")
    if preload_table:
        command.append("--preload-table")
    if auto_min_depth:
        command.append("--auto-min-depth")
    search_timeout_ms = _timeout_seconds_to_ms(timeout_seconds)
    if search_timeout_ms is not None:
        command.extend(["--search-timeout-ms", str(search_timeout_ms)])
    begin = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            text=True,
            capture_output=True,
            timeout=_process_timeout_with_grace(timeout_seconds),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        timeout_label = "unbounded" if timeout_seconds is None else f"{timeout_seconds}s"
        return SolverResult(
            solver_name=f"h48_native_{solver}",
            input_state=cube.to_facelets(),
            solution_moves=[],
            solution_length=None,
            metric="HTM",
            runtime_seconds=time.perf_counter() - begin,
            expanded_nodes=None,
            generated_nodes=None,
            table_bytes=table_path.stat().st_size,
            status="timeout",
            is_verified=False,
            notes=f"in-repo H48 backend timed out after {timeout_label}; partial_stdout={exc.stdout!r}",
        )

    runtime_seconds = time.perf_counter() - begin
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        payload = {
            "status": "failed",
            "solution": "",
            "solution_length": None,
            "expanded_nodes": None,
            "table_lookups": None,
            "table_fallbacks": None,
            "error": completed.stderr.strip() or completed.stdout.strip(),
        }
    return _result_from_payload(
        cube,
        solver=solver,
        payload=payload,
        runtime_seconds=runtime_seconds,
        table_path=table_path,
        table_bytes=table_path.stat().st_size,
        return_code=completed.returncode,
        source_sequence_provided=source_sequence is not None,
        mode_note=f"in-repo native H48 backend{trusted_note}",
    )


def compute_h48_native_lower_bound(
    cube: CubeState,
    *,
    solver: str = DEFAULT_H48_SOLVER,
    profile: str = "thesis",
    seed: int = 2026,
    table_path: Path | None = None,
    timeout_seconds: float = 30.0,
    threads: int = 8,
    skip_table_check: bool = False,
    preload_table: bool = False,
    root: Path | None = None,
) -> H48LowerBoundResult:
    """Compute the H48 admissible lower bound for a direct cube state."""

    root = root or repository_root()
    if cube == CubeState.solved():
        return H48LowerBoundResult(
            solver_name=f"h48_native_{solver}_lower_bound",
            input_state=cube.to_facelets(),
            lower_bound=0,
            runtime_seconds=0.0,
            table_bytes=0,
            status="lower_bound",
            notes="solved state; H48 lower-bound backend not invoked",
        )

    table_path = table_path or h48_table_path(root=root, profile=profile, seed=seed, solver=solver)
    if not table_path.exists():
        return H48LowerBoundResult(
            solver_name=f"h48_native_{solver}_lower_bound",
            input_state=cube.to_facelets(),
            lower_bound=None,
            runtime_seconds=0.0,
            table_bytes=0,
            status="failed",
            notes=f"missing required H48 table: {table_path}",
        )
    trusted_note = ""
    if skip_table_check:
        trusted_ok, trusted_message = validate_trusted_h48_table(
            root=root,
            profile=profile,
            seed=seed,
            solver=solver,
            table_path=table_path,
        )
        if not trusted_ok:
            return H48LowerBoundResult(
                solver_name=f"h48_native_{solver}_lower_bound",
                input_state=cube.to_facelets(),
                lower_bound=None,
                runtime_seconds=0.0,
                table_bytes=table_path.stat().st_size if table_path.exists() else 0,
                status="failed",
                notes=f"trusted H48 table rejected: {trusted_message}",
            )
        trusted_note = f"; trusted_table_metadata=valid; trusted_table_note={trusted_message}"

    binary = build_h48_backend(root=root, threads=threads)
    command = [
        str(binary),
        "--lower-bound",
        "--solver",
        solver,
        "--table",
        str(table_path),
        "--cube",
        cube_to_nissy_string(cube),
        "--threads",
        str(max(1, threads)),
    ]
    if skip_table_check:
        command.append("--skip-table-check")
    if preload_table:
        command.append("--preload-table")
    begin = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return H48LowerBoundResult(
            solver_name=f"h48_native_{solver}_lower_bound",
            input_state=cube.to_facelets(),
            lower_bound=None,
            runtime_seconds=time.perf_counter() - begin,
            table_bytes=table_path.stat().st_size,
            status="timeout",
            notes=f"in-repo H48 lower-bound backend timed out after {timeout_seconds}s; partial_stdout={exc.stdout!r}",
        )

    runtime_seconds = time.perf_counter() - begin
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return H48LowerBoundResult(
            solver_name=f"h48_native_{solver}_lower_bound",
            input_state=cube.to_facelets(),
            lower_bound=None,
            runtime_seconds=runtime_seconds,
            table_bytes=table_path.stat().st_size,
            status="failed",
            notes=f"could not parse H48 lower-bound JSON; stdout={completed.stdout.strip()}; stderr={completed.stderr.strip()}",
        )

    status = str(payload.get("status", "failed"))
    lower_bound = payload.get("lower_bound")
    return H48LowerBoundResult(
        solver_name=f"h48_native_{solver}_lower_bound",
        input_state=cube.to_facelets(),
        lower_bound=int(lower_bound) if status == "lower_bound" and lower_bound is not None else None,
        runtime_seconds=runtime_seconds,
        table_bytes=int(payload.get("table_size_bytes") or table_path.stat().st_size),
        status=status if status == "lower_bound" else "failed",
        notes=(
            f"in-repo native H48 admissible lower-bound probe{trusted_note}; "
            f"return_code={completed.returncode}; "
            f"backend_runtime_seconds={payload.get('runtime_seconds')}; "
            f"table_check={payload.get('table_check')}; "
            f"table_storage={payload.get('table_storage')}; "
            f"table_preload={payload.get('table_preload')}; "
            f"stderr={completed.stderr.strip()}"
        ),
    )


def compute_h48_native_lower_bound_batch(
    cubes: Iterable[CubeState],
    *,
    solver: str = DEFAULT_H48_SOLVER,
    profile: str = "thesis",
    seed: int = 2026,
    table_path: Path | None = None,
    timeout_seconds: float = 30.0,
    threads: int = 8,
    skip_table_check: bool = False,
    preload_table: bool = False,
    root: Path | None = None,
) -> list[H48LowerBoundResult]:
    """Compute H48 admissible lower bounds for many cube states after one table load."""

    root = root or repository_root()
    cube_list = list(cubes)
    results: list[H48LowerBoundResult | None] = [None] * len(cube_list)
    pending: list[tuple[int, CubeState]] = []
    for index, cube in enumerate(cube_list):
        if cube == CubeState.solved():
            results[index] = H48LowerBoundResult(
                solver_name=f"h48_native_{solver}_lower_bound_batch",
                input_state=cube.to_facelets(),
                lower_bound=0,
                runtime_seconds=0.0,
                table_bytes=0,
                status="lower_bound",
                notes="solved state; H48 multi-cube lower-bound batch backend not invoked for this row",
            )
        else:
            pending.append((index, cube))
    if not pending:
        return [result for result in results if result is not None]

    table_path = table_path or h48_table_path(root=root, profile=profile, seed=seed, solver=solver)
    if not table_path.exists():
        for index, cube in pending:
            results[index] = H48LowerBoundResult(
                solver_name=f"h48_native_{solver}_lower_bound_batch",
                input_state=cube.to_facelets(),
                lower_bound=None,
                runtime_seconds=0.0,
                table_bytes=0,
                status="failed",
                notes=f"missing required H48 table for multi-cube lower-bound batch: {table_path}",
            )
        return [result for result in results if result is not None]

    trusted_note = ""
    if skip_table_check:
        trusted_ok, trusted_message = validate_trusted_h48_table(
            root=root,
            profile=profile,
            seed=seed,
            solver=solver,
            table_path=table_path,
        )
        if not trusted_ok:
            for index, cube in pending:
                results[index] = H48LowerBoundResult(
                    solver_name=f"h48_native_{solver}_lower_bound_batch",
                    input_state=cube.to_facelets(),
                    lower_bound=None,
                    runtime_seconds=0.0,
                    table_bytes=table_path.stat().st_size,
                    status="failed",
                    notes=f"trusted H48 table rejected for multi-cube lower-bound batch: {trusted_message}",
                )
            return [result for result in results if result is not None]
        trusted_note = f"; trusted_table_metadata=valid; trusted_table_note={trusted_message}"

    try:
        batch_input = "\n".join(cube_to_nissy_string(cube) for _, cube in pending) + "\n"
    except Exception as exc:
        for index, cube in pending:
            results[index] = H48LowerBoundResult(
                solver_name=f"h48_native_{solver}_lower_bound_batch",
                input_state=cube.to_facelets(),
                lower_bound=None,
                runtime_seconds=0.0,
                table_bytes=table_path.stat().st_size,
                status="failed",
                notes=f"could not convert cube to nissy-core state for multi-cube lower-bound batch: {exc}",
            )
        return [result for result in results if result is not None]

    binary = build_h48_backend(root=root, threads=threads)
    command = [
        str(binary),
        "--lower-bound-batch",
        "--solver",
        solver,
        "--table",
        str(table_path),
        "--threads",
        str(max(1, threads)),
    ]
    if skip_table_check:
        command.append("--skip-table-check")
    if preload_table:
        command.append("--preload-table")

    begin = time.perf_counter()
    timed_out = False
    return_code: int | None = None
    stderr_text = ""
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            input=batch_input,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
        stdout_text = completed.stdout
        stderr_text = completed.stderr.strip()
        return_code = completed.returncode
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout_text = _subprocess_text(exc.stdout)
        stderr_text = _subprocess_text(exc.stderr).strip()

    runtime_seconds = time.perf_counter() - begin
    stdout_lines = [line for line in stdout_text.splitlines() if line.strip()]
    parse_errors: list[tuple[int, str]] = []
    failed_rows: list[tuple[int, str, object]] = []
    table_bytes = table_path.stat().st_size
    for row_index, (original_index, cube) in enumerate(pending):
        if row_index >= len(stdout_lines):
            results[original_index] = H48LowerBoundResult(
                solver_name=f"h48_native_{solver}_lower_bound_batch",
                input_state=cube.to_facelets(),
                lower_bound=None,
                runtime_seconds=runtime_seconds,
                table_bytes=table_bytes,
                status="timeout" if timed_out else "failed",
                notes=(
                    f"in-repo native H48 admissible multi-cube lower-bound batch{trusted_note}; "
                    f"table_loaded_once=true; batch_input_count={len(pending)}; batch_row={row_index}; "
                    f"return_code={return_code}; partial_timeout_recovered={'true' if timed_out else 'false'}; "
                    f"stdout_line_count={len(stdout_lines)}; missing_output_row=true; "
                    f"parse_errors={parse_errors}; failed_rows={failed_rows}; stderr={stderr_text}"
                ),
            )
            continue
        line = stdout_lines[row_index].strip()
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            parse_errors.append((row_index, line))
            results[original_index] = H48LowerBoundResult(
                solver_name=f"h48_native_{solver}_lower_bound_batch",
                input_state=cube.to_facelets(),
                lower_bound=None,
                runtime_seconds=runtime_seconds,
                table_bytes=table_bytes,
                status="failed",
                notes=(
                    f"in-repo native H48 admissible multi-cube lower-bound batch{trusted_note}; "
                    f"table_loaded_once=true; batch_input_count={len(pending)}; batch_row={row_index}; "
                    f"return_code={return_code}; partial_timeout_recovered={'true' if timed_out else 'false'}; "
                    f"stdout_line_count={len(stdout_lines)}; parse_errors={parse_errors}; stderr={stderr_text}"
                ),
            )
            continue
        status = str(payload.get("status", "failed"))
        lower_bound = payload.get("lower_bound")
        if status != "lower_bound" or lower_bound is None:
            failed_rows.append((row_index, status, payload.get("error", "")))
            results[original_index] = H48LowerBoundResult(
                solver_name=f"h48_native_{solver}_lower_bound_batch",
                input_state=cube.to_facelets(),
                lower_bound=None,
                runtime_seconds=runtime_seconds,
                table_bytes=int(payload.get("table_size_bytes") or table_bytes),
                status="failed",
                notes=(
                    f"in-repo native H48 admissible multi-cube lower-bound batch{trusted_note}; "
                    f"table_loaded_once=true; batch_input_count={len(pending)}; batch_row={row_index}; "
                    f"return_code={return_code}; row_status={status}; row_error={payload.get('error', '')}; "
                    f"partial_timeout_recovered={'true' if timed_out else 'false'}; "
                    f"stdout_line_count={len(stdout_lines)}; failed_rows={failed_rows}; stderr={stderr_text}"
                ),
            )
            continue
        results[original_index] = H48LowerBoundResult(
            solver_name=f"h48_native_{solver}_lower_bound_batch",
            input_state=cube.to_facelets(),
            lower_bound=int(lower_bound),
            runtime_seconds=runtime_seconds,
            table_bytes=int(payload.get("table_size_bytes") or table_bytes),
            status="lower_bound",
            notes=(
                f"in-repo native H48 admissible multi-cube lower-bound batch{trusted_note}; "
                f"table_loaded_once=true; batch_input_count={len(pending)}; batch_row={row_index}; "
                f"return_code={return_code}; backend_runtime_seconds={payload.get('runtime_seconds')}; "
                f"partial_timeout_recovered={'true' if timed_out else 'false'}; "
                f"stdout_line_count={len(stdout_lines)}; table_check={payload.get('table_check')}; "
                f"table_storage={payload.get('table_storage')}; table_preload={payload.get('table_preload')}; "
                f"stderr={stderr_text}"
            ),
        )

    return [result for result in results if result is not None]


def compute_h48_native_rotational_lower_bound(
    cube: CubeState,
    *,
    variant_count: int,
    include_identity: bool = True,
    solver: str = DEFAULT_H48_SOLVER,
    profile: str = "thesis",
    seed: int = 2026,
    table_path: Path | None = None,
    timeout_seconds: float = 30.0,
    threads: int = 8,
    skip_table_check: bool = False,
    preload_table: bool = False,
    root: Path | None = None,
) -> H48LowerBoundResult:
    """Compute the strongest H48 lower bound over whole-cube rotations.

    Each rotated state is the same physical cube under a solved-preserving
    automorphism, so the maximum of their H48 lower bounds is still admissible
    for the original cube.  A single native process loads the table once and
    reads rotated compact cube strings through ``--lower-bound-batch``.
    """

    rotations = _h48_symmetry_rotations(variant_count, include_identity=include_identity)
    if not rotations:
        return compute_h48_native_lower_bound(
            cube,
            solver=solver,
            profile=profile,
            seed=seed,
            table_path=table_path,
            timeout_seconds=timeout_seconds,
            threads=threads,
            skip_table_check=skip_table_check,
            preload_table=preload_table,
            root=root,
        )

    root = root or repository_root()
    if cube == CubeState.solved():
        return H48LowerBoundResult(
            solver_name=f"h48_native_{solver}_rotational_lower_bound",
            input_state=cube.to_facelets(),
            lower_bound=0,
            runtime_seconds=0.0,
            table_bytes=0,
            status="lower_bound",
            notes="solved state; H48 rotational lower-bound backend not invoked",
        )

    table_path = table_path or h48_table_path(root=root, profile=profile, seed=seed, solver=solver)
    if not table_path.exists():
        return H48LowerBoundResult(
            solver_name=f"h48_native_{solver}_rotational_lower_bound",
            input_state=cube.to_facelets(),
            lower_bound=None,
            runtime_seconds=0.0,
            table_bytes=0,
            status="failed",
            notes=f"missing required H48 table: {table_path}",
        )

    trusted_note = ""
    if skip_table_check:
        trusted_ok, trusted_message = validate_trusted_h48_table(
            root=root,
            profile=profile,
            seed=seed,
            solver=solver,
            table_path=table_path,
        )
        if not trusted_ok:
            return H48LowerBoundResult(
                solver_name=f"h48_native_{solver}_rotational_lower_bound",
                input_state=cube.to_facelets(),
                lower_bound=None,
                runtime_seconds=0.0,
                table_bytes=table_path.stat().st_size if table_path.exists() else 0,
                status="failed",
                notes=f"trusted H48 table rejected: {trusted_message}",
            )
        trusted_note = f"; trusted_table_metadata=valid; trusted_table_note={trusted_message}"

    try:
        rotated_input = "\n".join(cube_to_nissy_string(rotation.transform_cube(cube)) for rotation in rotations) + "\n"
    except Exception as exc:
        return H48LowerBoundResult(
            solver_name=f"h48_native_{solver}_rotational_lower_bound",
            input_state=cube.to_facelets(),
            lower_bound=None,
            runtime_seconds=0.0,
            table_bytes=table_path.stat().st_size,
            status="failed",
            notes=f"could not convert rotated cube to nissy-core state: {exc}",
        )

    binary = build_h48_backend(root=root, threads=threads)
    command = [
        str(binary),
        "--lower-bound-batch",
        "--solver",
        solver,
        "--table",
        str(table_path),
        "--threads",
        str(max(1, threads)),
    ]
    if skip_table_check:
        command.append("--skip-table-check")
    if preload_table:
        command.append("--preload-table")

    begin = time.perf_counter()
    timed_out = False
    return_code: int | None = None
    stderr_text = ""
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            input=rotated_input,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
        stdout_text = completed.stdout
        stderr_text = completed.stderr.strip()
        return_code = completed.returncode
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout_text = _subprocess_text(exc.stdout)
        stderr_text = _subprocess_text(exc.stderr).strip()

    runtime_seconds = time.perf_counter() - begin
    rows, failed_rows, parse_errors, stdout_line_count = _parse_h48_lower_bound_rows(stdout_text, rotations)
    valid_bounds = [
        (rotation.name, lower_bound, runtime_seconds)
        for _index, rotation, lower_bound, runtime_seconds, _payload in rows
    ]

    if not valid_bounds:
        return H48LowerBoundResult(
            solver_name=f"h48_native_{solver}_rotational_lower_bound",
            input_state=cube.to_facelets(),
            lower_bound=None,
            runtime_seconds=runtime_seconds,
            table_bytes=table_path.stat().st_size,
            status="timeout" if timed_out else "failed",
            notes=(
                "could not parse any valid H48 rotational lower-bound row; "
                f"return_code={return_code}; rotation_count={len(rotations)}; "
                f"partial_timeout_recovered={'true' if timed_out else 'false'}; "
                f"partial_completed_count=0; stdout_line_count={stdout_line_count}; "
                f"parse_errors={parse_errors}; stderr={stderr_text}"
            ),
        )

    best_rotation, best_lower, best_runtime = max(valid_bounds, key=lambda item: item[1])
    first_payload = rows[0][4]
    return H48LowerBoundResult(
        solver_name=f"h48_native_{solver}_rotational_lower_bound",
        input_state=cube.to_facelets(),
        lower_bound=best_lower,
        runtime_seconds=runtime_seconds,
        table_bytes=int(first_payload.get("table_size_bytes") or table_path.stat().st_size),
        status="lower_bound",
        notes=(
            f"in-repo native H48 rotational admissible lower-bound batch{trusted_note}; "
            f"return_code={return_code}; rotation_count={len(rotations)}; "
            f"include_identity={include_identity}; best_rotation={best_rotation}; "
            f"best_rotation_backend_runtime_seconds={best_runtime}; "
            f"partial_timeout_recovered={'true' if timed_out else 'false'}; "
            f"partial_completed_count={len(rows)}; "
            f"valid_bounds={valid_bounds}; failed_rows={failed_rows}; "
            f"parse_errors={parse_errors}; stdout_line_count={stdout_line_count}; "
            f"table_check={first_payload.get('table_check')}; "
            f"table_storage={first_payload.get('table_storage')}; "
            f"table_preload={first_payload.get('table_preload')}; "
            f"stderr={stderr_text}"
        ),
    )


def compute_h48_native_rotational_lower_bound_batch(
    cubes: Iterable[CubeState],
    *,
    variant_count: int,
    include_identity: bool = True,
    solver: str = DEFAULT_H48_SOLVER,
    profile: str = "thesis",
    seed: int = 2026,
    table_path: Path | None = None,
    timeout_seconds: float = 30.0,
    threads: int = 8,
    skip_table_check: bool = False,
    preload_table: bool = False,
    root: Path | None = None,
) -> list[H48LowerBoundResult]:
    """Compute strongest rotational H48 lower bounds for many cubes with one table-loaded batch."""

    rotations = _h48_symmetry_rotations(variant_count, include_identity=include_identity)
    if not rotations:
        return compute_h48_native_lower_bound_batch(
            cubes,
            solver=solver,
            profile=profile,
            seed=seed,
            table_path=table_path,
            timeout_seconds=timeout_seconds,
            threads=threads,
            skip_table_check=skip_table_check,
            preload_table=preload_table,
            root=root,
        )

    cube_list = list(cubes)
    results: list[H48LowerBoundResult | None] = [None] * len(cube_list)
    flat_cubes: list[CubeState] = []
    flat_meta: list[tuple[int, CubeRotation]] = []
    for index, cube in enumerate(cube_list):
        if cube == CubeState.solved():
            results[index] = H48LowerBoundResult(
                solver_name=f"h48_native_{solver}_rotational_lower_bound_batch",
                input_state=cube.to_facelets(),
                lower_bound=0,
                runtime_seconds=0.0,
                table_bytes=0,
                status="lower_bound",
                notes="solved state; H48 rotational multi-cube lower-bound batch backend not invoked for this row",
            )
            continue
        for rotation in rotations:
            flat_cubes.append(rotation.transform_cube(cube))
            flat_meta.append((index, rotation))

    if not flat_cubes:
        return [result for result in results if result is not None]

    flat_results = compute_h48_native_lower_bound_batch(
        flat_cubes,
        solver=solver,
        profile=profile,
        seed=seed,
        table_path=table_path,
        timeout_seconds=timeout_seconds,
        threads=threads,
        skip_table_check=skip_table_check,
        preload_table=preload_table,
        root=root,
    )
    grouped: dict[int, list[tuple[CubeRotation, H48LowerBoundResult]]] = {}
    for (original_index, rotation), lower_result in zip(flat_meta, flat_results, strict=True):
        grouped.setdefault(original_index, []).append((rotation, lower_result))

    for index, cube in enumerate(cube_list):
        if results[index] is not None:
            continue
        entries = grouped.get(index, [])
        valid = [
            (rotation, lower_result)
            for rotation, lower_result in entries
            if lower_result.status == "lower_bound" and lower_result.lower_bound is not None
        ]
        runtime_seconds = sum(max(0.0, lower_result.runtime_seconds) for _rotation, lower_result in entries)
        table_bytes = next(
            (lower_result.table_bytes for _rotation, lower_result in entries if lower_result.table_bytes is not None),
            0,
        )
        if not valid:
            status = "timeout" if any(lower_result.status == "timeout" for _rotation, lower_result in entries) else "failed"
            results[index] = H48LowerBoundResult(
                solver_name=f"h48_native_{solver}_rotational_lower_bound_batch",
                input_state=cube.to_facelets(),
                lower_bound=None,
                runtime_seconds=runtime_seconds,
                table_bytes=table_bytes,
                status=status,
                notes=(
                    "in-repo native H48 rotational admissible multi-cube lower-bound batch; "
                    f"table_loaded_once=true; source_batch_size={len(cube_list)}; "
                    f"rotation_count={len(rotations)}; flattened_rotation_count={len(flat_cubes)}; "
                    f"valid_bounds=[]; row_statuses={[(rotation.name, lower_result.status) for rotation, lower_result in entries]}"
                ),
            )
            continue
        best_rotation, best_result = max(valid, key=lambda item: int(item[1].lower_bound or 0))
        valid_bounds = [
            (rotation.name, lower_result.lower_bound, lower_result.runtime_seconds)
            for rotation, lower_result in valid
        ]
        results[index] = H48LowerBoundResult(
            solver_name=f"h48_native_{solver}_rotational_lower_bound_batch",
            input_state=cube.to_facelets(),
            lower_bound=int(best_result.lower_bound or 0),
            runtime_seconds=runtime_seconds,
            table_bytes=table_bytes,
            status="lower_bound",
            notes=(
                "in-repo native H48 rotational admissible multi-cube lower-bound batch; "
                "table_loaded_once=true; "
                f"source_batch_size={len(cube_list)}; rotation_count={len(rotations)}; "
                f"flattened_rotation_count={len(flat_cubes)}; include_identity={include_identity}; "
                f"best_rotation={best_rotation.name}; valid_bounds={valid_bounds}; "
                f"best_rotation_notes={best_result.notes}"
            ),
        )

    return [result for result in results if result is not None]


def solve_h48_native_batch(
    cubes: Iterable[CubeState],
    *,
    solver: str = DEFAULT_H48_SOLVER,
    profile: str = "thesis",
    seed: int = 2026,
    table_path: Path | None = None,
    timeout_seconds: float | None = 300.0,
    threads: int = 8,
    max_depth: int = 20,
    skip_table_check: bool = False,
    preload_table: bool = False,
    auto_min_depth: bool = False,
    root: Path | None = None,
) -> list[SolverResult]:
    """Solve multiple direct cube states after one native table load/check.

    The returned runtime for non-solved rows is the backend per-case search time
    reported by nissy-core. The notes include the batch wall time, which covers
    the single process launch plus one shared table read/check.
    """

    root = root or repository_root()
    cube_list = list(cubes)
    results: list[SolverResult | None] = [None] * len(cube_list)
    pending: list[tuple[int, CubeState, str]] = []
    for index, cube in enumerate(cube_list):
        if cube == CubeState.solved():
            results[index] = SolverResult(
                solver_name=f"h48_native_{solver}",
                input_state=cube.to_facelets(),
                solution_moves=[],
                solution_length=0,
                metric="HTM",
                runtime_seconds=0.0,
                expanded_nodes=0,
                generated_nodes=None,
                table_bytes=0,
                status="exact",
                is_verified=True,
                notes="solved state; H48 backend not invoked",
            )
        else:
            pending.append((index, cube, cube_to_nissy_string(cube)))
    if not pending:
        return [result for result in results if result is not None]

    table_path = table_path or h48_table_path(root=root, profile=profile, seed=seed, solver=solver)
    if not table_path.exists():
        for index, cube, _ in pending:
            results[index] = SolverResult(
                solver_name=f"h48_native_{solver}",
                input_state=cube.to_facelets(),
                solution_moves=[],
                solution_length=None,
                metric="HTM",
                runtime_seconds=0.0,
                expanded_nodes=None,
                generated_nodes=None,
                table_bytes=0,
                status="failed",
                is_verified=False,
                notes=f"missing required H48 table: {table_path}",
            )
        return [result for result in results if result is not None]
    trusted_note = ""
    if skip_table_check:
        trusted_ok, trusted_message = validate_trusted_h48_table(
            root=root,
            profile=profile,
            seed=seed,
            solver=solver,
            table_path=table_path,
        )
        if not trusted_ok:
            for index, cube, _ in pending:
                results[index] = SolverResult(
                    solver_name=f"h48_native_{solver}",
                    input_state=cube.to_facelets(),
                    solution_moves=[],
                    solution_length=None,
                    metric="HTM",
                    runtime_seconds=0.0,
                    expanded_nodes=None,
                    generated_nodes=None,
                    table_bytes=table_path.stat().st_size if table_path.exists() else 0,
                    status="failed",
                    is_verified=False,
                    notes=f"trusted H48 table rejected: {trusted_message}",
                )
            return [result for result in results if result is not None]
        trusted_note = f"; trusted_table_metadata=valid; trusted_table_note={trusted_message}"

    binary = build_h48_backend(root=root, threads=threads)
    command = [
        str(binary),
        "--solve-batch",
        "--solver",
        solver,
        "--table",
        str(table_path),
        "--threads",
        str(max(1, threads)),
        "--max-depth",
        str(max_depth),
    ]
    if skip_table_check:
        command.append("--skip-table-check")
    if preload_table:
        command.append("--preload-table")
    if auto_min_depth:
        command.append("--auto-min-depth")
    search_timeout_ms = _timeout_seconds_to_ms(timeout_seconds)
    if search_timeout_ms is not None:
        command.extend(["--search-timeout-ms", str(search_timeout_ms)])
    begin = time.perf_counter()
    process_timeout = _process_timeout_with_grace(timeout_seconds)
    if process_timeout is not None:
        process_timeout *= len(pending)
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            input="\n".join(nissy_cube for _, _, nissy_cube in pending) + "\n",
            text=True,
            capture_output=True,
            timeout=process_timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        runtime_seconds = time.perf_counter() - begin
        timeout_label = "unbounded" if timeout_seconds is None else f"{timeout_seconds}s"
        partial_stdout = _subprocess_text(exc.stdout)
        partial_payloads = _parse_h48_batch_payload_lines(partial_stdout)
        partial_count = min(len(partial_payloads), len(pending))
        table_bytes = table_path.stat().st_size
        for offset, (index, cube, _) in enumerate(pending):
            if offset < partial_count:
                payload = partial_payloads[offset]
                per_case_runtime = float(payload.get("runtime_seconds") or 0.0)
                results[index] = _result_from_payload(
                    cube,
                    solver=solver,
                    payload=payload,
                    runtime_seconds=per_case_runtime,
                    table_path=table_path,
                    table_bytes=table_bytes,
                    return_code=-1,
                    source_sequence_provided=False,
                    mode_note=(
                        "in-repo native H48 batch row completed before process timeout; "
                        "table_loaded_once=true; partial_timeout_recovered=true; "
                        f"batch_wall_seconds={runtime_seconds:.6f}; "
                        f"partial_completed_count={partial_count}{trusted_note}"
                    ),
                )
                continue
            results[index] = SolverResult(
                solver_name=f"h48_native_{solver}",
                input_state=cube.to_facelets(),
                solution_moves=[],
                solution_length=None,
                metric="HTM",
                runtime_seconds=runtime_seconds,
                expanded_nodes=None,
                generated_nodes=None,
                table_bytes=table_bytes,
                status="timeout",
                is_verified=False,
                notes=(
                    f"in-repo H48 batch backend timed out after {timeout_label}; "
                    "partial_timeout_recovered=true; "
                    f"partial_completed_count={partial_count}; "
                    f"partial_stdout={partial_stdout!r}; partial_stderr={_subprocess_text(exc.stderr)!r}"
                ),
            )
        return [result for result in results if result is not None]

    batch_wall_seconds = time.perf_counter() - begin
    stdout_lines = [line for line in completed.stdout.splitlines() if line.strip()]
    table_bytes = table_path.stat().st_size
    for offset, (index, cube, _) in enumerate(pending):
        if offset >= len(stdout_lines):
            payload = {
                "status": "failed",
                "solution": "",
                "solution_length": None,
                "expanded_nodes": None,
                "table_lookups": None,
                "table_fallbacks": None,
                "error": completed.stderr.strip() or "missing batch output row",
            }
        else:
            try:
                payload = json.loads(stdout_lines[offset])
            except json.JSONDecodeError:
                payload = {
                    "status": "failed",
                    "solution": "",
                    "solution_length": None,
                    "expanded_nodes": None,
                    "table_lookups": None,
                    "table_fallbacks": None,
                    "error": stdout_lines[offset],
                }
        per_case_runtime = float(payload.get("runtime_seconds") or 0.0)
        result = _result_from_payload(
            cube,
            solver=solver,
            payload=payload,
            runtime_seconds=per_case_runtime,
            table_path=table_path,
            table_bytes=table_bytes,
            return_code=completed.returncode,
            source_sequence_provided=False,
            mode_note=(
                "in-repo native H48 batch backend; table_loaded_once=true; "
                f"batch_wall_seconds={batch_wall_seconds:.6f}{trusted_note}"
            ),
        )
        results[index] = result

    return [result for result in results if result is not None]

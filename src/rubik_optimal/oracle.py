"""First-class fast optimal oracle API for arbitrary valid 3x3 states."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from pathlib import Path
import time
from typing import Callable, Iterable

from .cube import CubeState
from .exact_certificates import (
    EXTERNAL_LABEL_STATUS,
    LOCAL_PROOF_BASIS,
    ExactCertificate,
    ExactCertificateStore,
)
from .moves import inverse_sequence, parse_sequence
from .solvers.base import SolverResult
from .solvers.h48_native import (
    H48LowerBoundResult,
    H48NativeOracleSession,
    _h48_symmetry_rotations,
    compute_h48_native_lower_bound,
    compute_h48_native_lower_bound_batch,
    compute_h48_native_rotational_lower_bound,
    compute_h48_native_rotational_lower_bound_batch,
    cube_to_nissy_string,
    order_h48_rotations_by_lower_bound,
    solve_h48_native_optimal,
    solve_h48_native_resident_batch,
    solve_h48_native_rotational_race,
)
from .solvers.kociemba import solve_kociemba_adapter
from .solvers.nissy_external import (
    NissyCoreDirectPythonSession,
    _NISSY_OPTIMAL_TABLE,
    _NissyCorePythonUnavailable,
    _default_data_dir,
    _default_nissy_core_module_root,
    _directory_size,
    _find_binary,
    _find_nissy_core_shell,
    _nissy_core_python_enabled_for_table,
    _nissy_core_python_module_available,
    _parse_plain_nissy_core_solution,
    _parse_batch_solutions,
    _parse_solution,
    _representative_scramble,
    _table_path,
    solve_nissy_core_direct_optimal,
    solve_nissy_core_direct_optimal_batch,
    solve_nissy_optimal,
    solve_nissy_optimal_batch,
)
from .solvers.optimal_native import solve_korf_native_optimal
from .solvers.rubikoptimal_external import (
    _RESULT_MARKER as _RUBIKOPTIMAL_RESULT_MARKER,
    RubikOptimalOracleSession,
    default_rubikoptimal_pythonpath,
    default_rubikoptimal_table_dir,
    find_rubikoptimal_executable,
    parse_rubikoptimal_process_output,
    rubikoptimal_table_bytes,
    rubikoptimal_tables_ready,
    solve_rubikoptimal_external_rotational_race,
)
from .runtime import default_thread_count
from .symmetry import CUBE_ROTATIONS, CubeRotation
from .tables.h48 import (
    H48_FASTEST_SOLVER,
    ORACLE_H48_SOLVER,
    build_h48_backend,
    h48_table_path,
    repository_root,
    resolve_h48_solver,
    validate_trusted_h48_table,
)
from .validity import validate_cube
from .verify import verify_solution


def _default_threads() -> int:
    return default_thread_count()


def _default_nissy_threads() -> int:
    return min(2, _default_threads())


@dataclass(frozen=True)
class FastOptimalOracleConfig:
    """Configuration for the resident native H48 exact oracle.

    The default solver is ``fastest``: it resolves to the strongest trusted
    generated H48 table for the selected profile, with h48h7 as the oracle-grade
    fallback. Trusted-table mode is still checked against generated metadata
    before the native per-call table scan is skipped. The package API default
    leaves the native per-state search unbounded so a valid state is not
    downgraded to ``timeout`` unless the caller explicitly chooses a deadline
    for a benchmark or interactive probe.
    """

    profile: str = "thesis"
    seed: int = 2026
    solver: str = H48_FASTEST_SOLVER
    threads: int = field(default_factory=_default_threads)
    timeout_seconds: float | None = None
    max_depth: int = 20
    trusted_table: bool = True
    preload_table: bool = False
    auto_min_depth: bool = False
    table_path: Path | None = None
    root: Path | None = None


@dataclass(frozen=True)
class PortfolioOptimalOracleConfig:
    """Configuration for the mixed exact 3x3 oracle.

    Nissy's public optimal table is strong on many ordinary/random states; the
    resident H48 path is the reliable direct-state fallback and the saved hard
    superflip evidence path.  The portfolio keeps both exact backends available
    without letting the first one monopolize a busy workstation.
    """

    h48: FastOptimalOracleConfig = field(default_factory=FastOptimalOracleConfig)
    nissy_timeout_seconds: float = 30.0
    nissy_threads: int = field(default_factory=_default_nissy_threads)
    nissy_binary_path: Path | None = None
    nissy_data_dir: Path | None = None
    try_nissy_first: bool = True
    try_nissy_core_direct_first: bool = True
    nissy_core_direct_timeout_seconds: float = 10.0
    nissy_core_direct_binary_path: Path | None = None
    try_certificate_cache: bool = True
    certificate_artifacts: tuple[Path, ...] | None = None
    learned_certificate_artifact: Path | None = None
    # Opt-in only: certificates whose exactness rests on a third-party
    # benchmark label (status="external_label_exact") are excluded from the
    # certificate cache by default and are never served as plain "exact".
    include_external_label_certificates: bool = False
    try_upper_lower_certificate: bool = True
    lower_bound_timeout_seconds: float = 30.0
    lower_bound_symmetry_variants: int = 0
    lower_bound_symmetry_include_identity: bool = True
    kociemba_upper_bound_symmetry_variants: int = 0
    h48_upper_bound_proof_timeout_seconds: float = 0.0
    h48_upper_bound_proof_max_gap: int = 1
    native_korf_upper_bound_proof_timeout_seconds: float = 0.0
    native_korf_upper_bound_proof_max_gap: int = 1
    native_korf_upper_bound_proof_split_depth: int = 3
    # Off by default: the requirement-#3 optimal engine is the student's OWN
    # native corner+edge-PDB IDA*. Linking the optional GPL-3.0 nissy heuristic
    # makes a combined/derivative work and is therefore strictly opt-in.
    native_korf_upper_bound_proof_nissy_heuristic: bool = False
    try_h48_fallback: bool = True


@dataclass(frozen=True)
class RaceOptimalOracleConfig:
    """Configuration for racing independent exact 3x3 oracle backends.

    The race is a latency optimization, not a new proof rule: the first backend
    to return an independently verified exact solution wins, and any still
    running subprocess is terminated.
    """

    h48: FastOptimalOracleConfig = field(default_factory=FastOptimalOracleConfig)
    timeout_seconds: float = 300.0
    nissy_threads: int = field(default_factory=_default_nissy_threads)
    nissy_binary_path: Path | None = None
    nissy_data_dir: Path | None = None
    include_h48: bool = True
    include_nissy: bool = True
    include_nissy_core_direct: bool = True
    nissy_core_direct_binary_path: Path | None = None


@dataclass(frozen=True)
class ResidentRaceOptimalOracleConfig:
    """Configuration for racing Nissy against a resident native H48 session.

    This is the lower-overhead race variant: H48 runs through ``FastOptimalOracle``
    so repeated calls can reuse the native batch process and loaded table, while
    Nissy remains an independent exact subprocess competitor.
    """

    h48: FastOptimalOracleConfig = field(default_factory=FastOptimalOracleConfig)
    timeout_seconds: float = 300.0
    nissy_threads: int = field(default_factory=_default_nissy_threads)
    nissy_binary_path: Path | None = None
    nissy_data_dir: Path | None = None
    include_h48: bool = True
    include_nissy: bool = True
    h48_start_delay_seconds: float = 0.0
    nissy_symmetry_variants: int = 0
    include_nissy_core_direct: bool = True
    nissy_core_direct_binary_path: Path | None = None
    include_nissy_core_python_resident: bool = True
    include_rubikoptimal: bool = False
    rubikoptimal_race_timeout_seconds: float | None = None
    rubikoptimal_executable: Path | None = None
    rubikoptimal_package_path: Path | None = None
    rubikoptimal_table_dir: Path | None = None
    symmetry_order_by_h48_lower_bound: bool = False
    symmetry_lower_bound_order_timeout_seconds: float = 30.0


@dataclass(frozen=True)
class UniversalOptimalOracleConfig:
    """Configuration for the unified optimized exact 3x3 oracle.

    The universal wrapper is an orchestration layer: it uses zero-search exact
    certificates first, then cheap upper/lower-bound certificates, and only then
    falls back to the resident race of exact native backends.
    """

    resident_race: ResidentRaceOptimalOracleConfig = field(default_factory=ResidentRaceOptimalOracleConfig)
    try_certificate_cache: bool = True
    certificate_artifacts: tuple[Path, ...] | None = None
    learned_certificate_artifact: Path | None = None
    # Opt-in only: third-party-labeled certificates are excluded by default.
    include_external_label_certificates: bool = False
    try_upper_lower_certificate: bool = True
    lower_bound_timeout_seconds: float = 30.0
    lower_bound_symmetry_variants: int = 23
    lower_bound_symmetry_include_identity: bool = True
    kociemba_upper_bound_symmetry_variants: int = 23
    h48_upper_bound_proof_timeout_seconds: float = 0.0
    h48_upper_bound_proof_max_gap: int = 1
    native_korf_upper_bound_proof_timeout_seconds: float = 0.0
    native_korf_upper_bound_proof_max_gap: int = 1
    native_korf_upper_bound_proof_split_depth: int = 3
    # Off by default: the requirement-#3 optimal engine is the student's OWN
    # native corner+edge-PDB IDA*. Linking the optional GPL-3.0 nissy heuristic
    # makes a combined/derivative work and is therefore strictly opt-in.
    native_korf_upper_bound_proof_nissy_heuristic: bool = False
    nissy_symmetry_variants: int = 0
    nissy_symmetry_timeout_seconds: float | None = None
    nissy_core_direct_symmetry_variants: int = 0
    nissy_core_direct_symmetry_timeout_seconds: float | None = None
    nissy_core_direct_symmetry_max_concurrency: int = 0
    resident_h48_symmetry_variants: int = 0
    resident_h48_symmetry_timeout_seconds: float | None = 5.0
    resident_race_prepass_timeout_seconds: float | None = None
    parallel_h48_symmetry_variants: int = 0
    parallel_h48_symmetry_timeout_seconds: float | None = 5.0
    parallel_h48_symmetry_max_concurrency: int = 0
    parallel_h48_symmetry_order_by_lower_bound: bool = False
    parallel_h48_symmetry_lower_bound_order_timeout_seconds: float = 30.0
    symmetry_order_by_h48_lower_bound: bool = False
    symmetry_lower_bound_order_timeout_seconds: float = 30.0
    prefer_resident_h48_batch_for_state_input: bool = False
    resident_h48_batch_timeout_seconds: float | None = 30.0
    try_portfolio_batch_before_resident_h48_batch: bool = False
    portfolio_prepass_timeout_seconds: float | None = None
    portfolio_fallback_timeout_seconds: float | None = None
    portfolio_fallback_nissy_core_direct_timeout_seconds: float | None = 10.0
    rubikoptimal_prepass_timeout_seconds: float | None = None
    rubikoptimal_symmetry_variants: int = 0
    rubikoptimal_symmetry_timeout_seconds: float | None = None
    rubikoptimal_symmetry_max_concurrency: int = 0
    rubikoptimal_race_timeout_seconds: float | None = None
    rubikoptimal_fallback_timeout_seconds: float | None = None
    rubikoptimal_executable: Path | None = None
    rubikoptimal_package_path: Path | None = None
    rubikoptimal_table_dir: Path | None = None


def _is_verified_exact(result: SolverResult) -> bool:
    return result.status == "exact" and result.is_verified


def _note_int(notes: str, key: str) -> int | None:
    prefix = f"{key}="
    for part in notes.split("; "):
        if not part.startswith(prefix):
            continue
        try:
            return int(part[len(prefix) :].strip())
        except ValueError:
            return None
    return None


@dataclass
class _RaceCandidate:
    name: str
    process: subprocess.Popen[str]
    parse_result: Callable[[str, str, int, float], SolverResult]
    started_at: float
    cleanup: Callable[[], None] | None = None


class FastOptimalOracle:
    """Reusable exact H48 oracle for arbitrary physically valid 3x3 states.

    This is the package-level capability wrapper for thesis use: callers pass a
    cubie state, the wrapper validates physical legality, and a resident native
    H48 backend searches up to the HTM God's Number bound of 20 moves with
    nissy-core's optimal parameter set to zero in the backend.
    """

    def __init__(self, config: FastOptimalOracleConfig | None = None) -> None:
        self.config = config or FastOptimalOracleConfig()
        self.root = self.config.root or repository_root()
        self.solver = resolve_h48_solver(
            self.config.solver,
            root=self.root,
            profile=self.config.profile,
            seed=self.config.seed,
        )
        self.table_path = self.config.table_path or h48_table_path(
            root=self.root,
            profile=self.config.profile,
            seed=self.config.seed,
            solver=self.solver,
        )
        self._session: H48NativeOracleSession | None = None

    def __enter__(self) -> "FastOptimalOracle":
        self.start()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def start(self) -> None:
        if self._session is not None:
            return
        self._session = H48NativeOracleSession(
            solver=self.solver,
            profile=self.config.profile,
            seed=self.config.seed,
            table_path=self.table_path,
            threads=self.config.threads,
            max_depth=self.config.max_depth,
            skip_table_check=self.config.trusted_table,
            preload_table=self.config.preload_table,
            auto_min_depth=self.config.auto_min_depth,
            search_timeout_seconds=self.config.timeout_seconds,
            root=self.root,
        )
        self._session.start()

    def close(self) -> None:
        session = self._session
        self._session = None
        if session is not None:
            session.close()

    def solve(self, cube: CubeState) -> SolverResult:
        ok, message = validate_cube(cube)
        if not ok:
            return SolverResult(
                solver_name=f"fast_optimal_oracle_{self.solver}",
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
                notes=f"invalid physical cube state rejected before H48 oracle: {message}",
            )
        if cube.is_solved():
            return SolverResult(
                solver_name=f"fast_optimal_oracle_{self.solver}",
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
                notes=(
                    "fast optimal oracle API; arbitrary_valid_3x3_domain=true; "
                    "resident_native_h48=true; solved state; resident native H48 backend not invoked"
                ),
            )
        self.start()
        if self._session is None:
            raise RuntimeError("fast optimal oracle session did not start")
        result = self._session.solve(cube, timeout_seconds=self.config.timeout_seconds)
        return SolverResult(
            solver_name=f"fast_optimal_oracle_{self.solver}",
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
                "fast optimal oracle API; arbitrary_valid_3x3_domain=true; "
                f"resident_native_h48=true; max_depth={self.config.max_depth}; "
                f"trusted_table={self.config.trusted_table}; {result.notes}"
            ),
        )

    def solve_many(self, cubes: Iterable[CubeState]) -> list[SolverResult]:
        cube_list = list(cubes)
        results: list[SolverResult | None] = [None] * len(cube_list)
        pending: list[tuple[int, CubeState]] = []
        for index, cube in enumerate(cube_list):
            ok, message = validate_cube(cube)
            if not ok:
                results[index] = SolverResult(
                    solver_name=f"fast_optimal_oracle_{self.solver}",
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
                    notes=f"invalid physical cube state rejected before H48 oracle batch: {message}",
                )
                continue
            pending.append((index, cube))

        if pending and any(not cube.is_solved() for _, cube in pending):
            self.start()
        if pending and self._session is not None:
            batch_results = self._session.solve_many(
                [cube for _, cube in pending],
                timeout_seconds=self.config.timeout_seconds,
            )
        else:
            batch_results = [self.solve(cube) for _, cube in pending]

        for batch_row, ((index, _cube), result) in enumerate(
            zip(pending, batch_results, strict=True)
        ):
            results[index] = SolverResult(
                solver_name=f"fast_optimal_oracle_{self.solver}",
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
                    "fast optimal oracle API; arbitrary_valid_3x3_domain=true; "
                    "resident_native_h48=true; resident_native_h48_batch_api=true; "
                    f"batch_input_count={len(pending)}; batch_row={batch_row}; "
                    f"max_depth={self.config.max_depth}; trusted_table={self.config.trusted_table}; "
                    f"{result.notes}"
                ),
            )
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
        ok, message = validate_cube(cube)
        if not ok:
            return SolverResult(
                solver_name=f"fast_optimal_oracle_{self.solver}_symmetry_batch",
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
                notes=f"invalid physical cube state rejected before H48 symmetry oracle: {message}",
            )
        if cube.is_solved():
            return self.solve(cube)
        self.start()
        if self._session is None:
            raise RuntimeError("fast optimal oracle session did not start")
        result = self._session.solve_rotated_variants(
            cube,
            variant_count=variant_count,
            include_identity=include_identity,
            timeout_seconds=timeout_seconds,
            rotations=rotations,
            rotation_order_note=rotation_order_note,
        )
        return SolverResult(
            solver_name=f"fast_optimal_oracle_{self.solver}_symmetry_batch",
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
                "fast optimal oracle API; arbitrary_valid_3x3_domain=true; "
                "resident_native_h48=true; rotational_symmetry_prepass=true; "
                f"max_depth={self.config.max_depth}; trusted_table={self.config.trusted_table}; "
                f"{result.notes}"
            ),
        )

    def solve_parallel_rotated_variants(
        self,
        cube: CubeState,
        *,
        variant_count: int,
        include_identity: bool = True,
        timeout_seconds: float | None = None,
        max_concurrency: int | None = None,
        order_by_lower_bound: bool = False,
        lower_bound_order_timeout_seconds: float = 30.0,
    ) -> SolverResult:
        ok, message = validate_cube(cube)
        if not ok:
            return SolverResult(
                solver_name=f"fast_optimal_oracle_{self.solver}_parallel_symmetry_race",
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
                notes=f"invalid physical cube state rejected before H48 parallel symmetry oracle: {message}",
            )
        if cube.is_solved():
            return self.solve(cube)
        result = solve_h48_native_rotational_race(
            cube,
            variant_count=variant_count,
            include_identity=include_identity,
            max_concurrency=max_concurrency,
            solver=self.solver,
            profile=self.config.profile,
            seed=self.config.seed,
            table_path=self.table_path,
            timeout_seconds=timeout_seconds,
            threads=self.config.threads,
            max_depth=self.config.max_depth,
            skip_table_check=self.config.trusted_table,
            preload_table=self.config.preload_table,
            auto_min_depth=self.config.auto_min_depth,
            order_by_lower_bound=order_by_lower_bound,
            lower_bound_order_timeout_seconds=lower_bound_order_timeout_seconds,
            root=self.root,
        )
        return SolverResult(
            solver_name=f"fast_optimal_oracle_{self.solver}_parallel_symmetry_race",
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
                "fast optimal oracle API; arbitrary_valid_3x3_domain=true; "
                "native_h48_parallel_process_race=true; rotational_symmetry_prepass=true; "
                f"max_depth={self.config.max_depth}; trusted_table={self.config.trusted_table}; "
                f"{result.notes}"
            ),
        )

    def distance(self, cube: CubeState) -> int | None:
        result = self.solve(cube)
        if result.status == "exact" and result.is_verified:
            return result.solution_length
        return None


def solve_fast_optimal(cube: CubeState, config: FastOptimalOracleConfig | None = None) -> SolverResult:
    """Solve one valid 3x3 state with the resident h48h7 exact oracle API."""

    oracle = FastOptimalOracle(config)
    try:
        return oracle.solve(cube)
    finally:
        oracle.close()


def _stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=1.0)


def _cleanup_candidate(candidate: _RaceCandidate) -> None:
    if candidate.cleanup is None:
        return
    try:
        candidate.cleanup()
    except Exception:
        pass


def _stop_candidate(candidate: _RaceCandidate) -> None:
    try:
        _stop_process(candidate.process)
    finally:
        _cleanup_candidate(candidate)


class RaceOptimalOracle:
    """Race Nissy-optimal and native H48 exact searches for lower latency.

    This class exists for the user's literal target: an exact arbitrary-state
    3x3 oracle that is as fast as the available local backends allow.  It does
    not weaken exactness.  A result is returned as exact only when the selected
    backend returns a solution that the local verifier confirms from the input
    state.
    """

    solver_name = "race_optimal_oracle"

    def __init__(self, config: RaceOptimalOracleConfig | None = None) -> None:
        self.config = config or RaceOptimalOracleConfig()
        self.root = self.config.h48.root or repository_root()
        self.h48_solver = resolve_h48_solver(
            self.config.h48.solver,
            root=self.root,
            profile=self.config.h48.profile,
            seed=self.config.h48.seed,
        )
        self.h48_table_path = self.config.h48.table_path or h48_table_path(
            root=self.root,
            profile=self.config.h48.profile,
            seed=self.config.h48.seed,
            solver=self.h48_solver,
        )

    def solve(
        self,
        cube: CubeState,
        *,
        source_sequence: list[str] | tuple[str, ...] | str | None = None,
    ) -> SolverResult:
        begin = time.perf_counter()
        ok, message = validate_cube(cube)
        if not ok:
            return SolverResult(
                solver_name=self.solver_name,
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
                notes=f"invalid physical cube state rejected before race oracle: {message}",
            )
        if cube.is_solved():
            return SolverResult(
                solver_name=self.solver_name,
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
                notes="race exact oracle; selected_backend=solved_fast_path; no backend process started",
            )

        candidates, setup_notes = self._build_candidates(cube, source_sequence=source_sequence)
        if not candidates:
            return SolverResult(
                solver_name=self.solver_name,
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
                notes="race exact oracle could not start any backend; " + "; ".join(setup_notes),
            )

        active = list(candidates)
        completed: list[SolverResult] = []
        deadline = begin + self.config.timeout_seconds
        try:
            while active:
                now = time.perf_counter()
                if now >= deadline:
                    for candidate in active:
                        _stop_candidate(candidate)
                    return SolverResult(
                        solver_name=self.solver_name,
                        input_state=cube.to_facelets(),
                        solution_moves=[],
                        solution_length=None,
                        metric="HTM",
                        runtime_seconds=time.perf_counter() - begin,
                        expanded_nodes=None,
                        generated_nodes=None,
                        table_bytes=0,
                        status="timeout",
                        is_verified=False,
                        notes=(
                            "race exact oracle timed out before any backend produced a verified exact result; "
                            f"started_backends={','.join(candidate.name for candidate in candidates)}; "
                            f"completed_statuses={[(result.solver_name, result.status) for result in completed]}; "
                            f"setup_notes={'; '.join(setup_notes)}"
                        ),
                    )

                for candidate in list(active):
                    return_code = candidate.process.poll()
                    if return_code is None:
                        continue
                    stdout, stderr = candidate.process.communicate()
                    backend_runtime = time.perf_counter() - candidate.started_at
                    result = candidate.parse_result(stdout, stderr, return_code, backend_runtime)
                    active.remove(candidate)
                    _cleanup_candidate(candidate)
                    completed.append(result)
                    if result.status == "exact" and result.is_verified:
                        for loser in active:
                            _stop_candidate(loser)
                        return self._wrap_winner(
                            result,
                            selected_backend=candidate.name,
                            total_runtime_seconds=time.perf_counter() - begin,
                            started_backends=[item.name for item in candidates],
                            setup_notes=setup_notes,
                            killed_backends=[item.name for item in active],
                        )

                if active:
                    time.sleep(min(0.05, max(0.0, deadline - time.perf_counter())))
        finally:
            for candidate in active:
                _stop_candidate(candidate)

        status = "timeout" if any(result.status == "timeout" for result in completed) else "failed"
        return SolverResult(
            solver_name=self.solver_name,
            input_state=cube.to_facelets(),
            solution_moves=[],
            solution_length=None,
            metric="HTM",
            runtime_seconds=time.perf_counter() - begin,
            expanded_nodes=None,
            generated_nodes=None,
            table_bytes=0,
            status=status,
            is_verified=False,
            notes=(
                "race exact oracle finished without a verified exact backend result; "
                f"started_backends={','.join(candidate.name for candidate in candidates)}; "
                f"completed_statuses={[(result.solver_name, result.status) for result in completed]}; "
                f"setup_notes={'; '.join(setup_notes)}"
            ),
        )

    def _build_candidates(
        self,
        cube: CubeState,
        *,
        source_sequence: list[str] | tuple[str, ...] | str | None,
    ) -> tuple[list[_RaceCandidate], list[str]]:
        candidates: list[_RaceCandidate] = []
        setup_notes: list[str] = []
        if self.config.include_h48:
            h48_candidate = self._start_h48_candidate(cube, setup_notes)
            if h48_candidate is not None:
                candidates.append(h48_candidate)
        if self.config.include_nissy:
            nissy_candidate = self._start_nissy_candidate(cube, source_sequence, setup_notes)
            if nissy_candidate is not None:
                candidates.append(nissy_candidate)
        return candidates, setup_notes

    def _start_h48_candidate(self, cube: CubeState, setup_notes: list[str]) -> _RaceCandidate | None:
        if not self.h48_table_path.exists():
            setup_notes.append(f"h48_skipped=missing_table:{self.h48_table_path}")
            return None
        trusted_note = ""
        if self.config.h48.trusted_table:
            trusted_ok, trusted_message = validate_trusted_h48_table(
                root=self.root,
                profile=self.config.h48.profile,
                seed=self.config.h48.seed,
                solver=self.h48_solver,
                table_path=self.h48_table_path,
            )
            if not trusted_ok:
                setup_notes.append(f"h48_skipped=trusted_table_rejected:{trusted_message}")
                return None
            trusted_note = f"; trusted_table_metadata=valid; trusted_table_note={trusted_message}"
        binary = build_h48_backend(root=self.root, threads=self.config.h48.threads)
        command = [
            str(binary),
            "--solve",
            "--solver",
            self.h48_solver,
            "--table",
            str(self.h48_table_path),
            "--cube",
            cube_to_nissy_string(cube),
            "--threads",
            str(max(1, self.config.h48.threads)),
            "--max-depth",
            str(self.config.h48.max_depth),
        ]
        if self.config.h48.trusted_table:
            command.append("--skip-table-check")
        if self.config.h48.preload_table:
            command.append("--preload-table")
        started_at = time.perf_counter()
        process = subprocess.Popen(
            command,
            cwd=self.root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        def parse_h48(stdout: str, stderr: str, return_code: int, runtime_seconds: float) -> SolverResult:
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
            status = str(payload.get("status", "failed"))
            solution = parse_sequence(str(payload.get("solution") or ""))
            verification = verify_solution(cube, solution) if status == "exact" else None
            return SolverResult(
                solver_name=f"h48_native_{self.h48_solver}",
                input_state=cube.to_facelets(),
                solution_moves=solution,
                solution_length=(
                    int(payload["solution_length"]) if payload.get("solution_length") is not None else None
                ),
                metric="HTM",
                runtime_seconds=runtime_seconds,
                expanded_nodes=int(payload["expanded_nodes"]) if payload.get("expanded_nodes") is not None else None,
                generated_nodes=None,
                table_bytes=int(payload.get("table_size_bytes") or self.h48_table_path.stat().st_size),
                status=status if status in {"exact", "timeout"} else "failed",
                is_verified=bool(status == "exact" and verification and verification.ok),
                notes=(
                    f"race backend=h48; solver={self.h48_solver}; input_mode=cube_state; "
                    f"return_code={return_code}; backend_runtime_seconds={payload.get('runtime_seconds')}; "
                    f"table_check={payload.get('table_check')}; table_storage={payload.get('table_storage')}; "
                    f"table_preload={payload.get('table_preload')}; table_lookups={payload.get('table_lookups')}; "
                    f"table_fallbacks={payload.get('table_fallbacks')}; error={payload.get('error', '')}; "
                    f"stderr={stderr.strip()}{trusted_note}"
                ),
            )

        return _RaceCandidate("native-h48", process, parse_h48, started_at)

    def _start_nissy_candidate(
        self,
        cube: CubeState,
        source_sequence: list[str] | tuple[str, ...] | str | None,
        setup_notes: list[str],
        *,
        allow_direct_core: bool = True,
    ) -> _RaceCandidate | None:
        if allow_direct_core and self.config.include_nissy_core_direct and source_sequence is None:
            direct_candidate = self._start_nissy_core_direct_candidate(cube, setup_notes)
            if direct_candidate is not None:
                return direct_candidate

        selected_data_dir = _default_data_dir(self.root, self.config.nissy_data_dir)
        binary = _find_binary(self.root, self.config.nissy_binary_path)
        if binary is None:
            setup_notes.append("nissy_skipped=binary_not_found")
            return None
        required_path = _table_path(selected_data_dir, _NISSY_OPTIMAL_TABLE)
        if required_path is None or not required_path.exists():
            setup_notes.append(f"nissy_skipped=missing_table:{_NISSY_OPTIMAL_TABLE}")
            return None
        try:
            scramble, scramble_source = _representative_scramble(cube, source_sequence)
        except Exception as exc:
            setup_notes.append(f"nissy_skipped=representative_scramble_failed:{exc}")
            return None
        command = [
            str(binary),
            "solve",
            "optimal",
            "-t",
            str(max(1, self.config.nissy_threads)),
            "-o",
            "-n",
            "1",
            " ".join(scramble),
        ]
        env = os.environ.copy()
        if selected_data_dir is not None:
            env["NISSYDATA"] = str(selected_data_dir)
        started_at = time.perf_counter()
        process = subprocess.Popen(
            command,
            cwd=self.root,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        def parse_nissy(stdout: str, stderr: str, return_code: int, runtime_seconds: float) -> SolverResult:
            table_bytes = _directory_size(selected_data_dir)
            if return_code != 0:
                return SolverResult(
                    solver_name="nissy_optimal_external",
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
                        "race backend=nissy-optimal; "
                        f"return_code={return_code}; output={(stdout + stderr).strip()}"
                    ),
                )
            try:
                solution, solution_length = _parse_solution("\n".join(part for part in (stdout, stderr) if part))
                verification = verify_solution(cube, solution)
            except Exception as exc:
                return SolverResult(
                    solver_name="nissy_optimal_external",
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
                    notes=f"race backend=nissy-optimal; parse_or_verify_error={exc}",
                )
            return SolverResult(
                solver_name="nissy_optimal_external",
                input_state=cube.to_facelets(),
                solution_moves=solution,
                solution_length=solution_length if verification.ok else None,
                metric="HTM",
                runtime_seconds=runtime_seconds,
                expanded_nodes=None,
                generated_nodes=None,
                table_bytes=table_bytes,
                status="exact" if verification.ok else "failed",
                is_verified=verification.ok,
                notes=(
                    "race backend=nissy-optimal; input_mode=representative_scramble; "
                    f"source_sequence_provided={source_sequence is not None}; "
                    f"scramble_source={scramble_source}; threads={self.config.nissy_threads}; "
                    f"required_table={_NISSY_OPTIMAL_TABLE}; return_code={return_code}"
                ),
            )

        return _RaceCandidate("nissy-optimal", process, parse_nissy, started_at)

    def _start_nissy_core_direct_candidate(
        self,
        cube: CubeState,
        setup_notes: list[str],
    ) -> _RaceCandidate | None:
        binary = _find_nissy_core_shell(self.root, self.config.nissy_core_direct_binary_path)
        if binary is None:
            setup_notes.append("nissy_core_direct_skipped=binary_not_found")
            return None
        if not self.h48_table_path.exists():
            setup_notes.append(f"nissy_core_direct_skipped=missing_table:{self.h48_table_path}")
            return None
        try:
            nissy_cube = cube_to_nissy_string(cube)
        except Exception as exc:
            setup_notes.append(f"nissy_core_direct_skipped=cube_conversion_failed:{exc}")
            return None

        temp_dir = Path(tempfile.mkdtemp(prefix="rubik-race-nissy-core-"))
        link_path = temp_dir / self.h48_solver
        try:
            link_path.symlink_to(self.h48_table_path.resolve())
        except OSError as exc:
            shutil.rmtree(temp_dir, ignore_errors=True)
            setup_notes.append(f"nissy_core_direct_skipped=table_symlink_failed:{exc}")
            return None

        command = [
            str(binary),
            "solve",
            "-solver",
            self.h48_solver,
            "-M",
            str(self.config.h48.max_depth),
            "-n",
            "1",
            "-O",
            "0",
            "-cube",
            nissy_cube,
            "-t",
            str(max(1, self.config.nissy_threads)),
        ]
        started_at = time.perf_counter()
        try:
            process = subprocess.Popen(
                command,
                cwd=temp_dir,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except Exception as exc:
            shutil.rmtree(temp_dir, ignore_errors=True)
            setup_notes.append(f"nissy_core_direct_skipped=start_failed:{exc}")
            return None

        def cleanup() -> None:
            shutil.rmtree(temp_dir, ignore_errors=True)

        def parse_direct(stdout: str, stderr: str, return_code: int, runtime_seconds: float) -> SolverResult:
            output = "\n".join(part for part in (stdout, stderr) if part)
            table_bytes = self.h48_table_path.stat().st_size if self.h48_table_path.exists() else 0
            if return_code != 0:
                return SolverResult(
                    solver_name=f"nissy_core_direct_{self.h48_solver}",
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
                        "race backend=nissy-core-direct; input_mode=cube_state; "
                        f"table_symlink=true; return_code={return_code}; output={output.strip()}"
                    ),
                )
            try:
                solution, solution_length = _parse_plain_nissy_core_solution(output)
                verification = verify_solution(cube, solution)
            except Exception as exc:
                return SolverResult(
                    solver_name=f"nissy_core_direct_{self.h48_solver}",
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
                        "race backend=nissy-core-direct; input_mode=cube_state; "
                        f"parse_or_verify_error={exc}; output={output.strip()}"
                    ),
                )
            return SolverResult(
                solver_name=f"nissy_core_direct_{self.h48_solver}",
                input_state=cube.to_facelets(),
                solution_moves=solution,
                solution_length=solution_length if verification.ok else None,
                metric="HTM",
                runtime_seconds=runtime_seconds,
                expanded_nodes=None,
                generated_nodes=None,
                table_bytes=table_bytes,
                status="exact" if verification.ok else "failed",
                is_verified=verification.ok,
                notes=(
                    "race backend=nissy-core-direct; input_mode=cube_state; "
                    "table_symlink=true; source_sequence_provided=false; "
                    f"solver={self.h48_solver}; table_path={self.h48_table_path}; "
                    f"max_depth={self.config.h48.max_depth}; optimal=0; "
                    f"threads={self.config.nissy_threads}; return_code={return_code}"
                ),
            )

        return _RaceCandidate("nissy-core-direct", process, parse_direct, started_at, cleanup)

    def _wrap_winner(
        self,
        result: SolverResult,
        *,
        selected_backend: str,
        total_runtime_seconds: float,
        started_backends: list[str],
        setup_notes: list[str],
        killed_backends: list[str],
    ) -> SolverResult:
        return SolverResult(
            solver_name=self.solver_name,
            input_state=result.input_state,
            solution_moves=result.solution_moves,
            solution_length=result.solution_length,
            metric=result.metric,
            runtime_seconds=total_runtime_seconds,
            expanded_nodes=result.expanded_nodes,
            generated_nodes=result.generated_nodes,
            table_bytes=result.table_bytes,
            status=result.status,
            is_verified=result.is_verified,
            notes=(
                "race exact oracle; exactness_policy=first_verified_exact_solution_wins; "
                f"selected_backend={selected_backend}; started_backends={','.join(started_backends)}; "
                f"killed_backends={','.join(killed_backends) if killed_backends else 'none'}; "
                f"backend_solver={result.solver_name}; backend_runtime_seconds={result.runtime_seconds:.6f}; "
                f"setup_notes={'; '.join(setup_notes)}; {result.notes}"
            ),
        )


def solve_race_optimal(
    cube: CubeState,
    config: RaceOptimalOracleConfig | None = None,
    *,
    source_sequence: list[str] | tuple[str, ...] | str | None = None,
) -> SolverResult:
    """Solve one valid 3x3 state by racing exact Nissy and H48 backends."""

    return RaceOptimalOracle(config).solve(cube, source_sequence=source_sequence)


class ResidentRaceOptimalOracle:
    """Race exact Nissy against a resident H48 oracle session.

    ``RaceOptimalOracle`` proves the concurrent exactness policy with two
    one-shot subprocesses.  This variant keeps the H48 side resident, removing
    avoidable startup/table overhead for repeated API calls while preserving the
    same rule: only the first independently verified exact result can win.
    """

    solver_name = "resident_race_optimal_oracle"

    def __init__(self, config: ResidentRaceOptimalOracleConfig | None = None) -> None:
        self.config = config or ResidentRaceOptimalOracleConfig()
        self._h48 = FastOptimalOracle(self.config.h48)
        self._executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="resident-race")
        self._rubikoptimal_session: RubikOptimalOracleSession | None = None
        self._nissy_core_direct_session: NissyCoreDirectPythonSession | None = None
        self._closed = False

    def __enter__(self) -> "ResidentRaceOptimalOracle":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def close(self) -> None:
        self._closed = True
        self._h48.close()
        if self._rubikoptimal_session is not None:
            self._rubikoptimal_session.close()
            self._rubikoptimal_session = None
        if self._nissy_core_direct_session is not None:
            self._nissy_core_direct_session.close()
            self._nissy_core_direct_session = None
        self._executor.shutdown(wait=False, cancel_futures=True)

    def solve(
        self,
        cube: CubeState,
        *,
        source_sequence: list[str] | tuple[str, ...] | str | None = None,
    ) -> SolverResult:
        if self._closed:
            raise RuntimeError("resident race oracle is closed")

        begin = time.perf_counter()
        ok, message = validate_cube(cube)
        if not ok:
            return SolverResult(
                solver_name=self.solver_name,
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
                notes=f"invalid physical cube state rejected before resident race oracle: {message}",
            )
        if cube.is_solved():
            return SolverResult(
                solver_name=self.solver_name,
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
                notes=(
                    "resident race exact oracle; selected_backend=solved_fast_path; "
                    "resident_h48_invoked=false; nissy_optimal_invoked=false"
                ),
            )

        setup_notes: list[str] = []
        started_backends: list[str] = []
        completed: list[SolverResult] = []
        subprocess_candidates: list[_RaceCandidate] = []
        h48_future: Future[SolverResult] | None = None
        rubikoptimal_future: Future[SolverResult] | None = None
        nissy_core_direct_future: Future[SolverResult] | None = None
        h48_pending = self.config.include_h48
        rubikoptimal_pending = self.config.include_rubikoptimal
        nissy_core_direct_resident_pending = self._nissy_core_direct_resident_enabled(
            source_sequence=source_sequence,
            setup_notes=setup_notes,
        )
        h48_delay = max(0.0, float(self.config.h48_start_delay_seconds))
        h48_start_at = begin + h48_delay

        def start_h48() -> None:
            nonlocal h48_future, h48_pending
            if not h48_pending:
                return
            h48_future = self._executor.submit(self._h48.solve, cube)
            started_backends.append("resident-h48")
            h48_pending = False

        def start_rubikoptimal() -> None:
            nonlocal rubikoptimal_future, rubikoptimal_pending
            if not rubikoptimal_pending:
                return
            timeout_seconds = self._rubikoptimal_race_timeout_seconds()
            rubikoptimal_future = self._executor.submit(
                self._rubikoptimal_resident_session().solve,
                cube,
                timeout_seconds=timeout_seconds,
            )
            started_backends.append("rubikoptimal-race")
            rubikoptimal_pending = False

        def start_nissy_core_direct_resident() -> None:
            nonlocal nissy_core_direct_future, nissy_core_direct_resident_pending
            if not nissy_core_direct_resident_pending:
                return
            nissy_core_direct_future = self._executor.submit(
                self._nissy_core_direct_resident_session().solve,
                cube,
                timeout_seconds=self._nissy_core_direct_resident_timeout_seconds(),
            )
            started_backends.append("nissy-core-direct-resident")
            nissy_core_direct_resident_pending = False

        if h48_pending and h48_delay <= 0.0:
            start_h48()
        if nissy_core_direct_resident_pending:
            start_nissy_core_direct_resident()
        if rubikoptimal_pending:
            start_rubikoptimal()
        if self.config.include_nissy:
            for nissy_candidate in self._start_nissy_candidates(
                cube,
                source_sequence,
                setup_notes,
                allow_direct_core=nissy_core_direct_future is None,
            ):
                subprocess_candidates.append(nissy_candidate)
                started_backends.append(nissy_candidate.name)

        if (
            not h48_pending
            and h48_future is None
            and rubikoptimal_future is None
            and nissy_core_direct_future is None
            and not subprocess_candidates
        ):
            return SolverResult(
                solver_name=self.solver_name,
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
                notes="resident race exact oracle could not start any backend; " + "; ".join(setup_notes),
            )

        deadline = begin + self.config.timeout_seconds
        try:
            while (
                h48_pending
                or h48_future is not None
                or rubikoptimal_future is not None
                or nissy_core_direct_future is not None
                or subprocess_candidates
            ):
                now = time.perf_counter()
                if now >= deadline:
                    stopped = self._stop_remaining(
                        subprocess_candidates,
                        h48_future,
                        rubikoptimal_future,
                        nissy_core_direct_future,
                        h48_pending=h48_pending,
                    )
                    subprocess_candidates = []
                    rubikoptimal_future = None
                    nissy_core_direct_future = None
                    return SolverResult(
                        solver_name=self.solver_name,
                        input_state=cube.to_facelets(),
                        solution_moves=[],
                        solution_length=None,
                        metric="HTM",
                        runtime_seconds=time.perf_counter() - begin,
                        expanded_nodes=None,
                        generated_nodes=None,
                        table_bytes=0,
                        status="timeout",
                        is_verified=False,
                        notes=(
                            "resident race exact oracle timed out before any backend produced a verified exact "
                            "result; "
                            f"started_backends={','.join(started_backends)}; "
                            f"stopped_backends={','.join(stopped) if stopped else 'none'}; "
                            f"h48_start_delay_seconds={h48_delay:.6f}; "
                            f"completed_statuses={[(result.solver_name, result.status) for result in completed]}; "
                            f"setup_notes={'; '.join(setup_notes)}"
                        ),
                    )

                if h48_pending and now >= h48_start_at:
                    start_h48()

                if h48_future is not None and h48_future.done():
                    result = self._h48_result_from_future(cube, h48_future)
                    h48_future = None
                    completed.append(result)
                    if result.status == "exact" and result.is_verified:
                        stopped = []
                        if rubikoptimal_future is not None and not rubikoptimal_future.done():
                            self._stop_rubikoptimal_resident()
                            stopped.append("rubikoptimal-race")
                            rubikoptimal_future = None
                        if nissy_core_direct_future is not None and not nissy_core_direct_future.done():
                            self._stop_nissy_core_direct_resident()
                            stopped.append("nissy-core-direct-resident")
                            nissy_core_direct_future = None
                        for candidate in subprocess_candidates:
                            _stop_candidate(candidate)
                            stopped.append(candidate.name)
                        subprocess_candidates = []
                        return self._wrap_winner(
                            result,
                            selected_backend="resident-h48",
                            total_runtime_seconds=time.perf_counter() - begin,
                            started_backends=started_backends,
                            stopped_backends=stopped,
                            setup_notes=setup_notes,
                            h48_start_delay_seconds=h48_delay,
                        )

                if rubikoptimal_future is not None and rubikoptimal_future.done():
                    result = self._rubikoptimal_result_from_future(cube, rubikoptimal_future)
                    rubikoptimal_future = None
                    completed.append(result)
                    if result.status == "exact" and result.is_verified:
                        stopped = []
                        if h48_future is not None and not h48_future.done():
                            self._h48.close()
                            stopped.append("resident-h48")
                        if nissy_core_direct_future is not None and not nissy_core_direct_future.done():
                            self._stop_nissy_core_direct_resident()
                            stopped.append("nissy-core-direct-resident")
                            nissy_core_direct_future = None
                        if h48_pending:
                            h48_pending = False
                            stopped.append("resident-h48-deferred")
                        for loser in subprocess_candidates:
                            _stop_candidate(loser)
                            stopped.append(loser.name)
                        subprocess_candidates = []
                        return self._wrap_winner(
                            result,
                            selected_backend="rubikoptimal-race",
                            total_runtime_seconds=time.perf_counter() - begin,
                            started_backends=started_backends,
                            stopped_backends=stopped,
                            setup_notes=setup_notes,
                            h48_start_delay_seconds=h48_delay,
                        )
                    if result.status == "timeout":
                        setup_notes.append(
                            f"rubikoptimal-race_timeout_after_seconds={self._rubikoptimal_race_timeout_seconds():.6f}"
                        )

                if nissy_core_direct_future is not None and nissy_core_direct_future.done():
                    result = self._nissy_core_direct_resident_result_from_future(
                        cube,
                        nissy_core_direct_future,
                    )
                    nissy_core_direct_future = None
                    completed.append(result)
                    if result.status == "exact" and result.is_verified:
                        stopped = []
                        if h48_future is not None and not h48_future.done():
                            self._h48.close()
                            stopped.append("resident-h48")
                        if rubikoptimal_future is not None and not rubikoptimal_future.done():
                            self._stop_rubikoptimal_resident()
                            stopped.append("rubikoptimal-race")
                            rubikoptimal_future = None
                        if h48_pending:
                            h48_pending = False
                            stopped.append("resident-h48-deferred")
                        for loser in subprocess_candidates:
                            _stop_candidate(loser)
                            stopped.append(loser.name)
                        subprocess_candidates = []
                        return self._wrap_winner(
                            result,
                            selected_backend="nissy-core-direct-resident",
                            total_runtime_seconds=time.perf_counter() - begin,
                            started_backends=started_backends,
                            stopped_backends=stopped,
                            setup_notes=setup_notes,
                            h48_start_delay_seconds=h48_delay,
                        )
                    if result.status == "timeout":
                        setup_notes.append(
                            "nissy-core-direct-resident_timeout_after_seconds="
                            f"{self._nissy_core_direct_resident_timeout_seconds():.6f}"
                        )

                for candidate in list(subprocess_candidates):
                    return_code = candidate.process.poll()
                    if return_code is None:
                        candidate_timeout = self._candidate_timeout_seconds(candidate)
                        if candidate_timeout is not None and now - candidate.started_at >= candidate_timeout:
                            _stop_candidate(candidate)
                            subprocess_candidates.remove(candidate)
                            completed.append(
                                self._candidate_timeout_result(
                                    cube,
                                    candidate,
                                    runtime_seconds=time.perf_counter() - candidate.started_at,
                                    timeout_seconds=candidate_timeout,
                                )
                            )
                            setup_notes.append(f"{candidate.name}_timeout_after_seconds={candidate_timeout:.6f}")
                        continue

                    candidate_name = candidate.name
                    stdout, stderr = candidate.process.communicate()
                    backend_runtime = time.perf_counter() - candidate.started_at
                    result = candidate.parse_result(stdout, stderr, return_code, backend_runtime)
                    subprocess_candidates.remove(candidate)
                    _cleanup_candidate(candidate)
                    completed.append(result)
                    if result.status == "exact" and result.is_verified:
                        stopped = []
                        if h48_future is not None and not h48_future.done():
                            self._h48.close()
                            stopped.append("resident-h48")
                        if rubikoptimal_future is not None and not rubikoptimal_future.done():
                            self._stop_rubikoptimal_resident()
                            stopped.append("rubikoptimal-race")
                            rubikoptimal_future = None
                        if nissy_core_direct_future is not None and not nissy_core_direct_future.done():
                            self._stop_nissy_core_direct_resident()
                            stopped.append("nissy-core-direct-resident")
                            nissy_core_direct_future = None
                        if h48_pending:
                            h48_pending = False
                            stopped.append("resident-h48-deferred")
                        for loser in subprocess_candidates:
                            _stop_candidate(loser)
                            stopped.append(loser.name)
                        subprocess_candidates = []
                        return self._wrap_winner(
                            result,
                            selected_backend=candidate_name,
                            total_runtime_seconds=time.perf_counter() - begin,
                            started_backends=started_backends,
                            stopped_backends=stopped,
                            setup_notes=setup_notes,
                            h48_start_delay_seconds=h48_delay,
                        )

                if (
                    not h48_pending
                    and h48_future is None
                    and rubikoptimal_future is None
                    and nissy_core_direct_future is None
                    and not subprocess_candidates
                ):
                    break
                time.sleep(min(0.05, max(0.0, deadline - time.perf_counter())))
        finally:
            for candidate in subprocess_candidates:
                _stop_candidate(candidate)

        status = "timeout" if any(result.status == "timeout" for result in completed) else "failed"
        return SolverResult(
            solver_name=self.solver_name,
            input_state=cube.to_facelets(),
            solution_moves=[],
            solution_length=None,
            metric="HTM",
            runtime_seconds=time.perf_counter() - begin,
            expanded_nodes=None,
            generated_nodes=None,
            table_bytes=0,
            status=status,
            is_verified=False,
            notes=(
                "resident race exact oracle finished without a verified exact backend result; "
                f"started_backends={','.join(started_backends)}; "
                f"h48_start_delay_seconds={h48_delay:.6f}; "
                f"completed_statuses={[(result.solver_name, result.status) for result in completed]}; "
                f"setup_notes={'; '.join(setup_notes)}"
            ),
        )

    def _start_nissy_candidate(
        self,
        cube: CubeState,
        source_sequence: list[str] | tuple[str, ...] | str | None,
        setup_notes: list[str],
    ) -> _RaceCandidate | None:
        if self.config.include_nissy_core_direct and source_sequence is None:
            direct_candidate = self._start_nissy_core_direct_candidate(cube, setup_notes)
            if direct_candidate is not None:
                return direct_candidate

        if self.config.nissy_symmetry_variants > 0:
            symmetry_candidate = self._start_nissy_symmetry_candidate(cube, source_sequence, setup_notes)
            if symmetry_candidate is not None:
                return symmetry_candidate

        race_config = RaceOptimalOracleConfig(
            h48=self.config.h48,
            timeout_seconds=self.config.timeout_seconds,
            nissy_threads=self.config.nissy_threads,
            nissy_binary_path=self.config.nissy_binary_path,
            nissy_data_dir=self.config.nissy_data_dir,
            include_h48=False,
            include_nissy=True,
        )
        return RaceOptimalOracle(race_config)._start_nissy_candidate(cube, source_sequence, setup_notes)

    def _start_nissy_candidates(
        self,
        cube: CubeState,
        source_sequence: list[str] | tuple[str, ...] | str | None,
        setup_notes: list[str],
        *,
        allow_direct_core: bool = True,
    ) -> list[_RaceCandidate]:
        """Start all configured exact Nissy-side resident-race competitors.

        The legacy direct-state nissy-core candidate is valuable for facelet-only
        inputs, but it used to prevent an explicitly configured Nissy symmetry
        batch from joining the same race.  Hard-tail probes need the opposite:
        both exact Nissy paths may compete, and the first verified exact result
        stops the other subprocess.
        """

        candidates: list[_RaceCandidate] = []
        if allow_direct_core:
            primary = self._start_nissy_candidate(cube, source_sequence, setup_notes)
        else:
            primary = None
            if self.config.nissy_symmetry_variants > 0:
                primary = self._start_nissy_symmetry_candidate(cube, source_sequence, setup_notes)
            if primary is None:
                race_config = RaceOptimalOracleConfig(
                    h48=self.config.h48,
                    timeout_seconds=self.config.timeout_seconds,
                    nissy_threads=self.config.nissy_threads,
                    nissy_binary_path=self.config.nissy_binary_path,
                    nissy_data_dir=self.config.nissy_data_dir,
                    include_h48=False,
                    include_nissy=True,
                    include_nissy_core_direct=False,
                )
                primary = RaceOptimalOracle(race_config)._start_nissy_candidate(
                    cube,
                    source_sequence,
                    setup_notes,
                )
        if primary is not None:
            candidates.append(primary)

        should_add_symmetry_competitor = (
            source_sequence is None
            and self.config.include_nissy_core_direct
            and self.config.nissy_symmetry_variants > 0
            and not any(candidate.name == "nissy-symmetry-batch" for candidate in candidates)
        )
        if should_add_symmetry_competitor:
            symmetry_candidate = self._start_nissy_symmetry_candidate(cube, source_sequence, setup_notes)
            if symmetry_candidate is not None:
                candidates.append(symmetry_candidate)

        return candidates

    def _start_nissy_core_direct_candidate(
        self,
        cube: CubeState,
        setup_notes: list[str],
    ) -> _RaceCandidate | None:
        binary = _find_nissy_core_shell(self._h48.root, self.config.nissy_core_direct_binary_path)
        if binary is None:
            setup_notes.append("nissy_core_direct_skipped=binary_not_found")
            return None
        table_path = self._h48.table_path
        if not table_path.exists():
            setup_notes.append(f"nissy_core_direct_skipped=missing_table:{table_path}")
            return None
        try:
            nissy_cube = cube_to_nissy_string(cube)
        except Exception as exc:
            setup_notes.append(f"nissy_core_direct_skipped=cube_conversion_failed:{exc}")
            return None

        temp_dir = Path(tempfile.mkdtemp(prefix="rubik-race-nissy-core-"))
        link_path = temp_dir / self._h48.solver
        try:
            link_path.symlink_to(table_path.resolve())
        except OSError as exc:
            shutil.rmtree(temp_dir, ignore_errors=True)
            setup_notes.append(f"nissy_core_direct_skipped=table_symlink_failed:{exc}")
            return None

        command = [
            str(binary),
            "solve",
            "-solver",
            self._h48.solver,
            "-M",
            str(self.config.h48.max_depth),
            "-n",
            "1",
            "-O",
            "0",
            "-cube",
            nissy_cube,
            "-t",
            str(max(1, self.config.nissy_threads)),
        ]
        started_at = time.perf_counter()
        try:
            process = subprocess.Popen(
                command,
                cwd=temp_dir,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except Exception as exc:
            shutil.rmtree(temp_dir, ignore_errors=True)
            setup_notes.append(f"nissy_core_direct_skipped=start_failed:{exc}")
            return None

        def cleanup() -> None:
            shutil.rmtree(temp_dir, ignore_errors=True)

        def parse_direct(stdout: str, stderr: str, return_code: int, runtime_seconds: float) -> SolverResult:
            output = "\n".join(part for part in (stdout, stderr) if part)
            table_bytes = table_path.stat().st_size if table_path.exists() else 0
            if return_code != 0:
                return SolverResult(
                    solver_name=f"nissy_core_direct_{self._h48.solver}",
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
                        "resident race backend=nissy-core-direct; input_mode=cube_state; "
                        f"table_symlink=true; return_code={return_code}; output={output.strip()}"
                    ),
                )
            try:
                solution, solution_length = _parse_plain_nissy_core_solution(output)
                verification = verify_solution(cube, solution)
            except Exception as exc:
                return SolverResult(
                    solver_name=f"nissy_core_direct_{self._h48.solver}",
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
                        "resident race backend=nissy-core-direct; input_mode=cube_state; "
                        f"parse_or_verify_error={exc}; output={output.strip()}"
                    ),
                )
            return SolverResult(
                solver_name=f"nissy_core_direct_{self._h48.solver}",
                input_state=cube.to_facelets(),
                solution_moves=solution,
                solution_length=solution_length if verification.ok else None,
                metric="HTM",
                runtime_seconds=runtime_seconds,
                expanded_nodes=None,
                generated_nodes=None,
                table_bytes=table_bytes,
                status="exact" if verification.ok else "failed",
                is_verified=verification.ok,
                notes=(
                    "resident race backend=nissy-core-direct; input_mode=cube_state; "
                    "table_symlink=true; source_sequence_provided=false; "
                    f"solver={self._h48.solver}; table_path={table_path}; "
                    f"max_depth={self.config.h48.max_depth}; optimal=0; "
                    f"threads={self.config.nissy_threads}; return_code={return_code}; "
                    "h48_competes_concurrently=true"
                ),
            )

        return _RaceCandidate("nissy-core-direct", process, parse_direct, started_at, cleanup)

    def _start_nissy_symmetry_candidate(
        self,
        cube: CubeState,
        source_sequence: list[str] | tuple[str, ...] | str | None,
        setup_notes: list[str],
    ) -> _RaceCandidate | None:
        """Start one exact Nissy batch over identity plus whole-cube rotations.

        Unlike the older universal pre-race symmetry probe, this candidate runs
        inside the resident race. H48 can therefore start immediately or after
        the configured delay, and a hard Nissy symmetry batch no longer blocks
        the resident H48 fallback from competing.
        """

        selected_data_dir = _default_data_dir(self._h48.root, self.config.nissy_data_dir)
        binary = _find_binary(self._h48.root, self.config.nissy_binary_path)
        if binary is None:
            setup_notes.append("nissy_symmetry_skipped=binary_not_found")
            return None
        required_path = _table_path(selected_data_dir, _NISSY_OPTIMAL_TABLE)
        if required_path is None or not required_path.exists():
            setup_notes.append(f"nissy_symmetry_skipped=missing_table:{_NISSY_OPTIMAL_TABLE}")
            return None

        identity = next((rotation for rotation in CUBE_ROTATIONS if rotation.is_identity), None)
        if identity is None:
            setup_notes.append("nissy_symmetry_skipped=identity_rotation_missing")
            return None
        non_identity = [rotation for rotation in CUBE_ROTATIONS if not rotation.is_identity]
        rotations = [identity] + non_identity[: max(0, int(self.config.nissy_symmetry_variants))]
        rotations, rotation_order_note = self._order_nissy_symmetry_rotations_by_h48_lower_bound(
            cube,
            rotations,
        )
        rotated_inputs: list[tuple[object, CubeState, list[str], str]] = []
        for rotation in rotations:
            rotated_cube = rotation.transform_cube(cube)
            rotated_source = rotation.transform_sequence(source_sequence) if source_sequence is not None else None
            try:
                scramble, scramble_source = _representative_scramble(rotated_cube, rotated_source)
            except Exception as exc:
                setup_notes.append(f"nissy_symmetry_rotation_skipped={rotation.name}:{exc}")
                continue
            rotated_inputs.append((rotation, rotated_cube, scramble, scramble_source))

        if not rotated_inputs:
            setup_notes.append("nissy_symmetry_skipped=no_representative_scrambles")
            return None

        command = [
            str(binary),
            "solve",
            "optimal",
            "-t",
            str(max(1, self.config.nissy_threads)),
            "-o",
            "-n",
            "1",
            "-i",
        ]
        env = os.environ.copy()
        if selected_data_dir is not None:
            env["NISSYDATA"] = str(selected_data_dir)
        stdin = "\n".join(" ".join(scramble) for _, _, scramble, _ in rotated_inputs) + "\n"
        started_at = time.perf_counter()
        process = subprocess.Popen(
            command,
            cwd=self._h48.root,
            env=env,
            text=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert process.stdin is not None
        process.stdin.write(stdin)
        process.stdin.close()
        process.stdin = None

        def parse_symmetry_batch(stdout: str, stderr: str, return_code: int, runtime_seconds: float) -> SolverResult:
            table_bytes = _directory_size(selected_data_dir)
            output = "\n".join(part for part in (stdout, stderr) if part)
            if return_code != 0:
                return SolverResult(
                    solver_name="nissy_symmetry_batch_oracle",
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
                        "resident race backend=nissy-symmetry-batch; "
                        f"return_code={return_code}; {rotation_order_note}; output={output.strip()}"
                    ),
                )
            try:
                parsed = _parse_batch_solutions(output, len(rotated_inputs))
            except Exception as exc:
                return SolverResult(
                    solver_name="nissy_symmetry_batch_oracle",
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
                        "resident race backend=nissy-symmetry-batch; "
                        f"parse_error={exc}; {rotation_order_note}; output={output.strip()}"
                    ),
                )

            verified_candidates: list[tuple[object, list[str], int, str, float]] = []
            for (rotation, rotated_cube, _, scramble_source), (rotated_solution, rotated_length) in zip(
                rotated_inputs,
                parsed,
                strict=True,
            ):
                rotated_verification = verify_solution(rotated_cube, rotated_solution)
                if not rotated_verification.ok:
                    continue
                solution = rotation.inverse_transform_sequence(rotated_solution)
                verification = verify_solution(cube, solution)
                if verification.ok:
                    verified_candidates.append((rotation, solution, rotated_length, scramble_source, runtime_seconds))

            if not verified_candidates:
                return SolverResult(
                    solver_name="nissy_symmetry_batch_oracle",
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
                        "resident race backend=nissy-symmetry-batch; "
                        "no rotated exact solution verified after mapping back; "
                        f"{rotation_order_note}"
                    ),
                )

            selected_rotation, solution, rotated_length, scramble_source, _ = min(
                verified_candidates,
                key=lambda item: (len(item[1]), str(item[0].name)),
            )
            return SolverResult(
                solver_name="nissy_symmetry_batch_oracle",
                input_state=cube.to_facelets(),
                solution_moves=solution,
                solution_length=len(solution),
                metric="HTM",
                runtime_seconds=runtime_seconds,
                expanded_nodes=None,
                generated_nodes=None,
                table_bytes=table_bytes,
                status="exact",
                is_verified=True,
                notes=(
                    "resident race backend=nissy-symmetry-batch; "
                    "exactness_policy=rotated_exact_solution_mapped_back_and_verified; "
                    "identity_rotation_included=true; "
                    f"symmetry_variants={len(rotated_inputs)}; selected_rotation={selected_rotation.name}; "
                    f"rotated_solution_length={rotated_length}; "
                    f"scramble_source={scramble_source}; threads={self.config.nissy_threads}; "
                    f"required_table={_NISSY_OPTIMAL_TABLE}; return_code={return_code}; "
                    f"{rotation_order_note}; "
                    "h48_competes_concurrently=true"
                ),
            )

        return _RaceCandidate("nissy-symmetry-batch", process, parse_symmetry_batch, started_at)

    def _order_nissy_symmetry_rotations_by_h48_lower_bound(
        self,
        cube: CubeState,
        rotations: list[CubeRotation],
    ) -> tuple[list[CubeRotation], str]:
        if not self.config.symmetry_order_by_h48_lower_bound:
            return rotations, "resident_race_nissy_symmetry_h48_lower_bound_rotation_order=false"
        table_path = self._h48.table_path
        if not table_path.exists():
            return (
                rotations,
                "resident_race_nissy_symmetry_h48_lower_bound_rotation_order=true; "
                f"order_status=missing_table:{table_path}",
            )
        ordered, note = order_h48_rotations_by_lower_bound(
            cube,
            rotations,
            solver=self._h48.solver,
            table_path=table_path,
            timeout_seconds=max(0.001, self.config.symmetry_lower_bound_order_timeout_seconds),
            threads=self.config.h48.threads,
            skip_table_check=self.config.h48.trusted_table,
            preload_table=self.config.h48.preload_table,
            root=self.config.h48.root,
        )
        return ordered, f"resident_race_nissy_symmetry_{note}"

    def _start_rubikoptimal_candidate(
        self,
        cube: CubeState,
        setup_notes: list[str],
    ) -> _RaceCandidate | None:
        selected_table_dir = (
            Path(self.config.rubikoptimal_table_dir)
            if self.config.rubikoptimal_table_dir is not None
            else default_rubikoptimal_table_dir(self._h48.root)
        )
        table_bytes = rubikoptimal_table_bytes(selected_table_dir)
        if not rubikoptimal_tables_ready(selected_table_dir):
            setup_notes.append(f"rubikoptimal_race_skipped=missing_or_wrong_tables:{selected_table_dir}")
            return None

        selected_executable = find_rubikoptimal_executable(self.config.rubikoptimal_executable)
        if selected_executable is None:
            setup_notes.append("rubikoptimal_race_skipped=python_executable_not_found")
            return None

        pythonpath = (
            str(self.config.rubikoptimal_package_path)
            if self.config.rubikoptimal_package_path is not None
            else default_rubikoptimal_pythonpath()
        )
        if pythonpath is None:
            setup_notes.append("rubikoptimal_race_skipped=package_not_found")
            return None

        env = os.environ.copy()
        env["PYTHONPATH"] = pythonpath + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        code = (
            "import json, sys\n"
            "import optimal.solver as solver\n"
            "result = solver.solve(sys.argv[1])\n"
            f"print({_RUBIKOPTIMAL_RESULT_MARKER!r} + json.dumps({{'result': result}}), flush=True)\n"
        )
        started_at = time.perf_counter()
        try:
            process = subprocess.Popen(
                [str(selected_executable), "-c", code, cube.to_facelets()],
                cwd=selected_table_dir,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except Exception as exc:
            setup_notes.append(f"rubikoptimal_race_skipped=start_failed:{exc}")
            return None

        def parse_rubikoptimal(stdout: str, stderr: str, return_code: int, runtime_seconds: float) -> SolverResult:
            output = "\n".join(part for part in (stdout, stderr) if part)
            current_table_bytes = rubikoptimal_table_bytes(selected_table_dir)
            if return_code != 0:
                return SolverResult(
                    solver_name="rubikoptimal_external",
                    input_state=cube.to_facelets(),
                    solution_moves=[],
                    solution_length=None,
                    metric="HTM",
                    runtime_seconds=runtime_seconds,
                    expanded_nodes=None,
                    generated_nodes=None,
                    table_bytes=current_table_bytes,
                    status="failed",
                    is_verified=False,
                    notes=(
                        "resident race backend=rubikoptimal-race; input_mode=cube_state; "
                        f"return_code={return_code}; table_dir={selected_table_dir}; "
                        f"output={output.strip()}"
                    ),
                )
            try:
                solution, solution_length, raw_solution = parse_rubikoptimal_process_output(output)
                verification = verify_solution(cube, solution)
            except Exception as exc:
                return SolverResult(
                    solver_name="rubikoptimal_external",
                    input_state=cube.to_facelets(),
                    solution_moves=[],
                    solution_length=None,
                    metric="HTM",
                    runtime_seconds=runtime_seconds,
                    expanded_nodes=None,
                    generated_nodes=None,
                    table_bytes=current_table_bytes,
                    status="failed",
                    is_verified=False,
                    notes=(
                        "resident race backend=rubikoptimal-race; input_mode=cube_state; "
                        f"parse_or_verify_error={exc}; table_dir={selected_table_dir}; "
                        f"output={output.strip()}"
                    ),
                )
            return SolverResult(
                solver_name="rubikoptimal_external",
                input_state=cube.to_facelets(),
                solution_moves=solution,
                solution_length=solution_length if verification.ok else None,
                metric="HTM",
                runtime_seconds=runtime_seconds,
                expanded_nodes=None,
                generated_nodes=None,
                table_bytes=current_table_bytes,
                status="exact" if verification.ok else "failed",
                is_verified=verification.ok,
                notes=(
                    "resident race backend=rubikoptimal-race; input_mode=cube_state; "
                    "source_sequence_provided=false; h48_competes_concurrently=true; "
                    f"table_dir={selected_table_dir}; table_bytes={table_bytes}; "
                    f"return_code={return_code}; raw_solution={raw_solution}"
                ),
            )

        return _RaceCandidate("rubikoptimal-race", process, parse_rubikoptimal, started_at)

    def _h48_result_from_future(self, cube: CubeState, future: Future[SolverResult]) -> SolverResult:
        try:
            return future.result()
        except Exception as exc:
            return SolverResult(
                solver_name="fast_optimal_oracle_h48_future",
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
                notes=f"resident H48 future failed in race: {exc}",
            )

    def _rubikoptimal_resident_session(self) -> RubikOptimalOracleSession:
        if self._rubikoptimal_session is None:
            self._rubikoptimal_session = RubikOptimalOracleSession(
                executable=self.config.rubikoptimal_executable,
                package_path=self.config.rubikoptimal_package_path,
                table_dir=self.config.rubikoptimal_table_dir,
                root=self.config.h48.root,
            )
        return self._rubikoptimal_session

    def _rubikoptimal_race_timeout_seconds(self) -> float:
        timeout = self.config.rubikoptimal_race_timeout_seconds
        if timeout is None or timeout < 0.0:
            return max(0.0, float(self.config.timeout_seconds))
        return max(0.0, float(timeout))

    def _nissy_core_direct_resident_enabled(
        self,
        *,
        source_sequence: list[str] | tuple[str, ...] | str | None,
        setup_notes: list[str],
    ) -> bool:
        if not (
            self.config.include_nissy
            and self.config.include_nissy_core_direct
            and self.config.include_nissy_core_python_resident
            and source_sequence is None
        ):
            return False
        table_path = self._h48.table_path
        if not table_path.exists():
            setup_notes.append(f"nissy_core_direct_resident_skipped=missing_table:{table_path}")
            return False
        module_root = _default_nissy_core_module_root(self._h48.root)
        if not _nissy_core_python_module_available(module_root):
            setup_notes.append(
                f"nissy_core_direct_resident_skipped=python_module_not_found:{module_root / 'python'}"
            )
            return False
        if not _nissy_core_python_enabled_for_table(table_path, module_root):
            setup_notes.append(
                "nissy_core_direct_resident_skipped=python_module_not_enabled_for_table:"
                f"{table_path}"
            )
            return False
        return True

    def _nissy_core_direct_resident_session(self) -> NissyCoreDirectPythonSession:
        if self._nissy_core_direct_session is None:
            self._nissy_core_direct_session = NissyCoreDirectPythonSession(
                solver=self._h48.solver,
                table_path=self._h48.table_path,
                threads=max(1, self.config.nissy_threads),
                max_depth=self.config.h48.max_depth,
                root=self._h48.root,
                module_root=_default_nissy_core_module_root(self._h48.root),
            )
        return self._nissy_core_direct_session

    def _nissy_core_direct_resident_timeout_seconds(self) -> float:
        return max(0.0, float(self.config.timeout_seconds))

    def _stop_nissy_core_direct_resident(self) -> None:
        if self._nissy_core_direct_session is not None:
            self._nissy_core_direct_session.close()
            self._nissy_core_direct_session = None

    def _stop_rubikoptimal_resident(self) -> None:
        if self._rubikoptimal_session is not None:
            self._rubikoptimal_session.close()
            self._rubikoptimal_session = None

    def _nissy_core_direct_resident_result_from_future(
        self,
        cube: CubeState,
        future: Future[SolverResult],
    ) -> SolverResult:
        try:
            result = future.result()
        except _NissyCorePythonUnavailable as exc:
            self._stop_nissy_core_direct_resident()
            return SolverResult(
                solver_name=f"nissy_core_python_resident_{self._h48.solver}",
                input_state=cube.to_facelets(),
                solution_moves=[],
                solution_length=None,
                metric="HTM",
                runtime_seconds=0.0,
                expanded_nodes=None,
                generated_nodes=None,
                table_bytes=self._h48.table_path.stat().st_size if self._h48.table_path.exists() else 0,
                status="not_applicable",
                is_verified=False,
                notes=(
                    "resident race backend=nissy-core-direct-resident; "
                    f"resident nissy-core direct worker unavailable in race: {exc}"
                ),
            )
        except Exception as exc:
            self._stop_nissy_core_direct_resident()
            return SolverResult(
                solver_name=f"nissy_core_python_resident_{self._h48.solver}",
                input_state=cube.to_facelets(),
                solution_moves=[],
                solution_length=None,
                metric="HTM",
                runtime_seconds=0.0,
                expanded_nodes=None,
                generated_nodes=None,
                table_bytes=self._h48.table_path.stat().st_size if self._h48.table_path.exists() else 0,
                status="failed",
                is_verified=False,
                notes=(
                    "resident race backend=nissy-core-direct-resident; "
                    f"resident nissy-core direct future failed in race: {exc}"
                ),
            )
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
                "resident race backend=nissy-core-direct-resident; input_mode=cube_state; "
                "source_sequence_provided=false; h48_competes_concurrently=true; "
                "table_loaded_once=true; "
                "nissy_core_direct_resident_timeout_seconds="
                f"{self._nissy_core_direct_resident_timeout_seconds():.6f}; "
                f"{result.notes}"
            ),
        )

    def _rubikoptimal_result_from_future(
        self,
        cube: CubeState,
        future: Future[SolverResult],
    ) -> SolverResult:
        try:
            result = future.result()
        except Exception as exc:
            self._stop_rubikoptimal_resident()
            return SolverResult(
                solver_name="rubikoptimal_external",
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
                notes=(
                    "resident race backend=rubikoptimal-race; "
                    f"resident RubikOptimal future failed in race: {exc}"
                ),
            )
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
                "resident race backend=rubikoptimal-race; input_mode=cube_state; "
                "source_sequence_provided=false; h48_competes_concurrently=true; "
                f"rubikoptimal_timeout_seconds={self._rubikoptimal_race_timeout_seconds():.6f}; "
                f"{result.notes}"
            ),
        )

    def _candidate_timeout_seconds(self, candidate: _RaceCandidate) -> float | None:
        if candidate.name != "rubikoptimal-race":
            return None
        timeout = self.config.rubikoptimal_race_timeout_seconds
        if timeout is None or timeout < 0.0:
            return None
        return max(0.0, float(timeout))

    def _candidate_timeout_result(
        self,
        cube: CubeState,
        candidate: _RaceCandidate,
        *,
        runtime_seconds: float,
        timeout_seconds: float,
    ) -> SolverResult:
        return SolverResult(
            solver_name=f"{candidate.name}_timeout",
            input_state=cube.to_facelets(),
            solution_moves=[],
            solution_length=None,
            metric="HTM",
            runtime_seconds=runtime_seconds,
            expanded_nodes=None,
            generated_nodes=None,
            table_bytes=0,
            status="timeout",
            is_verified=False,
            notes=(
                "resident race backend candidate timed out and was stopped; "
                f"candidate={candidate.name}; candidate_timeout_seconds={timeout_seconds:.6f}"
            ),
        )

    def _stop_remaining(
        self,
        subprocess_candidates: list[_RaceCandidate],
        h48_future: Future[SolverResult] | None,
        rubikoptimal_future: Future[SolverResult] | None,
        nissy_core_direct_future: Future[SolverResult] | None,
        *,
        h48_pending: bool = False,
    ) -> list[str]:
        stopped: list[str] = []
        for candidate in subprocess_candidates:
            _stop_candidate(candidate)
            stopped.append(candidate.name)
        if h48_future is not None and not h48_future.done():
            self._h48.close()
            stopped.append("resident-h48")
        if rubikoptimal_future is not None and not rubikoptimal_future.done():
            self._stop_rubikoptimal_resident()
            stopped.append("rubikoptimal-race")
        if nissy_core_direct_future is not None and not nissy_core_direct_future.done():
            self._stop_nissy_core_direct_resident()
            stopped.append("nissy-core-direct-resident")
        if h48_pending:
            stopped.append("resident-h48-deferred")
        return stopped

    def _wrap_winner(
        self,
        result: SolverResult,
        *,
        selected_backend: str,
        total_runtime_seconds: float,
        started_backends: list[str],
        stopped_backends: list[str],
        setup_notes: list[str],
        h48_start_delay_seconds: float = 0.0,
    ) -> SolverResult:
        return SolverResult(
            solver_name=result.solver_name if selected_backend == "nissy-symmetry-batch" else self.solver_name,
            input_state=result.input_state,
            solution_moves=result.solution_moves,
            solution_length=result.solution_length,
            metric=result.metric,
            runtime_seconds=total_runtime_seconds,
            expanded_nodes=result.expanded_nodes,
            generated_nodes=result.generated_nodes,
            table_bytes=result.table_bytes,
            status=result.status,
            is_verified=result.is_verified,
            notes=(
                "resident race exact oracle; exactness_policy=first_verified_exact_solution_wins; "
                "resident_h48_process=shared_batch_session; "
                f"selected_backend={selected_backend}; started_backends={','.join(started_backends)}; "
                f"stopped_backends={','.join(stopped_backends) if stopped_backends else 'none'}; "
                f"h48_start_delay_seconds={h48_start_delay_seconds:.6f}; "
                f"backend_solver={result.solver_name}; backend_runtime_seconds={result.runtime_seconds:.6f}; "
                f"setup_notes={'; '.join(setup_notes)}; {result.notes}"
            ),
        )


def solve_resident_race_optimal(
    cube: CubeState,
    config: ResidentRaceOptimalOracleConfig | None = None,
    *,
    source_sequence: list[str] | tuple[str, ...] | str | None = None,
) -> SolverResult:
    """Solve one valid 3x3 state by racing Nissy against resident H48."""

    oracle = ResidentRaceOptimalOracle(config)
    try:
        return oracle.solve(cube, source_sequence=source_sequence)
    finally:
        oracle.close()


class PortfolioOptimalOracle:
    """Exact 3x3 oracle portfolio using Nissy optimal plus resident H48.

    The wrapper never downgrades exactness: it returns ``exact`` only when a
    selected backend returns an independently verified exact solution.  If the
    Nissy optimal attempt is unavailable or times out, the same cube is handed
    to the resident H48 oracle as a direct cubie state.
    """

    solver_name = "portfolio_optimal_oracle"

    def __init__(self, config: PortfolioOptimalOracleConfig | None = None) -> None:
        self.config = config or PortfolioOptimalOracleConfig()
        self._h48 = FastOptimalOracle(self.config.h48)
        self._certificates = ExactCertificateStore(
            root=self._h48.root,
            artifact_paths=self.config.certificate_artifacts,
            learned_artifact_path=self.config.learned_certificate_artifact,
            include_external_label=self.config.include_external_label_certificates,
        )

    def __enter__(self) -> "PortfolioOptimalOracle":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def close(self) -> None:
        self._h48.close()

    def solve(
        self,
        cube: CubeState,
        *,
        source_sequence: list[str] | tuple[str, ...] | str | None = None,
    ) -> SolverResult:
        begin = time.perf_counter()
        ok, message = validate_cube(cube)
        if not ok:
            return SolverResult(
                solver_name=self.solver_name,
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
                notes=f"invalid physical cube state rejected before portfolio oracle: {message}",
            )
        if cube.is_solved():
            return SolverResult(
                solver_name=self.solver_name,
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
                notes=(
                    "portfolio exact oracle; selected_backend=solved_fast_path; "
                    "nissy_optimal_invoked=false; resident_h48_invoked=false"
                ),
            )

        certificate_result = self._solve_from_certificate_cache(cube)
        if certificate_result is not None:
            return certificate_result

        nissy_core_result: SolverResult | None = None
        if self.config.try_nissy_core_direct_first and source_sequence is None:
            nissy_core_result = self._try_nissy_core_direct(cube)
            if nissy_core_result.status == "exact" and nissy_core_result.is_verified:
                return self._wrap_backend_result(
                    nissy_core_result,
                    selected_backend="nissy-core-direct",
                    total_runtime_seconds=time.perf_counter() - begin,
                    prefix_notes=(
                        "portfolio exact oracle; nissy_core_direct_invoked=true; "
                        "nissy_optimal_invoked=false; resident_h48_invoked=false"
                    ),
                )

        nissy_result: SolverResult | None = None
        if self.config.try_nissy_first:
            nissy_result = solve_nissy_optimal(
                cube,
                source_sequence=source_sequence,
                timeout_seconds=self.config.nissy_timeout_seconds,
                threads=self.config.nissy_threads,
                binary_path=self.config.nissy_binary_path,
                data_dir=self.config.nissy_data_dir,
                root=self._h48.root,
            )
            if nissy_result.status == "exact" and nissy_result.is_verified:
                return self._wrap_backend_result(
                    nissy_result,
                    selected_backend="nissy-optimal",
                    total_runtime_seconds=time.perf_counter() - begin,
                    prefix_notes=(
                        "portfolio exact oracle; nissy_optimal_invoked=true; "
                        "resident_h48_invoked=false"
                    ),
                )

        upper_lower_result = self._try_upper_lower_certificate(cube, source_sequence=source_sequence)
        if upper_lower_result is not None:
            return upper_lower_result

        if not self.config.try_h48_fallback:
            return self._h48_fallback_disabled_result(
                cube,
                begin=begin,
                nissy_result=nissy_result,
                nissy_core_result=nissy_core_result,
            )

        h48_result = self._h48.solve(cube)
        fallback_note = "nissy_optimal_invoked=false"
        if nissy_core_result is not None:
            fallback_note = (
                "nissy_core_direct_invoked=true; "
                f"nissy_core_direct_status={nissy_core_result.status}; "
                f"nissy_core_direct_runtime_seconds={nissy_core_result.runtime_seconds:.6f}; "
                f"nissy_core_direct_notes={nissy_core_result.notes}; "
                f"{fallback_note}"
            )
        if nissy_result is not None:
            fallback_note = (
                "nissy_optimal_invoked=true; "
                f"nissy_status={nissy_result.status}; "
                f"nissy_runtime_seconds={nissy_result.runtime_seconds:.6f}; "
                f"nissy_notes={nissy_result.notes}"
            )
        return self._wrap_backend_result(
            h48_result,
            selected_backend="resident-h48",
            total_runtime_seconds=time.perf_counter() - begin,
            prefix_notes=(
                "portfolio exact oracle; "
                f"{fallback_note}; resident_h48_invoked=true"
            ),
        )

    def _try_nissy_core_direct(self, cube: CubeState) -> SolverResult:
        return solve_nissy_core_direct_optimal(
            cube,
            solver=self._h48.solver,
            profile=self.config.h48.profile,
            seed=self.config.h48.seed,
            table_path=self._h48.table_path,
            timeout_seconds=self.config.nissy_core_direct_timeout_seconds,
            threads=max(1, self.config.nissy_threads),
            binary_path=self.config.nissy_core_direct_binary_path,
            root=self._h48.root,
        )

    def _try_nissy_core_direct_batch(self, cubes: list[CubeState]) -> list[SolverResult]:
        return solve_nissy_core_direct_optimal_batch(
            cubes,
            solver=self._h48.solver,
            profile=self.config.h48.profile,
            seed=self.config.h48.seed,
            table_path=self._h48.table_path,
            timeout_seconds=self.config.nissy_core_direct_timeout_seconds,
            threads=max(1, self.config.nissy_threads),
            binary_path=self.config.nissy_core_direct_binary_path,
            root=self._h48.root,
        )

    def _solve_from_certificate_cache(self, cube: CubeState) -> SolverResult | None:
        if not self.config.try_certificate_cache:
            return None
        begin = time.perf_counter()
        certificate = self._certificates.find(cube)
        if certificate is None:
            return None
        return self._result_from_certificate(
            cube,
            certificate,
            runtime_seconds=time.perf_counter() - begin,
        )

    def _result_from_certificate(
        self,
        cube: CubeState,
        certificate: ExactCertificate,
        *,
        runtime_seconds: float,
    ) -> SolverResult:
        try:
            artifact_display = certificate.artifact_path.relative_to(self._h48.root)
        except ValueError:
            artifact_display = certificate.artifact_path
        external_label = certificate.exactness_basis != LOCAL_PROOF_BASIS
        if external_label:
            status = EXTERNAL_LABEL_STATUS
            revalidation_note = (
                "saved third-party-labeled artifact row revalidated before reuse "
                "(revalidation proves solution validity only); optimality rests on the "
                f"third-party basis '{certificate.exactness_basis}' and was NOT proven "
                "locally; served under explicit opt-in "
                "(include_external_label_certificates=True)"
            )
        else:
            status = "exact"
            revalidation_note = "saved exact/verified artifact row revalidated before reuse"
        return SolverResult(
            solver_name=self.solver_name,
            input_state=cube.to_facelets(),
            solution_moves=certificate.solution_moves,
            solution_length=certificate.solution_length,
            metric="HTM",
            runtime_seconds=runtime_seconds,
            expanded_nodes=0,
            generated_nodes=None,
            table_bytes=0,
            status=status,
            is_verified=True,
            notes=(
                "portfolio exact oracle; selected_backend=exact-certificate-cache; "
                "nissy_optimal_invoked=false; resident_h48_invoked=false; "
                f"{revalidation_note}; "
                f"certificate_artifact={artifact_display}; "
                f"certificate_case_id={certificate.case_id}; "
                f"certificate_derivation={certificate.derivation}; "
                f"certificate_exactness_basis={certificate.exactness_basis}; "
                f"certificate_source_solver={certificate.source_solver}; "
                f"certificate_source_runtime_seconds={certificate.source_runtime_seconds}"
            ),
        )

    def _try_upper_lower_certificate(
        self,
        cube: CubeState,
        *,
        source_sequence: list[str] | tuple[str, ...] | str | None = None,
    ) -> SolverResult | None:
        if not self.config.try_upper_lower_certificate:
            return None
        begin = time.perf_counter()
        upper = self._shortest_verified_upper_bound(cube, source_sequence=source_sequence)
        if upper is None or upper.solution_length is None:
            return None
        lower_kwargs = {
            "solver": self._h48.solver,
            "profile": self.config.h48.profile,
            "seed": self.config.h48.seed,
            "table_path": self._h48.table_path,
            "timeout_seconds": self.config.lower_bound_timeout_seconds,
            "threads": self.config.h48.threads,
            "skip_table_check": self.config.h48.trusted_table,
            "preload_table": False,
            "root": self._h48.root,
        }
        if self.config.lower_bound_symmetry_variants > 0:
            lower = compute_h48_native_rotational_lower_bound(
                cube,
                variant_count=self.config.lower_bound_symmetry_variants,
                include_identity=self.config.lower_bound_symmetry_include_identity,
                **lower_kwargs,
            )
        else:
            lower = compute_h48_native_lower_bound(cube, **lower_kwargs)
        if lower.status != "lower_bound" or lower.lower_bound is None:
            return None
        symmetry_upper: SolverResult | None = None
        if upper.solution_length != lower.lower_bound:
            symmetry_upper = self._shortest_kociemba_symmetry_upper_bound(
                cube,
                current_best=upper,
                target_length=lower.lower_bound,
            )
            if (
                symmetry_upper is not None
                and symmetry_upper.solution_length is not None
                and (
                    upper.solution_length is None
                    or symmetry_upper.solution_length < upper.solution_length
                    or symmetry_upper.solution_length == lower.lower_bound
                )
            ):
                upper = symmetry_upper
        if upper.solution_length != lower.lower_bound:
            bounded_proof = self._try_h48_upper_bound_proof(
                cube,
                upper=upper,
                lower=lower,
                begin=begin,
                symmetry_upper_used=symmetry_upper is not None,
            )
            if bounded_proof is not None:
                return bounded_proof
            native_proof = self._try_native_korf_upper_bound_proof(
                cube,
                upper=upper,
                lower=lower,
                begin=begin,
                symmetry_upper_used=symmetry_upper is not None,
                source_sequence=source_sequence,
                proof_loop_invoked=False,
            )
            if native_proof is not None:
                return native_proof
            return None
        return self._build_upper_lower_certificate_result(
            cube,
            upper=upper,
            lower=lower,
            runtime_seconds=time.perf_counter() - begin,
            symmetry_upper_used=symmetry_upper is not None,
            lower_bound_batch_invoked=False,
        )

    def _try_upper_lower_certificates_batch(
        self,
        items: list[tuple[int, CubeState, list[str] | tuple[str, ...] | str | None]],
    ) -> dict[int, SolverResult]:
        if not self.config.try_upper_lower_certificate or not items:
            return {}
        begin = time.perf_counter()
        upper_by_index: dict[int, SolverResult] = {}
        bound_items: list[tuple[int, CubeState]] = []
        for index, cube, source in items:
            upper = self._shortest_verified_upper_bound(cube, source_sequence=source)
            if upper is None or upper.solution_length is None:
                continue
            upper_by_index[index] = upper
            bound_items.append((index, cube))
        if not bound_items:
            return {}

        lower_kwargs = {
            "solver": self._h48.solver,
            "profile": self.config.h48.profile,
            "seed": self.config.h48.seed,
            "table_path": self._h48.table_path,
            "timeout_seconds": self.config.lower_bound_timeout_seconds,
            "threads": self.config.h48.threads,
            "skip_table_check": self.config.h48.trusted_table,
            "preload_table": False,
            "root": self._h48.root,
        }
        if self.config.lower_bound_symmetry_variants > 0:
            lower_results = compute_h48_native_rotational_lower_bound_batch(
                [cube for _, cube in bound_items],
                variant_count=self.config.lower_bound_symmetry_variants,
                include_identity=self.config.lower_bound_symmetry_include_identity,
                **lower_kwargs,
            )
        else:
            lower_results = compute_h48_native_lower_bound_batch(
                [cube for _, cube in bound_items],
                **lower_kwargs,
            )

        certified: dict[int, SolverResult] = {}
        proof_candidates: list[tuple[int, CubeState, SolverResult, H48LowerBoundResult, bool]] = []
        for (index, cube), lower in zip(bound_items, lower_results, strict=True):
            upper = upper_by_index[index]
            if lower.status != "lower_bound" or lower.lower_bound is None:
                continue
            symmetry_upper: SolverResult | None = None
            if upper.solution_length != lower.lower_bound:
                symmetry_upper = self._shortest_kociemba_symmetry_upper_bound(
                    cube,
                    current_best=upper,
                    target_length=lower.lower_bound,
                )
                if (
                    symmetry_upper is not None
                    and symmetry_upper.solution_length is not None
                    and (
                        upper.solution_length is None
                        or symmetry_upper.solution_length < upper.solution_length
                        or symmetry_upper.solution_length == lower.lower_bound
                    )
                ):
                    upper = symmetry_upper
            if upper.solution_length != lower.lower_bound:
                proof_candidates.append(
                    (index, cube, upper, lower, symmetry_upper is not None)
                )
                continue
            certified[index] = self._build_upper_lower_certificate_result(
                cube,
                upper=upper,
                lower=lower,
                runtime_seconds=time.perf_counter() - begin,
                symmetry_upper_used=symmetry_upper is not None,
                lower_bound_batch_invoked=True,
            )
        h48_proof_results = self._try_h48_upper_bound_proofs_batch(
            proof_candidates,
            begin=begin,
        )
        certified.update(h48_proof_results)
        native_proof_candidates = [
            candidate
            for candidate in proof_candidates
            if candidate[0] not in h48_proof_results
        ]
        certified.update(
            self._try_native_korf_upper_bound_proofs(
                native_proof_candidates,
                begin=begin,
            )
        )
        return certified

    def _build_upper_lower_certificate_result(
        self,
        cube: CubeState,
        *,
        upper: SolverResult,
        lower: H48LowerBoundResult,
        runtime_seconds: float,
        symmetry_upper_used: bool,
        lower_bound_batch_invoked: bool,
    ) -> SolverResult:
        result = SolverResult(
            solver_name=self.solver_name,
            input_state=cube.to_facelets(),
            solution_moves=upper.solution_moves,
            solution_length=upper.solution_length,
            metric="HTM",
            runtime_seconds=runtime_seconds,
            expanded_nodes=0,
            generated_nodes=None,
            table_bytes=lower.table_bytes,
            status="exact",
            is_verified=True,
            notes=(
                "portfolio exact oracle; selected_backend=upper-lower-certificate; "
                "nissy_optimal_invoked=false; resident_h48_invoked=false; "
                "h48_lower_bound_invoked=true; admissible_lower_bound_matches_verified_upper_solution=true; "
                f"h48_lower_bound_batch_invoked={str(lower_bound_batch_invoked).lower()}; "
                f"upper_solver={upper.solver_name}; upper_runtime_seconds={upper.runtime_seconds:.6f}; "
                f"h48_lower_bound={lower.lower_bound}; h48_lower_bound_runtime_seconds={lower.runtime_seconds:.6f}; "
                f"h48_lower_bound_notes={lower.notes}; "
                f"kociemba_symmetry_upper_bound_used={str(symmetry_upper_used).lower()}; "
                f"upper_notes={upper.notes}"
            ),
        )
        self.remember_result(result, selected_backend="upper-lower-certificate")
        return result

    def _h48_upper_bound_proof_max_depth(
        self,
        *,
        upper: SolverResult,
        lower: H48LowerBoundResult,
    ) -> int | None:
        if upper.solution_length is None:
            return None
        proof_max_depth = upper.solution_length - 1
        if proof_max_depth < 0 or proof_max_depth > self.config.h48.max_depth:
            return None
        gap = upper.solution_length - int(lower.lower_bound or 0)
        if gap < 1 or gap > max(1, int(self.config.h48_upper_bound_proof_max_gap)):
            return None
        return proof_max_depth

    def _native_korf_upper_bound_proof_max_depth(
        self,
        *,
        upper: SolverResult,
        lower: H48LowerBoundResult,
    ) -> int | None:
        if upper.solution_length is None:
            return None
        proof_max_depth = upper.solution_length - 1
        if proof_max_depth < 0 or proof_max_depth > self.config.h48.max_depth:
            return None
        gap = upper.solution_length - int(lower.lower_bound or 0)
        if gap < 1 or gap > max(1, int(self.config.native_korf_upper_bound_proof_max_gap)):
            return None
        return proof_max_depth

    def _build_h48_upper_bound_proof_result(
        self,
        cube: CubeState,
        *,
        upper: SolverResult,
        lower: H48LowerBoundResult,
        proof: SolverResult,
        begin: float,
        proof_max_depth: int,
        timeout: float,
        symmetry_upper_used: bool,
        proof_batch_invoked: bool,
        proof_group_size: int | None = None,
    ) -> SolverResult | None:
        proved_lower_bound = _note_int(proof.notes, "proved_lower_bound")
        if proof.status != "lower_bound" or proved_lower_bound is None:
            return None
        if upper.solution_length is None or proved_lower_bound < upper.solution_length:
            return None
        group_note = ""
        if proof_group_size is not None:
            group_note = f"h48_proof_group_size={proof_group_size}; "
        result = SolverResult(
            solver_name=self.solver_name,
            input_state=cube.to_facelets(),
            solution_moves=upper.solution_moves,
            solution_length=upper.solution_length,
            metric="HTM",
            runtime_seconds=time.perf_counter() - begin,
            expanded_nodes=proof.expanded_nodes,
            generated_nodes=None,
            table_bytes=proof.table_bytes,
            status="exact",
            is_verified=True,
            notes=(
                "portfolio exact oracle; selected_backend=h48-upper-bound-proof; "
                "nissy_optimal_invoked=false; resident_h48_invoked=false; "
                "h48_upper_bound_proof_invoked=true; "
                f"h48_upper_bound_proof_batch_invoked={str(proof_batch_invoked).lower()}; "
                "completed bounded H48 search proved no shorter solution than verified upper bound; "
                f"upper_solver={upper.solver_name}; upper_runtime_seconds={upper.runtime_seconds:.6f}; "
                f"candidate_upper_length={upper.solution_length}; "
                f"h48_lower_bound={lower.lower_bound}; h48_lower_bound_runtime_seconds={lower.runtime_seconds:.6f}; "
                f"h48_proof_max_depth={proof_max_depth}; {group_note}"
                f"h48_proved_lower_bound={proved_lower_bound}; "
                f"h48_proof_runtime_seconds={proof.runtime_seconds:.6f}; "
                f"h48_proof_timeout_seconds={timeout}; "
                f"kociemba_symmetry_upper_bound_used={str(symmetry_upper_used).lower()}; "
                f"h48_lower_bound_notes={lower.notes}; h48_proof_notes={proof.notes}; "
                f"upper_notes={upper.notes}"
            ),
        )
        self.remember_result(result, selected_backend="h48-upper-bound-proof")
        return result

    def _try_h48_upper_bound_proofs_batch(
        self,
        items: list[tuple[int, CubeState, SolverResult, H48LowerBoundResult, bool]],
        *,
        begin: float,
    ) -> dict[int, SolverResult]:
        timeout = float(self.config.h48_upper_bound_proof_timeout_seconds)
        if timeout <= 0 or not items:
            return {}

        proof_groups: dict[
            int,
            list[tuple[int, CubeState, SolverResult, H48LowerBoundResult, bool]],
        ] = {}
        for item in items:
            _, _, upper, lower, _ = item
            proof_max_depth = self._h48_upper_bound_proof_max_depth(upper=upper, lower=lower)
            if proof_max_depth is None:
                continue
            proof_groups.setdefault(proof_max_depth, []).append(item)

        certified: dict[int, SolverResult] = {}
        for proof_max_depth, group in proof_groups.items():
            proof_results = solve_h48_native_resident_batch(
                [cube for _, cube, _, _, _ in group],
                solver=self._h48.solver,
                profile=self.config.h48.profile,
                seed=self.config.h48.seed,
                table_path=self._h48.table_path,
                timeout_seconds=timeout,
                threads=self.config.h48.threads,
                max_depth=proof_max_depth,
                skip_table_check=self.config.h48.trusted_table,
                preload_table=False,
                auto_min_depth=self.config.h48.auto_min_depth,
                root=self._h48.root,
            )
            for (index, cube, upper, lower, symmetry_upper_used), proof in zip(
                group,
                proof_results,
                strict=True,
            ):
                if proof.status == "exact" and proof.is_verified:
                    certified[index] = self._wrap_backend_result(
                        proof,
                        selected_backend="h48-upper-bound-proof-found-shorter",
                        total_runtime_seconds=time.perf_counter() - begin,
                        prefix_notes=(
                            "portfolio exact oracle; "
                            "h48_upper_bound_proof_invoked=true; "
                            "h48_upper_bound_proof_batch_invoked=true; "
                            "verified shorter solution found while checking candidate upper bound; "
                            f"candidate_upper_length={upper.solution_length}; "
                            f"h48_proof_max_depth={proof_max_depth}; "
                            f"h48_proof_group_size={len(group)}; "
                            f"h48_lower_bound={lower.lower_bound}; "
                            f"kociemba_symmetry_upper_bound_used={str(symmetry_upper_used).lower()}"
                        ),
                    )
                    continue
                proof_result = self._build_h48_upper_bound_proof_result(
                    cube,
                    upper=upper,
                    lower=lower,
                    proof=proof,
                    begin=begin,
                    proof_max_depth=proof_max_depth,
                    timeout=timeout,
                    symmetry_upper_used=symmetry_upper_used,
                    proof_batch_invoked=True,
                    proof_group_size=len(group),
                )
                if proof_result is not None:
                    certified[index] = proof_result
        return certified

    def _try_h48_upper_bound_proof(
        self,
        cube: CubeState,
        *,
        upper: SolverResult,
        lower: H48LowerBoundResult,
        begin: float,
        symmetry_upper_used: bool,
    ) -> SolverResult | None:
        timeout = float(self.config.h48_upper_bound_proof_timeout_seconds)
        if timeout <= 0:
            return None
        proof_max_depth = self._h48_upper_bound_proof_max_depth(upper=upper, lower=lower)
        if proof_max_depth is None:
            return None

        proof = solve_h48_native_optimal(
            cube,
            solver=self._h48.solver,
            profile=self.config.h48.profile,
            seed=self.config.h48.seed,
            table_path=self._h48.table_path,
            timeout_seconds=timeout,
            threads=self.config.h48.threads,
            max_depth=proof_max_depth,
            skip_table_check=self.config.h48.trusted_table,
            preload_table=False,
            auto_min_depth=self.config.h48.auto_min_depth,
            root=self._h48.root,
        )
        if proof.status == "exact" and proof.is_verified:
            return self._wrap_backend_result(
                proof,
                selected_backend="h48-upper-bound-proof-found-shorter",
                total_runtime_seconds=time.perf_counter() - begin,
                prefix_notes=(
                    "portfolio exact oracle; "
                    "h48_upper_bound_proof_invoked=true; "
                    "h48_upper_bound_proof_batch_invoked=false; "
                    "verified shorter solution found while checking candidate upper bound; "
                    f"candidate_upper_length={upper.solution_length}; "
                    f"h48_proof_max_depth={proof_max_depth}; "
                    f"h48_lower_bound={lower.lower_bound}; "
                    f"kociemba_symmetry_upper_bound_used={str(symmetry_upper_used).lower()}"
                ),
            )

        return self._build_h48_upper_bound_proof_result(
            cube,
            upper=upper,
            lower=lower,
            proof=proof,
            begin=begin,
            proof_max_depth=proof_max_depth,
            timeout=timeout,
            symmetry_upper_used=symmetry_upper_used,
            proof_batch_invoked=False,
        )

    def _try_native_korf_upper_bound_proofs(
        self,
        items: list[tuple[int, CubeState, SolverResult, H48LowerBoundResult, bool]],
        *,
        begin: float,
    ) -> dict[int, SolverResult]:
        if self.config.native_korf_upper_bound_proof_timeout_seconds <= 0 or not items:
            return {}
        certified: dict[int, SolverResult] = {}
        for index, cube, upper, lower, symmetry_upper_used in items:
            proof_result = self._try_native_korf_upper_bound_proof(
                cube,
                upper=upper,
                lower=lower,
                begin=begin,
                symmetry_upper_used=symmetry_upper_used,
                source_sequence=None,
                proof_loop_invoked=True,
            )
            if proof_result is not None:
                certified[index] = proof_result
        return certified

    def _try_native_korf_upper_bound_proof(
        self,
        cube: CubeState,
        *,
        upper: SolverResult,
        lower: H48LowerBoundResult,
        begin: float,
        symmetry_upper_used: bool,
        source_sequence: list[str] | tuple[str, ...] | str | None,
        proof_loop_invoked: bool,
    ) -> SolverResult | None:
        timeout = float(self.config.native_korf_upper_bound_proof_timeout_seconds)
        if timeout <= 0:
            return None
        proof_max_depth = self._native_korf_upper_bound_proof_max_depth(
            upper=upper,
            lower=lower,
        )
        if proof_max_depth is None or upper.solution_moves is None:
            return None

        parsed_source: list[str] | tuple[str, ...] | None
        if isinstance(source_sequence, str):
            try:
                parsed_source = parse_sequence(source_sequence)
            except Exception:
                parsed_source = None
        else:
            parsed_source = source_sequence

        proof = solve_korf_native_optimal(
            cube,
            max_depth=proof_max_depth,
            timeout_seconds=timeout,
            threads=max(1, self.config.h48.threads),
            split_depth=max(1, int(self.config.native_korf_upper_bound_proof_split_depth)),
            nissy_heuristic=bool(self.config.native_korf_upper_bound_proof_nissy_heuristic),
            nissy_axis_transforms=True,
            nissy_data_dir=self.config.nissy_data_dir,
            source_sequence=parsed_source,
            upper_solution=upper.solution_moves,
            upper_bound_proof_strategy="single-bound",
            root=self._h48.root,
        )
        if (
            proof.status != "exact"
            or not proof.is_verified
            or proof.solution_length is None
            or upper.solution_length is None
            or proof.solution_length > upper.solution_length
        ):
            return None
        return self._wrap_backend_result(
            proof,
            selected_backend="native-korf-upper-bound-proof",
            total_runtime_seconds=time.perf_counter() - begin,
            prefix_notes=(
                "portfolio exact oracle; "
                "native_korf_upper_bound_proof_invoked=true; "
                f"native_korf_upper_bound_proof_loop_invoked={str(proof_loop_invoked).lower()}; "
                "completed native Korf/IDA* single-bound proof below verified upper bound; "
                f"upper_solver={upper.solver_name}; upper_runtime_seconds={upper.runtime_seconds:.6f}; "
                f"candidate_upper_length={upper.solution_length}; "
                f"h48_lower_bound={lower.lower_bound}; "
                f"h48_lower_bound_runtime_seconds={lower.runtime_seconds:.6f}; "
                f"native_korf_proof_max_depth={proof_max_depth}; "
                f"native_korf_proof_timeout_seconds={timeout}; "
                f"native_korf_proof_split_depth={max(1, int(self.config.native_korf_upper_bound_proof_split_depth))}; "
                f"native_korf_proof_nissy_heuristic={str(bool(self.config.native_korf_upper_bound_proof_nissy_heuristic)).lower()}; "
                f"kociemba_symmetry_upper_bound_used={str(symmetry_upper_used).lower()}; "
                f"h48_lower_bound_notes={lower.notes}; upper_notes={upper.notes}"
            ),
        )

    def _shortest_verified_upper_bound(
        self,
        cube: CubeState,
        *,
        source_sequence: list[str] | tuple[str, ...] | str | None = None,
    ) -> SolverResult | None:
        candidates: list[SolverResult] = []
        if source_sequence is not None:
            try:
                scramble = parse_sequence(source_sequence)
                solution = inverse_sequence(scramble)
                verification = verify_solution(cube, solution)
                if verification.ok:
                    candidates.append(
                        SolverResult(
                            solver_name="source_sequence_inverse_upper_bound",
                            input_state=cube.to_facelets(),
                            solution_moves=solution,
                            solution_length=len(solution),
                            metric="HTM",
                            runtime_seconds=0.0,
                            expanded_nodes=None,
                            generated_nodes=None,
                            table_bytes=None,
                            status="non_exact",
                            is_verified=True,
                            notes="source sequence inverse verified as an upper-bound solution; no optimality proof alone",
                        )
                    )
            except Exception:
                pass
        kociemba = solve_kociemba_adapter(cube)
        if kociemba.is_verified and kociemba.solution_length is not None:
            candidates.append(kociemba)
        if not candidates:
            return None
        return min(candidates, key=lambda result: result.solution_length or 10**9)

    def _shortest_kociemba_symmetry_upper_bound(
        self,
        cube: CubeState,
        *,
        current_best: SolverResult | None = None,
        target_length: int | None = None,
    ) -> SolverResult | None:
        variant_count = max(0, int(self.config.kociemba_upper_bound_symmetry_variants))
        if variant_count <= 0:
            return None
        rotations = [rotation for rotation in CUBE_ROTATIONS if not rotation.is_identity][:variant_count]
        if not rotations:
            return None
        best = current_best
        tried = 0
        for rotation in rotations:
            tried += 1
            rotated_cube = rotation.transform_cube(cube)
            rotated_upper = solve_kociemba_adapter(rotated_cube)
            if not rotated_upper.is_verified or rotated_upper.solution_length is None:
                continue
            solution = rotation.inverse_transform_sequence(rotated_upper.solution_moves)
            verification = verify_solution(cube, solution)
            if not verification.ok:
                continue
            candidate = SolverResult(
                solver_name="kociemba_two_phase_adapter_symmetry_upper_bound",
                input_state=cube.to_facelets(),
                solution_moves=solution,
                solution_length=len(solution),
                metric=rotated_upper.metric,
                runtime_seconds=rotated_upper.runtime_seconds,
                expanded_nodes=rotated_upper.expanded_nodes,
                generated_nodes=rotated_upper.generated_nodes,
                table_bytes=rotated_upper.table_bytes,
                status="non_exact",
                is_verified=True,
                notes=(
                    "Kociemba adapter whole-cube symmetry upper-bound candidate verified; "
                    "no optimality proof claimed until compared with an admissible lower bound; "
                    "kociemba_symmetry_upper_bound=true; "
                    f"selected_rotation={rotation.name}; "
                    f"symmetry_variants_configured={variant_count}; "
                    f"symmetry_variants_tried={tried}; "
                    f"rotated_solution_length={rotated_upper.solution_length}; "
                    f"rotated_notes={rotated_upper.notes}"
                ),
            )
            if best is None or (
                candidate.solution_length is not None
                and candidate.solution_length < (best.solution_length or 10**9)
            ):
                best = candidate
            if target_length is not None and candidate.solution_length <= target_length:
                break
        if best is current_best:
            return None
        return best

    def _wrap_backend_result(
        self,
        result: SolverResult,
        *,
        selected_backend: str,
        total_runtime_seconds: float,
        prefix_notes: str,
    ) -> SolverResult:
        wrapped = SolverResult(
            solver_name=self.solver_name,
            input_state=result.input_state,
            solution_moves=result.solution_moves,
            solution_length=result.solution_length,
            metric=result.metric,
            runtime_seconds=total_runtime_seconds,
            expanded_nodes=result.expanded_nodes,
            generated_nodes=result.generated_nodes,
            table_bytes=result.table_bytes,
            status=result.status,
            is_verified=result.is_verified,
            notes=(
                f"{prefix_notes}; selected_backend={selected_backend}; "
                f"backend_solver={result.solver_name}; "
                f"backend_runtime_seconds={result.runtime_seconds:.6f}; {result.notes}"
            ),
        )
        self.remember_result(wrapped, selected_backend=selected_backend)
        return wrapped

    def remember_result(self, result: SolverResult, *, selected_backend: str) -> bool:
        if selected_backend in {"exact-certificate-cache", "solved_fast_path"}:
            return False
        return self._certificates.remember_result(result, selected_backend=selected_backend)

    def solve_many(
        self,
        cubes: Iterable[CubeState],
        *,
        source_sequences: Iterable[list[str] | tuple[str, ...] | str | None] | None = None,
    ) -> list[SolverResult]:
        cube_list = list(cubes)
        if source_sequences is None:
            source_list: list[list[str] | tuple[str, ...] | str | None] = [None] * len(cube_list)
        else:
            source_list = list(source_sequences)
            if len(source_list) != len(cube_list):
                raise ValueError("source_sequences length must match cubes length")

        if not self.config.try_nissy_first:
            return [self.solve(cube, source_sequence=source) for cube, source in zip(cube_list, source_list, strict=True)]

        results: list[SolverResult | None] = [None] * len(cube_list)
        pending: list[tuple[int, CubeState, list[str] | tuple[str, ...] | str | None]] = []
        for index, (cube, source) in enumerate(zip(cube_list, source_list, strict=True)):
            ok, _ = validate_cube(cube)
            if not ok or cube.is_solved():
                results[index] = self.solve(cube, source_sequence=source)
            else:
                certificate_result = self._solve_from_certificate_cache(cube)
                if certificate_result is not None:
                    results[index] = certificate_result
                else:
                    pending.append((index, cube, source))

        fallback: list[tuple[int, CubeState, SolverResult | None, SolverResult | None]] = []
        nissy_pending: list[
            tuple[int, CubeState, list[str] | tuple[str, ...] | str | None, SolverResult | None]
        ] = []
        if pending:
            direct_pending: list[tuple[int, CubeState]] = []
            for index, cube, source in pending:
                if self.config.try_nissy_core_direct_first and source is None:
                    direct_pending.append((index, cube))

            direct_results_by_index: dict[int, SolverResult] = {}
            if direct_pending:
                direct_results = self._try_nissy_core_direct_batch([cube for _, cube in direct_pending])
                for (index, _), nissy_core_result in zip(direct_pending, direct_results, strict=True):
                    direct_results_by_index[index] = nissy_core_result
                    if nissy_core_result.status == "exact" and nissy_core_result.is_verified:
                        results[index] = self._wrap_backend_result(
                            nissy_core_result,
                            selected_backend="nissy-core-direct",
                            total_runtime_seconds=nissy_core_result.runtime_seconds,
                            prefix_notes=(
                                "portfolio exact oracle; nissy_core_direct_invoked=true; "
                                "nissy_core_direct_batch_invoked=true; "
                                "nissy_optimal_batch_invoked=false; resident_h48_invoked=false"
                            ),
                        )
                        continue

            for index, cube, source in pending:
                if results[index] is not None:
                    continue
                nissy_pending.append((index, cube, source, direct_results_by_index.get(index)))

        if nissy_pending:
            nissy_results = solve_nissy_optimal_batch(
                [cube for _, cube, _, _ in nissy_pending],
                source_sequences=[source for _, _, source, _ in nissy_pending],
                timeout_seconds=self.config.nissy_timeout_seconds,
                threads=self.config.nissy_threads,
                binary_path=self.config.nissy_binary_path,
                data_dir=self.config.nissy_data_dir,
                root=self._h48.root,
            )
            for (index, cube, _, nissy_core_result), nissy_result in zip(
                nissy_pending,
                nissy_results,
                strict=True,
            ):
                if nissy_result.status == "exact" and nissy_result.is_verified:
                    direct_note = ""
                    if nissy_core_result is not None:
                        direct_note = (
                            "nissy_core_direct_invoked=true; "
                            f"nissy_core_direct_status={nissy_core_result.status}; "
                            f"nissy_core_direct_runtime_seconds={nissy_core_result.runtime_seconds:.6f}; "
                            f"nissy_core_direct_notes={nissy_core_result.notes}; "
                        )
                    results[index] = self._wrap_backend_result(
                        nissy_result,
                        selected_backend="nissy-optimal-batch",
                        total_runtime_seconds=(
                            nissy_result.runtime_seconds
                            + (nissy_core_result.runtime_seconds if nissy_core_result is not None else 0.0)
                        ),
                        prefix_notes=(
                            f"portfolio exact oracle; {direct_note}nissy_optimal_batch_invoked=true; "
                            "resident_h48_invoked=false"
                        ),
                    )
                else:
                    fallback.append((index, cube, nissy_result, nissy_core_result))

        batch_certificate_results = (
            self._try_upper_lower_certificates_batch(
                [(item_index, item_cube, source_list[item_index]) for item_index, item_cube, _, _ in fallback]
            )
            if fallback
            else {}
        )

        for index, cube, nissy_result, nissy_core_result in fallback:
            certificate_result = self._solve_from_certificate_cache(cube)
            if certificate_result is not None:
                results[index] = certificate_result
                continue
            upper_lower_result = batch_certificate_results.get(index)
            if upper_lower_result is not None:
                results[index] = upper_lower_result
                continue
            if not self.config.try_h48_fallback:
                results[index] = self._h48_fallback_disabled_result(
                    cube,
                    begin=None,
                    nissy_result=nissy_result,
                    nissy_core_result=nissy_core_result,
                )
                continue
            h48_result = self._h48.solve(cube)
            total_runtime = h48_result.runtime_seconds
            fallback_tokens = []
            if nissy_core_result is not None:
                total_runtime += nissy_core_result.runtime_seconds
                fallback_tokens.extend(
                    [
                        "nissy_core_direct_invoked=true",
                        f"nissy_core_direct_status={nissy_core_result.status}",
                        f"nissy_core_direct_runtime_seconds={nissy_core_result.runtime_seconds:.6f}",
                        f"nissy_core_direct_notes={nissy_core_result.notes}",
                    ]
                )
            else:
                fallback_tokens.append("nissy_core_direct_invoked=false")
            if nissy_result is not None:
                total_runtime += nissy_result.runtime_seconds
                fallback_tokens.extend(
                    [
                        "nissy_optimal_batch_invoked=true",
                        f"nissy_status={nissy_result.status}",
                        f"nissy_runtime_seconds={nissy_result.runtime_seconds:.6f}",
                        f"nissy_notes={nissy_result.notes}",
                    ]
                )
            else:
                fallback_tokens.append("nissy_optimal_batch_invoked=false")
            results[index] = self._wrap_backend_result(
                h48_result,
                selected_backend="resident-h48",
                total_runtime_seconds=total_runtime,
                prefix_notes=(
                    "portfolio exact oracle; "
                    f"{'; '.join(fallback_tokens)}; resident_h48_invoked=true"
                ),
            )

        return [result for result in results if result is not None]

    def _h48_fallback_disabled_result(
        self,
        cube: CubeState,
        *,
        begin: float | None,
        nissy_result: SolverResult | None,
        nissy_core_result: SolverResult | None,
    ) -> SolverResult:
        fallback_tokens = []
        total_runtime = 0.0 if begin is None else time.perf_counter() - begin
        status = "timeout"
        table_bytes = 0
        if nissy_core_result is not None:
            if begin is None:
                total_runtime += nissy_core_result.runtime_seconds
            status = nissy_core_result.status
            table_bytes = nissy_core_result.table_bytes or table_bytes
            fallback_tokens.extend(
                [
                    "nissy_core_direct_invoked=true",
                    f"nissy_core_direct_status={nissy_core_result.status}",
                    f"nissy_core_direct_runtime_seconds={nissy_core_result.runtime_seconds:.6f}",
                    f"nissy_core_direct_notes={nissy_core_result.notes}",
                ]
            )
        else:
            fallback_tokens.append("nissy_core_direct_invoked=false")
        if nissy_result is not None:
            if begin is None:
                total_runtime += nissy_result.runtime_seconds
            status = nissy_result.status
            table_bytes = nissy_result.table_bytes or table_bytes
            fallback_tokens.extend(
                [
                    "nissy_optimal_batch_invoked=true",
                    f"nissy_status={nissy_result.status}",
                    f"nissy_runtime_seconds={nissy_result.runtime_seconds:.6f}",
                    f"nissy_notes={nissy_result.notes}",
                ]
            )
        else:
            fallback_tokens.append("nissy_optimal_batch_invoked=false")
        return SolverResult(
            solver_name=self.solver_name,
            input_state=cube.to_facelets(),
            solution_moves=[],
            solution_length=None,
            metric="HTM",
            runtime_seconds=total_runtime,
            expanded_nodes=None,
            generated_nodes=None,
            table_bytes=table_bytes,
            status=status,
            is_verified=False,
            notes=(
                "portfolio exact oracle; "
                f"{'; '.join(fallback_tokens)}; "
                "resident_h48_invoked=false; h48_fallback_disabled=true"
            ),
        )

    def distance(
        self,
        cube: CubeState,
        *,
        source_sequence: list[str] | tuple[str, ...] | str | None = None,
    ) -> int | None:
        result = self.solve(cube, source_sequence=source_sequence)
        if result.status == "exact" and result.is_verified:
            return result.solution_length
        return None


def solve_portfolio_optimal(
    cube: CubeState,
    config: PortfolioOptimalOracleConfig | None = None,
    *,
    source_sequence: list[str] | tuple[str, ...] | str | None = None,
) -> SolverResult:
    """Solve one valid 3x3 state with the Nissy/H48 exact oracle portfolio."""

    oracle = PortfolioOptimalOracle(config)
    try:
        return oracle.solve(cube, source_sequence=source_sequence)
    finally:
        oracle.close()


class UniversalOptimalOracle:
    """Unified optimized exact oracle for arbitrary valid 3x3 states.

    This is the highest-level package API for thesis experiments.  It tries the
    cheapest exact proof paths first and falls back to the resident exact-backend
    race.  It does not turn timeouts into claims: exactness is returned only for
    verified exact solutions or revalidated saved certificates.
    """

    solver_name = "universal_optimal_oracle"

    def __init__(self, config: UniversalOptimalOracleConfig | None = None) -> None:
        self.config = config or UniversalOptimalOracleConfig()
        portfolio_config = PortfolioOptimalOracleConfig(
            h48=self.config.resident_race.h48,
            nissy_timeout_seconds=0.0,
            nissy_threads=self.config.resident_race.nissy_threads,
            nissy_binary_path=self.config.resident_race.nissy_binary_path,
            nissy_data_dir=self.config.resident_race.nissy_data_dir,
            try_nissy_first=False,
            try_certificate_cache=self.config.try_certificate_cache,
            certificate_artifacts=self.config.certificate_artifacts,
            learned_certificate_artifact=self.config.learned_certificate_artifact,
            include_external_label_certificates=self.config.include_external_label_certificates,
            try_upper_lower_certificate=self.config.try_upper_lower_certificate,
            lower_bound_timeout_seconds=self.config.lower_bound_timeout_seconds,
            lower_bound_symmetry_variants=self.config.lower_bound_symmetry_variants,
            lower_bound_symmetry_include_identity=self.config.lower_bound_symmetry_include_identity,
            kociemba_upper_bound_symmetry_variants=self.config.kociemba_upper_bound_symmetry_variants,
            h48_upper_bound_proof_timeout_seconds=self.config.h48_upper_bound_proof_timeout_seconds,
            h48_upper_bound_proof_max_gap=self.config.h48_upper_bound_proof_max_gap,
            native_korf_upper_bound_proof_timeout_seconds=(
                self.config.native_korf_upper_bound_proof_timeout_seconds
            ),
            native_korf_upper_bound_proof_max_gap=self.config.native_korf_upper_bound_proof_max_gap,
            native_korf_upper_bound_proof_split_depth=(
                self.config.native_korf_upper_bound_proof_split_depth
            ),
            native_korf_upper_bound_proof_nissy_heuristic=(
                self.config.native_korf_upper_bound_proof_nissy_heuristic
            ),
        )
        self._certifying_portfolio = PortfolioOptimalOracle(portfolio_config)
        portfolio_prepass_timeout = (
            self.config.resident_race.timeout_seconds
            if self.config.portfolio_prepass_timeout_seconds is None
            else self.config.portfolio_prepass_timeout_seconds
        )
        portfolio_fallback_timeout = (
            portfolio_prepass_timeout
            if self.config.portfolio_fallback_timeout_seconds is None
            else self.config.portfolio_fallback_timeout_seconds
        )
        batch_portfolio_config = PortfolioOptimalOracleConfig(
            h48=self.config.resident_race.h48,
            nissy_timeout_seconds=portfolio_prepass_timeout,
            nissy_threads=self.config.resident_race.nissy_threads,
            nissy_binary_path=self.config.resident_race.nissy_binary_path,
            nissy_data_dir=self.config.resident_race.nissy_data_dir,
            try_nissy_first=self.config.resident_race.include_nissy,
            try_nissy_core_direct_first=not self.config.try_portfolio_batch_before_resident_h48_batch,
            try_certificate_cache=False,
            try_upper_lower_certificate=False,
            try_h48_fallback=False,
        )
        self._batch_portfolio = PortfolioOptimalOracle(batch_portfolio_config)
        fallback_portfolio_config = replace(
            batch_portfolio_config,
            nissy_timeout_seconds=portfolio_fallback_timeout,
            try_nissy_core_direct_first=(
                self.config.portfolio_fallback_nissy_core_direct_timeout_seconds is not None
                and self.config.portfolio_fallback_nissy_core_direct_timeout_seconds >= 0.0
            ),
            nissy_core_direct_timeout_seconds=max(
                0.0,
                self.config.portfolio_fallback_nissy_core_direct_timeout_seconds or 0.0,
            ),
        )
        self._fallback_portfolio = PortfolioOptimalOracle(fallback_portfolio_config)
        self._resident_race = ResidentRaceOptimalOracle(self._resident_race_config())
        self._rubikoptimal_session: RubikOptimalOracleSession | None = None
        self._closed = False

    def _resident_race_config(
        self,
        *,
        timeout_seconds: float | None = None,
    ) -> ResidentRaceOptimalOracleConfig:
        resident_race_config = self.config.resident_race
        if timeout_seconds is not None:
            resident_race_config = replace(
                resident_race_config,
                timeout_seconds=max(0.0, float(timeout_seconds)),
            )
        if self.config.nissy_symmetry_variants > resident_race_config.nissy_symmetry_variants:
            resident_race_config = replace(
                resident_race_config,
                nissy_symmetry_variants=self.config.nissy_symmetry_variants,
            )
        if (
            self.config.rubikoptimal_race_timeout_seconds is not None
            and self.config.rubikoptimal_race_timeout_seconds >= 0.0
        ):
            resident_race_config = replace(
                resident_race_config,
                include_rubikoptimal=True,
                rubikoptimal_race_timeout_seconds=self.config.rubikoptimal_race_timeout_seconds,
                rubikoptimal_executable=self.config.rubikoptimal_executable,
                rubikoptimal_package_path=self.config.rubikoptimal_package_path,
                rubikoptimal_table_dir=self.config.rubikoptimal_table_dir,
            )
        if self.config.symmetry_order_by_h48_lower_bound:
            resident_race_config = replace(
                resident_race_config,
                symmetry_order_by_h48_lower_bound=True,
                symmetry_lower_bound_order_timeout_seconds=(
                    self.config.symmetry_lower_bound_order_timeout_seconds
                ),
            )
        return resident_race_config

    def __enter__(self) -> "UniversalOptimalOracle":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def close(self) -> None:
        self._closed = True
        self._certifying_portfolio.close()
        self._batch_portfolio.close()
        self._fallback_portfolio.close()
        self._resident_race.close()
        if self._rubikoptimal_session is not None:
            self._rubikoptimal_session.close()
            self._rubikoptimal_session = None

    def solve(
        self,
        cube: CubeState,
        *,
        source_sequence: list[str] | tuple[str, ...] | str | None = None,
    ) -> SolverResult:
        if self._closed:
            raise RuntimeError("universal optimal oracle is closed")

        begin = time.perf_counter()
        ok, message = validate_cube(cube)
        if not ok:
            return SolverResult(
                solver_name=self.solver_name,
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
                notes=f"invalid physical cube state rejected before universal oracle: {message}",
            )
        if cube.is_solved():
            return SolverResult(
                solver_name=self.solver_name,
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
                notes=(
                    "universal exact oracle; selected_backend=solved_fast_path; "
                    "exactness_policy=verified_exact_only; arbitrary_valid_3x3_domain=true; "
                    "fast_runtime_proven_for_every_possible_state=false; no backend process started"
                ),
            )

        certificate_result = self._certifying_portfolio._solve_from_certificate_cache(cube)
        if certificate_result is not None:
            return self._wrap_result(
                certificate_result,
                selected_backend="exact-certificate-cache",
                total_runtime_seconds=time.perf_counter() - begin,
            )

        upper_lower_result = self._certifying_portfolio._try_upper_lower_certificate(
            cube,
            source_sequence=source_sequence,
        )
        if upper_lower_result is not None:
            return self._wrap_result(
                upper_lower_result,
                selected_backend="upper-lower-certificate",
                total_runtime_seconds=time.perf_counter() - begin,
            )

        rubikoptimal_prepass_result = self._try_rubikoptimal_prepass(cube)
        if rubikoptimal_prepass_result is not None and _is_verified_exact(rubikoptimal_prepass_result):
            return self._wrap_result(
                rubikoptimal_prepass_result,
                selected_backend="rubikoptimal-prepass",
                total_runtime_seconds=time.perf_counter() - begin,
            )

        resident_race_prepass_result = self._try_resident_race_prepass(
            cube,
            source_sequence=source_sequence,
        )
        if resident_race_prepass_result is not None and _is_verified_exact(resident_race_prepass_result):
            return self._wrap_result(
                resident_race_prepass_result,
                selected_backend="resident-race-prepass",
                total_runtime_seconds=time.perf_counter() - begin,
            )

        rubikoptimal_symmetry_result = self._try_rubikoptimal_symmetry_batch(cube)
        if rubikoptimal_symmetry_result is not None and _is_verified_exact(rubikoptimal_symmetry_result):
            rubikoptimal_symmetry_backend = (
                "rubikoptimal-symmetry-race"
                if (
                    rubikoptimal_symmetry_result.solver_name == "rubikoptimal_rotational_race"
                    or "selected_backend=rubikoptimal_rotational_race"
                    in rubikoptimal_symmetry_result.notes
                )
                else "rubikoptimal-symmetry-batch"
            )
            return self._wrap_result(
                rubikoptimal_symmetry_result,
                selected_backend=rubikoptimal_symmetry_backend,
                total_runtime_seconds=time.perf_counter() - begin,
            )

        nissy_core_symmetry_result = self._try_nissy_core_direct_rotational_race(cube)
        if nissy_core_symmetry_result is not None and _is_verified_exact(nissy_core_symmetry_result):
            return self._wrap_result(
                nissy_core_symmetry_result,
                selected_backend="nissy-core-direct-symmetry-race",
                total_runtime_seconds=time.perf_counter() - begin,
            )

        nissy_symmetry_result = self._try_nissy_symmetry_batch(cube, source_sequence=source_sequence)
        if nissy_symmetry_result is not None and _is_verified_exact(nissy_symmetry_result):
            return self._wrap_result(
                nissy_symmetry_result,
                selected_backend="nissy-symmetry-batch",
                total_runtime_seconds=time.perf_counter() - begin,
            )

        h48_symmetry_result = self._try_resident_h48_symmetry_batch(cube)
        if h48_symmetry_result is not None:
            return self._wrap_result(
                h48_symmetry_result,
                selected_backend="resident-h48-symmetry-batch",
                total_runtime_seconds=time.perf_counter() - begin,
            )

        parallel_h48_result = self._try_parallel_h48_symmetry_race(cube)
        if parallel_h48_result is not None:
            return self._wrap_result(
                parallel_h48_result,
                selected_backend="parallel-h48-symmetry-race",
                total_runtime_seconds=time.perf_counter() - begin,
            )

        race_result = self._resident_race.solve(cube, source_sequence=source_sequence)
        selected_backend = "resident-race"
        if "selected_backend=nissy-symmetry-batch" in race_result.notes:
            selected_backend = "nissy-symmetry-batch"
        elif "selected_backend=nissy-core-direct-resident" in race_result.notes:
            selected_backend = "nissy-core-direct-resident"
        elif "selected_backend=rubikoptimal-race" in race_result.notes:
            selected_backend = "rubikoptimal-race"
        wrapped_race_result = self._wrap_result(
            race_result,
            selected_backend=selected_backend,
            total_runtime_seconds=time.perf_counter() - begin,
        )
        return self._maybe_apply_rubikoptimal_fallback(
            cube,
            wrapped_race_result,
            started_at=begin,
            selected_backend="rubikoptimal-after-resident-race",
        )

    def solve_many(
        self,
        cubes: Iterable[CubeState],
        *,
        source_sequences: Iterable[list[str] | tuple[str, ...] | str | None] | None = None,
    ) -> list[SolverResult]:
        cube_list = list(cubes)
        if source_sequences is None:
            source_list: list[list[str] | tuple[str, ...] | str | None] = [None] * len(cube_list)
        else:
            source_list = list(source_sequences)
            if len(source_list) != len(cube_list):
                raise ValueError("source_sequences length must match cubes length")
        results: list[SolverResult | None] = [None] * len(cube_list)
        pending: list[tuple[int, CubeState, list[str] | tuple[str, ...] | str | None]] = []
        pre_pending_prepass_results: dict[int, list[tuple[str, SolverResult]]] = {}

        def record_pre_pending_prepass(index: int, name: str, result: SolverResult | None) -> None:
            if result is None:
                return
            pre_pending_prepass_results.setdefault(index, []).append((name, result))

        def pre_pending_wall_seconds(index: int) -> float:
            return sum(
                max(0.0, float(result.runtime_seconds))
                for _, result in pre_pending_prepass_results.get(index, [])
            )

        def pre_pending_notes(index: int) -> str:
            entries = pre_pending_prepass_results.get(index, [])
            if not entries:
                return ""
            parts = []
            for name, result in entries:
                parts.append(
                    f"{name}_prepass_initial_solver={result.solver_name}; "
                    f"{name}_prepass_initial_status={result.status}; "
                    f"{name}_prepass_initial_verified={result.is_verified}; "
                    f"{name}_prepass_initial_runtime_seconds={result.runtime_seconds:.6f}; "
                    f"{name}_prepass_initial_notes={result.notes}"
                )
            return "; " + "; ".join(parts)

        def annotate_with_pre_pending_prepasses(index: int, result: SolverResult) -> SolverResult:
            notes = pre_pending_notes(index)
            if not notes:
                return result
            return replace(result, notes=f"{result.notes}{notes}")

        defer_h48_symmetry_until_after_portfolio_prepass = (
            self.config.resident_h48_symmetry_variants > 0
            and self.config.prefer_resident_h48_batch_for_state_input
            and self.config.try_portfolio_batch_before_resident_h48_batch
            and self.config.resident_race.include_h48
            and self.config.resident_race.include_nissy
            and all(source is None for source in source_list)
        )

        for index, (cube, source) in enumerate(zip(cube_list, source_list, strict=True)):
            ok, _ = validate_cube(cube)
            if not ok or cube.is_solved():
                results[index] = self.solve(cube, source_sequence=source)
                continue

            begin = time.perf_counter()
            certificate_result = self._certifying_portfolio._solve_from_certificate_cache(cube)
            if certificate_result is not None:
                results[index] = self._wrap_result(
                    certificate_result,
                    selected_backend="exact-certificate-cache",
                    total_runtime_seconds=time.perf_counter() - begin,
                )
                continue

            resident_race_prepass_result = self._try_resident_race_prepass(cube, source_sequence=source)
            if resident_race_prepass_result is not None:
                if _is_verified_exact(resident_race_prepass_result):
                    results[index] = self._wrap_result(
                        resident_race_prepass_result,
                        selected_backend="resident-race-prepass",
                        total_runtime_seconds=time.perf_counter() - begin,
                    )
                    continue
                record_pre_pending_prepass(index, "resident_race", resident_race_prepass_result)

            nissy_core_symmetry_result = self._try_nissy_core_direct_rotational_race(cube)
            if nissy_core_symmetry_result is not None:
                if _is_verified_exact(nissy_core_symmetry_result):
                    results[index] = self._wrap_result(
                        nissy_core_symmetry_result,
                        selected_backend="nissy-core-direct-symmetry-race",
                        total_runtime_seconds=time.perf_counter() - begin,
                    )
                    continue
                record_pre_pending_prepass(index, "nissy_core_direct_symmetry", nissy_core_symmetry_result)

            nissy_symmetry_result = self._try_nissy_symmetry_batch(cube, source_sequence=source)
            if nissy_symmetry_result is not None:
                if _is_verified_exact(nissy_symmetry_result):
                    results[index] = self._wrap_result(
                        nissy_symmetry_result,
                        selected_backend="nissy-symmetry-batch",
                        total_runtime_seconds=time.perf_counter() - begin,
                    )
                    continue
                record_pre_pending_prepass(index, "nissy_symmetry", nissy_symmetry_result)

            if not defer_h48_symmetry_until_after_portfolio_prepass:
                h48_symmetry_result = self._run_resident_h48_symmetry_batch(cube)
                if h48_symmetry_result is not None:
                    if _is_verified_exact(h48_symmetry_result):
                        results[index] = self._wrap_result(
                            h48_symmetry_result,
                            selected_backend="resident-h48-symmetry-batch",
                            total_runtime_seconds=time.perf_counter() - begin,
                        )
                        continue
                    record_pre_pending_prepass(index, "resident_h48_symmetry", h48_symmetry_result)
                parallel_h48_result = self._run_parallel_h48_symmetry_race(cube)
                if parallel_h48_result is not None:
                    if _is_verified_exact(parallel_h48_result):
                        results[index] = self._wrap_result(
                            parallel_h48_result,
                            selected_backend="parallel-h48-symmetry-race",
                            total_runtime_seconds=time.perf_counter() - begin,
                        )
                        continue
                    record_pre_pending_prepass(index, "parallel_h48_symmetry", parallel_h48_result)

            pending.append((index, cube, source))

        if pending and self.config.try_upper_lower_certificate:
            upper_lower_begin = time.perf_counter()
            upper_lower_results = self._certifying_portfolio._try_upper_lower_certificates_batch(pending)
            upper_lower_wall_seconds = time.perf_counter() - upper_lower_begin
            if upper_lower_results:
                unresolved_after_upper_lower: list[
                    tuple[int, CubeState, list[str] | tuple[str, ...] | str | None]
                ] = []
                for index, cube, source in pending:
                    upper_lower_result = upper_lower_results.get(index)
                    if upper_lower_result is None:
                        unresolved_after_upper_lower.append((index, cube, source))
                        continue
                    results[index] = self._wrap_result(
                        replace(
                            upper_lower_result,
                            notes=(
                                f"{upper_lower_result.notes}; "
                                "universal_solve_many_upper_lower_batch=true; "
                                f"universal_upper_lower_batch_wall_seconds={upper_lower_wall_seconds:.6f}"
                                f"{pre_pending_notes(index)}"
                            ),
                        ),
                        selected_backend="upper-lower-certificate",
                        total_runtime_seconds=(
                            pre_pending_wall_seconds(index) + upper_lower_wall_seconds
                        ),
                    )
                pending = unresolved_after_upper_lower
                if not pending:
                    return [result for result in results if result is not None]

        if pending and self._rubikoptimal_prepass_enabled():
            rubikoptimal_results, rubikoptimal_wall_seconds = (
                self._solve_rubikoptimal_resident_batch(
                    [cube for _, cube, _ in pending],
                    total_timeout_seconds=self._rubikoptimal_prepass_timeout(len(pending)),
                    note_flag="universal_prepass_uses_shared_rubikoptimal_session",
                    budget_note_prefix="prepass",
                    exhausted_message=(
                        "RubikOptimal shared resident prepass row skipped because the global "
                        "prepass budget was exhausted"
                    ),
                )
            )
            unresolved_after_rubikoptimal: list[
                tuple[int, CubeState, list[str] | tuple[str, ...] | str | None]
            ] = []
            for (index, cube, source), rubikoptimal_result in zip(
                pending,
                rubikoptimal_results,
                strict=False,
            ):
                if _is_verified_exact(rubikoptimal_result):
                    annotated = replace(
                        rubikoptimal_result,
                        notes=(
                            f"{rubikoptimal_result.notes}; "
                            "universal_rubikoptimal_prepass=true; "
                            f"rubikoptimal_prepass_batch_wall_seconds={rubikoptimal_wall_seconds:.6f}"
                            f"{pre_pending_notes(index)}"
                        ),
                    )
                    results[index] = self._wrap_result(
                        annotated,
                        selected_backend="rubikoptimal-prepass",
                        total_runtime_seconds=pre_pending_wall_seconds(index) + rubikoptimal_wall_seconds,
                    )
                else:
                    record_pre_pending_prepass(index, "rubikoptimal", rubikoptimal_result)
                    unresolved_after_rubikoptimal.append((index, cube, source))
            pending = unresolved_after_rubikoptimal
            if not pending:
                return [result for result in results if result is not None]

        if pending and self._rubikoptimal_symmetry_enabled():
            rubikoptimal_symmetry_max_concurrency = max(
                0, int(self.config.rubikoptimal_symmetry_max_concurrency)
            )
            if rubikoptimal_symmetry_max_concurrency > 0:
                unresolved_after_rubikoptimal_symmetry_race: list[
                    tuple[int, CubeState, list[str] | tuple[str, ...] | str | None]
                ] = []
                for index, cube, source in pending:
                    include_identity = self._rubikoptimal_symmetry_include_identity()
                    rotations, rotation_order_note = self._order_symmetry_rotations_by_h48_lower_bound(
                        cube,
                        self._rubikoptimal_symmetry_rotations(include_identity=include_identity),
                        context="rubikoptimal_symmetry_race",
                    )
                    race_begin = time.perf_counter()
                    race_result = solve_rubikoptimal_external_rotational_race(
                        cube,
                        variant_count=len(rotations),
                        include_identity=include_identity,
                        rotations=rotations,
                        rotation_order_note=rotation_order_note,
                        timeout_seconds=self._rubikoptimal_symmetry_global_timeout(),
                        max_concurrency=rubikoptimal_symmetry_max_concurrency,
                        executable=self.config.rubikoptimal_executable,
                        package_path=self.config.rubikoptimal_package_path,
                        table_dir=self.config.rubikoptimal_table_dir,
                        root=self.config.resident_race.h48.root,
                    )
                    race_wall_seconds = time.perf_counter() - race_begin
                    if _is_verified_exact(race_result):
                        results[index] = self._wrap_result(
                            replace(
                                race_result,
                                notes=(
                                    f"{race_result.notes}; "
                                    "universal_rubikoptimal_symmetry_race=true; "
                                    f"rubikoptimal_symmetry_race_wall_seconds={race_wall_seconds:.6f}"
                                    f"{pre_pending_notes(index)}"
                                ),
                            ),
                            selected_backend="rubikoptimal-symmetry-race",
                            total_runtime_seconds=(
                                pre_pending_wall_seconds(index) + race_wall_seconds
                            ),
                        )
                    else:
                        record_pre_pending_prepass(index, "rubikoptimal_symmetry_race", race_result)
                        unresolved_after_rubikoptimal_symmetry_race.append((index, cube, source))
                pending = unresolved_after_rubikoptimal_symmetry_race
                if not pending:
                    return [result for result in results if result is not None]
                # The explicit race mode has already spent the configured symmetry budget.
                # Remaining rows continue to later backends instead of repeating the same
                # rotations through the sequential batch helper.
                rubikoptimal_symmetry_begin = None
            else:
                rubikoptimal_symmetry_begin = time.perf_counter()
            if rubikoptimal_symmetry_max_concurrency > 0:
                pass
            else:
                include_identity = self._rubikoptimal_symmetry_include_identity()
                rotations = self._rubikoptimal_symmetry_rotations(include_identity=include_identity)
                rotated_items: list[tuple[int, CubeState, CubeRotation, CubeState]] = []
                rotation_order_notes_by_index: dict[int, str] = {}
                for index, cube, _source in pending:
                    ordered_rotations, rotation_order_note = self._order_symmetry_rotations_by_h48_lower_bound(
                        cube,
                        rotations,
                        context="rubikoptimal_symmetry",
                    )
                    rotation_order_notes_by_index[index] = rotation_order_note
                    for rotation in ordered_rotations:
                        rotated_items.append((index, cube, rotation, rotation.transform_cube(cube)))
                if rotated_items:
                    rotated_results, rubikoptimal_symmetry_wall_seconds = (
                        self._solve_rubikoptimal_resident_batch(
                            [rotated_cube for _, _, _, rotated_cube in rotated_items],
                            total_timeout_seconds=self._rubikoptimal_symmetry_timeout(
                                len(rotated_items)
                            ),
                            note_flag="universal_symmetry_batch_uses_shared_rubikoptimal_session",
                            budget_note_prefix="symmetry",
                            exhausted_message=(
                                "RubikOptimal shared resident symmetry row skipped because the global "
                                "symmetry budget was exhausted"
                            ),
                        )
                    )
                    solved_indices: set[int] = set()
                    first_non_exact_by_index: dict[int, SolverResult] = {}
                    for (index, cube, rotation, _rotated_cube), rotated_result in zip(
                        rotated_items,
                        rotated_results,
                        strict=False,
                    ):
                        if index in solved_indices:
                            continue
                        if _is_verified_exact(rotated_result):
                            mapped = self._rubikoptimal_symmetry_exact_result(
                                cube,
                                rotation=rotation,
                                rotated_result=rotated_result,
                                runtime_seconds=rubikoptimal_symmetry_wall_seconds,
                                rotated_item_count=len(rotated_items),
                                rotation_count=len(rotations),
                                include_identity=include_identity,
                                rotation_order_note=rotation_order_notes_by_index.get(
                                    index,
                                    "rubikoptimal_symmetry_h48_lower_bound_rotation_order=false",
                                ),
                            )
                            if mapped is None:
                                first_non_exact_by_index.setdefault(
                                    index,
                                    self._rubikoptimal_symmetry_failed_verification_result(
                                        cube,
                                        rotation=rotation,
                                        rotated_result=rotated_result,
                                        runtime_seconds=rubikoptimal_symmetry_wall_seconds,
                                    ),
                                )
                                continue
                            results[index] = self._wrap_result(
                                replace(
                                    mapped,
                                    notes=(
                                        f"{mapped.notes}; universal_rubikoptimal_symmetry_prepass=true; "
                                        f"rubikoptimal_symmetry_batch_wall_seconds="
                                        f"{rubikoptimal_symmetry_wall_seconds:.6f}"
                                        f"{pre_pending_notes(index)}"
                                    ),
                                ),
                                selected_backend="rubikoptimal-symmetry-batch",
                                total_runtime_seconds=(
                                    pre_pending_wall_seconds(index) + rubikoptimal_symmetry_wall_seconds
                                ),
                            )
                            solved_indices.add(index)
                        else:
                            first_non_exact_by_index.setdefault(index, rotated_result)

                    unresolved_after_rubikoptimal_symmetry: list[
                        tuple[int, CubeState, list[str] | tuple[str, ...] | str | None]
                    ] = []
                    for index, cube, source in pending:
                        if index in solved_indices:
                            continue
                        first_non_exact = first_non_exact_by_index.get(index)
                        if first_non_exact is not None:
                            record_pre_pending_prepass(
                                index,
                                "rubikoptimal_symmetry",
                                self._rubikoptimal_symmetry_non_exact_result(
                                    cube,
                                    first_non_exact=first_non_exact,
                                    rotation_count=len(rotations),
                                    rotated_item_count=len(rotated_items),
                                    include_identity=include_identity,
                                    runtime_seconds=rubikoptimal_symmetry_wall_seconds,
                                    rotation_order_note=rotation_order_notes_by_index.get(
                                        index,
                                        "rubikoptimal_symmetry_h48_lower_bound_rotation_order=false",
                                    ),
                                ),
                            )
                        unresolved_after_rubikoptimal_symmetry.append((index, cube, source))
                    pending = unresolved_after_rubikoptimal_symmetry
                    if not pending:
                        return [result for result in results if result is not None]

        if (
            pending
            and self.config.prefer_resident_h48_batch_for_state_input
            and self.config.resident_race.include_h48
            and all(source is None for _, _, source in pending)
        ):
            resident_batch_pending = pending
            portfolio_prepass_results: dict[int, SolverResult] = {}
            portfolio_prepass_wall_seconds = 0.0
            if self.config.try_portfolio_batch_before_resident_h48_batch and self.config.resident_race.include_nissy:
                prepass_begin = time.perf_counter()
                prepass_results = self._batch_portfolio.solve_many(
                    [cube for _, cube, _ in pending],
                    source_sequences=[None] * len(pending),
                )
                portfolio_prepass_wall_seconds = time.perf_counter() - prepass_begin
                unresolved: list[tuple[int, CubeState, list[str] | tuple[str, ...] | str | None]] = []
                for (index, cube, source), prepass_result in zip(pending, prepass_results, strict=True):
                    portfolio_prepass_results[index] = prepass_result
                    if _is_verified_exact(prepass_result):
                        annotated = replace(
                            prepass_result,
                            notes=(
                                f"{prepass_result.notes}; "
                                "portfolio_prepass_before_resident_h48_batch=true"
                                f"{pre_pending_notes(index)}"
                            ),
                        )
                        results[index] = self._wrap_result(
                            annotated,
                            selected_backend="portfolio-before-resident-h48-batch",
                            total_runtime_seconds=(
                                pre_pending_wall_seconds(index) + portfolio_prepass_wall_seconds
                            ),
                        )
                    else:
                        unresolved.append((index, cube, source))
                resident_batch_pending = unresolved

            if not resident_batch_pending:
                return [result for result in results if result is not None]

            h48_symmetry_prepass_results: dict[int, SolverResult] = {}
            h48_symmetry_prepass_wall_seconds = 0.0
            if defer_h48_symmetry_until_after_portfolio_prepass:
                h48_symmetry_begin = time.perf_counter()
                unresolved_after_h48_symmetry: list[
                    tuple[int, CubeState, list[str] | tuple[str, ...] | str | None]
                ] = []
                for index, cube, source in resident_batch_pending:
                    h48_symmetry_result = self._run_resident_h48_symmetry_batch(cube)
                    if h48_symmetry_result is None:
                        unresolved_after_h48_symmetry.append((index, cube, source))
                        continue
                    h48_symmetry_prepass_results[index] = h48_symmetry_result
                    prepass_result = portfolio_prepass_results.get(index)
                    if _is_verified_exact(h48_symmetry_result):
                        annotated_h48_symmetry_result = h48_symmetry_result
                        total_runtime = h48_symmetry_result.runtime_seconds
                        selected_backend = "resident-h48-symmetry-batch"
                        if prepass_result is not None:
                            selected_backend = "resident-h48-symmetry-batch-after-portfolio-prepass"
                            total_runtime += portfolio_prepass_wall_seconds
                            annotated_h48_symmetry_result = replace(
                                h48_symmetry_result,
                                notes=(
                                    f"{h48_symmetry_result.notes}; "
                                    "portfolio_prepass_before_resident_h48_batch=true; "
                                    f"portfolio_prepass_initial_solver={prepass_result.solver_name}; "
                                    f"portfolio_prepass_initial_status={prepass_result.status}; "
                                    f"portfolio_prepass_initial_verified={prepass_result.is_verified}; "
                                    f"portfolio_prepass_initial_runtime_seconds={prepass_result.runtime_seconds:.6f}; "
                                    f"portfolio_prepass_initial_notes={prepass_result.notes}"
                                ),
                            )
                        results[index] = self._wrap_result(
                            annotated_h48_symmetry_result,
                            selected_backend=selected_backend,
                            total_runtime_seconds=total_runtime,
                        )
                    else:
                        unresolved_after_h48_symmetry.append((index, cube, source))
                h48_symmetry_prepass_wall_seconds = time.perf_counter() - h48_symmetry_begin
                resident_batch_pending = unresolved_after_h48_symmetry

            if not resident_batch_pending:
                return [result for result in results if result is not None]

            batch_begin = time.perf_counter()
            h48_batch_oracle = self._resident_race._h48
            close_h48_batch_oracle = False
            if (
                self.config.resident_h48_batch_timeout_seconds is not None
                and self.config.resident_h48_batch_timeout_seconds
                != self.config.resident_race.h48.timeout_seconds
            ):
                h48_batch_oracle = FastOptimalOracle(
                    replace(
                        self.config.resident_race.h48,
                        timeout_seconds=self.config.resident_h48_batch_timeout_seconds,
                    )
                )
                close_h48_batch_oracle = True
            try:
                h48_results = h48_batch_oracle.solve_many([cube for _, cube, _ in resident_batch_pending])
            finally:
                if close_h48_batch_oracle:
                    h48_batch_oracle.close()
            batch_wall_seconds = time.perf_counter() - batch_begin
            fallback_pending: list[tuple[int, CubeState, SolverResult]] = []
            for (index, cube, _), h48_result in zip(resident_batch_pending, h48_results, strict=True):
                prepass_result = portfolio_prepass_results.get(index)
                if _is_verified_exact(h48_result):
                    selected_backend = "resident-h48-batch"
                    annotated_h48_result = annotate_with_pre_pending_prepasses(index, h48_result)
                    total_runtime = pre_pending_wall_seconds(index) + batch_wall_seconds
                    if prepass_result is not None:
                        selected_backend = "resident-h48-batch-after-portfolio-prepass"
                        total_runtime += portfolio_prepass_wall_seconds + h48_symmetry_prepass_wall_seconds
                        h48_symmetry_result = h48_symmetry_prepass_results.get(index)
                        h48_symmetry_note = ""
                        if h48_symmetry_result is not None:
                            h48_symmetry_note = (
                                f"; h48_symmetry_prepass_initial_solver={h48_symmetry_result.solver_name}; "
                                f"h48_symmetry_prepass_initial_status={h48_symmetry_result.status}; "
                                f"h48_symmetry_prepass_initial_verified={h48_symmetry_result.is_verified}; "
                                f"h48_symmetry_prepass_initial_runtime_seconds={h48_symmetry_result.runtime_seconds:.6f}; "
                                f"h48_symmetry_prepass_initial_notes={h48_symmetry_result.notes}"
                            )
                        annotated_h48_result = replace(
                            h48_result,
                            notes=(
                                f"{h48_result.notes}; portfolio_prepass_before_resident_h48_batch=true; "
                                f"portfolio_prepass_initial_solver={prepass_result.solver_name}; "
                                f"portfolio_prepass_initial_status={prepass_result.status}; "
                                f"portfolio_prepass_initial_verified={prepass_result.is_verified}; "
                                f"portfolio_prepass_initial_runtime_seconds={prepass_result.runtime_seconds:.6f}; "
                                f"portfolio_prepass_initial_notes={prepass_result.notes}"
                                f"{h48_symmetry_note}"
                                f"{pre_pending_notes(index)}"
                            ),
                        )
                    results[index] = self._wrap_result(
                        annotated_h48_result,
                        selected_backend=selected_backend,
                        total_runtime_seconds=total_runtime,
                    )
                else:
                    fallback_pending.append((index, cube, h48_result))
            if fallback_pending:
                fallback_begin = time.perf_counter()
                fallback_results = self._fallback_portfolio.solve_many(
                    [cube for _, cube, _ in fallback_pending],
                    source_sequences=[None] * len(fallback_pending),
                )
                fallback_wall_seconds = time.perf_counter() - fallback_begin
                for (index, _, h48_result), fallback_result in zip(
                    fallback_pending,
                    fallback_results,
                    strict=True,
                ):
                    prepass_result = portfolio_prepass_results.get(index)
                    fallback_notes = (
                        f"{fallback_result.notes}; resident_h48_batch_fallback=true; "
                        f"resident_h48_batch_initial_solver={h48_result.solver_name}; "
                        f"resident_h48_batch_initial_status={h48_result.status}; "
                        f"resident_h48_batch_initial_verified={h48_result.is_verified}; "
                        f"resident_h48_batch_initial_runtime_seconds={h48_result.runtime_seconds:.6f}; "
                        f"resident_h48_batch_initial_notes={h48_result.notes}"
                        f"{pre_pending_notes(index)}"
                    )
                    selected_backend = "portfolio-after-resident-h48-fallback"
                    total_runtime_seconds = (
                        pre_pending_wall_seconds(index) + batch_wall_seconds + fallback_wall_seconds
                    )
                    if prepass_result is not None:
                        selected_backend = "portfolio-after-resident-h48-fallback-after-prepass"
                        total_runtime_seconds += portfolio_prepass_wall_seconds + h48_symmetry_prepass_wall_seconds
                        h48_symmetry_result = h48_symmetry_prepass_results.get(index)
                        h48_symmetry_note = ""
                        if h48_symmetry_result is not None:
                            h48_symmetry_note = (
                                f"; h48_symmetry_prepass_initial_solver={h48_symmetry_result.solver_name}; "
                                f"h48_symmetry_prepass_initial_status={h48_symmetry_result.status}; "
                                f"h48_symmetry_prepass_initial_verified={h48_symmetry_result.is_verified}; "
                                f"h48_symmetry_prepass_initial_runtime_seconds={h48_symmetry_result.runtime_seconds:.6f}; "
                                f"h48_symmetry_prepass_initial_notes={h48_symmetry_result.notes}"
                            )
                        fallback_notes = (
                            f"{fallback_notes}; portfolio_prepass_before_resident_h48_batch=true; "
                            f"portfolio_prepass_initial_solver={prepass_result.solver_name}; "
                            f"portfolio_prepass_initial_status={prepass_result.status}; "
                            f"portfolio_prepass_initial_verified={prepass_result.is_verified}; "
                            f"portfolio_prepass_initial_runtime_seconds={prepass_result.runtime_seconds:.6f}; "
                            f"portfolio_prepass_initial_notes={prepass_result.notes}"
                            f"{h48_symmetry_note}"
                            f"{pre_pending_notes(index)}"
                        )
                    annotated = replace(
                        fallback_result,
                        notes=fallback_notes,
                    )
                    results[index] = self._wrap_result(
                        annotated,
                        selected_backend=selected_backend,
                        total_runtime_seconds=total_runtime_seconds,
                    )
        elif pending and self.config.resident_race.include_h48 and self.config.resident_race.include_nissy:
            batch_begin = time.perf_counter()
            batch_results = self._batch_portfolio.solve_many(
                [cube for _, cube, _ in pending],
                source_sequences=[source for _, _, source in pending],
            )
            batch_wall_seconds = time.perf_counter() - batch_begin
            for (index, _, _), batch_result in zip(pending, batch_results, strict=True):
                annotated_batch_result = annotate_with_pre_pending_prepasses(index, batch_result)
                results[index] = self._wrap_result(
                    annotated_batch_result,
                    selected_backend="portfolio-batch",
                    total_runtime_seconds=pre_pending_wall_seconds(index) + batch_wall_seconds,
                )
        elif pending and self._rubikoptimal_fallback_enabled():
            for index, cube, _source in pending:
                results[index] = SolverResult(
                    solver_name=self.solver_name,
                    input_state=cube.to_facelets(),
                    solution_moves=[],
                    solution_length=None,
                    metric="HTM",
                    runtime_seconds=pre_pending_wall_seconds(index),
                    expanded_nodes=None,
                    generated_nodes=None,
                    table_bytes=0,
                    status="not_applicable",
                    is_verified=False,
                    notes=(
                        "universal exact oracle deferred to RubikOptimal fallback; "
                        "selected_backend=live-backends-disabled; "
                        "resident_h48_invoked=false; nissy_optimal_invoked=false"
                        f"{pre_pending_notes(index)}"
                    ),
                )
        else:
            for index, cube, source in pending:
                results[index] = self.solve(cube, source_sequence=source)

        return self._apply_rubikoptimal_fallback_many(cube_list, results)

    def distance(
        self,
        cube: CubeState,
        *,
        source_sequence: list[str] | tuple[str, ...] | str | None = None,
    ) -> int | None:
        result = self.solve(cube, source_sequence=source_sequence)
        if result.status == "exact" and result.is_verified:
            return result.solution_length
        return None

    def _try_nissy_symmetry_batch(
        self,
        cube: CubeState,
        *,
        source_sequence: list[str] | tuple[str, ...] | str | None = None,
    ) -> SolverResult | None:
        variant_count = max(0, int(self.config.nissy_symmetry_variants))
        if variant_count <= 0 or not self.config.resident_race.include_nissy:
            return None
        rotations = [rotation for rotation in CUBE_ROTATIONS if not rotation.is_identity][:variant_count]
        if not rotations:
            return None
        rotations, rotation_order_note = self._order_symmetry_rotations_by_h48_lower_bound(
            cube,
            rotations,
            context="nissy_symmetry",
        )

        begin = time.perf_counter()
        rotated_cubes = [rotation.transform_cube(cube) for rotation in rotations]
        rotated_sources: list[list[str] | tuple[str, ...] | str | None] = [
            rotation.transform_sequence(source_sequence) if source_sequence is not None else None
            for rotation in rotations
        ]
        try:
            rotated_results = solve_nissy_optimal_batch(
                rotated_cubes,
                source_sequences=rotated_sources,
                timeout_seconds=(
                    self.config.resident_race.timeout_seconds
                    if self.config.nissy_symmetry_timeout_seconds is None
                    else self.config.nissy_symmetry_timeout_seconds
                ),
                threads=self.config.resident_race.nissy_threads,
                binary_path=self.config.resident_race.nissy_binary_path,
                data_dir=self.config.resident_race.nissy_data_dir,
                root=self._certifying_portfolio._h48.root,
            )
        except Exception:
            return None

        first_non_exact: SolverResult | None = None
        for rotation, rotated_result in zip(rotations, rotated_results, strict=True):
            if rotated_result.status != "exact" or not rotated_result.is_verified:
                if first_non_exact is None:
                    first_non_exact = rotated_result
                continue
            solution = rotation.inverse_transform_sequence(rotated_result.solution_moves)
            verification = verify_solution(cube, solution)
            if not verification.ok:
                continue
            return SolverResult(
                solver_name="nissy_symmetry_batch_oracle",
                input_state=cube.to_facelets(),
                solution_moves=solution,
                solution_length=len(solution),
                metric=rotated_result.metric,
                runtime_seconds=time.perf_counter() - begin,
                expanded_nodes=rotated_result.expanded_nodes,
                generated_nodes=rotated_result.generated_nodes,
                table_bytes=rotated_result.table_bytes,
                status="exact",
                is_verified=True,
                notes=(
                    "universal nissy symmetry batch; exactness_policy=rotated_exact_solution_mapped_back_and_verified; "
                    "identity_rotation_excluded=true; "
                    f"symmetry_variants={len(rotations)}; selected_rotation={rotation.name}; "
                    f"rotated_backend_solver={rotated_result.solver_name}; "
                    f"rotated_runtime_seconds={rotated_result.runtime_seconds:.6f}; "
                    f"rotated_solution_length={rotated_result.solution_length}; "
                    f"source_sequence_provided={source_sequence is not None}; "
                    f"{rotation_order_note}; "
                    f"rotated_notes={rotated_result.notes}"
                ),
            )
        if first_non_exact is None:
            return None
        return SolverResult(
            solver_name="nissy_symmetry_batch_oracle",
            input_state=cube.to_facelets(),
            solution_moves=[],
            solution_length=None,
            metric="HTM",
            runtime_seconds=time.perf_counter() - begin,
            expanded_nodes=first_non_exact.expanded_nodes,
            generated_nodes=first_non_exact.generated_nodes,
            table_bytes=first_non_exact.table_bytes,
            status=first_non_exact.status,
            is_verified=False,
            notes=(
                "universal nissy symmetry batch finished without a verified rotated exact solution; "
                "identity_rotation_excluded=true; "
                f"symmetry_variants={len(rotations)}; "
                f"timeout_seconds={self.config.nissy_symmetry_timeout_seconds}; "
                f"first_non_exact_status={first_non_exact.status}; "
                f"{rotation_order_note}; "
                f"first_non_exact_notes={first_non_exact.notes}"
            ),
        )

    def _resident_race_prepass_enabled(self) -> bool:
        timeout = self.config.resident_race_prepass_timeout_seconds
        return timeout is not None and timeout >= 0.0

    def _try_resident_race_prepass(
        self,
        cube: CubeState,
        *,
        source_sequence: list[str] | tuple[str, ...] | str | None = None,
    ) -> SolverResult | None:
        if not self._resident_race_prepass_enabled():
            return None
        timeout = self.config.resident_race_prepass_timeout_seconds
        assert timeout is not None
        race_config = self._resident_race_config(timeout_seconds=timeout)
        with ResidentRaceOptimalOracle(race_config) as resident_race:
            result = resident_race.solve(cube, source_sequence=source_sequence)
        return replace(
            result,
            notes=(
                f"{result.notes}; universal_resident_race_prepass=true; "
                f"resident_race_prepass_timeout_seconds={max(0.0, float(timeout)):.6f}"
            ),
        )

    def _try_nissy_core_direct_rotational_race(self, cube: CubeState) -> SolverResult | None:
        variant_count = max(0, int(self.config.nissy_core_direct_symmetry_variants))
        if (
            variant_count <= 0
            or not self.config.resident_race.include_nissy
            or not self.config.resident_race.include_nissy_core_direct
        ):
            return None

        identity = next((rotation for rotation in CUBE_ROTATIONS if rotation.is_identity), None)
        if identity is None:
            return None
        rotations = [identity] + [
            rotation for rotation in CUBE_ROTATIONS if not rotation.is_identity
        ][:variant_count]
        if not rotations:
            return None
        rotations, rotation_order_note = self._order_symmetry_rotations_by_h48_lower_bound(
            cube,
            rotations,
            context="nissy_core_direct_symmetry",
        )

        binary = _find_nissy_core_shell(
            self._certifying_portfolio._h48.root,
            self.config.resident_race.nissy_core_direct_binary_path,
        )
        if binary is None:
            return None
        table_path = self._certifying_portfolio._h48.table_path
        if not table_path.exists():
            return None

        temp_dir = Path(tempfile.mkdtemp(prefix="rubik-universal-nissy-core-symmetry-"))
        link_path = temp_dir / self._certifying_portfolio._h48.solver
        try:
            link_path.symlink_to(table_path.resolve())
        except OSError:
            shutil.rmtree(temp_dir, ignore_errors=True)
            return None

        timeout_seconds = (
            self.config.resident_race.timeout_seconds
            if self.config.nissy_core_direct_symmetry_timeout_seconds is None
            else self.config.nissy_core_direct_symmetry_timeout_seconds
        )
        per_rotation_timeout = None if timeout_seconds is None else max(0.0, float(timeout_seconds))
        global_timeout_seconds = per_rotation_timeout
        rotation_count = len(rotations)
        max_concurrency = self.config.nissy_core_direct_symmetry_max_concurrency
        concurrency = (
            rotation_count
            if max_concurrency <= 0
            else max(1, min(rotation_count, int(max_concurrency)))
        )

        begin = time.perf_counter()
        deadline = None if global_timeout_seconds is None else begin + global_timeout_seconds
        table_bytes = table_path.stat().st_size if table_path.exists() else 0
        pending = list(rotations)
        active: list[dict[str, object]] = []
        completed_statuses: list[tuple[str, str]] = []
        timed_out_rotations: list[str] = []
        setup_errors: list[str] = []
        global_timeout_expired = False

        def can_start_more() -> bool:
            return deadline is None or time.perf_counter() < deadline

        def start_rotation(rotation: object) -> None:
            try:
                rotated_cube = rotation.transform_cube(cube)
                nissy_cube = cube_to_nissy_string(rotated_cube)
            except Exception as exc:
                setup_errors.append(f"{rotation.name}:cube_conversion_failed:{exc}")
                return
            command = [
                str(binary),
                "solve",
                "-solver",
                self._certifying_portfolio._h48.solver,
                "-M",
                str(self.config.resident_race.h48.max_depth),
                "-n",
                "1",
                "-O",
                "0",
                "-cube",
                nissy_cube,
                "-t",
                str(max(1, self.config.resident_race.nissy_threads)),
            ]
            try:
                process = subprocess.Popen(
                    command,
                    cwd=temp_dir,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
            except Exception as exc:
                setup_errors.append(f"{rotation.name}:start_failed:{exc}")
                return
            active.append(
                {
                    "rotation": rotation,
                    "cube": rotated_cube,
                    "process": process,
                    "started_at": time.perf_counter(),
                }
            )

        def result_from_process(
            entry: dict[str, object],
            *,
            return_code: int,
            stdout: str,
            stderr: str,
            runtime_seconds: float,
            timed_out: bool = False,
        ) -> SolverResult:
            rotation = entry["rotation"]
            rotated_cube = entry["cube"]
            output = "\n".join(part for part in (stdout, stderr) if part)
            if timed_out:
                return SolverResult(
                    solver_name="nissy_core_direct_symmetry_race",
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
                    notes=f"rotation={rotation.name}; timed_out_after={per_rotation_timeout}; output={output.strip()}",
                )
            if return_code != 0:
                return SolverResult(
                    solver_name="nissy_core_direct_symmetry_race",
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
                    notes=f"rotation={rotation.name}; return_code={return_code}; output={output.strip()}",
                )
            try:
                rotated_solution, rotated_length = _parse_plain_nissy_core_solution(output)
                rotated_verification = verify_solution(rotated_cube, rotated_solution)
                if not rotated_verification.ok:
                    raise RuntimeError("rotated solution failed local verification")
                solution = rotation.inverse_transform_sequence(rotated_solution)
                verification = verify_solution(cube, solution)
                if not verification.ok:
                    raise RuntimeError("mapped solution failed original-state verification")
            except Exception as exc:
                return SolverResult(
                    solver_name="nissy_core_direct_symmetry_race",
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
                    notes=f"rotation={rotation.name}; parse_or_verify_error={exc}; output={output.strip()}",
                )
            return SolverResult(
                solver_name="nissy_core_direct_symmetry_race",
                input_state=cube.to_facelets(),
                solution_moves=solution,
                solution_length=len(solution),
                metric="HTM",
                runtime_seconds=runtime_seconds,
                expanded_nodes=None,
                generated_nodes=None,
                table_bytes=table_bytes,
                status="exact",
                is_verified=True,
                notes=(
                    "universal nissy-core direct rotational race; input_mode=cube_state; "
                    "exactness_policy=rotated_direct_exact_solution_mapped_back_and_verified; "
                    "identity_rotation_included=true; "
                    f"symmetry_variants={rotation_count}; selected_rotation={rotation.name}; "
                    f"rotated_solution_length={rotated_length}; "
                    f"solver={self._certifying_portfolio._h48.solver}; table_symlink=true; "
                    f"threads={self.config.resident_race.nissy_threads}; "
                    f"max_concurrency={concurrency}; global_timeout_seconds={global_timeout_seconds}; "
                    f"return_code={return_code}; "
                    f"{rotation_order_note}"
                ),
            )

        try:
            while pending or active:
                while pending and len(active) < concurrency and can_start_more():
                    start_rotation(pending.pop(0))
                if pending and not active and not can_start_more():
                    global_timeout_expired = True
                    break
                now = time.perf_counter()
                for entry in list(active):
                    process = entry["process"]
                    assert isinstance(process, subprocess.Popen)
                    return_code = process.poll()
                    runtime_seconds = now - float(entry["started_at"])
                    global_timed_out = deadline is not None and now >= deadline
                    timed_out = (
                        return_code is None
                        and (
                            global_timed_out
                            or (
                                per_rotation_timeout is not None
                                and runtime_seconds >= per_rotation_timeout
                            )
                        )
                    )
                    if timed_out:
                        global_timeout_expired = global_timeout_expired or global_timed_out
                        _stop_process(process)
                        stdout, stderr = process.communicate()
                        active.remove(entry)
                        result = result_from_process(
                            entry,
                            return_code=process.returncode or -9,
                            stdout=stdout,
                            stderr=stderr,
                            runtime_seconds=time.perf_counter() - float(entry["started_at"]),
                            timed_out=True,
                        )
                        timed_out_rotations.append(entry["rotation"].name)
                        completed_statuses.append((entry["rotation"].name, result.status))
                        continue
                    if return_code is None:
                        continue
                    stdout, stderr = process.communicate()
                    active.remove(entry)
                    result = result_from_process(
                        entry,
                        return_code=return_code,
                        stdout=stdout,
                        stderr=stderr,
                        runtime_seconds=time.perf_counter() - float(entry["started_at"]),
                    )
                    completed_statuses.append((entry["rotation"].name, result.status))
                    if _is_verified_exact(result):
                        for loser in active:
                            loser_process = loser["process"]
                            assert isinstance(loser_process, subprocess.Popen)
                            _stop_process(loser_process)
                        return replace(result, runtime_seconds=time.perf_counter() - begin)
                if deadline is not None and time.perf_counter() >= deadline:
                    global_timeout_expired = True
                    break
                if active or pending:
                    time.sleep(0.02)
        finally:
            for entry in active:
                process = entry["process"]
                assert isinstance(process, subprocess.Popen)
                _stop_process(process)
            shutil.rmtree(temp_dir, ignore_errors=True)

        status = "timeout" if timed_out_rotations else "failed"
        if global_timeout_expired:
            status = "timeout"
        return SolverResult(
            solver_name="nissy_core_direct_symmetry_race",
            input_state=cube.to_facelets(),
            solution_moves=[],
            solution_length=None,
            metric="HTM",
            runtime_seconds=time.perf_counter() - begin,
            expanded_nodes=None,
            generated_nodes=None,
            table_bytes=table_bytes,
            status=status,
            is_verified=False,
            notes=(
                "universal nissy-core direct rotational race finished without a verified exact solution; "
                f"identity_rotation_included=true; symmetry_variants={rotation_count}; "
                f"max_concurrency={concurrency}; timeout_seconds={per_rotation_timeout}; "
                f"global_timeout_seconds={global_timeout_seconds}; "
                f"global_timeout_expired={global_timeout_expired}; "
                f"pending_rotations_not_started={len(pending)}; "
                f"completed_statuses={completed_statuses}; timed_out_rotations={timed_out_rotations}; "
                f"setup_errors={setup_errors}; {rotation_order_note}"
            ),
        )

    def _order_symmetry_rotations_by_h48_lower_bound(
        self,
        cube: CubeState,
        rotations: list[CubeRotation],
        *,
        context: str,
    ) -> tuple[list[CubeRotation], str]:
        if not self.config.symmetry_order_by_h48_lower_bound:
            return rotations, f"{context}_h48_lower_bound_rotation_order=false"
        h48 = self.config.resident_race.h48
        table_path = self._certifying_portfolio._h48.table_path
        if not table_path.exists():
            return (
                rotations,
                f"{context}_h48_lower_bound_rotation_order=true; order_status=missing_table:{table_path}",
            )
        ordered, note = order_h48_rotations_by_lower_bound(
            cube,
            rotations,
            solver=self._certifying_portfolio._h48.solver,
            table_path=table_path,
            timeout_seconds=max(0.001, self.config.symmetry_lower_bound_order_timeout_seconds),
            threads=h48.threads,
            skip_table_check=h48.trusted_table,
            preload_table=h48.preload_table,
            root=h48.root,
        )
        return ordered, f"{context}_{note}"

    def _try_resident_h48_symmetry_batch(self, cube: CubeState) -> SolverResult | None:
        result = self._run_resident_h48_symmetry_batch(cube)
        if result is not None and result.status == "exact" and result.is_verified:
            return result
        return None

    def _try_parallel_h48_symmetry_race(self, cube: CubeState) -> SolverResult | None:
        result = self._run_parallel_h48_symmetry_race(cube)
        if result is not None and result.status == "exact" and result.is_verified:
            return result
        return None

    def _run_parallel_h48_symmetry_race(self, cube: CubeState) -> SolverResult | None:
        variant_count = max(0, int(self.config.parallel_h48_symmetry_variants))
        if variant_count <= 0 or not self.config.resident_race.include_h48:
            return None
        return self._resident_race._h48.solve_parallel_rotated_variants(
            cube,
            variant_count=variant_count,
            include_identity=True,
            timeout_seconds=self.config.parallel_h48_symmetry_timeout_seconds,
            max_concurrency=(
                None
                if self.config.parallel_h48_symmetry_max_concurrency <= 0
                else self.config.parallel_h48_symmetry_max_concurrency
            ),
            order_by_lower_bound=self.config.parallel_h48_symmetry_order_by_lower_bound,
            lower_bound_order_timeout_seconds=(
                self.config.parallel_h48_symmetry_lower_bound_order_timeout_seconds
            ),
        )

    def _run_resident_h48_symmetry_batch(self, cube: CubeState) -> SolverResult | None:
        variant_count = max(0, int(self.config.resident_h48_symmetry_variants))
        if variant_count <= 0 or not self.config.resident_race.include_h48:
            return None
        rotations, rotation_order_note = self._order_symmetry_rotations_by_h48_lower_bound(
            cube,
            _h48_symmetry_rotations(variant_count, include_identity=False),
            context="resident_h48_symmetry",
        )
        return self._resident_race._h48.solve_rotated_variants(
            cube,
            variant_count=variant_count,
            include_identity=False,
            timeout_seconds=self.config.resident_h48_symmetry_timeout_seconds,
            rotations=rotations,
            rotation_order_note=rotation_order_note,
        )

    def _rubikoptimal_fallback_enabled(self) -> bool:
        timeout = self.config.rubikoptimal_fallback_timeout_seconds
        return timeout is not None and timeout >= 0.0

    def _rubikoptimal_prepass_enabled(self) -> bool:
        timeout = self.config.rubikoptimal_prepass_timeout_seconds
        return timeout is not None and timeout >= 0.0

    def _rubikoptimal_symmetry_enabled(self) -> bool:
        timeout = self.config.rubikoptimal_symmetry_timeout_seconds
        return (
            max(0, int(self.config.rubikoptimal_symmetry_variants)) > 0
            and (timeout is None or timeout >= 0.0)
        )

    def _rubikoptimal_fallback_timeout(self, count: int) -> float:
        timeout = self.config.rubikoptimal_fallback_timeout_seconds
        if timeout is None:
            raise RuntimeError("RubikOptimal fallback timeout requested while fallback is disabled")
        return max(0.0, float(timeout)) * max(1, count)

    def _rubikoptimal_prepass_timeout(self, count: int) -> float:
        timeout = self.config.rubikoptimal_prepass_timeout_seconds
        if timeout is None:
            raise RuntimeError("RubikOptimal prepass timeout requested while prepass is disabled")
        return max(0.0, float(timeout)) * max(1, count)

    def _rubikoptimal_symmetry_timeout(self, count: int) -> float:
        return self._rubikoptimal_symmetry_global_timeout()

    def _rubikoptimal_symmetry_global_timeout(self) -> float:
        return self._rubikoptimal_symmetry_per_rotation_timeout()

    def _rubikoptimal_symmetry_per_rotation_timeout(self) -> float:
        timeout = self.config.rubikoptimal_symmetry_timeout_seconds
        if timeout is None:
            timeout = self.config.resident_race.timeout_seconds
        return max(0.0, float(timeout))

    def _try_rubikoptimal_prepass(self, cube: CubeState) -> SolverResult | None:
        if not self._rubikoptimal_prepass_enabled():
            return None
        return self._rubikoptimal_resident_session().solve(
            cube,
            timeout_seconds=self._rubikoptimal_prepass_timeout(1),
        )

    def _rubikoptimal_symmetry_include_identity(self) -> bool:
        return not self._rubikoptimal_prepass_enabled()

    def _rubikoptimal_symmetry_rotations(
        self,
        *,
        include_identity: bool | None = None,
    ) -> list[CubeRotation]:
        variant_count = max(0, int(self.config.rubikoptimal_symmetry_variants))
        if include_identity is None:
            include_identity = self._rubikoptimal_symmetry_include_identity()
        rotations: list[CubeRotation] = []
        if include_identity:
            rotations.extend(rotation for rotation in CUBE_ROTATIONS if rotation.is_identity)
        rotations.extend(
            rotation for rotation in CUBE_ROTATIONS if not rotation.is_identity
        )
        limit = variant_count + (1 if include_identity else 0)
        return rotations[:limit]

    def _try_rubikoptimal_symmetry_batch(self, cube: CubeState) -> SolverResult | None:
        if not self._rubikoptimal_symmetry_enabled():
            return None
        include_identity = self._rubikoptimal_symmetry_include_identity()
        rotations = self._rubikoptimal_symmetry_rotations(include_identity=include_identity)
        if not rotations:
            return None
        rotations, rotation_order_note = self._order_symmetry_rotations_by_h48_lower_bound(
            cube,
            rotations,
            context="rubikoptimal_symmetry",
        )

        max_concurrency = max(0, int(self.config.rubikoptimal_symmetry_max_concurrency))
        if max_concurrency > 0:
            return solve_rubikoptimal_external_rotational_race(
                cube,
                variant_count=len(rotations),
                include_identity=include_identity,
                rotations=rotations,
                rotation_order_note=rotation_order_note,
                timeout_seconds=self._rubikoptimal_symmetry_global_timeout(),
                max_concurrency=max_concurrency,
                executable=self.config.rubikoptimal_executable,
                package_path=self.config.rubikoptimal_package_path,
                table_dir=self.config.rubikoptimal_table_dir,
                root=self.config.resident_race.h48.root,
            )

        begin = time.perf_counter()
        rotated_cubes = [rotation.transform_cube(cube) for rotation in rotations]
        try:
            rotated_results, symmetry_wall_seconds = self._solve_rubikoptimal_resident_batch(
                rotated_cubes,
                total_timeout_seconds=self._rubikoptimal_symmetry_global_timeout(),
                note_flag="universal_symmetry_batch_uses_shared_rubikoptimal_session",
                budget_note_prefix="symmetry",
                exhausted_message=(
                    "RubikOptimal shared resident symmetry row skipped because the global "
                    "symmetry budget was exhausted"
                ),
            )
        except Exception:
            return None

        first_non_exact: SolverResult | None = None
        for rotation, rotated_result in zip(rotations, rotated_results, strict=False):
            if not _is_verified_exact(rotated_result):
                if first_non_exact is None:
                    first_non_exact = rotated_result
                continue
            mapped = self._rubikoptimal_symmetry_exact_result(
                cube,
                rotation=rotation,
                rotated_result=rotated_result,
                runtime_seconds=symmetry_wall_seconds,
                rotated_item_count=len(rotations),
                rotation_count=len(rotations),
                include_identity=include_identity,
                rotation_order_note=rotation_order_note,
            )
            if mapped is not None:
                return mapped

        if first_non_exact is None:
            return None
        return self._rubikoptimal_symmetry_non_exact_result(
            cube,
            first_non_exact=first_non_exact,
            rotation_count=len(rotations),
            rotated_item_count=len(rotations),
            include_identity=include_identity,
            runtime_seconds=time.perf_counter() - begin,
            rotation_order_note=rotation_order_note,
        )

    def _rubikoptimal_symmetry_exact_result(
        self,
        cube: CubeState,
        *,
        rotation: CubeRotation,
        rotated_result: SolverResult,
        runtime_seconds: float,
        rotated_item_count: int,
        rotation_count: int,
        include_identity: bool,
        rotation_order_note: str = "rubikoptimal_symmetry_h48_lower_bound_rotation_order=false",
    ) -> SolverResult | None:
        solution = rotation.inverse_transform_sequence(rotated_result.solution_moves)
        verification = verify_solution(cube, solution)
        if not verification.ok:
            return None
        return SolverResult(
            solver_name="rubikoptimal_symmetry_batch_oracle",
            input_state=cube.to_facelets(),
            solution_moves=solution,
            solution_length=len(solution),
            metric=rotated_result.metric,
            runtime_seconds=runtime_seconds,
            expanded_nodes=rotated_result.expanded_nodes,
            generated_nodes=rotated_result.generated_nodes,
            table_bytes=rotated_result.table_bytes,
            status="exact",
            is_verified=True,
            notes=(
                "universal RubikOptimal symmetry batch; "
                "exactness_policy=rotated_exact_solution_mapped_back_and_verified; "
                f"identity_rotation_included={include_identity}; "
                f"symmetry_variants={rotation_count}; "
                f"rotated_item_count={rotated_item_count}; selected_rotation={rotation.name}; "
                f"rotated_backend_solver={rotated_result.solver_name}; "
                f"rotated_runtime_seconds={rotated_result.runtime_seconds:.6f}; "
                f"rotated_solution_length={rotated_result.solution_length}; "
                f"{rotation_order_note}; "
                f"rotated_notes={rotated_result.notes}"
            ),
        )

    def _rubikoptimal_symmetry_failed_verification_result(
        self,
        cube: CubeState,
        *,
        rotation: CubeRotation,
        rotated_result: SolverResult,
        runtime_seconds: float,
    ) -> SolverResult:
        return SolverResult(
            solver_name="rubikoptimal_symmetry_batch_oracle",
            input_state=cube.to_facelets(),
            solution_moves=[],
            solution_length=None,
            metric="HTM",
            runtime_seconds=runtime_seconds,
            expanded_nodes=rotated_result.expanded_nodes,
            generated_nodes=rotated_result.generated_nodes,
            table_bytes=rotated_result.table_bytes,
            status="failed",
            is_verified=False,
            notes=(
                "universal RubikOptimal symmetry batch returned a rotated exact row, "
                "but mapping the solution back failed verification; "
                f"selected_rotation={rotation.name}; rotated_notes={rotated_result.notes}"
            ),
        )

    def _rubikoptimal_symmetry_non_exact_result(
        self,
        cube: CubeState,
        *,
        first_non_exact: SolverResult,
        rotation_count: int,
        rotated_item_count: int,
        include_identity: bool,
        runtime_seconds: float,
        rotation_order_note: str = "rubikoptimal_symmetry_h48_lower_bound_rotation_order=false",
    ) -> SolverResult:
        return SolverResult(
            solver_name="rubikoptimal_symmetry_batch_oracle",
            input_state=cube.to_facelets(),
            solution_moves=[],
            solution_length=None,
            metric="HTM",
            runtime_seconds=runtime_seconds,
            expanded_nodes=first_non_exact.expanded_nodes,
            generated_nodes=first_non_exact.generated_nodes,
            table_bytes=first_non_exact.table_bytes,
            status=first_non_exact.status,
            is_verified=False,
            notes=(
                "universal RubikOptimal symmetry batch finished without a verified rotated exact solution; "
                f"identity_rotation_included={include_identity}; "
                f"symmetry_variants={rotation_count}; rotated_item_count={rotated_item_count}; "
                f"timeout_seconds={self.config.rubikoptimal_symmetry_timeout_seconds}; "
                f"global_timeout_seconds={self._rubikoptimal_symmetry_global_timeout()}; "
                f"first_non_exact_status={first_non_exact.status}; "
                f"{rotation_order_note}; "
                f"first_non_exact_notes={first_non_exact.notes}"
            ),
        )

    def _annotate_rubikoptimal_fallback(
        self,
        fallback_result: SolverResult,
        *,
        prior_result: SolverResult,
        batch_wall_seconds: float,
    ) -> SolverResult:
        return replace(
            fallback_result,
            notes=(
                f"{fallback_result.notes}; universal_rubikoptimal_fallback=true; "
                f"rubikoptimal_batch_wall_seconds={batch_wall_seconds:.6f}; "
                f"prior_universal_solver={prior_result.solver_name}; "
                f"prior_universal_status={prior_result.status}; "
                f"prior_universal_verified={prior_result.is_verified}; "
                f"prior_universal_runtime_seconds={prior_result.runtime_seconds:.6f}; "
                f"prior_universal_notes={prior_result.notes}"
            ),
        )

    def _maybe_apply_rubikoptimal_fallback(
        self,
        cube: CubeState,
        prior_result: SolverResult,
        *,
        started_at: float,
        selected_backend: str,
    ) -> SolverResult:
        if _is_verified_exact(prior_result) or not self._rubikoptimal_fallback_enabled():
            return prior_result
        fallback_begin = time.perf_counter()
        fallback_result = self._rubikoptimal_resident_session().solve(
            cube,
            timeout_seconds=self._rubikoptimal_fallback_timeout(1),
        )
        batch_wall_seconds = time.perf_counter() - fallback_begin
        if fallback_result.status == "not_applicable":
            return replace(
                prior_result,
                notes=(
                    f"{prior_result.notes}; rubikoptimal_fallback_attempted=true; "
                    f"rubikoptimal_fallback_status={fallback_result.status}; "
                    f"rubikoptimal_fallback_runtime_seconds={fallback_result.runtime_seconds:.6f}; "
                    f"rubikoptimal_fallback_notes={fallback_result.notes}"
                ),
            )
        return self._wrap_result(
            self._annotate_rubikoptimal_fallback(
                fallback_result,
                prior_result=prior_result,
                batch_wall_seconds=batch_wall_seconds,
            ),
            selected_backend=selected_backend,
            total_runtime_seconds=time.perf_counter() - started_at,
        )

    def _rubikoptimal_resident_session(self) -> RubikOptimalOracleSession:
        if self._rubikoptimal_session is None:
            self._rubikoptimal_session = RubikOptimalOracleSession(
                executable=self.config.rubikoptimal_executable,
                package_path=self.config.rubikoptimal_package_path,
                table_dir=self.config.rubikoptimal_table_dir,
                root=self.config.resident_race.h48.root,
            )
        return self._rubikoptimal_session

    def _solve_rubikoptimal_resident_batch(
        self,
        cubes: list[CubeState],
        *,
        total_timeout_seconds: float,
        note_flag: str,
        budget_note_prefix: str,
        exhausted_message: str,
    ) -> tuple[list[SolverResult], float]:
        batch_begin = time.perf_counter()
        total_timeout_seconds = max(0.0, float(total_timeout_seconds))
        deadline = batch_begin + total_timeout_seconds
        per_row_timeout_seconds = total_timeout_seconds / max(1, len(cubes))
        shared_session = self._rubikoptimal_resident_session()
        batch_results: list[SolverResult] = []
        for row_index, cube in enumerate(cubes):
            row_begin = time.perf_counter()
            remaining_seconds = max(0.0, deadline - row_begin)
            if remaining_seconds + 1.0e-3 >= per_row_timeout_seconds:
                row_timeout_seconds = per_row_timeout_seconds
            else:
                row_timeout_seconds = remaining_seconds

            def budget_notes() -> str:
                return (
                    f"{note_flag}=true; "
                    f"{budget_note_prefix}_batch_row_index={row_index}; "
                    f"{budget_note_prefix}_row_timeout_seconds={row_timeout_seconds}; "
                    f"{budget_note_prefix}_global_timeout_seconds={total_timeout_seconds}; "
                    f"rubikoptimal_resident_start_count={shared_session.start_count}"
                )

            if row_timeout_seconds <= 0.0:
                selected_table_dir = (
                    Path(self.config.rubikoptimal_table_dir)
                    if self.config.rubikoptimal_table_dir is not None
                    else default_rubikoptimal_table_dir(self.config.resident_race.h48.root)
                )
                batch_results.append(
                    SolverResult(
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
                            f"{exhausted_message}; selected_backend=rubikoptimal_resident; "
                            f"backend_solver=rubikoptimal_external; {budget_notes()}"
                        ),
                    )
                )
                continue
            result = shared_session.solve(cube, timeout_seconds=row_timeout_seconds)
            batch_results.append(
                replace(
                    result,
                    notes=f"{result.notes}; {budget_notes()}",
                )
            )
        return batch_results, time.perf_counter() - batch_begin

    def _apply_rubikoptimal_fallback_many(
        self,
        cubes: list[CubeState],
        results: list[SolverResult | None],
    ) -> list[SolverResult]:
        complete_results = [result for result in results if result is not None]
        if not self._rubikoptimal_fallback_enabled():
            return complete_results
        pending: list[tuple[int, CubeState, SolverResult]] = []
        for index, result in enumerate(results):
            if result is None or _is_verified_exact(result):
                continue
            pending.append((index, cubes[index], result))
        if not pending:
            return complete_results

        fallback_begin = time.perf_counter()
        total_timeout_seconds = self._rubikoptimal_fallback_timeout(len(pending))
        deadline = fallback_begin + total_timeout_seconds
        per_row_timeout_seconds = total_timeout_seconds / max(1, len(pending))
        fallback_results: list[tuple[SolverResult, float]] = []
        shared_session = self._rubikoptimal_resident_session()
        for row_index, (_index, cube, _prior_result) in enumerate(pending):
            row_begin = time.perf_counter()
            remaining_seconds = max(0.0, deadline - row_begin)
            row_timeout_seconds = min(per_row_timeout_seconds, remaining_seconds)
            if row_timeout_seconds <= 0.0:
                selected_table_dir = (
                    Path(self.config.rubikoptimal_table_dir)
                    if self.config.rubikoptimal_table_dir is not None
                    else default_rubikoptimal_table_dir(self.config.resident_race.h48.root)
                )
                fallback_result = SolverResult(
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
                        "RubikOptimal shared resident fallback row skipped because the global "
                        "fallback budget was exhausted; selected_backend=rubikoptimal_resident; "
                        "backend_solver=rubikoptimal_external; "
                        "universal_fallback_uses_shared_rubikoptimal_session=true; "
                        f"fallback_batch_row_index={row_index}; "
                        f"fallback_row_timeout_seconds={row_timeout_seconds}; "
                        f"fallback_global_timeout_seconds={total_timeout_seconds}; "
                        f"rubikoptimal_resident_start_count={shared_session.start_count}"
                    ),
                )
            else:
                fallback_result = shared_session.solve(cube, timeout_seconds=row_timeout_seconds)
                fallback_result = replace(
                    fallback_result,
                    notes=(
                        f"{fallback_result.notes}; "
                        "universal_fallback_uses_shared_rubikoptimal_session=true; "
                        f"fallback_batch_row_index={row_index}; "
                        f"fallback_row_timeout_seconds={row_timeout_seconds}; "
                        f"fallback_global_timeout_seconds={total_timeout_seconds}; "
                        f"rubikoptimal_resident_start_count={shared_session.start_count}"
                    ),
                )
            fallback_results.append((fallback_result, row_timeout_seconds))
        batch_wall_seconds = time.perf_counter() - fallback_begin
        for (index, _cube, prior_result), (fallback_result, _row_timeout_seconds) in zip(
            pending,
            fallback_results,
            strict=False,
        ):
            if fallback_result.status == "not_applicable":
                results[index] = replace(
                    prior_result,
                    notes=(
                        f"{prior_result.notes}; rubikoptimal_fallback_attempted=true; "
                        f"rubikoptimal_fallback_status={fallback_result.status}; "
                        f"rubikoptimal_fallback_runtime_seconds={fallback_result.runtime_seconds:.6f}; "
                        f"rubikoptimal_fallback_notes={fallback_result.notes}"
                    ),
                )
                continue
            annotated = self._annotate_rubikoptimal_fallback(
                fallback_result,
                prior_result=prior_result,
                batch_wall_seconds=batch_wall_seconds,
            )
            results[index] = self._wrap_result(
                annotated,
                selected_backend="rubikoptimal-after-universal-fallback",
                total_runtime_seconds=max(0.0, prior_result.runtime_seconds) + batch_wall_seconds,
            )
        return [result for result in results if result is not None]

    def _wrap_result(
        self,
        result: SolverResult,
        *,
        selected_backend: str,
        total_runtime_seconds: float,
    ) -> SolverResult:
        wrapped = SolverResult(
            solver_name=self.solver_name,
            input_state=result.input_state,
            solution_moves=result.solution_moves,
            solution_length=result.solution_length,
            metric=result.metric,
            runtime_seconds=total_runtime_seconds,
            expanded_nodes=result.expanded_nodes,
            generated_nodes=result.generated_nodes,
            table_bytes=result.table_bytes,
            status=result.status,
            is_verified=result.is_verified,
            notes=(
                "universal exact oracle; exactness_policy=verified_exact_only; "
                "arbitrary_valid_3x3_domain=true; "
                "optimized_paths=exact_certificate_cache,upper_lower_certificate,nissy_symmetry_batch,"
                "resident_h48_symmetry_batch,parallel_h48_symmetry_race,resident_h48_batch,"
                "rubikoptimal_prepass,rubikoptimal_symmetry_batch,rubikoptimal_race,"
                "portfolio_after_resident_h48_fallback,"
                "nissy_core_direct_late_fallback,rubikoptimal_table_complete_fallback,resident_race; "
                "fast_runtime_proven_for_every_possible_state=false; "
                f"selected_backend={selected_backend}; backend_solver={result.solver_name}; "
                f"backend_runtime_seconds={result.runtime_seconds:.6f}; {result.notes}"
            ),
        )
        self._certifying_portfolio.remember_result(wrapped, selected_backend=selected_backend)
        return wrapped


def solve_universal_optimal(
    cube: CubeState,
    config: UniversalOptimalOracleConfig | None = None,
    *,
    source_sequence: list[str] | tuple[str, ...] | str | None = None,
) -> SolverResult:
    """Solve one valid 3x3 state through the unified optimized exact oracle."""

    oracle = UniversalOptimalOracle(config)
    try:
        return oracle.solve(cube, source_sequence=source_sequence)
    finally:
        oracle.close()

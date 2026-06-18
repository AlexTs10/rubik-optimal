"""End-to-end 3x3 solving helpers for CLI and evidence scripts."""

from __future__ import annotations

import time

from rubik_optimal.cube import CubeState
from rubik_optimal.moves import inverse_sequence
from rubik_optimal.solvers.base import SolverResult
from rubik_optimal.solvers.kociemba import solve_kociemba_adapter, solve_kociemba_native_scoped
from rubik_optimal.solvers.thistlethwaite import solve_thistlethwaite_native_scoped
from rubik_optimal.verify import verify_solution


def solve_scramble_inverse(cube: CubeState, sequence: list[str] | tuple[str, ...]) -> SolverResult:
    """Return the verified inverse of a supplied generating sequence.

    This is useful for command-line smoke checks where the input is explicitly a
    scramble sequence. It is not a solver for arbitrary facelet-only states and
    therefore never supports optimality claims.
    """

    begin = time.perf_counter()
    solution = inverse_sequence(sequence)
    verification = verify_solution(cube, solution)
    return SolverResult(
        solver_name="scramble_inverse_verified",
        input_state=cube.to_facelets(),
        solution_moves=solution,
        solution_length=len(solution),
        metric="HTM",
        runtime_seconds=time.perf_counter() - begin,
        expanded_nodes=0,
        generated_nodes=0,
        table_bytes=None,
        status="non_exact" if verification.ok else "failed",
        is_verified=verification.ok,
        notes=(
            "Direct inverse of the supplied move sequence; useful for E2E verification, "
            "not applicable to arbitrary facelet-only states and no optimality proof claimed"
        ),
    )


def solve_auto_3x3(
    cube: CubeState,
    *,
    source_sequence: list[str] | tuple[str, ...] | None = None,
    # Defaults equal the phase diameters so the scoped two-phase leg is not
    # incomplete by configuration (phase 1 diameter 12, phase 2 diameter 18).
    native_phase1_depth: int = 12,
    native_phase2_depth: int = 18,
    thistle_stage1_depth: int = 7,
    thistle_stage2_depth: int = 8,
    thistle_stage3_depth: int = 13,
    timeout_seconds: float = 5.0,
) -> SolverResult:
    """Try the practical 3x3 solving stack and return the first verified result."""

    attempts: list[SolverResult] = []

    native = solve_kociemba_native_scoped(
        cube,
        phase1_max_depth=native_phase1_depth,
        phase2_max_depth=native_phase2_depth,
        timeout_seconds=timeout_seconds,
    )
    attempts.append(native)
    if native.is_verified and native.solution_length is not None:
        return native

    adapter = solve_kociemba_adapter(cube)
    attempts.append(adapter)
    if adapter.is_verified and adapter.solution_length is not None:
        return adapter

    thistle = solve_thistlethwaite_native_scoped(
        cube,
        stage1_max_depth=thistle_stage1_depth,
        stage2_max_depth=thistle_stage2_depth,
        stage3_max_depth=thistle_stage3_depth,
        stage2_candidate_limit=64,
        stage3_candidate_limit=8,
        timeout_seconds=timeout_seconds,
    )
    attempts.append(thistle)
    if thistle.is_verified and thistle.solution_length is not None:
        return thistle

    if source_sequence is not None:
        inverse = solve_scramble_inverse(cube, source_sequence)
        attempts.append(inverse)
        if inverse.is_verified and inverse.solution_length is not None:
            return inverse

    notes = "; ".join(
        f"{result.solver_name}:{result.status}:{result.solution_length}" for result in attempts
    )
    return SolverResult(
        solver_name="auto_3x3",
        input_state=cube.to_facelets(),
        solution_moves=[],
        solution_length=None,
        metric="HTM",
        runtime_seconds=sum(result.runtime_seconds for result in attempts),
        expanded_nodes=sum(result.expanded_nodes or 0 for result in attempts),
        generated_nodes=sum(result.generated_nodes or 0 for result in attempts),
        table_bytes=max((result.table_bytes or 0 for result in attempts), default=0),
        status="failed",
        is_verified=False,
        notes=f"No configured 3x3 solver produced a verified solution; attempts={notes}",
    )

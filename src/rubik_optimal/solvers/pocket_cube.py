"""Solver facade for the normalized Pocket Cube case study."""

from __future__ import annotations

import time

from rubik_optimal.pocket.cube import PocketState
from rubik_optimal.pocket.optimal import pocket_optimal_solution
from rubik_optimal.solvers.base import SolverResult


def solve_pocket_cube_optimal(
    state: PocketState,
    *,
    max_depth: int = 14,
) -> SolverResult:
    begin = time.perf_counter()
    solution, expanded, generated = pocket_optimal_solution(state, max_depth=max_depth)
    verified = solution is not None and state.apply_sequence(solution).is_solved()
    return SolverResult(
        solver_name="pocket_cube_optimal",
        input_state=str(state.coord()),
        solution_moves=solution or [],
        solution_length=len(solution) if solution is not None else None,
        metric="normalized HTM over U/R/F",
        runtime_seconds=time.perf_counter() - begin,
        expanded_nodes=expanded,
        generated_nodes=generated,
        table_bytes=None,
        status="exact" if verified else "timeout",
        is_verified=verified,
        notes="Exact BFS in the fixed-corner normalized 2x2x2 state space",
    )


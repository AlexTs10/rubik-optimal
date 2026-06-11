"""Korf-style IDA* solver with an admissible cubie lower bound.

This module is a BOUNDED PEDAGOGICAL DEMONSTRATION of Richard Korf's IDA*
pattern-database search, written in pure Python.  It is deliberately scoped
(default ``max_depth=8``, a node limit, and a wall-clock timeout) so that the
algorithm's structure stays readable and the solve finishes quickly on shallow
scrambles.  Within its bound it is provably optimal: it returns the exact
shortest solution whenever one exists at depth <= ``max_depth`` and reports an
honest non-exact status (``lower_bound`` / ``timeout``) otherwise.

It is NOT the production optimal engine.  Deep states (the diameter of the
group is 20 in HTM) require the student's native C++ corner+edge pattern-
database IDA* exposed as ``solve_korf_native_optimal`` (CLI: ``--solver
optimal-native``).  See :func:`rubik_optimal.solvers.optimal_native.solve_korf_native_optimal`.
"""

from __future__ import annotations

from rubik_optimal.cube import CubeState
from rubik_optimal.search.heuristics import (
    combined_table_lower_bound,
    coordinate_pruning_table_bytes,
    corner_pattern_database_bytes,
    edge_pattern_database_bytes,
)
from rubik_optimal.search.ida_star import ida_star_solve
from rubik_optimal.solvers.base import SolverResult
from rubik_optimal.verify import verify_solution


# Note appended whenever the scoped solver cannot prove an optimal solution
# within its bound, so a reader of the JSON output is never misled into
# thinking a non-exact result is the optimal distance.
_SCOPED_DEMO_NOTE = (
    "scoped pedagogical Python IDA*; optimal solutions for deep states require "
    "--solver optimal-native (native C++ corner+edge PDB)."
)


def solve_korf_ida(
    cube: CubeState,
    *,
    max_depth: int = 8,
    timeout_seconds: float = 5.0,
    node_limit: int = 500_000,
) -> SolverResult:
    """Bounded demonstration of Korf-style IDA* (pure Python).

    Returns the exact optimal solution when one exists at depth
    <= ``max_depth`` within the node/time budget; otherwise returns an honest
    non-exact result (status ``lower_bound`` when the admissible bound exceeds
    ``max_depth`` or no solution was found within the depth, ``timeout`` when
    the wall-clock/node budget was hit).  In both non-exact cases a note is
    appended pointing to the native optimal engine.

    This is a scoped pedagogical demonstrator, not the production optimal
    solver; see the module docstring and
    :func:`rubik_optimal.solvers.optimal_native.solve_korf_native_optimal`.
    """

    corner_pdb_bytes = corner_pattern_database_bytes()
    edge_pdb_bytes = edge_pattern_database_bytes()
    # combined_table_lower_bound is the frozen 6-edge thesis heuristic (the
    # optional 7-edge PDBs are strictly opt-in elsewhere and never consulted
    # here), so table_bytes deliberately counts only the tables this search
    # actually uses: coordinate projections + corner PDB + eight 6-edge PDBs.
    table_bytes = coordinate_pruning_table_bytes() + corner_pdb_bytes + edge_pdb_bytes
    outcome = ida_star_solve(
        cube,
        max_depth=max_depth,
        timeout_seconds=timeout_seconds,
        node_limit=node_limit,
        heuristic=combined_table_lower_bound,
    )
    solution = outcome.solution or []
    verification = verify_solution(cube, solution) if outcome.solution is not None else None
    notes = (
        f"{outcome.notes}; table_lower_bound={outcome.lower_bound}; "
        f"corner_pdb_bytes={corner_pdb_bytes}; edge_pdb_bytes={edge_pdb_bytes}; max_depth={max_depth}"
    )
    # Cover BOTH non-exact branches: the early-exit lower-bound > max_depth case
    # and the depth-exhausted / timeout / node-limit cases all surface here.
    if outcome.status in {"lower_bound", "timeout"}:
        notes = f"{notes}; {_SCOPED_DEMO_NOTE}"
    return SolverResult(
        solver_name="korf_ida_star_scoped",
        input_state=cube.to_facelets(),
        solution_moves=solution,
        solution_length=len(solution) if outcome.solution is not None else None,
        metric="HTM",
        runtime_seconds=outcome.runtime_seconds,
        expanded_nodes=outcome.expanded_nodes,
        generated_nodes=outcome.generated_nodes,
        table_bytes=table_bytes,
        status=outcome.status,
        is_verified=bool(verification and verification.ok),
        notes=notes,
    )

"""Provably-optimal two-phase (iterated phase-1) HTM solver.

This is WORSTCASE Path 3 from ``docs/WORSTCASE_HEURISTIC_DESIGN.md``: instead of
pushing IDA*+PDB, iterate Kociemba phase-1 over increasing depths and pair each
phase-1 maneuver with an *optimal* phase-2 solve, tracking the best total. It
reuses the existing phase-1 coordinate tables and the existing optimal phase-2
IDA* in :mod:`rubik_optimal.solvers.kociemba`.

Why this is provably optimal (the key theorem, since claiming optimality is the
#1 risk):

    G1 = <U, D, R2, L2, F2, B2> is a *subgroup*. Take any solution S of the
    input cube C, S = m1 m2 ... mL. Let j* be the LAST index whose move is not a
    phase-2 (G1-preserving) move; then the suffix R = m[j*+1..L] consists only of
    G1-preserving moves and ends at the solved state (which is in G1). Because G1
    is closed under its generators and their inverses, the state C.P reached by
    the prefix P = m[1..j*] must ALSO be in G1. Hence every solution decomposes
    as (phase-1 maneuver P reaching G1) + (phase-2 maneuver R), with
    |P| + |R| = L. Therefore

        min over { phase-1 maneuver P, phase-2 maneuver R : C.P.R solved } of
        |P| + |R|   ==   the optimal HTM length of C.

    We enumerate phase-1 maneuvers by increasing length d and, for each distinct
    reachable G1 state, compute the OPTIMAL phase-2 length. Once the phase-1
    search depth d reaches the best total found, every unexplored maneuver has
    |P| = d >= best, so no shorter solution can exist: best is optimal.

Honest tractability note: enumerating phase-1 maneuvers to depth d costs about
13.3^d, so the outer loop is only tractable when the optimum is found and proven
at a modest d. This engine optimally solves moderate-depth states fast and is an
INDEPENDENT optimal cross-check for the native Korf solver; it does NOT claim to
crack the depth-20 superflip quickly (that needs symmetry reduction, Path 2). It
NEVER reports ``status="exact"`` unless optimality was actually proven within the
search budget; otherwise it returns the verified solution as ``non_exact`` with
the proven lower bound.
"""

from __future__ import annotations

import math
import time

from rubik_optimal.coordinates import (
    CORNER_ORIENTATION_SPEC,
    EDGE_ORIENTATION_SPEC,
    UD_SLICE_SPEC,
)
from rubik_optimal.coordinates.phase2 import (
    encode_phase2_corner_permutation,
    encode_phase2_slice_edge_permutation,
    encode_phase2_ud_edge_permutation,
)
from rubik_optimal.cube import CubeState
from rubik_optimal.moves import ALL_MOVES, same_face
from rubik_optimal.search.ida_star import _commuting_order_violation
from rubik_optimal.search.heuristics import combined_table_lower_bound
from rubik_optimal.solvers.base import SolverResult
from rubik_optimal.solvers.kociemba import (
    _native_table_bytes,
    _phase1_coordinate_tables,
    solve_kociemba_phase2,
)
from rubik_optimal.verify import verify_solution

def _phase2_state_key(cube: CubeState) -> tuple[int, int, int]:
    """A G1 state is fully determined by its three phase-2 permutation coords."""

    return (
        encode_phase2_corner_permutation(cube),
        encode_phase2_ud_edge_permutation(cube),
        encode_phase2_slice_edge_permutation(cube),
    )


class _Budget:
    """Tracks the time/node budget and whether it forced an incomplete search."""

    def __init__(self, deadline: float, phase1_node_limit: int):
        self.deadline = deadline
        self.phase1_node_limit = phase1_node_limit
        self.phase1_nodes = 0
        self.phase2_expanded = 0
        self.phase2_generated = 0
        self.aborted = False

    def exhausted(self) -> bool:
        if self.aborted:
            return True
        if self.phase1_node_limit and self.phase1_nodes >= self.phase1_node_limit:
            self.aborted = True
        elif time.perf_counter() >= self.deadline:
            self.aborted = True
        return self.aborted


def _enumerate_phase1_g1_states_at_depth(
    cube: CubeState,
    depth: int,
    move_tables: tuple[list[list[int]], ...],
    pruning_tables: tuple[tuple[int, ...], ...],
    budget: _Budget,
):
    """Yield (maneuver, g1_cube) for distinct G1 states reachable in exactly ``depth`` moves.

    Coordinate-space DFS over the three phase-1 projections, pruned by the
    admissible phase-1 lower bound (f = g + h1 <= depth) plus the standard
    same-face and commuting-order restrictions. Both restrictions are safe for an
    iterated-deepening search: any maneuver they remove has an equal-length or
    shorter equivalent reaching the SAME state, so no G1 state is lost at its
    minimal reachable length (it is simply found at that depth via the canonical
    sequence). De-duplication within this depth is by full G1 state.
    """

    co0 = CORNER_ORIENTATION_SPEC.encode(cube)
    eo0 = EDGE_ORIENTATION_SPEC.encode(cube)
    sl0 = UD_SLICE_SPEC.encode(cube)
    co_move, eo_move, sl_move = move_tables
    co_prune, eo_prune, sl_prune = pruning_tables

    if max(co_prune[co0], eo_prune[eo0], sl_prune[sl0]) > depth:
        return  # cannot reach G1 in exactly `depth` moves

    seen_here: set[tuple[int, int, int]] = set()
    path: list[int] = []  # move indices
    results: list[tuple[list[str], CubeState]] = []

    def recurse_tracked(co: int, eo: int, sl: int, g: int, previous: str | None) -> None:
        if budget.exhausted():
            return
        remaining = depth - g
        if max(co_prune[co], eo_prune[eo], sl_prune[sl]) > remaining:
            return
        if g == depth:
            maneuver = [ALL_MOVES[i] for i in path]
            g1_cube = cube.apply_sequence(maneuver)
            key = _phase2_state_key(g1_cube)
            if key not in seen_here:
                seen_here.add(key)
                results.append((maneuver, g1_cube))
            return
        budget.phase1_nodes += 1
        for move_index in range(18):
            move = ALL_MOVES[move_index]
            if same_face(previous, move) or _commuting_order_violation(previous, move):
                continue
            path.append(move_index)
            recurse_tracked(
                co_move[co][move_index],
                eo_move[eo][move_index],
                sl_move[sl][move_index],
                g + 1,
                move,
            )
            path.pop()
            if budget.exhausted():
                return

    recurse_tracked(co0, eo0, sl0, 0, None)
    return results


def solve_kociemba_two_phase_optimal(
    cube: CubeState,
    *,
    max_total_depth: int = 20,
    time_budget_seconds: float = 120.0,
    phase1_node_limit: int = 30_000_000,
    phase2_node_limit: int = 3_000_000,
    phase2_timeout_seconds: float = 20.0,
) -> SolverResult:
    """Solve ``cube`` optimally via iterated phase-1 + optimal phase-2.

    Returns ``status="exact"`` only when optimality is PROVEN within the budget
    (the outer phase-1 depth reached the best total with no inconclusive phase-2
    sub-search). Otherwise returns the best verified solution as ``non_exact``
    with the proven lower bound recorded in the notes.
    """

    start = time.perf_counter()
    deadline = start + time_budget_seconds
    move_tables, pruning_tables = _phase1_coordinate_tables()

    if cube.is_solved():
        return SolverResult(
            solver_name="kociemba_two_phase_optimal",
            input_state=cube.to_facelets(),
            solution_moves=[],
            solution_length=0,
            metric="HTM",
            runtime_seconds=time.perf_counter() - start,
            expanded_nodes=0,
            generated_nodes=0,
            table_bytes=_native_table_bytes(),
            status="exact",
            is_verified=True,
            notes="already solved; optimal length 0 (proven)",
        )

    # Both are admissible lower bounds on the TOTAL HTM length, so their max seeds
    # the iterated-deepening floor.
    co0 = CORNER_ORIENTATION_SPEC.encode(cube)
    eo0 = EDGE_ORIENTATION_SPEC.encode(cube)
    sl0 = UD_SLICE_SPEC.encode(cube)
    phase1_floor = max(pruning_tables[0][co0], pruning_tables[1][eo0], pruning_tables[2][sl0])
    total_floor = max(phase1_floor, combined_table_lower_bound(cube))

    budget = _Budget(deadline, phase1_node_limit)
    best = math.inf
    best_solution: list[str] | None = None
    seen_g1: set[tuple[int, int, int]] = set()
    proven_lower_bound = total_floor
    aborted_depth: int | None = None

    d = total_floor
    while d <= max_total_depth:
        if d >= best:
            break  # PROVEN OPTIMAL: any further maneuver has length d >= best
        if budget.exhausted():
            aborted_depth = d
            break

        states = _enumerate_phase1_g1_states_at_depth(cube, d, move_tables, pruning_tables, budget)
        if budget.exhausted():
            aborted_depth = d
            break

        for maneuver, g1_cube in states or []:
            key = _phase2_state_key(g1_cube)
            if key in seen_g1:
                continue  # already optimally phase-2-solved at a shorter phase-1 length
            seen_g1.add(key)

            cutoff = (best - d - 1) if best != math.inf else (max_total_depth - d)
            if cutoff < 0:
                continue
            remaining_time = deadline - time.perf_counter()
            if remaining_time <= 0:
                budget.aborted = True
                aborted_depth = d
                break
            p2 = solve_kociemba_phase2(
                g1_cube,
                max_depth=int(cutoff),
                timeout_seconds=min(phase2_timeout_seconds, remaining_time),
                node_limit=phase2_node_limit,
            )
            budget.phase2_expanded += p2.expanded_nodes
            budget.phase2_generated += p2.generated_nodes
            if p2.status == "exact" and p2.solution is not None:
                total = d + len(p2.solution)
                if total < best:
                    best = total
                    best_solution = list(maneuver) + list(p2.solution)
            elif p2.status == "lower_bound":
                continue  # PROVEN: no phase-2 solution within the cutoff from this G1 state
            else:
                # timeout / node_limit / failed: this G1 state is unresolved, so the
                # depth-d enumeration is incomplete and optimality cannot be proven.
                budget.aborted = True
                aborted_depth = d
                break

        if budget.aborted:
            if aborted_depth is None:
                aborted_depth = d
            break
        # Depth d fully searched with no inconclusive sub-search: the optimum is
        # not strictly below d+1 unless already found, so the proven lower bound
        # advances. (If best was found, the loop will break at d+1 >= best.)
        proven_lower_bound = d + 1
        d += 1

    runtime = time.perf_counter() - start
    table_bytes = _native_table_bytes()
    proven_optimal = best_solution is not None and not budget.aborted

    if best_solution is not None:
        verification = verify_solution(cube, best_solution)
        verified = verification.ok
    else:
        verified = False

    if proven_optimal and verified:
        status = "exact"
        proven_lower_bound = best  # type: ignore[assignment]
    elif best_solution is not None and verified:
        status = "non_exact"
    elif budget.aborted:
        status = "timeout"
    else:
        status = "lower_bound"

    lower_bound = int(min(proven_lower_bound, best) if best != math.inf else proven_lower_bound)
    notes = (
        f"iterated phase-1 two-phase to optimal; "
        f"proven_optimal={proven_optimal}; "
        f"proven_lower_bound={lower_bound}; "
        f"best_total={best if best != math.inf else None}; "
        f"aborted={budget.aborted}; aborted_depth={aborted_depth}; "
        f"total_floor={total_floor}; phase1_nodes={budget.phase1_nodes}; "
        f"distinct_g1_states={len(seen_g1)}; max_total_depth={max_total_depth}; "
        f"time_budget_seconds={time_budget_seconds}"
    )

    return SolverResult(
        solver_name="kociemba_two_phase_optimal",
        input_state=cube.to_facelets(),
        solution_moves=best_solution or [],
        solution_length=(len(best_solution) if best_solution is not None else None),
        metric="HTM",
        runtime_seconds=runtime,
        expanded_nodes=budget.phase1_nodes + budget.phase2_expanded,
        generated_nodes=budget.phase2_generated,
        table_bytes=table_bytes,
        status=status,
        is_verified=bool(best_solution is not None and verified),
        notes=notes,
    )

"""IDA* exact search for feasible 3x3 states."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Callable

from rubik_optimal.cube import CubeState
from rubik_optimal.moves import ALL_MOVES, same_face
from rubik_optimal.search.heuristics import misplaced_cubie_lower_bound

# Axis grouping for the standard Korf canonical move ordering.  Opposite faces
# of the same axis commute (e.g. U and D), so every commuting pair would
# otherwise be explored in both orders.  We pick one canonical order per axis
# and forbid the *second* face being immediately followed by the *first* face
# of the same axis.  This is admissible: it only removes one redundant ordering
# of a commuting pair, never the only path to a state, so optimal lengths are
# preserved for ANY move subset (restricted Thistlethwaite/Kociemba sets too).
_AXIS_OF_FACE = {
    "U": 0, "D": 0,
    "R": 1, "L": 1,
    "F": 2, "B": 2,
}
# The "first" face of each axis; a move on this face may not directly follow a
# move on the opposite (second) face of the same axis.
_FIRST_FACE_OF_AXIS = {0: "U", 1: "R", 2: "F"}


def _commuting_order_violation(previous: str | None, move: str) -> bool:
    """Return True if ``move`` after ``previous`` breaks canonical commuting order.

    ``previous`` and ``move`` are on opposite faces of the same axis (they
    commute), and ``move`` is the canonical "first" face while ``previous`` was
    the "second" face.  Exploring this pair in this order is redundant with the
    canonical order, so it is pruned.  Same-face repeats are handled separately
    by :func:`same_face`.
    """

    if previous is None:
        return False
    prev_face = previous[0]
    move_face = move[0]
    if prev_face == move_face:
        return False  # same face: handled by same_face()
    axis = _AXIS_OF_FACE[move_face]
    if _AXIS_OF_FACE[prev_face] != axis:
        return False  # different axes: do not commute, never prune
    # Opposite faces of one axis: keep only the canonical order, i.e. forbid the
    # "first" face directly after the "second" face.
    return move_face == _FIRST_FACE_OF_AXIS[axis]


@dataclass(frozen=True)
class IDAStarResult:
    solution: list[str] | None
    expanded_nodes: int
    generated_nodes: int
    max_depth: int
    status: str
    runtime_seconds: float
    lower_bound: int
    notes: str


@dataclass(frozen=True)
class IDAStarCandidatesResult:
    solutions: list[list[str]]
    expanded_nodes: int
    generated_nodes: int
    max_depth: int
    status: str
    runtime_seconds: float
    lower_bound: int
    notes: str


def ida_star_solve(
    start: CubeState,
    *,
    max_depth: int = 8,
    timeout_seconds: float = 5.0,
    node_limit: int = 500_000,
    heuristic: Callable[[CubeState], int] = misplaced_cubie_lower_bound,
    goal_test: Callable[[CubeState], bool] | None = None,
    moves: tuple[str, ...] = ALL_MOVES,
    order_children_by_heuristic: bool = False,
    prune_commuting_moves: bool = True,
) -> IDAStarResult:
    begin = time.perf_counter()
    goal = goal_test or CubeState.is_solved
    heuristic_cache: dict[CubeState, int] = {}

    def h(cube: CubeState) -> int:
        value = heuristic_cache.get(cube)
        if value is None:
            value = heuristic(cube)
            heuristic_cache[cube] = value
        return value

    lower_bound = h(start)
    if goal(start):
        return IDAStarResult([], 0, 0, max_depth, "exact", 0.0, 0, "Goal already satisfied")
    if lower_bound > max_depth:
        return IDAStarResult(
            None, 0, 0, max_depth, "lower_bound", time.perf_counter() - begin,
            lower_bound, "Admissible lower bound exceeds configured max depth",
        )

    expanded = 0
    generated = 0
    path: list[str] = []

    def timed_out() -> bool:
        return (time.perf_counter() - begin) >= timeout_seconds

    def node_budget_exceeded() -> bool:
        # Bound BOTH expanded and generated nodes.  Generated-node blow-ups
        # between expansions are otherwise unbounded; summing them keeps the
        # check monotone (the sum never decreases) so the search still
        # terminates predictably.
        return (expanded + generated) >= node_limit

    def search(cube: CubeState, g: int, bound: int, previous: str | None) -> int | list[str]:
        nonlocal expanded, generated
        f_score = g + h(cube)
        if f_score > bound:
            return f_score
        if goal(cube):
            return list(path)
        if g >= max_depth:
            return math.inf
        if timed_out() or node_budget_exceeded():
            return math.inf

        expanded += 1
        minimum = math.inf
        children: list[tuple[int, str, CubeState]] = []
        for move in moves:
            if same_face(previous, move):
                continue
            if prune_commuting_moves and _commuting_order_violation(previous, move):
                continue
            child = cube.apply_move(move)
            generated += 1
            if order_children_by_heuristic:
                children.append((h(child), move, child))
            else:
                children.append((0, move, child))
        if order_children_by_heuristic:
            children.sort(key=lambda item: (item[0], item[1]))
        for _, move, child in children:
            path.append(move)
            outcome = search(child, g + 1, bound, move)
            if isinstance(outcome, list):
                return outcome
            if outcome < minimum:
                minimum = outcome
            path.pop()
            if timed_out() or node_budget_exceeded():
                break
        return minimum

    bound = lower_bound
    while bound <= max_depth:
        outcome = search(start, 0, bound, None)
        runtime = time.perf_counter() - begin
        if isinstance(outcome, list):
            return IDAStarResult(
                outcome, expanded, generated, max_depth, "exact", runtime,
                lower_bound, "IDA* completed before timeout",
            )
        if timed_out():
            return IDAStarResult(
                None, expanded, generated, max_depth, "timeout", runtime,
                lower_bound, "IDA* timed out",
            )
        if node_budget_exceeded():
            # Node-limit exhaustion deliberately reuses status "timeout": the
            # benchmark schema and the saved thesis artifacts pin the status
            # enum (exact/non_exact/lower_bound/timeout/not_applicable/failed),
            # and both stops are the same honest non-exact budget exhaustion.
            # The notes string records which budget was hit.
            return IDAStarResult(
                None, expanded, generated, max_depth, "timeout", runtime,
                lower_bound, "IDA* node limit reached",
            )
        if outcome == math.inf:
            break
        bound = int(outcome)

    return IDAStarResult(
        None, expanded, generated, max_depth, "lower_bound", time.perf_counter() - begin,
        lower_bound, "No exact solution within configured depth",
    )


def ida_star_collect_solutions(
    start: CubeState,
    *,
    max_depth: int = 8,
    timeout_seconds: float = 5.0,
    node_limit: int = 500_000,
    heuristic: Callable[[CubeState], int] = misplaced_cubie_lower_bound,
    goal_test: Callable[[CubeState], bool] | None = None,
    moves: tuple[str, ...] = ALL_MOVES,
    max_solutions: int = 16,
    order_children_by_heuristic: bool = False,
    prune_commuting_moves: bool = True,
) -> IDAStarCandidatesResult:
    """Collect bounded candidate paths to a goal predicate.

    This is used by staged solvers where the first subgroup hit is not
    necessarily the best hand-off state for the next stage.
    """

    begin = time.perf_counter()
    goal = goal_test or CubeState.is_solved
    heuristic_cache: dict[CubeState, int] = {}

    def h(cube: CubeState) -> int:
        value = heuristic_cache.get(cube)
        if value is None:
            value = heuristic(cube)
            heuristic_cache[cube] = value
        return value

    lower_bound = h(start)
    if max_solutions <= 0:
        raise ValueError("max_solutions must be positive")
    if goal(start):
        return IDAStarCandidatesResult(
            [[]], 0, 0, max_depth, "exact", 0.0, 0, "Goal already satisfied",
        )
    if lower_bound > max_depth:
        return IDAStarCandidatesResult(
            [], 0, 0, max_depth, "lower_bound", time.perf_counter() - begin,
            lower_bound, "Admissible lower bound exceeds configured max depth",
        )

    expanded = 0
    generated = 0
    path: list[str] = []
    solutions: list[list[str]] = []
    seen_goal_states: set[str] = set()

    def timed_out() -> bool:
        return (time.perf_counter() - begin) >= timeout_seconds

    def node_budget_exceeded() -> bool:
        # Bound BOTH expanded and generated nodes (see ida_star_solve).
        return (expanded + generated) >= node_limit

    def search(cube: CubeState, g: int, bound: int, previous: str | None) -> int:
        nonlocal expanded, generated
        if len(solutions) >= max_solutions or timed_out() or node_budget_exceeded():
            return math.inf
        f_score = g + h(cube)
        if f_score > bound:
            return f_score
        if goal(cube):
            state_key = cube.to_facelets()
            if state_key not in seen_goal_states:
                seen_goal_states.add(state_key)
                solutions.append(list(path))
            return math.inf
        if g >= max_depth:
            return math.inf

        expanded += 1
        minimum = math.inf
        children: list[tuple[int, str, CubeState]] = []
        for move in moves:
            if same_face(previous, move):
                continue
            if prune_commuting_moves and _commuting_order_violation(previous, move):
                continue
            child = cube.apply_move(move)
            generated += 1
            if order_children_by_heuristic:
                children.append((h(child), move, child))
            else:
                children.append((0, move, child))
        if order_children_by_heuristic:
            children.sort(key=lambda item: (item[0], item[1]))
        for _, move, child in children:
            path.append(move)
            outcome = search(child, g + 1, bound, move)
            if outcome < minimum:
                minimum = outcome
            path.pop()
            if len(solutions) >= max_solutions or timed_out() or node_budget_exceeded():
                break
        return minimum

    for bound in range(lower_bound, max_depth + 1):
        search(start, 0, bound, None)
        if len(solutions) >= max_solutions or timed_out() or node_budget_exceeded():
            break

    runtime = time.perf_counter() - begin
    if solutions:
        note = "Collected candidate goal paths"
        if len(solutions) >= max_solutions:
            note += "; candidate limit reached"
        elif timed_out():
            note += "; timeout reached after collecting candidates"
        elif node_budget_exceeded():
            note += "; node limit reached after collecting candidates"
        return IDAStarCandidatesResult(
            solutions, expanded, generated, max_depth, "exact", runtime, lower_bound, note,
        )
    if timed_out():
        note = "IDA* candidate collection timed out"
        status = "timeout"
    elif node_budget_exceeded():
        note = "IDA* candidate collection node limit reached"
        # Deliberate conflation: the status enum is pinned by the benchmark
        # schema and saved artifacts (see ida_star_solve); the note string
        # records that the node budget, not the wall clock, was exhausted.
        status = "timeout"
    else:
        note = "No candidate solution within configured depth"
        status = "lower_bound"
    return IDAStarCandidatesResult(
        [], expanded, generated, max_depth, status, runtime, lower_bound, note,
    )

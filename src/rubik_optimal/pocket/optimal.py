"""Complete optimal search utilities for the normalized Pocket Cube."""

from __future__ import annotations

import time
from array import array
from collections import Counter
from dataclasses import dataclass

from rubik_optimal.moves import same_face
from rubik_optimal.pocket.cube import POCKET_MOVES, POCKET_STATE_COUNT, PocketState
from rubik_optimal.pocket.tables import (
    pocket_next_coord,
    pocket_orientation_move_table,
    pocket_permutation_move_table,
)

# Exhaustive distance distribution of the normalized 2x2x2 (Pocket) Cube under
# the half-turn metric, with the DBL corner fixed as the reference cubie. This
# table is produced independently by ``compute_pocket_distribution()`` and is
# frozen here as a regression invariant so that a silent corruption of the
# coordinate encoders or move tables (which could still yield a *complete* and
# internally consistent but wrong distribution) is detected.
#
# Properties locked in by this constant:
#   * the bucket counts sum to 7! * 3^6 = 3,674,160 (the full state space);
#   * the maximum distance is 11 -- consistent with the widely reported 2x2x2
#     God's Number in the half-turn metric (a primary citation is tracked in
#     docs/SOURCES_TO_FETCH.md);
#   * exactly 2,644 states are antipodal (distance 11).
POCKET_DISTANCE_DISTRIBUTION: dict[int, int] = {
    0: 1,
    1: 9,
    2: 54,
    3: 321,
    4: 1847,
    5: 9992,
    6: 50136,
    7: 227536,
    8: 870072,
    9: 1887748,
    10: 623800,
    11: 2644,
}

#: Maximum optimal distance over the whole normalized 2x2x2 state space (HTM).
POCKET_GODS_NUMBER: int = max(POCKET_DISTANCE_DISTRIBUTION)

#: Number of antipodal states (states exactly at ``POCKET_GODS_NUMBER`` moves).
POCKET_ANTIPODE_COUNT: int = POCKET_DISTANCE_DISTRIBUTION[POCKET_GODS_NUMBER]


@dataclass(frozen=True)
class PocketBFSResult:
    distribution: dict[int, int]
    state_count: int
    max_distance: int
    expanded_nodes: int
    generated_nodes: int
    runtime_seconds: float
    complete: bool
    max_depth: int | None


@dataclass(frozen=True)
class PocketTableCheckResult:
    """Outcome of cross-checking the coordinate tables against cubie moves."""

    states_checked: int
    transitions_checked: int
    mismatches: tuple[str, ...]
    max_depth: int | None

    @property
    def ok(self) -> bool:
        return not self.mismatches


def compute_pocket_distribution(max_depth: int | None = None) -> PocketBFSResult:
    """Compute exact distances from solved for the normalized Pocket Cube.

    A breadth-first search over the coordinate move tables fills an exact
    distance for every reachable coordinate (or every coordinate within
    ``max_depth`` when a bound is given). The distance distribution is derived
    once from the filled distance array at the end, which avoids per-edge
    bookkeeping in the hot loop.
    """

    begin = time.perf_counter()
    permutation_table = pocket_permutation_move_table()
    orientation_table = pocket_orientation_move_table()
    orientation_count = len(orientation_table)
    move_count = len(POCKET_MOVES)

    distances = array("b", [-1]) * POCKET_STATE_COUNT
    distances[0] = 0
    queue: list[int] = [0]
    head = 0
    expanded = 0
    generated = 0
    unbounded = max_depth is None
    append = queue.append

    while head < len(queue):
        coord = queue[head]
        head += 1
        depth = distances[coord]
        if not unbounded and depth >= max_depth:
            continue
        expanded += 1
        perm_coord, orient_coord = divmod(coord, orientation_count)
        perm_row = permutation_table[perm_coord]
        orient_row = orientation_table[orient_coord]
        child_depth = depth + 1
        for move_index in range(move_count):
            child = perm_row[move_index] * orientation_count + orient_row[move_index]
            if distances[child] != -1:
                continue
            distances[child] = child_depth
            generated += 1
            append(child)

    counts = Counter(distances)
    counts.pop(-1, None)
    distribution = {int(depth): count for depth, count in sorted(counts.items())}
    max_observed = max(distribution) if distribution else 0
    state_count = sum(distribution.values())
    return PocketBFSResult(
        distribution=distribution,
        state_count=state_count,
        max_distance=max_observed,
        expanded_nodes=expanded,
        generated_nodes=generated,
        runtime_seconds=time.perf_counter() - begin,
        complete=state_count == POCKET_STATE_COUNT,
        max_depth=max_depth,
    )


def verify_pocket_tables_against_cubie_moves(
    max_depth: int | None = 5,
) -> PocketTableCheckResult:
    """Cross-check the coordinate move tables against direct cubie moves.

    The coordinate transition :func:`pocket_next_coord` is built from separate
    permutation and orientation move tables that are combined arithmetically,
    where the orientation table is derived assuming the identity permutation.
    That decomposition is only correct if the orientation transition is
    independent of the permutation. This routine validates that assumption
    empirically: it walks every state reachable within ``max_depth`` (the whole
    space when ``None``) and asserts, for every move, that the table transition
    equals the coordinate obtained from the cubie-level model. It therefore
    proves the tables are faithful to the cube moves rather than merely
    self-consistent.
    """

    distances = array("b", [-1]) * POCKET_STATE_COUNT
    distances[0] = 0
    queue: list[int] = [0]
    head = 0
    states_checked = 0
    transitions_checked = 0
    mismatches: list[str] = []
    unbounded = max_depth is None
    append = queue.append

    while head < len(queue):
        coord = queue[head]
        head += 1
        depth = distances[coord]
        states_checked += 1
        expand = unbounded or depth < max_depth
        cubie = PocketState.from_coord(coord)
        next_depth = depth + 1
        for move_index, move in enumerate(POCKET_MOVES):
            table_child = pocket_next_coord(coord, move_index)
            cubie_child = cubie.apply_move(move).coord()
            transitions_checked += 1
            if table_child != cubie_child and len(mismatches) < 16:
                mismatches.append(
                    f"coord={coord} move={move} table={table_child} cubie={cubie_child}"
                )
            if expand and distances[table_child] == -1:
                distances[table_child] = next_depth
                append(table_child)

    return PocketTableCheckResult(
        states_checked=states_checked,
        transitions_checked=transitions_checked,
        mismatches=tuple(mismatches),
        max_depth=max_depth,
    )


def pocket_optimal_solution(
    start: PocketState,
    *,
    max_depth: int = 14,
) -> tuple[list[str] | None, int, int]:
    """Return an optimal solution for one normalized Pocket Cube state."""

    start_coord = start.coord()
    if start_coord == 0:
        return [], 0, 0

    queue: list[tuple[int, list[str], str | None]] = [(start_coord, [], None)]
    visited = {start_coord}
    head = 0
    expanded = 0
    generated = 0

    while head < len(queue):
        coord, path, previous = queue[head]
        head += 1
        expanded += 1
        if len(path) >= max_depth:
            continue
        for move_index, move in enumerate(POCKET_MOVES):
            if same_face(previous, move):
                continue
            child = pocket_next_coord(coord, move_index)
            if child in visited:
                continue
            generated += 1
            next_path = path + [move]
            if child == 0:
                return next_path, expanded, generated
            visited.add(child)
            queue.append((child, next_path, move))
    return None, expanded, generated

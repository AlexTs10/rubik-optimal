"""Pruning-table generation for coordinate projections."""

from __future__ import annotations

from collections import deque


def build_pruning_table(
    move_table: list[list[int]],
    *,
    solved_coord: int = 0,
) -> list[int]:
    """Return exact distances in a coordinate projection from the solved state."""

    if solved_coord < 0 or solved_coord >= len(move_table):
        raise ValueError(f"Solved coordinate {solved_coord} outside table domain")

    distances = [-1] * len(move_table)
    distances[solved_coord] = 0
    queue: deque[int] = deque([solved_coord])

    while queue:
        coord = queue.popleft()
        next_distance = distances[coord] + 1
        for child in move_table[coord]:
            if distances[child] == -1:
                distances[child] = next_distance
                queue.append(child)

    return distances


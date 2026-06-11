"""Breadth-first exact search for shallow depths."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from rubik_optimal.cube import CubeState
from rubik_optimal.moves import ALL_MOVES, same_face


@dataclass(frozen=True)
class BFSResult:
    solution: list[str] | None
    expanded_nodes: int
    generated_nodes: int
    max_depth: int
    status: str


def bfs_solve(start: CubeState, max_depth: int = 5) -> BFSResult:
    if start.is_solved():
        return BFSResult([], 0, 0, max_depth, "exact")

    queue = deque([(start, [], None)])
    visited = {start}
    expanded = 0
    generated = 0

    while queue:
        cube, path, previous = queue.popleft()
        expanded += 1
        if len(path) >= max_depth:
            continue
        for move in ALL_MOVES:
            if same_face(previous, move):
                continue
            child = cube.apply_move(move)
            if child in visited:
                continue
            generated += 1
            next_path = path + [move]
            if child.is_solved():
                return BFSResult(next_path, expanded, generated, max_depth, "exact")
            visited.add(child)
            queue.append((child, next_path, move))

    return BFSResult(None, expanded, generated, max_depth, "lower_bound")


def exact_distance_bfs(start: CubeState, max_depth: int = 5) -> tuple[int | None, BFSResult]:
    result = bfs_solve(start, max_depth=max_depth)
    if result.solution is None:
        return None, result
    return len(result.solution), result

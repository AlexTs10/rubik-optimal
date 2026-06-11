"""Move-table generation from coordinate projections."""

from __future__ import annotations

from typing import Protocol

from rubik_optimal.cube import CubeState
from rubik_optimal.moves import ALL_MOVES


class CoordinateSpec(Protocol):
    name: str
    domain_size: int
    solved_coord: int
    description: str

    def encode(self, cube: CubeState) -> int:
        ...

    def decode(self, coord: int) -> CubeState:
        ...


def build_move_table(
    spec: CoordinateSpec,
    *,
    moves: tuple[str, ...] = ALL_MOVES,
) -> list[list[int]]:
    """Build a coordinate move table by applying direct cubie moves."""

    table: list[list[int]] = []
    for coord in range(spec.domain_size):
        cube = spec.decode(coord)
        table.append([spec.encode(cube.apply_move(move)) for move in moves])
    return table

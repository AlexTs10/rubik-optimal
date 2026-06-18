"""UD-slice coordinate used by two-phase style search.

The coordinate records which four edge positions contain the middle-slice
edges FR, FL, BL, and BR. The order of those four edge pieces is deliberately
ignored for this phase-1 projection.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

from rubik_optimal.cube import BL, BR, FL, FR, CubeState

SLICE_EDGES = frozenset({FR, FL, BL, BR})
COMBINATIONS = tuple(combinations(range(12), 4))
COMBINATION_TO_COORD = {combo: index for index, combo in enumerate(COMBINATIONS)}
DOMAIN_SIZE = len(COMBINATIONS)
SOLVED_COORD = COMBINATION_TO_COORD[(8, 9, 10, 11)]


def slice_positions(cube: CubeState) -> tuple[int, ...]:
    return tuple(index for index, edge in enumerate(cube.ep) if edge in SLICE_EDGES)


def encode_ud_slice(cube: CubeState) -> int:
    positions = slice_positions(cube)
    if len(positions) != 4:
        raise ValueError(f"Expected exactly four UD-slice edge positions, got {positions}")
    return COMBINATION_TO_COORD[positions]


def decode_ud_slice(coord: int) -> CubeState:
    if coord < 0 or coord >= DOMAIN_SIZE:
        raise ValueError(f"UD-slice coordinate must be in [0, {DOMAIN_SIZE}), got {coord}")

    selected = set(COMBINATIONS[coord])
    slice_edges = [FR, FL, BL, BR]
    other_edges = [edge for edge in range(12) if edge not in SLICE_EDGES]
    ep: list[int] = []
    for position in range(12):
        if position in selected:
            ep.append(slice_edges.pop(0))
        else:
            ep.append(other_edges.pop(0))
    return CubeState(ep=tuple(ep))


@dataclass(frozen=True)
class UDSliceCoordinate:
    name: str = "ud_slice"
    domain_size: int = DOMAIN_SIZE
    solved_coord: int = SOLVED_COORD
    description: str = "C(12, 4) coordinate for the positions of FR, FL, BL, and BR"

    def encode(self, cube: CubeState) -> int:
        return encode_ud_slice(cube)

    def decode(self, coord: int) -> CubeState:
        return decode_ud_slice(coord)


SPEC = UDSliceCoordinate()

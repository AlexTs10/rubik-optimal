"""Edge-permutation coordinate."""

from __future__ import annotations

import math
from dataclasses import dataclass

from rubik_optimal.cube import CubeState
from rubik_optimal.coordinates.permutation import rank_permutation, unrank_permutation

DOMAIN_SIZE = math.factorial(12)


def encode_edge_permutation(cube: CubeState) -> int:
    return rank_permutation(cube.ep)


def decode_edge_permutation(coord: int) -> CubeState:
    return CubeState(ep=unrank_permutation(coord, 12))


@dataclass(frozen=True)
class EdgePermutationCoordinate:
    name: str = "edge_permutation"
    domain_size: int = DOMAIN_SIZE
    solved_coord: int = 0
    description: str = "12! edge-permutation coordinate"

    def encode(self, cube: CubeState) -> int:
        return encode_edge_permutation(cube)

    def decode(self, coord: int) -> CubeState:
        return decode_edge_permutation(coord)


SPEC = EdgePermutationCoordinate()

"""Corner-permutation coordinate."""

from __future__ import annotations

import math
from dataclasses import dataclass

from rubik_optimal.cube import CubeState
from rubik_optimal.coordinates.permutation import rank_permutation, unrank_permutation

DOMAIN_SIZE = math.factorial(8)


def encode_corner_permutation(cube: CubeState) -> int:
    return rank_permutation(cube.cp)


def decode_corner_permutation(coord: int) -> CubeState:
    return CubeState(cp=unrank_permutation(coord, 8))


@dataclass(frozen=True)
class CornerPermutationCoordinate:
    name: str = "corner_permutation"
    domain_size: int = DOMAIN_SIZE
    solved_coord: int = 0
    description: str = "8! corner-permutation coordinate"

    def encode(self, cube: CubeState) -> int:
        return encode_corner_permutation(cube)

    def decode(self, coord: int) -> CubeState:
        return decode_corner_permutation(coord)


SPEC = CornerPermutationCoordinate()

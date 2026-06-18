"""Corner-orientation coordinate.

Only the first seven corner twists are encoded. The eighth twist is implied by
the physical constraint that the total corner orientation sum is divisible by 3.
"""

from __future__ import annotations

from dataclasses import dataclass

from rubik_optimal.cube import CubeState

DOMAIN_SIZE = 3 ** 7


def encode_corner_orientation(cube: CubeState) -> int:
    coord = 0
    for orientation in cube.co[:7]:
        if orientation not in (0, 1, 2):
            raise ValueError(f"Invalid corner orientation value {orientation}")
        coord = coord * 3 + orientation
    return coord


def decode_corner_orientation(coord: int) -> CubeState:
    if coord < 0 or coord >= DOMAIN_SIZE:
        raise ValueError(f"Corner-orientation coordinate must be in [0, {DOMAIN_SIZE}), got {coord}")

    orientations = [0] * 8
    remaining = coord
    for index in range(6, -1, -1):
        orientations[index] = remaining % 3
        remaining //= 3
    orientations[7] = (-sum(orientations[:7])) % 3
    return CubeState(co=tuple(orientations))


@dataclass(frozen=True)
class CornerOrientationCoordinate:
    name: str = "corner_orientation"
    domain_size: int = DOMAIN_SIZE
    solved_coord: int = 0
    description: str = "3^7 corner-orientation coordinate with the final twist implied"

    def encode(self, cube: CubeState) -> int:
        return encode_corner_orientation(cube)

    def decode(self, coord: int) -> CubeState:
        return decode_corner_orientation(coord)


SPEC = CornerOrientationCoordinate()

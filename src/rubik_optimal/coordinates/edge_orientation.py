"""Edge-orientation coordinate.

Only the first eleven edge flips are encoded. The twelfth flip is implied by
the physical constraint that the total edge orientation sum is even.
"""

from __future__ import annotations

from dataclasses import dataclass

from rubik_optimal.cube import CubeState

DOMAIN_SIZE = 2 ** 11


def encode_edge_orientation(cube: CubeState) -> int:
    coord = 0
    for orientation in cube.eo[:11]:
        if orientation not in (0, 1):
            raise ValueError(f"Invalid edge orientation value {orientation}")
        coord = (coord << 1) | orientation
    return coord


def decode_edge_orientation(coord: int) -> CubeState:
    if coord < 0 or coord >= DOMAIN_SIZE:
        raise ValueError(f"Edge-orientation coordinate must be in [0, {DOMAIN_SIZE}), got {coord}")

    orientations = [0] * 12
    remaining = coord
    for index in range(10, -1, -1):
        orientations[index] = remaining & 1
        remaining >>= 1
    orientations[11] = sum(orientations[:11]) % 2
    return CubeState(eo=tuple(orientations))


@dataclass(frozen=True)
class EdgeOrientationCoordinate:
    name: str = "edge_orientation"
    domain_size: int = DOMAIN_SIZE
    solved_coord: int = 0
    description: str = "2^11 edge-orientation coordinate with the final flip implied"

    def encode(self, cube: CubeState) -> int:
        return encode_edge_orientation(cube)

    def decode(self, coord: int) -> CubeState:
        return decode_edge_orientation(coord)


SPEC = EdgeOrientationCoordinate()

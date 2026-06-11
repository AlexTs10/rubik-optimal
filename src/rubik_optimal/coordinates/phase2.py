"""Kociemba phase-2 projection coordinates.

These coordinates are valid for states already in the phase-2 subgroup:
corner and edge orientations are solved, and the four slice edges occupy the
slice positions. The encoders enforce both conditions and raise ``ValueError``
otherwise, so a non-G1 state can never be silently encoded. They deliberately
stay as separate projections, so their pruning tables are small enough for
this thesis repository.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from rubik_optimal.cube import BL, BR, FL, FR, CubeState
from rubik_optimal.coordinates.permutation import rank_permutation, unrank_permutation
from rubik_optimal.moves import PHASE2_MOVES

UD_EDGE_POSITIONS = tuple(range(8))
SLICE_EDGE_POSITIONS = (8, 9, 10, 11)
UD_EDGES = tuple(range(8))
SLICE_EDGES = (FR, FL, BL, BR)

CORNER_PERMUTATION_DOMAIN_SIZE = math.factorial(8)
UD_EDGE_PERMUTATION_DOMAIN_SIZE = math.factorial(8)
SLICE_EDGE_PERMUTATION_DOMAIN_SIZE = math.factorial(4)


def _require_solved_orientations(cube: CubeState) -> None:
    """Reject states outside the phase-2 subgroup by orientation.

    Phase-2 moves cannot change corner/edge orientations, so a state with any
    nonzero co/eo has no phase-2 solution; encoding it anyway would let a
    phase-2 search report a maneuver that does not solve the real cube.  This
    mirrors the existing edge-position guard in :func:`_rank_projected_edges`.
    """

    if any(cube.co) or any(cube.eo):
        raise ValueError(
            "Phase-2 coordinates require solved corner and edge orientations; "
            f"got co={cube.co}, eo={cube.eo}"
        )


def _rank_projected_edges(cube: CubeState, positions: tuple[int, ...], expected_edges: tuple[int, ...]) -> int:
    pieces = tuple(cube.ep[position] for position in positions)
    if sorted(pieces) != sorted(expected_edges):
        raise ValueError(
            f"Phase-2 edge projection expected edges {expected_edges} in positions {positions}, got {pieces}"
        )
    edge_to_index = {edge: index for index, edge in enumerate(expected_edges)}
    return rank_permutation(tuple(edge_to_index[edge] for edge in pieces))


def encode_phase2_corner_permutation(cube: CubeState) -> int:
    _require_solved_orientations(cube)
    return rank_permutation(cube.cp)


def decode_phase2_corner_permutation(coord: int) -> CubeState:
    return CubeState(cp=unrank_permutation(coord, 8))


def encode_phase2_ud_edge_permutation(cube: CubeState) -> int:
    _require_solved_orientations(cube)
    return _rank_projected_edges(cube, UD_EDGE_POSITIONS, UD_EDGES)


def decode_phase2_ud_edge_permutation(coord: int) -> CubeState:
    if coord < 0 or coord >= UD_EDGE_PERMUTATION_DOMAIN_SIZE:
        raise ValueError(
            f"Phase-2 U/D edge permutation must be in [0, {UD_EDGE_PERMUTATION_DOMAIN_SIZE}), got {coord}"
        )
    ep = list(range(12))
    ep[:8] = list(unrank_permutation(coord, 8))
    ep[8:] = list(SLICE_EDGES)
    return CubeState(ep=tuple(ep))


def encode_phase2_slice_edge_permutation(cube: CubeState) -> int:
    _require_solved_orientations(cube)
    return _rank_projected_edges(cube, SLICE_EDGE_POSITIONS, SLICE_EDGES)


def decode_phase2_slice_edge_permutation(coord: int) -> CubeState:
    if coord < 0 or coord >= SLICE_EDGE_PERMUTATION_DOMAIN_SIZE:
        raise ValueError(
            f"Phase-2 slice edge permutation must be in [0, {SLICE_EDGE_PERMUTATION_DOMAIN_SIZE}), got {coord}"
        )
    ep = list(range(12))
    slice_perm = unrank_permutation(coord, 4)
    ep[8:] = [SLICE_EDGES[index] for index in slice_perm]
    return CubeState(ep=tuple(ep))


@dataclass(frozen=True)
class Phase2CornerPermutationCoordinate:
    name: str = "phase2_corner_permutation"
    domain_size: int = CORNER_PERMUTATION_DOMAIN_SIZE
    solved_coord: int = 0
    description: str = "8! corner-permutation projection for Kociemba phase 2"
    moves: tuple[str, ...] = PHASE2_MOVES

    def encode(self, cube: CubeState) -> int:
        return encode_phase2_corner_permutation(cube)

    def decode(self, coord: int) -> CubeState:
        return decode_phase2_corner_permutation(coord)


@dataclass(frozen=True)
class Phase2UDEdgePermutationCoordinate:
    name: str = "phase2_ud_edge_permutation"
    domain_size: int = UD_EDGE_PERMUTATION_DOMAIN_SIZE
    solved_coord: int = 0
    description: str = "8! U/D-edge permutation projection for Kociemba phase 2"
    moves: tuple[str, ...] = PHASE2_MOVES

    def encode(self, cube: CubeState) -> int:
        return encode_phase2_ud_edge_permutation(cube)

    def decode(self, coord: int) -> CubeState:
        return decode_phase2_ud_edge_permutation(coord)


@dataclass(frozen=True)
class Phase2SliceEdgePermutationCoordinate:
    name: str = "phase2_slice_edge_permutation"
    domain_size: int = SLICE_EDGE_PERMUTATION_DOMAIN_SIZE
    solved_coord: int = 0
    description: str = "4! slice-edge permutation projection for Kociemba phase 2"
    moves: tuple[str, ...] = PHASE2_MOVES

    def encode(self, cube: CubeState) -> int:
        return encode_phase2_slice_edge_permutation(cube)

    def decode(self, coord: int) -> CubeState:
        return decode_phase2_slice_edge_permutation(coord)


PHASE2_CORNER_PERMUTATION_SPEC = Phase2CornerPermutationCoordinate()
PHASE2_UD_EDGE_PERMUTATION_SPEC = Phase2UDEdgePermutationCoordinate()
PHASE2_SLICE_EDGE_PERMUTATION_SPEC = Phase2SliceEdgePermutationCoordinate()

PHASE2_MOVE_TABLE_SPECS = (
    PHASE2_CORNER_PERMUTATION_SPEC,
    PHASE2_UD_EDGE_PERMUTATION_SPEC,
    PHASE2_SLICE_EDGE_PERMUTATION_SPEC,
)

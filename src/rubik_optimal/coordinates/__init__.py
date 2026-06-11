"""Coordinate encodings for table-driven Rubik search."""

from rubik_optimal.coordinates.corner_orientation import (
    SPEC as CORNER_ORIENTATION_SPEC,
    decode_corner_orientation,
    encode_corner_orientation,
)
from rubik_optimal.coordinates.corner_permutation import (
    SPEC as CORNER_PERMUTATION_SPEC,
    decode_corner_permutation,
    encode_corner_permutation,
)
from rubik_optimal.coordinates.edge_orientation import (
    SPEC as EDGE_ORIENTATION_SPEC,
    decode_edge_orientation,
    encode_edge_orientation,
)
from rubik_optimal.coordinates.edge_permutation import (
    SPEC as EDGE_PERMUTATION_SPEC,
    decode_edge_permutation,
    encode_edge_permutation,
)
from rubik_optimal.coordinates.phase2 import (
    PHASE2_CORNER_PERMUTATION_SPEC,
    PHASE2_MOVE_TABLE_SPECS,
    PHASE2_SLICE_EDGE_PERMUTATION_SPEC,
    PHASE2_UD_EDGE_PERMUTATION_SPEC,
    decode_phase2_corner_permutation,
    decode_phase2_slice_edge_permutation,
    decode_phase2_ud_edge_permutation,
    encode_phase2_corner_permutation,
    encode_phase2_slice_edge_permutation,
    encode_phase2_ud_edge_permutation,
)
from rubik_optimal.coordinates.ud_slice import (
    SPEC as UD_SLICE_SPEC,
    decode_ud_slice,
    encode_ud_slice,
    slice_positions,
)

MOVE_TABLE_SPECS = (
    CORNER_ORIENTATION_SPEC,
    EDGE_ORIENTATION_SPEC,
    UD_SLICE_SPEC,
)
GENERATED_TABLE_SPECS = MOVE_TABLE_SPECS + PHASE2_MOVE_TABLE_SPECS

__all__ = [
    "CORNER_ORIENTATION_SPEC",
    "EDGE_ORIENTATION_SPEC",
    "CORNER_PERMUTATION_SPEC",
    "EDGE_PERMUTATION_SPEC",
    "UD_SLICE_SPEC",
    "PHASE2_CORNER_PERMUTATION_SPEC",
    "PHASE2_UD_EDGE_PERMUTATION_SPEC",
    "PHASE2_SLICE_EDGE_PERMUTATION_SPEC",
    "MOVE_TABLE_SPECS",
    "PHASE2_MOVE_TABLE_SPECS",
    "GENERATED_TABLE_SPECS",
    "decode_corner_orientation",
    "decode_edge_orientation",
    "decode_corner_permutation",
    "decode_edge_permutation",
    "decode_ud_slice",
    "decode_phase2_corner_permutation",
    "decode_phase2_ud_edge_permutation",
    "decode_phase2_slice_edge_permutation",
    "encode_corner_orientation",
    "encode_edge_orientation",
    "encode_corner_permutation",
    "encode_edge_permutation",
    "encode_ud_slice",
    "encode_phase2_corner_permutation",
    "encode_phase2_ud_edge_permutation",
    "encode_phase2_slice_edge_permutation",
    "slice_positions",
]

from pathlib import Path

from rubik_optimal.coordinates import (
    CORNER_ORIENTATION_SPEC,
    EDGE_ORIENTATION_SPEC,
    GENERATED_TABLE_SPECS,
    MOVE_TABLE_SPECS,
    PHASE2_MOVE_TABLE_SPECS,
    UD_SLICE_SPEC,
    decode_corner_permutation,
    decode_edge_permutation,
    encode_phase2_slice_edge_permutation,
    encode_phase2_ud_edge_permutation,
    encode_corner_permutation,
    encode_edge_permutation,
)
from rubik_optimal.cube import CubeState
from rubik_optimal.moves import ALL_MOVES, PHASE2_MOVES
from rubik_optimal.search.bfs import exact_distance_bfs
from rubik_optimal.search.heuristics import coordinate_pruning_lower_bound, kociemba_phase2_lower_bound
from rubik_optimal.tables.generation import generate_coordinate_tables
from rubik_optimal.tables.metadata import sha256_file
from rubik_optimal.tables.move_tables import build_move_table
from rubik_optimal.tables.pruning_tables import build_pruning_table


def test_orientation_and_slice_coordinates_roundtrip():
    cases = [
        CubeState.solved(),
        CubeState.from_sequence("R U F"),
        CubeState.from_sequence("F R U R' U' F'"),
        CubeState.from_sequence("R2 F B' L D2 U"),
    ]
    for cube in cases:
        for spec in MOVE_TABLE_SPECS:
            coord = spec.encode(cube)
            decoded = spec.decode(coord)
            assert spec.encode(decoded) == coord

    assert CORNER_ORIENTATION_SPEC.solved_coord == CORNER_ORIENTATION_SPEC.encode(CubeState.solved())
    assert EDGE_ORIENTATION_SPEC.solved_coord == EDGE_ORIENTATION_SPEC.encode(CubeState.solved())
    assert UD_SLICE_SPEC.solved_coord == UD_SLICE_SPEC.encode(CubeState.solved())


def test_permutation_coordinates_roundtrip():
    cube = CubeState.from_sequence("R U F2 L D")

    corner_coord = encode_corner_permutation(cube)
    assert encode_corner_permutation(decode_corner_permutation(corner_coord)) == corner_coord

    edge_coord = encode_edge_permutation(cube)
    assert encode_edge_permutation(decode_edge_permutation(edge_coord)) == edge_coord


def test_generated_move_tables_match_direct_cubie_moves():
    for spec in MOVE_TABLE_SPECS:
        table = build_move_table(spec)
        sample_coords = {spec.solved_coord, spec.domain_size // 3, spec.domain_size - 1}
        for coord in sample_coords:
            cube = spec.decode(coord)
            for move_index, move in enumerate(ALL_MOVES):
                assert table[coord][move_index] == spec.encode(cube.apply_move(move))


def test_phase2_projection_tables_match_restricted_moves():
    for spec in PHASE2_MOVE_TABLE_SPECS:
        table = build_move_table(spec, moves=PHASE2_MOVES)
        sample_coords = {spec.solved_coord, spec.domain_size // 3, spec.domain_size - 1}
        for coord in sample_coords:
            cube = spec.decode(coord)
            for move_index, move in enumerate(PHASE2_MOVES):
                assert table[coord][move_index] == spec.encode(cube.apply_move(move))


def test_phase2_coordinates_require_phase2_subgroup_edges():
    non_phase2_cube = CubeState.from_sequence("R")
    for encoder in (encode_phase2_ud_edge_permutation, encode_phase2_slice_edge_permutation):
        try:
            encoder(non_phase2_cube)
        except ValueError:
            pass
        else:  # pragma: no cover - assertion branch
            raise AssertionError("phase-2 edge coordinate accepted a non-phase-2 edge placement")


def test_pruning_tables_have_solved_distance_zero_and_one_move_distance_one():
    for spec in MOVE_TABLE_SPECS:
        move_table = build_move_table(spec)
        pruning = build_pruning_table(move_table, solved_coord=spec.solved_coord)
        assert pruning[spec.solved_coord] == 0
        for move_index, move in enumerate(ALL_MOVES):
            coord = spec.encode(CubeState.solved().apply_move(move))
            if coord != spec.solved_coord:
                assert pruning[coord] == 1, (spec.name, move, move_index)


def test_coordinate_pruning_heuristic_is_admissible_on_shallow_cases():
    for sequence in ["", "R", "R U", "F R U", "R U R' U'"]:
        cube = CubeState.from_sequence(sequence)
        distance, _ = exact_distance_bfs(cube, max_depth=5)
        assert distance is not None
        assert coordinate_pruning_lower_bound(cube) <= distance


def test_phase2_pruning_heuristic_is_admissible_for_restricted_sequences():
    for sequence in ["", "U", "U R2", "R2 U D'", "F2 U R2 D"]:
        cube = CubeState.from_sequence(sequence)
        assert kociemba_phase2_lower_bound(cube) <= len(sequence.split())


def test_generate_coordinate_tables_writes_metadata_and_checksums(tmp_path: Path):
    manifest = generate_coordinate_tables(root=tmp_path, profile="quick", seed=2026)
    manifest_path = tmp_path / manifest["manifest"]
    metadata_path = tmp_path / manifest["metadata"]
    assert manifest_path.exists()
    assert metadata_path.exists()
    assert len(manifest["tables"]) == len(GENERATED_TABLE_SPECS) * 2

    for row in manifest["tables"]:
        table_path = tmp_path / str(row["file_path"])
        assert table_path.exists()
        assert row["checksum_sha256"] == sha256_file(table_path)
        assert row["size_bytes"] == table_path.stat().st_size

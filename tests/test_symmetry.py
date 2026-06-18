from rubik_optimal.cube import CubeState
from rubik_optimal.moves import ALL_MOVES, parse_sequence
from rubik_optimal.symmetry import (
    CUBE_ROTATIONS,
    CUBE_SYMMETRIES,
    g1_preserving_symmetries,
    root_g1_preserving_symmetry_representative_moves,
    root_symmetry_representative_moves,
    stabilizing_rotations,
    stabilizing_symmetries,
)
from rubik_optimal.verify import verify_solution


def test_cube_rotations_form_24_solved_preserving_automorphisms():
    assert len(CUBE_ROTATIONS) == 24
    solved = CubeState.solved()
    sample = CubeState.from_sequence("R U F2 L' D")

    for rotation in CUBE_ROTATIONS:
        assert rotation.transform_cube(solved) == solved
        assert rotation.transform_cube(sample).is_valid()
        for move in ALL_MOVES:
            assert rotation.transform_cube(sample.apply_move(move)) == rotation.transform_cube(sample).apply_move(
                rotation.transform_move(move)
            )


def test_cube_symmetries_form_48_solved_preserving_automorphisms():
    assert len(CUBE_SYMMETRIES) == 48
    solved = CubeState.solved()
    sample = CubeState.from_sequence("R U F2 L' D B")

    for symmetry in CUBE_SYMMETRIES:
        assert symmetry.transform_cube(solved) == solved
        assert symmetry.transform_cube(sample).is_valid()
        for move in ALL_MOVES:
            assert symmetry.transform_cube(sample.apply_move(move)) == symmetry.transform_cube(sample).apply_move(
                symmetry.transform_move(move)
            )


def test_rotated_solution_solves_rotated_state():
    cube = CubeState.from_sequence("R U F2")
    solution = ["F2", "U'", "R'"]

    for rotation in CUBE_ROTATIONS:
        rotated_cube = rotation.transform_cube(cube)
        rotated_solution = rotation.transform_sequence(solution)
        verification = verify_solution(rotated_cube, rotated_solution)
        assert verification.ok


def test_rotation_sequence_mapping_is_invertible():
    sequence = parse_sequence("R U F2 L' D B2")

    for rotation in CUBE_ROTATIONS:
        rotated = rotation.transform_sequence(sequence)
        assert rotation.inverse_transform_sequence(rotated) == sequence


def test_superflip_root_symmetry_representatives_collapse_first_moves():
    superflip = CubeState(cp=tuple(range(8)), co=(0,) * 8, ep=tuple(range(12)), eo=(1,) * 12)

    assert len(stabilizing_rotations(superflip)) == 24
    assert len(stabilizing_symmetries(superflip)) == 48
    assert root_symmetry_representative_moves(superflip) == ("U", "U2")


def test_superflip_g1_preserving_root_representatives_keep_kociemba_axis_safe():
    superflip = CubeState(cp=tuple(range(8)), co=(0,) * 8, ep=tuple(range(12)), eo=(1,) * 12)

    assert len(g1_preserving_symmetries()) == 16
    assert root_g1_preserving_symmetry_representative_moves(superflip) == ("U", "U2", "R", "R2")


def test_asymmetric_state_keeps_all_root_moves():
    cube = CubeState.from_sequence("R U F2 L' D")

    assert len(stabilizing_rotations(cube)) == 1
    assert root_symmetry_representative_moves(cube) == ALL_MOVES
    assert root_g1_preserving_symmetry_representative_moves(cube) == ALL_MOVES


def test_partially_symmetric_state_uses_one_representative_per_orbit():
    cube = CubeState.from_sequence("U2 D2")

    assert len(stabilizing_rotations(cube)) == 8
    assert len(stabilizing_symmetries(cube)) == 16
    assert root_symmetry_representative_moves(cube) == ("U", "U2", "R", "R2")

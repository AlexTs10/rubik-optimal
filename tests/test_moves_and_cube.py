import pytest

from rubik_optimal.cube import CubeState
from rubik_optimal.moves import ALL_MOVES, inverse_sequence, parse_sequence
from rubik_optimal.scramble import deterministic_scramble


def test_identity_cube_is_valid_and_solved():
    cube = CubeState.solved()
    assert cube.is_solved()
    assert cube.is_valid()
    assert CubeState.from_facelets(cube.to_facelets()) == cube


@pytest.mark.parametrize(
    "sequence",
    [
        "",
        "R U F2",
        "L D2 B' R2 U",
        " ".join(deterministic_scramble(20, seed=2026)),
    ],
)
def test_legal_facelet_strings_round_trip_to_same_cubie_state(sequence):
    cube = CubeState.from_sequence(sequence)
    assert CubeState.from_facelets(cube.to_facelets()) == cube


@pytest.mark.parametrize(
    "facelets",
    [
        # Count-valid but fixed-center-invalid input.
        "UUUURUUUURRRRURRRRFFFFFFFFFDDDDDDDDDLLLLLLLLLBBBBBBBBB",
        # Count-valid stickers with a corner triple that cannot be a legal cubie.
        "DUUUUUUUURRRRRRRRRFFFFFFFFFUDDDDDDDDLLLLLLLLLBBBBBBBBB",
        # Count-valid stickers with no U/D sticker in the URF corner.
        "RUUUUUUUURRRRRRRRFFFFFFFFFDDDDDDDDDLLLLLLLLLBBBBBBBBB",
    ],
)
def test_facelet_parser_rejects_malformed_count_valid_states(facelets):
    with pytest.raises(ValueError):
        CubeState.from_facelets(facelets)


@pytest.mark.parametrize("move", ALL_MOVES)
def test_each_move_followed_by_inverse_returns_identity(move):
    cube = CubeState.solved().apply_sequence([move] + inverse_sequence([move]))
    assert cube.is_solved()


@pytest.mark.parametrize("face", ["U", "R", "F", "D", "L", "B"])
def test_four_quarter_turns_return_identity(face):
    assert CubeState.solved().apply_sequence([face, face, face, face]).is_solved()


@pytest.mark.parametrize("face", ["U", "R", "F", "D", "L", "B"])
def test_half_turn_equals_two_quarter_turns(face):
    assert CubeState.solved().apply_sequence([face, face]) == CubeState.solved().apply_move(f"{face}2")


def test_legal_and_illegal_move_parsing():
    assert parse_sequence("U R2 F'") == ["U", "R2", "F'"]
    with pytest.raises(ValueError):
        parse_sequence("U M")


def test_scramble_followed_by_inverse_returns_solved():
    scramble = deterministic_scramble(20, seed=2026)
    cube = CubeState.solved().apply_sequence(scramble).apply_sequence(inverse_sequence(scramble))
    assert cube.is_solved()


def test_deterministic_scramble_rejects_negative_length():
    with pytest.raises(ValueError, match="non-negative"):
        deterministic_scramble(-1, seed=2026)


def test_cube_validity_rejects_bad_edge_flip():
    cube = CubeState(eo=(1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0))
    ok, message = cube.verify_physical()
    assert ok == -3
    assert "flip" in message.lower()


def test_cube_validity_rejects_bad_corner_twist():
    cube = CubeState(co=(1, 0, 0, 0, 0, 0, 0, 0))
    ok, message = cube.verify_physical()
    assert ok == -5
    assert "twist" in message.lower()


def test_cube_validity_rejects_parity_mismatch():
    cube = CubeState(cp=(1, 0, 2, 3, 4, 5, 6, 7))
    ok, message = cube.verify_physical()
    assert ok == -6
    assert "parity" in message.lower()

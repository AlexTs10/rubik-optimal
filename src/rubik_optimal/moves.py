"""Move notation utilities for the face-turn / half-turn metric."""

from __future__ import annotations

from dataclasses import dataclass

FACES = ("U", "R", "F", "D", "L", "B")
SUFFIXES = ("", "'", "2")
ALL_MOVES = tuple(f"{face}{suffix}" for face in FACES for suffix in SUFFIXES)
PHASE2_MOVES = ("U", "U'", "U2", "D", "D'", "D2", "R2", "L2", "F2", "B2")
MOVE_TO_FACE_TURNS = {
    move: (move[0], 2 if move.endswith("2") else 3 if move.endswith("'") else 1)
    for move in ALL_MOVES
}


@dataclass(frozen=True)
class Move:
    token: str
    face: str
    quarter_turns: int


def parse_move(token: str) -> Move:
    token = token.strip()
    if token not in MOVE_TO_FACE_TURNS:
        allowed = " ".join(ALL_MOVES)
        raise ValueError(f"Illegal move {token!r}; allowed moves: {allowed}")
    face, turns = MOVE_TO_FACE_TURNS[token]
    return Move(token=token, face=face, quarter_turns=turns)


def parse_sequence(sequence: str | list[str] | tuple[str, ...]) -> list[str]:
    if isinstance(sequence, str):
        text = sequence.strip()
        if not text:
            return []
        tokens = text.split()
    else:
        tokens = list(sequence)
    return [parse_move(token).token for token in tokens]


def inverse_move(token: str) -> str:
    parse_move(token)
    if token.endswith("2"):
        return token
    if token.endswith("'"):
        return token[:-1]
    return f"{token}'"


def inverse_sequence(sequence: str | list[str] | tuple[str, ...]) -> list[str]:
    return [inverse_move(token) for token in reversed(parse_sequence(sequence))]


def half_turn_length(sequence: str | list[str] | tuple[str, ...]) -> int:
    return len(parse_sequence(sequence))


def same_face(a: str | None, b: str) -> bool:
    return a is not None and a[0] == b[0]

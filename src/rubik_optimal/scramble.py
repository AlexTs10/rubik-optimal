"""Deterministic scramble generation."""

from __future__ import annotations

import random

from .moves import ALL_MOVES


def deterministic_scramble(length: int, seed: int, *, offset: int = 0) -> list[str]:
    if length < 0:
        raise ValueError("Scramble length must be non-negative")
    rng = random.Random((seed, length, offset).__repr__())
    moves: list[str] = []
    previous_face: str | None = None
    while len(moves) < length:
        move = rng.choice(ALL_MOVES)
        if previous_face == move[0]:
            continue
        moves.append(move)
        previous_face = move[0]
    return moves

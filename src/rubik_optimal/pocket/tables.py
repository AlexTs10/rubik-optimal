"""Small coordinate move tables for the normalized Pocket Cube."""

from __future__ import annotations

from functools import lru_cache

from rubik_optimal.pocket.cube import (
    ORIENTATION_COUNT,
    PERMUTATION_COUNT,
    POCKET_MOVES,
    PocketState,
)


@lru_cache(maxsize=1)
def pocket_permutation_move_table() -> tuple[tuple[int, ...], ...]:
    rows: list[tuple[int, ...]] = []
    for perm_coord in range(PERMUTATION_COUNT):
        state = PocketState.from_coord(perm_coord * ORIENTATION_COUNT)
        rows.append(
            tuple(
                state.apply_move(move).coord() // ORIENTATION_COUNT
                for move in POCKET_MOVES
            )
        )
    return tuple(rows)


@lru_cache(maxsize=1)
def pocket_orientation_move_table() -> tuple[tuple[int, ...], ...]:
    rows: list[tuple[int, ...]] = []
    for orient_coord in range(ORIENTATION_COUNT):
        state = PocketState.from_coord(orient_coord)
        rows.append(
            tuple(
                state.apply_move(move).coord() % ORIENTATION_COUNT
                for move in POCKET_MOVES
            )
        )
    return tuple(rows)


def pocket_next_coord(coord: int, move_index: int) -> int:
    perm_coord, orient_coord = divmod(coord, ORIENTATION_COUNT)
    next_perm = pocket_permutation_move_table()[perm_coord][move_index]
    next_orient = pocket_orientation_move_table()[orient_coord][move_index]
    return next_perm * ORIENTATION_COUNT + next_orient


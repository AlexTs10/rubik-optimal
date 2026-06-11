"""Normalized 2x2x2/Pocket Cube state model.

The model fixes the DBL corner as the reference cubie. This removes the 24
global cube orientations and yields the canonical 7! * 3^6 state space used for
the complete case study.
"""

from __future__ import annotations

from dataclasses import dataclass

from rubik_optimal.coordinates.permutation import rank_permutation, unrank_permutation
from rubik_optimal.cube import DBL, CubeState

POCKET_POSITIONS = (0, 1, 2, 3, 4, 5, 7)
POCKET_CUBIES = (0, 1, 2, 3, 4, 5, 7)
LOCAL_CUBIE = {cubie: index for index, cubie in enumerate(POCKET_CUBIES)}
GLOBAL_CUBIE = {index: cubie for index, cubie in enumerate(POCKET_CUBIES)}
POCKET_MOVES = ("U", "U'", "U2", "R", "R'", "R2", "F", "F'", "F2")
ORIENTATION_COUNT = 3 ** 6
PERMUTATION_COUNT = 5040
POCKET_STATE_COUNT = PERMUTATION_COUNT * ORIENTATION_COUNT


def _rank_orientation(co: tuple[int, ...]) -> int:
    coord = 0
    for orientation in co[:6]:
        if orientation not in (0, 1, 2):
            raise ValueError(f"Invalid corner orientation value {orientation}")
        coord = coord * 3 + orientation
    if sum(co) % 3 != 0:
        raise ValueError(f"Pocket corner orientations must sum to 0 modulo 3, got {co}")
    return coord


def _unrank_orientation(coord: int) -> tuple[int, ...]:
    if coord < 0 or coord >= ORIENTATION_COUNT:
        raise ValueError(f"Orientation coordinate must be in [0, {ORIENTATION_COUNT}), got {coord}")

    orientations = [0] * 7
    remaining = coord
    for index in range(5, -1, -1):
        orientations[index] = remaining % 3
        remaining //= 3
    orientations[6] = (-sum(orientations[:6])) % 3
    return tuple(orientations)


@dataclass(frozen=True, slots=True)
class PocketState:
    cp: tuple[int, ...] = POCKET_CUBIES
    co: tuple[int, ...] = (0, 0, 0, 0, 0, 0, 0)

    @classmethod
    def solved(cls) -> "PocketState":
        return cls()

    @classmethod
    def from_sequence(cls, sequence: str | list[str] | tuple[str, ...]) -> "PocketState":
        state = cls.solved()
        tokens = sequence.split() if isinstance(sequence, str) else list(sequence)
        for token in tokens:
            state = state.apply_move(token)
        return state

    @classmethod
    def from_cube(cls, cube: CubeState) -> "PocketState":
        if cube.cp[DBL] != DBL or cube.co[DBL] != 0:
            raise ValueError("PocketState projection requires the DBL reference corner fixed")
        cp = tuple(cube.cp[position] for position in POCKET_POSITIONS)
        co = tuple(cube.co[position] for position in POCKET_POSITIONS)
        state = cls(cp=cp, co=co)
        state.validate()
        return state

    @classmethod
    def from_coord(cls, coord: int) -> "PocketState":
        if coord < 0 or coord >= POCKET_STATE_COUNT:
            raise ValueError(f"Pocket coordinate must be in [0, {POCKET_STATE_COUNT}), got {coord}")
        perm_coord, orient_coord = divmod(coord, ORIENTATION_COUNT)
        local_perm = unrank_permutation(perm_coord, 7)
        cp = tuple(GLOBAL_CUBIE[index] for index in local_perm)
        co = _unrank_orientation(orient_coord)
        return cls(cp=cp, co=co)

    def validate(self) -> None:
        if len(self.cp) != 7 or len(self.co) != 7:
            raise ValueError("PocketState must contain seven non-reference corners")
        if sorted(self.cp) != list(POCKET_CUBIES):
            raise ValueError(f"PocketState corner permutation must contain {POCKET_CUBIES}, got {self.cp}")
        if any(orientation not in (0, 1, 2) for orientation in self.co):
            raise ValueError(f"PocketState orientations must be 0, 1, or 2, got {self.co}")
        if sum(self.co) % 3 != 0:
            raise ValueError(f"PocketState orientation sum must be 0 modulo 3, got {self.co}")

    def to_cube(self) -> CubeState:
        cp = list(range(8))
        co = [0] * 8
        for local_index, position in enumerate(POCKET_POSITIONS):
            cp[position] = self.cp[local_index]
            co[position] = self.co[local_index]
        cp[DBL] = DBL
        co[DBL] = 0
        return CubeState(cp=tuple(cp), co=tuple(co))

    def apply_move(self, token: str) -> "PocketState":
        if token not in POCKET_MOVES:
            raise ValueError(f"Pocket move must be one of {' '.join(POCKET_MOVES)}, got {token!r}")
        return PocketState.from_cube(self.to_cube().apply_move(token))

    def apply_sequence(self, sequence: str | list[str] | tuple[str, ...]) -> "PocketState":
        state = self
        tokens = sequence.split() if isinstance(sequence, str) else list(sequence)
        for token in tokens:
            state = state.apply_move(token)
        return state

    def is_solved(self) -> bool:
        return self == PocketState.solved()

    def coord(self) -> int:
        local_perm = tuple(LOCAL_CUBIE[cubie] for cubie in self.cp)
        return rank_permutation(local_perm) * ORIENTATION_COUNT + _rank_orientation(self.co)


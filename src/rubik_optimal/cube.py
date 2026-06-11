"""Cubie-level 3x3 Rubik's Cube representation.

The cubie order follows the common two-phase convention:
corners URF, UFL, ULB, UBR, DFR, DLF, DBL, DRB and edges
UR, UF, UL, UB, DR, DF, DL, DB, FR, FL, BL, BR.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .moves import MOVE_TO_FACE_TURNS, parse_move, parse_sequence

CORNER_NAMES = ("URF", "UFL", "ULB", "UBR", "DFR", "DLF", "DBL", "DRB")
EDGE_NAMES = ("UR", "UF", "UL", "UB", "DR", "DF", "DL", "DB", "FR", "FL", "BL", "BR")

URF, UFL, ULB, UBR, DFR, DLF, DBL, DRB = range(8)
UR, UF, UL, UB, DR, DF, DL, DB, FR, FL, BL, BR = range(12)

SOLVED_FACELETS = "UUUUUUUUURRRRRRRRRFFFFFFFFFDDDDDDDDDLLLLLLLLLBBBBBBBBB"
FACE_CENTER_INDICES = {"U": 4, "R": 13, "F": 22, "D": 31, "L": 40, "B": 49}

CORNER_FACELETS = (
    (8, 9, 20), (6, 18, 38), (0, 36, 47), (2, 45, 11),
    (29, 26, 15), (27, 44, 24), (33, 53, 42), (35, 17, 51),
)
EDGE_FACELETS = (
    (5, 10), (7, 19), (3, 37), (1, 46), (32, 16), (28, 25),
    (30, 43), (34, 52), (23, 12), (21, 41), (50, 39), (48, 14),
)
CORNER_COLORS = (
    ("U", "R", "F"), ("U", "F", "L"), ("U", "L", "B"), ("U", "B", "R"),
    ("D", "F", "R"), ("D", "L", "F"), ("D", "B", "L"), ("D", "R", "B"),
)
EDGE_COLORS = (
    ("U", "R"), ("U", "F"), ("U", "L"), ("U", "B"), ("D", "R"), ("D", "F"),
    ("D", "L"), ("D", "B"), ("F", "R"), ("F", "L"), ("B", "L"), ("B", "R"),
)


@dataclass(frozen=True)
class MoveCube:
    cp: tuple[int, ...]
    co: tuple[int, ...]
    ep: tuple[int, ...]
    eo: tuple[int, ...]


BASE_MOVES: dict[str, MoveCube] = {
    "U": MoveCube(
        cp=(UBR, URF, UFL, ULB, DFR, DLF, DBL, DRB),
        co=(0, 0, 0, 0, 0, 0, 0, 0),
        ep=(UB, UR, UF, UL, DR, DF, DL, DB, FR, FL, BL, BR),
        eo=(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
    ),
    "R": MoveCube(
        cp=(DFR, UFL, ULB, URF, DRB, DLF, DBL, UBR),
        co=(2, 0, 0, 1, 1, 0, 0, 2),
        ep=(FR, UF, UL, UB, BR, DF, DL, DB, DR, FL, BL, UR),
        eo=(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
    ),
    "F": MoveCube(
        cp=(UFL, DLF, ULB, UBR, URF, DFR, DBL, DRB),
        co=(1, 2, 0, 0, 2, 1, 0, 0),
        ep=(UR, FL, UL, UB, DR, FR, DL, DB, UF, DF, BL, BR),
        eo=(0, 1, 0, 0, 0, 1, 0, 0, 1, 1, 0, 0),
    ),
    "D": MoveCube(
        cp=(URF, UFL, ULB, UBR, DLF, DBL, DRB, DFR),
        co=(0, 0, 0, 0, 0, 0, 0, 0),
        ep=(UR, UF, UL, UB, DF, DL, DB, DR, FR, FL, BL, BR),
        eo=(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
    ),
    "L": MoveCube(
        cp=(URF, ULB, DBL, UBR, DFR, UFL, DLF, DRB),
        co=(0, 1, 2, 0, 0, 2, 1, 0),
        ep=(UR, UF, BL, UB, DR, DF, FL, DB, FR, UL, DL, BR),
        eo=(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
    ),
    "B": MoveCube(
        cp=(URF, UFL, UBR, DRB, DFR, DLF, ULB, DBL),
        co=(0, 0, 1, 2, 0, 0, 2, 1),
        ep=(UR, UF, UL, BR, DR, DF, DL, BL, FR, FL, UB, DB),
        eo=(0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 1, 1),
    ),
}


def _parity(values: Iterable[int]) -> int:
    items = list(values)
    inversions = 0
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            inversions += items[i] > items[j]
    return inversions % 2


@dataclass(frozen=True, slots=True)
class CubeState:
    cp: tuple[int, ...] = tuple(range(8))
    co: tuple[int, ...] = (0, 0, 0, 0, 0, 0, 0, 0)
    ep: tuple[int, ...] = tuple(range(12))
    eo: tuple[int, ...] = (0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)

    @classmethod
    def solved(cls) -> "CubeState":
        return cls()

    @classmethod
    def from_sequence(cls, sequence: str | list[str] | tuple[str, ...]) -> "CubeState":
        return cls.solved().apply_sequence(sequence)

    @classmethod
    def from_facelets(cls, facelets: str) -> "CubeState":
        if len(facelets) != 54:
            raise ValueError("A facelet cube must contain exactly 54 facelets")
        if set(facelets) - set("URFDLB"):
            raise ValueError("Facelets must use only U, R, F, D, L, B")
        counts = {color: facelets.count(color) for color in "URFDLB"}
        if any(count != 9 for count in counts.values()):
            raise ValueError(f"Each color must occur exactly 9 times, got {counts}")
        bad_centers = {
            color: facelets[index]
            for color, index in FACE_CENTER_INDICES.items()
            if facelets[index] != color
        }
        if bad_centers:
            raise ValueError(f"Facelet centers must be fixed URFDLB, got {bad_centers}")

        cp = [URF] * 8
        co = [0] * 8
        ep = [UR] * 12
        eo = [0] * 12

        for pos in range(8):
            corner_stickers = tuple(facelets[index] for index in CORNER_FACELETS[pos])
            ori = next((idx for idx, color in enumerate(corner_stickers) if color in ("U", "D")), None)
            if ori is None:
                raise ValueError(
                    f"Corner position {CORNER_NAMES[pos]} has no U/D sticker: {corner_stickers}"
                )
            col1 = facelets[CORNER_FACELETS[pos][(ori + 1) % 3]]
            col2 = facelets[CORNER_FACELETS[pos][(ori + 2) % 3]]
            matched = False
            for cubie in range(8):
                if col1 == CORNER_COLORS[cubie][1] and col2 == CORNER_COLORS[cubie][2]:
                    cp[pos] = cubie
                    co[pos] = ori % 3
                    matched = True
                    break
            if not matched:
                raise ValueError(
                    f"Corner stickers at {CORNER_NAMES[pos]} do not match a legal cubie: "
                    f"{corner_stickers}"
                )

        for pos in range(12):
            a = facelets[EDGE_FACELETS[pos][0]]
            b = facelets[EDGE_FACELETS[pos][1]]
            matched = False
            for cubie in range(12):
                if (a, b) == EDGE_COLORS[cubie]:
                    ep[pos] = cubie
                    eo[pos] = 0
                    matched = True
                    break
                if (a, b) == (EDGE_COLORS[cubie][1], EDGE_COLORS[cubie][0]):
                    ep[pos] = cubie
                    eo[pos] = 1
                    matched = True
                    break
            if not matched:
                raise ValueError(
                    f"Edge stickers at {EDGE_NAMES[pos]} do not match a legal cubie: {(a, b)}"
                )

        cube = cls(tuple(cp), tuple(co), tuple(ep), tuple(eo))
        code, message = cube.verify_physical()
        if code != 0:
            raise ValueError(message)
        if cube.to_facelets() != facelets:
            raise ValueError("Facelets do not describe a canonical reachable sticker state")
        return cube

    @classmethod
    def from_text(cls, text: str) -> "CubeState":
        text = text.strip()
        if text == "" or text.lower() == "solved":
            return cls.solved()
        compact = "".join(text.split())
        if len(compact) == 54 and set(compact) <= set("URFDLB"):
            return cls.from_facelets(compact)
        return cls.from_sequence(text)

    def apply_base(self, face: str) -> "CubeState":
        move = BASE_MOVES[face]
        cp = tuple(self.cp[move.cp[i]] for i in range(8))
        co = tuple((self.co[move.cp[i]] + move.co[i]) % 3 for i in range(8))
        ep = tuple(self.ep[move.ep[i]] for i in range(12))
        eo = tuple((self.eo[move.ep[i]] + move.eo[i]) % 2 for i in range(12))
        return CubeState(cp=cp, co=co, ep=ep, eo=eo)

    def apply_move(self, token: str) -> "CubeState":
        move = parse_move(token)
        cube = self
        for _ in range(move.quarter_turns):
            cube = cube.apply_base(move.face)
        return cube

    def apply_sequence(self, sequence: str | list[str] | tuple[str, ...]) -> "CubeState":
        cube = self
        for token in parse_sequence(sequence):
            cube = cube.apply_move(token)
        return cube

    def is_solved(self) -> bool:
        return self == CubeState.solved()

    def to_facelets(self) -> str:
        facelets = list(SOLVED_FACELETS)
        for pos in range(8):
            cubie = self.cp[pos]
            ori = self.co[pos]
            for n in range(3):
                facelets[CORNER_FACELETS[pos][(n + ori) % 3]] = CORNER_COLORS[cubie][n]
        for pos in range(12):
            cubie = self.ep[pos]
            ori = self.eo[pos]
            for n in range(2):
                facelets[EDGE_FACELETS[pos][(n + ori) % 2]] = EDGE_COLORS[cubie][n]
        return "".join(facelets)

    def verify_physical(self) -> tuple[int, str]:
        if len(self.cp) != 8 or len(self.co) != 8 or len(self.ep) != 12 or len(self.eo) != 12:
            return -1, "Invalid cubie vector lengths"
        if sorted(self.ep) != list(range(12)):
            return -2, "Not all 12 edges exist exactly once"
        if any(ori not in (0, 1) for ori in self.eo) or sum(self.eo) % 2 != 0:
            return -3, "Edge flip parity is invalid"
        if sorted(self.cp) != list(range(8)):
            return -4, "Not all 8 corners exist exactly once"
        if any(ori not in (0, 1, 2) for ori in self.co) or sum(self.co) % 3 != 0:
            return -5, "Corner twist parity is invalid"
        if _parity(self.cp) != _parity(self.ep):
            return -6, "Corner and edge permutation parity differ"
        return 0, "Cube is physically solvable"

    def is_valid(self) -> bool:
        return self.verify_physical()[0] == 0

    def compact(self) -> str:
        return self.to_facelets()

    def __str__(self) -> str:
        return self.to_facelets()


def move_count(sequence: str | list[str] | tuple[str, ...]) -> int:
    return len(parse_sequence(sequence))


def face_of(token: str) -> str:
    return MOVE_TO_FACE_TURNS[parse_move(token).token][0]

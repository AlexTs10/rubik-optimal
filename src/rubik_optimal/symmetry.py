"""Whole-cube rotational symmetries for exact 3x3 certificate reuse."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import permutations, product

from .cube import CubeState
from .moves import ALL_MOVES, parse_sequence

Vector = tuple[int, int, int]
Matrix = tuple[Vector, Vector, Vector]

NORMAL_BY_FACE: dict[str, Vector] = {
    "U": (0, 1, 0),
    "R": (1, 0, 0),
    "F": (0, 0, 1),
    "D": (0, -1, 0),
    "L": (-1, 0, 0),
    "B": (0, 0, -1),
}
FACE_BY_NORMAL = {normal: face for face, normal in NORMAL_BY_FACE.items()}


def _facelet_geometry() -> tuple[dict[int, tuple[Vector, Vector]], dict[tuple[Vector, Vector], int]]:
    index_to_geometry: dict[int, tuple[Vector, Vector]] = {}
    geometry_to_index: dict[tuple[Vector, Vector], int] = {}

    def add_grid(
        *,
        start: int,
        normal: Vector,
        rows: tuple[int, int, int],
        cols: tuple[int, int, int],
        constant_axis: int,
        row_axis: int,
        col_axis: int,
        constant_value: int,
    ) -> None:
        for row_index, row_value in enumerate(rows):
            for col_index, col_value in enumerate(cols):
                position = [0, 0, 0]
                position[constant_axis] = constant_value
                position[row_axis] = row_value
                position[col_axis] = col_value
                index = start + row_index * 3 + col_index
                key = (tuple(position), normal)  # type: ignore[arg-type]
                index_to_geometry[index] = key
                geometry_to_index[key] = index

    add_grid(start=0, normal=NORMAL_BY_FACE["U"], rows=(-1, 0, 1), cols=(-1, 0, 1), constant_axis=1, row_axis=2, col_axis=0, constant_value=1)
    add_grid(start=9, normal=NORMAL_BY_FACE["R"], rows=(1, 0, -1), cols=(1, 0, -1), constant_axis=0, row_axis=1, col_axis=2, constant_value=1)
    add_grid(start=18, normal=NORMAL_BY_FACE["F"], rows=(1, 0, -1), cols=(-1, 0, 1), constant_axis=2, row_axis=1, col_axis=0, constant_value=1)
    add_grid(start=27, normal=NORMAL_BY_FACE["D"], rows=(1, 0, -1), cols=(-1, 0, 1), constant_axis=1, row_axis=2, col_axis=0, constant_value=-1)
    add_grid(start=36, normal=NORMAL_BY_FACE["L"], rows=(1, 0, -1), cols=(-1, 0, 1), constant_axis=0, row_axis=1, col_axis=2, constant_value=-1)
    add_grid(start=45, normal=NORMAL_BY_FACE["B"], rows=(1, 0, -1), cols=(1, 0, -1), constant_axis=2, row_axis=1, col_axis=0, constant_value=-1)

    if len(index_to_geometry) != 54 or len(geometry_to_index) != 54:
        raise RuntimeError("cube facelet geometry must contain exactly 54 stickers")
    return index_to_geometry, geometry_to_index


INDEX_TO_GEOMETRY, GEOMETRY_TO_INDEX = _facelet_geometry()


def _apply_matrix(matrix: Matrix, vector: Vector) -> Vector:
    return tuple(sum(matrix[row][col] * vector[col] for col in range(3)) for row in range(3))  # type: ignore[return-value]


def _determinant(matrix: Matrix) -> int:
    return (
        matrix[0][0] * (matrix[1][1] * matrix[2][2] - matrix[1][2] * matrix[2][1])
        - matrix[0][1] * (matrix[1][0] * matrix[2][2] - matrix[1][2] * matrix[2][0])
        + matrix[0][2] * (matrix[1][0] * matrix[2][1] - matrix[1][1] * matrix[2][0])
    )


def _signed_permutation_matrices(*, proper_only: bool) -> tuple[Matrix, ...]:
    matrices: list[Matrix] = []
    for perm in permutations(range(3)):
        for signs in product((-1, 1), repeat=3):
            rows: list[Vector] = []
            for row in range(3):
                values = [0, 0, 0]
                values[perm[row]] = signs[row]
                rows.append(tuple(values))  # type: ignore[arg-type]
            matrix = tuple(rows)  # type: ignore[assignment]
            if not proper_only or _determinant(matrix) == 1:
                matrices.append(matrix)
    identity: Matrix = ((1, 0, 0), (0, 1, 0), (0, 0, 1))
    matrices.sort(key=lambda candidate: (candidate != identity, candidate))
    return tuple(matrices)


def _rotation_matrices() -> tuple[Matrix, ...]:
    return _signed_permutation_matrices(proper_only=True)


def _symmetry_matrices() -> tuple[Matrix, ...]:
    return _signed_permutation_matrices(proper_only=False)


@dataclass(frozen=True)
class CubeRotation:
    name: str
    matrix: Matrix
    face_map: dict[str, str]
    move_map: dict[str, str]
    index_map: dict[int, int]
    color_map: dict[str, str]

    @property
    def is_identity(self) -> bool:
        return self.matrix == ((1, 0, 0), (0, 1, 0), (0, 0, 1))

    def transform_facelets(self, facelets: str) -> str:
        if len(facelets) != 54:
            raise ValueError("A facelet cube must contain exactly 54 facelets")
        transformed = [""] * 54
        for old_index, new_index in self.index_map.items():
            transformed[new_index] = self.color_map[facelets[old_index]]
        return "".join(transformed)

    def transform_cube(self, cube: CubeState) -> CubeState:
        return CubeState.from_facelets(self.transform_facelets(cube.to_facelets()))

    def transform_move(self, move: str) -> str:
        return self.move_map[move]

    def transform_sequence(self, sequence: str | list[str] | tuple[str, ...]) -> list[str]:
        return [self.transform_move(move) for move in parse_sequence(sequence)]

    def inverse_transform_move(self, move: str) -> str:
        inverse_map = {transformed: original for original, transformed in self.move_map.items()}
        return inverse_map[move]

    def inverse_transform_sequence(self, sequence: str | list[str] | tuple[str, ...]) -> list[str]:
        return [self.inverse_transform_move(move) for move in parse_sequence(sequence)]


def _build_rotation(name: str, matrix: Matrix) -> CubeRotation:
    index_map: dict[int, int] = {}
    for old_index, (position, normal) in INDEX_TO_GEOMETRY.items():
        new_key = (_apply_matrix(matrix, position), _apply_matrix(matrix, normal))
        index_map[old_index] = GEOMETRY_TO_INDEX[new_key]

    face_map = {
        face: FACE_BY_NORMAL[_apply_matrix(matrix, normal)]
        for face, normal in NORMAL_BY_FACE.items()
    }
    color_map = dict(face_map)

    rotation = CubeRotation(
        name=name,
        matrix=matrix,
        face_map=face_map,
        move_map={},
        index_map=index_map,
        color_map=color_map,
    )
    move_map = _derive_move_map(rotation)
    return CubeRotation(
        name=name,
        matrix=matrix,
        face_map=face_map,
        move_map=move_map,
        index_map=index_map,
        color_map=color_map,
    )


def _derive_move_map(rotation: CubeRotation) -> dict[str, str]:
    solved = CubeState.solved()
    move_map: dict[str, str] = {}
    for move in ALL_MOVES:
        target = rotation.transform_cube(solved.apply_move(move))
        matches = [
            candidate
            for candidate in ALL_MOVES
            if solved.apply_move(candidate) == target
        ]
        if len(matches) != 1:
            raise RuntimeError(f"could not derive unique transformed move for {move} under {rotation.name}")
        move_map[move] = matches[0]
    return move_map


CUBE_ROTATIONS: tuple[CubeRotation, ...] = tuple(
    _build_rotation(f"rot{index:02d}", matrix)
    for index, matrix in enumerate(_rotation_matrices())
)

if len(CUBE_ROTATIONS) != 24:
    raise RuntimeError("whole-cube rotational symmetry group must contain 24 rotations")


CUBE_SYMMETRIES: tuple[CubeRotation, ...] = tuple(
    _build_rotation(f"sym{index:02d}", matrix)
    for index, matrix in enumerate(_symmetry_matrices())
)

if len(CUBE_SYMMETRIES) != 48:
    raise RuntimeError("whole-cube full symmetry group must contain 48 symmetries")


def stabilizing_rotations(cube: CubeState) -> tuple[CubeRotation, ...]:
    """Return whole-cube rotations that leave ``cube`` unchanged."""

    return tuple(rotation for rotation in CUBE_ROTATIONS if rotation.transform_cube(cube) == cube)


def stabilizing_symmetries(cube: CubeState) -> tuple[CubeRotation, ...]:
    """Return whole-cube rotations/reflections that leave ``cube`` unchanged."""

    return tuple(symmetry for symmetry in CUBE_SYMMETRIES if symmetry.transform_cube(cube) == cube)


def _is_g1_state(cube: CubeState) -> bool:
    return (
        all(value == 0 for value in cube.co)
        and all(value == 0 for value in cube.eo)
        and all(8 <= cube.ep[position] <= 11 for position in range(8, 12))
    )


def g1_preserving_symmetries() -> tuple[CubeRotation, ...]:
    """Return whole-cube symmetries that preserve Kociemba's fixed UD-axis G1.

    Kociemba phase 1 targets the subgroup with solved orientations and the
    UD-slice edges in the UD slice. Symmetries that move the UD axis to another
    axis preserve whole-cube optimality but not this axis-specific phase split.
    """

    samples = (
        CubeState.solved(),
        CubeState.from_sequence("U R2 F2 D L2 B2"),
        CubeState.from_sequence("R2 U F2 D2 B2 L2 U2"),
    )
    return tuple(
        symmetry
        for symmetry in CUBE_SYMMETRIES
        if all(_is_g1_state(symmetry.transform_cube(sample)) for sample in samples)
    )


def axis_to_ud_rotation(axis: str) -> CubeRotation:
    """Return a whole-cube rotation mapping ``axis``'s face axis onto the U-D axis.

    Used for Mike Reid's three-axis phase-1 bound: conjugating a state by this
    rotation turns its RL- or FB-axis phase-1 distance into the (table-backed)
    UD-axis phase-1 distance, since the rotation carries the corresponding
    axis-specific G1 subgroup onto the fixed UD-axis G1.
    """

    if axis not in ("R", "L", "F", "B"):
        raise ValueError("axis must be one of R, L, F, B")
    for rotation in CUBE_ROTATIONS:
        if rotation.face_map[axis] in ("U", "D"):
            return rotation
    raise RuntimeError(f"no whole-cube rotation maps {axis} onto the UD axis")


@dataclass(frozen=True)
class ThreeAxisPhase1Inputs:
    """Conjugation data reusing a fixed-UD-axis phase-1 table for all three axes."""

    rl_rotation: str
    fb_rotation: str
    conj_rl: list[str]
    conj_fb: list[str]
    rl_cube: CubeState
    fb_cube: CubeState


def three_axis_phase1_inputs(cube: CubeState) -> ThreeAxisPhase1Inputs:
    """Conjugation data for the RL and FB phase-1 axes of ``cube``.

    Returns the move-conjugation maps (one transformed move name per move in
    :data:`ALL_MOVES` order) and the conjugated cube states, so a fixed-UD-axis
    phase-1 table can be reused to bound the RL and FB axes.  The conjugation
    homomorphism ``phi (s . m) phi^-1 == (phi s phi^-1) . (phi m phi^-1)`` lets
    the native search maintain the conjugated coordinates incrementally.
    """

    phi_rl = axis_to_ud_rotation("R")
    phi_fb = axis_to_ud_rotation("F")
    return ThreeAxisPhase1Inputs(
        rl_rotation=phi_rl.name,
        fb_rotation=phi_fb.name,
        conj_rl=[phi_rl.transform_move(move) for move in ALL_MOVES],
        conj_fb=[phi_fb.transform_move(move) for move in ALL_MOVES],
        rl_cube=phi_rl.transform_cube(cube),
        fb_cube=phi_fb.transform_cube(cube),
    )


def root_symmetry_representative_moves(cube: CubeState) -> tuple[str, ...]:
    """Return one first-move representative per stabilizer orbit.

    If a whole-cube symmetry fixes the root state and maps first move ``a`` to
    first move ``b``, then any solution beginning with ``a`` has a transformed
    solution of the same length beginning with ``b``. Searching one move from
    each such orbit is therefore exact-safe at the root. This uses the full
    48-element whole-cube symmetry group, including orientation-reversing
    reflections.
    """

    stabilizer = stabilizing_symmetries(cube)
    if len(stabilizer) <= 1:
        return ALL_MOVES

    seen: set[str] = set()
    representatives: list[str] = []
    for move in ALL_MOVES:
        if move in seen:
            continue
        orbit = {rotation.transform_move(move) for rotation in stabilizer}
        representatives.append(min(orbit, key=ALL_MOVES.index))
        seen.update(orbit)
    return tuple(representatives)


def root_g1_preserving_symmetry_representative_moves(cube: CubeState) -> tuple[str, ...]:
    """Return root representatives that are safe for the fixed-axis Kociemba proof.

    This is intentionally narrower than :func:`root_symmetry_representative_moves`.
    A full whole-cube symmetry can transform a valid phase-1 prefix into a prefix
    for a different axis-specific G1 subgroup. For the native two-phase proof
    driver we only quotient by symmetries that both stabilize the input and
    preserve the repository's fixed UD-axis G1 target.
    """

    stabilizer = tuple(
        symmetry
        for symmetry in stabilizing_symmetries(cube)
        if symmetry in g1_preserving_symmetries()
    )
    if len(stabilizer) <= 1:
        return ALL_MOVES

    seen: set[str] = set()
    representatives: list[str] = []
    for move in ALL_MOVES:
        if move in seen:
            continue
        orbit = {symmetry.transform_move(move) for symmetry in stabilizer}
        representatives.append(min(orbit, key=ALL_MOVES.index))
        seen.update(orbit)
    return tuple(representatives)

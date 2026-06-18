"""Admissible lower-bound heuristics for the cubie model."""

from __future__ import annotations

import math
from functools import lru_cache

from rubik_optimal.cube import CubeState
from rubik_optimal.coordinates import MOVE_TABLE_SPECS, PHASE2_MOVE_TABLE_SPECS
from rubik_optimal.moves import PHASE2_MOVES
from rubik_optimal.tables.corner_pdb import (
    corner_pdb_available,
    corner_pdb_size_bytes,
    load_corner_pdb,
)
from rubik_optimal.tables.edge_pdb import (
    additive_edge_pdb_size_bytes,
    additive_edge_pdbs_available,
    default_additive_edge_pdb_paths,
    default_edge_pdb_paths,
    default_edge_pdb_paths_7,
    edge_pdb_7_size_bytes,
    edge_pdb_size_bytes,
    edge_pdbs_7_available,
    edge_pdbs_available,
    load_edge_pdb,
)
from rubik_optimal.tables.move_tables import build_move_table
from rubik_optimal.tables.pruning_tables import build_pruning_table


def misplaced_cubie_lower_bound(cube: CubeState) -> int:
    """Return a simple admissible lower bound under the half-turn metric.

    A single face turn moves at most four corner cubies and four edge cubies,
    and can change the orientation of at most four corners or four edges.
    """

    misplaced_corners = sum(cubie != pos for pos, cubie in enumerate(cube.cp))
    misplaced_edges = sum(cubie != pos for pos, cubie in enumerate(cube.ep))
    twisted_corners = sum(ori != 0 for ori in cube.co)
    flipped_edges = sum(ori != 0 for ori in cube.eo)
    return max(
        math.ceil(misplaced_corners / 4),
        math.ceil(misplaced_edges / 4),
        math.ceil(twisted_corners / 4),
        math.ceil(flipped_edges / 4),
    )


@lru_cache(maxsize=1)
def _projection_pruning_tables() -> tuple[tuple[object, tuple[int, ...]], ...]:
    tables = []
    for spec in MOVE_TABLE_SPECS:
        move_table = build_move_table(spec)
        pruning_table = tuple(build_pruning_table(move_table, solved_coord=spec.solved_coord))
        tables.append((spec, pruning_table))
    return tuple(tables)


def coordinate_pruning_lower_bound(cube: CubeState) -> int:
    """Return a table-based admissible lower bound from coordinate projections."""

    lower_bounds = []
    for spec, pruning_table in _projection_pruning_tables():
        coord = spec.encode(cube)  # type: ignore[attr-defined]
        lower_bounds.append(pruning_table[coord])
    return max(lower_bounds, default=0)


@lru_cache(maxsize=1)
def _phase2_pruning_tables() -> tuple[tuple[object, tuple[int, ...]], ...]:
    tables = []
    for spec in PHASE2_MOVE_TABLE_SPECS:
        move_table = build_move_table(spec, moves=PHASE2_MOVES)
        pruning_table = tuple(build_pruning_table(move_table, solved_coord=spec.solved_coord))
        tables.append((spec, pruning_table))
    return tuple(tables)


def kociemba_phase2_lower_bound(cube: CubeState) -> int:
    """Return an admissible phase-2 lower bound from restricted-move projections.

    Raises ``ValueError`` for states outside the phase-2 subgroup (misplaced
    UD/slice edges or unsolved orientations); the value is only meaningful for
    true G1 states searched under ``PHASE2_MOVES``.
    """

    lower_bounds = [misplaced_cubie_lower_bound(cube)]
    for spec, pruning_table in _phase2_pruning_tables():
        coord = spec.encode(cube)  # type: ignore[attr-defined]
        lower_bounds.append(pruning_table[coord])
    return max(lower_bounds)


def projection_pruning_distance(cube: CubeState, spec_name: str) -> int:
    """Return the projection distance for one generated coordinate table."""

    for spec, pruning_table in _projection_pruning_tables():
        if spec.name == spec_name:  # type: ignore[attr-defined]
            coord = spec.encode(cube)  # type: ignore[attr-defined]
            return pruning_table[coord]
    raise KeyError(f"Unknown pruning projection {spec_name!r}")


def combined_table_lower_bound(cube: CubeState) -> int:
    """Combine the cubie-count bound with generated projection pruning tables."""

    components = heuristic_lower_bound_components(cube)
    return max(components.values(), default=0)


def heuristic_lower_bound_components(cube: CubeState, *, include_seven_edge: bool = False) -> dict[str, int]:
    """Return named component lower bounds used by the default IDA* heuristic.

    The default component set is the frozen thesis configuration (corner PDB +
    eight 6-edge PDBs + cheap projections). The optional 7-edge layer
    (WORSTCASE Path 1) is strictly opt-in via ``include_seven_edge=True`` so
    that default invocations reproduce the frozen 6-edge thesis evidence.
    """

    components = {
        "misplaced_cubie": misplaced_cubie_lower_bound(cube),
        "coordinate_pruning": coordinate_pruning_lower_bound(cube),
        "corner_pdb": corner_pattern_database_lower_bound(cube),
        "edge_pdb": edge_pattern_database_lower_bound(cube),
    }
    if include_seven_edge:
        components["edge_pdb7"] = seven_edge_pattern_database_lower_bound(cube)
    return components


def corner_pattern_database_lower_bound(cube: CubeState) -> int:
    """Return the native 3x3 corner-PDB lower bound when its binary artifact exists."""

    if not corner_pdb_available():
        return 0
    distance = load_corner_pdb().distance(cube)
    return 0 if distance is None else distance


def edge_pattern_database_lower_bound(cube: CubeState) -> int:
    """Return the max of available native 6-edge PDB lower bounds."""

    paths = default_edge_pdb_paths()
    if not edge_pdbs_available(paths):
        return 0
    distances = []
    for path in paths:
        distance = load_edge_pdb(path).distance(cube)
        distances.append(0 if distance is None else distance)
    return max(distances, default=0)


def seven_edge_pattern_database_lower_bound(cube: CubeState) -> int:
    """Return the max of available 7-edge PDB lower bounds (0 if none generated).

    A 7-edge subset projection reaches slightly deeper than the 6-edge PDBs
    (measured max distance 11 vs 10, realized only on permutation-scrambled
    projections; on the superflip the bound stays 8, identical to 6-edge --
    see results/processed/seven_edge_strength_seed_2026.json and
    docs/WORSTCASE_HEURISTIC_DESIGN.md section 0), so on some worst-case states
    it raises the admissible MAX by +1. This is WORSTCASE Path 1; the bound is admissible
    (a true projected distance) and folds into the admissible MAX of
    ``heuristic_lower_bound_components(cube, include_seven_edge=True)``, never
    lowering the existing heuristic. It is strictly opt-in and NOT part of the
    frozen 6-edge thesis default (``combined_table_lower_bound`` excludes it).
    """

    paths = default_edge_pdb_paths_7()
    if not edge_pdbs_7_available(paths):
        return 0
    distances = []
    for path in paths:
        distance = load_edge_pdb(path).distance(cube)
        distances.append(0 if distance is None else distance)
    return max(distances, default=0)


def seven_edge_pattern_database_bytes() -> int:
    """Return the on-disk byte count of the 7-edge PDB artifacts, if present."""

    return edge_pdb_7_size_bytes(default_edge_pdb_paths_7())


def additive_edge_cpdb_lower_bound(cube: CubeState) -> int:
    """Return the compatible cost-partitioned edge-PDB sum when artifacts exist."""

    paths = default_additive_edge_pdb_paths()
    if not additive_edge_pdbs_available(paths):
        return 0
    total = 0
    for path in paths:
        distance = load_edge_pdb(path).distance(cube)
        total += 0 if distance is None else distance
    return total


def coordinate_pruning_table_bytes() -> int:
    """Return an approximate in-memory byte count for the projection distances."""

    return sum(int(spec.domain_size) for spec in MOVE_TABLE_SPECS)


def corner_pattern_database_bytes() -> int:
    """Return the on-disk byte count of the native corner PDB artifact, if present."""

    return corner_pdb_size_bytes()


def edge_pattern_database_bytes() -> int:
    """Return the on-disk byte count of the native edge PDB artifacts, if present."""

    return edge_pdb_size_bytes(default_edge_pdb_paths())


def additive_edge_cpdb_bytes() -> int:
    """Return the on-disk byte count of cost-partitioned edge PDB artifacts, if present."""

    return additive_edge_pdb_size_bytes(default_additive_edge_pdb_paths())


def phase2_pruning_table_bytes() -> int:
    """Return an approximate in-memory byte count for phase-2 projection distances."""

    return sum(int(spec.domain_size) for spec in PHASE2_MOVE_TABLE_SPECS)

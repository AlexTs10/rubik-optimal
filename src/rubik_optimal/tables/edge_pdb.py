"""Binary 3x3 edge pattern-database support (6- or 7-edge subsets).

A subset of ``N`` edge cubies (``N in {6, 7}``) is projected to a single uint32
coordinate over ``C(12, N) * N! * 2^N`` states. The 6-edge layout is the frozen
thesis format; the 7-edge layout reuses the *identical* 72-byte header (the
packed ``subset_edges[6]`` and ``reserved[2]`` fields form 8 contiguous bytes,
so a 7th edge id fits in ``reserved[0]``), distinguished by ``subset_size``. A
larger ``h`` from the deeper 7-edge projection is the lever in
``docs/WORSTCASE_HEURISTIC_DESIGN.md`` (Path 1).
"""

from __future__ import annotations

import mmap
import struct
from dataclasses import dataclass
from functools import lru_cache
from math import comb, factorial
from pathlib import Path

from rubik_optimal.coordinates.permutation import rank_permutation
from rubik_optimal.cube import CubeState

MAGIC = b"R3EPDB1\x00"
COST_PARTITIONED_MAGIC = b"R3ECPD1\x00"
VERSION = 1
SUBSET_SIZE = 6
EDGE_POSITION_COUNT = 12
SUPPORTED_SUBSET_SIZES = (6, 7)
COMBINATION_COUNT = 924
PERMUTATION_COUNT = 720
ORIENTATION_COUNT = 64
EDGE_PDB_STATE_COUNT = COMBINATION_COUNT * PERMUTATION_COUNT * ORIENTATION_COUNT
UNVISITED = 0xFF
HEADER = struct.Struct("<8sIIIIII6s2sIIIIQQ")


def subset_dimensions(subset_size: int) -> tuple[int, int, int, int]:
    """Return ``(combination, permutation, orientation, state)`` counts for N edges."""

    # The membership gate is what actually rejects 8-edge today (both supported
    # sizes 6 and 7 fit in uint32). The overflow check below is defense-in-depth:
    # it is currently unreachable, but it keeps the uint32-coordinate invariant
    # enforced at the point of computation should SUPPORTED_SUBSET_SIZES ever be
    # widened to a size whose C(12,N)*N!*2^N exceeds 2^32 (e.g. N=8).
    if subset_size not in SUPPORTED_SUBSET_SIZES:
        raise ValueError(f"edge subset size must be one of {SUPPORTED_SUBSET_SIZES}, got {subset_size}")
    combination_count = comb(EDGE_POSITION_COUNT, subset_size)
    permutation_count = factorial(subset_size)
    orientation_count = 1 << subset_size
    state_count = combination_count * permutation_count * orientation_count
    if state_count > 0xFFFFFFFF:  # unreachable for {6, 7}; guards future widening
        raise ValueError(f"edge PDB state count for subset size {subset_size} overflows uint32")
    return combination_count, permutation_count, orientation_count, state_count


def edge_pdb_state_count(subset_size: int) -> int:
    """Return the uint32 coordinate cardinality for an N-edge PDB."""

    return subset_dimensions(subset_size)[3]


DEFAULT_EDGE_SUBSETS = (
    (0, 1, 2, 3, 4, 5),
    (6, 7, 8, 9, 10, 11),
    (0, 2, 4, 6, 8, 10),
    (1, 3, 5, 7, 9, 11),
    (0, 1, 4, 5, 8, 9),
    (2, 3, 6, 7, 10, 11),
    (0, 3, 5, 6, 8, 11),
    (1, 2, 4, 7, 9, 10),
)
# Two complementary 7-edge subsets that together cover all 12 edges (overlap on
# {5, 6}). Each sees 7 of the cube's edges, so the projection reaches slightly
# deeper (measured max distance 11 vs the 6-edge PDB's 10, per the generated
# table metadata; +0 on the superflip) and can raise the admissible MAX by +1
# on hard permutation-scrambled states. See WORSTCASE Path 1 (section 0 for the
# measured revision of the original ~13 estimate).
DEFAULT_EDGE_SUBSETS_7 = (
    (0, 1, 2, 3, 4, 5, 6),
    (5, 6, 7, 8, 9, 10, 11),
)
MOVE_NAMES = (
    "U",
    "U'",
    "U2",
    "R",
    "R'",
    "R2",
    "F",
    "F'",
    "F2",
    "D",
    "D'",
    "D2",
    "L",
    "L'",
    "L2",
    "B",
    "B'",
    "B2",
)


@dataclass(frozen=True)
class AdditiveEdgePDBSpec:
    """One compatible member of an operator-cost-partitioned edge-PDB set."""

    label: str
    subset_edges: tuple[int, ...]
    move_costs: tuple[int, ...]


def _face_partition_costs(costed_faces: tuple[str, ...]) -> tuple[int, ...]:
    costed = set(costed_faces)
    costs: list[int] = []
    for move in MOVE_NAMES:
        costs.append(1 if move[0] in costed else 0)
    return tuple(costs)


DEFAULT_ADDITIVE_EDGE_PDB_SPECS = (
    AdditiveEdgePDBSpec(
        label="urf",
        subset_edges=(0, 1, 2, 3, 4, 5),
        move_costs=_face_partition_costs(("U", "R", "F")),
    ),
    AdditiveEdgePDBSpec(
        label="dlb",
        subset_edges=(6, 7, 8, 9, 10, 11),
        move_costs=_face_partition_costs(("D", "L", "B")),
    ),
)


def repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def edge_subset_label(subset_edges: tuple[int, ...] | list[int]) -> str:
    if len(subset_edges) not in SUPPORTED_SUBSET_SIZES:
        raise ValueError(f"edge subset must contain one of {SUPPORTED_SUBSET_SIZES} edge ids")
    return "_".join(str(edge) for edge in subset_edges)


def default_edge_pdb_path(
    subset_edges: tuple[int, ...] | list[int],
    *,
    root: Path | None = None,
    profile: str = "thesis",
    seed: int = 2026,
) -> Path:
    base = root or repository_root()
    return base / "data" / "generated" / f"{profile}_seed_{seed}_edge_subset_{edge_subset_label(subset_edges)}_pdb.bin"


def additive_edge_pdb_label(spec: AdditiveEdgePDBSpec) -> str:
    return f"{spec.label}_subset_{edge_subset_label(spec.subset_edges)}"


def default_additive_edge_pdb_path(
    spec: AdditiveEdgePDBSpec,
    *,
    root: Path | None = None,
    profile: str = "thesis",
    seed: int = 2026,
) -> Path:
    base = root or repository_root()
    return base / "data" / "generated" / f"{profile}_seed_{seed}_edge_cpdb_{additive_edge_pdb_label(spec)}.bin"


def _rank_combination(positions: list[int], subset_size: int) -> int:
    rank = 0
    next_value = 0
    for index, position in enumerate(positions):
        for value in range(next_value, position):
            rank += comb(EDGE_POSITION_COUNT - value - 1, subset_size - index - 1)
        next_value = position + 1
    return rank


def edge_subset_coord(cube: CubeState, subset_edges: tuple[int, ...] | list[int]) -> int:
    """Return the C(12,N) * N! * 2^N coordinate for one edge subset (N in {6, 7})."""

    subset = tuple(subset_edges)
    subset_size = len(subset)
    if subset_size not in SUPPORTED_SUBSET_SIZES or len(set(subset)) != subset_size:
        raise ValueError(f"edge subset must contain {SUPPORTED_SUBSET_SIZES} distinct edge ids")
    _, permutation_count, orientation_count, _ = subset_dimensions(subset_size)
    edge_to_subset_index = {edge: index for index, edge in enumerate(subset)}
    positions: list[int] = []
    permutation: list[int] = []
    orientation = 0
    for position, edge in enumerate(cube.ep):
        subset_index = edge_to_subset_index.get(edge)
        if subset_index is None:
            continue
        orientation_index = len(positions)
        positions.append(position)
        permutation.append(subset_index)
        if cube.eo[position] & 1:
            orientation |= 1 << orientation_index
    if len(positions) != subset_size:
        raise ValueError("cube state does not contain all subset edges")
    return (
        _rank_combination(positions, subset_size) * permutation_count + rank_permutation(permutation)
    ) * orientation_count + orientation


@dataclass(frozen=True)
class EdgePDBHeader:
    subset_edges: tuple[int, ...]
    subset_size: int
    state_count: int
    combination_count: int
    permutation_count: int
    orientation_count: int
    max_distance: int
    complete: bool
    depth_limit: int
    header_bytes: int
    expanded_nodes: int
    generated_nodes: int
    cost_partitioned: bool


class EdgePatternDatabase:
    """Memory-mapped edge pattern database (6- or 7-edge subset)."""

    def __init__(self, path: Path):
        self.path = path
        self._handle = path.open("rb")
        raw_header = self._handle.read(HEADER.size)
        if len(raw_header) != HEADER.size:
            self._handle.close()
            raise ValueError(f"{path} is too small to contain an edge PDB header")
        (
            magic,
            version,
            subset_size,
            state_count,
            combination_count,
            permutation_count,
            orientation_count,
            subset_raw,
            reserved,
            max_distance,
            complete,
            depth_limit,
            header_bytes,
            expanded_nodes,
            generated_nodes,
        ) = HEADER.unpack(raw_header)
        if magic not in {MAGIC, COST_PARTITIONED_MAGIC}:
            self._handle.close()
            raise ValueError(f"{path} has invalid edge PDB magic {magic!r}")
        if version != VERSION:
            self._handle.close()
            raise ValueError(f"{path} has unsupported edge PDB version {version}")
        if subset_size not in SUPPORTED_SUBSET_SIZES:
            self._handle.close()
            raise ValueError(f"{path} has unsupported edge PDB subset size {subset_size}")
        # subset_edges[6] and reserved[2] are contiguous in the packed header;
        # the N ids occupy the first N of those 8 bytes (N=7 spills into byte 6).
        subset_edges = tuple(int(value) for value in (subset_raw + reserved)[:subset_size])
        expected_combination, expected_permutation, expected_orientation, expected_state = subset_dimensions(
            subset_size
        )
        if (
            state_count != expected_state
            or combination_count != expected_combination
            or permutation_count != expected_permutation
            or orientation_count != expected_orientation
            or len(set(subset_edges)) != subset_size
            or any(not 0 <= edge < EDGE_POSITION_COUNT for edge in subset_edges)
        ):
            self._handle.close()
            raise ValueError(f"{path} has unexpected edge PDB dimensions")
        expected_size = header_bytes + state_count
        actual_size = path.stat().st_size
        if actual_size != expected_size:
            self._handle.close()
            raise ValueError(f"{path} size {actual_size} does not match expected {expected_size}")
        self.header = EdgePDBHeader(
            subset_edges=subset_edges,
            subset_size=subset_size,
            state_count=state_count,
            combination_count=combination_count,
            permutation_count=permutation_count,
            orientation_count=orientation_count,
            max_distance=max_distance,
            complete=bool(complete),
            depth_limit=depth_limit,
            header_bytes=header_bytes,
            expanded_nodes=expanded_nodes,
            generated_nodes=generated_nodes,
            cost_partitioned=magic == COST_PARTITIONED_MAGIC,
        )
        self._mmap = mmap.mmap(self._handle.fileno(), 0, access=mmap.ACCESS_READ)

    @property
    def size_bytes(self) -> int:
        return self.path.stat().st_size

    def distance_by_coord(self, coord: int) -> int | None:
        if coord < 0 or coord >= self.header.state_count:
            raise ValueError(f"edge PDB coordinate must be in [0, {self.header.state_count}), got {coord}")
        value = self._mmap[self.header.header_bytes + coord]
        if value == UNVISITED:
            return None
        return int(value)

    def distance(self, cube: CubeState) -> int | None:
        return self.distance_by_coord(edge_subset_coord(cube, self.header.subset_edges))

    def close(self) -> None:
        self._mmap.close()
        self._handle.close()

    def __enter__(self) -> "EdgePatternDatabase":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


@lru_cache(maxsize=16)
def load_edge_pdb(path: str | Path) -> EdgePatternDatabase:
    return EdgePatternDatabase(Path(path))


def default_edge_pdb_paths(*, root: Path | None = None, profile: str = "thesis", seed: int = 2026) -> tuple[Path, ...]:
    return tuple(default_edge_pdb_path(subset, root=root, profile=profile, seed=seed) for subset in DEFAULT_EDGE_SUBSETS)


def default_edge_pdb_paths_7(*, root: Path | None = None, profile: str = "thesis", seed: int = 2026) -> tuple[Path, ...]:
    """Paths for the optional 7-edge PDBs (WORSTCASE Path 1). Empty set if ungenerated."""

    return tuple(default_edge_pdb_path(subset, root=root, profile=profile, seed=seed) for subset in DEFAULT_EDGE_SUBSETS_7)


def edge_pdbs_7_available(paths: tuple[str | Path, ...] | None = None) -> bool:
    candidates = tuple(Path(path) for path in paths) if paths is not None else default_edge_pdb_paths_7()
    return bool(candidates) and all(candidate.exists() for candidate in candidates)


def edge_pdb_7_size_bytes(paths: tuple[str | Path, ...] | None = None) -> int:
    candidates = tuple(Path(path) for path in paths) if paths is not None else default_edge_pdb_paths_7()
    return sum(candidate.stat().st_size for candidate in candidates if candidate.exists())


def default_additive_edge_pdb_paths(
    *,
    root: Path | None = None,
    profile: str = "thesis",
    seed: int = 2026,
) -> tuple[Path, ...]:
    return tuple(
        default_additive_edge_pdb_path(spec, root=root, profile=profile, seed=seed)
        for spec in DEFAULT_ADDITIVE_EDGE_PDB_SPECS
    )


def edge_pdbs_available(paths: tuple[str | Path, ...] | None = None) -> bool:
    candidates = tuple(Path(path) for path in paths) if paths is not None else default_edge_pdb_paths()
    return all(candidate.exists() for candidate in candidates)


def edge_pdb_size_bytes(paths: tuple[str | Path, ...] | None = None) -> int:
    candidates = tuple(Path(path) for path in paths) if paths is not None else default_edge_pdb_paths()
    return sum(candidate.stat().st_size for candidate in candidates if candidate.exists())


def additive_edge_pdbs_available(paths: tuple[str | Path, ...] | None = None) -> bool:
    candidates = tuple(Path(path) for path in paths) if paths is not None else default_additive_edge_pdb_paths()
    return all(candidate.exists() for candidate in candidates)


def additive_edge_pdb_size_bytes(paths: tuple[str | Path, ...] | None = None) -> int:
    candidates = tuple(Path(path) for path in paths) if paths is not None else default_additive_edge_pdb_paths()
    return sum(candidate.stat().st_size for candidate in candidates if candidate.exists())

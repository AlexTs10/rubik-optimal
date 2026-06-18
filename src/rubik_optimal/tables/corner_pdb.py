"""Binary 3x3 corner-state pattern database support."""

from __future__ import annotations

import mmap
import struct
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from rubik_optimal.coordinates import encode_corner_orientation, encode_corner_permutation
from rubik_optimal.cube import CubeState

MAGIC = b"R3CPDB1\x00"
VERSION = 1
CORNER_PERMUTATION_COUNT = 40_320
CORNER_ORIENTATION_COUNT = 2_187
CORNER_STATE_COUNT = CORNER_PERMUTATION_COUNT * CORNER_ORIENTATION_COUNT
UNVISITED = 0xFF
HEADER = struct.Struct("<8sIIIIIIIIQQ")


def repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def default_corner_pdb_path(*, root: Path | None = None, profile: str = "thesis", seed: int = 2026) -> Path:
    base = root or repository_root()
    return base / "data" / "generated" / f"{profile}_seed_{seed}_corner_state_pdb.bin"


def corner_state_coord(cube: CubeState) -> int:
    """Return the combined 8! * 3^7 corner-state projection coordinate."""

    return encode_corner_permutation(cube) * CORNER_ORIENTATION_COUNT + encode_corner_orientation(cube)


@dataclass(frozen=True)
class CornerPDBHeader:
    state_count: int
    corner_permutation_count: int
    corner_orientation_count: int
    max_distance: int
    complete: bool
    depth_limit: int
    header_bytes: int
    expanded_nodes: int
    generated_nodes: int


class CornerPatternDatabase:
    """Memory-mapped 3x3 corner-state pattern database."""

    def __init__(self, path: Path):
        self.path = path
        self._handle = path.open("rb")
        raw_header = self._handle.read(HEADER.size)
        if len(raw_header) != HEADER.size:
            self._handle.close()
            raise ValueError(f"{path} is too small to contain a corner PDB header")
        (
            magic,
            version,
            state_count,
            corner_permutation_count,
            corner_orientation_count,
            max_distance,
            complete,
            depth_limit,
            header_bytes,
            expanded_nodes,
            generated_nodes,
        ) = HEADER.unpack(raw_header)
        if magic != MAGIC:
            self._handle.close()
            raise ValueError(f"{path} has invalid corner PDB magic {magic!r}")
        if version != VERSION:
            self._handle.close()
            raise ValueError(f"{path} has unsupported corner PDB version {version}")
        if (
            state_count != CORNER_STATE_COUNT
            or corner_permutation_count != CORNER_PERMUTATION_COUNT
            or corner_orientation_count != CORNER_ORIENTATION_COUNT
        ):
            self._handle.close()
            raise ValueError(f"{path} has unexpected corner PDB dimensions")
        expected_size = header_bytes + state_count
        actual_size = path.stat().st_size
        if actual_size != expected_size:
            self._handle.close()
            raise ValueError(f"{path} size {actual_size} does not match expected {expected_size}")
        self.header = CornerPDBHeader(
            state_count=state_count,
            corner_permutation_count=corner_permutation_count,
            corner_orientation_count=corner_orientation_count,
            max_distance=max_distance,
            complete=bool(complete),
            depth_limit=depth_limit,
            header_bytes=header_bytes,
            expanded_nodes=expanded_nodes,
            generated_nodes=generated_nodes,
        )
        self._mmap = mmap.mmap(self._handle.fileno(), 0, access=mmap.ACCESS_READ)

    @property
    def size_bytes(self) -> int:
        return self.path.stat().st_size

    def distance_by_coord(self, coord: int) -> int | None:
        if coord < 0 or coord >= self.header.state_count:
            raise ValueError(f"corner PDB coordinate must be in [0, {self.header.state_count}), got {coord}")
        value = self._mmap[self.header.header_bytes + coord]
        if value == UNVISITED:
            return None
        return int(value)

    def distance(self, cube: CubeState) -> int | None:
        return self.distance_by_coord(corner_state_coord(cube))

    def close(self) -> None:
        self._mmap.close()
        self._handle.close()

    def __enter__(self) -> "CornerPatternDatabase":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


@lru_cache(maxsize=4)
def load_corner_pdb(path: str | Path | None = None) -> CornerPatternDatabase:
    return CornerPatternDatabase(Path(path) if path is not None else default_corner_pdb_path())


def corner_pdb_available(path: str | Path | None = None) -> bool:
    try:
        candidate = Path(path) if path is not None else default_corner_pdb_path()
        return candidate.exists()
    except OSError:
        return False


def corner_pdb_size_bytes(path: str | Path | None = None) -> int:
    candidate = Path(path) if path is not None else default_corner_pdb_path()
    return candidate.stat().st_size if candidate.exists() else 0

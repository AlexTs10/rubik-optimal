"""Integrity and distribution checks for the shipped full-size pattern databases.

The native Korf solver's exactness claims rest on the complete corner and
6-edge pattern databases committed under ``data/generated/``.  The other PDB
tests regenerate tiny depth-limited tables in ``tmp_path``; the tests in this
module validate the shipped artifacts themselves:

* every shipped ``.bin`` re-hashes to the sha256 recorded in its generation
  metadata under ``results/processed/``,
* the complete corner PDB reproduces the published Korf (1997) reference
  distribution statistics (maximum distance 11, mean distance ~8.764), and
* the solved-state entry is zero for the corner PDB and one edge subset PDB.

Each test skips with an explicit reason when a table or its generation
metadata is absent, so the suite stays green on checkouts that have not
generated the multi-hundred-megabyte tables.
"""

from pathlib import Path
import hashlib
import json

import pytest

from rubik_optimal.cube import CubeState
from rubik_optimal.tables.corner_pdb import CORNER_STATE_COUNT, CornerPatternDatabase
from rubik_optimal.tables.edge_pdb import EDGE_PDB_STATE_COUNT, EdgePatternDatabase

pytestmark = pytest.mark.native

REPO_ROOT = Path(__file__).resolve().parents[1]
CORNER_METADATA_PATH = REPO_ROOT / "results" / "processed" / "corner_pdb_metadata_seed_2026_thesis.json"
EDGE_METADATA_PATH = REPO_ROOT / "results" / "processed" / "edge_pdb_metadata_seed_2026_thesis.json"

# Published reference statistics for the complete 8! * 3^7 corner pattern
# database (Korf 1997): maximum distance 11, expected distance ~8.764.  These
# are external anchors independent of this repository's generation pipeline.
KORF_CORNER_MAX_DISTANCE = 11
KORF_CORNER_MEAN_DISTANCE = 8.764
KORF_CORNER_MEAN_TOLERANCE = 0.01

_CHUNK_BYTES = 8 * 1024 * 1024


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(_CHUNK_BYTES)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _load_metadata(path: Path) -> dict:
    if not path.exists():
        pytest.skip(f"generation metadata {path} is absent")
    return json.loads(path.read_text(encoding="utf-8"))


def _shipped_table(metadata_entry: dict, *, label: str) -> Path:
    path = REPO_ROOT / str(metadata_entry.get("file_path", ""))
    if not path.exists():
        pytest.skip(f"shipped {label} table {path} is absent")
    return path


def test_shipped_corner_pdb_matches_generation_checksum():
    metadata = _load_metadata(CORNER_METADATA_PATH)
    pdb_path = _shipped_table(metadata, label="corner PDB")

    assert pdb_path.stat().st_size == metadata["size_bytes"]
    assert _sha256_file(pdb_path) == metadata["checksum_sha256"]


def test_shipped_six_edge_pdbs_match_generation_checksums():
    metadata = _load_metadata(EDGE_METADATA_PATH)
    subsets = metadata.get("subsets", [])
    assert subsets, f"{EDGE_METADATA_PATH} records no edge PDB subsets"

    absent = [
        str(REPO_ROOT / str(subset.get("file_path", "")))
        for subset in subsets
        if not (REPO_ROOT / str(subset.get("file_path", ""))).exists()
    ]
    if absent:
        pytest.skip(f"shipped 6-edge PDB tables absent: {', '.join(absent)}")

    errors: list[str] = []
    for subset in subsets:
        label = subset.get("subset_label", "?")
        pdb_path = REPO_ROOT / str(subset["file_path"])
        if pdb_path.stat().st_size != subset["size_bytes"]:
            errors.append(f"{label}: size {pdb_path.stat().st_size} != recorded {subset['size_bytes']}")
        elif _sha256_file(pdb_path) != subset["checksum_sha256"]:
            errors.append(f"{label}: sha256 does not match generation metadata for {pdb_path}")
    assert not errors, "; ".join(errors)


def test_shipped_corner_pdb_distribution_matches_korf_reference():
    metadata = _load_metadata(CORNER_METADATA_PATH)
    pdb_path = _shipped_table(metadata, label="corner PDB")

    with CornerPatternDatabase(pdb_path) as pdb:
        assert pdb.header.complete
        assert pdb.header.state_count == CORNER_STATE_COUNT
        assert pdb.header.max_distance == KORF_CORNER_MAX_DISTANCE
        header_bytes = pdb.header.header_bytes

    # Stream the one-byte-per-state payload and histogram it with bytes.count
    # (stdlib only; numpy is intentionally not required).
    counts = [0] * (KORF_CORNER_MAX_DISTANCE + 1)
    with pdb_path.open("rb") as handle:
        handle.seek(header_bytes)
        while True:
            chunk = handle.read(_CHUNK_BYTES)
            if not chunk:
                break
            for value in range(KORF_CORNER_MAX_DISTANCE + 1):
                counts[value] += chunk.count(value)

    # Every payload byte must be a distance in [0, 11]: the totals matching the
    # state count proves there are no unvisited (0xFF) or out-of-range entries,
    # and a populated depth-11 bucket pins the maximum to exactly 11.
    assert sum(counts) == CORNER_STATE_COUNT
    assert counts[KORF_CORNER_MAX_DISTANCE] > 0

    mean_distance = sum(depth * count for depth, count in enumerate(counts)) / CORNER_STATE_COUNT
    assert abs(mean_distance - KORF_CORNER_MEAN_DISTANCE) <= KORF_CORNER_MEAN_TOLERANCE

    recorded_distribution = metadata.get("distribution")
    if recorded_distribution:
        assert {str(depth): count for depth, count in enumerate(counts)} == {
            str(depth): int(count) for depth, count in recorded_distribution.items()
        }


def test_shipped_corner_pdb_scores_solved_state_zero():
    metadata = _load_metadata(CORNER_METADATA_PATH)
    pdb_path = _shipped_table(metadata, label="corner PDB")

    with CornerPatternDatabase(pdb_path) as pdb:
        assert pdb.distance(CubeState.solved()) == 0


def test_shipped_edge_subset_pdb_scores_solved_state_zero():
    metadata = _load_metadata(EDGE_METADATA_PATH)
    subsets = metadata.get("subsets", [])
    assert subsets, f"{EDGE_METADATA_PATH} records no edge PDB subsets"
    pdb_path = _shipped_table(subsets[0], label="6-edge PDB")

    with EdgePatternDatabase(pdb_path) as pdb:
        assert pdb.header.complete
        assert pdb.header.state_count == EDGE_PDB_STATE_COUNT
        assert pdb.distance(CubeState.solved()) == 0

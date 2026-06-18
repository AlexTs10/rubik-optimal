from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from rubik_optimal.cube import CubeState
from rubik_optimal.tables.edge_pdb import (
    DEFAULT_ADDITIVE_EDGE_PDB_SPECS,
    DEFAULT_EDGE_SUBSETS,
    EDGE_PDB_STATE_COUNT,
    EdgePatternDatabase,
    edge_subset_coord,
)


def test_default_edge_pdb_set_uses_complementary_mixed_partitions():
    assert len(DEFAULT_EDGE_SUBSETS) == 8
    assert len(set(DEFAULT_EDGE_SUBSETS)) == len(DEFAULT_EDGE_SUBSETS)
    for subset in DEFAULT_EDGE_SUBSETS:
        assert len(subset) == 6
        assert len(set(subset)) == 6
        assert all(0 <= edge < 12 for edge in subset)


def test_default_additive_edge_pdb_specs_partition_htm_move_costs():
    assert len(DEFAULT_ADDITIVE_EDGE_PDB_SPECS) == 2
    for move_index in range(18):
        assert sum(spec.move_costs[move_index] for spec in DEFAULT_ADDITIVE_EDGE_PDB_SPECS) == 1


def test_edge_subset_coordinate_distinguishes_real_3x3_edge_projection():
    solved = CubeState.solved()
    moved = CubeState.from_sequence("R U F")
    subset = (0, 1, 2, 3, 4, 5)

    assert edge_subset_coord(solved, subset) == 0
    assert 0 < edge_subset_coord(moved, subset) < EDGE_PDB_STATE_COUNT


def test_native_edge_pdb_depth_limited_binary_roundtrip(tmp_path: Path):
    if shutil.which("c++") is None:
        pytest.skip("no c++ compiler available to build the edge-PDB generator")

    subprocess.run(
        [
            sys.executable,
            "scripts/generate_edge_pdb.py",
            "--profile",
            "quick",
            "--seed",
            "2026",
            "--root",
            str(Path.cwd()),
            "--output-root",
            str(tmp_path),
            "--subset",
            "0,1,2,3,4,5",
            "--max-depth",
            "2",
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    pdb_path = tmp_path / "data" / "generated" / "quick_seed_2026_edge_subset_0_1_2_3_4_5_pdb.bin"
    metadata_path = tmp_path / "results" / "processed" / "edge_pdb_metadata_seed_2026_quick.json"
    table_path = tmp_path / "thesis" / "tables" / "edge_pdb_metadata.tex"

    assert pdb_path.exists()
    assert metadata_path.exists()
    assert table_path.exists()

    with EdgePatternDatabase(pdb_path) as pdb:
        assert pdb.header.state_count == EDGE_PDB_STATE_COUNT
        assert not pdb.header.complete
        assert pdb.header.subset_edges == (0, 1, 2, 3, 4, 5)
        assert pdb.distance(CubeState.solved()) == 0
        assert pdb.distance(CubeState.from_sequence("R")) == 1
        assert pdb.distance(CubeState.from_sequence("R U")) == 2


def test_native_edge_cpdb_depth_limited_binary_roundtrip(tmp_path: Path):
    if shutil.which("c++") is None:
        pytest.skip("no c++ compiler available to build the edge-CPDB generator")

    move_costs = "1,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0"
    subprocess.run(
        [
            sys.executable,
            "scripts/generate_edge_pdb.py",
            "--profile",
            "quick",
            "--seed",
            "2026",
            "--root",
            str(Path.cwd()),
            "--output-root",
            str(tmp_path),
            "--subset",
            "0,1,2,3,4,5",
            "--move-costs",
            move_costs,
            "--max-depth",
            "0",
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    pdb_path = tmp_path / "data" / "generated" / "quick_seed_2026_edge_subset_0_1_2_3_4_5_pdb.bin"
    metadata_path = tmp_path / "results" / "processed" / "edge_pdb_metadata_seed_2026_quick.json"

    assert pdb_path.exists()
    assert metadata_path.exists()

    with EdgePatternDatabase(pdb_path) as pdb:
        assert pdb.header.cost_partitioned
        assert not pdb.header.complete
        assert pdb.distance(CubeState.solved()) == 0
        assert pdb.distance(CubeState.from_sequence("U")) is None

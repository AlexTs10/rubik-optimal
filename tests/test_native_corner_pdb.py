from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from rubik_optimal.cube import CubeState
from rubik_optimal.tables.corner_pdb import (
    CORNER_STATE_COUNT,
    CornerPatternDatabase,
    corner_state_coord,
)


def test_corner_state_coordinate_distinguishes_real_3x3_corner_projection():
    solved = CubeState.solved()
    moved = CubeState.from_sequence("R U F")

    assert corner_state_coord(solved) == 0
    assert 0 < corner_state_coord(moved) < CORNER_STATE_COUNT


def test_native_corner_pdb_depth_limited_binary_roundtrip(tmp_path: Path):
    if shutil.which("c++") is None:
        pytest.skip("no c++ compiler available to build the corner-PDB generator")

    subprocess.run(
        [
            sys.executable,
            "scripts/generate_corner_pdb.py",
            "--profile",
            "quick",
            "--seed",
            "2026",
            "--root",
            str(Path.cwd()),
            "--output-root",
            str(tmp_path),
            "--max-depth",
            "2",
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    pdb_path = tmp_path / "data" / "generated" / "quick_seed_2026_corner_state_pdb.bin"
    metadata_path = tmp_path / "results" / "processed" / "corner_pdb_metadata_seed_2026_quick.json"
    table_path = tmp_path / "thesis" / "tables" / "corner_pdb_metadata.tex"

    assert pdb_path.exists()
    assert metadata_path.exists()
    assert table_path.exists()

    with CornerPatternDatabase(pdb_path) as pdb:
        assert pdb.header.state_count == CORNER_STATE_COUNT
        assert not pdb.header.complete
        assert pdb.distance(CubeState.solved()) == 0
        assert pdb.distance(CubeState.from_sequence("R")) == 1
        assert pdb.distance(CubeState.from_sequence("R U")) == 2

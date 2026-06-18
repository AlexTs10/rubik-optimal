import json
import shutil
import subprocess

import pytest

from scripts.probe_edge_projection_distance import (
    ROOT,
    _compile_native,
    bidirectional_projected_distance,
    edge_subset_coord,
    projected_state_count,
    requested_subsets,
    rotational_subset_representatives,
)
from rubik_optimal.cube import CubeState
from rubik_optimal.tables.edge_pdb import edge_subset_coord as supported_edge_subset_coord


def test_probe_coordinate_matches_supported_edge_pdb_coordinate():
    cube = CubeState.from_sequence("R U F B")

    for subset in ((0, 1, 2, 3, 4, 5), (0, 1, 2, 3, 4, 5, 6)):
        assert edge_subset_coord(cube, subset) == supported_edge_subset_coord(cube, subset)


def test_probe_projected_state_count_extends_beyond_runtime_pdb_sizes():
    assert projected_state_count(7) == 510_935_040
    assert projected_state_count(8) == 5_109_350_400
    assert projected_state_count(9) == 40_874_803_200


def test_requested_subsets_supports_explicit_and_sweep_modes():
    assert requested_subsets(
        subset_sizes=(),
        explicit_subsets=((0, 2, 4),),
        all_subsets_sizes=(),
        orbit_subsets_sizes=(),
    ) == ((0, 2, 4),)

    assert requested_subsets(
        subset_sizes=(),
        explicit_subsets=(),
        all_subsets_sizes=(11,),
        orbit_subsets_sizes=(),
    )[:2] == (
        (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10),
        (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 11),
    )

    assert requested_subsets(
        subset_sizes=(8, 9),
        explicit_subsets=(),
        all_subsets_sizes=(),
        orbit_subsets_sizes=(),
    ) == (tuple(range(8)), tuple(range(9)))


def test_rotational_subset_representatives_collapse_equivalent_subsets():
    representatives = rotational_subset_representatives(9)

    assert (0, 1, 2, 3, 4, 5, 6, 7, 8) in representatives
    assert len(representatives) < 220
    assert all(len(subset) == 9 for subset in representatives)


def test_requested_subsets_rejects_ambiguous_modes():
    try:
        requested_subsets(
            subset_sizes=(9,),
            explicit_subsets=((0, 1, 2),),
            all_subsets_sizes=(),
            orbit_subsets_sizes=(),
        )
    except ValueError as exc:
        assert "subset selection modes cannot be combined" in str(exc)
    else:
        raise AssertionError("expected ambiguous subset request to fail")


def test_bidirectional_projected_distance_finds_one_move_target():
    target = CubeState.from_sequence("F")

    result = bidirectional_projected_distance(
        subset_edges=(0, 1, 2, 3, 4, 5, 6),
        target=target,
        target_label="F",
        max_depth=1,
    )

    assert result.found_distance == 1
    assert result.proved_greater_than is None


@pytest.mark.native
def test_native_canonical_rotation_ball_smoke():
    if shutil.which("c++") is None:
        pytest.skip("no c++ compiler available to build the edge-projection probe")

    binary = _compile_native(ROOT)
    completed = subprocess.run(
        [
            str(binary),
            "--subset",
            "0,1,2,3,4,5,6,7,8,9",
            "--ball",
            "--canonical-rotations",
            "--max-depth",
            "3",
        ],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    payload = json.loads(completed.stdout)

    assert payload["completed"] is True
    assert payload["canonical_rotations"] is True
    assert [layer["seen"] for layer in payload["layers"]] == [1, 13, 142, 1798]


@pytest.mark.native
def test_native_full_symmetry_ball_smoke():
    if shutil.which("c++") is None:
        pytest.skip("no c++ compiler available to build the edge-projection probe")

    binary = _compile_native(ROOT)
    completed = subprocess.run(
        [
            str(binary),
            "--subset",
            "0,1,2,3,4,5,6,7,8,9",
            "--ball",
            "--canonical-full-symmetries",
            "--max-depth",
            "3",
        ],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    payload = json.loads(completed.stdout)

    assert payload["completed"] is True
    assert payload["canonical_rotations"] is True
    assert payload["canonical_full_symmetries"] is True
    assert payload["canonical_transform_count"] == 48
    assert [layer["seen"] for layer in payload["layers"]] == [1, 9, 80, 932]

import json
import shutil
import subprocess

import pytest

from scripts.probe_native_kociemba_phase2_superflip import ROOT, compile_native
from rubik_optimal.cube import CubeState
from rubik_optimal.search.bfs import exact_distance_bfs
from rubik_optimal.solvers.kociemba import solve_kociemba_phase2
from rubik_optimal.verify import verify_solution


def _run_native(cube: CubeState, *, max_depth: int = 10) -> dict[str, object]:
    binary = compile_native()
    completed = subprocess.run(
        [
            str(binary),
            "--cp",
            ",".join(str(value) for value in cube.cp),
            "--co",
            ",".join(str(value) for value in cube.co),
            "--ep",
            ",".join(str(value) for value in cube.ep),
            "--eo",
            ",".join(str(value) for value in cube.eo),
            "--max-depth",
            str(max_depth),
            "--timeout",
            "10",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    payload = json.loads(completed.stdout)
    payload["return_code"] = completed.returncode
    return payload


def _csv(values: tuple[int, ...]) -> str:
    return ",".join(str(value) for value in values)


def _run_native_two_phase(
    cube: CubeState,
    *,
    target_bound: int,
    phase1_start_depth: int = 0,
    root_mask: str | None = None,
    no_handoff_dedup: bool = False,
    no_cp_target_pruning: bool = False,
    phase1_full_pruning: bool = False,
    phase1_full_pruning_min_depth: int = 0,
    cp_slice_target_pruning: bool = False,
    cp_slice_target_min_depth: int = 0,
    ud_edge_target_pruning: bool = False,
    ud_edge_target_min_depth: int = 0,
    threads: int = 1,
    split_depth: int = 0,
) -> dict[str, object]:
    binary = compile_native()
    command = [
        str(binary),
        "--mode",
        "two-phase",
        "--target-bound",
        str(target_bound),
        "--phase1-start-depth",
        str(phase1_start_depth),
        "--phase1-max-depth",
        str(target_bound),
        "--timeout",
        "10",
        "--threads",
        str(threads),
        "--split-depth",
        str(split_depth),
        "--cp",
        _csv(cube.cp),
        "--co",
        _csv(cube.co),
        "--ep",
        _csv(cube.ep),
        "--eo",
        _csv(cube.eo),
    ]
    if root_mask is not None:
        command.extend(["--root-move-mask", root_mask])
    if no_handoff_dedup:
        command.append("--no-handoff-dedup")
    if no_cp_target_pruning:
        command.append("--no-cp-target-pruning")
    if phase1_full_pruning:
        command.append("--phase1-full-pruning")
        command.extend(["--phase1-full-pruning-min-depth", str(phase1_full_pruning_min_depth)])
    if cp_slice_target_pruning:
        command.append("--cp-slice-target-pruning")
        command.extend(["--cp-slice-target-min-depth", str(cp_slice_target_min_depth)])
    if ud_edge_target_pruning:
        command.append("--ud-edge-target-pruning")
        command.extend(["--ud-edge-target-min-depth", str(ud_edge_target_min_depth)])
    completed = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    payload = json.loads(completed.stdout)
    payload["return_code"] = completed.returncode
    return payload


@pytest.mark.native
@pytest.mark.parametrize(
    "sequence",
    [
        "",
        "U",
        "U D2 R2",
        "U2 R2 F2 D",
    ],
)
def test_native_phase2_probe_matches_python_phase2_length(sequence):
    if shutil.which("c++") is None:
        pytest.skip("no c++ compiler available to build native phase-2 probe")

    cube = CubeState.from_sequence(sequence)
    native = _run_native(cube, max_depth=10)
    python = solve_kociemba_phase2(cube, max_depth=10, timeout_seconds=10, node_limit=5_000_000)

    assert native["return_code"] == 0
    assert native["phase2_pair_pruning_enabled"] is True
    assert native["status"] == python.status
    assert native["solution_length"] == (
        None if python.solution is None else len(python.solution)
    )


@pytest.mark.native
def test_native_phase2_probe_rejects_non_g1_state():
    if shutil.which("c++") is None:
        pytest.skip("no c++ compiler available to build native phase-2 probe")

    payload = _run_native(CubeState.from_sequence("R"), max_depth=5)

    assert payload["return_code"] == 1
    assert payload["status"] == "failed"
    assert "phase-2 input" in payload["error"]


@pytest.mark.native
@pytest.mark.parametrize(
    "sequence",
    [
        "",
        "R",
        "R U",
        "R U F2",
        "U D2 R2",
    ],
)
def test_native_two_phase_probe_matches_bfs_on_shallow_cases(sequence):
    if shutil.which("c++") is None:
        pytest.skip("no c++ compiler available to build native phase-2 probe")

    cube = CubeState.from_sequence(sequence)
    oracle, oracle_result = exact_distance_bfs(cube, max_depth=max(1, len(sequence.split())) + 1)
    assert oracle_result.status == "exact"

    payload = _run_native_two_phase(cube, target_bound=oracle)
    moves = list(payload["phase1_solution_moves"]) + list(payload["phase2_solution_moves"])

    assert payload["return_code"] == 0
    assert payload["phase1_pair_pruning_enabled"] is True
    assert payload["phase2_pair_pruning_enabled"] is True
    assert payload["phase1_cp_target_pruning_enabled"] is True
    assert payload["phase1_cp_slice_target_pruning_enabled"] is False
    assert payload["handoff_dedup_enabled"] is True
    assert payload["status"] == "solution_found"
    assert payload["solution_length"] == oracle
    assert verify_solution(cube, moves).ok


@pytest.mark.native
def test_native_two_phase_probe_honors_root_move_mask():
    if shutil.which("c++") is None:
        pytest.skip("no c++ compiler available to build native phase-2 probe")

    cube = CubeState.from_sequence("R")
    payload = _run_native_two_phase(cube, target_bound=1, root_mask="U")

    assert payload["return_code"] == 0
    assert payload["root_move_mask_enabled"] is True
    assert payload["root_move_count"] == 1
    assert payload["status"] == "lower_bound"
    assert payload["solution_found"] is False


@pytest.mark.native
def test_native_two_phase_probe_can_skip_handoff_dedup():
    if shutil.which("c++") is None:
        pytest.skip("no c++ compiler available to build native phase-2 probe")

    cube = CubeState.from_sequence("R U")
    payload = _run_native_two_phase(cube, target_bound=2, no_handoff_dedup=True)
    moves = list(payload["phase1_solution_moves"]) + list(payload["phase2_solution_moves"])

    assert payload["return_code"] == 0
    assert payload["handoff_dedup_enabled"] is False
    assert payload["status"] == "solution_found"
    assert payload["solution_length"] == 2
    assert verify_solution(cube, moves).ok


@pytest.mark.native
def test_native_two_phase_probe_can_skip_cp_target_pruning():
    if shutil.which("c++") is None:
        pytest.skip("no c++ compiler available to build native phase-2 probe")

    cube = CubeState.from_sequence("R U")
    payload = _run_native_two_phase(cube, target_bound=2, no_cp_target_pruning=True)
    moves = list(payload["phase1_solution_moves"]) + list(payload["phase2_solution_moves"])

    assert payload["return_code"] == 0
    assert payload["phase1_cp_target_pruning_enabled"] is False
    assert payload["status"] == "solution_found"
    assert payload["solution_length"] == 2
    assert verify_solution(cube, moves).ok


@pytest.mark.native
def test_native_two_phase_probe_exposes_cp_slice_target_pruning_flag_without_build():
    if shutil.which("c++") is None:
        pytest.skip("no c++ compiler available to build native phase-2 probe")

    cube = CubeState.from_sequence("R U")
    payload = _run_native_two_phase(
        cube,
        target_bound=2,
        cp_slice_target_pruning=True,
        cp_slice_target_min_depth=99,
    )
    moves = list(payload["phase1_solution_moves"]) + list(payload["phase2_solution_moves"])

    assert payload["return_code"] == 0
    assert payload["phase1_cp_slice_target_pruning_enabled"] is True
    assert payload["phase1_cp_slice_target_min_depth"] == 99
    assert payload["phase1_cp_slice_target_table_builds"] == 0
    assert payload["status"] == "solution_found"
    assert payload["solution_length"] == 2
    assert verify_solution(cube, moves).ok


@pytest.mark.native
def test_native_two_phase_probe_exposes_phase1_full_pruning_flag_without_build():
    if shutil.which("c++") is None:
        pytest.skip("no c++ compiler available to build native phase-2 probe")

    cube = CubeState.from_sequence("R U")
    payload = _run_native_two_phase(
        cube,
        target_bound=2,
        phase1_full_pruning=True,
        phase1_full_pruning_min_depth=99,
    )
    moves = list(payload["phase1_solution_moves"]) + list(payload["phase2_solution_moves"])

    assert payload["return_code"] == 0
    assert payload["phase1_full_pruning_enabled"] is True
    assert payload["phase1_full_pruning_min_depth"] == 99
    assert payload["phase1_full_pruning_table_builds"] == 0
    assert payload["status"] == "solution_found"
    assert payload["solution_length"] == 2
    assert verify_solution(cube, moves).ok


@pytest.mark.native
def test_native_two_phase_probe_records_nonzero_phase1_start_depth_as_partial():
    if shutil.which("c++") is None:
        pytest.skip("no c++ compiler available to build native phase-2 probe")

    cube = CubeState.from_sequence("R U")
    payload = _run_native_two_phase(cube, target_bound=2, phase1_start_depth=2)
    moves = list(payload["phase1_solution_moves"]) + list(payload["phase2_solution_moves"])

    assert payload["return_code"] == 0
    assert payload["phase1_start_depth"] == 2
    assert payload["status"] == "solution_found"
    assert payload["solution_length"] == 2
    assert payload["phase1_exhaustive_for_target_bound"] is False
    assert verify_solution(cube, moves).ok


@pytest.mark.native
def test_native_two_phase_probe_parallel_split_solves_shallow_case():
    if shutil.which("c++") is None:
        pytest.skip("no c++ compiler available to build native phase-2 probe")

    cube = CubeState.from_sequence("R U")
    payload = _run_native_two_phase(
        cube,
        target_bound=2,
        no_handoff_dedup=True,
        no_cp_target_pruning=True,
        threads=2,
        split_depth=1,
    )
    moves = list(payload["phase1_solution_moves"]) + list(payload["phase2_solution_moves"])

    assert payload["return_code"] == 0
    assert payload["handoff_dedup_enabled"] is False
    assert payload["phase1_cp_target_pruning_enabled"] is False
    assert payload["threads"] == 2
    assert payload["split_depth"] == 1
    assert payload["status"] == "solution_found"
    assert payload["solution_length"] == 2
    assert verify_solution(cube, moves).ok


@pytest.mark.native
def test_native_two_phase_probe_parallel_split_allows_cp_target_pruning():
    if shutil.which("c++") is None:
        pytest.skip("no c++ compiler available to build native phase-2 probe")

    cube = CubeState.from_sequence("R U")
    payload = _run_native_two_phase(
        cube,
        target_bound=2,
        no_handoff_dedup=True,
        threads=2,
        split_depth=1,
    )
    moves = list(payload["phase1_solution_moves"]) + list(payload["phase2_solution_moves"])

    assert payload["return_code"] == 0
    assert payload["handoff_dedup_enabled"] is False
    assert payload["phase1_cp_target_pruning_enabled"] is True
    assert payload["threads"] == 2
    assert payload["split_depth"] == 1
    assert payload["status"] == "solution_found"
    assert payload["solution_length"] == 2
    assert verify_solution(cube, moves).ok


@pytest.mark.native
def test_native_two_phase_probe_parallel_split_allows_cp_slice_target_flag_without_build():
    if shutil.which("c++") is None:
        pytest.skip("no c++ compiler available to build native phase-2 probe")

    cube = CubeState.from_sequence("R U")
    payload = _run_native_two_phase(
        cube,
        target_bound=2,
        no_handoff_dedup=True,
        no_cp_target_pruning=True,
        cp_slice_target_pruning=True,
        cp_slice_target_min_depth=99,
        threads=2,
        split_depth=1,
    )
    moves = list(payload["phase1_solution_moves"]) + list(payload["phase2_solution_moves"])

    assert payload["return_code"] == 0
    assert payload["handoff_dedup_enabled"] is False
    assert payload["phase1_cp_target_pruning_enabled"] is False
    assert payload["phase1_cp_slice_target_pruning_enabled"] is True
    assert payload["phase1_cp_slice_target_table_builds"] == 0
    assert payload["threads"] == 2
    assert payload["split_depth"] == 1
    assert payload["status"] == "solution_found"
    assert payload["solution_length"] == 2
    assert verify_solution(cube, moves).ok


@pytest.mark.native
def test_native_two_phase_probe_exposes_ud_edge_target_pruning_flag_without_build():
    if shutil.which("c++") is None:
        pytest.skip("no c++ compiler available to build native phase-2 probe")

    cube = CubeState.from_sequence("R U")
    payload = _run_native_two_phase(
        cube,
        target_bound=2,
        ud_edge_target_pruning=True,
        ud_edge_target_min_depth=99,
    )
    moves = list(payload["phase1_solution_moves"]) + list(payload["phase2_solution_moves"])

    assert payload["return_code"] == 0
    assert payload["phase1_ud_edge_target_pruning_enabled"] is True
    assert payload["phase1_ud_edge_target_min_depth"] == 99
    assert payload["phase1_ud_edge_target_table_builds"] == 0
    assert payload["status"] == "solution_found"
    assert payload["solution_length"] == 2
    assert verify_solution(cube, moves).ok

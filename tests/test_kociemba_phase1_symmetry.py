"""Gates for the FlipUDSlice 16-symmetry phase-1 pruning table.

The symmetry-reduced phase-1 table is an admissible lower bound used by the
native two-phase superflip proof.  A wrong symmetry coordinate would silently
make the heuristic *inadmissible* (the worst possible failure for an optimality
claim), so these tests pin the §5 mandatory checks:

- the native FlipUDSlice reduction produces Kociemba's 64,430 classes;
- the symmetry-reduced distances match the trusted raw phase-1 BFS table
  byte-for-byte on every known (<=9) entry;
- the superflip phase-1 distance and the table diameter are the expected
  values; and
- the two-phase search with symmetric pruning still returns BFS-optimal,
  verified solutions on shallow states (admissibility at the search level).

The large generated artifacts (``phase1_sym_tables.bin``, the symmetric pruning
cache and the raw phase-1 table) are produced by ``scripts`` and may be absent
in a fresh checkout; the relevant tests skip in that case.
"""

import json
import shutil
import subprocess

import pytest

from scripts.probe_native_kociemba_phase2_superflip import ROOT, compile_native, _csv
from rubik_optimal.cube import CubeState
from rubik_optimal.search.bfs import exact_distance_bfs
from rubik_optimal.symmetry import three_axis_phase1_inputs
from rubik_optimal.verify import verify_solution

SYM_TABLES = ROOT / "data" / "generated" / "phase1_sym_tables.bin"
SYM_CACHE = ROOT / "data" / "generated" / "kociemba_phase1_sym_depth12.bin"
RAW_TABLE = ROOT / "data" / "generated" / "kociemba_phase1_full_depth9.bin"


def _require_native():
    if shutil.which("c++") is None:
        pytest.skip("no c++ compiler available to build native probe")
    if not SYM_TABLES.exists():
        pytest.skip("phase1_sym_tables.bin missing (run scripts/generate_phase1_sym_tables.py)")


def _run_verify(*, with_raw: bool) -> dict:
    binary = compile_native()
    command = [
        str(binary),
        "--mode",
        "verify-sym-phase1",
        "--sym-phase1-max-depth",
        "12",
        "--sym-tables",
        str(SYM_TABLES),
        "--sym-phase1-cache",
        str(SYM_CACHE),
    ]
    if with_raw:
        command.extend(["--raw-phase1-table", str(RAW_TABLE)])
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    payload = json.loads(completed.stdout)
    payload["return_code"] = completed.returncode
    return payload


@pytest.mark.native
def test_sym_phase1_table_builds_with_expected_invariants():
    _require_native()
    payload = _run_verify(with_raw=False)

    assert payload["return_code"] == 0
    assert payload["sym_phase1_class_count"] == 64430
    assert payload["sym_phase1_domain"] == 140908410
    # Phase-1 (CO x EO x UD-slice) has HTM diameter 12; the table is complete to it.
    assert payload["sym_phase1_max_distance"] == 12
    assert payload["solved_sym_dist"] == 0
    # The superflip's phase-1 distance is exactly 10 (fixed by the reduction).
    assert payload["superflip_phase1_sym_dist"] == 10


@pytest.mark.native
def test_sym_phase1_matches_raw_bfs_on_all_known_entries():
    _require_native()
    if not RAW_TABLE.exists():
        pytest.skip("raw phase-1 BFS table missing (run scripts to build kociemba_phase1_full_depth9.bin)")

    payload = _run_verify(with_raw=True)

    assert payload["return_code"] == 0
    assert payload["raw_table_loaded"] is True
    # Every state whose exact phase-1 distance the raw BFS knows (<=9) must agree:
    # admissibility and exactness in one byte-for-byte cross-check.
    assert payload["compared_entries"] > 900_000_000
    assert payload["mismatches"] == 0
    assert payload["matches_raw_on_all_known"] is True


def _run_two_phase_sym(cube: CubeState, *, target_bound: int) -> dict:
    binary = compile_native()
    command = [
        str(binary),
        "--mode",
        "two-phase",
        "--target-bound",
        str(target_bound),
        "--phase1-start-depth",
        "0",
        "--phase1-max-depth",
        str(target_bound),
        "--timeout",
        "60",
        "--sym-phase1-pruning",
        "--sym-tables",
        str(SYM_TABLES),
        "--sym-phase1-cache",
        str(SYM_CACHE),
        "--cp",
        _csv(cube.cp),
        "--co",
        _csv(cube.co),
        "--ep",
        _csv(cube.ep),
        "--eo",
        _csv(cube.eo),
    ]
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    payload = json.loads(completed.stdout)
    payload["return_code"] = completed.returncode
    return payload


@pytest.mark.native
@pytest.mark.parametrize("sequence", ["", "R", "R U", "R U F2", "U D2 R2"])
def test_two_phase_with_sym_pruning_is_optimal_on_shallow_states(sequence):
    _require_native()

    cube = CubeState.from_sequence(sequence)
    oracle, oracle_result = exact_distance_bfs(cube, max_depth=max(1, len(sequence.split())) + 1)
    assert oracle_result.status == "exact"
    assert oracle is not None

    payload = _run_two_phase_sym(cube, target_bound=oracle)
    moves = list(payload["phase1_solution_moves"]) + list(payload["phase2_solution_moves"])

    assert payload["return_code"] == 0
    assert payload["sym_phase1_pruning_enabled"] is True
    assert payload["status"] == "solution_found"
    # Admissible pruning must not lengthen the optimal solution.
    assert payload["solution_length"] == oracle
    assert verify_solution(cube, moves).ok


def _run_two_phase_three_axis(
    cube: CubeState, *, target_bound: int, threads: int = 1, split_depth: int = 0
) -> dict:
    binary = compile_native()
    inputs = three_axis_phase1_inputs(cube)
    command = [
        str(binary),
        "--mode",
        "two-phase",
        "--target-bound",
        str(target_bound),
        "--phase1-start-depth",
        "0",
        "--phase1-max-depth",
        str(target_bound),
        "--timeout",
        "60",
        "--threads",
        str(threads),
        "--split-depth",
        str(split_depth),
        "--sym-phase1-pruning",
        "--sym-tables",
        str(SYM_TABLES),
        "--sym-phase1-cache",
        str(SYM_CACHE),
        "--three-axis-pruning",
        "--conj-rl",
        ",".join(inputs.conj_rl),
        "--conj-fb",
        ",".join(inputs.conj_fb),
        "--cp-rl", _csv(inputs.rl_cube.cp), "--co-rl", _csv(inputs.rl_cube.co),
        "--ep-rl", _csv(inputs.rl_cube.ep), "--eo-rl", _csv(inputs.rl_cube.eo),
        "--cp-fb", _csv(inputs.fb_cube.cp), "--co-fb", _csv(inputs.fb_cube.co),
        "--ep-fb", _csv(inputs.fb_cube.ep), "--eo-fb", _csv(inputs.fb_cube.eo),
        "--cp", _csv(cube.cp), "--co", _csv(cube.co),
        "--ep", _csv(cube.ep), "--eo", _csv(cube.eo),
    ]
    if threads > 1:
        command.append("--no-handoff-dedup")
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    payload = json.loads(completed.stdout)
    payload["return_code"] = completed.returncode
    return payload


@pytest.mark.native
@pytest.mark.parametrize("sequence", ["", "R", "R U", "R U F2", "U D2 R2", "R U2 F D'", "F R U R' U'"])
def test_three_axis_pruning_is_optimal_on_shallow_states(sequence):
    _require_native()

    cube = CubeState.from_sequence(sequence)
    oracle, oracle_result = exact_distance_bfs(cube, max_depth=max(1, len(sequence.split())) + 2)
    assert oracle_result.status == "exact"
    assert oracle is not None

    payload = _run_two_phase_three_axis(cube, target_bound=oracle)
    moves = list(payload["phase1_solution_moves"]) + list(payload["phase2_solution_moves"])

    assert payload["return_code"] == 0
    assert payload["three_axis_pruning_enabled"] is True
    assert payload["status"] == "solution_found"
    # The three-axis bound is admissible: it must not prune away the optimum.
    assert payload["solution_length"] == oracle
    assert verify_solution(cube, moves).ok


@pytest.mark.native
@pytest.mark.parametrize("sequence", ["R U F2", "U D2 R2", "R U2 F D'", "F R U R' U'"])
def test_three_axis_pruning_threaded_split_is_optimal(sequence):
    """The parallel split path carries the RL/FB coordinates in each task; this
    guards against a task-carrying bug that single-threaded tests cannot catch."""
    _require_native()

    cube = CubeState.from_sequence(sequence)
    oracle, oracle_result = exact_distance_bfs(cube, max_depth=max(1, len(sequence.split())) + 2)
    assert oracle_result.status == "exact"
    assert oracle is not None

    payload = _run_two_phase_three_axis(cube, target_bound=oracle, threads=2, split_depth=1)
    moves = list(payload["phase1_solution_moves"]) + list(payload["phase2_solution_moves"])

    assert payload["return_code"] == 0
    assert payload["three_axis_pruning_enabled"] is True
    assert payload["threads"] == 2
    assert payload["status"] == "solution_found"
    assert payload["solution_length"] == oracle
    assert verify_solution(cube, moves).ok


def _run_optimal_ida(cube: CubeState, *, target_bound: int, threads: int = 1, split_depth: int = 0) -> dict:
    binary = compile_native()
    inputs = three_axis_phase1_inputs(cube)
    command = [
        str(binary),
        "--mode",
        "optimal-ida",
        "--target-bound",
        str(target_bound),
        "--timeout",
        "60",
        "--threads",
        str(threads),
        "--split-depth",
        str(split_depth),
        "--sym-phase1-pruning",
        "--sym-tables",
        str(SYM_TABLES),
        "--sym-phase1-cache",
        str(SYM_CACHE),
        "--three-axis-pruning",
        "--conj-rl",
        ",".join(inputs.conj_rl),
        "--conj-fb",
        ",".join(inputs.conj_fb),
        "--cp-rl", _csv(inputs.rl_cube.cp), "--co-rl", _csv(inputs.rl_cube.co),
        "--ep-rl", _csv(inputs.rl_cube.ep), "--eo-rl", _csv(inputs.rl_cube.eo),
        "--cp-fb", _csv(inputs.fb_cube.cp), "--co-fb", _csv(inputs.fb_cube.co),
        "--ep-fb", _csv(inputs.fb_cube.ep), "--eo-fb", _csv(inputs.fb_cube.eo),
        "--cp", _csv(cube.cp), "--co", _csv(cube.co),
        "--ep", _csv(cube.ep), "--eo", _csv(cube.eo),
    ]
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    payload = json.loads(completed.stdout)
    payload["return_code"] = completed.returncode
    return payload


@pytest.mark.native
@pytest.mark.parametrize("sequence", ["R", "R U", "R U F2", "U D2 R2", "R U2 F D'", "F R U R' U'"])
def test_optimal_ida_finds_optimal_and_proves_none_below(sequence):
    """Reid single-bound IDA*: at bound = distance it finds a verified optimal
    solution; at bound = distance - 1 it must *prove* no solution exists. The
    second direction is the admissibility gate — an over-pruning (inadmissible)
    heuristic would falsely prove no solution at the true distance."""
    _require_native()

    cube = CubeState.from_sequence(sequence)
    oracle, oracle_result = exact_distance_bfs(cube, max_depth=len(sequence.split()) + 2)
    assert oracle_result.status == "exact"
    assert oracle is not None

    at_distance = _run_optimal_ida(cube, target_bound=oracle)
    assert at_distance["return_code"] == 0
    assert at_distance["status"] == "solution_found"
    assert at_distance["solution_length"] == oracle
    assert at_distance["proves_no_solution_at_or_below_target"] is False
    assert verify_solution(cube, list(at_distance["solution_moves"])).ok

    below = _run_optimal_ida(cube, target_bound=oracle - 1)
    assert below["return_code"] == 0
    assert below["solution_found"] is False
    assert below["status"] == "lower_bound"
    assert below["proves_no_solution_at_or_below_target"] is True


@pytest.mark.native
@pytest.mark.parametrize("sequence", ["R U F2", "R U2 F D'", "F R U R' U'"])
def test_optimal_ida_threaded_split_matches_serial(sequence):
    _require_native()

    cube = CubeState.from_sequence(sequence)
    oracle, oracle_result = exact_distance_bfs(cube, max_depth=len(sequence.split()) + 2)
    assert oracle_result.status == "exact"
    assert oracle is not None

    payload = _run_optimal_ida(cube, target_bound=oracle, threads=4, split_depth=2)
    assert payload["return_code"] == 0
    assert payload["status"] == "solution_found"
    assert payload["solution_length"] == oracle
    assert verify_solution(cube, list(payload["solution_moves"])).ok

    proof = _run_optimal_ida(cube, target_bound=oracle - 1, threads=4, split_depth=2)
    assert proof["proves_no_solution_at_or_below_target"] is True

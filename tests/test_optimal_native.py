import json
import subprocess

import pytest

import rubik_optimal.solvers.optimal_native as optimal_native
from rubik_optimal.cube import CubeState
from rubik_optimal.search.bfs import exact_distance_bfs
from rubik_optimal.tables.edge_pdb import edge_pdbs_available
from rubik_optimal.tables.h48 import repository_root


def _native_optimal_binary_present() -> bool:
    return (repository_root() / "native" / "build" / "optimal_solver").exists()


# NOTE: the two ``*_cli_argument_forwarding`` tests below DO NOT prove native
# optimality.  They monkeypatch ``subprocess.run`` to return a hardcoded
# ``status: "exact"`` payload, so they only verify that the Python wrapper
# forwards the right CLI flags and parses the JSON into a SolverResult.  The
# genuine exactness proof lives in
# ``test_native_optimal_matches_bfs_exact_distance`` (real binary, BFS oracle).
def test_native_optimal_wrapper_cli_argument_forwarding_single_bound_upper_proof(
    monkeypatch, tmp_path
):
    corner_pdb = tmp_path / "corner.bin"
    edge_pdb = tmp_path / "edge.bin"
    binary = tmp_path / "optimal_solver"
    corner_pdb.write_bytes(b"corner")
    edge_pdb.write_bytes(b"edge")
    binary.write_text("#!/bin/sh\n", encoding="utf-8")

    monkeypatch.setattr(optimal_native, "default_corner_pdb_path", lambda *, root: corner_pdb)
    monkeypatch.setattr(optimal_native, "default_edge_pdb_paths", lambda *, root: (edge_pdb,))
    monkeypatch.setattr(optimal_native, "_compile", lambda root, compiler, *, with_nissy=False: binary)

    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["cwd"] = kwargs["cwd"]
        payload = {
            "status": "exact",
            "solution_moves": ["R'"],
            "solution_length": 1,
            "runtime_seconds": 0.001,
            "expanded_nodes": 12,
            "generated_nodes": 34,
            "initial_lower_bound": 1,
            "final_bound": 1,
            "edge_pdb_count": 1,
            "threads": 1,
            "split_depth": 1,
            "split_tasks": 0,
            "child_order": "heuristic-desc",
            "dual_heuristic": False,
            "nissy_heuristic": False,
            "nissy_axis_transforms": False,
            "upper_solution_verified": True,
            "exact_certified_by_upper_bound": True,
            "upper_bound_solution_length": 3,
            "upper_bound_proof_strategy": "single-bound",
            "upper_bound_proof_search_bound": 2,
            "upper_bound_proof_exhaustive": True,
            "upper_bound_shorter_solution_found": True,
            "tt_entry_limit": 0,
            "tt_hits": 0,
            "tt_capacity_skips": 0,
        }
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = optimal_native.solve_korf_native_optimal(
        CubeState.from_sequence("R"),
        upper_solution=["R'", "U", "U'"],
        upper_bound_proof_strategy="single-bound",
        root=tmp_path,
    )

    command = captured["command"]
    assert "--upper-solution" in command
    assert command[command.index("--upper-bound-proof-strategy") + 1] == "single-bound"
    assert result.status == "exact"
    assert result.is_verified is True
    assert "upper_bound_proof_strategy=single-bound" in result.notes
    assert "upper_bound_proof_exhaustive=True" in result.notes
    assert "upper_bound_shorter_solution_found=True" in result.notes


def test_native_optimal_wrapper_cli_argument_forwarding_additive_edge_pdbs(
    monkeypatch, tmp_path
):
    corner_pdb = tmp_path / "corner.bin"
    edge_pdb = tmp_path / "edge.bin"
    additive_edge_pdb = tmp_path / "edge_cpdb.bin"
    binary = tmp_path / "optimal_solver"
    corner_pdb.write_bytes(b"corner")
    edge_pdb.write_bytes(b"edge")
    additive_edge_pdb.write_bytes(b"edge-cpdb")
    binary.write_text("#!/bin/sh\n", encoding="utf-8")

    monkeypatch.setattr(optimal_native, "default_corner_pdb_path", lambda *, root: corner_pdb)
    monkeypatch.setattr(optimal_native, "default_edge_pdb_paths", lambda *, root: (edge_pdb,))
    monkeypatch.setattr(optimal_native, "default_additive_edge_pdb_paths", lambda *, root: (additive_edge_pdb,))
    monkeypatch.setattr(optimal_native, "_compile", lambda root, compiler, *, with_nissy=False: binary)

    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        payload = {
            "status": "exact",
            "solution_moves": ["R'"],
            "solution_length": 1,
            "runtime_seconds": 0.001,
            "expanded_nodes": 12,
            "generated_nodes": 34,
            "initial_lower_bound": 1,
            "final_bound": 1,
            "edge_pdb_count": 1,
            "additive_edge_pdb_count": 1,
            "threads": 1,
            "split_depth": 1,
            "split_tasks": 0,
            "child_order": "heuristic-desc",
            "dual_heuristic": False,
            "nissy_heuristic": False,
            "nissy_axis_transforms": False,
            "upper_solution_verified": False,
            "exact_certified_by_upper_bound": False,
            "upper_bound_solution_length": 0,
            "upper_bound_proof_strategy": "single-bound",
            "upper_bound_proof_search_bound": -1,
            "upper_bound_proof_exhaustive": False,
            "upper_bound_shorter_solution_found": False,
            "tt_entry_limit": 0,
            "tt_hits": 0,
            "tt_capacity_skips": 0,
        }
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = optimal_native.solve_korf_native_optimal(
        CubeState.from_sequence("R"),
        additive_edge_pdbs=True,
        root=tmp_path,
    )

    command = captured["command"]
    assert command[command.index("--additive-edge-pdb") + 1] == str(additive_edge_pdb)
    assert result.status == "exact"
    assert result.is_verified is True
    assert "additive_edge_pdb_count=1" in result.notes


def test_native_optimal_wrapper_forwards_root_symmetry_mask(monkeypatch, tmp_path):
    corner_pdb = tmp_path / "corner.bin"
    edge_pdb = tmp_path / "edge.bin"
    binary = tmp_path / "optimal_solver"
    corner_pdb.write_bytes(b"corner")
    edge_pdb.write_bytes(b"edge")
    binary.write_text("#!/bin/sh\n", encoding="utf-8")

    monkeypatch.setattr(optimal_native, "default_corner_pdb_path", lambda *, root: corner_pdb)
    monkeypatch.setattr(optimal_native, "default_edge_pdb_paths", lambda *, root: (edge_pdb,))
    monkeypatch.setattr(optimal_native, "_compile", lambda root, compiler, *, with_nissy=False: binary)

    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        payload = {
            "status": "lower_bound",
            "solution_moves": [],
            "solution_length": None,
            "runtime_seconds": 0.001,
            "expanded_nodes": 12,
            "generated_nodes": 34,
            "initial_lower_bound": 8,
            "final_bound": 9,
            "edge_pdb_count": 1,
            "additive_edge_pdb_count": 0,
            "threads": 1,
            "split_depth": 1,
            "split_tasks": 0,
            "child_order": "heuristic-desc",
            "dual_heuristic": False,
            "nissy_heuristic": False,
            "nissy_axis_transforms": False,
            "upper_solution_verified": False,
            "exact_certified_by_upper_bound": False,
            "upper_bound_solution_length": 0,
            "upper_bound_proof_strategy": "single-bound",
            "upper_bound_proof_search_bound": -1,
            "upper_bound_proof_exhaustive": False,
            "upper_bound_shorter_solution_found": False,
            "root_move_mask_enabled": True,
            "root_move_count": 2,
            "symmetry_transpositions": True,
            "symmetry_rotation_count": 24,
            "full_symmetry_transpositions": False,
            "symmetry_transform_count": 24,
            "tt_entry_limit": 0,
            "tt_hits": 0,
            "tt_capacity_skips": 0,
        }
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    superflip = CubeState(cp=tuple(range(8)), co=(0,) * 8, ep=tuple(range(12)), eo=(1,) * 12)
    result = optimal_native.solve_korf_native_optimal(
        superflip,
        root_symmetry_prune=True,
        symmetry_transpositions=True,
        root=tmp_path,
    )

    command = captured["command"]
    assert "--root-move-mask" in command
    assert command[command.index("--root-move-mask") + 1] == "U,U2"
    assert "--symmetry-transpositions" in command
    assert result.status == "lower_bound"
    assert "root_symmetry_prune=True" in result.notes
    assert "root_move_count=2" in result.notes
    assert "symmetry_transpositions=True" in result.notes


def _exact_under_root_mask_payload() -> dict[str, object]:
    return {
        "status": "exact_under_root_mask",
        "solution_moves": ["U2", "D2"],
        "solution_length": 2,
        "runtime_seconds": 0.001,
        "expanded_nodes": 12,
        "generated_nodes": 34,
        "initial_lower_bound": 2,
        "final_bound": 2,
        "edge_pdb_count": 1,
        "additive_edge_pdb_count": 0,
        "threads": 1,
        "split_depth": 1,
        "split_tasks": 0,
        "child_order": "heuristic-desc",
        "dual_heuristic": False,
        "nissy_heuristic": False,
        "nissy_axis_transforms": False,
        "upper_solution_verified": False,
        "exact_certified_by_upper_bound": False,
        "upper_bound_solution_length": 0,
        "upper_bound_proof_strategy": "single-bound",
        "upper_bound_proof_search_bound": -1,
        "upper_bound_proof_exhaustive": False,
        "upper_bound_shorter_solution_found": False,
        "root_move_mask_enabled": True,
        "root_move_count": 6,
        "symmetry_transpositions": False,
        "symmetry_rotation_count": 0,
        "full_symmetry_transpositions": False,
        "symmetry_transform_count": 0,
        "tt_entry_limit": 0,
        "tt_hits": 0,
        "tt_capacity_skips": 0,
    }


def test_native_optimal_wrapper_upgrades_exact_under_root_mask_for_derived_mask(
    monkeypatch, tmp_path
):
    """The wrapper restores ``exact`` ONLY for its own stabilizer-derived mask.

    The native binary reports the conditional status ``exact_under_root_mask``
    whenever ``--root-move-mask`` is active.  When the wrapper itself derived
    the mask from the 48-symmetry stabilizer (``root_symmetry_prune=True``),
    masked-tree optimality implies unconditional optimality, so the upgrade is
    sound and must be recorded in the notes.
    """

    corner_pdb = tmp_path / "corner.bin"
    edge_pdb = tmp_path / "edge.bin"
    binary = tmp_path / "optimal_solver"
    corner_pdb.write_bytes(b"corner")
    edge_pdb.write_bytes(b"edge")
    binary.write_text("#!/bin/sh\n", encoding="utf-8")

    monkeypatch.setattr(optimal_native, "default_corner_pdb_path", lambda *, root: corner_pdb)
    monkeypatch.setattr(optimal_native, "default_edge_pdb_paths", lambda *, root: (edge_pdb,))
    monkeypatch.setattr(optimal_native, "_compile", lambda root, compiler, *, with_nissy=False: binary)

    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        payload = _exact_under_root_mask_payload()
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = optimal_native.solve_korf_native_optimal(
        CubeState.from_sequence("U2 D2"),
        root_symmetry_prune=True,
        root=tmp_path,
    )

    assert "--root-move-mask" in captured["command"]
    assert result.status == "exact"
    assert result.is_verified is True
    assert "exact_under_root_mask upgraded to exact" in result.notes
    assert "root_symmetry_representative_moves" in result.notes


def test_native_optimal_wrapper_passes_through_exact_under_root_mask_without_derived_mask(
    monkeypatch, tmp_path
):
    """A masked-exact status the wrapper did not certify stays conditional.

    If the binary reports ``exact_under_root_mask`` but the wrapper never
    derived a mask itself (``root_symmetry_prune=False``), the conditional
    status must survive unchanged and the result must not be marked verified.
    """

    corner_pdb = tmp_path / "corner.bin"
    edge_pdb = tmp_path / "edge.bin"
    binary = tmp_path / "optimal_solver"
    corner_pdb.write_bytes(b"corner")
    edge_pdb.write_bytes(b"edge")
    binary.write_text("#!/bin/sh\n", encoding="utf-8")

    monkeypatch.setattr(optimal_native, "default_corner_pdb_path", lambda *, root: corner_pdb)
    monkeypatch.setattr(optimal_native, "default_edge_pdb_paths", lambda *, root: (edge_pdb,))
    monkeypatch.setattr(optimal_native, "_compile", lambda root, compiler, *, with_nissy=False: binary)

    def fake_run(command, **kwargs):
        payload = _exact_under_root_mask_payload()
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = optimal_native.solve_korf_native_optimal(
        CubeState.from_sequence("U2 D2"),
        root_symmetry_prune=False,
        root=tmp_path,
    )

    assert result.status == "exact_under_root_mask"
    assert result.is_verified is False
    assert "upgraded to exact" not in result.notes


def test_native_optimal_wrapper_omits_root_mask_for_asymmetric_state(monkeypatch, tmp_path):
    corner_pdb = tmp_path / "corner.bin"
    edge_pdb = tmp_path / "edge.bin"
    binary = tmp_path / "optimal_solver"
    corner_pdb.write_bytes(b"corner")
    edge_pdb.write_bytes(b"edge")
    binary.write_text("#!/bin/sh\n", encoding="utf-8")

    monkeypatch.setattr(optimal_native, "default_corner_pdb_path", lambda *, root: corner_pdb)
    monkeypatch.setattr(optimal_native, "default_edge_pdb_paths", lambda *, root: (edge_pdb,))
    monkeypatch.setattr(optimal_native, "_compile", lambda root, compiler, *, with_nissy=False: binary)

    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        payload = {
            "status": "lower_bound",
            "solution_moves": [],
            "solution_length": None,
            "runtime_seconds": 0.001,
            "expanded_nodes": 1,
            "generated_nodes": 18,
            "initial_lower_bound": 3,
            "final_bound": 4,
            "edge_pdb_count": 1,
            "additive_edge_pdb_count": 0,
            "threads": 1,
            "split_depth": 1,
            "split_tasks": 0,
            "child_order": "heuristic-desc",
            "dual_heuristic": False,
            "nissy_heuristic": False,
            "nissy_axis_transforms": False,
            "upper_solution_verified": False,
            "exact_certified_by_upper_bound": False,
            "upper_bound_solution_length": 0,
            "upper_bound_proof_strategy": "single-bound",
            "upper_bound_proof_search_bound": -1,
            "upper_bound_proof_exhaustive": False,
            "upper_bound_shorter_solution_found": False,
            "root_move_mask_enabled": False,
            "root_move_count": 18,
            "symmetry_transpositions": False,
            "symmetry_rotation_count": 0,
            "tt_entry_limit": 0,
            "tt_hits": 0,
            "tt_capacity_skips": 0,
        }
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    optimal_native.solve_korf_native_optimal(
        CubeState.from_sequence("R U F2 L' D"),
        root_symmetry_prune=True,
        root=tmp_path,
    )

    assert "--root-move-mask" not in captured["command"]


def test_native_optimal_wrapper_forwards_full_symmetry_transpositions(monkeypatch, tmp_path):
    corner_pdb = tmp_path / "corner.bin"
    edge_pdb = tmp_path / "edge.bin"
    binary = tmp_path / "optimal_solver"
    corner_pdb.write_bytes(b"corner")
    edge_pdb.write_bytes(b"edge")
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    binary.chmod(0o755)

    monkeypatch.setattr(optimal_native, "default_corner_pdb_path", lambda root: corner_pdb)
    monkeypatch.setattr(optimal_native, "default_edge_pdb_paths", lambda root: (edge_pdb,))
    monkeypatch.setattr(optimal_native, "default_edge_pdb_paths_7", lambda root: ())
    monkeypatch.setattr(optimal_native, "edge_pdbs_7_available", lambda paths: False)
    monkeypatch.setattr(optimal_native, "_compile", lambda root, compiler, with_nissy=False: binary)

    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        payload = {
            "status": "lower_bound",
            "solution_moves": [],
            "solution_length": None,
            "runtime_seconds": 0.001,
            "expanded_nodes": 1,
            "generated_nodes": 18,
            "initial_lower_bound": 3,
            "final_bound": 4,
            "edge_pdb_count": 1,
            "additive_edge_pdb_count": 0,
            "threads": 1,
            "split_depth": 1,
            "split_tasks": 0,
            "child_order": "heuristic-desc",
            "dual_heuristic": False,
            "nissy_heuristic": False,
            "nissy_axis_transforms": False,
            "upper_solution_verified": False,
            "exact_certified_by_upper_bound": False,
            "upper_bound_solution_length": 0,
            "upper_bound_proof_strategy": "single-bound",
            "upper_bound_proof_search_bound": -1,
            "upper_bound_proof_exhaustive": False,
            "upper_bound_shorter_solution_found": False,
            "root_move_mask_enabled": False,
            "root_move_count": 18,
            "symmetry_transpositions": True,
            "symmetry_rotation_count": 24,
            "full_symmetry_transpositions": True,
            "symmetry_transform_count": 48,
            "tt_entry_limit": 0,
            "tt_hits": 0,
            "tt_capacity_skips": 0,
        }
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = optimal_native.solve_korf_native_optimal(
        CubeState.from_sequence("R U"),
        symmetry_transpositions=True,
        full_symmetry_transpositions=True,
        root=tmp_path,
    )

    assert "--symmetry-transpositions" in captured["command"]
    assert "--full-symmetry-transpositions" in captured["command"]
    assert "full_symmetry_transpositions=True" in result.notes
    assert "symmetry_transform_count=48" in result.notes


def test_native_optimal_wrapper_forwards_compact_transpositions(monkeypatch, tmp_path):
    corner_pdb = tmp_path / "corner.bin"
    edge_pdb = tmp_path / "edge.bin"
    binary = tmp_path / "optimal_solver"
    corner_pdb.write_bytes(b"corner")
    edge_pdb.write_bytes(b"edge")
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    binary.chmod(0o755)

    monkeypatch.setattr(optimal_native, "default_corner_pdb_path", lambda *, root: corner_pdb)
    monkeypatch.setattr(optimal_native, "default_edge_pdb_paths", lambda *, root: (edge_pdb,))
    monkeypatch.setattr(optimal_native, "default_edge_pdb_paths_7", lambda *, root: ())
    monkeypatch.setattr(optimal_native, "edge_pdbs_7_available", lambda paths: False)
    monkeypatch.setattr(optimal_native, "_compile", lambda root, compiler, *, with_nissy=False: binary)

    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        payload = {
            "status": "lower_bound",
            "solution_moves": [],
            "solution_length": None,
            "runtime_seconds": 0.001,
            "expanded_nodes": 1,
            "generated_nodes": 18,
            "initial_lower_bound": 3,
            "final_bound": 4,
            "edge_pdb_count": 1,
            "additive_edge_pdb_count": 0,
            "threads": 1,
            "split_depth": 1,
            "split_tasks": 0,
            "child_order": "heuristic-desc",
            "dual_heuristic": False,
            "nissy_heuristic": False,
            "nissy_axis_transforms": False,
            "upper_solution_verified": False,
            "exact_certified_by_upper_bound": False,
            "upper_bound_solution_length": 0,
            "upper_bound_proof_strategy": "single-bound",
            "upper_bound_proof_search_bound": -1,
            "upper_bound_proof_exhaustive": False,
            "upper_bound_shorter_solution_found": False,
            "root_move_mask_enabled": False,
            "root_move_count": 18,
            "symmetry_transpositions": True,
            "symmetry_rotation_count": 24,
            "full_symmetry_transpositions": True,
            "symmetry_transform_count": 48,
            "compact_transpositions": True,
            "tt_entry_limit": 100,
            "tt_hits": 3,
            "tt_capacity_skips": 0,
        }
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = optimal_native.solve_korf_native_optimal(
        CubeState.from_sequence("R U"),
        symmetry_transpositions=True,
        full_symmetry_transpositions=True,
        compact_transpositions=True,
        transposition_entries=100,
        root=tmp_path,
    )

    assert "--compact-transpositions" in captured["command"]
    assert "compact_transpositions=True" in result.notes


@pytest.mark.native
@pytest.mark.parametrize(
    "scramble",
    [
        ["R"],
        ["R", "U"],
        ["R", "U", "F2"],
        ["F", "R", "U", "R'", "U'"],
    ],
)
def test_native_optimal_matches_bfs_exact_distance(scramble):
    """REAL native-optimal exactness proof (no mocked subprocess).

    Runs the compiled C++ Korf engine on shallow scrambles whose ground-truth
    optimal HTM distance is independently established by an exhaustive BFS
    oracle, and asserts the native solver returns that exact length.  BFS is the
    sole ground truth (no hand-guessed expected constant -- a scramble of length
    n is only an UPPER bound on the optimal distance, e.g. F R U R' U' is
    optimally 5, not 4).  Guarded by PDB availability + binary presence
    (``pytest.skip``, never a silent pass) and marked ``native`` so it can be
    deselected while the binary is rebuilt.
    """

    if not edge_pdbs_available():
        pytest.skip("native edge PDBs not generated; cannot run native optimal solver")
    if not _native_optimal_binary_present():
        pytest.skip("native optimal_solver binary absent (not yet compiled)")

    cube = CubeState.from_sequence(scramble)
    oracle, oracle_result = exact_distance_bfs(cube, max_depth=len(scramble) + 1)
    assert oracle is not None and oracle_result.status == "exact", (scramble, oracle_result.status)

    result = optimal_native.solve_korf_native_optimal(
        cube,
        max_depth=20,
        timeout_seconds=60,
        threads=1,
        nissy_heuristic=False,
    )

    assert result.status == "exact", (scramble, result.status, result.notes)
    assert result.solution_length == oracle, (scramble, oracle, result.solution_length)
    assert result.is_verified


@pytest.mark.native
@pytest.mark.parametrize(
    "scramble",
    [
        ["R"],
        ["R", "U"],
        ["R", "U", "F2"],
        ["U2", "D2"],
        ["F", "R", "U", "R'", "U'"],
    ],
)
def test_native_optimal_with_symmetry_transpositions_matches_bfs(scramble):
    if not edge_pdbs_available():
        pytest.skip("native edge PDBs not generated; cannot run native optimal solver")
    if not _native_optimal_binary_present():
        pytest.skip("native optimal_solver binary absent (not yet compiled)")

    cube = CubeState.from_sequence(scramble)
    oracle, oracle_result = exact_distance_bfs(cube, max_depth=len(scramble) + 1)
    assert oracle is not None and oracle_result.status == "exact", (scramble, oracle_result.status)

    result = optimal_native.solve_korf_native_optimal(
        cube,
        max_depth=20,
        timeout_seconds=60,
        threads=1,
        nissy_heuristic=False,
        transposition_entries=50_000,
        symmetry_transpositions=True,
        root_symmetry_prune=True,
    )

    assert result.status == "exact", (scramble, result.status, result.notes)
    assert result.solution_length == oracle, (scramble, oracle, result.solution_length)
    assert result.is_verified
    assert "symmetry_transpositions=True" in result.notes
    assert "symmetry_rotation_count=24" in result.notes


@pytest.mark.native
@pytest.mark.parametrize(
    "scramble",
    [
        ["R", "U"],
        ["F", "R", "U", "R'", "U'"],
    ],
)
def test_native_optimal_with_compact_full_symmetry_transpositions_matches_bfs(scramble):
    if not edge_pdbs_available():
        pytest.skip("native edge PDBs not generated; cannot run native optimal solver")
    if not _native_optimal_binary_present():
        pytest.skip("native optimal_solver binary absent (not yet compiled)")

    cube = CubeState.from_sequence(scramble)
    oracle, oracle_result = exact_distance_bfs(cube, max_depth=len(scramble) + 1)
    assert oracle is not None and oracle_result.status == "exact", (scramble, oracle_result.status)

    result = optimal_native.solve_korf_native_optimal(
        cube,
        max_depth=20,
        timeout_seconds=60,
        threads=1,
        nissy_heuristic=False,
        transposition_entries=50_000,
        symmetry_transpositions=True,
        full_symmetry_transpositions=True,
        compact_transpositions=True,
        root_symmetry_prune=True,
    )

    assert result.status == "exact", (scramble, result.status, result.notes)
    assert result.solution_length == oracle, (scramble, oracle, result.solution_length)
    assert result.is_verified
    assert "full_symmetry_transpositions=True" in result.notes
    assert "compact_transpositions=True" in result.notes

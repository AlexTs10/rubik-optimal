"""Mandatory admissibility / correctness gate for the 7-edge PDB (WORSTCASE Path 1).

``docs/WORSTCASE_HEURISTIC_DESIGN.md`` §5 makes this gate non-optional: any
heuristic change can silently break optimality, so every layer is checked.

Layers, fastest first:

1. Pure-Python coordinate identities (always run): the 7-edge encoder is a
   bijection-consistent projection -- solved -> 0, in-range, orientation parity.
2. Depth-limited generator round-trip (needs a C++ compiler, ~seconds): the
   *real* native generator builds a tiny depth-2 7-edge PDB and the Python reader
   recovers exact shallow distances. This proves generator+reader without the
   ~15-minute full build.
3. Native coordinate equivalence (``native``; needs the binary + complete PDBs):
   the compiled engine's 7-edge ``edge_subset_coord`` is byte-identical to the
   validated Python encoder on random states -- the decisive guard against a
   silently inadmissible native heuristic.
4. Admissibility (``native``; needs complete 7-edge PDBs): ``h(s) <= BFS(s)``.
5. Shallow optimality (``native``): native solution length == BFS exact distance
   with the 7-edge PDBs loaded, so the new path is exercised inside the search.

All ``native`` layers ``pytest.skip`` (never silently pass) when their inputs are
absent, so the gate is honest while the 7-edge PDBs are still being generated.
"""

from __future__ import annotations

import json
import random
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from rubik_optimal.cube import CubeState
from rubik_optimal.moves import ALL_MOVES, same_face
from rubik_optimal.search.bfs import exact_distance_bfs
from rubik_optimal.search.heuristics import (
    combined_table_lower_bound,
    heuristic_lower_bound_components,
    seven_edge_pattern_database_lower_bound,
)
from rubik_optimal.tables.corner_pdb import (
    default_corner_pdb_path,
    encode_corner_orientation,
    encode_corner_permutation,
)
from rubik_optimal.tables.edge_pdb import (
    DEFAULT_EDGE_SUBSETS_7,
    EdgePatternDatabase,
    default_edge_pdb_paths_7,
    edge_pdb_state_count,
    edge_pdbs_7_available,
    edge_subset_coord,
    load_edge_pdb,
    subset_dimensions,
)
from rubik_optimal.tables.h48 import repository_root


def _native_binary() -> Path:
    return repository_root() / "native" / "build" / "optimal_solver"


def _scrambler(seed: int):
    rng = random.Random(seed)

    def scramble(length: int) -> list[str]:
        moves: list[str] = []
        previous = None
        while len(moves) < length:
            move = rng.choice(ALL_MOVES)
            if same_face(previous, move):
                continue
            moves.append(move)
            previous = move
        return moves

    return scramble


SUPERFLIP = CubeState(cp=tuple(range(8)), co=(0,) * 8, ep=tuple(range(12)), eo=(1,) * 12)


# ---------------------------------------------------------------------------
# Layer 1: pure-Python coordinate identities (always run).
# ---------------------------------------------------------------------------
def test_seven_edge_default_subsets_well_formed():
    assert len(DEFAULT_EDGE_SUBSETS_7) >= 1
    covered: set[int] = set()
    for subset in DEFAULT_EDGE_SUBSETS_7:
        assert len(subset) == 7
        assert len(set(subset)) == 7
        assert all(0 <= edge < 12 for edge in subset)
        covered |= set(subset)
    assert covered == set(range(12)), "7-edge subsets must collectively cover all 12 edges"


def test_seven_edge_dimensions():
    combination, permutation, orientation, state = subset_dimensions(7)
    assert (combination, permutation, orientation) == (792, 5040, 128)
    assert state == 510_935_040 == edge_pdb_state_count(7)


def test_seven_edge_coordinate_projection_is_in_range_and_solved_is_zero():
    subset = (0, 1, 2, 3, 4, 5, 6)
    assert edge_subset_coord(CubeState.solved(), subset) == 0
    moved = CubeState.from_sequence("R U F")
    assert 0 < edge_subset_coord(moved, subset) < edge_pdb_state_count(7)


def test_superflip_seven_edge_coordinate_sees_all_seven_flips():
    # All edges flipped, identity permutation -> orientation field = 2^7 - 1.
    for subset in DEFAULT_EDGE_SUBSETS_7:
        coord = edge_subset_coord(SUPERFLIP, subset)
        assert coord % 128 == 127


# ---------------------------------------------------------------------------
# Layer 2: depth-limited generator round-trip (needs a C++ compiler).
# ---------------------------------------------------------------------------
def test_native_seven_edge_generator_depth_limited_roundtrip(tmp_path: Path):
    if shutil.which("c++") is None:
        pytest.skip("no c++ compiler available to build the 7-edge PDB generator")

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
            "0,1,2,3,4,5,6",
            "--max-depth",
            "2",
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    pdb_path = tmp_path / "data" / "generated" / "quick_seed_2026_edge_subset_0_1_2_3_4_5_6_pdb.bin"
    summary_path = tmp_path / "results" / "processed" / "edge_pdb7_metadata_seed_2026_quick.json"
    assert pdb_path.exists()
    assert summary_path.exists()
    # The 7-edge follow-up table must NOT be written into the frozen thesis tree.
    assert not (tmp_path / "thesis").exists()
    assert (tmp_path / "results" / "processed" / "edge_pdb7_metadata.tex").exists()

    with EdgePatternDatabase(pdb_path) as pdb:
        assert pdb.header.subset_size == 7
        assert pdb.header.subset_edges == (0, 1, 2, 3, 4, 5, 6)
        assert pdb.header.state_count == edge_pdb_state_count(7)
        assert not pdb.header.complete
        assert pdb.distance(CubeState.solved()) == 0
        assert pdb.distance(CubeState.from_sequence("R")) == 1
        assert pdb.distance(CubeState.from_sequence("R U")) == 2
        # Beyond the depth-2 frontier the BFS has not reached the state.
        assert pdb.distance(CubeState.from_sequence("R U F")) is None


# ---------------------------------------------------------------------------
# Layer 3: native vs Python coordinate equivalence (needs the binary + PDBs).
# ---------------------------------------------------------------------------
def _emit_edge_coords(cube: CubeState, edge_paths: tuple[Path, ...]) -> dict:
    corner = default_corner_pdb_path(root=repository_root())
    command = [
        str(_native_binary()),
        "--corner-pdb",
        str(corner),
        "--cp",
        ",".join(map(str, cube.cp)),
        "--co",
        ",".join(map(str, cube.co)),
        "--ep",
        ",".join(map(str, cube.ep)),
        "--eo",
        ",".join(map(str, cube.eo)),
        "--emit-edge-coords",
    ]
    for path in edge_paths:
        command += ["--edge-pdb", str(path)]
    completed = subprocess.run(command, capture_output=True, text=True, check=True)
    return json.loads(completed.stdout)


@pytest.mark.native
def test_native_seven_edge_coordinate_matches_python_encoder():
    if not _native_binary().exists():
        pytest.skip("native optimal_solver binary absent (not yet compiled)")
    seven = default_edge_pdb_paths_7(root=repository_root())
    if not edge_pdbs_7_available(seven):
        pytest.skip("complete 7-edge PDBs not generated yet")

    pdbs = [load_edge_pdb(str(path)) for path in seven]
    scramble = _scrambler(2026)
    length_rng = random.Random(4242)
    mismatches = 0
    for _ in range(25):
        cube = CubeState.from_sequence(scramble(length_rng.randint(4, 18)))
        payload = _emit_edge_coords(cube, seven)
        assert payload["corner_coord"] == encode_corner_permutation(cube) * 2187 + encode_corner_orientation(cube)
        for pdb, slot in zip(pdbs, payload["edge_pdbs"]):
            assert slot["subset_size"] == 7
            py_coord = edge_subset_coord(cube, pdb.header.subset_edges)
            py_distance = pdb.distance(cube)
            if slot["coord"] != py_coord or slot["distance"] != py_distance:
                mismatches += 1
    assert mismatches == 0


# ---------------------------------------------------------------------------
# Layer 4: admissibility -- h(s) <= true distance (BFS oracle, depth <= 5).
# ---------------------------------------------------------------------------
@pytest.mark.native
def test_seven_edge_heuristic_is_admissible_against_bfs():
    seven = default_edge_pdb_paths_7(root=repository_root())
    if not edge_pdbs_7_available(seven):
        pytest.skip("complete 7-edge PDBs not generated yet")

    scramble = _scrambler(99)
    checked = 0
    for length in range(1, 6):
        for _ in range(3):
            cube = CubeState.from_sequence(scramble(length))
            distance, result = exact_distance_bfs(cube, max_depth=5)
            if distance is None or result.status != "exact":
                continue
            checked += 1
            h7 = seven_edge_pattern_database_lower_bound(cube)
            combined = combined_table_lower_bound(cube)
            assert h7 <= distance, (cube.to_facelets(), h7, distance)
            assert combined <= distance, (cube.to_facelets(), combined, distance)
            # The 7-edge layer is strictly opt-in: the frozen default component
            # set must not include it, so the 6-edge thesis evidence reproduces.
            assert "edge_pdb7" not in heuristic_lower_bound_components(cube)
            # Opted in explicitly, the 7-edge layer must never lower the
            # combined bound, and the opted-in MAX must stay admissible.
            components = heuristic_lower_bound_components(cube, include_seven_edge=True)
            assert components["edge_pdb7"] == h7
            assert max(components.values()) == max(combined, h7)
            assert max(components.values()) <= distance
    assert checked >= 5


# ---------------------------------------------------------------------------
# Layer 5: shallow optimality with the 7-edge PDBs loaded in the native search.
# ---------------------------------------------------------------------------
@pytest.mark.native
@pytest.mark.parametrize("scramble", [["R"], ["R", "U"], ["F", "R", "U", "R'", "U'"]])
def test_native_optimal_with_seven_edge_pdbs_matches_bfs(scramble):
    import rubik_optimal.solvers.optimal_native as optimal_native

    if not _native_binary().exists():
        pytest.skip("native optimal_solver binary absent (not yet compiled)")
    if not edge_pdbs_7_available(default_edge_pdb_paths_7(root=repository_root())):
        pytest.skip("complete 7-edge PDBs not generated yet")

    cube = CubeState.from_sequence(scramble)
    oracle, oracle_result = exact_distance_bfs(cube, max_depth=len(scramble) + 1)
    assert oracle is not None and oracle_result.status == "exact"

    result = optimal_native.solve_korf_native_optimal(
        cube,
        max_depth=20,
        timeout_seconds=60,
        threads=1,
        use_seven_edge_pdbs=True,
    )
    assert result.status == "exact", (scramble, result.status, result.notes)
    assert result.solution_length == oracle, (scramble, oracle, result.solution_length)
    assert result.is_verified
    # Confirm the 7-edge tables were actually loaded into the search (8 default
    # 6-edge + len(DEFAULT_EDGE_SUBSETS_7) 7-edge). A positive count assertion --
    # NOT "... in notes or 'edge_pdb_count=' in notes", which is a tautology.
    from rubik_optimal.tables.edge_pdb import DEFAULT_EDGE_SUBSETS_7

    expected_count = 8 + len(DEFAULT_EDGE_SUBSETS_7)
    assert f"edge_pdb_count={expected_count}" in result.notes, result.notes
    # Decisively confirm the loaded set really contains the 7-edge tables (guards
    # against a path bug that loads a 6-edge PDB twice to reach the same count).
    from rubik_optimal.tables.edge_pdb import default_edge_pdb_paths

    seven = default_edge_pdb_paths_7(root=repository_root())
    payload = _emit_edge_coords(cube, default_edge_pdb_paths(root=repository_root()) + seven)
    seven_loaded = sum(1 for slot in payload["edge_pdbs"] if slot["subset_size"] == 7)
    assert seven_loaded == len(DEFAULT_EDGE_SUBSETS_7), payload["edge_pdbs"]

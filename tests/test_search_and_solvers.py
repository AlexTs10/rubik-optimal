import random

import pytest

from rubik_optimal.cube import CubeState
from rubik_optimal.coordinates import CORNER_ORIENTATION_SPEC, EDGE_ORIENTATION_SPEC, UD_SLICE_SPEC
from rubik_optimal.distance import recognize_distance
from rubik_optimal.moves import ALL_MOVES
from rubik_optimal.search.bfs import exact_distance_bfs
from rubik_optimal.search.heuristics import (
    additive_edge_cpdb_lower_bound,
    combined_table_lower_bound,
    heuristic_lower_bound_components,
    misplaced_cubie_lower_bound,
)
from rubik_optimal.search.ida_star import ida_star_collect_solutions, ida_star_solve
from rubik_optimal.solvers.kociemba import (
    collect_kociemba_phase1_candidates,
    is_kociemba_phase1_goal,
    solve_kociemba_adapter,
    solve_kociemba_native_scoped,
    solve_kociemba_phase1,
    solve_kociemba_phase2,
)
from rubik_optimal.solvers.base import SolverResult
from rubik_optimal.solvers.korf import solve_korf_ida
from rubik_optimal.solvers.optimal_native import solve_korf_native_optimal
from rubik_optimal.solvers.thistlethwaite import (
    G2_MOVES,
    G3_MOVES,
    g3_subgroup_permutation_counts,
    is_edge_orientation_solved,
    is_g2_subgroup,
    is_g3_square_group,
    solve_thistlethwaite_native_full,
    solve_thistlethwaite_native_scoped,
)
from rubik_optimal.tables.edge_pdb import additive_edge_pdbs_available, edge_pdbs_available
from rubik_optimal.tables.h48 import h48_table_path, repository_root
from rubik_optimal.verify import verify_solution


def _note_int(notes: str, key: str) -> int:
    prefix = f"{key}="
    for part in notes.split(";"):
        item = part.strip()
        if item.startswith(prefix):
            return int(item.removeprefix(prefix))
    raise AssertionError(f"missing {key} in notes: {notes}")


def _native_optimal_binary_present() -> bool:
    """True when the compiled native optimal_solver binary is on disk.

    The native C++ Korf engine is compiled on demand by the solver wrapper, but
    a separate work-stream may be rebuilding it; tests that drive it guard on
    this so they ``pytest.skip`` (never silently pass) when it is absent.
    """

    from rubik_optimal.tables.h48 import repository_root

    root = repository_root()
    return (root / "native" / "build" / "optimal_solver").exists()


def _non_cancelling_scramble(rng: random.Random, length: int) -> list[str]:
    """Draw a ``length``-move scramble with no two consecutive same-face turns."""

    moves: list[str] = []
    previous_face: str | None = None
    while len(moves) < length:
        move = rng.choice(ALL_MOVES)
        if previous_face == move[0]:
            continue
        moves.append(move)
        previous_face = move[0]
    return moves


# Deterministic corpus of ~30 non-cancelling scrambles of length 1..7, generated
# once with random.Random(2026) so the parametrization (and any skip) is stable
# across runs and machines.  The BFS oracle is capped modestly because pure-Python
# BFS is exponential in depth (depth 5+ can take many seconds per case under load);
# cases whose optimal distance exceeds the cap return ``None`` and are EXPLICITLY
# skipped rather than silently passed.  At this cap the scrambles with optimal
# distance <= 4 (~half the corpus) are real BFS-exact optimality checks against
# BOTH solve_korf_ida and ida_star_solve, keeping the parametrization well under
# a minute while still covering many distinct randomized states.
_OPTIMALITY_BFS_DEPTH = 4


def _build_optimality_corpus() -> list[tuple[int, tuple[str, ...]]]:
    rng = random.Random(2026)
    corpus: list[tuple[int, tuple[str, ...]]] = []
    for _ in range(30):
        length = rng.randint(1, 7)
        corpus.append((length, tuple(_non_cancelling_scramble(rng, length))))
    return corpus


_OPTIMALITY_SCRAMBLES = _build_optimality_corpus()


def test_bfs_finds_exact_shallow_distance():
    cube = CubeState.from_sequence("R U")
    distance, result = exact_distance_bfs(cube, max_depth=4)
    assert result.status == "exact"
    assert distance == 2


def test_bfs_completed_depth_bound_reports_lower_bound_not_not_applicable():
    cube = CubeState.from_sequence("R U")
    distance, result = exact_distance_bfs(cube, max_depth=1)

    assert distance is None
    assert result.status == "lower_bound"


def test_heuristic_is_admissible_on_shallow_cases():
    cases = ["", "R", "R U", "F R U", "R U R' U'"]
    for sequence in cases:
        cube = CubeState.from_sequence(sequence)
        distance, _ = exact_distance_bfs(cube, max_depth=5)
        assert distance is not None
        assert misplaced_cubie_lower_bound(cube) <= distance


def test_combined_table_heuristic_is_admissible_on_shallow_exact_cases():
    cases = ["", "R", "R U", "F R U", "R U R' U'", "F R U R' U'"]
    for sequence in cases:
        cube = CubeState.from_sequence(sequence)
        distance, _ = exact_distance_bfs(cube, max_depth=5)
        assert distance is not None
        components = heuristic_lower_bound_components(cube)
        combined = combined_table_lower_bound(cube)
        assert all(value <= distance for value in components.values())
        assert combined <= distance
        if additive_edge_pdbs_available():
            assert additive_edge_cpdb_lower_bound(cube) <= distance


def test_combined_table_heuristic_is_not_weaker_than_default_components():
    cases = ["", "R", "R U F2", "F R U R' U' F'", "L D2 B R2 U"]
    for sequence in cases:
        cube = CubeState.from_sequence(sequence)
        components = heuristic_lower_bound_components(cube)
        combined = combined_table_lower_bound(cube)
        assert combined == max(components.values())
        for component in components.values():
            assert combined >= component


def test_ida_star_solves_feasible_case_exactly():
    cube = CubeState.from_sequence("R U F")
    result = ida_star_solve(cube, max_depth=5, timeout_seconds=2)
    assert result.status == "exact"
    assert result.solution is not None
    assert len(result.solution) == 3
    assert verify_solution(cube, result.solution).ok


def test_ida_star_heuristic_ordering_preserves_exact_solution():
    cube = CubeState.from_sequence("F R U")
    result = ida_star_solve(
        cube,
        max_depth=5,
        timeout_seconds=2,
        order_children_by_heuristic=True,
    )
    assert result.status == "exact"
    assert result.solution is not None
    assert len(result.solution) == 3
    assert verify_solution(cube, result.solution).ok


def test_ida_star_completed_depth_bound_reports_lower_bound():
    cube = CubeState.from_sequence("R U")
    result = ida_star_solve(cube, max_depth=1, timeout_seconds=2)

    assert result.status == "lower_bound"
    assert result.solution is None
    assert result.lower_bound <= 2


def test_ida_star_candidate_collection_keeps_timeout_distinct_from_lower_bound():
    cube = CubeState.from_sequence("R U")

    completed = ida_star_collect_solutions(cube, max_depth=1, timeout_seconds=2)
    timed_out = ida_star_collect_solutions(cube, max_depth=5, timeout_seconds=0.0)

    assert completed.status == "lower_bound"
    assert timed_out.status == "timeout"


def test_verify_solution_rejects_malformed_direct_cubie_state_without_crashing():
    malformed = CubeState(cp=(0, 1), co=(0, 0))

    result = verify_solution(malformed, "R")

    assert not result.ok
    assert result.move_count == 1
    assert "Invalid physical cube state" in result.message
    assert "vector lengths" in result.message


def test_korf_solver_labels_exact_when_completed():
    cube = CubeState.from_sequence("R U")
    result = solve_korf_ida(cube, max_depth=5, timeout_seconds=2)
    assert result.status == "exact"
    assert result.solution_length == 2
    assert result.is_verified


@pytest.mark.parametrize(
    "length, scramble",
    _OPTIMALITY_SCRAMBLES,
    ids=[f"len{length}_{i}" for i, (length, _) in enumerate(_OPTIMALITY_SCRAMBLES)],
)
def test_korf_and_ida_match_bfs_exact_distance(length, scramble, warm_pattern_databases):
    """Randomized BFS-exact optimality regression for the Python Korf/IDA* path.

    For each deterministic scramble we compute the ground-truth optimal HTM
    distance with an exhaustive BFS oracle, then require that BOTH the
    pedagogical ``solve_korf_ida`` and the lower-level ``ida_star_solve`` (using
    the admissible ``combined_table_lower_bound``) return a solution of exactly
    that length.  This is the test that would catch a heuristic-inadmissibility
    regression (a non-admissible bound would let IDA* return a shorter-than-real
    or longer-than-optimal path).

    The oracle is capped at :data:`_OPTIMALITY_BFS_DEPTH`; a scramble whose
    optimal distance exceeds the cap yields ``oracle is None`` and the case is
    explicitly skipped (never silently passed).
    """

    cube = CubeState.from_sequence(list(scramble))
    oracle, oracle_result = exact_distance_bfs(cube, max_depth=_OPTIMALITY_BFS_DEPTH)
    if oracle is None:
        pytest.skip(
            f"optimal distance of {scramble} exceeds BFS oracle depth "
            f"{_OPTIMALITY_BFS_DEPTH} (status={oracle_result.status}); "
            "BFS oracle cannot certify the exact distance for this case"
        )

    korf = solve_korf_ida(cube, max_depth=8, timeout_seconds=5)
    assert korf.status == "exact", (scramble, korf.status, korf.notes)
    assert korf.solution_length == oracle, (scramble, oracle, korf.solution_length)
    assert korf.is_verified

    ida = ida_star_solve(
        cube,
        max_depth=8,
        timeout_seconds=5,
        heuristic=combined_table_lower_bound,
    )
    assert ida.solution is not None, (scramble, ida.status)
    assert len(ida.solution) == oracle, (scramble, oracle, len(ida.solution))
    assert verify_solution(cube, ida.solution).ok


# Deeper Python-Korf optimality cases (deep-review findings M11/M14): the pure-
# Python BFS oracle above is capped at depth 4, so the randomized corpus test
# never certifies the Python Korf/IDA* path past distance 4.  These seeded
# cases extend LIVE optimality coverage to distances 5-6 by using the native
# optimal solver as an independent oracle whose expected length is computed at
# test time (never hardcoded), so the check is self-maintaining.  The seeds
# were probed in advance: each pure-Python solve finishes in well under a
# minute with the PDB-backed combined heuristic (sub-second when probed), and
# seed 110 deliberately uses a 7-move scramble whose optimal distance is 6 so
# the oracle is exercised on a case where scramble length != optimal distance.
_DEEP_PYTHON_OPTIMALITY_CASES = (
    # (rng seed, scramble length); probed optimal distances: 5, 6, 6, 5.
    (102, 5),
    (106, 6),
    (110, 7),
    (111, 5),
)


@pytest.mark.native
@pytest.mark.parametrize(
    "seed, length",
    _DEEP_PYTHON_OPTIMALITY_CASES,
    ids=[f"seed{seed}_len{length}" for seed, length in _DEEP_PYTHON_OPTIMALITY_CASES],
)
def test_python_korf_and_ida_match_native_oracle_beyond_bfs_depth(
    seed, length, warm_pattern_databases
):
    """Live distance-5/6 optimality regression for the Python Korf/IDA* path.

    The exhaustive-BFS corpus test above stops certifying at distance 4
    (:data:`_OPTIMALITY_BFS_DEPTH`), so this test closes the gap with the
    native C++ optimal solver as the ground-truth oracle: its ``exact``
    solution length is computed live for each seeded scramble, and BOTH
    ``solve_korf_ida`` and ``ida_star_solve`` (with the admissible
    ``combined_table_lower_bound``) must return a verified solution of exactly
    that length.  A heuristic-inadmissibility regression that only inflates
    ``h`` on states deeper than the BFS cap would be caught here.
    """

    if not edge_pdbs_available():
        pytest.skip("native edge PDBs not generated; cannot run the native optimal oracle")
    if not _native_optimal_binary_present():
        pytest.skip("native optimal_solver binary absent (not yet compiled)")

    scramble = _non_cancelling_scramble(random.Random(seed), length)
    cube = CubeState.from_sequence(scramble)

    oracle = solve_korf_native_optimal(cube, max_depth=20, timeout_seconds=60, threads=4)
    if oracle.status != "exact":
        pytest.skip(
            f"native oracle did not certify the optimal distance for seed {seed} "
            f"within its time box (status={oracle.status}); cannot ground-truth this case"
        )
    assert oracle.is_verified
    # Pin the intended depth band (probed when the seeds were chosen) WITHOUT
    # hardcoding the oracle's answer: the cases must stay strictly deeper than
    # the BFS-certified distance-4 corpus or this test stops adding coverage.
    assert 5 <= oracle.solution_length <= 6, (seed, scramble, oracle.solution_length)

    korf = solve_korf_ida(cube, max_depth=8, timeout_seconds=60, node_limit=20_000_000)
    assert korf.status == "exact", (seed, scramble, korf.status, korf.notes)
    assert korf.solution_length == oracle.solution_length, (
        seed,
        scramble,
        oracle.solution_length,
        korf.solution_length,
    )
    assert korf.is_verified
    assert cube.apply_sequence(korf.solution_moves).is_solved()

    ida = ida_star_solve(
        cube,
        max_depth=8,
        timeout_seconds=60,
        node_limit=20_000_000,
        heuristic=combined_table_lower_bound,
    )
    assert ida.solution is not None, (seed, scramble, ida.status)
    assert len(ida.solution) == oracle.solution_length, (
        seed,
        scramble,
        oracle.solution_length,
        len(ida.solution),
    )
    assert verify_solution(cube, ida.solution).ok


@pytest.mark.native
def test_native_optimal_solver_returns_exact_when_pdbs_are_available():
    if not edge_pdbs_available():
        pytest.skip("native edge PDBs not generated; cannot run native optimal solver")
    if not _native_optimal_binary_present():
        pytest.skip("native optimal_solver binary absent (not yet compiled)")

    cube = CubeState.from_sequence("R U F2")
    result = solve_korf_native_optimal(cube, max_depth=20, timeout_seconds=20)
    assert result.status == "exact"
    assert result.solution_length == 3
    assert result.is_verified
    assert "corner+edge PDB" in result.notes
    assert "child_order=heuristic-desc" in result.notes


@pytest.mark.native
def test_native_nissy_axis_transforms_are_admissible_for_direct_state():
    if not edge_pdbs_available():
        pytest.skip("native edge PDBs not generated; cannot run native optimal solver")
    if not _native_optimal_binary_present():
        pytest.skip("native optimal_solver binary absent (not yet compiled)")

    cube = CubeState.from_facelets(CubeState.from_sequence("R U F2").to_facelets())
    result = solve_korf_native_optimal(
        cube,
        max_depth=20,
        timeout_seconds=20,
        threads=1,
        nissy_heuristic=True,
        source_sequence=None,
    )

    assert result.status == "exact"
    assert result.solution_length == 3
    assert result.is_verified
    assert _note_int(result.notes, "initial_lower_bound") <= result.solution_length
    assert "nissy_axis_transforms=True" in result.notes
    assert "child_order=heuristic-desc" in result.notes


def test_kociemba_adapter_returns_verified_non_exact_solution_when_available():
    cube = CubeState.from_sequence("R U F2")
    result = solve_kociemba_adapter(cube)
    if result.status == "not_applicable":
        assert not result.is_verified
    else:
        assert result.status == "non_exact"
        assert result.is_verified


def test_native_kociemba_phase1_reaches_orientation_slice_subgroup():
    cube = CubeState.from_sequence("F R U R' U' F'")
    result = solve_kociemba_phase1(cube, max_depth=7, timeout_seconds=2)
    assert result.status == "exact"
    assert result.solution is not None
    assert is_kociemba_phase1_goal(cube.apply_sequence(result.solution))


def test_native_kociemba_collects_multiple_phase1_handoffs():
    cube = CubeState.from_sequence("R U F2")
    result = collect_kociemba_phase1_candidates(
        cube,
        max_depth=8,
        timeout_seconds=2,
        node_limit=200_000,
        max_candidates=4,
    )
    assert result.status == "exact"
    assert len(result.solutions) >= 2
    for candidate in result.solutions:
        assert is_kociemba_phase1_goal(cube.apply_sequence(candidate))


def test_native_kociemba_phase2_solves_phase2_subgroup_state():
    cube = CubeState.from_sequence("U R2 F2 D")
    result = solve_kociemba_phase2(cube, max_depth=6, timeout_seconds=2)
    assert result.status == "exact"
    assert result.solution is not None
    assert verify_solution(cube, result.solution).ok


def test_native_kociemba_scoped_returns_verified_solution_for_shallow_case():
    cube = CubeState.from_sequence("R U F")
    result = solve_kociemba_native_scoped(
        cube,
        phase1_max_depth=6,
        phase2_max_depth=6,
        timeout_seconds=2,
    )
    assert result.status == "non_exact"
    assert result.is_verified
    assert verify_solution(cube, result.solution_moves).ok


def test_native_kociemba_scoped_returns_verified_solution_with_phase2_leg():
    cube = CubeState.from_sequence("R U F2 D R2")
    result = solve_kociemba_native_scoped(
        cube,
        phase1_max_depth=10,
        phase2_max_depth=14,
        timeout_seconds=3,
        node_limit=1_000_000,
        phase1_candidate_limit=6,
    )
    assert result.status == "non_exact"
    assert result.is_verified
    assert verify_solution(cube, result.solution_moves).ok
    assert "phase1_candidates_collected=" in result.notes
    assert "phase2_length=0" not in result.notes


def test_native_thistlethwaite_subgroup_membership_predicates():
    solved = CubeState.solved()
    assert is_edge_orientation_solved(solved)
    assert is_g2_subgroup(solved)
    assert is_g3_square_group(solved)

    g2_state = CubeState.from_sequence("U R2")
    assert is_g2_subgroup(g2_state)
    assert not is_g3_square_group(g2_state)

    for move in G2_MOVES:
        assert is_g2_subgroup(CubeState.solved().apply_move(move))
    for move in G3_MOVES:
        assert is_g3_square_group(CubeState.solved().apply_move(move))

    assert not is_g2_subgroup(CubeState.from_sequence("R"))
    assert not is_g3_square_group(CubeState.from_sequence("U"))


def test_native_thistlethwaite_g3_membership_rejects_wrong_tetrad_twist():
    assert g3_subgroup_permutation_counts() == (96, 6912)

    bad_tetrad_twist = CubeState(cp=(0, 1, 2, 4, 6, 5, 3, 7))
    assert bad_tetrad_twist.is_valid()
    assert is_g2_subgroup(bad_tetrad_twist)
    assert not is_g3_square_group(bad_tetrad_twist)


def test_native_thistlethwaite_full_reduces_and_solves_g2_case():
    cube = CubeState.from_sequence("U R2")
    result = solve_thistlethwaite_native_full(
        cube,
        stage1_max_depth=4,
        stage2_max_depth=4,
        stage3_max_depth=5,
        stage4_max_depth=5,
        stage2_candidate_limit=1,
        stage3_candidate_limit=1,
        stage4_candidate_limit=1,
        timeout_seconds=10,
    )
    assert result.status == "non_exact"
    assert result.is_verified
    assert result.table_bytes is not None
    corner_count, edge_count = g3_subgroup_permutation_counts()
    assert result.table_bytes == sum(
        spec.domain_size
        for spec in (CORNER_ORIENTATION_SPEC, EDGE_ORIENTATION_SPEC, UD_SLICE_SPEC)
    ) + corner_count * 8 + edge_count * 12
    assert verify_solution(cube, result.solution_moves).ok
    assert is_edge_orientation_solved(cube.apply_sequence(result.solution_moves))
    assert "Four-phase Thistlethwaite" in result.notes
    assert "stage_lengths=" in result.notes


def test_native_thistlethwaite_full_uses_half_turn_final_phase():
    cube = CubeState.from_sequence("R2 U2 F2")
    result = solve_thistlethwaite_native_scoped(
        cube,
        stage1_max_depth=0,
        stage2_max_depth=0,
        stage3_max_depth=0,
        stage4_max_depth=3,
        stage2_candidate_limit=1,
        stage3_candidate_limit=1,
        stage4_candidate_limit=1,
        timeout_seconds=2,
        node_limit=10_000,
    )
    assert result.status == "non_exact"
    assert result.is_verified
    assert verify_solution(cube, result.solution_moves).ok
    assert all(move in G3_MOVES for move in result.solution_moves)
    assert "stage_lengths=0/0/0/3" in result.notes


def _build_thistlethwaite_corpus() -> list[tuple[str, ...]]:
    rng = random.Random(2026)
    corpus: list[tuple[str, ...]] = []
    for _ in range(15):
        length = rng.randint(8, 20)
        corpus.append(tuple(_non_cancelling_scramble(rng, length)))
    return corpus


_THISTLETHWAITE_SCRAMBLES = _build_thistlethwaite_corpus()


@pytest.mark.parametrize(
    "scramble",
    _THISTLETHWAITE_SCRAMBLES,
    ids=[f"deep{i}_len{len(s)}" for i, s in enumerate(_THISTLETHWAITE_SCRAMBLES)],
)
def test_thistlethwaite_full_solves_deep_states_quickly_and_honestly(scramble):
    """Thistlethwaite must SOLVE every deep (up to 20-move) random state and
    label the result honestly as ``non_exact`` (subgroup-chain, no optimality).

    This is the requirement-defending regression for the rewritten P0-1 path:
    with the cached per-phase coset distance tables every phase terminates, so
    the solver no longer times out / falls back on deep states.  We also bound
    per-solve wall time generously (a few seconds) AFTER a one-time table load,
    so the test fails if a phase regresses to slow bounded IDA*.
    """

    import time

    cube = CubeState.from_sequence(list(scramble))
    started = time.perf_counter()
    result = solve_thistlethwaite_native_full(cube)
    elapsed = time.perf_counter() - started

    assert result.status == "non_exact", (scramble, result.status, result.notes)
    assert result.is_verified
    assert verify_solution(cube, result.solution_moves).ok, scramble
    assert cube.apply_sequence(result.solution_moves).is_solved(), scramble
    # Table-guided descent is near-instant; allow generous slack for the very
    # first parametrized case (cold table load) and machine contention.
    assert elapsed < 30.0, (scramble, elapsed)


def test_distance_recognition_separates_exact_and_lower_bound():
    exact = recognize_distance(CubeState.from_sequence("R U"), bfs_depth=4, ida_depth=4)
    assert exact.kind == "exact_distance"
    assert exact.distance_value == 2

    deeper = recognize_distance(CubeState.from_sequence("R U F B L D R2"), bfs_depth=1, ida_depth=1, timeout_seconds=0.01)
    assert deeper.kind in {"lower_bound", "exact_distance"}
    if deeper.kind == "lower_bound":
        assert deeper.distance_value is not None


def test_distance_recognition_default_path_emits_unknown_timeout():
    """A deep state on the DEFAULT (no native/H48) path must report
    ``unknown_timeout`` when the depth-20 IDA* hits the wall clock.

    This defends the contract category fixed in ``distance.py``: a timed-out
    IDA* is no longer mislabelled ``lower_bound``.  We use a long, hard scramble
    with a tiny BFS depth (so BFS cannot solve it first) and a near-zero timeout
    so the depth-20 IDA* cannot complete.
    """

    deep = CubeState.from_sequence(
        "R U F B L D R2 F2 U2 L2 B R U D F2 L D2 B2 R F"
    )
    result = recognize_distance(
        deep,
        bfs_depth=2,
        ida_depth=20,
        timeout_seconds=0.001,
    )

    assert result.kind == "unknown_timeout", (result.kind, result.proof_notes)
    assert result.method == "combined_table_lower_bound"
    assert result.distance_value is not None
    assert "ida_status=timeout" in result.proof_notes


def test_distance_recognition_default_path_emits_lower_bound_when_completed():
    """A completed depth-bounded IDA* (no timeout, no solution found within the
    depth) must report ``lower_bound`` — distinct wording from the timeout case.
    """

    state = CubeState.from_sequence("R U F B L D R2")
    result = recognize_distance(
        state,
        bfs_depth=1,
        ida_depth=2,
        timeout_seconds=30,
    )

    assert result.kind == "lower_bound", (result.kind, result.proof_notes)
    assert result.method == "combined_table_lower_bound"
    assert result.distance_value is not None
    assert "no shorter solution" in result.proof_notes


def test_distance_recognition_rejects_invalid_cubie_state():
    invalid = CubeState(eo=(1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0))

    result = recognize_distance(invalid, bfs_depth=1, ida_depth=1)

    assert result.kind == "invalid_state"
    assert result.distance_value is None
    assert result.method == "validity"
    assert "parity" in result.proof_notes


def test_distance_recognition_h48_timeout_is_unknown_timeout(monkeypatch):
    from rubik_optimal.solvers import h48_native as h48_native_module

    cube = CubeState.from_sequence("R U F2")

    def fake_h48_timeout(cube_arg, **_kwargs):
        return SolverResult(
            solver_name="h48_native_h48h0",
            input_state=cube_arg.to_facelets(),
            solution_moves=[],
            solution_length=None,
            metric="HTM",
            runtime_seconds=0.01,
            expanded_nodes=7,
            generated_nodes=7,
            table_bytes=0,
            status="timeout",
            is_verified=False,
            notes="test forced timeout",
        )

    monkeypatch.setattr(h48_native_module, "solve_h48_native_optimal", fake_h48_timeout)

    result = recognize_distance(
        cube,
        bfs_depth=0,
        ida_depth=0,
        timeout_seconds=0.01,
        h48_native=True,
    )

    assert result.kind == "unknown_timeout"
    assert result.distance_value is not None
    assert result.method == "h48_native_h48h0_depth_20"
    assert "solver_status=timeout" in result.proof_notes


def test_distance_recognition_can_use_h48_state_oracle():
    root = repository_root()
    assert h48_table_path(root=root, profile="thesis", seed=2026, solver="h48h0").exists()

    cube = CubeState.from_facelets(CubeState.from_sequence("R U F2").to_facelets())
    result = recognize_distance(
        cube,
        bfs_depth=0,
        ida_depth=0,
        timeout_seconds=10,
        h48_native=True,
        threads=8,
    )

    assert result.kind == "exact_distance"
    assert result.distance_value == 3
    assert result.method == "h48_native_h48h0_depth_20"
    assert "input_mode=cube_state" in result.proof_notes

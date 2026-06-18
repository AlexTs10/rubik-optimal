"""§5-style gate for the provably-optimal two-phase solver (WORSTCASE Path 3).

The solver in ``rubik_optimal.solvers.kociemba_optimal`` claims HTM optimality, so
(per the design doc's #1 risk) every claim is checked:

1. Enumeration soundness: ``_enumerate_phase1_g1_states_at_depth`` yields only G1
   states, with distinct phase-2 keys, and finds the solved state at depth 0.
2. Optimality vs BFS (the sole ground truth) on shallow states: a verified
   ``status="exact"`` length must equal the exhaustive BFS distance -- never a
   hand-guessed scramble length (e.g. ``F R U R' U'`` is optimally 5, not 4).
3. Honest degradation: with an intentionally tiny budget on a deeper state, the
   solver must NOT report ``exact``; any returned solution must still verify.
4. Optimality vs the native Korf oracle on a moderate state (``native`` marker,
   skipped when the binary/PDBs are absent -- never a silent pass).
"""

from __future__ import annotations

import time

import pytest

from rubik_optimal.cube import CubeState
from rubik_optimal.moves import ALL_MOVES, same_face
from rubik_optimal.search.bfs import exact_distance_bfs
from rubik_optimal.solvers.kociemba import is_kociemba_phase1_goal, kociemba_phase1_lower_bound
from rubik_optimal.solvers.kociemba_optimal import (
    _Budget,
    _enumerate_phase1_g1_states_at_depth,
    _phase2_state_key,
    solve_kociemba_two_phase_optimal,
)


def _scrambler(seed: int):
    import random

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


def _phase1_tables():
    from rubik_optimal.solvers.kociemba import _phase1_coordinate_tables

    return _phase1_coordinate_tables()


# ---------------------------------------------------------------------------
# 1. Enumeration soundness.
# ---------------------------------------------------------------------------
def test_phase1_enumeration_solved_state_at_depth_zero():
    move_tables, pruning_tables = _phase1_tables()
    budget = _Budget(deadline=time.perf_counter() + 30, phase1_node_limit=10_000_000)
    states = _enumerate_phase1_g1_states_at_depth(
        CubeState.solved(), 0, move_tables, pruning_tables, budget
    )
    assert states is not None
    assert len(states) == 1
    maneuver, g1_cube = states[0]
    assert maneuver == []
    assert is_kociemba_phase1_goal(g1_cube)


def test_phase1_enumeration_yields_only_distinct_g1_states():
    move_tables, pruning_tables = _phase1_tables()
    scramble = _scrambler(11)
    cube = CubeState.from_sequence(scramble(7))
    depth = kociemba_phase1_lower_bound(cube)
    budget = _Budget(deadline=time.perf_counter() + 60, phase1_node_limit=20_000_000)
    states = _enumerate_phase1_g1_states_at_depth(cube, depth, move_tables, pruning_tables, budget)
    assert states is not None and len(states) >= 1
    keys = set()
    for maneuver, g1_cube in states:
        # Each returned maneuver genuinely reaches G1...
        assert is_kociemba_phase1_goal(g1_cube)
        assert g1_cube == cube.apply_sequence(maneuver)
        assert len(maneuver) == depth
        # ...and the G1 states are pairwise distinct (deduped by phase-2 key).
        key = _phase2_state_key(g1_cube)
        assert key not in keys
        keys.add(key)


# ---------------------------------------------------------------------------
# 2. Optimality vs BFS on shallow states (BFS is the sole ground truth).
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "scramble",
    [[], ["R"], ["R", "U"], ["R", "U", "F2"], ["F", "R", "U", "R'", "U'"]],
)
def test_two_phase_optimal_matches_bfs_exact_distance(scramble):
    cube = CubeState.from_sequence(scramble)
    oracle, oracle_result = exact_distance_bfs(cube, max_depth=max(1, len(scramble)) + 1)
    assert oracle is not None and oracle_result.status == "exact"

    result = solve_kociemba_two_phase_optimal(cube, max_total_depth=14, time_budget_seconds=60.0)
    assert result.status == "exact", (scramble, result.status, result.notes)
    assert result.is_verified
    assert result.solution_length == oracle, (scramble, oracle, result.solution_length)


def test_two_phase_optimal_solved_state_is_zero_and_exact():
    result = solve_kociemba_two_phase_optimal(CubeState.solved())
    assert result.status == "exact"
    assert result.solution_length == 0
    assert result.is_verified


# ---------------------------------------------------------------------------
# 3. Honest degradation: a tiny budget must not yield a false optimality claim.
# ---------------------------------------------------------------------------
def test_two_phase_optimal_does_not_overclaim_under_tiny_budget():
    scramble = _scrambler(2026)
    cube = CubeState.from_sequence(scramble(14))
    result = solve_kociemba_two_phase_optimal(
        cube, max_total_depth=20, time_budget_seconds=0.5, phase1_node_limit=50_000
    )
    # The defining honesty property: never claim "exact" without a completed proof.
    assert result.status != "exact", result.notes
    # Any returned solution must still actually solve the cube.
    if result.solution_moves:
        assert result.is_verified
        assert CubeState.from_sequence(scramble(14)).apply_sequence(result.solution_moves).is_solved()
    assert "proven_optimal=False" in result.notes


# ---------------------------------------------------------------------------
# 4. Optimality vs the native Korf oracle on a moderate state.
# ---------------------------------------------------------------------------
def _native_korf_oracle_skip_reason() -> str | None:
    """Return a skip reason when a table/binary the native oracle needs is absent."""

    from rubik_optimal.tables.corner_pdb import corner_pdb_available
    from rubik_optimal.tables.edge_pdb import edge_pdbs_available
    from rubik_optimal.tables.h48 import repository_root

    if not corner_pdb_available():
        return "native corner PDB not generated; cannot run native Korf oracle"
    if not edge_pdbs_available():
        return "native edge PDBs not generated; cannot run native Korf oracle"
    if not (repository_root() / "native" / "build" / "optimal_solver").exists():
        return "native optimal_solver binary absent"
    return None


@pytest.mark.native
def test_two_phase_optimal_matches_native_korf_oracle():
    from rubik_optimal.solvers import optimal_native
    from rubik_optimal.tables.edge_pdb import edge_pdbs_available
    from rubik_optimal.tables.h48 import repository_root

    if not edge_pdbs_available():
        pytest.skip("native edge PDBs not generated; cannot run native Korf oracle")
    if not (repository_root() / "native" / "build" / "optimal_solver").exists():
        pytest.skip("native optimal_solver binary absent")

    cube = CubeState.from_sequence(_scrambler(7)(8))
    korf = optimal_native.solve_korf_native_optimal(cube, max_depth=20, timeout_seconds=60, threads=4)
    assert korf.status == "exact"

    result = solve_kociemba_two_phase_optimal(cube, max_total_depth=20, time_budget_seconds=90.0)
    assert result.status == "exact", result.notes
    assert result.is_verified
    assert result.solution_length == korf.solution_length, (korf.solution_length, result.solution_length)


# ---------------------------------------------------------------------------
# 5. Deep mutual-oracle gate (deep-review finding M11): the deepest LIVE
#    optimality cross-check used to be a single depth-8 scramble, so every
#    exactness claim past distance 8 rested on saved-artifact flags.  These
#    seeded nominal-depth-10..12 cases make two INDEPENDENT optimality provers
#    -- the native C++ Korf IDA* and the pure-Python two-phase-optimal solver
#    (different algorithms, different table stacks) -- certify the same state
#    live and agree on the optimal length, with both solutions replayed to
#    solved.  Neither solver's answer is hardcoded; agreement IS the oracle.
#    Seeds were probed in advance so both proofs complete well inside the time
#    boxes (probed optimal distances 10/11/10; two-phase proof <= ~30 s each,
#    native Korf < 1 s).  The two-phase proof cost is state-dependent: several
#    probed distance-11/12 states did NOT certify within 90-120 s, which is
#    what bounds how deep this gate can go live.
# ---------------------------------------------------------------------------
_MUTUAL_ORACLE_CASES = (
    # (rng seed, nominal scramble length); probed optimal distances 10, 11, 10.
    (301, 10),
    (302, 11),
    (313, 12),
)


@pytest.mark.native
@pytest.mark.parametrize(
    "seed, length",
    _MUTUAL_ORACLE_CASES,
    ids=[f"seed{seed}_len{length}" for seed, length in _MUTUAL_ORACLE_CASES],
)
def test_two_phase_optimal_and_native_korf_mutually_certify_depth_10_plus(seed, length):
    from rubik_optimal.solvers import optimal_native

    reason = _native_korf_oracle_skip_reason()
    if reason is not None:
        pytest.skip(reason)

    cube = CubeState.from_sequence(_scrambler(seed)(length))

    # Time-boxed native Korf proof (probed < 1 s at these depths).
    korf = optimal_native.solve_korf_native_optimal(
        cube, max_depth=20, timeout_seconds=120, threads=4
    )
    assert korf.status == "exact", (seed, korf.status, korf.notes)
    assert korf.is_verified
    assert cube.apply_sequence(korf.solution_moves).is_solved(), (seed, korf.solution_moves)

    # Pin the intended depth band: each case must stay strictly deeper than the
    # depth-8 cross-check above, or this gate stops extending live coverage.
    assert korf.solution_length >= 10, (seed, korf.solution_length)

    # Time-boxed two-phase-optimal proof (probed <= ~30 s at these depths).
    two_phase = solve_kociemba_two_phase_optimal(
        cube, max_total_depth=20, time_budget_seconds=180.0
    )
    assert two_phase.status == "exact", (seed, two_phase.status, two_phase.notes)
    assert two_phase.is_verified
    assert cube.apply_sequence(two_phase.solution_moves).is_solved(), (
        seed,
        two_phase.solution_moves,
    )

    # The mutual-oracle property: two independent optimality proofs must agree.
    assert two_phase.solution_length == korf.solution_length, (
        seed,
        korf.solution_length,
        two_phase.solution_length,
    )

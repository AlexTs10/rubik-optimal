from rubik_optimal.pocket.cube import POCKET_MOVES, POCKET_STATE_COUNT, PocketState
from rubik_optimal.pocket.optimal import (
    POCKET_ANTIPODE_COUNT,
    POCKET_DISTANCE_DISTRIBUTION,
    POCKET_GODS_NUMBER,
    compute_pocket_distribution,
    pocket_optimal_solution,
    verify_pocket_tables_against_cubie_moves,
)
from rubik_optimal.solvers.pocket_cube import solve_pocket_cube_optimal


def test_pocket_coordinate_roundtrip_and_state_count():
    assert POCKET_STATE_COUNT == 3_674_160
    for sequence in ["", "R", "U R F", "R U R' F2"]:
        state = PocketState.from_sequence(sequence)
        assert PocketState.from_coord(state.coord()) == state


def test_pocket_moves_preserve_fixed_reference_corner():
    state = PocketState.solved()
    for move in POCKET_MOVES:
        moved = state.apply_move(move)
        moved.validate()
        assert PocketState.from_coord(moved.coord()) == moved


def test_pocket_depth_limited_distribution_starts_correctly():
    result = compute_pocket_distribution(max_depth=2)
    assert not result.complete
    assert result.distribution[0] == 1
    assert result.distribution[1] == 9
    assert result.max_distance == 2
    assert result.state_count > 10


def test_pocket_optimal_solver_verifies_shallow_case():
    state = PocketState.from_sequence("R U F")
    solution, expanded, generated = pocket_optimal_solution(state, max_depth=6)
    assert solution is not None
    assert len(solution) == 3
    assert state.apply_sequence(solution).is_solved()
    assert expanded > 0
    assert generated > 0

    result = solve_pocket_cube_optimal(state, max_depth=6)
    assert result.status == "exact"
    assert result.is_verified
    assert result.solution_length == 3


def test_pocket_canonical_distribution_is_internally_consistent():
    # The canonical distribution must describe the full 7! * 3^6 state space,
    # start with the solved state and the nine single moves, and peak at the
    # normalized 2x2x2 God's Number in the half-turn metric.
    assert sum(POCKET_DISTANCE_DISTRIBUTION.values()) == POCKET_STATE_COUNT
    assert sum(POCKET_DISTANCE_DISTRIBUTION.values()) == 5040 * 729
    assert POCKET_DISTANCE_DISTRIBUTION[0] == 1
    assert POCKET_DISTANCE_DISTRIBUTION[1] == len(POCKET_MOVES) == 9
    assert max(POCKET_DISTANCE_DISTRIBUTION) == POCKET_GODS_NUMBER == 11
    assert POCKET_DISTANCE_DISTRIBUTION[POCKET_GODS_NUMBER] == POCKET_ANTIPODE_COUNT == 2644
    # Contiguous depths with strictly positive counts up to the maximum.
    assert sorted(POCKET_DISTANCE_DISTRIBUTION) == list(range(POCKET_GODS_NUMBER + 1))
    assert all(count > 0 for count in POCKET_DISTANCE_DISTRIBUTION.values())


def test_pocket_full_distribution_matches_canonical():
    # The exhaustive BFS over the whole space must reproduce the canonical
    # God's-Number distribution exactly. This guards against a coordinate or
    # move-table corruption that would still be complete and sum correctly.
    result = compute_pocket_distribution()
    assert result.complete
    assert result.state_count == POCKET_STATE_COUNT
    assert result.max_distance == POCKET_GODS_NUMBER
    assert result.distribution == POCKET_DISTANCE_DISTRIBUTION
    assert result.expanded_nodes == POCKET_STATE_COUNT
    assert result.generated_nodes == POCKET_STATE_COUNT - 1


def test_pocket_table_transitions_match_cubie_moves():
    # Independent correctness proof: the coordinate move tables (built from a
    # permutation/orientation decomposition) must agree with the cubie-level
    # model on every transition of every reachable shallow state.
    check = verify_pocket_tables_against_cubie_moves(max_depth=5)
    assert check.ok, check.mismatches
    assert check.states_checked == sum(
        POCKET_DISTANCE_DISTRIBUTION[depth] for depth in range(6)
    )
    assert check.transitions_checked == check.states_checked * len(POCKET_MOVES)

from scripts.run_fast_optimal_oracle_api import api_cases


def test_fast_optimal_oracle_api_cases_cover_state_sequence_and_facelets():
    cases = api_cases(2026)
    by_id = {case.case_id: case for case in cases}

    assert set(by_id) == {"solved", "sequence_shallow", "facelets_shallow", "deterministic_depth_10"}
    assert by_id["solved"].expected_distance == 0
    assert by_id["sequence_shallow"].expected_distance == 3
    assert by_id["facelets_shallow"].expected_distance == 3
    assert by_id["deterministic_depth_10"].expected_distance is None
    assert all(case.cube.verify_physical()[0] == 0 for case in cases)


def test_fast_optimal_oracle_api_hard_cases_are_explicitly_opt_in():
    base_ids = {case.case_id for case in api_cases(2026)}
    hard_ids = {case.case_id for case in api_cases(2026, include_hard=True)}

    assert "superflip_distance_20" not in base_ids
    assert {"deterministic_depth_25", "superflip_distance_20"} <= hard_ids

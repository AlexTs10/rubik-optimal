from rubik_optimal.cube import CubeState
from rubik_optimal.solvers.base import SolverResult

import scripts.run_korf_native_evidence as korf_evidence


def test_korf_evidence_real_solver_bfs_cross_check_and_depth6_exact():
    shallow = korf_evidence.evaluate_case(
        korf_evidence.KorfEvidenceCase(
            "shallow_r_u_f2_bfs_exact",
            ("R", "U", "F2"),
            bfs_max_depth=3,
            expected_exact_depth=3,
        ),
        max_depth=6,
        timeout_seconds=60,
        node_limit=5_000_000,
    )
    assert shallow["status"] == "exact"
    assert shallow["solution_length"] == 3
    assert shallow["verified"] is True
    assert shallow["bfs_cross_checked"] is True
    assert shallow["proof_method"] == "bfs_cross_check_plus_native_ida_star"

    depth6 = korf_evidence.evaluate_case(
        korf_evidence.KorfEvidenceCase(
            "deterministic_depth_6_native_ida",
            tuple(korf_evidence.deterministic_scramble(6, 2026, offset=601)),
            expected_exact_depth=6,
        ),
        max_depth=8,
        timeout_seconds=60,
        node_limit=5_000_000,
    )
    assert depth6["status"] == "exact"
    assert depth6["solution_length"] == 6
    assert depth6["verified"] is True
    assert depth6["bfs_status"] == "not_run_too_expensive"
    assert depth6["proof_method"] == "native_ida_star_complete_admissible_search"
    assert depth6["uses_h48"] is False
    assert depth6["uses_nissy"] is False


def test_korf_native_evidence_payload_is_native_only(monkeypatch, tmp_path):
    monkeypatch.setattr(
        korf_evidence,
        "default_cases",
        lambda seed, *, include_depth12_probe=True: [
            korf_evidence.KorfEvidenceCase("solved", (), bfs_max_depth=0, expected_exact_depth=0),
            korf_evidence.KorfEvidenceCase("depth6", ("R", "U", "F2", "L", "D", "B2")),
            korf_evidence.KorfEvidenceCase("depth8", ("R", "U", "F2", "L", "D", "B2", "R2", "U'")),
        ],
    )

    def fake_solve(cube: CubeState, **kwargs):
        is_solved = cube.is_solved()
        length = 0 if is_solved else len(kwargs)
        return SolverResult(
            solver_name="korf_ida_star_scoped",
            input_state=cube.to_facelets(),
            solution_moves=[] if is_solved else ["test"],
            solution_length=length,
            metric="HTM",
            runtime_seconds=0.001,
            expanded_nodes=0,
            generated_nodes=0,
            table_bytes=123,
            status="exact",
            is_verified=True,
            notes="fake native Korf/IDA* row",
        )

    monkeypatch.setattr(korf_evidence, "solve_korf_ida", fake_solve)
    payload = korf_evidence.build_payload(
        root=tmp_path,
        profile="unit",
        seed=2026,
        max_depth=8,
        timeout_seconds=1,
        node_limit=100,
        include_depth12_probe=False,
    )

    assert payload["backend_family"] == "native_korf_ida_star"
    assert payload["uses_h48"] is False
    assert payload["uses_nissy"] is False
    assert payload["uses_external_optimal_backend"] is False
    assert payload["all_rows_native_only"] is True
    assert payload["all_bfs_rows_cross_checked"] is True
    assert payload["has_depth_6_or_deeper_exact_native_row"] is True
    assert payload["has_depth_8_or_deeper_exact_native_row"] is True

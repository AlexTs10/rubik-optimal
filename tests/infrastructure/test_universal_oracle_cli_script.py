import subprocess
import sys
from pathlib import Path

from rubik_optimal.cube import CubeState
from scripts.run_universal_oracle_cli import (
    _ALLOWED_UNIVERSAL_SELECTED_BACKENDS,
    _adaptive_command_timeout_seconds,
    _has_complete_row_set,
    _nissy_benchmark_cases,
)
from scripts.import_nissy_benchmark_certificates import import_rows


def test_nissy_benchmark_cases_are_direct_facelet_known_distance_rows(tmp_path):
    scrambles = tmp_path / ".codex_external" / "nissy-core" / "benchmarks" / "scrambles"
    scrambles.mkdir(parents=True)
    (scrambles / "scrambles-17.txt").write_text(
        "R U F2\n"
        "U R2 F\n",
        encoding="utf-8",
    )

    rows = _nissy_benchmark_cases(tmp_path, distances=[17], limit_per_distance=1)

    assert len(rows) == 1
    row = rows[0]
    assert row.case_id == "nissy_benchmark_distance_17_0"
    assert row.case_kind == "nissy_core_benchmark_known_distance"
    assert row.expected_distance == 17
    assert row.source_depth == 3
    assert row.source_label == str(Path(".codex_external/nissy-core/benchmarks/scrambles/scrambles-17.txt"))
    assert row.facelets == CubeState.from_sequence("R U F2").to_facelets()


def test_universal_cli_allows_rubikoptimal_symmetry_race_backend():
    assert "rubikoptimal-symmetry-race" in _ALLOWED_UNIVERSAL_SELECTED_BACKENDS
    assert "resident-race-prepass" in _ALLOWED_UNIVERSAL_SELECTED_BACKENDS
    assert "h48-upper-bound-proof" in _ALLOWED_UNIVERSAL_SELECTED_BACKENDS


def test_universal_cli_help_exposes_shared_symmetry_ordering_alias():
    completed = subprocess.run(
        [sys.executable, "scripts/run_universal_oracle_cli.py", "--help"],
        check=True,
        text=True,
        capture_output=True,
    )

    assert "--symmetry-order-by-h48-lower-bound" in completed.stdout
    assert "--symmetry-lower-bound-order-timeout" in completed.stdout
    assert "--kociemba-upper-bound-symmetry-variants" in completed.stdout
    assert "--h48-upper-bound-proof-timeout" in completed.stdout
    assert "--h48-upper-bound-proof-max-gap" in completed.stdout


def test_nissy_benchmark_cases_can_start_from_offset(tmp_path):
    scrambles = tmp_path / ".codex_external" / "nissy-core" / "benchmarks" / "scrambles"
    scrambles.mkdir(parents=True)
    (scrambles / "scrambles-20.txt").write_text(
        "R U F2\n"
        "U R2 F\n"
        "L2 D B\n",
        encoding="utf-8",
    )

    rows = _nissy_benchmark_cases(
        tmp_path,
        distances=[20],
        limit_per_distance=1,
        offset_per_distance=1,
    )

    assert len(rows) == 1
    row = rows[0]
    assert row.case_id == "nissy_benchmark_distance_20_1"
    assert row.expected_distance == 20
    assert row.facelets == CubeState.from_sequence("U R2 F").to_facelets()


def test_nissy_benchmark_certificate_importer_verifies_inverse_rows(tmp_path):
    scrambles = tmp_path / ".codex_external" / "nissy-core" / "benchmarks" / "scrambles"
    scrambles.mkdir(parents=True)
    (scrambles / "scrambles-20.txt").write_text(
        "R U F2 L B2 D R2 U' F L2 B D2 R' U2 F2 L' B' U R2 D2\n",
        encoding="utf-8",
    )

    rows, errors = import_rows(tmp_path, distances=[20])

    assert errors == []
    assert len(rows) == 1
    row = rows[0]
    assert row.case_id == "nissy_benchmark_distance_20_0"
    assert row.distance == 20
    assert row.state == CubeState.from_sequence(row.source_sequence).to_facelets()
    assert len(row.solution_moves) == 20


def test_nissy_benchmark_certificate_importer_rejects_label_mismatch(tmp_path):
    scrambles = tmp_path / ".codex_external" / "nissy-core" / "benchmarks" / "scrambles"
    scrambles.mkdir(parents=True)
    (scrambles / "scrambles-20.txt").write_text("R U F2\n", encoding="utf-8")

    rows, errors = import_rows(tmp_path, distances=[20])

    assert rows == []
    assert errors
    assert "does not match known-distance label 20" in errors[0]


def test_adaptive_command_timeout_accounts_for_all_exact_phases():
    timeout = _adaptive_command_timeout_seconds(
        solver_timeout_seconds=180,
        resident_h48_batch_timeout_seconds=180,
        case_count=1,
        portfolio_prepass_enabled=True,
        portfolio_prepass_timeout_seconds=None,
        h48_symmetry_variants=2,
        h48_symmetry_timeout_seconds=45,
    )

    assert timeout == 645


def test_adaptive_command_timeout_uses_separate_portfolio_prepass_budget():
    timeout = _adaptive_command_timeout_seconds(
        solver_timeout_seconds=300,
        resident_h48_batch_timeout_seconds=300,
        case_count=1,
        portfolio_prepass_enabled=True,
        portfolio_prepass_timeout_seconds=30,
        h48_symmetry_variants=0,
        h48_symmetry_timeout_seconds=60,
    )

    assert timeout == 690


def test_adaptive_command_timeout_uses_separate_late_fallback_budget():
    timeout = _adaptive_command_timeout_seconds(
        solver_timeout_seconds=300,
        resident_h48_batch_timeout_seconds=180,
        case_count=1,
        portfolio_prepass_enabled=True,
        portfolio_prepass_timeout_seconds=30,
        portfolio_fallback_timeout_seconds=120,
        h48_symmetry_variants=0,
        h48_symmetry_timeout_seconds=60,
    )

    assert timeout == 390


def test_adaptive_command_timeout_accounts_for_late_nissy_core_direct_fallback_budget():
    timeout = _adaptive_command_timeout_seconds(
        solver_timeout_seconds=300,
        resident_h48_batch_timeout_seconds=180,
        case_count=1,
        portfolio_prepass_enabled=True,
        portfolio_prepass_timeout_seconds=30,
        portfolio_fallback_timeout_seconds=120,
        portfolio_fallback_nissy_core_direct_timeout_seconds=15,
        h48_symmetry_variants=0,
        h48_symmetry_timeout_seconds=60,
    )

    assert timeout == 405


def test_adaptive_command_timeout_treats_nissy_core_direct_symmetry_as_global_budget():
    timeout = _adaptive_command_timeout_seconds(
        solver_timeout_seconds=300,
        resident_h48_batch_timeout_seconds=180,
        case_count=1,
        portfolio_prepass_enabled=True,
        portfolio_prepass_timeout_seconds=30,
        portfolio_fallback_timeout_seconds=120,
        portfolio_fallback_nissy_core_direct_timeout_seconds=None,
        nissy_core_direct_symmetry_variants=23,
        nissy_core_direct_symmetry_timeout_seconds=180,
        nissy_core_direct_symmetry_max_concurrency=2,
        h48_symmetry_variants=0,
        h48_symmetry_timeout_seconds=60,
    )

    assert timeout == 570


def test_adaptive_command_timeout_accounts_for_nissy_symmetry_budget():
    timeout = _adaptive_command_timeout_seconds(
        solver_timeout_seconds=300,
        resident_h48_batch_timeout_seconds=180,
        case_count=1,
        portfolio_prepass_enabled=True,
        portfolio_prepass_timeout_seconds=30,
        portfolio_fallback_timeout_seconds=120,
        portfolio_fallback_nissy_core_direct_timeout_seconds=None,
        nissy_symmetry_variants=23,
        nissy_symmetry_timeout_seconds=90,
        h48_symmetry_variants=0,
        h48_symmetry_timeout_seconds=60,
    )

    assert timeout == 480


def test_adaptive_command_timeout_accounts_for_shared_symmetry_ordering_budget():
    timeout = _adaptive_command_timeout_seconds(
        solver_timeout_seconds=300,
        resident_h48_batch_timeout_seconds=180,
        case_count=1,
        portfolio_prepass_enabled=True,
        portfolio_prepass_timeout_seconds=30,
        portfolio_fallback_timeout_seconds=120,
        portfolio_fallback_nissy_core_direct_timeout_seconds=None,
        h48_symmetry_variants=2,
        h48_symmetry_timeout_seconds=45,
        nissy_symmetry_variants=23,
        nissy_symmetry_timeout_seconds=90,
        symmetry_order_by_h48_lower_bound=True,
        symmetry_lower_bound_order_timeout_seconds=25,
    )

    assert timeout == 575


def test_adaptive_command_timeout_accounts_for_h48_upper_bound_proof_budget():
    timeout = _adaptive_command_timeout_seconds(
        solver_timeout_seconds=300,
        resident_h48_batch_timeout_seconds=180,
        case_count=2,
        portfolio_prepass_enabled=True,
        portfolio_prepass_timeout_seconds=30,
        portfolio_fallback_timeout_seconds=120,
        portfolio_fallback_nissy_core_direct_timeout_seconds=15,
        h48_upper_bound_proof_timeout_seconds=25,
        h48_symmetry_variants=0,
        h48_symmetry_timeout_seconds=60,
    )

    assert timeout == 635


def test_adaptive_command_timeout_accounts_for_native_korf_upper_bound_proof_budget():
    timeout = _adaptive_command_timeout_seconds(
        solver_timeout_seconds=300,
        resident_h48_batch_timeout_seconds=180,
        case_count=2,
        portfolio_prepass_enabled=True,
        portfolio_prepass_timeout_seconds=30,
        portfolio_fallback_timeout_seconds=120,
        portfolio_fallback_nissy_core_direct_timeout_seconds=15,
        h48_upper_bound_proof_timeout_seconds=25,
        native_korf_upper_bound_proof_timeout_seconds=35,
        h48_symmetry_variants=0,
        h48_symmetry_timeout_seconds=60,
    )

    assert timeout == 705


def test_adaptive_command_timeout_accounts_for_rubikoptimal_budgets():
    timeout = _adaptive_command_timeout_seconds(
        solver_timeout_seconds=300,
        resident_h48_batch_timeout_seconds=180,
        case_count=2,
        portfolio_prepass_enabled=True,
        portfolio_prepass_timeout_seconds=30,
        portfolio_fallback_timeout_seconds=120,
        portfolio_fallback_nissy_core_direct_timeout_seconds=15,
        rubikoptimal_prepass_timeout_seconds=40,
        rubikoptimal_race_timeout_seconds=50,
        rubikoptimal_fallback_timeout_seconds=60,
        h48_symmetry_variants=0,
        h48_symmetry_timeout_seconds=60,
    )

    assert timeout == 885


def test_adaptive_command_timeout_accounts_for_resident_race_prepass_budget():
    timeout = _adaptive_command_timeout_seconds(
        solver_timeout_seconds=300,
        resident_h48_batch_timeout_seconds=180,
        case_count=2,
        portfolio_prepass_enabled=True,
        portfolio_prepass_timeout_seconds=30,
        portfolio_fallback_timeout_seconds=120,
        portfolio_fallback_nissy_core_direct_timeout_seconds=15,
        rubikoptimal_prepass_timeout_seconds=40,
        rubikoptimal_race_timeout_seconds=50,
        resident_race_prepass_timeout_seconds=25,
        rubikoptimal_fallback_timeout_seconds=60,
        h48_symmetry_variants=0,
        h48_symmetry_timeout_seconds=60,
    )

    assert timeout == 935


def test_adaptive_command_timeout_accounts_for_rubikoptimal_symmetry_budget():
    timeout = _adaptive_command_timeout_seconds(
        solver_timeout_seconds=300,
        resident_h48_batch_timeout_seconds=180,
        case_count=1,
        portfolio_prepass_enabled=True,
        portfolio_prepass_timeout_seconds=30,
        portfolio_fallback_timeout_seconds=120,
        portfolio_fallback_nissy_core_direct_timeout_seconds=15,
        rubikoptimal_prepass_timeout_seconds=40,
        rubikoptimal_symmetry_variants=3,
        rubikoptimal_symmetry_timeout_seconds=20,
        rubikoptimal_race_timeout_seconds=50,
        rubikoptimal_fallback_timeout_seconds=60,
        h48_symmetry_variants=0,
        h48_symmetry_timeout_seconds=60,
    )

    assert timeout == 575


def test_adaptive_command_timeout_uses_rubikoptimal_symmetry_as_global_phase():
    timeout = _adaptive_command_timeout_seconds(
        solver_timeout_seconds=300,
        resident_h48_batch_timeout_seconds=180,
        case_count=1,
        portfolio_prepass_enabled=True,
        portfolio_prepass_timeout_seconds=30,
        portfolio_fallback_timeout_seconds=120,
        portfolio_fallback_nissy_core_direct_timeout_seconds=15,
        rubikoptimal_prepass_timeout_seconds=40,
        rubikoptimal_symmetry_variants=5,
        rubikoptimal_symmetry_timeout_seconds=20,
        rubikoptimal_symmetry_max_concurrency=2,
        rubikoptimal_race_timeout_seconds=50,
        rubikoptimal_fallback_timeout_seconds=60,
        h48_symmetry_variants=0,
        h48_symmetry_timeout_seconds=60,
    )

    assert timeout == 575


def test_adaptive_command_timeout_can_be_overridden():
    timeout = _adaptive_command_timeout_seconds(
        solver_timeout_seconds=180,
        resident_h48_batch_timeout_seconds=180,
        case_count=1,
        portfolio_prepass_enabled=True,
        portfolio_prepass_timeout_seconds=None,
        h48_symmetry_variants=2,
        h48_symmetry_timeout_seconds=45,
        explicit_command_timeout_seconds=123,
    )

    assert timeout == 123


def test_complete_row_set_rejects_empty_timeout_payloads():
    assert not _has_complete_row_set([], 1)
    assert not _has_complete_row_set([], 0)
    assert not _has_complete_row_set([{"status": "exact"}], 2)
    assert _has_complete_row_set([{"status": "exact"}], 1)

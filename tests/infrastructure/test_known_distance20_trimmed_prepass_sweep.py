import json
from pathlib import Path

from scripts.run_known_distance20_trimmed_prepass_sweep import (
    _artifact_path,
    _build_universal_cli_command,
    _estimated_command_timeout_seconds,
    _existing_artifact_success,
    _idle_guard_config,
    _plan_items,
    _single_row_artifact_suffix,
)


def test_single_row_suffix_names_offset_and_timeout():
    suffix = _single_row_artifact_suffix(
        distance=20,
        offset=2,
        h48_timeout_seconds=420.0,
        label="lowload",
    )

    assert suffix == "known_distance_20_offset2_trimmed_prepass_h48_420_ncorefb10_lowload"


def test_single_row_suffix_names_parallel_h48_symmetry_campaign():
    suffix = _single_row_artifact_suffix(
        distance=20,
        offset=2,
        h48_timeout_seconds=180.0,
        parallel_h48_symmetry_variants=2,
        parallel_h48_symmetry_timeout_seconds=180.0,
        preload_table=False,
        label="lowload",
    )

    assert suffix == (
        "known_distance_20_offset2_trimmed_prepass_h48_180_"
        "parallel_h48sym2_180_ncorefb10_nopreload_lowload"
    )


def test_single_row_suffix_names_parallel_h48_lower_bound_order_campaign():
    suffix = _single_row_artifact_suffix(
        distance=20,
        offset=2,
        h48_timeout_seconds=180.0,
        parallel_h48_symmetry_variants=23,
        parallel_h48_symmetry_timeout_seconds=180.0,
        parallel_h48_symmetry_max_concurrency=2,
        parallel_h48_symmetry_order_by_lower_bound=True,
        parallel_h48_symmetry_lower_bound_order_timeout_seconds=30.0,
        preload_table=False,
        label="lowload",
    )

    assert suffix == (
        "known_distance_20_offset2_trimmed_prepass_h48_180_"
        "parallel_h48sym23_180_conc2_lborder30_ncorefb10_nopreload_lowload"
    )


def test_single_row_suffix_names_shared_lower_bound_order_without_parallel_h48():
    suffix = _single_row_artifact_suffix(
        distance=20,
        offset=2,
        h48_timeout_seconds=180.0,
        nissy_symmetry_variants=23,
        nissy_symmetry_timeout_seconds=120.0,
        parallel_h48_symmetry_order_by_lower_bound=True,
        parallel_h48_symmetry_lower_bound_order_timeout_seconds=30.0,
        preload_table=False,
        label="lowload",
    )

    assert suffix == (
        "known_distance_20_offset2_trimmed_prepass_h48_180_"
        "nissysym23_120_lborder30_ncorefb10_nopreload_lowload"
    )


def test_single_row_suffix_names_h48_auto_min_depth_campaign():
    suffix = _single_row_artifact_suffix(
        distance=20,
        offset=2,
        h48_timeout_seconds=180.0,
        preload_table=False,
        h48_auto_min_depth=True,
        label="lowload",
    )

    assert suffix == "known_distance_20_offset2_trimmed_prepass_h48_180_ncorefb10_nopreload_automin_lowload"


def test_single_row_suffix_names_h48_upper_bound_proof_campaign():
    suffix = _single_row_artifact_suffix(
        distance=20,
        offset=2,
        h48_timeout_seconds=180.0,
        h48_upper_bound_proof_timeout_seconds=120.0,
        h48_upper_bound_proof_max_gap=4,
        preload_table=False,
        label="lowload",
    )

    assert suffix == (
        "known_distance_20_offset2_trimmed_prepass_h48_180_"
        "ubproof120_gap4_ncorefb10_nopreload_lowload"
    )


def test_single_row_suffix_names_h48_only_no_portfolio_prepass_campaign():
    suffix = _single_row_artifact_suffix(
        distance=20,
        offset=2,
        h48_timeout_seconds=420.0,
        prepass_timeout_seconds=30.0,
        fallback_timeout_seconds=1.0,
        fallback_nissy_core_direct_timeout_seconds=None,
        preload_table=False,
        h48_auto_min_depth=True,
        no_portfolio_prepass=True,
        label="lowload",
    )

    assert suffix == (
        "known_distance_20_offset2_trimmed_prepass_h48_420_"
        "nissyfb1_noprepass_nopreload_automin_lowload"
    )


def test_single_row_suffix_names_nissy_symmetry_campaign():
    suffix = _single_row_artifact_suffix(
        distance=20,
        offset=2,
        h48_timeout_seconds=180.0,
        nissy_symmetry_variants=4,
        nissy_symmetry_timeout_seconds=120.0,
        preload_table=False,
        label="lowload",
    )

    assert suffix == "known_distance_20_offset2_trimmed_prepass_h48_180_nissysym4_120_ncorefb10_nopreload_lowload"


def test_single_row_suffix_names_nissy_core_direct_symmetry_campaign():
    suffix = _single_row_artifact_suffix(
        distance=20,
        offset=2,
        h48_timeout_seconds=180.0,
        nissy_core_direct_symmetry_variants=4,
        nissy_core_direct_symmetry_timeout_seconds=120.0,
        nissy_core_direct_symmetry_max_concurrency=2,
        preload_table=False,
        label="lowload",
    )

    assert suffix == (
        "known_distance_20_offset2_trimmed_prepass_h48_180_"
        "ncoredsym4_120_conc2_ncorefb10_nopreload_lowload"
    )


def test_single_row_suffix_names_rubikoptimal_campaign():
    suffix = _single_row_artifact_suffix(
        distance=20,
        offset=2,
        h48_timeout_seconds=180.0,
        rubikoptimal_prepass_timeout_seconds=120.0,
        rubikoptimal_race_timeout_seconds=60.0,
        rubikoptimal_fallback_timeout_seconds=300.0,
        preload_table=False,
        label="lowload",
    )

    assert suffix == (
        "known_distance_20_offset2_trimmed_prepass_h48_180_"
        "ncorefb10_ropre120_rorace60_rofb300_nopreload_lowload"
    )


def test_single_row_suffix_names_resident_race_prepass_campaign():
    suffix = _single_row_artifact_suffix(
        distance=20,
        offset=2,
        h48_timeout_seconds=180.0,
        resident_race_prepass_timeout_seconds=90.0,
        preload_table=False,
        label="lowload",
    )

    assert suffix == (
        "known_distance_20_offset2_trimmed_prepass_h48_180_"
        "ncorefb10_rrpre90_nopreload_lowload"
    )


def test_estimated_command_timeout_accounts_for_resident_race_prepass():
    timeout = _estimated_command_timeout_seconds(
        solver_timeout_seconds=180.0,
        prepass_timeout_seconds=30.0,
        fallback_timeout_seconds=300.0,
        fallback_nissy_core_direct_timeout_seconds=None,
        resident_race_prepass_timeout_seconds=90.0,
        h48_symmetry_variants=0,
        h48_symmetry_timeout_seconds=0.0,
    )

    assert timeout == 660.0


def test_estimated_command_timeout_can_skip_portfolio_prepass():
    timeout = _estimated_command_timeout_seconds(
        solver_timeout_seconds=420.0,
        prepass_timeout_seconds=30.0,
        fallback_timeout_seconds=1.0,
        fallback_nissy_core_direct_timeout_seconds=None,
        h48_symmetry_variants=0,
        h48_symmetry_timeout_seconds=0.0,
        no_portfolio_prepass=True,
    )

    assert timeout == 481.0


def test_estimated_command_timeout_accounts_for_h48_upper_bound_proof_budget():
    timeout = _estimated_command_timeout_seconds(
        solver_timeout_seconds=180.0,
        prepass_timeout_seconds=30.0,
        fallback_timeout_seconds=300.0,
        fallback_nissy_core_direct_timeout_seconds=None,
        h48_upper_bound_proof_timeout_seconds=120.0,
        h48_symmetry_variants=0,
        h48_symmetry_timeout_seconds=0.0,
    )

    assert timeout == 690.0


def test_estimated_command_timeout_accounts_for_parallel_h48_lower_bound_order():
    timeout = _estimated_command_timeout_seconds(
        solver_timeout_seconds=180.0,
        prepass_timeout_seconds=30.0,
        fallback_timeout_seconds=300.0,
        fallback_nissy_core_direct_timeout_seconds=None,
        parallel_h48_symmetry_variants=23,
        parallel_h48_symmetry_timeout_seconds=180.0,
        parallel_h48_symmetry_max_concurrency=2,
        parallel_h48_symmetry_order_by_lower_bound=True,
        parallel_h48_symmetry_lower_bound_order_timeout_seconds=30.0,
        h48_symmetry_variants=0,
        h48_symmetry_timeout_seconds=0.0,
    )

    assert timeout == 780.0


def test_estimated_command_timeout_accounts_for_shared_lower_bound_order_without_parallel_h48():
    timeout = _estimated_command_timeout_seconds(
        solver_timeout_seconds=180.0,
        prepass_timeout_seconds=30.0,
        fallback_timeout_seconds=300.0,
        fallback_nissy_core_direct_timeout_seconds=None,
        nissy_symmetry_variants=23,
        nissy_symmetry_timeout_seconds=120.0,
        parallel_h48_symmetry_order_by_lower_bound=True,
        parallel_h48_symmetry_lower_bound_order_timeout_seconds=30.0,
        h48_symmetry_variants=0,
        h48_symmetry_timeout_seconds=0.0,
    )

    assert timeout == 720.0


def test_estimated_command_timeout_treats_nissy_core_direct_symmetry_as_global_budget():
    timeout = _estimated_command_timeout_seconds(
        solver_timeout_seconds=180.0,
        prepass_timeout_seconds=30.0,
        fallback_timeout_seconds=300.0,
        fallback_nissy_core_direct_timeout_seconds=None,
        nissy_core_direct_symmetry_variants=23,
        nissy_core_direct_symmetry_timeout_seconds=180.0,
        nissy_core_direct_symmetry_max_concurrency=2,
        h48_symmetry_variants=0,
        h48_symmetry_timeout_seconds=0.0,
    )

    assert timeout == 750.0


def test_idle_guard_config_records_thresholds_for_hard_tail_campaigns():
    config = _idle_guard_config(
        enabled=True,
        max_load_1m=2.5,
        max_load_5m=3.0,
        min_available_gib=6.0,
        required_checks=2,
        check_interval_seconds=60.0,
        timeout_seconds=0.0,
    )

    assert config["enabled"] is True
    assert config["max_load_1m"] == 2.5
    assert config["max_load_5m"] == 3.0
    assert config["min_available_memory_bytes"] == 6 * 1024**3
    assert config["required_consecutive_checks"] == 2


def test_single_row_suffix_names_rubikoptimal_symmetry_campaign():
    suffix = _single_row_artifact_suffix(
        distance=20,
        offset=2,
        h48_timeout_seconds=180.0,
        rubikoptimal_prepass_timeout_seconds=120.0,
        rubikoptimal_symmetry_variants=23,
        rubikoptimal_symmetry_timeout_seconds=300.0,
        rubikoptimal_fallback_timeout_seconds=300.0,
        preload_table=False,
        label="lowload",
    )

    assert suffix == (
        "known_distance_20_offset2_trimmed_prepass_h48_180_"
        "ncorefb10_ropre120_rosym23_300_rofb300_nopreload_lowload"
    )


def test_single_row_suffix_names_rubikoptimal_symmetry_race_campaign():
    suffix = _single_row_artifact_suffix(
        distance=20,
        offset=2,
        h48_timeout_seconds=180.0,
        rubikoptimal_prepass_timeout_seconds=120.0,
        rubikoptimal_symmetry_variants=23,
        rubikoptimal_symmetry_timeout_seconds=300.0,
        rubikoptimal_symmetry_max_concurrency=2,
        rubikoptimal_fallback_timeout_seconds=300.0,
        preload_table=False,
        label="lowload",
    )

    assert suffix == (
        "known_distance_20_offset2_trimmed_prepass_h48_180_"
        "ncorefb10_ropre120_rosym23_300_conc2_rofb300_nopreload_lowload"
    )


def test_estimated_command_timeout_uses_rubikoptimal_symmetry_as_global_phase():
    timeout = _estimated_command_timeout_seconds(
        solver_timeout_seconds=180.0,
        prepass_timeout_seconds=30.0,
        fallback_timeout_seconds=300.0,
        fallback_nissy_core_direct_timeout_seconds=None,
        rubikoptimal_prepass_timeout_seconds=300.0,
        rubikoptimal_symmetry_variants=23,
        rubikoptimal_symmetry_timeout_seconds=300.0,
        rubikoptimal_symmetry_max_concurrency=2,
        rubikoptimal_race_timeout_seconds=120.0,
        rubikoptimal_fallback_timeout_seconds=300.0,
        h48_symmetry_variants=0,
        h48_symmetry_timeout_seconds=0.0,
    )

    assert timeout == 1590.0


def test_single_row_suffix_names_larger_late_nissy_fallback():
    suffix = _single_row_artifact_suffix(
        distance=20,
        offset=2,
        h48_timeout_seconds=180.0,
        prepass_timeout_seconds=30.0,
        fallback_timeout_seconds=300.0,
        parallel_h48_symmetry_variants=2,
        parallel_h48_symmetry_timeout_seconds=180.0,
        preload_table=False,
        label="lowload",
    )

    assert (
        suffix
        == "known_distance_20_offset2_trimmed_prepass_h48_180_parallel_h48sym2_180_nissyfb300_ncorefb10_nopreload_lowload"
    )


def test_build_universal_cli_command_uses_optimized_lowload_flags():
    command = _build_universal_cli_command(
        python_executable="python",
        profile="thesis",
        seed=2026,
        solver="h48h7",
        distance=20,
        offset=2,
        timeout_seconds=420.0,
        prepass_timeout_seconds=30.0,
        fallback_timeout_seconds=None,
        command_timeout_seconds=540.0,
        threads=1,
        artifact_suffix="known_distance_20_offset2_trimmed_prepass_h48_420_lowload",
        nice_level=20,
        nice_available=True,
    )

    assert command[:4] == ["nice", "-n", "20", "python"]
    assert "scripts/run_universal_oracle_cli.py" in command
    assert command[command.index("--benchmark-distance") + 1] == "20"
    assert command[command.index("--benchmark-offset-per-distance") + 1] == "2"
    assert command[command.index("--universal-portfolio-prepass-timeout") + 1] == "30.0"
    assert command[command.index("--resident-h48-batch-timeout") + 1] == "420.0"
    assert command[command.index("--command-timeout") + 1] == "540.0"
    assert command[command.index("--threads") + 1] == "1"
    assert command[command.index("--universal-fallback-nissy-core-direct-timeout") + 1] == "10.0"
    assert "--trusted-table" in command
    assert "--preload-table" in command
    assert "--no-certificate-cache" in command
    assert "--no-upper-lower-certificate" in command
    assert command[command.index("--h48-upper-bound-proof-timeout") + 1] == "0.0"
    assert command[command.index("--h48-upper-bound-proof-max-gap") + 1] == "1"


def test_build_universal_cli_command_can_enable_h48_upper_bound_proof():
    command = _build_universal_cli_command(
        python_executable="python",
        profile="thesis",
        seed=2026,
        solver="h48h7",
        distance=20,
        offset=2,
        timeout_seconds=180.0,
        prepass_timeout_seconds=30.0,
        fallback_timeout_seconds=300.0,
        h48_upper_bound_proof_timeout_seconds=120.0,
        h48_upper_bound_proof_max_gap=4,
        command_timeout_seconds=690.0,
        threads=1,
        preload_table=False,
        artifact_suffix=(
            "known_distance_20_offset2_trimmed_prepass_h48_180_"
            "ubproof120_gap4_nissyfb300_ncorefb10_nopreload_lowload"
        ),
        nice_level=20,
        nice_available=False,
    )

    assert command[0] == "python"
    assert "--no-certificate-cache" in command
    assert "--no-upper-lower-certificate" not in command
    assert command[command.index("--h48-upper-bound-proof-timeout") + 1] == "120.0"
    assert command[command.index("--h48-upper-bound-proof-max-gap") + 1] == "4"
    assert command[command.index("--command-timeout") + 1] == "690.0"


def test_build_universal_cli_command_can_skip_portfolio_prepass():
    command = _build_universal_cli_command(
        python_executable="python",
        profile="thesis",
        seed=2026,
        solver="h48h7",
        distance=20,
        offset=2,
        timeout_seconds=420.0,
        prepass_timeout_seconds=30.0,
        fallback_timeout_seconds=1.0,
        fallback_nissy_core_direct_timeout_seconds=None,
        command_timeout_seconds=541.0,
        threads=1,
        preload_table=False,
        h48_auto_min_depth=True,
        no_portfolio_prepass=True,
        artifact_suffix="known_distance_20_offset2_h48_only_automin",
        nice_level=20,
        nice_available=False,
    )

    assert command[0] == "python"
    assert "--no-portfolio-prepass" in command
    assert "--universal-portfolio-prepass-timeout" not in command
    assert command[command.index("--universal-portfolio-fallback-timeout") + 1] == "1.0"
    assert command[command.index("--universal-fallback-nissy-core-direct-timeout") + 1] == "-1.0"
    assert "--h48-auto-min-depth" in command
    assert "--preload-table" not in command


def test_build_universal_cli_command_can_enable_parallel_h48_symmetry_race():
    command = _build_universal_cli_command(
        python_executable="python",
        profile="thesis",
        seed=2026,
        solver="h48h7",
        distance=20,
        offset=2,
        timeout_seconds=180.0,
        prepass_timeout_seconds=30.0,
        fallback_timeout_seconds=300.0,
        command_timeout_seconds=600.0,
        threads=1,
        nissy_symmetry_variants=4,
        nissy_symmetry_timeout_seconds=120.0,
        nissy_core_direct_symmetry_variants=3,
        nissy_core_direct_symmetry_timeout_seconds=90.0,
        nissy_core_direct_symmetry_max_concurrency=2,
        parallel_h48_symmetry_variants=2,
        parallel_h48_symmetry_timeout_seconds=180.0,
        parallel_h48_symmetry_order_by_lower_bound=True,
        parallel_h48_symmetry_lower_bound_order_timeout_seconds=30.0,
        preload_table=False,
        h48_auto_min_depth=True,
        artifact_suffix=(
            "known_distance_20_offset2_trimmed_prepass_h48_180_"
            "nissysym4_120_parallel_h48sym2_180_nissyfb300_nopreload_automin_lowload"
        ),
        nice_level=20,
        nice_available=False,
    )

    assert command[0] == "python"
    assert command[command.index("--h48-parallel-symmetry-variants") + 1] == "2"
    assert command[command.index("--h48-parallel-symmetry-timeout") + 1] == "180.0"
    assert "--symmetry-order-by-h48-lower-bound" in command
    assert command[command.index("--symmetry-lower-bound-order-timeout") + 1] == "30.0"
    assert command[command.index("--nissy-symmetry-variants") + 1] == "4"
    assert command[command.index("--nissy-symmetry-timeout") + 1] == "120.0"
    assert command[command.index("--nissy-core-direct-symmetry-variants") + 1] == "3"
    assert command[command.index("--nissy-core-direct-symmetry-timeout") + 1] == "90.0"
    assert command[command.index("--nissy-core-direct-symmetry-max-concurrency") + 1] == "2"
    assert command[command.index("--universal-portfolio-fallback-timeout") + 1] == "300.0"
    assert command[command.index("--universal-fallback-nissy-core-direct-timeout") + 1] == "10.0"
    assert "--preload-table" not in command
    assert "--h48-auto-min-depth" in command
    assert "--no-certificate-cache" in command
    assert "--no-upper-lower-certificate" in command


def test_build_universal_cli_command_can_order_shared_symmetry_without_parallel_h48():
    command = _build_universal_cli_command(
        python_executable="python",
        profile="thesis",
        seed=2026,
        solver="h48h7",
        distance=20,
        offset=2,
        timeout_seconds=180.0,
        prepass_timeout_seconds=30.0,
        fallback_timeout_seconds=300.0,
        fallback_nissy_core_direct_timeout_seconds=-1.0,
        resident_race_prepass_timeout_seconds=90.0,
        command_timeout_seconds=600.0,
        threads=1,
        nissy_symmetry_variants=4,
        nissy_symmetry_timeout_seconds=120.0,
        parallel_h48_symmetry_variants=0,
        parallel_h48_symmetry_order_by_lower_bound=True,
        parallel_h48_symmetry_lower_bound_order_timeout_seconds=30.0,
        preload_table=False,
        artifact_suffix="known_distance_20_offset2_shared_lborder_lowload",
        nice_level=20,
        nice_available=False,
    )

    assert "--h48-parallel-symmetry-variants" not in command
    assert command[command.index("--nissy-symmetry-variants") + 1] == "4"
    assert command[command.index("--universal-resident-race-prepass-timeout") + 1] == "90.0"
    assert "--symmetry-order-by-h48-lower-bound" in command
    assert command[command.index("--symmetry-lower-bound-order-timeout") + 1] == "30.0"


def test_build_universal_cli_command_can_enable_rubikoptimal_phases():
    command = _build_universal_cli_command(
        python_executable="python",
        profile="thesis",
        seed=2026,
        solver="h48h7",
        distance=20,
        offset=2,
        timeout_seconds=180.0,
        prepass_timeout_seconds=30.0,
        fallback_timeout_seconds=300.0,
        fallback_nissy_core_direct_timeout_seconds=-1.0,
        rubikoptimal_prepass_timeout_seconds=120.0,
        rubikoptimal_symmetry_variants=23,
        rubikoptimal_symmetry_timeout_seconds=300.0,
        rubikoptimal_symmetry_max_concurrency=2,
        rubikoptimal_race_timeout_seconds=60.0,
        rubikoptimal_fallback_timeout_seconds=300.0,
        command_timeout_seconds=720.0,
        threads=1,
        preload_table=False,
        artifact_suffix=(
            "known_distance_20_offset2_trimmed_prepass_h48_180_"
            "ncorefb10_ropre120_rorace60_rofb300_nopreload_lowload"
        ),
        nice_level=20,
        nice_available=False,
    )

    assert command[0] == "python"
    assert command[command.index("--universal-rubikoptimal-prepass-timeout") + 1] == "120.0"
    assert command[command.index("--universal-rubikoptimal-symmetry-variants") + 1] == "23"
    assert command[command.index("--universal-rubikoptimal-symmetry-timeout") + 1] == "300.0"
    assert command[command.index("--universal-rubikoptimal-symmetry-max-concurrency") + 1] == "2"
    assert command[command.index("--universal-rubikoptimal-race-timeout") + 1] == "60.0"
    assert command[command.index("--universal-rubikoptimal-fallback-timeout") + 1] == "300.0"
    assert command[command.index("--universal-fallback-nissy-core-direct-timeout") + 1] == "-1.0"
    assert command[command.index("--universal-portfolio-fallback-timeout") + 1] == "300.0"
    assert "--preload-table" not in command


def test_build_universal_cli_command_can_enable_resident_race_prepass():
    command = _build_universal_cli_command(
        python_executable="python",
        profile="thesis",
        seed=2026,
        solver="h48h7",
        distance=20,
        offset=2,
        timeout_seconds=180.0,
        prepass_timeout_seconds=30.0,
        fallback_timeout_seconds=300.0,
        resident_race_prepass_timeout_seconds=90.0,
        command_timeout_seconds=720.0,
        threads=1,
        preload_table=False,
        artifact_suffix=(
            "known_distance_20_offset2_trimmed_prepass_h48_180_"
            "ncorefb10_rrpre90_nopreload_lowload"
        ),
        nice_level=20,
        nice_available=False,
    )

    assert command[0] == "python"
    assert command[command.index("--universal-resident-race-prepass-timeout") + 1] == "90.0"
    assert "--preload-table" not in command


def test_existing_artifact_success_requires_exact_public_known_distance_row(tmp_path):
    path = tmp_path / "row.json"
    path.write_text(
        json.dumps(
            {
                "passed": True,
                "outer_command_timed_out": False,
                "all_exact": True,
                "all_verified": True,
                "all_expected_distances_match": True,
                "live_solver_shortcuts_disabled": True,
                "random_cases_enabled": False,
                "benchmark_limit_per_distance": 1,
                "benchmark_offset_per_distance": 2,
                "nissy_benchmark_distances_present": [20],
                "timeout_seconds": 420.0,
                "resident_h48_batch_timeout_seconds": 420.0,
                "portfolio_prepass_timeout_seconds": 30.0,
                "portfolio_fallback_nissy_core_direct_timeout_seconds": 10.0,
                "preload_table": True,
            }
        ),
        encoding="utf-8",
    )

    assert _existing_artifact_success(
        path,
        distance=20,
        offset=2,
        h48_timeout_seconds=420.0,
        prepass_timeout_seconds=30.0,
    )


def test_existing_artifact_success_distinguishes_parallel_h48_symmetry_settings(tmp_path):
    path = tmp_path / "row.json"
    path.write_text(
        json.dumps(
            {
                "passed": True,
                "outer_command_timed_out": False,
                "all_exact": True,
                "all_verified": True,
                "all_expected_distances_match": True,
                "live_solver_shortcuts_disabled": True,
                "random_cases_enabled": False,
                "benchmark_limit_per_distance": 1,
                "benchmark_offset_per_distance": 2,
                "nissy_benchmark_distances_present": [20],
                "timeout_seconds": 180.0,
                "resident_h48_batch_timeout_seconds": 180.0,
                "portfolio_prepass_timeout_seconds": 30.0,
                "portfolio_fallback_timeout_seconds": 300.0,
                "portfolio_fallback_nissy_core_direct_timeout_seconds": 10.0,
                "nissy_core_direct_symmetry_variants": 3,
                "nissy_core_direct_symmetry_timeout_seconds": 90.0,
                "nissy_core_direct_symmetry_max_concurrency": 2,
                "parallel_h48_symmetry_variants": 2,
                "parallel_h48_symmetry_timeout_seconds": 180.0,
                "preload_table": False,
            }
        ),
        encoding="utf-8",
    )

    assert _existing_artifact_success(
        path,
        distance=20,
        offset=2,
        h48_timeout_seconds=180.0,
        prepass_timeout_seconds=30.0,
        fallback_timeout_seconds=300.0,
        nissy_core_direct_symmetry_variants=3,
        nissy_core_direct_symmetry_timeout_seconds=90.0,
        nissy_core_direct_symmetry_max_concurrency=2,
        parallel_h48_symmetry_variants=2,
        parallel_h48_symmetry_timeout_seconds=180.0,
        preload_table=False,
    )
    assert not _existing_artifact_success(
        path,
        distance=20,
        offset=2,
        h48_timeout_seconds=180.0,
        prepass_timeout_seconds=30.0,
        fallback_timeout_seconds=300.0,
        nissy_core_direct_symmetry_variants=4,
        nissy_core_direct_symmetry_timeout_seconds=90.0,
        nissy_core_direct_symmetry_max_concurrency=2,
        parallel_h48_symmetry_variants=3,
        parallel_h48_symmetry_timeout_seconds=180.0,
        preload_table=False,
    )
    assert not _existing_artifact_success(
        path,
        distance=20,
        offset=3,
        h48_timeout_seconds=420.0,
        prepass_timeout_seconds=30.0,
    )


def test_existing_artifact_success_distinguishes_rubikoptimal_settings(tmp_path):
    path = tmp_path / "row.json"
    path.write_text(
        json.dumps(
            {
                "passed": True,
                "outer_command_timed_out": False,
                "all_exact": True,
                "all_verified": True,
                "all_expected_distances_match": True,
                "live_solver_shortcuts_disabled": True,
                "random_cases_enabled": False,
                "benchmark_limit_per_distance": 1,
                "benchmark_offset_per_distance": 2,
                "nissy_benchmark_distances_present": [20],
                "timeout_seconds": 180.0,
                "resident_h48_batch_timeout_seconds": 180.0,
                "portfolio_prepass_timeout_seconds": 30.0,
                "portfolio_fallback_nissy_core_direct_timeout_seconds": None,
                "rubikoptimal_prepass_timeout_seconds": 120.0,
                "rubikoptimal_symmetry_variants": 23,
                "rubikoptimal_symmetry_timeout_seconds": 300.0,
                "rubikoptimal_symmetry_max_concurrency": 2,
                "rubikoptimal_race_timeout_seconds": 60.0,
                "rubikoptimal_fallback_timeout_seconds": 300.0,
                "preload_table": False,
            }
        ),
        encoding="utf-8",
    )

    assert _existing_artifact_success(
        path,
        distance=20,
        offset=2,
        h48_timeout_seconds=180.0,
        prepass_timeout_seconds=30.0,
        fallback_nissy_core_direct_timeout_seconds=None,
        rubikoptimal_prepass_timeout_seconds=120.0,
        rubikoptimal_symmetry_variants=23,
        rubikoptimal_symmetry_timeout_seconds=300.0,
        rubikoptimal_symmetry_max_concurrency=2,
        rubikoptimal_race_timeout_seconds=60.0,
        rubikoptimal_fallback_timeout_seconds=300.0,
        preload_table=False,
    )
    assert not _existing_artifact_success(
        path,
        distance=20,
        offset=2,
        h48_timeout_seconds=180.0,
        prepass_timeout_seconds=30.0,
        fallback_nissy_core_direct_timeout_seconds=None,
        rubikoptimal_prepass_timeout_seconds=120.0,
        rubikoptimal_symmetry_variants=23,
        rubikoptimal_symmetry_timeout_seconds=300.0,
        rubikoptimal_symmetry_max_concurrency=3,
        rubikoptimal_race_timeout_seconds=60.0,
        rubikoptimal_fallback_timeout_seconds=300.0,
        preload_table=False,
    )


def test_existing_artifact_success_distinguishes_resident_race_prepass_settings(tmp_path):
    path = tmp_path / "row.json"
    path.write_text(
        json.dumps(
            {
                "passed": True,
                "outer_command_timed_out": False,
                "all_exact": True,
                "all_verified": True,
                "all_expected_distances_match": True,
                "live_solver_shortcuts_disabled": True,
                "random_cases_enabled": False,
                "benchmark_limit_per_distance": 1,
                "benchmark_offset_per_distance": 2,
                "nissy_benchmark_distances_present": [20],
                "timeout_seconds": 180.0,
                "resident_h48_batch_timeout_seconds": 180.0,
                "portfolio_prepass_timeout_seconds": 30.0,
                "portfolio_fallback_nissy_core_direct_timeout_seconds": 10.0,
                "resident_race_prepass_timeout_seconds": 90.0,
                "preload_table": False,
            }
        ),
        encoding="utf-8",
    )

    assert _existing_artifact_success(
        path,
        distance=20,
        offset=2,
        h48_timeout_seconds=180.0,
        prepass_timeout_seconds=30.0,
        resident_race_prepass_timeout_seconds=90.0,
        preload_table=False,
    )
    assert not _existing_artifact_success(
        path,
        distance=20,
        offset=2,
        h48_timeout_seconds=180.0,
        prepass_timeout_seconds=30.0,
        resident_race_prepass_timeout_seconds=91.0,
        preload_table=False,
    )
    assert not _existing_artifact_success(
        path,
        distance=20,
        offset=2,
        h48_timeout_seconds=180.0,
        prepass_timeout_seconds=30.0,
        fallback_nissy_core_direct_timeout_seconds=None,
        rubikoptimal_prepass_timeout_seconds=121.0,
        rubikoptimal_symmetry_variants=23,
        rubikoptimal_symmetry_timeout_seconds=300.0,
        rubikoptimal_symmetry_max_concurrency=2,
        rubikoptimal_race_timeout_seconds=60.0,
        rubikoptimal_fallback_timeout_seconds=300.0,
        preload_table=False,
    )


def test_existing_artifact_success_distinguishes_h48_upper_bound_proof_settings(tmp_path):
    path = tmp_path / "row.json"
    path.write_text(
        json.dumps(
            {
                "passed": True,
                "outer_command_timed_out": False,
                "all_exact": True,
                "all_verified": True,
                "all_expected_distances_match": True,
                "live_solver_shortcuts_disabled": False,
                "random_cases_enabled": False,
                "benchmark_limit_per_distance": 1,
                "benchmark_offset_per_distance": 2,
                "nissy_benchmark_distances_present": [20],
                "timeout_seconds": 180.0,
                "resident_h48_batch_timeout_seconds": 180.0,
                "portfolio_prepass_timeout_seconds": 30.0,
                "portfolio_fallback_nissy_core_direct_timeout_seconds": 10.0,
                "h48_upper_bound_proof_timeout_seconds": 120.0,
                "h48_upper_bound_proof_max_gap": 4,
                "preload_table": False,
            }
        ),
        encoding="utf-8",
    )

    assert _existing_artifact_success(
        path,
        distance=20,
        offset=2,
        h48_timeout_seconds=180.0,
        prepass_timeout_seconds=30.0,
        h48_upper_bound_proof_timeout_seconds=120.0,
        h48_upper_bound_proof_max_gap=4,
        preload_table=False,
    )
    assert not _existing_artifact_success(
        path,
        distance=20,
        offset=2,
        h48_timeout_seconds=180.0,
        prepass_timeout_seconds=30.0,
        h48_upper_bound_proof_timeout_seconds=60.0,
        h48_upper_bound_proof_max_gap=4,
        preload_table=False,
    )


def test_existing_artifact_success_distinguishes_no_portfolio_prepass(tmp_path):
    path = tmp_path / "row.json"
    path.write_text(
        json.dumps(
            {
                "passed": True,
                "outer_command_timed_out": False,
                "all_exact": True,
                "all_verified": True,
                "all_expected_distances_match": True,
                "live_solver_shortcuts_disabled": True,
                "random_cases_enabled": False,
                "benchmark_limit_per_distance": 1,
                "benchmark_offset_per_distance": 2,
                "nissy_benchmark_distances_present": [20],
                "timeout_seconds": 420.0,
                "resident_h48_batch_timeout_seconds": 420.0,
                "portfolio_prepass_timeout_seconds": None,
                "portfolio_fallback_timeout_seconds": 1.0,
                "portfolio_fallback_nissy_core_direct_timeout_seconds": None,
                "no_portfolio_prepass": True,
                "preload_table": False,
                "h48_auto_min_depth": True,
            }
        ),
        encoding="utf-8",
    )

    assert _existing_artifact_success(
        path,
        distance=20,
        offset=2,
        h48_timeout_seconds=420.0,
        prepass_timeout_seconds=30.0,
        fallback_timeout_seconds=1.0,
        fallback_nissy_core_direct_timeout_seconds=None,
        preload_table=False,
        h48_auto_min_depth=True,
        no_portfolio_prepass=True,
    )
    assert not _existing_artifact_success(
        path,
        distance=20,
        offset=2,
        h48_timeout_seconds=420.0,
        prepass_timeout_seconds=30.0,
        fallback_timeout_seconds=1.0,
        fallback_nissy_core_direct_timeout_seconds=None,
        preload_table=False,
        h48_auto_min_depth=True,
        no_portfolio_prepass=False,
    )


def test_plan_items_points_each_offset_to_its_own_artifact(tmp_path):
    items = _plan_items(
        tmp_path,
        profile="thesis",
        seed=2026,
        solver="h48h7",
        distance=20,
        offsets=[1, 2],
        timeout_seconds=420.0,
        prepass_timeout_seconds=30.0,
        fallback_timeout_seconds=None,
        command_timeout_seconds=540.0,
        threads=1,
        h48_symmetry_variants=0,
        h48_symmetry_timeout_seconds=0.0,
        parallel_h48_symmetry_variants=0,
        parallel_h48_symmetry_timeout_seconds=0.0,
        preload_table=True,
        label="lowload",
        nice_level=20,
        python_executable="python",
        nice_available=False,
    )

    assert [item.offset for item in items] == [1, 2]
    assert items[0].artifact_suffix == "known_distance_20_offset1_trimmed_prepass_h48_420_ncorefb10_lowload"
    assert items[1].artifact_suffix == "known_distance_20_offset2_trimmed_prepass_h48_420_ncorefb10_lowload"
    assert items[0].artifact_path == _artifact_path(
        tmp_path,
        seed=2026,
        profile="thesis",
        solver="h48h7",
        artifact_suffix=items[0].artifact_suffix,
    )
    assert items[0].command[0] == "python"
    assert Path(items[0].artifact_path).name.endswith(
        "_known_distance_20_offset1_trimmed_prepass_h48_420_ncorefb10_lowload.json"
    )

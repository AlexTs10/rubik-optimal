import json

from scripts.generate_h48_oracle_contract import (
    _cloud_runtime_proof_from_evaluation,
    _h48_metadata_is_oracle_grade,
    _latest_cloud_hardtail_evaluation,
    _latest_h48_stronger_table_detached_status,
    build_contract_payload,
)
from rubik_optimal.tables.h48 import repository_root


def test_h48_contract_oracle_grade_metadata_accepts_stronger_h_values():
    assert _h48_metadata_is_oracle_grade(
        {"solver": "h48h7", "oracle_grade": True},
        solver="h48h7",
    )
    assert _h48_metadata_is_oracle_grade(
        {"solver": "h48h8", "oracle_grade": True},
        solver="h48h8",
    )
    assert _h48_metadata_is_oracle_grade(
        {"solver": "h48h10", "oracle_grade": True},
        solver="h48h10",
    )
    assert not _h48_metadata_is_oracle_grade(
        {"solver": "h48h6", "oracle_grade": False},
        solver="h48h6",
    )
    assert not _h48_metadata_is_oracle_grade(
        {"solver": "h48h8", "oracle_grade": True},
        solver="h48h10",
    )


def test_h48_contract_latest_detached_status_uses_payload_noaws_identity(tmp_path):
    processed = tmp_path / "results" / "processed"
    processed.mkdir(parents=True)
    stale = (
        processed
        / "h48_stronger_table_detached_status_seed_2026_thesis_h48h8_"
        "noaws_workbatch256_waitsafe_live_status_old.json"
    )
    current = (
        processed
        / "h48_stronger_table_detached_status_seed_2026_thesis_h48h8_"
        "current_live_check.json"
    )
    stale.write_text(
        json.dumps(
            {
                "profile": "thesis",
                "seed": 2026,
                "target_solver": "h48h8",
                "artifact_suffix": "noaws_workbatch256_waitsafe_live",
                "status": "detached_python_alive_waiting_safety_gate_no_trusted_table",
                "pid_alive": True,
            }
        ),
        encoding="utf-8",
    )
    current.write_text(
        json.dumps(
            {
                "profile": "thesis",
                "seed": 2026,
                "target_solver": "h48h8",
                "artifact_suffix": "noaws_workbatch256_waitsafe_optimized_flags_live",
                "detached_payload_path": (
                    "results/processed/h48_stronger_table_detached_seed_2026_thesis_"
                    "h48h8_noaws_workbatch256_waitsafe_optimized_flags_live.json"
                ),
                "status": "detached_process_not_alive_no_trusted_table",
                "pid_alive": False,
            }
        ),
        encoding="utf-8",
    )

    selected = _latest_h48_stronger_table_detached_status(
        root=tmp_path,
        profile="thesis",
        seed=2026,
        target_solver="h48h8",
    )

    assert selected is not None
    assert selected["path"].endswith("current_live_check.json")
    assert selected["payload"]["status"] == "detached_process_not_alive_no_trusted_table"
    assert selected["payload"]["pid_alive"] is False


def test_h48_oracle_contract_distinguishes_exactness_from_runtime_proof():
    payload = build_contract_payload(root=repository_root(), profile="thesis", seed=2026, solver="h48h7")

    assert payload["source_checks"]["nissy_docs_h48_htm_optimal"] is True
    assert payload["source_checks"]["backend_sets_optimal_zero"] is True
    assert payload["source_checks"]["backend_exposes_lower_bound_mode"] is True
    assert payload["source_checks"]["backend_exposes_lower_bound_batch_mode"] is True
    assert payload["source_checks"]["backend_has_native_search_deadline_poll"] is True
    assert payload["source_checks"]["backend_reports_native_search_timeout"] is True
    assert payload["source_checks"]["backend_reports_completed_negative_search_as_lower_bound"] is True
    assert payload["source_checks"]["python_independently_verifies_solution"] is True
    assert payload["source_checks"]["python_h48_lower_bound_wrapper_exists"] is True
    assert payload["source_checks"]["python_h48_rotational_lower_bound_wrapper_exists"] is True
    assert payload["source_checks"]["python_h48_wrapper_passes_native_search_timeout"] is True
    assert payload["source_checks"]["python_h48_wrapper_preserves_bounded_search_lower_bound"] is True
    assert payload["source_checks"]["python_h48_resident_timeout_keeps_loaded_process"] is True
    assert payload["source_checks"]["python_h48_batch_recovers_partial_timeout_rows"] is True
    assert payload["source_checks"]["python_h48_resident_batch_recovers_partial_timeout_rows"] is True
    assert payload["source_checks"]["python_h48_lower_bound_recovers_partial_timeout_rows"] is True
    assert payload["source_checks"]["h48_stronger_table_campaign_status_exposes_top_level_pid_liveness"] is True
    assert payload["source_checks"]["h48_stronger_table_campaign_exposes_status_alias"] is True
    assert payload["source_checks"]["h48_oracle_contract_records_stronger_table_detached_status"] is True
    assert payload["source_checks"]["h48_oracle_contract_records_fasttarget_stronger_table_status"] is True
    assert payload["source_checks"]["h48_resident_timeout_survival_evidence_script_uses_session"] is True
    assert payload["source_checks"]["h48_batch_partial_timeout_recovery_evidence_script_exists"] is True
    assert payload["source_checks"]["h48_lower_bound_partial_timeout_recovery_evidence_script_exists"] is True
    assert payload["source_checks"]["python_exact_certificate_cache_revalidates"] is True
    assert payload["source_checks"]["python_exact_certificate_cache_accepts_cli_facelet_input"] is True
    assert payload["source_checks"]["python_exact_certificate_cache_accepts_solution_moves_rows"] is True
    assert payload["source_checks"]["python_exact_certificate_cache_loads_expanded_cli_default"] is True
    assert payload["source_checks"]["python_exact_certificate_cache_derives_inverse_closure"] is True
    assert payload["source_checks"]["python_cube_symmetry_has_24_rotations"] is True
    assert payload["source_checks"]["python_exact_certificate_cache_derives_symmetry_closure"] is True
    assert payload["source_checks"]["python_exact_certificate_cache_supports_learned_jsonl"] is True
    assert payload["source_checks"]["fast_oracle_api_exists"] is True
    assert payload["source_checks"]["fast_oracle_api_defaults_to_strongest_trusted_h48"] is True
    assert payload["source_checks"]["fast_oracle_api_uses_resident_backend"] is True
    assert payload["source_checks"]["fast_oracle_api_defaults_to_unbounded_native_search"] is True
    assert payload["source_checks"]["fast_oracle_api_passes_timeout_to_resident_h48"] is True
    assert payload["source_checks"]["python_h48_resident_solve_many_pipelines_batch"] is True
    assert payload["source_checks"]["fast_oracle_api_solve_many_uses_resident_batch"] is True
    assert payload["source_checks"]["fast_oracle_api_threads_are_runtime_configurable"] is True
    assert payload["source_checks"]["portfolio_oracle_api_exists"] is True
    assert payload["source_checks"]["runtime_helper_terminates_process_group_on_timeout"] is True
    assert payload["source_checks"]["portfolio_oracle_tries_nissy_before_h48"] is True
    assert payload["source_checks"]["portfolio_oracle_uses_exact_certificate_cache"] is True
    assert payload["source_checks"]["portfolio_oracle_has_upper_lower_certificate"] is True
    assert payload["source_checks"]["portfolio_oracle_can_use_rotational_lower_bound_certificate"] is True
    assert payload["source_checks"]["portfolio_oracle_batches_upper_lower_certificates"] is True
    assert (
        payload["source_checks"]["portfolio_oracle_can_use_kociemba_symmetry_upper_bound_certificate"]
        is True
    )
    assert payload["source_checks"]["portfolio_oracle_can_use_h48_upper_bound_proof"] is True
    assert payload["source_checks"]["portfolio_oracle_batches_h48_upper_bound_proofs"] is True
    assert (
        payload["source_checks"]["native_korf_upper_bound_proof_supports_single_bound_exhaustive"]
        is True
    )
    assert payload["source_checks"]["portfolio_oracle_can_use_native_korf_upper_bound_proof"] is True
    assert payload["source_checks"]["portfolio_oracle_tries_nissy_core_direct_for_state_input"] is True
    assert payload["source_checks"]["portfolio_oracle_batches_nissy_core_direct_for_state_input"] is True
    assert payload["source_checks"]["portfolio_oracle_persists_learned_certificates"] is True
    assert payload["source_checks"]["portfolio_evidence_script_uses_package_api"] is True
    assert payload["source_checks"]["race_oracle_api_exists"] is True
    assert payload["source_checks"]["race_oracle_uses_exact_first_verified_policy"] is True
    assert payload["source_checks"]["race_oracle_terminates_slower_backend"] is True
    assert payload["source_checks"]["race_oracle_starts_h48_and_nissy"] is True
    assert payload["source_checks"]["race_oracle_uses_nissy_core_direct_state_candidate"] is True
    assert payload["source_checks"]["race_oracle_cli_exposed"] is True
    assert payload["source_checks"]["race_evidence_script_uses_package_api"] is True
    assert payload["source_checks"]["resident_race_oracle_api_exists"] is True
    assert payload["source_checks"]["resident_race_oracle_uses_resident_h48"] is True
    assert payload["source_checks"]["resident_race_oracle_uses_threaded_h48"] is True
    assert payload["source_checks"]["resident_race_oracle_stops_losing_backends"] is True
    assert payload["source_checks"]["resident_race_oracle_cli_exposed"] is True
    assert payload["source_checks"]["resident_race_evidence_script_uses_package_api"] is True
    assert payload["source_checks"]["resident_race_oracle_can_delay_h48_start"] is True
    assert payload["source_checks"]["resident_race_oracle_uses_nissy_core_direct_state_candidate"] is True
    assert (
        payload["source_checks"]["resident_race_oracle_uses_resident_nissy_core_direct_state_candidate"]
        is True
    )
    assert payload["source_checks"]["universal_oracle_api_exists"] is True
    assert payload["source_checks"]["universal_oracle_uses_certificate_before_live_race"] is True
    assert payload["source_checks"]["universal_oracle_uses_upper_lower_before_live_race"] is True
    assert payload["source_checks"]["universal_oracle_solve_many_batches_upper_lower_certificates"] is True
    assert payload["source_checks"]["universal_oracle_falls_back_to_resident_race"] is True
    assert payload["source_checks"]["universal_oracle_batches_live_corpus"] is True
    assert payload["source_checks"]["universal_oracle_batches_state_input_through_resident_h48"] is True
    assert payload["source_checks"]["universal_oracle_uses_portfolio_prepass_before_resident_h48_batch"] is True
    assert payload["source_checks"]["universal_oracle_falls_back_after_resident_h48_batch_timeout"] is True
    assert payload["source_checks"]["universal_oracle_late_fallback_uses_nissy_core_direct_state_input"] is True
    assert payload["source_checks"]["universal_oracle_uses_live_nissy_symmetry_batch"] is True
    assert payload["source_checks"]["resident_race_nissy_symmetry_orders_by_h48_lower_bound"] is True
    assert payload["source_checks"]["public_oracle_cli_exposes_shared_symmetry_ordering_alias"] is True
    assert payload["source_checks"]["public_oracle_cli_exposes_kociemba_symmetry_upper_bound"] is True
    assert payload["source_checks"]["public_oracle_cli_exposes_h48_upper_bound_proof"] is True
    assert payload["source_checks"]["public_oracle_cli_exposes_native_korf_upper_bound_proof"] is True
    assert payload["source_checks"]["universal_oracle_uses_resident_race_prepass"] is True
    assert payload["source_checks"]["h48_native_supports_rotated_direct_state_variants"] is True
    assert (
        payload["source_checks"]["python_h48_resident_symmetry_accepts_explicit_rotation_order"]
        is True
    )
    assert payload["source_checks"]["h48_native_symmetry_rotations_cover_cube_axes"] is True
    assert payload["source_checks"]["universal_oracle_uses_resident_h48_symmetry_batch"] is True
    assert (
        payload["source_checks"]["universal_resident_h48_symmetry_orders_by_h48_lower_bound"]
        is True
    )
    assert payload["source_checks"]["universal_oracle_solve_many_uses_resident_h48_symmetry_batch"] is True
    assert payload["source_checks"]["resident_race_oracle_uses_rubikoptimal_candidate"] is True
    assert payload["source_checks"]["rubikoptimal_resident_session_exists"] is True
    assert payload["source_checks"]["public_oracle_cli_rubikoptimal_stream_uses_resident_session"] is True
    assert payload["source_checks"]["universal_oracle_exposes_rubikoptimal_race"] is True
    assert payload["source_checks"]["universal_oracle_uses_rubikoptimal_symmetry_batch"] is True
    assert (
        payload["source_checks"][
            "universal_oracle_rubikoptimal_symmetry_batch_uses_shared_resident_session"
        ]
        is True
    )
    assert (
        payload["source_checks"][
            "universal_oracle_rubikoptimal_symmetry_includes_identity_without_prepass"
        ]
        is True
    )
    assert payload["source_checks"]["rubikoptimal_external_supports_rotational_race"] is True
    assert payload["source_checks"]["rubikoptimal_rotational_race_uses_resident_worker_pool"] is True
    assert payload["source_checks"]["rubikoptimal_rotational_race_uses_global_wall_timeout"] is True
    assert payload["source_checks"]["rubikoptimal_resident_timeout_keeps_loaded_process"] is True
    assert payload["source_checks"]["rubikoptimal_batch_uses_resident_session"] is True
    assert payload["source_checks"]["universal_oracle_uses_rubikoptimal_symmetry_race"] is True
    assert payload["source_checks"]["universal_rubikoptimal_symmetry_uses_global_wall_timeout"] is True
    assert payload["source_checks"]["universal_oracle_uses_resident_rubikoptimal_session"] is True
    assert (
        payload["source_checks"][
            "universal_oracle_rubikoptimal_prepass_uses_shared_resident_session"
        ]
        is True
    )
    assert (
        payload["source_checks"][
            "universal_oracle_rubikoptimal_fallback_uses_shared_resident_session"
        ]
        is True
    )
    assert payload["source_checks"]["universal_evidence_script_supports_rubikoptimal_race"] is True
    assert payload["source_checks"]["rubikoptimal_resident_evidence_script_uses_session"] is True
    assert payload["source_checks"]["rubikoptimal_stream_evidence_script_uses_public_cli"] is True
    assert payload["source_checks"]["h48_native_supports_parallel_rotational_race"] is True
    assert payload["source_checks"]["h48_parallel_rotational_race_uses_global_wall_timeout"] is True
    assert payload["source_checks"]["h48_resident_rotational_batch_uses_global_wall_timeout"] is True
    assert payload["source_checks"]["universal_oracle_cli_exposed"] is True
    assert payload["source_checks"]["universal_evidence_script_uses_package_api"] is True
    assert payload["source_checks"]["universal_evidence_script_supports_state_input_only"] is True
    assert payload["source_checks"]["universal_evidence_script_supports_h48_symmetry_prepass"] is True
    assert payload["source_checks"]["universal_oracle_cli_evidence_supports_h48_symmetry_prepass"] is True
    assert payload["source_checks"]["universal_oracle_cli_evidence_supports_parallel_h48_symmetry_race"] is True
    assert payload["source_checks"]["universal_nissy_core_direct_symmetry_uses_global_wall_timeout"] is True
    assert payload["source_checks"]["universal_oracle_cli_budgets_symmetry_races_as_global_phases"] is True
    assert payload["source_checks"]["universal_oracle_cli_budgets_shared_symmetry_ordering"] is True
    assert payload["source_checks"]["universal_oracle_cli_evidence_supports_rubikoptimal_symmetry_batch"] is True
    assert payload["source_checks"]["universal_oracle_cli_evidence_supports_rubikoptimal_symmetry_race"] is True
    assert payload["source_checks"]["universal_oracle_cli_evidence_supports_resident_race_prepass"] is True
    assert (
        payload["source_checks"]["universal_oracle_cli_evidence_exposes_shared_symmetry_ordering_alias"]
        is True
    )
    assert payload["source_checks"]["universal_batch_evidence_script_uses_solve_many"] is True
    assert payload["source_checks"]["universal_batch_evidence_script_supports_resident_h48_batch"] is True
    assert payload["source_checks"]["public_oracle_cli_exposes_universal_resident_batch"] is True
    assert payload["source_checks"]["public_oracle_cli_exposes_rubikoptimal_race"] is True
    assert payload["source_checks"]["public_oracle_cli_exposes_resident_race_prepass"] is True
    assert payload["source_checks"]["public_oracle_cli_exposes_rubikoptimal_symmetry_batch"] is True
    assert payload["source_checks"]["public_oracle_cli_exposes_rubikoptimal_symmetry_race"] is True
    assert payload["source_checks"]["public_oracle_cli_exposes_h48_symmetry_prepass"] is True
    assert payload["source_checks"]["public_oracle_cli_exposes_parallel_h48_symmetry_race"] is True
    assert payload["source_checks"]["public_oracle_cli_can_disable_universal_shortcuts"] is True
    assert payload["source_checks"]["public_oracle_cli_exposes_learned_certificate_log"] is True
    assert payload["source_checks"]["universal_oracle_cli_evidence_script_uses_public_cli"] is True
    assert payload["source_checks"]["universal_oracle_cli_evidence_can_disable_shortcuts"] is True
    assert payload["source_checks"]["universal_oracle_cli_evidence_supports_known_distance_benchmark_corpus"] is True
    assert payload["source_checks"]["universal_oracle_cli_evidence_budgets_adaptive_hard_phases"] is True
    assert payload["source_checks"]["universal_oracle_cli_exposes_rotational_lower_bound_certificate"] is True
    assert payload["source_checks"]["universal_oracle_cli_exposes_late_nissy_core_direct_fallback"] is True
    assert payload["source_checks"]["known_distance_sweep_exposes_rubikoptimal_phases"] is True
    assert payload["source_checks"]["known_distance_sweep_exposes_resident_race_prepass"] is True
    assert payload["source_checks"]["known_distance_sweep_exposes_shared_symmetry_ordering_alias"] is True
    assert payload["source_checks"]["known_distance_sweep_budgets_shared_symmetry_ordering"] is True
    assert payload["source_checks"]["known_distance_sweep_exposes_h48_upper_bound_proof"] is True
    assert payload["source_checks"]["h48_generation_can_skip_distribution_scan_with_expected_constants"] is True
    assert payload["source_checks"]["h48_generation_exposes_mmap_sync_mode"] is True
    assert payload["source_checks"]["cloud_hardtail_campaign_forwards_h48_gendata_workbatch"] is True
    assert payload["source_checks"]["h48_capacity_recommends_h48_gendata_workbatch"] is True
    assert payload["source_checks"]["h48_backend_exposes_audited_native_compile_flags"] is True
    assert payload["source_checks"]["cloud_hardtail_campaign_plans_fast_every_state_workloads"] is True
    assert payload["source_checks"]["cloud_hardtail_campaign_has_workload_runner_and_evaluator"] is True
    assert payload["source_checks"]["cloud_hardtail_campaign_rejects_stale_workload_results"] is True
    assert payload["source_checks"]["cloud_hardtail_campaign_reuses_valid_passed_workload_evidence"] is True
    assert payload["source_checks"]["cloud_hardtail_workload_artifacts_are_content_fingerprinted"] is True
    assert payload["source_checks"]["cloud_hardtail_final_runtime_proof_requires_artifact_integrity"] is True
    assert payload["source_checks"]["cloud_hardtail_evaluator_requires_h48_dependency_validation"] is True
    assert payload["source_checks"]["cloud_hardtail_fasttarget_can_require_native_h48_only"] is True
    assert payload["source_checks"]["h48_stronger_table_campaign_uses_process_tree_timeout"] is True
    assert payload["source_checks"]["h48_stronger_table_campaign_streams_generation_progress"] is True
    assert payload["source_checks"]["h48_stronger_table_campaign_requires_full_checksum"] is True
    assert payload["source_checks"]["h48_table_generator_can_recover_exact_size_table_metadata"] is True
    assert payload["source_checks"]["h48_stronger_table_campaign_can_wait_for_safe_generation"] is True
    assert payload["source_checks"]["h48_stronger_table_campaign_logs_wait_safe_heartbeats"] is True
    assert payload["source_checks"]["h48_stronger_table_campaign_recomputes_auto_threads_during_wait"] is True
    assert payload["source_checks"]["h48_stronger_table_campaign_can_plan_detached_local_generation"] is True
    assert payload["source_checks"]["h48_stronger_table_campaign_can_probe_detached_local_status"] is True
    assert payload["source_checks"]["h48_stronger_table_campaign_status_parses_generation_progress"] is True
    assert payload["source_checks"]["h48_stronger_table_campaign_status_parses_waitsafe_heartbeats"] is True
    assert (
        payload["source_checks"]["h48_stronger_table_campaign_status_reports_optimized_generation_options"]
        is True
    )
    assert payload["source_checks"]["h48_stronger_table_campaign_exposes_mmap_memory_guard"] is True
    assert payload["source_checks"]["h48_generation_safety_uses_storage_aware_disk_multiplier"] is True
    assert payload["source_checks"]["h48_table_storage_root_is_relocatable"] is True
    assert payload["source_checks"]["h48_capacity_and_preflight_use_configured_table_root"] is True
    assert (
        payload["source_checks"]["h48_proof_volume_inspector_records_local_nonaws_launch_gate"]
        is True
    )
    assert payload["source_checks"]["h48_proof_volume_inspector_uses_configured_h48_table_root"] is True
    assert payload["source_checks"]["h48_stronger_table_campaign_can_stop_stale_detached_waiter"] is True
    assert payload["source_checks"]["h48_stronger_table_campaign_status_reports_process_resources"] is True
    assert payload["source_checks"]["h48_native_generation_workbatch_is_configurable"] is True
    assert payload["source_checks"]["h48_native_generation_uses_atomic_table_updates"] is True
    assert payload["source_checks"]["h48_native_generation_uses_atomic_work_scheduling"] is True
    assert payload["source_checks"]["h48_native_generation_uses_edge_only_symmetry_marking"] is True
    assert (
        payload["source_checks"]["h48_native_short_generation_uses_edge_only_symmetry_expansion"]
        is True
    )
    assert payload["source_checks"]["h48_contract_accepts_stronger_oracle_grade_solvers"] is True
    assert payload["source_checks"]["cloud_hardtail_runbook_renders_cloud_execution_scripts"] is True
    assert payload["source_checks"]["cloud_hardtail_runbook_enforces_leader_preflight_before_real_runs"] is True
    assert payload["source_checks"]["cloud_hardtail_runbook_validates_target_table_before_full"] is True
    assert payload["source_checks"]["cloud_hardtail_runbook_reuses_shared_h48_prerequisite_for_canary"] is True
    assert payload["source_checks"]["cloud_hardtail_runbook_separates_single_machine_and_staged_order"] is True
    assert payload["source_checks"]["cloud_hardtail_runbook_bootstraps_python_environment"] is True
    assert payload["source_checks"]["cloud_hardtail_runbook_records_nonaws_execution_summary"] is True
    assert payload["source_checks"]["cloud_hardtail_runbook_fingerprints_generated_files"] is True
    assert payload["source_checks"]["cloud_hardtail_preflight_records_machine_gate"] is True
    assert payload["source_checks"]["cloud_hardtail_preflight_records_target_h48_workspace"] is True
    assert (
        payload["source_checks"]["cloud_hardtail_preflight_supports_assumed_nonaws_machine_spec"]
        is True
    )
    assert payload["source_checks"]["h48_fasttarget_aws_provisioner_can_dryrun_target_ec2"] is True
    assert payload["source_checks"]["h48_fasttarget_aws_helpers_block_cli_by_default"] is True
    assert (
        payload["source_checks"]["h48_fasttarget_aws_helpers_are_archived_for_current_route"]
        is True
    )
    assert (
        payload["source_checks"][
            "h48_fasttarget_aws_security_group_can_prepare_dedicated_ssh_access"
        ]
        is True
    )
    assert (
        payload["source_checks"][
            "h48_fasttarget_aws_proof_runner_can_launch_wait_and_start_detached_proof"
        ]
        is True
    )
    assert (
        payload["source_checks"][
            "h48_fasttarget_aws_proof_runner_can_create_dedicated_sg_before_launch"
        ]
        is True
    )
    assert (
        payload["source_checks"][
            "h48_fasttarget_aws_proof_runner_can_cleanup_after_detached_proof"
        ]
        is True
    )
    assert (
        payload["source_checks"][
            "h48_fasttarget_aws_proof_runner_checkpoints_before_remote_wait"
        ]
        is True
    )
    assert (
        payload["source_checks"][
            "h48_fasttarget_aws_proof_runner_passes_detached_wait_windows"
        ]
        is True
    )
    assert (
        payload["source_checks"][
            "h48_fasttarget_aws_proof_runner_can_resume_from_checkpoint"
        ]
        is True
    )
    assert (
        payload["source_checks"][
            "h48_fasttarget_aws_proof_runner_writes_actionable_resume_command"
        ]
        is True
    )
    assert payload["source_checks"]["h48_fasttarget_remote_runner_syncs_runs_fetches_and_finalizes"] is True
    assert payload["source_checks"]["h48_fasttarget_remote_runner_runs_cloud_bootstrap"] is True
    assert payload["source_checks"]["h48_fasttarget_remote_runner_fetches_diagnostics_on_fail"] is True
    assert payload["source_checks"]["h48_fasttarget_remote_runner_can_run_prerequisite_stage_separately"] is True
    assert payload["source_checks"]["h48_fasttarget_remote_runner_can_run_preflight_only"] is True
    assert payload["source_checks"]["h48_fasttarget_remote_runner_can_start_prerequisites_detached"] is True
    assert payload["source_checks"]["h48_fasttarget_remote_runner_can_run_canary_after_prerequisites"] is True
    assert payload["source_checks"]["h48_fasttarget_remote_runner_can_probe_remote_status"] is True
    assert payload["source_checks"]["h48_fasttarget_remote_runner_status_reports_detached_prerequisites"] is True
    assert payload["source_checks"]["h48_fasttarget_remote_runner_status_reports_detached_full_proof"] is True
    assert payload["source_checks"]["h48_fasttarget_remote_runner_can_wait_for_detached_prerequisites"] is True
    assert (
        payload["source_checks"]["h48_fasttarget_remote_runner_can_recover_prerequisite_metadata"]
        is True
    )
    assert payload["source_checks"]["h48_fasttarget_remote_runner_can_install_fetched_prerequisites"] is True
    assert payload["source_checks"][
        "h48_fasttarget_remote_runner_preserves_install_on_resume_finalize"
    ] is True
    assert payload["source_checks"]["h48_fasttarget_remote_runner_can_start_full_detached"] is True
    assert payload["source_checks"]["h48_fasttarget_remote_runner_can_wait_for_detached_full"] is True
    assert payload["source_checks"]["h48_fasttarget_remote_runner_can_run_staged_detached_proof"] is True
    assert payload["source_checks"]["h48_fasttarget_remote_runner_can_run_detached_staged_proof"] is True
    assert payload["source_checks"][
        "h48_fasttarget_remote_runner_validates_results_archive_before_finalize"
    ] is True
    assert payload["source_checks"]["h48_fasttarget_remote_runner_can_resume_from_status"] is True
    assert payload["source_checks"]["h48_fasttarget_remote_runner_requires_final_contract_proof"] is True
    assert payload["source_checks"]["h48_fasttarget_nonaws_runner_forbids_aws_usage"] is True
    assert (
        payload["source_checks"]["h48_fasttarget_nonaws_runner_validates_h48h10_runbook_before_execute"]
        is True
    )
    assert (
        payload["source_checks"][
            "h48_fasttarget_nonaws_runner_requires_launchable_package_for_execute"
        ]
        is True
    )
    assert (
        payload["source_checks"][
            "h48_fasttarget_local_runner_requires_launchable_package_for_staged_execute"
        ]
        is True
    )
    assert (
        payload["source_checks"]["h48_fasttarget_remote_runner_supports_split_prerequisite_bundles"]
        is True
    )
    assert (
        payload["source_checks"]["h48_fasttarget_nonaws_runner_passes_split_prerequisite_bundle_mode"]
        is True
    )
    assert (
        payload["source_checks"][
            "h48_fasttarget_nonaws_proof_package_builds_byte_bound_manifest"
        ]
        is True
    )
    assert (
        payload["source_checks"][
            "h48_fasttarget_nonaws_launch_preparation_gathers_live_launch_evidence"
        ]
        is True
    )
    assert (
        payload["source_checks"][
            "h48_oracle_contract_requires_nonaws_runbook_fingerprint_validation"
        ]
        is True
    )
    assert (
        payload["source_checks"]["cloud_hardtail_runbook_can_recover_prerequisite_metadata"]
        is True
    )
    assert (
        payload["source_checks"]["cloud_hardtail_runbook_exports_split_prerequisite_table_bundle"]
        is True
    )
    assert payload["source_checks"]["h48_fasttarget_local_runner_runs_generated_nonaws_runbook"] is True
    assert (
        payload["source_checks"]["h48_fasttarget_local_runner_validates_h48h10_runbook_before_execute"]
        is True
    )
    assert (
        payload["source_checks"][
            "h48_fasttarget_local_runner_executes_staged_single_machine_order"
        ]
        is True
    )
    assert payload["source_checks"]["h48_worker_table_validation_script_full_checksums"] is True
    assert payload["source_checks"]["h48_table_bundle_creator_writes_split_manifest"] is True
    assert (
        payload["source_checks"]["h48_table_bundle_installer_skips_existing_full_checksum_target"]
        is True
    )
    assert (
        payload["source_checks"]["h48_table_bundle_installer_supports_split_manifest_bundle"]
        is True
    )
    assert payload["source_checks"]["h48_table_bundle_installer_hardlinks_extracted_bundle"] is True
    assert payload["source_checks"]["h48_split_bundle_smoke_script_records_isolated_install"] is True
    assert payload["source_checks"]["h48_proof_workflow_uses_persistent_checksum_certificate"] is True
    assert payload["source_checks"]["python_exact_certificate_cache_loads_nissy_benchmark_certificates"] is True
    assert payload["source_checks"]["nissy_benchmark_certificate_importer_verifies_rows"] is True
    assert payload["source_checks"]["universal_symmetry_evidence_script_uses_package_api"] is True
    assert payload["source_checks"]["certificate_inverse_evidence_script_uses_universal_api"] is True
    assert payload["source_checks"]["certificate_symmetry_evidence_script_uses_universal_api"] is True
    assert payload["source_checks"]["learned_certificate_cache_evidence_script_uses_universal_api"] is True
    assert payload["source_checks"]["h48_capacity_script_records_stronger_table_build_plan"] is True
    assert payload["source_checks"]["h48_contract_separates_fast_target_plan_from_local_table"] is True
    assert payload["source_checks"]["h48_table_generator_has_generation_safety_guard"] is True
    assert payload["source_checks"]["h48_table_generator_refuses_untrusted_existing_table"] is True
    assert payload["source_checks"]["h48_table_generator_can_recover_exact_size_table_metadata"] is True
    assert payload["source_checks"]["h48_generation_probe_uses_native_mmap_progress"] is True
    assert payload["source_checks"]["h48_generation_probe_records_native_workbatch"] is True
    assert payload["source_checks"]["h48_generation_uses_upstream_workbatch_default"] is True
    assert payload["source_checks"]["h48_generation_logs_scan_progress"] is True
    assert payload["source_checks"]["h48_generation_probe_is_bounded_and_cleans_partial"] is True
    assert payload["source_checks"]["h48_generation_probe_parses_native_progress"] is True
    assert payload["source_checks"]["fast_oracle_api_evidence_script_uses_package_api"] is True
    assert payload["source_checks"]["external_nissy_optimal_backend_exists"] is True
    assert payload["source_checks"]["external_nissy_optimal_uses_direct_state_bridge"] is True
    assert payload["source_checks"]["external_nissy_batch_recovers_partial_timeout_rows"] is True
    assert payload["source_checks"]["external_nissy_batch_orders_shorter_scrambles_first"] is True
    assert payload["source_checks"]["external_nissy_core_direct_backend_exists"] is True
    assert payload["source_checks"]["external_nissy_core_direct_backend_uses_h48_table_symlink"] is True
    assert payload["source_checks"]["external_nissy_core_direct_backend_enforces_optimal_zero"] is True
    assert payload["source_checks"]["external_nissy_core_direct_batch_backend_reuses_h48_table_symlink"] is True
    assert payload["source_checks"]["external_nissy_core_python_resident_backend_exists"] is True
    assert payload["source_checks"]["external_nissy_core_python_resident_has_safe_table_size_gate"] is True
    assert payload["source_checks"]["external_nissy_core_python_resident_uses_mmap_buffer_when_available"] is True
    assert payload["source_checks"]["external_nissy_core_python_resident_auto_allows_large_mmap_tables"] is True
    assert payload["source_checks"]["external_nissy_core_python_resident_mmap_evidence_script_exists"] is True
    assert payload["source_checks"]["cli_exposes_nissy_core_direct_backend"] is True
    assert payload["source_checks"]["external_nissy_table_installer_fetches_single_range"] is True
    assert payload["source_checks"]["external_nissy_table_verifier_checks_complete_public_install"] is True
    assert payload["source_checks"]["optimal_3x3_script_exposes_nissy_core_direct_backend"] is True
    assert payload["artifact_checks"]["h48_trusted_metadata_valid"] is True
    assert payload["artifact_checks"]["nissy_public_optimal_table_installed"] is True
    assert payload["artifact_checks"]["nissy_public_tables_complete"] is True
    assert payload["measured_evidence"]["nissy_public_archive_table_entry_count"] == 18
    assert payload["measured_evidence"]["nissy_public_installed_table_count"] == 18
    assert payload["measured_evidence"]["nissy_public_ptable_reports_missing_tables"] is False
    assert payload["measured_evidence"]["nissy_public_tables_complete_path"].endswith(
        "_complete_public_current.json"
    )
    assert payload["artifact_checks"]["h48_capacity_stronger_table_plan_valid"] is True
    assert payload["artifact_checks"]["h48_capacity_fast_target_proof_plan_valid"] is True
    assert (
        payload["artifact_checks"]["h48_proof_volume_candidates_current_local_machine_recorded"]
        is True
    )
    assert payload["artifact_checks"]["h48_generation_probe_records_h48h8_lowload_bottleneck"] is True
    assert (
        payload["artifact_checks"]["h48_split_bundle_smoke_installed_isolated_trusted_table"]
        is True
    )
    assert (
        payload["artifact_checks"][
            "h48_split_bundle_oracle_grade_smoke_installed_isolated_trusted_table"
        ]
        is True
    )
    assert payload["artifact_checks"]["h48_fasttarget_runbook_bootstrap_planned"] is True
    assert (
        payload["artifact_checks"]["h48_fasttarget_assumed_nonaws_machine_preflight_passed"]
        is True
    )
    assert payload["artifact_checks"]["h48_fasttarget_aws_provision_dryrun_authorized"] is True
    assert payload["artifact_checks"]["h48_fasttarget_aws_security_group_dryrun_authorized"] is True
    assert payload["artifact_checks"]["h48_fasttarget_aws_proof_run_dryrun_planned"] is True
    assert payload["artifact_checks"]["h48_fasttarget_remote_preflight_dryrun_planned"] is True
    assert payload["artifact_checks"]["h48_fasttarget_remote_status_dryrun_planned"] is True
    assert payload["artifact_checks"]["h48_fasttarget_remote_wait_prerequisites_dryrun_planned"] is True
    assert (
        payload["artifact_checks"][
            "h48_fasttarget_remote_recover_prerequisite_metadata_dryrun_planned"
        ]
        is True
    )
    assert payload["artifact_checks"]["h48_fasttarget_remote_wait_prerequisites_install_dryrun_planned"] is True
    assert payload["artifact_checks"]["h48_fasttarget_remote_resume_install_dryrun_planned"] is True
    assert payload["artifact_checks"]["h48_fasttarget_remote_start_prerequisites_dryrun_planned"] is True
    assert payload["artifact_checks"]["h48_fasttarget_remote_staged_proof_dryrun_planned"] is True
    assert payload["artifact_checks"]["h48_fasttarget_remote_detached_staged_proof_dryrun_planned"] is True
    assert (
        payload["artifact_checks"][
            "h48_fasttarget_nonaws_detached_staged_proof_validates_runbook"
        ]
        is True
    )
    assert (
        payload["artifact_checks"][
            "h48_fasttarget_nonaws_detached_staged_proof_split_bundle_planned"
        ]
        is True
    )
    assert (
        payload["artifact_checks"]["h48_fasttarget_nonaws_proof_package_validated"]
        is True
    )
    assert payload["artifact_checks"]["h48_fasttarget_remote_start_full_dryrun_planned"] is True
    assert payload["artifact_checks"]["h48_fasttarget_remote_wait_full_dryrun_planned"] is True
    assert payload["empirical_checks"]["fast_optimal_oracle_api_all_exact"] is True
    assert payload["empirical_checks"]["resident_certification_all_exact"] is True
    assert payload["empirical_checks"]["external_nissy_optimal_stress_depth20_exact"] is True
    assert payload["empirical_checks"]["external_nissy_core_direct_thesis_all_exact"] is True
    assert payload["empirical_checks"]["external_nissy_core_resident_mmap_h48_table_all_exact"] is True
    assert payload["empirical_checks"]["portfolio_nissy_first_corpus_all_exact"] is True
    assert payload["empirical_checks"]["portfolio_nissy_state_recovery_all_exact"] is True
    assert payload["empirical_checks"]["portfolio_nissy_core_direct_state_all_exact"] is True
    assert payload["empirical_checks"]["portfolio_superflip_h48_fallback_exact"] is True
    assert payload["empirical_checks"]["portfolio_superflip_certificate_cache_exact"] is True
    assert payload["empirical_checks"]["race_optimal_oracle_lowload_exact"] is True
    assert payload["empirical_checks"]["race_nissy_core_direct_lowload_exact"] is True
    assert payload["empirical_checks"]["resident_race_optimal_oracle_lowload_exact"] is True
    assert payload["empirical_checks"]["resident_race_nissy_core_direct_lowload_exact"] is True
    assert payload["empirical_checks"]["universal_optimal_oracle_lowload_exact"] is True
    assert payload["empirical_checks"]["universal_nissy_core_direct_lowload_exact"] is True
    assert payload["empirical_checks"]["universal_rubikoptimal_race_lowload_exact"] is True
    assert payload["empirical_checks"]["rubikoptimal_resident_oracle_lowload_exact"] is True
    assert payload["empirical_checks"]["rubikoptimal_oracle_stream_lowload_exact"] is True
    assert payload["empirical_checks"]["universal_h48_symmetry_lowload_exact"] is True
    assert payload["empirical_checks"]["universal_batch_oracle_corpus_lowload_exact"] is True
    assert payload["empirical_checks"]["universal_resident_h48_batch_lowload_exact"] is True
    assert payload["empirical_checks"]["universal_oracle_cli_optimized_lowload_exact"] is True
    assert payload["empirical_checks"]["universal_oracle_cli_broader_lowload_exact"] is True
    assert payload["empirical_checks"]["universal_oracle_cli_adaptive_lowload_exact"] is True
    assert payload["empirical_checks"]["universal_oracle_cli_expanded_adaptive_lowload_exact"] is True
    assert payload["empirical_checks"]["universal_oracle_cli_h48_symmetry_lowload_exact"] is True
    assert payload["empirical_checks"]["universal_oracle_cli_h48_parallel_symmetry_lowload_exact"] is True
    assert payload["empirical_checks"]["universal_oracle_cli_rotational_lower_bound_certificate_exact"] is True
    assert payload["empirical_checks"]["universal_oracle_cli_late_nissy_core_direct_fallback_exact"] is True
    assert payload["empirical_checks"]["universal_oracle_cli_live_no_shortcuts_lowload_exact"] is True
    assert payload["empirical_checks"]["universal_oracle_cli_live_no_shortcuts_broader_lowload_exact"] is True
    assert payload["empirical_checks"]["universal_oracle_cli_known_distance_17_no_shortcuts_lowload_exact"] is True
    assert payload["empirical_checks"]["universal_oracle_cli_known_distance_17_18_adaptive_lowload_exact"] is True
    assert payload["empirical_checks"]["universal_oracle_cli_known_distance_19_adaptive_lowload_exact"] is True
    assert payload["empirical_checks"]["universal_oracle_cli_known_distance_20_adaptive_lowload_exact"] is True
    assert (
        payload["empirical_checks"]["universal_oracle_cli_known_distance_20_offset1_adaptive_lowload_exact"]
        is True
    )
    assert (
        payload["empirical_checks"][
            "universal_oracle_cli_known_distance_20_offset1_trimmed_prepass_lowload_exact"
        ]
        is True
    )
    assert (
        payload["empirical_checks"]["nissy_benchmark_certificates_imported_all_external_label_exact"]
        is True
    )
    assert (
        payload["empirical_checks"][
            "universal_oracle_cli_known_distance_16_20_certificate_cache_external_label_exact"
        ]
        is True
    )
    assert payload["empirical_checks"]["universal_symmetry_oracle_lowload_exact"] is True
    assert payload["empirical_checks"]["certificate_cache_inverse_closure_lowload_exact"] is True
    assert payload["empirical_checks"]["certificate_cache_symmetry_closure_lowload_exact"] is True
    assert payload["empirical_checks"]["certificate_cache_expanded_symmetry_closure_lowload_exact"] is True
    assert payload["empirical_checks"]["learned_certificate_cache_lowload_exact"] is True
    assert payload["all_state_exact_contract_supported"] is True
    assert payload["fast_optimal_oracle_implemented_for_every_valid_3x3_state"] is True
    assert payload["empirical_fast_corpus_supported"] is True
    assert payload["cloud_runtime_proof"]["evaluation_present"] is True
    assert payload["cloud_runtime_proof"]["passed"] is False
    assert payload["fast_runtime_proven_for_every_possible_state"] is False
    assert payload["measured_evidence"]["cloud_hardtail_runtime_proof_passed"] is False
    assert payload["measured_evidence"]["h48_capacity_stronger_table_plan_solvers"] == [
        "h48h8",
        "h48h9",
        "h48h10",
        "h48h11",
    ]
    assert payload["measured_evidence"]["h48_capacity_fast_target_proof_plan_valid"] is True
    assert payload["measured_evidence"]["h48_capacity_plan_recommends_optimized_generation"] is True
    assert payload["measured_evidence"]["h48_capacity_can_claim_every_state_fast"] is False
    assert payload["measured_evidence"]["h48_capacity_fast_target_solver"] == "h48h10"
    assert payload["measured_evidence"]["h48_capacity_fast_target_expected_size_bytes"] == 30_336_314_216
    assert payload["measured_evidence"]["h48_capacity_fast_target_table_trusted"] is False
    assert payload["measured_evidence"]["h48_capacity_fast_target_safe_to_generate_now"] is False
    assert payload["measured_evidence"]["h48_capacity_fast_target_has_upstream_distance20_timing"] is True
    assert payload["measured_evidence"]["h48_capacity_fast_target_has_upstream_superflip_timing"] is True
    assert payload["measured_evidence"]["h48_fasttarget_assumed_nonaws_preflight_passed"] is True
    assert (
        payload["measured_evidence"]["h48_fasttarget_assumed_nonaws_preflight_machine_source"]
        == "assumed"
    )
    assert (
        payload["measured_evidence"]["h48_fasttarget_assumed_nonaws_preflight_workspace_satisfies"]
        is True
    )
    assert (
        payload["measured_evidence"]["h48_fasttarget_assumed_nonaws_preflight_runtime_proven"]
        is False
    )
    assert payload["measured_evidence"]["h48_proof_volume_candidate_count"] >= 1
    assert payload["measured_evidence"]["h48_proof_volume_launchable_for_generation"] is False
    assert payload["measured_evidence"]["h48_proof_volume_host_machine_satisfies"] is False
    assert payload["measured_evidence"]["h48_proof_volume_required_workspace_bytes"] == 34_886_761_349
    assert payload["measured_evidence"]["h48_fasttarget_nonaws_proof_package_passed"] is True
    assert payload["measured_evidence"]["h48_fasttarget_nonaws_proof_package_sha256"]
    assert payload["measured_evidence"]["h48_fasttarget_nonaws_proof_package_step_count"] == 15
    assert payload["measured_evidence"]["h48_fasttarget_nonaws_proof_package_mode"] == "planning"
    assert payload["measured_evidence"]["h48_fasttarget_nonaws_proof_package_launchable"] is False
    assert (
        payload["measured_evidence"]["h48_fasttarget_nonaws_proof_package_preflight_is_live"]
        is False
    )
    assert (
        payload["measured_evidence"]["h48_fasttarget_nonaws_proof_package_proof_volume_required"]
        is False
    )
    assert (
        payload["measured_evidence"]["h48_fasttarget_nonaws_proof_package_proof_volume_launchable"]
        is False
    )
    assert (
        payload["measured_evidence"]["h48_fasttarget_nonaws_proof_package_proof_volume_requirement"]
        is True
    )
    assert (
        payload["measured_evidence"]["h48_fasttarget_nonaws_proof_package_launchable_volume_count"]
        == 0
    )
    assert (
        payload["measured_evidence"][
            "h48_fasttarget_nonaws_proof_package_full_required_workload_count"
        ]
        == 8
    )
    assert (
        payload["measured_evidence"][
            "h48_fasttarget_nonaws_proof_package_contract_still_requires_runtime"
        ]
        is True
    )
    assert (
        payload["measured_evidence"]["h48_fasttarget_nonaws_proof_package_fast_runtime_proven"]
        is False
    )
    assert payload["measured_evidence"]["cloud_hardtail_contract_solver_matches_fast_target"] is False
    assert payload["measured_evidence"]["cloud_hardtail_contract_solver_meets_fast_target"] is False
    assert payload["cloud_runtime_proof"]["target_solver"] == "h48h10"
    assert payload["cloud_runtime_proof"]["contract_solver_matches_h48_fast_target"] is False
    assert payload["cloud_runtime_proof"]["contract_solver_meets_h48_fast_target"] is False
    assert payload["cloud_runtime_proof"]["h48_fast_target_table_trusted"] is False
    assert payload["cloud_runtime_proof"]["contract_solver_table_trusted"] is True
    assert payload["measured_evidence"]["h48_generation_probe_status"] == "timed_out"
    assert payload["measured_evidence"]["h48_generation_probe_safe_to_start"] is False
    assert payload["measured_evidence"]["h48_stronger_table_detached_status_target_solver"] == "h48h8"
    assert (
        payload["measured_evidence"]["h48_stronger_table_detached_status_target_trusted_table"]
        is False
    )
    assert (
        payload["measured_evidence"]["h48_stronger_table_detached_status_fast_runtime_proven"]
        is False
    )
    assert (
        payload["measured_evidence"]["h48_stronger_table_detached_status_generation_progress_available"]
        is False
    )
    assert payload["measured_evidence"]["h48_stronger_table_detached_status_waitsafe_sample_count"] >= 1
    assert payload["measured_evidence"]["h48_stronger_table_detached_status_gendata_workbatch"] == 256
    assert (
        payload["measured_evidence"][
            "h48_stronger_table_detached_status_generation_distribution_mode"
        ]
        == "expected_constants"
    )
    assert (
        payload["measured_evidence"]["h48_stronger_table_detached_status_generation_mmap_sync_mode"]
        == "async"
    )
    assert payload["measured_evidence"]["h48_stronger_table_detached_status_backend_extra_cflags"] == [
        "-march=native"
    ]
    assert payload["referenced_evidence_files"]["h48_stronger_table_detached_status"]
    assert payload["measured_evidence"]["certificate_cache_symmetry_closure_case_count"] >= 700
    assert payload["measured_evidence"]["certificate_cache_expanded_symmetry_closure_case_count"] > payload[
        "measured_evidence"
    ]["certificate_cache_symmetry_closure_case_count"]
    assert payload["measured_evidence"]["learned_certificate_cache_case_count"] >= 2
    assert payload["measured_evidence"]["learned_certificate_cache_jsonl_row_count"] >= payload[
        "measured_evidence"
    ]["learned_certificate_cache_case_count"]
    assert payload["measured_evidence"]["learned_certificate_cache_replay_selected_backends"] == [
        "exact-certificate-cache"
    ]
    assert payload["measured_evidence"]["universal_nissy_core_direct_case_count"] >= 1
    assert "nissy-core-direct" in payload["measured_evidence"]["universal_nissy_core_direct_nested_backends"]
    assert payload["measured_evidence"]["nissy_core_resident_mmap_case_count"] >= 2
    assert payload["measured_evidence"]["nissy_core_resident_mmap_table_data_modes"] == ["mmap"]
    assert payload["measured_evidence"]["universal_rubikoptimal_race_case_count"] >= 1
    assert "rubikoptimal-race" in payload["measured_evidence"]["universal_rubikoptimal_race_selected_backends"]
    assert payload["measured_evidence"]["rubikoptimal_resident_oracle_case_count"] >= 2
    assert payload["measured_evidence"]["rubikoptimal_resident_oracle_start_count"] == 1
    assert payload["measured_evidence"]["rubikoptimal_resident_oracle_reused_rows"] >= 1
    assert payload["measured_evidence"]["rubikoptimal_oracle_stream_case_count"] >= 3
    assert payload["measured_evidence"]["rubikoptimal_oracle_stream_reused_rows"] >= 1
    assert payload["measured_evidence"]["universal_h48_symmetry_case_count"] >= 1
    assert payload["measured_evidence"]["universal_h48_symmetry_selected_rotations"]
    assert payload["measured_evidence"]["universal_resident_h48_batch_case_count"] >= 3
    assert "resident-h48-batch" in payload["measured_evidence"]["universal_resident_h48_batch_nested_backends"]
    assert payload["measured_evidence"]["universal_oracle_cli_case_count"] >= 3
    assert payload["measured_evidence"]["universal_oracle_cli_resident_h48_batch_rows"] >= 1
    assert "resident-h48-batch" in payload["measured_evidence"]["universal_oracle_cli_selected_backends"]
    assert payload["measured_evidence"]["universal_oracle_cli_broader_case_count"] >= 5
    assert payload["measured_evidence"]["universal_oracle_cli_broader_resident_h48_batch_rows"] >= 1
    assert payload["measured_evidence"]["universal_oracle_cli_broader_resident_h48_fallback_rows"] >= 1
    assert "portfolio-after-resident-h48-fallback" in payload["measured_evidence"][
        "universal_oracle_cli_broader_selected_backends"
    ]
    assert payload["measured_evidence"]["universal_oracle_cli_adaptive_case_count"] >= 5
    assert payload["measured_evidence"]["universal_oracle_cli_adaptive_portfolio_prepass_rows"] >= 1
    assert payload["measured_evidence"]["universal_oracle_cli_adaptive_max_runtime_seconds"] < payload[
        "measured_evidence"
    ]["universal_oracle_cli_broader_max_runtime_seconds"]
    assert "portfolio-before-resident-h48-batch" in payload["measured_evidence"][
        "universal_oracle_cli_adaptive_selected_backends"
    ]

    assert payload["measured_evidence"]["universal_oracle_cli_expanded_adaptive_case_count"] >= 12
    assert payload["measured_evidence"]["universal_oracle_cli_expanded_adaptive_hard_case_count"] >= 2
    assert payload["measured_evidence"]["universal_oracle_cli_expanded_adaptive_contains_superflip"] is True
    assert "exact-certificate-cache" in payload["measured_evidence"][
        "universal_oracle_cli_expanded_adaptive_selected_backends"
    ]
    assert payload["measured_evidence"]["universal_oracle_cli_h48_parallel_symmetry_case_count"] >= 1
    assert payload["measured_evidence"]["universal_oracle_cli_h48_parallel_symmetry_rows"] >= 1
    assert payload["measured_evidence"]["universal_oracle_cli_h48_parallel_symmetry_selected_backends"] == [
        "parallel-h48-symmetry-race"
    ]
    assert payload["measured_evidence"]["universal_oracle_cli_rotational_lower_bound_case_count"] >= 1
    assert payload["measured_evidence"]["universal_oracle_cli_rotational_lower_bound_symmetry_variants"] == 23
    assert payload["measured_evidence"]["universal_oracle_cli_rotational_lower_bound_selected_backends"] == [
        "upper-lower-certificate"
    ]
    assert payload["measured_evidence"]["universal_oracle_cli_upper_lower_batch_case_count"] >= 2
    assert payload["measured_evidence"]["universal_oracle_cli_upper_lower_batch_rows"] >= 1
    assert payload["measured_evidence"]["universal_oracle_cli_upper_lower_batch_lower_bound_rows"] >= 1
    assert "upper-lower-certificate" in payload["measured_evidence"][
        "universal_oracle_cli_upper_lower_batch_selected_backends"
    ]
    assert payload["measured_evidence"]["universal_oracle_cli_late_nissy_core_direct_case_count"] >= 1
    assert payload["measured_evidence"]["universal_oracle_cli_late_nissy_core_direct_rows"] >= 1
    assert payload["measured_evidence"]["universal_oracle_cli_late_nissy_core_direct_selected_backends"] == [
        "portfolio-after-resident-h48-fallback"
    ]
    assert payload["measured_evidence"]["universal_oracle_cli_known_distance_17_case_count"] >= 1
    assert payload["measured_evidence"]["universal_oracle_cli_known_distance_17_distances"] == [17]
    assert payload["measured_evidence"]["universal_oracle_cli_known_distance_17_max_backend_solve_seconds"] <= 120
    assert payload["measured_evidence"]["universal_oracle_cli_known_distance_adaptive_case_count"] >= 2
    assert payload["measured_evidence"]["universal_oracle_cli_known_distance_adaptive_distances"] == [17, 18]
    assert (
        payload["measured_evidence"]["universal_oracle_cli_known_distance_adaptive_max_runtime_seconds"]
        < payload["measured_evidence"]["universal_oracle_cli_known_distance_17_max_runtime_seconds"]
        * 2
    )
    assert payload["measured_evidence"]["universal_oracle_cli_known_distance_adaptive_selected_backends"] == [
        "portfolio-before-resident-h48-batch"
    ]
    assert payload["measured_evidence"]["universal_oracle_cli_known_distance_19_case_count"] >= 1
    assert payload["measured_evidence"]["universal_oracle_cli_known_distance_19_distances"] == [19]
    assert payload["measured_evidence"]["universal_oracle_cli_known_distance_19_max_runtime_seconds"] <= 240
    assert payload["measured_evidence"]["universal_oracle_cli_known_distance_19_max_backend_solve_seconds"] <= 60
    assert payload["measured_evidence"]["universal_oracle_cli_known_distance_19_selected_backends"] == [
        "portfolio-before-resident-h48-batch"
    ]
    assert payload["measured_evidence"]["universal_oracle_cli_known_distance_20_case_count"] >= 1
    assert payload["measured_evidence"]["universal_oracle_cli_known_distance_20_distances"] == [20]
    assert payload["measured_evidence"]["universal_oracle_cli_known_distance_20_max_runtime_seconds"] <= 540
    assert payload["measured_evidence"]["universal_oracle_cli_known_distance_20_max_backend_solve_seconds"] <= 240
    assert payload["measured_evidence"]["universal_oracle_cli_known_distance_20_selected_backends"] == [
        "portfolio-before-resident-h48-batch"
    ]
    assert payload["measured_evidence"]["universal_oracle_cli_known_distance_20_offset1_case_count"] >= 1
    assert payload["measured_evidence"]["universal_oracle_cli_known_distance_20_offset1_distances"] == [20]
    assert payload["measured_evidence"]["universal_oracle_cli_known_distance_20_offset1_max_runtime_seconds"] <= 540
    assert (
        payload["measured_evidence"][
            "universal_oracle_cli_known_distance_20_offset1_max_backend_solve_seconds"
        ]
        <= 240
    )
    assert payload["measured_evidence"]["universal_oracle_cli_known_distance_20_offset1_selected_backends"] == [
        "portfolio-before-resident-h48-batch"
    ]
    assert (
        payload["measured_evidence"][
            "universal_oracle_cli_known_distance_20_offset1_benchmark_offset_per_distance"
        ]
        == 1
    )
    assert (
        payload["measured_evidence"][
            "universal_oracle_cli_known_distance_20_offset1_trimmed_prepass_case_count"
        ]
        >= 1
    )
    assert payload["measured_evidence"][
        "universal_oracle_cli_known_distance_20_offset1_trimmed_prepass_distances"
    ] == [20]
    assert (
        payload["measured_evidence"][
            "universal_oracle_cli_known_distance_20_offset1_trimmed_prepass_max_runtime_seconds"
        ]
        <= 240
    )
    assert (
        payload["measured_evidence"][
            "universal_oracle_cli_known_distance_20_offset1_trimmed_prepass_max_backend_solve_seconds"
        ]
        <= 180
    )
    assert payload["measured_evidence"][
        "universal_oracle_cli_known_distance_20_offset1_trimmed_prepass_selected_backends"
    ] == ["resident-h48-batch-after-portfolio-prepass"]
    assert (
        payload["measured_evidence"][
            "universal_oracle_cli_known_distance_20_offset1_trimmed_prepass_timeout_seconds"
        ]
        == 30.0
    )
    assert payload["measured_evidence"]["nissy_benchmark_certificate_imported_case_count"] >= 125
    assert payload["measured_evidence"]["nissy_benchmark_certificate_imported_distances"] == [
        16,
        17,
        18,
        19,
        20,
    ]
    assert (
        payload["measured_evidence"]["universal_oracle_cli_known_distance_certificate_cache_case_count"]
        >= 125
    )
    assert payload["measured_evidence"]["universal_oracle_cli_known_distance_certificate_cache_distances"] == [
        16,
        17,
        18,
        19,
        20,
    ]
    assert payload["measured_evidence"][
        "universal_oracle_cli_known_distance_certificate_cache_selected_backends"
    ] == ["exact-certificate-cache"]
    assert (
        payload["measured_evidence"][
            "universal_oracle_cli_known_distance_certificate_cache_max_runtime_seconds"
        ]
        <= 5
    )
    assert payload["measured_evidence"][
        "universal_oracle_cli_known_distance_20_offset2_rubikoptimal_live_statuses"
    ] == ["timeout"]
    assert payload["measured_evidence"][
        "universal_oracle_cli_known_distance_20_offset2_rubikoptimal_live_selected_backends"
    ] == ["rubikoptimal-after-universal-fallback"]
    assert (
        payload["measured_evidence"][
            "universal_oracle_cli_known_distance_20_offset2_rubikoptimal_live_max_runtime_seconds"
        ]
        >= 600
    )
    assert (
        payload["measured_evidence"]["known_distance_20_offset2_rubikoptimal_live_sweep_failed_offset_count"]
        == 1
    )
    assert payload["measured_evidence"]["known_distance_20_offset2_rubikoptimal_live_sweep_row_statuses"] == [
        "timeout"
    ]
    assert payload["measured_evidence"]["universal_symmetry_oracle_case_count"] >= 1
    assert payload["passed"] is True


def test_h48h10_contract_keeps_fast_target_plan_separate_from_missing_table():
    payload = build_contract_payload(root=repository_root(), profile="thesis", seed=2026, solver="h48h10")

    assert payload["source_checks"]["h48_contract_separates_fast_target_plan_from_local_table"] is True
    assert (
        payload["source_checks"]["h48_proof_volume_inspector_records_local_nonaws_launch_gate"]
        is True
    )
    assert (
        payload["source_checks"]["cloud_hardtail_preflight_supports_assumed_nonaws_machine_spec"]
        is True
    )
    assert payload["artifact_checks"]["h48_capacity_fast_target_proof_plan_valid"] is True
    assert (
        payload["artifact_checks"]["h48_proof_volume_candidates_current_local_machine_recorded"]
        is True
    )
    assert (
        payload["artifact_checks"]["h48_fasttarget_assumed_nonaws_machine_preflight_passed"]
        is True
    )
    assert payload["measured_evidence"]["h48_capacity_fast_target_proof_plan_valid"] is True
    assert payload["measured_evidence"]["h48_capacity_plan_recommends_optimized_generation"] is True
    assert payload["measured_evidence"]["h48_capacity_fast_target_solver"] == "h48h10"
    assert payload["measured_evidence"]["h48_capacity_fast_target_expected_size_bytes"] == 30_336_314_216
    assert payload["measured_evidence"]["h48_fasttarget_assumed_nonaws_preflight_passed"] is True
    assert (
        payload["measured_evidence"]["h48_fasttarget_assumed_nonaws_preflight_machine_source"]
        == "assumed"
    )
    assert (
        payload["measured_evidence"]["h48_fasttarget_assumed_nonaws_preflight_runtime_proven"]
        is False
    )
    assert payload["measured_evidence"]["h48_proof_volume_launchable_for_generation"] is False
    assert (
        payload["measured_evidence"]["h48_fasttarget_nonaws_proof_package_proof_volume_launchable"]
        is False
    )
    assert (
        payload["measured_evidence"]["h48_fasttarget_nonaws_proof_package_launchable_volume_count"]
        == 0
    )

    if payload["measured_evidence"]["h48_capacity_fast_target_table_trusted"] is False:
        assert payload["artifact_checks"]["h48_capacity_stronger_table_plan_valid"] is False
        assert payload["all_state_exact_contract_supported"] is False
        assert payload["fast_runtime_proven_for_every_possible_state"] is False


def test_cloud_runtime_proof_requires_full_scope_passing_campaign():
    base_workloads = [
        {"kind": "public_known_distance_hardtail_sweep"},
        {"kind": "h48_stronger_table_generation_and_certification"},
        {"kind": "rubikoptimal_table_complete_hardcase"},
    ]
    evaluation = {
        "payload": {
            "all_required_workloads_passed": True,
            "all_required_artifact_integrity_passed": True,
            "artifact_integrity_required_workload_count": 3,
            "artifact_integrity_passed_workload_count": 3,
            "cloud_runtime_evidence_passed": True,
            "thesis_audit_acceptance_gates_passed": True,
            "missing_or_failed_workloads": [],
            "workload_count": 3,
            "evaluated_workload_count": 3,
        },
        "path": "results/processed/cloud_eval.json",
        "plan_path": "results/processed/cloud_plan.json",
        "plan": {
            "claim_scope": "full",
            "distance": 20,
            "selected_offset_start": 0,
            "selected_offset_end": 25,
            "available_scramble_rows": 25,
            "workloads": base_workloads,
        },
    }

    proof = _cloud_runtime_proof_from_evaluation(evaluation)
    assert proof["passed"] is True
    assert proof["full_distance20_hardtail_coverage"] is True
    assert proof["all_required_artifact_integrity_passed"] is True
    assert proof["artifact_integrity_required_workload_count"] == 3

    target_mismatch_proof = _cloud_runtime_proof_from_evaluation(
        evaluation,
        solver="h48h7",
        target_solver="h48h10",
        target_table_trusted=False,
        solver_table_trusted=True,
    )
    assert target_mismatch_proof["passed"] is False
    assert target_mismatch_proof["contract_solver_matches_h48_fast_target"] is False
    assert target_mismatch_proof["contract_solver_meets_h48_fast_target"] is False
    assert target_mismatch_proof["h48_fast_target_table_trusted"] is False

    target_plan = {
        **evaluation,
        "plan": {
            **evaluation["plan"],
            "solver": "h48h10",
        },
    }
    target_proof = _cloud_runtime_proof_from_evaluation(
        target_plan,
        solver="h48h10",
        target_solver="h48h10",
        target_table_trusted=True,
        solver_table_trusted=True,
    )
    assert target_proof["passed"] is True
    assert target_proof["plan_solver_matches_h48_fast_target"] is True
    assert target_proof["plan_solver_meets_h48_fast_target"] is True

    stronger_plan = {
        **evaluation,
        "plan": {
            **evaluation["plan"],
            "solver": "h48h11",
        },
    }
    stronger_proof = _cloud_runtime_proof_from_evaluation(
        stronger_plan,
        solver="h48h11",
        target_solver="h48h10",
        target_table_trusted=False,
        solver_table_trusted=True,
    )
    assert stronger_proof["passed"] is True
    assert stronger_proof["plan_solver_matches_h48_fast_target"] is False
    assert stronger_proof["plan_solver_meets_h48_fast_target"] is True

    no_integrity_evaluation = {
        **evaluation,
        "payload": {
            **evaluation["payload"],
            "all_required_artifact_integrity_passed": False,
            "artifact_integrity_passed_workload_count": 2,
        },
    }
    no_integrity_proof = _cloud_runtime_proof_from_evaluation(no_integrity_evaluation)
    assert no_integrity_proof["passed"] is False
    assert no_integrity_proof["all_required_artifact_integrity_passed"] is False

    canary_evaluation = {
        **evaluation,
        "plan": {
            **evaluation["plan"],
            "claim_scope": "canary",
            "selected_offset_start": 2,
            "selected_offset_end": 5,
        },
    }
    canary_proof = _cloud_runtime_proof_from_evaluation(canary_evaluation)
    assert canary_proof["passed"] is False
    assert canary_proof["full_distance20_hardtail_coverage"] is False


def test_cloud_runtime_evaluation_lookup_prefers_full_scope_over_newer_canary(tmp_path):
    processed = tmp_path / "results" / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    full_plan = {
        "profile": "thesis",
        "seed": 2026,
        "solver": "h48h7",
        "claim_scope": "full",
    }
    canary_plan = {
        "profile": "thesis",
        "seed": 2026,
        "solver": "h48h7",
        "claim_scope": "canary",
    }
    full_plan_path = processed / "full_plan.json"
    canary_plan_path = processed / "canary_plan.json"
    full_plan_path.write_text(json.dumps(full_plan), encoding="utf-8")
    canary_plan_path.write_text(json.dumps(canary_plan), encoding="utf-8")
    (processed / "cloud_hardtail_campaign_evaluation_full.json").write_text(
        json.dumps({"plan_path": "results/processed/full_plan.json"}),
        encoding="utf-8",
    )
    (processed / "cloud_hardtail_campaign_evaluation_canary.json").write_text(
        json.dumps({"plan_path": "results/processed/canary_plan.json"}),
        encoding="utf-8",
    )

    latest = _latest_cloud_hardtail_evaluation(
        root=tmp_path,
        profile="thesis",
        seed=2026,
        solver="h48h7",
    )

    assert latest is not None
    assert latest["plan"]["claim_scope"] == "full"

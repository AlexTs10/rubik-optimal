import json
import hashlib
from pathlib import Path

from scripts.experimental.build_h48_fasttarget_proof_package import build_proof_package
from scripts.experimental.prepare_h48_fasttarget_nonaws_launch import prepare_launch_package
from scripts.experimental.run_h48_fasttarget_nonaws_proof import run_nonaws_fasttarget_proof


REQUIRED_RUNBOOK_SCRIPTS = [
    "bootstrap_cloud_machine",
    "preflight_leader",
    "preflight_worker",
    "run_full_prerequisites",
    "collect_prerequisite_tables",
    "collect_prerequisite_table_parts",
    "validate_prerequisite_tables",
    "recover_prerequisite_metadata",
    "run_canary_after_prerequisites",
    "run_full",
    "evaluate_full",
    "collect_results",
    "unpack_results",
    "finalize_full_after_collect",
]


def _stronger_table_workload() -> dict:
    return {
        "id": "stronger_table_h48h10",
        "kind": "h48_stronger_table_generation_and_certification",
        "required_for_fast_every_state_claim": True,
        "h48_gendata_workbatch": 256,
        "command_args": [
            "python",
            "scripts/run_h48_stronger_table_campaign.py",
            "--profile",
            "thesis",
            "--seed",
            "2026",
            "--target-solver",
            "h48h10",
            "--threads",
            "16",
            "--generation-timeout",
            "43200.0",
            "--certification-timeout",
            "90.0",
            "--runtime-target",
            "60.0",
            "--artifact-suffix",
            "nonaws_test_shared_prereq",
            "--gendata-workbatch",
            "256",
            "--mmap-sync-mode",
            "async",
            "--backend-cflag=-march=native",
            "--skip-generation-distribution-scan",
        ],
    }


def _write_plan(root: Path, *, scope: str, suffix: str, selected_end: int) -> Path:
    processed = root / "results" / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    workloads = [_stronger_table_workload()]
    if scope == "full":
        workloads.extend(
            {
                "id": f"known_distance_20_shard_{index:03d}",
                "kind": "public_known_distance_hardtail_batch",
                "required_for_fast_every_state_claim": True,
            }
            for index in range(3)
        )
        workloads.append(
            {
                "id": "rubikoptimal_superflip_hardcase",
                "kind": "rubikoptimal_table_complete_hardcase",
                "required_for_fast_every_state_claim": True,
            }
        )
        workloads.extend(
            {
                "id": f"postprocess_{index:02d}",
                "kind": "postprocess_and_audit",
                "required_for_fast_every_state_claim": True,
            }
            for index in range(3)
        )
    else:
        workloads.append(
            {
                "id": "known_distance_20_shard_000",
                "kind": "public_known_distance_hardtail_batch",
                "required_for_fast_every_state_claim": True,
            }
        )
    path = processed / f"cloud_hardtail_campaign_plan_{scope}_{suffix}.json"
    path.write_text(
        json.dumps(
            {
                "solver": "h48h10",
                "profile": "thesis",
                "seed": 2026,
                "claim_scope": scope,
                "distance": 20,
                "h48_gendata_workbatch": 256,
                "selected_offset_start": 0,
                "selected_offset_end": selected_end,
                "available_scramble_rows": selected_end,
                "workloads": workloads,
            }
        ),
        encoding="utf-8",
    )
    return path


def _plan_summary(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    required_ids = [
        workload["id"]
        for workload in payload["workloads"]
        if workload.get("required_for_fast_every_state_claim") is True
    ]
    return {
        "solver": "h48h10",
        "profile": "thesis",
        "seed": 2026,
        "claim_scope": payload["claim_scope"],
        "distance": 20,
        "h48_gendata_workbatch": 256,
        "required_workload_count": len(required_ids),
        "required_workload_ids": required_ids,
        "hardtail_strategy": "native-h48-only",
    }


def _write_status_runbook(root: Path) -> Path:
    processed = root / "results" / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    runbook_dir = root / "results" / "cloud_hardtail_runbook_nonaws_test"
    runbook_dir.mkdir(parents=True, exist_ok=True)
    generated = {}
    for key in REQUIRED_RUNBOOK_SCRIPTS:
        script = runbook_dir / f"{key}.sh"
        script.write_text("#!/usr/bin/env bash\ntrue\n", encoding="utf-8")
        script.chmod(0o755)
        generated[key] = str(script.relative_to(root))
    canary_plan = _write_plan(root, scope="canary", suffix="nonaws_test", selected_end=3)
    full_plan = _write_plan(root, scope="full", suffix="nonaws_test", selected_end=25)
    path = processed / "cloud_hardtail_runbook_nonaws_test.json"
    path.write_text(
        json.dumps(
            {
                "run_suffix": "nonaws_test",
                "solver": "h48h10",
                "profile": "thesis",
                "seed": 2026,
                "status": "runbook_generated_not_runtime_evidence",
                "aws_required": False,
                "nonaws_generic_ssh_supported": True,
                "nonaws_entrypoint": "scripts/run_h48_fasttarget_nonaws_proof.py",
                "fast_runtime_proven_for_every_possible_state": False,
                "generated_files": generated,
                "generated_file_fingerprint_algorithm": "sha256-size-mode-v1",
                "generated_file_fingerprints": {
                    key: _file_fingerprint(root / relative, relative)
                    for key, relative in generated.items()
                },
                "canary_plan_path": str(canary_plan.relative_to(root)),
                "full_plan_path": str(full_plan.relative_to(root)),
                "canary_plan_summary": _plan_summary(canary_plan),
                "full_plan_summary": _plan_summary(full_plan),
                "recommended_minimum_cloud_machine": {
                    "h48_target_table_size_bytes": 30336314216,
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def _write_assumed_preflight(root: Path) -> Path:
    path = root / "results" / "processed" / "cloud_hardtail_preflight_assumed_nonaws.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "profile": "thesis",
                "seed": 2026,
                "solver": "h48h10",
                "passed": True,
                "machine_source": "assumed",
                "assumed_machine_not_runtime_evidence": True,
                "machine": {
                    "cpu_count": 16,
                    "memory_gib": 64.0,
                    "data_generated_h48_total_gib": 250.0,
                    "data_generated_h48_free_gib": 40.0,
                },
                "target_h48_workspace": {
                    "required_workspace_gib": 32.490828,
                    "available_workspace_gib": 40.0,
                    "satisfies_workspace": True,
                },
                "fast_runtime_proven_for_every_possible_state": False,
            }
        ),
        encoding="utf-8",
    )
    return path


def _write_live_preflight(root: Path) -> Path:
    path = root / "results" / "processed" / "cloud_hardtail_preflight_live_nonaws.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "profile": "thesis",
                "seed": 2026,
                "solver": "h48h10",
                "passed": True,
                "machine_source": "local",
                "assumed_machine_not_runtime_evidence": False,
                "machine": {
                    "cpu_count": 16,
                    "memory_gib": 64.0,
                    "data_generated_h48_total_gib": 250.0,
                    "data_generated_h48_free_gib": 40.0,
                },
                "target_h48_workspace": {
                    "required_workspace_gib": 32.490828,
                    "available_workspace_gib": 40.0,
                    "satisfies_workspace": True,
                },
                "fast_runtime_proven_for_every_possible_state": False,
            }
        ),
        encoding="utf-8",
    )
    return path


def _write_proof_volume_report(root: Path, *, launchable: bool) -> Path:
    path = root / "results" / "processed" / "h48_proof_volume_candidates_live_nonaws.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "artifact_kind": "h48_proof_volume_candidates",
                "profile": "thesis",
                "seed": 2026,
                "solver": "h48h10",
                "machine_source": "local",
                "h48_table_root_env": "RUBIK_OPTIMAL_H48_TABLE_ROOT",
                "host_machine_satisfies": launchable,
                "available_memory_satisfies": launchable,
                "threads_satisfy_cpu": launchable,
                "candidate_count": 1,
                "launchable_candidate_count": 1 if launchable else 0,
                "launchable_for_h48_generation": launchable,
                "requirements": {
                    "target_table_size_bytes": 30336314216,
                    "required_workspace_bytes": 34886761349,
                    "workspace_multiplier": 1.15,
                },
                "machine_reasons": [] if launchable else ["test machine is too small"],
                "best_candidate": {
                    "h48_table_root": "/mnt/sgarbas-h48/h48",
                    "launchable_for_h48_generation": launchable,
                },
                "fast_runtime_proven_for_every_possible_state": False,
            }
        ),
        encoding="utf-8",
    )
    return path


def _write_h48h10_contract(root: Path) -> Path:
    path = root / "results" / "processed" / "h48_oracle_contract_seed_2026_thesis_h48h10.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "passed": False,
                "all_state_exact_contract_supported": False,
                "empirical_fast_corpus_supported": False,
                "fast_runtime_proven_for_every_possible_state": False,
                "artifact_checks": {
                    "h48_metadata_present": False,
                    "h48_table_present": False,
                },
                "empirical_checks": {},
                "cloud_runtime_proof": {
                    "passed": False,
                    "missing_or_failed_workload_count": 8,
                    "reason": "missing proof workloads",
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def _file_fingerprint(path: Path, relative: str) -> dict:
    data = path.read_bytes()
    return {
        "path": relative,
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "mode_octal": oct(path.stat().st_mode & 0o777),
    }


def test_nonaws_fasttarget_wrapper_writes_provider_dry_run(tmp_path, monkeypatch):
    monkeypatch.delenv("RUBIK_OPTIMAL_ENABLE_AWS", raising=False)
    runbook = _write_status_runbook(tmp_path)

    payload, output = run_nonaws_fasttarget_proof(
        root=tmp_path,
        runbook_manifest_path=runbook,
        host="proof-host.example",
        remote_root="/mnt/sgarbas-h48",
        remote_action="status",
        execute=False,
        artifact_suffix="dryrun",
    )

    assert output.exists()
    assert payload["execution_provider"] == "generic_ssh_non_aws"
    assert payload["aws_usage_allowed"] is False
    assert payload["aws_command_scan"]["passed"] is True
    assert payload["runbook_validation"]["passed"] is True
    assert payload["runbook_validation"]["generated_file_fingerprint_count"] == len(
        REQUIRED_RUNBOOK_SCRIPTS
    )
    assert payload["runbook_validation"]["h48_gendata_workbatch"] == 256
    assert payload["execute"] is False
    assert payload["fast_runtime_proven_for_every_possible_state"] is False
    assert payload["underlying_remote_artifact"].startswith("results/processed/")


def test_h48_fasttarget_proof_package_records_nonaws_split_ready_bundle(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("RUBIK_OPTIMAL_ENABLE_AWS", raising=False)
    runbook = _write_status_runbook(tmp_path)
    preflight = _write_assumed_preflight(tmp_path)
    contract = _write_h48h10_contract(tmp_path)

    payload, output = build_proof_package(
        root=tmp_path,
        runbook_manifest_path=runbook,
        assumed_preflight_path=preflight,
        proof_volume_report_path=None,
        contract_path=contract,
        host="proof-host.example",
        remote_root="/mnt/sgarbas-h48",
        artifact_suffix="package",
    )

    assert output.exists()
    assert payload["artifact_kind"] == "h48_fasttarget_nonaws_proof_package"
    assert payload["passed"] is True
    assert payload["package_mode"] == "planning"
    assert payload["live_preflight_required"] is False
    assert payload["preflight_is_live_runtime_evidence"] is False
    assert payload["launchable_for_execution"] is False
    assert payload["readiness_classification"] == "planning_nonaws_proof_package"
    assert payload["execution_provider"] == "generic_ssh_non_aws"
    assert payload["prerequisite_bundle_mode"] == "split"
    assert payload["aws_command_scan"]["passed"] is True
    assert payload["runbook_validation"]["passed"] is True
    assert payload["checks"]["split_bundle_mode_planned"] is True
    assert payload["checks"]["archive_fetch_omitted_for_split_mode"] is True
    assert payload["checks"]["assumed_preflight_not_runtime_evidence"] is True
    assert payload["checks"]["preflight_requirement_satisfied"] is True
    assert payload["checks"]["proof_volume_report_present_or_not_required"] is True
    assert payload["checks"]["proof_volume_requirement_satisfied"] is True
    assert payload["checks"]["contract_still_requires_runtime_proof"] is True
    assert payload["assumed_preflight_summary"]["live_runtime_evidence"] is False
    assert payload["assumed_preflight_summary"]["preflight_requirement_satisfied"] is True
    assert payload["proof_volume_report_summary"]["present"] is False
    assert payload["proof_volume_report_summary"]["proof_volume_report_required"] is False
    assert payload["proof_volume_report_summary"]["proof_volume_requirement_satisfied"] is True
    assert payload["full_plan_summary"]["required_workload_count"] == 8
    assert "stronger_table_h48h10" in payload["full_plan_summary"]["required_workload_ids"]
    assert payload["package_sha256"]
    assert "--proof-package" in payload["operator_commands"]["generic_ssh_detached_staged_split_proof"]
    assert payload["operator_commands"]["generic_ssh_detached_staged_split_proof"].endswith(
        "--execute --artifact-suffix h48h10_detached_staged_nonaws_split_realhost"
    )
    assert payload["fast_runtime_proven_for_every_possible_state"] is False


def test_prepare_nonaws_launch_package_builds_launchable_manifest_from_live_evidence(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("RUBIK_OPTIMAL_ENABLE_AWS", raising=False)
    runbook = _write_status_runbook(tmp_path)
    contract = _write_h48h10_contract(tmp_path)

    def fake_write_preflight(**kwargs):
        path = _write_live_preflight(tmp_path)
        return json.loads(path.read_text(encoding="utf-8")), path

    def fake_write_proof_volume_report(**kwargs):
        path = _write_proof_volume_report(tmp_path, launchable=True)
        table = tmp_path / "thesis" / "tables" / "proof_volume.tex"
        table.parent.mkdir(parents=True, exist_ok=True)
        table.write_text("proof volume", encoding="utf-8")
        return json.loads(path.read_text(encoding="utf-8")), path, table

    monkeypatch.setattr(
        "scripts.experimental.prepare_h48_fasttarget_nonaws_launch.write_preflight",
        fake_write_preflight,
    )
    monkeypatch.setattr(
        "scripts.experimental.prepare_h48_fasttarget_nonaws_launch.write_proof_volume_report",
        fake_write_proof_volume_report,
    )

    payload, output = prepare_launch_package(
        root=tmp_path,
        profile="thesis",
        seed=2026,
        solver="h48h10",
        runbook_manifest_path=runbook,
        contract_path=contract,
        host="proof-host.example",
        remote_root="/mnt/sgarbas-h48",
        artifact_suffix="launch_ready",
    )

    assert output.exists()
    assert payload["artifact_kind"] == "h48_fasttarget_nonaws_launch_preparation"
    assert payload["status"] == "launchable"
    assert payload["passed"] is True
    assert payload["launchable_for_execution"] is True
    assert payload["heavy_generation_started"] is False
    assert payload["proof_workloads_started"] is False
    assert payload["proof_package_summary"]["package_mode"] == "launchable"
    assert payload["proof_package_summary"]["readiness_classification"] == (
        "launchable_nonaws_proof_package"
    )
    assert "--proof-package" in payload["next_execute_command_after_approval"]
    assert payload["proof_package_path"] in payload["next_execute_command_after_approval"]
    package = json.loads((tmp_path / payload["proof_package_path"]).read_text(encoding="utf-8"))
    assert package["launchable_for_execution"] is True
    assert package["fast_runtime_proven_for_every_possible_state"] is False
    assert payload["fast_runtime_proven_for_every_possible_state"] is False


def test_prepare_nonaws_launch_package_records_nonlaunchable_host_without_generation(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("RUBIK_OPTIMAL_ENABLE_AWS", raising=False)
    runbook = _write_status_runbook(tmp_path)
    contract = _write_h48h10_contract(tmp_path)

    def fake_write_preflight(**kwargs):
        path = _write_live_preflight(tmp_path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["passed"] = False
        payload["reasons"] = ["cpu_count 8 is below required 16"]
        path.write_text(json.dumps(payload), encoding="utf-8")
        return payload, path

    def fake_write_proof_volume_report(**kwargs):
        path = _write_proof_volume_report(tmp_path, launchable=False)
        table = tmp_path / "thesis" / "tables" / "proof_volume.tex"
        table.parent.mkdir(parents=True, exist_ok=True)
        table.write_text("proof volume", encoding="utf-8")
        return json.loads(path.read_text(encoding="utf-8")), path, table

    monkeypatch.setattr(
        "scripts.experimental.prepare_h48_fasttarget_nonaws_launch.write_preflight",
        fake_write_preflight,
    )
    monkeypatch.setattr(
        "scripts.experimental.prepare_h48_fasttarget_nonaws_launch.write_proof_volume_report",
        fake_write_proof_volume_report,
    )

    payload, output = prepare_launch_package(
        root=tmp_path,
        profile="thesis",
        seed=2026,
        solver="h48h10",
        runbook_manifest_path=runbook,
        contract_path=contract,
        host="proof-host.example",
        remote_root="/mnt/sgarbas-h48",
        artifact_suffix="not_ready",
    )

    assert output.exists()
    assert payload["status"] == "not_launchable"
    assert payload["passed"] is False
    assert payload["launchable_for_execution"] is False
    assert payload["heavy_generation_started"] is False
    assert payload["proof_workloads_started"] is False
    assert payload["next_execute_command_after_approval"] is None
    assert payload["preflight_summary"]["passed"] is False
    assert payload["proof_volume_summary"]["launchable_for_h48_generation"] is False
    assert payload["proof_package_summary"]["package_mode"] == "launchable"
    assert payload["proof_package_summary"]["launchable_for_execution"] is False
    assert payload["fast_runtime_proven_for_every_possible_state"] is False


def test_h48_fasttarget_proof_package_requires_live_preflight_for_launch(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("RUBIK_OPTIMAL_ENABLE_AWS", raising=False)
    runbook = _write_status_runbook(tmp_path)
    preflight = _write_assumed_preflight(tmp_path)
    contract = _write_h48h10_contract(tmp_path)

    payload, output = build_proof_package(
        root=tmp_path,
        runbook_manifest_path=runbook,
        assumed_preflight_path=preflight,
        proof_volume_report_path=None,
        contract_path=contract,
        host="proof-host.example",
        remote_root="/mnt/sgarbas-h48",
        artifact_suffix="launch_assumed",
        require_live_preflight=True,
    )

    assert output.exists()
    assert payload["passed"] is False
    assert payload["package_mode"] == "launchable"
    assert payload["live_preflight_required"] is True
    assert payload["preflight_is_live_runtime_evidence"] is False
    assert payload["assumed_preflight_allowed_for_package"] is False
    assert payload["launchable_for_execution"] is False
    assert payload["readiness_classification"] == "not_ready"
    assert payload["checks"]["assumed_preflight_not_runtime_evidence"] is True
    assert payload["checks"]["preflight_requirement_satisfied"] is False
    assert payload["checks"]["proof_volume_report_present_or_not_required"] is False
    assert payload["checks"]["proof_volume_requirement_satisfied"] is False
    assert payload["assumed_preflight_summary"]["live_runtime_evidence"] is False
    assert payload["assumed_preflight_summary"]["preflight_requirement_satisfied"] is False
    assert payload["proof_volume_report_summary"]["present"] is False
    assert payload["proof_volume_report_summary"]["proof_volume_report_required"] is True
    assert payload["proof_volume_report_summary"]["proof_volume_requirement_satisfied"] is False
    assert payload["fast_runtime_proven_for_every_possible_state"] is False


def test_h48_fasttarget_proof_package_refuses_live_preflight_without_launchable_volume(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("RUBIK_OPTIMAL_ENABLE_AWS", raising=False)
    runbook = _write_status_runbook(tmp_path)
    preflight = _write_live_preflight(tmp_path)
    proof_volume = _write_proof_volume_report(tmp_path, launchable=False)
    contract = _write_h48h10_contract(tmp_path)

    payload, output = build_proof_package(
        root=tmp_path,
        runbook_manifest_path=runbook,
        assumed_preflight_path=preflight,
        proof_volume_report_path=proof_volume,
        contract_path=contract,
        host="proof-host.example",
        remote_root="/mnt/sgarbas-h48",
        artifact_suffix="launch_live_no_volume",
        require_live_preflight=True,
    )

    assert output.exists()
    assert payload["passed"] is False
    assert payload["package_mode"] == "launchable"
    assert payload["live_preflight_required"] is True
    assert payload["preflight_is_live_runtime_evidence"] is True
    assert payload["assumed_preflight_allowed_for_package"] is False
    assert payload["proof_volume_report_launchable"] is False
    assert payload["launchable_for_execution"] is False
    assert payload["readiness_classification"] == "not_ready"
    assert payload["checks"]["assumed_preflight_not_runtime_evidence"] is True
    assert payload["checks"]["preflight_requirement_satisfied"] is True
    assert payload["checks"]["proof_volume_report_present_or_not_required"] is True
    assert payload["checks"]["proof_volume_requirement_satisfied"] is False
    assert payload["assumed_preflight_summary"]["machine_source"] == "local"
    assert payload["assumed_preflight_summary"]["live_runtime_evidence"] is True
    assert payload["assumed_preflight_summary"]["preflight_requirement_satisfied"] is True
    assert payload["proof_volume_report_summary"]["present"] is True
    assert payload["proof_volume_report_summary"]["proof_volume_report_required"] is True
    assert payload["proof_volume_report_summary"]["proof_volume_requirement_satisfied"] is False
    assert payload["fast_runtime_proven_for_every_possible_state"] is False


def test_h48_fasttarget_proof_package_launchable_with_live_preflight_and_volume(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("RUBIK_OPTIMAL_ENABLE_AWS", raising=False)
    runbook = _write_status_runbook(tmp_path)
    preflight = _write_live_preflight(tmp_path)
    proof_volume = _write_proof_volume_report(tmp_path, launchable=True)
    contract = _write_h48h10_contract(tmp_path)

    payload, output = build_proof_package(
        root=tmp_path,
        runbook_manifest_path=runbook,
        assumed_preflight_path=preflight,
        proof_volume_report_path=proof_volume,
        contract_path=contract,
        host="proof-host.example",
        remote_root="/mnt/sgarbas-h48",
        artifact_suffix="launch_live",
        require_live_preflight=True,
    )

    assert output.exists()
    assert payload["passed"] is True
    assert payload["package_mode"] == "launchable"
    assert payload["live_preflight_required"] is True
    assert payload["preflight_is_live_runtime_evidence"] is True
    assert payload["proof_volume_report_launchable"] is True
    assert payload["assumed_preflight_allowed_for_package"] is False
    assert payload["launchable_for_execution"] is True
    assert payload["readiness_classification"] == "launchable_nonaws_proof_package"
    assert payload["checks"]["preflight_requirement_satisfied"] is True
    assert payload["checks"]["proof_volume_report_present_or_not_required"] is True
    assert payload["checks"]["proof_volume_requirement_satisfied"] is True
    assert payload["proof_volume_report_summary"]["live_launchable_evidence"] is True
    assert payload["proof_volume_report_summary"]["proof_volume_requirement_satisfied"] is True
    assert payload["fast_runtime_proven_for_every_possible_state"] is False


def test_h48_fasttarget_proof_package_fails_when_runbook_plan_drifts(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("RUBIK_OPTIMAL_ENABLE_AWS", raising=False)
    runbook = _write_status_runbook(tmp_path)
    preflight = _write_assumed_preflight(tmp_path)
    contract = _write_h48h10_contract(tmp_path)
    manifest = json.loads(runbook.read_text(encoding="utf-8"))
    full_plan = tmp_path / manifest["full_plan_path"]
    plan = json.loads(full_plan.read_text(encoding="utf-8"))
    plan["workloads"][0]["command_args"] = [
        arg
        for arg in plan["workloads"][0]["command_args"]
        if arg != "--skip-generation-distribution-scan"
    ]
    full_plan.write_text(json.dumps(plan), encoding="utf-8")

    payload, _output = build_proof_package(
        root=tmp_path,
        runbook_manifest_path=runbook,
        assumed_preflight_path=preflight,
        proof_volume_report_path=None,
        contract_path=contract,
        host="proof-host.example",
        remote_root="/mnt/sgarbas-h48",
        artifact_suffix="drift",
    )

    assert payload["passed"] is False
    assert payload["checks"]["runbook_validation_passed"] is False
    assert any(
        issue["code"] == "stronger_table_missing_optimized_command_flag"
        for issue in payload["runbook_validation"]["issues"]
    )


def test_nonaws_fasttarget_wrapper_passes_split_prerequisite_bundle_mode(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("RUBIK_OPTIMAL_ENABLE_AWS", raising=False)
    runbook = _write_status_runbook(tmp_path)

    payload, output = run_nonaws_fasttarget_proof(
        root=tmp_path,
        runbook_manifest_path=runbook,
        host="proof-host.example",
        remote_root="/mnt/sgarbas-h48",
        remote_action="detached-staged-proof",
        prerequisite_bundle_mode="split",
        execute=False,
        artifact_suffix="split_dryrun",
    )

    assert output.exists()
    assert payload["execution_provider"] == "generic_ssh_non_aws"
    assert payload["prerequisite_bundle_mode"] == "split"
    assert payload["aws_command_scan"]["passed"] is True
    assert payload["runbook_validation"]["passed"] is True
    assert payload["underlying_remote_artifact"].startswith("results/processed/")
    assert "fetch_prerequisite_table_parts" in [row["id"] for row in payload["rows"]]
    assert "fetch_prerequisite_tables_archive" not in [
        row["id"] for row in payload["rows"]
    ]
    assert any(
        "collect_prerequisite_table_parts.sh" in str(row.get("shell_command", ""))
        for row in payload["rows"]
        if row["id"] == "remote_start_prerequisites_detached"
    )
    assert payload["fast_runtime_proven_for_every_possible_state"] is False


def test_nonaws_fasttarget_wrapper_can_plan_recovery_action(tmp_path, monkeypatch):
    monkeypatch.delenv("RUBIK_OPTIMAL_ENABLE_AWS", raising=False)
    runbook = _write_status_runbook(tmp_path)

    payload, output = run_nonaws_fasttarget_proof(
        root=tmp_path,
        runbook_manifest_path=runbook,
        host="proof-host.example",
        remote_root="/mnt/sgarbas-h48",
        remote_action="recover-prerequisite-metadata",
        execute=False,
        artifact_suffix="recover",
    )

    assert output.exists()
    assert payload["execution_provider"] == "generic_ssh_non_aws"
    assert payload["remote_action"] == "recover-prerequisite-metadata"
    assert payload["aws_command_scan"]["passed"] is True
    assert payload["runbook_validation"]["passed"] is True
    assert payload["underlying_remote_artifact"].startswith("results/processed/")
    assert payload["passed"] is False
    assert payload["fast_runtime_proven_for_every_possible_state"] is False


def test_nonaws_fasttarget_wrapper_refuses_execute_without_launchable_package(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("RUBIK_OPTIMAL_ENABLE_AWS", raising=False)
    runbook = _write_status_runbook(tmp_path)
    preflight = _write_assumed_preflight(tmp_path)
    contract = _write_h48h10_contract(tmp_path)
    package_payload, package_path = build_proof_package(
        root=tmp_path,
        runbook_manifest_path=runbook,
        assumed_preflight_path=preflight,
        proof_volume_report_path=None,
        contract_path=contract,
        host="proof-host.example",
        remote_root="/mnt/sgarbas-h48",
        artifact_suffix="planning_package",
    )
    assert package_payload["package_mode"] == "planning"
    assert package_payload["launchable_for_execution"] is False

    payload, output = run_nonaws_fasttarget_proof(
        root=tmp_path,
        runbook_manifest_path=runbook,
        host="proof-host.example",
        remote_root="/mnt/sgarbas-h48",
        remote_action="detached-staged-proof",
        prerequisite_bundle_mode="split",
        execute=True,
        artifact_suffix="refuse_planning_package",
        proof_package_path=package_path,
    )

    assert output.exists()
    assert payload["status"] == "refused_nonaws_guard"
    assert payload["execute"] is False
    assert payload["requested_execute"] is True
    assert payload["launchable_proof_package_required"] is True
    assert payload["proof_package_validation"]["passed"] is False
    assert payload["proof_package_validation"]["package_mode"] == "planning"
    assert "package_mode_launchable" in payload["proof_package_validation"]["issues"]
    assert "launchable_for_execution" in payload["proof_package_validation"]["issues"]
    assert payload["reason"] == (
        "launchable H48H10 proof package validation failed; refusing generic "
        "non-AWS proof execution"
    )
    assert "underlying_remote_artifact" not in payload
    assert payload["fast_runtime_proven_for_every_possible_state"] is False


def test_nonaws_fasttarget_wrapper_executes_dangerous_action_with_launchable_package(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("RUBIK_OPTIMAL_ENABLE_AWS", raising=False)
    runbook = _write_status_runbook(tmp_path)
    preflight = _write_live_preflight(tmp_path)
    proof_volume = _write_proof_volume_report(tmp_path, launchable=True)
    contract = _write_h48h10_contract(tmp_path)
    _package_payload, package_path = build_proof_package(
        root=tmp_path,
        runbook_manifest_path=runbook,
        assumed_preflight_path=preflight,
        proof_volume_report_path=proof_volume,
        contract_path=contract,
        host="proof-host.example",
        remote_root="/mnt/sgarbas-h48",
        artifact_suffix="launchable_package",
        require_live_preflight=True,
    )
    calls = []
    checkpoint_path = (
        tmp_path
        / "results"
        / "processed"
        / "h48_fasttarget_nonaws_run_nonaws_test_launchable_execute.json"
    )

    def fake_remote_runner(**kwargs):
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        assert checkpoint["status"] == (
            "nonaws_h48_fasttarget_pre_remote_checkpoint_not_runtime_evidence"
        )
        assert checkpoint["checkpoint_kind"] == "nonaws_pre_remote_proof"
        assert checkpoint["pre_remote_checkpoint_written"] is True
        assert checkpoint["checkpoint_written_before_remote_start"] is True
        assert checkpoint["proof_package_validation"]["passed"] is True
        assert checkpoint["aws_command_scan"]["passed"] is True
        assert checkpoint["runbook_validation"]["passed"] is True
        assert "--execute" in checkpoint["checkpoint_resume_command"]
        assert checkpoint["checkpoint_status_command"][
            checkpoint["checkpoint_status_command"].index("--remote-action") + 1
        ] == "status"
        assert "--execute" not in checkpoint["checkpoint_status_command"]
        calls.append(kwargs)
        output = tmp_path / "results" / "processed" / "fake_remote.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("{}", encoding="utf-8")
        return (
            {
                "schema_version": 1,
                "execution_provider": "remote_ssh",
                "execute": True,
                "passed": False,
                "remote_action": kwargs["remote_action"],
                "remote_host": kwargs["host"],
                "remote_root": kwargs["remote_root"],
                "fast_runtime_proven_for_every_possible_state": False,
                "notes": "fake remote runner",
            },
            output,
        )

    monkeypatch.setattr(
        "scripts.experimental.run_h48_fasttarget_nonaws_proof.run_remote_fasttarget_proof",
        fake_remote_runner,
    )

    payload, output = run_nonaws_fasttarget_proof(
        root=tmp_path,
        runbook_manifest_path=runbook,
        host="proof-host.example",
        remote_root="/mnt/sgarbas-h48",
        remote_action="detached-staged-proof",
        prerequisite_bundle_mode="split",
        execute=True,
        artifact_suffix="launchable_execute",
        proof_package_path=package_path,
    )

    assert output.exists()
    assert len(calls) == 1
    assert calls[0]["execute"] is True
    assert calls[0]["remote_action"] == "detached-staged-proof"
    assert payload["execution_provider"] == "generic_ssh_non_aws"
    assert payload["launchable_proof_package_required"] is True
    assert payload["proof_package_validation"]["passed"] is True
    assert payload["proof_package_validation"]["package_mode"] == "launchable"
    assert payload["proof_package_validation"]["package_sha256_matches_components"] is True
    assert payload["proof_package_validation"]["component_fingerprint_count"] > 10
    assert (
        payload["proof_package_validation"]["component_fingerprint_validation"]["passed"]
        is True
    )
    assert payload["proof_package_validation"]["remote_host_placeholder"] == "proof-host.example"
    assert payload["proof_package_validation"]["remote_root_placeholder"] == "/mnt/sgarbas-h48"
    assert payload["pre_remote_checkpoint_written"] is True
    assert payload["checkpoint_written_before_remote_start"] is True
    assert payload["pre_remote_checkpoint_status"] == (
        "nonaws_h48_fasttarget_pre_remote_checkpoint_not_runtime_evidence"
    )
    assert payload["pre_remote_checkpoint_path"] == (
        "results/processed/h48_fasttarget_nonaws_run_nonaws_test_launchable_execute.json"
    )
    assert payload["underlying_remote_artifact"] == "results/processed/fake_remote.json"
    assert payload["fast_runtime_proven_for_every_possible_state"] is False


def test_nonaws_fasttarget_wrapper_refuses_launchable_package_with_stale_component(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("RUBIK_OPTIMAL_ENABLE_AWS", raising=False)
    runbook = _write_status_runbook(tmp_path)
    preflight = _write_live_preflight(tmp_path)
    proof_volume = _write_proof_volume_report(tmp_path, launchable=True)
    contract = _write_h48h10_contract(tmp_path)
    _package_payload, package_path = build_proof_package(
        root=tmp_path,
        runbook_manifest_path=runbook,
        assumed_preflight_path=preflight,
        proof_volume_report_path=proof_volume,
        contract_path=contract,
        host="proof-host.example",
        remote_root="/mnt/sgarbas-h48",
        artifact_suffix="launchable_package_stale_component",
        require_live_preflight=True,
    )
    preflight.write_text(
        preflight.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )

    payload, output = run_nonaws_fasttarget_proof(
        root=tmp_path,
        runbook_manifest_path=runbook,
        host="proof-host.example",
        remote_root="/mnt/sgarbas-h48",
        remote_action="detached-staged-proof",
        prerequisite_bundle_mode="split",
        execute=True,
        artifact_suffix="refuse_stale_component",
        proof_package_path=package_path,
    )

    assert output.exists()
    assert payload["status"] == "refused_nonaws_guard"
    assert payload["execute"] is False
    assert payload["requested_execute"] is True
    assert payload["launchable_proof_package_required"] is True
    assert payload["proof_package_validation"]["passed"] is False
    assert "component_fingerprints_revalidated" in payload["proof_package_validation"]["issues"]
    component_validation = payload["proof_package_validation"][
        "component_fingerprint_validation"
    ]
    assert component_validation["passed"] is False
    assert {
        issue["code"] for issue in component_validation["issues"]
    } >= {
        "component_fingerprint_size_mismatch",
        "component_fingerprint_sha256_mismatch",
    }
    assert "underlying_remote_artifact" not in payload
    assert payload["fast_runtime_proven_for_every_possible_state"] is False


def test_nonaws_fasttarget_wrapper_refuses_launchable_package_for_wrong_host(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("RUBIK_OPTIMAL_ENABLE_AWS", raising=False)
    runbook = _write_status_runbook(tmp_path)
    preflight = _write_live_preflight(tmp_path)
    proof_volume = _write_proof_volume_report(tmp_path, launchable=True)
    contract = _write_h48h10_contract(tmp_path)
    _package_payload, package_path = build_proof_package(
        root=tmp_path,
        runbook_manifest_path=runbook,
        assumed_preflight_path=preflight,
        proof_volume_report_path=proof_volume,
        contract_path=contract,
        host="proof-host.example",
        remote_root="/mnt/sgarbas-h48",
        artifact_suffix="launchable_package_bound_host",
        require_live_preflight=True,
    )

    payload, output = run_nonaws_fasttarget_proof(
        root=tmp_path,
        runbook_manifest_path=runbook,
        host="different-proof-host.example",
        remote_root="/mnt/different-root",
        remote_action="detached-staged-proof",
        prerequisite_bundle_mode="split",
        execute=True,
        artifact_suffix="refuse_wrong_bound_host",
        proof_package_path=package_path,
    )

    assert output.exists()
    assert payload["status"] == "refused_nonaws_guard"
    assert payload["execute"] is False
    assert payload["requested_execute"] is True
    assert payload["launchable_proof_package_required"] is True
    assert payload["proof_package_validation"]["passed"] is False
    assert payload["proof_package_validation"]["remote_host_placeholder"] == "proof-host.example"
    assert payload["proof_package_validation"]["expected_remote_host"] == (
        "different-proof-host.example"
    )
    assert payload["proof_package_validation"]["remote_root_placeholder"] == "/mnt/sgarbas-h48"
    assert payload["proof_package_validation"]["expected_remote_root"] == "/mnt/different-root"
    assert "remote_host_matches" in payload["proof_package_validation"]["issues"]
    assert "remote_root_matches" in payload["proof_package_validation"]["issues"]
    assert "underlying_remote_artifact" not in payload
    assert payload["fast_runtime_proven_for_every_possible_state"] is False


def test_nonaws_fasttarget_wrapper_refuses_aws_script_before_execute(tmp_path, monkeypatch):
    monkeypatch.delenv("RUBIK_OPTIMAL_ENABLE_AWS", raising=False)
    runbook = _write_status_runbook(tmp_path)
    payload = json.loads(runbook.read_text(encoding="utf-8"))
    preflight = tmp_path / payload["generated_files"]["preflight_leader"]
    preflight.write_text("#!/usr/bin/env bash\naws sts get-caller-identity\n", encoding="utf-8")
    payload["generated_file_fingerprints"]["preflight_leader"] = _file_fingerprint(
        preflight,
        payload["generated_files"]["preflight_leader"],
    )
    runbook.write_text(json.dumps(payload), encoding="utf-8")

    payload, output = run_nonaws_fasttarget_proof(
        root=tmp_path,
        runbook_manifest_path=runbook,
        host="proof-host.example",
        remote_root="/mnt/sgarbas-h48",
        remote_action="preflight",
        execute=True,
        skip_sync=True,
        skip_fetch=True,
        artifact_suffix="guard",
    )

    assert output.exists()
    assert payload["status"] == "refused_nonaws_guard"
    assert payload["execute"] is False
    assert payload["requested_execute"] is True
    assert payload["runbook_validation"]["passed"] is True
    assert payload["aws_command_scan"]["passed"] is False
    assert payload["aws_command_scan"]["forbidden_aws_match_count"] >= 1
    assert payload["fast_runtime_proven_for_every_possible_state"] is False


def test_nonaws_fasttarget_wrapper_refuses_stale_h48h10_plan_before_execute(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("RUBIK_OPTIMAL_ENABLE_AWS", raising=False)
    runbook = _write_status_runbook(tmp_path)
    manifest = json.loads(runbook.read_text(encoding="utf-8"))
    full_plan = tmp_path / manifest["full_plan_path"]
    plan = json.loads(full_plan.read_text(encoding="utf-8"))
    stronger = plan["workloads"][0]
    stronger["command_args"] = [
        arg for arg in stronger["command_args"] if arg != "--skip-generation-distribution-scan"
    ]
    full_plan.write_text(json.dumps(plan), encoding="utf-8")

    payload, output = run_nonaws_fasttarget_proof(
        root=tmp_path,
        runbook_manifest_path=runbook,
        host="proof-host.example",
        remote_root="/mnt/sgarbas-h48",
        remote_action="status",
        execute=True,
        artifact_suffix="stale_plan",
    )

    assert output.exists()
    assert payload["status"] == "refused_nonaws_guard"
    assert payload["execute"] is False
    assert payload["requested_execute"] is True
    assert payload["aws_command_scan"]["passed"] is True
    assert payload["runbook_validation"]["passed"] is False
    assert {
        issue["code"] for issue in payload["runbook_validation"]["issues"]
    } >= {"stronger_table_missing_optimized_command_flag"}
    assert payload["fast_runtime_proven_for_every_possible_state"] is False


def test_nonaws_fasttarget_wrapper_refuses_script_fingerprint_drift_before_execute(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("RUBIK_OPTIMAL_ENABLE_AWS", raising=False)
    runbook = _write_status_runbook(tmp_path)
    manifest = json.loads(runbook.read_text(encoding="utf-8"))
    preflight = tmp_path / manifest["generated_files"]["preflight_leader"]
    preflight.write_text("#!/usr/bin/env bash\ntrue\n# drift\n", encoding="utf-8")

    payload, output = run_nonaws_fasttarget_proof(
        root=tmp_path,
        runbook_manifest_path=runbook,
        host="proof-host.example",
        remote_root="/mnt/sgarbas-h48",
        remote_action="preflight",
        execute=True,
        artifact_suffix="script_drift",
    )

    assert output.exists()
    assert payload["status"] == "refused_nonaws_guard"
    assert payload["execute"] is False
    assert payload["runbook_validation"]["passed"] is False
    assert {
        issue["code"] for issue in payload["runbook_validation"]["issues"]
    } >= {
        "generated_file_fingerprint_size_mismatch",
        "generated_file_fingerprint_sha256_mismatch",
    }

from __future__ import annotations

import json
import hashlib
from pathlib import Path

from scripts.experimental.run_h48_fasttarget_local_proof import run_local_fasttarget_proof


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
            "local_test_shared_prereq",
            "--gendata-workbatch",
            "256",
            "--mmap-sync-mode",
            "async",
            "--backend-cflag=-march=native",
            "--skip-generation-distribution-scan",
        ],
    }


def _write_plan(root: Path, *, scope: str, selected_end: int) -> Path:
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
    path = processed / f"cloud_hardtail_campaign_plan_{scope}_local_test.json"
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


def _write_runbook(root: Path, *, script_text: str = "echo preflight\\n") -> Path:
    runbook_dir = root / "results" / "local_runbook"
    runbook_dir.mkdir(parents=True)
    generated = {}
    for key in REQUIRED_RUNBOOK_SCRIPTS:
        script = runbook_dir / f"{key}.sh"
        text = script_text if key == "preflight_leader" else "echo ok\\n"
        script.write_text(f"#!/usr/bin/env bash\nset -euo pipefail\n{text}", encoding="utf-8")
        script.chmod(0o755)
        generated[key] = f"results/local_runbook/{key}.sh"
    processed = root / "results" / "processed"
    processed.mkdir(parents=True)
    canary_plan = _write_plan(root, scope="canary", selected_end=3)
    full_plan = _write_plan(root, scope="full", selected_end=25)
    runbook = processed / "cloud_hardtail_runbook_local_test.json"
    runbook.write_text(
        json.dumps(
            {
                "run_suffix": "local_test",
                "profile": "thesis",
                "seed": 2026,
                "solver": "h48h10",
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
                "single_machine_run_order": [
                    "bootstrap_cloud_machine",
                    "preflight_leader",
                    "run_full_prerequisites",
                    "preflight_worker",
                    "validate_prerequisite_tables",
                    "run_canary_after_prerequisites",
                    "run_full",
                    "evaluate_full",
                    "collect_results",
                    "finalize_full_after_collect",
                ],
            }
        ),
        encoding="utf-8",
    )
    return runbook


def _write_passing_contract(root: Path) -> Path:
    path = root / "results" / "processed" / "h48_oracle_contract_seed_2026_thesis_h48h10.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "passed": True,
                "fast_runtime_proven_for_every_possible_state": True,
                "all_state_exact_contract_supported": True,
                "empirical_fast_corpus_supported": True,
                "cloud_runtime_proof": {
                    "passed": True,
                    "missing_or_failed_workload_count": 0,
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def _write_proof_package(root: Path, runbook: Path, *, launchable: bool = True) -> Path:
    path = (
        root
        / "results"
        / "processed"
        / "h48_fasttarget_nonaws_proof_package_seed_2026_thesis_h48h10_test.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    runbook_relative = str(runbook.relative_to(root))
    path.write_text(
        json.dumps(
            {
                "artifact_kind": "h48_fasttarget_nonaws_proof_package",
                "execution_provider": "generic_ssh_non_aws",
                "aws_usage_allowed": False,
                "profile": "thesis",
                "seed": 2026,
                "solver": "h48h10",
                "runbook_manifest_path": runbook_relative,
                "passed": launchable,
                "package_mode": "launchable" if launchable else "planning",
                "readiness_classification": (
                    "launchable_nonaws_proof_package" if launchable else "planning_nonaws_proof_package"
                ),
                "live_preflight_required": launchable,
                "proof_volume_report_required": launchable,
                "launchable_for_execution": launchable,
                "preflight_is_live_runtime_evidence": launchable,
                "proof_volume_report_launchable": launchable,
                "checks": {
                    "preflight_requirement_satisfied": launchable,
                    "proof_volume_requirement_satisfied": launchable,
                },
                "aws_command_scan": {"passed": True},
                "runbook_validation": {"passed": True},
                "full_plan_summary": {"required_workload_count": 8},
                "fast_runtime_proven_for_every_possible_state": False,
                "package_sha256": "test-package-sha256",
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


def test_local_fasttarget_runner_writes_nonaws_dry_run(tmp_path, monkeypatch):
    monkeypatch.delenv("RUBIK_OPTIMAL_ENABLE_AWS", raising=False)
    runbook = _write_runbook(tmp_path)

    payload, output = run_local_fasttarget_proof(
        root=tmp_path,
        runbook_manifest_path=runbook,
        action="preflight",
        execute=False,
        artifact_suffix="dryrun",
        timeout_seconds=None,
    )

    assert output.exists()
    assert payload["passed"] is True
    assert payload["execute"] is False
    assert payload["execution_provider"] == "local_non_aws"
    assert payload["aws_usage_allowed"] is False
    assert payload["aws_command_scan"]["passed"] is True
    assert payload["runbook_validation"]["passed"] is True
    assert payload["runbook_validation"]["generated_file_fingerprint_count"] == len(
        REQUIRED_RUNBOOK_SCRIPTS
    )
    assert payload["status"] == "local_nonaws_dryrun_planned"
    assert "results/local_runbook/preflight_leader.sh" in payload["command"]


def test_local_fasttarget_runner_plans_staged_single_machine_sequence(tmp_path, monkeypatch):
    monkeypatch.delenv("RUBIK_OPTIMAL_ENABLE_AWS", raising=False)
    runbook = _write_runbook(tmp_path)

    payload, output = run_local_fasttarget_proof(
        root=tmp_path,
        runbook_manifest_path=runbook,
        action="staged-proof",
        execute=False,
        artifact_suffix="staged_dryrun",
        timeout_seconds=None,
    )

    assert output.exists()
    assert payload["passed"] is True
    assert payload["execute"] is False
    assert payload["sequence_order_key"] == "single_machine_run_order"
    assert payload["planned_steps"][0]["runbook_key"] == "bootstrap_cloud_machine"
    assert payload["planned_steps"][-1]["runbook_key"] == "finalize_full_after_collect"
    assert payload["sequence_summary"] is not None
    assert payload["sequence_summary"]["planned_step_count"] == 10
    assert "bootstrap_cloud_machine.sh" in payload["command"]
    assert "finalize_full_after_collect.sh" in payload["command"]
    assert payload["aws_command_scan"]["passed"] is True
    assert payload["runbook_validation"]["passed"] is True
    assert payload["launchable_proof_package_required"] is False
    assert payload["proof_package_validation"]["passed"] is True


def test_local_fasttarget_runner_refuses_staged_execute_without_launchable_package(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("RUBIK_OPTIMAL_ENABLE_AWS", raising=False)
    marker = tmp_path / "bootstrap_should_not_run"
    runbook = _write_runbook(tmp_path)
    manifest = json.loads(runbook.read_text(encoding="utf-8"))
    bootstrap = tmp_path / manifest["generated_files"]["bootstrap_cloud_machine"]
    bootstrap.write_text(
        bootstrap.read_text(encoding="utf-8") + f"\ntouch {marker}\n",
        encoding="utf-8",
    )
    manifest["generated_file_fingerprints"]["bootstrap_cloud_machine"] = _file_fingerprint(
        bootstrap,
        manifest["generated_files"]["bootstrap_cloud_machine"],
    )
    runbook.write_text(json.dumps(manifest), encoding="utf-8")
    proof_package = _write_proof_package(tmp_path, runbook, launchable=False)

    payload, _output = run_local_fasttarget_proof(
        root=tmp_path,
        runbook_manifest_path=runbook,
        action="staged-proof",
        execute=True,
        artifact_suffix="staged_missing_launchable_package",
        timeout_seconds=5.0,
        proof_package_path=proof_package,
    )

    assert payload["passed"] is False
    assert payload["status"] == "refused_local_nonaws_guard"
    assert payload["launchable_proof_package_required"] is True
    assert payload["proof_package_validation"]["passed"] is False
    assert "package_mode_launchable" in payload["proof_package_validation"]["issues"]
    assert "launchable_for_execution" in payload["proof_package_validation"]["issues"]
    assert (
        "launchable H48H10 proof package validation failed; refusing staged proof execution"
        in payload["errors"]
    )
    assert payload["command_result"] is None
    assert payload["step_results"] == []
    assert marker.exists() is False


def test_local_fasttarget_runner_staged_execute_stops_at_failed_gate(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("RUBIK_OPTIMAL_ENABLE_AWS", raising=False)
    marker = tmp_path / "after_preflight_should_not_run"
    script_text = "echo preflight failed >&2\nexit 7\n"
    runbook = _write_runbook(tmp_path, script_text=script_text)
    manifest = json.loads(runbook.read_text(encoding="utf-8"))
    after_preflight = tmp_path / manifest["generated_files"]["run_full_prerequisites"]
    after_preflight.write_text(
        after_preflight.read_text(encoding="utf-8") + f"\ntouch {marker}\n",
        encoding="utf-8",
    )
    manifest["generated_file_fingerprints"]["run_full_prerequisites"] = _file_fingerprint(
        after_preflight,
        manifest["generated_files"]["run_full_prerequisites"],
    )
    runbook.write_text(json.dumps(manifest), encoding="utf-8")
    proof_package = _write_proof_package(tmp_path, runbook)

    payload, _output = run_local_fasttarget_proof(
        root=tmp_path,
        runbook_manifest_path=runbook,
        action="staged-proof",
        execute=True,
        artifact_suffix="staged_failed_gate",
        timeout_seconds=5.0,
        proof_package_path=proof_package,
    )

    assert payload["passed"] is False
    assert payload["status"] == "local_nonaws_staged_proof_failed"
    assert [result["runbook_key"] for result in payload["step_results"]] == [
        "bootstrap_cloud_machine",
        "preflight_leader",
    ]
    assert payload["command_result"]["return_code"] == 7
    assert payload["sequence_summary"]["failed_runbook_key"] == "preflight_leader"
    assert payload["sequence_summary"]["stopped_before_runbook_key"] == "run_full_prerequisites"
    assert marker.exists() is False
    assert payload["final_contract_required_for_pass"] is True


def test_local_fasttarget_runner_staged_execute_requires_final_contract(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("RUBIK_OPTIMAL_ENABLE_AWS", raising=False)
    runbook = _write_runbook(tmp_path)
    proof_package = _write_proof_package(tmp_path, runbook)

    payload, _output = run_local_fasttarget_proof(
        root=tmp_path,
        runbook_manifest_path=runbook,
        action="staged-proof",
        execute=True,
        artifact_suffix="staged_missing_contract",
        timeout_seconds=5.0,
        proof_package_path=proof_package,
    )

    assert payload["passed"] is False
    assert payload["status"] == "local_nonaws_staged_proof_failed_final_contract"
    assert payload["sequence_summary"]["all_steps_completed"] is True
    assert payload["final_contract_required_for_pass"] is True
    assert payload["final_contract_proof_passed"] is False


def test_local_fasttarget_runner_staged_execute_passes_with_final_contract(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("RUBIK_OPTIMAL_ENABLE_AWS", raising=False)
    runbook = _write_runbook(tmp_path)
    proof_package = _write_proof_package(tmp_path, runbook)
    _write_passing_contract(tmp_path)

    payload, _output = run_local_fasttarget_proof(
        root=tmp_path,
        runbook_manifest_path=runbook,
        action="staged-proof",
        execute=True,
        artifact_suffix="staged_passing_contract",
        timeout_seconds=5.0,
        proof_package_path=proof_package,
    )

    assert payload["passed"] is True
    assert payload["status"] == "local_nonaws_staged_proof_commands_passed"
    assert payload["sequence_summary"]["all_steps_completed"] is True
    assert payload["final_contract_required_for_pass"] is True
    assert payload["final_contract_proof_passed"] is True
    assert payload["fast_runtime_proven_for_every_possible_state"] is True


def test_local_fasttarget_runner_refuses_execute_when_aws_unlock_is_set(tmp_path, monkeypatch):
    monkeypatch.setenv("RUBIK_OPTIMAL_ENABLE_AWS", "1")
    runbook = _write_runbook(tmp_path)

    payload, _output = run_local_fasttarget_proof(
        root=tmp_path,
        runbook_manifest_path=runbook,
        action="preflight",
        execute=True,
        artifact_suffix="aws_env",
        timeout_seconds=1.0,
    )

    assert payload["passed"] is False
    assert payload["status"] == "refused_local_nonaws_guard"
    assert payload["command_result"] is None
    assert payload["runbook_validation"]["passed"] is True
    assert any("RUBIK_OPTIMAL_ENABLE_AWS=1 is active" in error for error in payload["errors"])


def test_local_fasttarget_runner_refuses_script_with_aws_command(tmp_path, monkeypatch):
    monkeypatch.delenv("RUBIK_OPTIMAL_ENABLE_AWS", raising=False)
    runbook = _write_runbook(tmp_path, script_text="aws sts get-caller-identity\\n")

    payload, _output = run_local_fasttarget_proof(
        root=tmp_path,
        runbook_manifest_path=runbook,
        action="preflight",
        execute=True,
        artifact_suffix="aws_script",
        timeout_seconds=1.0,
    )

    assert payload["passed"] is False
    assert payload["status"] == "refused_local_nonaws_guard"
    assert payload["runbook_validation"]["passed"] is True
    assert payload["aws_command_scan"]["passed"] is False
    assert "planned local proof script references AWS helpers or AWS CLI commands" in payload["errors"]


def test_local_fasttarget_runner_summarizes_executed_preflight_artifact(tmp_path, monkeypatch):
    monkeypatch.delenv("RUBIK_OPTIMAL_ENABLE_AWS", raising=False)
    artifact = tmp_path / "results" / "processed" / "cloud_hardtail_preflight_test.json"
    script_text = f"""python - <<'PY'
import json
from pathlib import Path

path = Path({str(artifact)!r})
path.parent.mkdir(parents=True, exist_ok=True)
payload = {{
    "profile": "thesis",
    "seed": 2026,
    "solver": "h48h10",
    "passed": False,
    "fast_runtime_proven_for_every_possible_state": False,
    "reasons": ["cpu_count 8 is below required 16"],
    "machine": {{
        "cpu_count": 8,
        "memory_gib": 16.0,
        "data_generated_h48_total_gib": 460.0,
        "data_generated_h48_free_gib": 38.0,
    }},
    "target_h48_workspace": {{
        "target_table_size_gib": 28.257,
        "required_workspace_gib": 32.491,
        "available_workspace_gib": 38.0,
        "workspace_headroom_gib": 5.509,
        "satisfies_workspace": True,
    }},
    "require_target_table": False,
    "target_table_validation": None,
}}
path.write_text(json.dumps(payload), encoding="utf-8")
print(json.dumps({{"output": str(path), "passed": False}}))
raise SystemExit(1)
PY
"""
    runbook = _write_runbook(tmp_path, script_text=script_text)

    payload, _output = run_local_fasttarget_proof(
        root=tmp_path,
        runbook_manifest_path=runbook,
        action="preflight",
        execute=True,
        artifact_suffix="preflight_summary",
        timeout_seconds=5.0,
    )

    summary = payload["action_artifact_summary"]
    assert payload["passed"] is False
    assert payload["status"] == "local_nonaws_action_failed"
    assert summary["exists"] is True
    assert summary["path"] == "results/processed/cloud_hardtail_preflight_test.json"
    assert summary["machine"]["cpu_count"] == 8
    assert summary["machine"]["memory_gib"] == 16.0
    assert summary["target_h48_workspace"]["satisfies_workspace"] is True
    assert summary["reasons"] == ["cpu_count 8 is below required 16"]


def test_local_fasttarget_runner_refuses_stale_runbook_before_execute(tmp_path, monkeypatch):
    monkeypatch.delenv("RUBIK_OPTIMAL_ENABLE_AWS", raising=False)
    marker = tmp_path / "script_ran"
    runbook = _write_runbook(tmp_path, script_text=f"touch {marker}\\n")
    manifest = json.loads(runbook.read_text(encoding="utf-8"))
    full_plan = tmp_path / manifest["full_plan_path"]
    plan = json.loads(full_plan.read_text(encoding="utf-8"))
    stronger = plan["workloads"][0]
    stronger["command_args"] = [
        arg for arg in stronger["command_args"] if arg != "--skip-generation-distribution-scan"
    ]
    full_plan.write_text(json.dumps(plan), encoding="utf-8")

    payload, _output = run_local_fasttarget_proof(
        root=tmp_path,
        runbook_manifest_path=runbook,
        action="preflight",
        execute=True,
        artifact_suffix="stale_runbook",
        timeout_seconds=5.0,
    )

    assert payload["passed"] is False
    assert payload["status"] == "refused_local_nonaws_guard"
    assert payload["command_result"] is None
    assert marker.exists() is False
    assert payload["runbook_validation"]["passed"] is False
    assert any(
        issue["code"] == "stronger_table_missing_optimized_command_flag"
        for issue in payload["runbook_validation"]["issues"]
    )
    assert (
        "runbook manifest/plan validation failed for the local non-AWS H48H10 proof package"
        in payload["errors"]
    )


def test_local_fasttarget_runner_refuses_script_fingerprint_drift_before_execute(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("RUBIK_OPTIMAL_ENABLE_AWS", raising=False)
    marker = tmp_path / "script_ran"
    runbook = _write_runbook(tmp_path, script_text=f"touch {marker}\\n")
    manifest = json.loads(runbook.read_text(encoding="utf-8"))
    preflight = tmp_path / manifest["generated_files"]["preflight_leader"]
    preflight.write_text(preflight.read_text(encoding="utf-8") + "\n# drift\n", encoding="utf-8")

    payload, _output = run_local_fasttarget_proof(
        root=tmp_path,
        runbook_manifest_path=runbook,
        action="preflight",
        execute=True,
        artifact_suffix="script_drift",
        timeout_seconds=5.0,
    )

    assert payload["passed"] is False
    assert payload["status"] == "refused_local_nonaws_guard"
    assert payload["command_result"] is None
    assert marker.exists() is False
    assert payload["runbook_validation"]["passed"] is False
    assert any(
        issue["code"] == "generated_file_fingerprint_sha256_mismatch"
        for issue in payload["runbook_validation"]["issues"]
    )

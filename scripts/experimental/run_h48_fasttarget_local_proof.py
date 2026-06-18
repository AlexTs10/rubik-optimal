#!/usr/bin/env python
"""Run or dry-run the H48 fast-target proof on the current non-AWS machine."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rubik_optimal.results import write_json  # noqa: E402
from rubik_optimal.runtime import run_process_tree  # noqa: E402
from scripts.experimental.run_h48_fasttarget_nonaws_proof import (  # noqa: E402
    AWS_UNLOCK_ENV,
    AWS_UNLOCK_VALUE,
    _validate_nonaws_runbook_manifest,
    scan_planned_steps_for_aws,
)


EXECUTION_PROVIDER = "local_non_aws"
DEFAULT_RUNBOOK = Path(
    "results/processed/cloud_hardtail_runbook_cloud_20260601_h48h10_fasttarget_batch10.json"
)
DEFAULT_PROOF_PACKAGE = Path(
    "results/processed/"
    "h48_fasttarget_nonaws_proof_package_seed_2026_thesis_h48h10_nonaws_splitbundle_validated.json"
)
ACTION_TO_RUNBOOK_FILE = {
    "preflight": "preflight_leader",
    "prerequisites": "run_full_prerequisites",
    "worker-preflight": "preflight_worker",
    "validate-table": "validate_prerequisite_tables",
    "recover-prerequisite-metadata": "recover_prerequisite_metadata",
    "canary-after-prerequisites": "run_canary_after_prerequisites",
    "full": "run_full",
    "evaluate": "evaluate_full",
    "collect": "collect_results",
    "finalize": "finalize_full_after_collect",
    "end-to-end": "run_end_to_end_single_machine",
}
SEQUENCE_ACTION_TO_RUNBOOK_ORDER = {
    "staged-proof": "single_machine_run_order",
}
ACTION_CHOICES = sorted(set(ACTION_TO_RUNBOOK_FILE) | set(SEQUENCE_ACTION_TO_RUNBOOK_ORDER))


def _safe_id(value: str) -> str:
    return "".join(char if char.isalnum() or char in "._-" else "_" for char in value)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _relative(root: Path, path: Path) -> str:
    return str(path.relative_to(root)) if path.is_relative_to(root) else str(path)


def _output_path(root: Path, run_suffix: str, suffix: str) -> Path:
    suffix_part = f"_{_safe_id(suffix)}" if suffix else ""
    return (
        root
        / "results"
        / "processed"
        / f"h48_fasttarget_local_run_{_safe_id(run_suffix)}{suffix_part}.json"
    )


def _contract_summary(root: Path, *, profile: str, seed: int, solver: str) -> dict[str, Any] | None:
    path = root / "results" / "processed" / f"h48_oracle_contract_seed_{seed}_{profile}_{solver}.json"
    if not path.exists():
        return None
    payload = _load_json(path)
    cloud_proof = payload.get("cloud_runtime_proof") or {}
    return {
        "path": _relative(root, path),
        "passed": payload.get("passed") is True,
        "fast_runtime_proven_for_every_possible_state": (
            payload.get("fast_runtime_proven_for_every_possible_state") is True
        ),
        "all_state_exact_contract_supported": payload.get("all_state_exact_contract_supported") is True,
        "empirical_fast_corpus_supported": payload.get("empirical_fast_corpus_supported") is True,
        "cloud_runtime_proof_passed": cloud_proof.get("passed") is True,
        "missing_or_failed_workload_count": cloud_proof.get("missing_or_failed_workload_count"),
    }


def _proof_package_validation(
    root: Path,
    *,
    proof_package_path: Path,
    runbook_manifest_path: Path,
    profile: str,
    seed: int,
    solver: str,
    required: bool,
) -> dict[str, Any]:
    path = proof_package_path if proof_package_path.is_absolute() else root / proof_package_path
    summary: dict[str, Any] = {
        "required": required,
        "path": _relative(root, path),
        "exists": path.exists(),
        "passed": False,
        "issues": [],
    }
    if not required:
        summary["passed"] = True
        return summary
    if not path.exists():
        summary["issues"].append("launchable proof package is missing")
        return summary
    payload = _load_json(path)
    runbook_relative = _relative(root, runbook_manifest_path)
    package_checks = payload.get("checks") or {}
    checks = {
        "artifact_kind": payload.get("artifact_kind") == "h48_fasttarget_nonaws_proof_package",
        "package_passed": payload.get("passed") is True,
        "package_mode_launchable": payload.get("package_mode") == "launchable",
        "readiness_classification_launchable": (
            payload.get("readiness_classification") == "launchable_nonaws_proof_package"
        ),
        "launchable_for_execution": payload.get("launchable_for_execution") is True,
        "live_preflight_required": payload.get("live_preflight_required") is True,
        "preflight_is_live_runtime_evidence": (
            payload.get("preflight_is_live_runtime_evidence") is True
        ),
        "preflight_requirement_satisfied": (
            package_checks.get("preflight_requirement_satisfied") is True
        ),
        "proof_volume_report_required": payload.get("proof_volume_report_required") is True,
        "proof_volume_report_launchable": payload.get("proof_volume_report_launchable") is True,
        "proof_volume_requirement_satisfied": (
            package_checks.get("proof_volume_requirement_satisfied") is True
        ),
        "execution_provider_nonaws": payload.get("execution_provider") == "generic_ssh_non_aws",
        "aws_usage_disallowed": payload.get("aws_usage_allowed") is False,
        "aws_scan_passed": (payload.get("aws_command_scan") or {}).get("passed") is True,
        "runbook_validation_passed": (payload.get("runbook_validation") or {}).get("passed") is True,
        "runbook_matches": payload.get("runbook_manifest_path") == runbook_relative,
        "solver_matches": payload.get("solver") == solver,
        "profile_matches": payload.get("profile") == profile,
        "seed_matches": payload.get("seed") == seed,
        "full_plan_has_eight_required_workloads": (
            (payload.get("full_plan_summary") or {}).get("required_workload_count") == 8
        ),
        "package_is_not_runtime_proof": (
            payload.get("fast_runtime_proven_for_every_possible_state") is False
        ),
    }
    issues = [name for name, passed in checks.items() if not passed]
    summary.update(
        {
            "artifact_kind": payload.get("artifact_kind"),
            "package_mode": payload.get("package_mode"),
            "readiness_classification": payload.get("readiness_classification"),
            "launchable_for_execution": payload.get("launchable_for_execution") is True,
            "live_preflight_required": payload.get("live_preflight_required") is True,
            "preflight_is_live_runtime_evidence": (
                payload.get("preflight_is_live_runtime_evidence") is True
            ),
            "preflight_requirement_satisfied": (
                package_checks.get("preflight_requirement_satisfied") is True
            ),
            "proof_volume_report_required": payload.get("proof_volume_report_required") is True,
            "proof_volume_report_launchable": payload.get("proof_volume_report_launchable") is True,
            "proof_volume_requirement_satisfied": (
                package_checks.get("proof_volume_requirement_satisfied") is True
            ),
            "package_sha256": payload.get("package_sha256"),
            "runbook_manifest_path": payload.get("runbook_manifest_path"),
            "expected_runbook_manifest_path": runbook_relative,
            "full_required_workload_count": (
                (payload.get("full_plan_summary") or {}).get("required_workload_count")
            ),
            "checks": checks,
            "issues": issues,
            "passed": not issues,
        }
    )
    return summary


def _json_objects_from_text(text: str) -> list[dict[str, Any]]:
    decoder = json.JSONDecoder()
    objects: list[dict[str, Any]] = []
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            objects.append(value)
    return objects


def _action_artifact_path_from_output(root: Path, text: str) -> Path | None:
    for value in reversed(_json_objects_from_text(text)):
        output = value.get("output")
        if not isinstance(output, str) or not output:
            continue
        path = Path(output)
        return path if path.is_absolute() else root / path
    return None


def _summarize_action_artifact(root: Path, path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return {
            "path": _relative(root, path),
            "exists": False,
        }
    payload = _load_json(path)
    machine = payload.get("machine") or {}
    workspace = payload.get("target_h48_workspace") or {}
    return {
        "path": _relative(root, path),
        "exists": True,
        "profile": payload.get("profile"),
        "seed": payload.get("seed"),
        "solver": payload.get("solver"),
        "passed": payload.get("passed") is True,
        "fast_runtime_proven_for_every_possible_state": (
            payload.get("fast_runtime_proven_for_every_possible_state") is True
        ),
        "reasons": payload.get("reasons") or [],
        "machine": {
            "cpu_count": machine.get("cpu_count"),
            "memory_gib": machine.get("memory_gib"),
            "data_generated_h48_total_gib": machine.get("data_generated_h48_total_gib"),
            "data_generated_h48_free_gib": machine.get("data_generated_h48_free_gib"),
        },
        "target_h48_workspace": {
            "target_table_size_gib": workspace.get("target_table_size_gib"),
            "required_workspace_gib": workspace.get("required_workspace_gib"),
            "available_workspace_gib": workspace.get("available_workspace_gib"),
            "workspace_headroom_gib": workspace.get("workspace_headroom_gib"),
            "satisfies_workspace": workspace.get("satisfies_workspace"),
        },
        "require_target_table": payload.get("require_target_table"),
        "target_table_validation": payload.get("target_table_validation"),
    }


def _planned_step_for_key(
    root: Path,
    manifest: dict[str, Any],
    *,
    key: str,
    action_id: str | None = None,
) -> dict[str, Any]:
    generated = manifest.get("generated_files") or {}
    relative_script = generated.get(key)
    if not relative_script:
        raise RuntimeError(f"runbook does not expose generated file {key!r}")
    script = root / str(relative_script)
    if not script.exists():
        raise RuntimeError(f"generated runbook script is missing: {script}")
    return {
        "id": action_id or key,
        "runbook_key": key,
        "script": _relative(root, script),
        "command": ["bash", _relative(root, script)],
    }


def _planned_step(root: Path, manifest: dict[str, Any], *, action: str) -> dict[str, Any]:
    return _planned_step_for_key(
        root,
        manifest,
        key=ACTION_TO_RUNBOOK_FILE[action],
        action_id=action,
    )


def _planned_sequence(root: Path, manifest: dict[str, Any], *, action: str) -> list[dict[str, Any]]:
    order_key = SEQUENCE_ACTION_TO_RUNBOOK_ORDER[action]
    order = manifest.get(order_key)
    if not isinstance(order, list) or not order:
        raise RuntimeError(f"runbook does not expose a non-empty {order_key!r}")
    steps = [
        _planned_step_for_key(root, manifest, key=str(key))
        for key in order
    ]
    if "finalize_full_after_collect" not in [step["runbook_key"] for step in steps]:
        raise RuntimeError(f"{order_key!r} does not include finalize_full_after_collect")
    return steps


def _shell_join_steps(steps: list[dict[str, Any]]) -> str:
    return " && ".join(shlex.join([str(part) for part in step["command"]]) for step in steps)


def _command_result_payload(
    *,
    command: list[str],
    completed: Any,
    step: dict[str, Any] | None = None,
    step_index: int | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "command": shlex.join(command),
        "return_code": completed.return_code,
        "timed_out": completed.timed_out,
        "terminated_process_group": completed.terminated_process_group,
        "runtime_seconds": completed.runtime_seconds,
        "stdout_tail": "\n".join(completed.stdout.splitlines()[-80:]),
        "stderr_tail": "\n".join(completed.stderr.splitlines()[-80:]),
    }
    if step is not None:
        payload.update(
            {
                "step_index": step_index,
                "step_id": step.get("id"),
                "runbook_key": step.get("runbook_key"),
                "script": step.get("script"),
            }
        )
    return payload


def _sequence_summary(
    *,
    steps: list[dict[str, Any]],
    step_results: list[dict[str, Any]],
) -> dict[str, Any]:
    failed_result = next(
        (
            result
            for result in step_results
            if result.get("return_code") != 0 or result.get("timed_out") is True
        ),
        None,
    )
    stopped_before_step = None
    if failed_result is not None and len(step_results) < len(steps):
        stopped_before_step = steps[len(step_results)]
    return {
        "planned_step_count": len(steps),
        "executed_step_count": len(step_results),
        "all_steps_completed": len(step_results) == len(steps),
        "failed_step_id": failed_result.get("step_id") if failed_result else None,
        "failed_runbook_key": failed_result.get("runbook_key") if failed_result else None,
        "stopped_before_step_id": stopped_before_step.get("id") if stopped_before_step else None,
        "stopped_before_runbook_key": (
            stopped_before_step.get("runbook_key") if stopped_before_step else None
        ),
    }


def run_local_fasttarget_proof(
    *,
    root: Path,
    runbook_manifest_path: Path,
    action: str,
    execute: bool,
    artifact_suffix: str,
    timeout_seconds: float | None,
    proof_package_path: Path | None = None,
) -> tuple[dict[str, Any], Path]:
    manifest_path = (
        runbook_manifest_path if runbook_manifest_path.is_absolute() else root / runbook_manifest_path
    )
    manifest = _load_json(manifest_path)
    run_suffix = str(manifest.get("run_suffix") or manifest_path.stem)
    profile = str(manifest.get("profile") or "thesis")
    seed = int(manifest.get("seed") or 2026)
    solver = str(manifest.get("solver") or "h48h10")
    sequence_order_key = SEQUENCE_ACTION_TO_RUNBOOK_ORDER.get(action)
    launchable_proof_package_required = bool(execute and sequence_order_key)
    proof_package_validation = _proof_package_validation(
        root=root,
        proof_package_path=proof_package_path or DEFAULT_PROOF_PACKAGE,
        runbook_manifest_path=manifest_path,
        profile=profile,
        seed=seed,
        solver=solver,
        required=launchable_proof_package_required,
    )
    runbook_validation = _validate_nonaws_runbook_manifest(
        root=root,
        runbook_manifest_path=manifest_path,
    )
    if sequence_order_key:
        planned_steps = _planned_sequence(root, manifest, action=action)
    else:
        planned_steps = [_planned_step(root, manifest, action=action)]
    step = planned_steps[0]
    output = _output_path(root, run_suffix, artifact_suffix or action)

    scan = scan_planned_steps_for_aws(root=root, steps=planned_steps)
    env_has_aws_unlock = os.environ.get(AWS_UNLOCK_ENV) == AWS_UNLOCK_VALUE
    errors: list[str] = []
    if execute and runbook_validation.get("passed") is not True:
        errors.append("runbook manifest/plan validation failed for the local non-AWS H48H10 proof package")
    if manifest.get("aws_required") is True:
        errors.append("runbook declares aws_required=true")
    if execute and env_has_aws_unlock:
        errors.append(f"{AWS_UNLOCK_ENV}=1 is active; local non-AWS proof refuses execution")
    if not scan.get("passed"):
        errors.append("planned local proof script references AWS helpers or AWS CLI commands")
    if launchable_proof_package_required and proof_package_validation.get("passed") is not True:
        errors.append(
            "launchable H48H10 proof package validation failed; refusing staged proof execution"
        )

    command = [str(part) for part in step["command"]]
    command_text = _shell_join_steps(planned_steps) if sequence_order_key else shlex.join(command)
    command_result: dict[str, Any] | None = None
    step_results: list[dict[str, Any]] = []
    action_artifact_summaries: list[dict[str, Any]] = []
    status = "local_nonaws_dryrun_planned"
    if execute and not errors:
        for index, planned in enumerate(planned_steps):
            planned_command = [str(part) for part in planned["command"]]
            completed = run_process_tree(
                planned_command,
                cwd=root,
                timeout_seconds=timeout_seconds,
            )
            result = _command_result_payload(
                command=planned_command,
                completed=completed,
                step=planned,
                step_index=index,
            )
            step_results.append(result)
            command_result = result
            action_artifact_path = _action_artifact_path_from_output(root, completed.stdout)
            if action_artifact_path is not None:
                summary = _summarize_action_artifact(root, action_artifact_path)
                if summary is not None:
                    summary["step_id"] = planned.get("id")
                    summary["runbook_key"] = planned.get("runbook_key")
                    action_artifact_summaries.append(summary)
            if completed.return_code != 0 or completed.timed_out:
                break
        execution_succeeded_now = bool(
            step_results
            and len(step_results) == len(planned_steps)
            and all(
                result["return_code"] == 0 and result["timed_out"] is not True
                for result in step_results
            )
        )
        if sequence_order_key:
            status = (
                "local_nonaws_staged_proof_commands_passed"
                if execution_succeeded_now
                else "local_nonaws_staged_proof_failed"
            )
        else:
            status = (
                "local_nonaws_action_passed"
                if execution_succeeded_now
                else "local_nonaws_action_failed"
            )
    elif errors:
        status = "refused_local_nonaws_guard"

    action_artifact_summary: dict[str, Any] | None = (
        action_artifact_summaries[-1] if action_artifact_summaries else None
    )

    final_contract = _contract_summary(root, profile=profile, seed=seed, solver=solver)
    sequence_summary = (
        _sequence_summary(steps=planned_steps, step_results=step_results)
        if sequence_order_key
        else None
    )
    execution_succeeded = bool(
        execute
        and step_results
        and len(step_results) == len(planned_steps)
        and all(
            result["return_code"] == 0 and result["timed_out"] is not True
            for result in step_results
        )
    )
    final_action = action in {"finalize", "end-to-end"} or (
        sequence_order_key is not None
        and any(step.get("runbook_key") == "finalize_full_after_collect" for step in planned_steps)
    )
    final_contract_proof_passed = bool(
        final_contract
        and final_contract["passed"]
        and final_contract["fast_runtime_proven_for_every_possible_state"]
        and final_contract["cloud_runtime_proof_passed"]
    )
    passed = (
        not errors
        and (
            (not execute)
            or (
                execution_succeeded
                and (final_contract_proof_passed if final_action else True)
            )
        )
    )
    if execute and sequence_order_key and execution_succeeded and not final_contract_proof_passed:
        status = "local_nonaws_staged_proof_failed_final_contract"
    elif execute and not sequence_order_key and final_action and execution_succeeded and not final_contract_proof_passed:
        status = "local_nonaws_action_failed_final_contract"

    payload: dict[str, Any] = {
        "schema_version": 1,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "execution_provider": EXECUTION_PROVIDER,
        "runbook_manifest_path": _relative(root, manifest_path),
        "run_suffix": run_suffix,
        "profile": profile,
        "seed": seed,
        "solver": solver,
        "action": action,
        "sequence_order_key": sequence_order_key,
        "execute": execute,
        "launchable_proof_package_required": launchable_proof_package_required,
        "proof_package_validation": proof_package_validation,
        "timeout_seconds": timeout_seconds,
        "planned_step": step,
        "planned_steps": planned_steps,
        "command": command_text,
        "aws_usage_allowed": False,
        "aws_unlock_env": AWS_UNLOCK_ENV,
        "aws_unlock_env_present": env_has_aws_unlock,
        "aws_command_scan": scan,
        "runbook_validation": runbook_validation,
        "errors": errors,
        "command_result": command_result,
        "step_results": step_results,
        "sequence_summary": sequence_summary,
        "action_artifact_summary": action_artifact_summary,
        "action_artifact_summaries": action_artifact_summaries,
        "final_contract": final_contract,
        "final_contract_required_for_pass": final_action and execute,
        "final_contract_proof_passed": final_contract_proof_passed,
        "status": status,
        "passed": passed,
        "fast_runtime_proven_for_every_possible_state": final_contract_proof_passed,
        "notes": (
            "Local non-AWS proof-host entrypoint. Dry-run is only a plan; execute mode runs the "
            "generated runbook script on the current machine after an AWS-command scan and records "
            "the final H48 contract state."
        ),
    }
    write_json(output, payload)
    return payload, output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runbook", type=Path, default=DEFAULT_RUNBOOK)
    parser.add_argument("--action", choices=ACTION_CHOICES, default="preflight")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--timeout", type=float, default=None)
    parser.add_argument("--artifact-suffix", default="local_nonaws")
    parser.add_argument("--proof-package", type=Path, default=DEFAULT_PROOF_PACKAGE)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()

    payload, output = run_local_fasttarget_proof(
        root=args.root,
        runbook_manifest_path=args.runbook,
        action=args.action,
        execute=args.execute,
        artifact_suffix=args.artifact_suffix,
        timeout_seconds=args.timeout,
        proof_package_path=args.proof_package,
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "passed": payload["passed"],
                "status": payload["status"],
                "execute": payload["execute"],
            },
            indent=2,
        )
    )
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

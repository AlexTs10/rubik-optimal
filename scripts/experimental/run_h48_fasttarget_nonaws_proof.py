#!/usr/bin/env python
"""Run or dry-run the H48 fast-target proof on a generic non-AWS SSH host."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rubik_optimal.results import write_json  # noqa: E402
from scripts.experimental.run_h48_fasttarget_remote import (  # noqa: E402
    PREREQUISITE_BUNDLE_MODE_CHOICES,
    REMOTE_ACTION_CHOICES,
    build_remote_proof_steps,
    run_remote_fasttarget_proof,
)


AWS_UNLOCK_ENV = "RUBIK_OPTIMAL_ENABLE_AWS"
AWS_UNLOCK_VALUE = "1"
EXECUTION_PROVIDER = "generic_ssh_non_aws"
DEFAULT_PROOF_PACKAGE = Path(
    "results/processed/"
    "h48_fasttarget_nonaws_proof_package_seed_2026_thesis_h48h10_nonaws_splitbundle_validated.json"
)
FORBIDDEN_SCRIPT_NAMES = {
    "prepare_h48_fasttarget_aws_security_group.py",
    "provision_h48_fasttarget_aws.py",
    "run_h48_fasttarget_aws_proof.py",
}
AWS_CLI_RE = re.compile(r"(^|[;&|()\s])aws\s+(ec2|sts|s3|ssm|iam|cloudformation)\b")
LAUNCHABLE_PACKAGE_REQUIRED_ACTIONS = {
    "end-to-end",
    "canary",
    "canary-after-prerequisites",
    "start-prerequisites",
    "prerequisites",
    "full",
    "start-full",
    "resume",
    "staged-proof",
    "detached-staged-proof",
}


def _safe_id(value: str) -> str:
    return "".join(char if char.isalnum() or char in "._-" else "_" for char in value)


def _relative(root: Path, path: Path) -> str:
    return str(path.relative_to(root)) if path.is_relative_to(root) else str(path)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _digest_components(components: list[dict[str, Any]]) -> str:
    canonical = json.dumps(components, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _validate_package_component_fingerprints(
    *, root: Path, payload: dict[str, Any]
) -> dict[str, Any]:
    components = payload.get("component_fingerprints")
    expected_package_sha256 = payload.get("package_sha256")
    summary: dict[str, Any] = {
        "present": isinstance(components, list),
        "component_count": len(components) if isinstance(components, list) else 0,
        "package_sha256_present": bool(expected_package_sha256),
        "expected_package_sha256": expected_package_sha256,
        "recomputed_package_sha256": None,
        "package_sha256_matches_components": False,
        "passed": False,
        "issues": [],
        "rows": [],
    }
    if not isinstance(components, list) or not components:
        summary["issues"].append(
            {
                "code": "component_fingerprints_missing",
                "message": "proof package does not contain component fingerprints",
            }
        )
        return summary

    recomputed = _digest_components(components)
    summary["recomputed_package_sha256"] = recomputed
    summary["package_sha256_matches_components"] = expected_package_sha256 == recomputed
    if not expected_package_sha256:
        summary["issues"].append(
            {
                "code": "package_sha256_missing",
                "message": "proof package does not record the component digest",
            }
        )
    elif expected_package_sha256 != recomputed:
        summary["issues"].append(
            {
                "code": "package_sha256_component_digest_mismatch",
                "message": "proof package digest does not match stored component fingerprints",
                "expected_package_sha256": expected_package_sha256,
                "recomputed_package_sha256": recomputed,
            }
        )

    for index, component in enumerate(components):
        if not isinstance(component, dict):
            summary["issues"].append(
                {
                    "code": "component_fingerprint_row_invalid",
                    "message": "component fingerprint row is not an object",
                    "index": index,
                }
            )
            continue
        relative = component.get("path")
        row: dict[str, Any] = {
            "index": index,
            "path": relative,
            "present": False,
            "passed": False,
        }
        summary["rows"].append(row)
        if not relative:
            summary["issues"].append(
                {
                    "code": "component_fingerprint_path_missing",
                    "message": "component fingerprint row does not record a path",
                    "index": index,
                }
            )
            continue
        path = Path(str(relative))
        resolved = path if path.is_absolute() else root / path
        row["resolved_path"] = _relative(root, resolved)
        if not resolved.exists():
            summary["issues"].append(
                {
                    "code": "component_fingerprint_file_missing",
                    "message": "fingerprinted proof-package component is missing",
                    "index": index,
                    "path": str(relative),
                }
            )
            continue
        actual = _fingerprint_file(resolved)
        row.update(
            {
                "present": True,
                "expected_size_bytes": component.get("size_bytes"),
                "actual_size_bytes": actual["size_bytes"],
                "expected_sha256": component.get("sha256"),
                "actual_sha256": actual["sha256"],
                "expected_mode_octal": component.get("mode_octal"),
                "actual_mode_octal": actual["mode_octal"],
            }
        )
        checks = {
            "size": component.get("size_bytes") == actual["size_bytes"],
            "sha256": component.get("sha256") == actual["sha256"],
            "mode": component.get("mode_octal") == actual["mode_octal"],
        }
        row["checks"] = checks
        row["passed"] = all(checks.values())
        if not checks["size"]:
            summary["issues"].append(
                {
                    "code": "component_fingerprint_size_mismatch",
                    "message": "fingerprinted proof-package component size changed",
                    "index": index,
                    "path": str(relative),
                    "expected_size_bytes": component.get("size_bytes"),
                    "actual_size_bytes": actual["size_bytes"],
                }
            )
        if not checks["sha256"]:
            summary["issues"].append(
                {
                    "code": "component_fingerprint_sha256_mismatch",
                    "message": "fingerprinted proof-package component bytes changed",
                    "index": index,
                    "path": str(relative),
                    "expected_sha256": component.get("sha256"),
                    "actual_sha256": actual["sha256"],
                }
            )
        if not checks["mode"]:
            summary["issues"].append(
                {
                    "code": "component_fingerprint_mode_mismatch",
                    "message": "fingerprinted proof-package component mode changed",
                    "index": index,
                    "path": str(relative),
                    "expected_mode_octal": component.get("mode_octal"),
                    "actual_mode_octal": actual["mode_octal"],
                }
            )

    summary["passed"] = not summary["issues"]
    return summary


def _proof_package_validation(
    *,
    root: Path,
    proof_package_path: Path,
    runbook_manifest_path: Path,
    host: str,
    remote_root: str,
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
    component_validation = _validate_package_component_fingerprints(
        root=root,
        payload=payload,
    )
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
        "package_sha256_present": bool(payload.get("package_sha256")),
        "package_sha256_matches_components": (
            component_validation.get("package_sha256_matches_components") is True
        ),
        "component_fingerprints_present": (
            component_validation.get("present") is True
            and int(component_validation.get("component_count") or 0) > 0
        ),
        "component_fingerprints_revalidated": component_validation.get("passed") is True,
        "execution_provider_nonaws": payload.get("execution_provider") == EXECUTION_PROVIDER,
        "aws_usage_disallowed": payload.get("aws_usage_allowed") is False,
        "aws_scan_passed": (payload.get("aws_command_scan") or {}).get("passed") is True,
        "runbook_validation_passed": (payload.get("runbook_validation") or {}).get("passed") is True,
        "runbook_matches": payload.get("runbook_manifest_path") == runbook_relative,
        "remote_host_matches": payload.get("remote_host_placeholder") == host,
        "remote_root_matches": payload.get("remote_root_placeholder") == remote_root,
        "solver_matches": payload.get("solver") == "h48h10",
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
            "package_sha256_matches_components": (
                component_validation.get("package_sha256_matches_components") is True
            ),
            "component_fingerprint_count": component_validation.get("component_count"),
            "component_fingerprint_validation": component_validation,
            "runbook_manifest_path": payload.get("runbook_manifest_path"),
            "expected_runbook_manifest_path": runbook_relative,
            "remote_host_placeholder": payload.get("remote_host_placeholder"),
            "expected_remote_host": host,
            "remote_root_placeholder": payload.get("remote_root_placeholder"),
            "expected_remote_root": remote_root,
            "full_required_workload_count": (
                (payload.get("full_plan_summary") or {}).get("required_workload_count")
            ),
            "checks": checks,
            "issues": issues,
            "passed": not issues,
        }
    )
    return summary


def _issue(code: str, message: str, **details: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"code": code, "message": message}
    payload.update(details)
    return payload


def _path_from_manifest(root: Path, manifest_path: Path, value: Any) -> Path | None:
    if value is None:
        return None
    path = Path(str(value))
    if path.is_absolute():
        return path
    return root / path


def _fingerprint_file(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    mode = path.stat().st_mode & 0o777
    return {
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "mode_octal": oct(mode),
    }


def _contains_arg(command: list[Any], *expected: str) -> bool:
    tokens = [str(token) for token in command]
    if not expected:
        return False
    if len(expected) == 1:
        return expected[0] in tokens
    width = len(expected)
    return any(tokens[index : index + width] == list(expected) for index in range(len(tokens) - width + 1))


def _find_stronger_table_workload(plan: dict[str, Any], solver: str) -> dict[str, Any] | None:
    target_id = f"stronger_table_{solver}"
    for workload in plan.get("workloads", []) or []:
        if not isinstance(workload, dict):
            continue
        if workload.get("id") == target_id and workload.get("kind") == "h48_stronger_table_generation_and_certification":
            return workload
    return None


def _validate_plan(
    *,
    root: Path,
    manifest: dict[str, Any],
    plan_path: Path,
    expected_scope: str,
    expected_solver: str,
    expected_profile: str | None,
    expected_seed: int | None,
    expected_workbatch: int | None,
    issues: list[dict[str, Any]],
) -> dict[str, Any]:
    relative_plan_path = _relative(root, plan_path)
    if not plan_path.exists():
        issues.append(
            _issue(
                "missing_plan",
                f"{expected_scope} plan referenced by the runbook does not exist",
                path=relative_plan_path,
            )
        )
        return {"path": relative_plan_path, "present": False, "scope": expected_scope}

    try:
        plan = _load_json(plan_path)
    except json.JSONDecodeError as exc:
        issues.append(
            _issue(
                "invalid_plan_json",
                f"{expected_scope} plan is not valid JSON",
                path=relative_plan_path,
                error=str(exc),
            )
        )
        return {"path": relative_plan_path, "present": True, "scope": expected_scope, "json_valid": False}

    summary_key = f"{expected_scope}_plan_summary"
    summary = manifest.get(summary_key) or {}
    workload_ids = [
        str(workload.get("id"))
        for workload in plan.get("workloads", []) or []
        if isinstance(workload, dict) and workload.get("id") is not None
    ]
    required_ids = [
        str(workload.get("id"))
        for workload in plan.get("workloads", []) or []
        if isinstance(workload, dict)
        and workload.get("required_for_fast_every_state_claim") is True
        and workload.get("id") is not None
    ]
    checks = {
        "path": relative_plan_path,
        "present": True,
        "json_valid": True,
        "scope": expected_scope,
        "solver": plan.get("solver"),
        "profile": plan.get("profile"),
        "seed": plan.get("seed"),
        "claim_scope": plan.get("claim_scope"),
        "distance": plan.get("distance"),
        "h48_gendata_workbatch": plan.get("h48_gendata_workbatch"),
        "workload_count": len(workload_ids),
        "required_workload_ids": required_ids,
        "summary_required_workload_count": summary.get("required_workload_count"),
        "summary_h48_gendata_workbatch": summary.get("h48_gendata_workbatch"),
    }

    if plan.get("solver") != expected_solver:
        issues.append(
            _issue(
                "plan_solver_mismatch",
                f"{expected_scope} plan solver does not match the runbook target solver",
                path=relative_plan_path,
                expected=expected_solver,
                actual=plan.get("solver"),
            )
        )
    if expected_profile is not None and plan.get("profile") != expected_profile:
        issues.append(
            _issue(
                "plan_profile_mismatch",
                f"{expected_scope} plan profile does not match the runbook profile",
                path=relative_plan_path,
                expected=expected_profile,
                actual=plan.get("profile"),
            )
        )
    if expected_seed is not None and plan.get("seed") != expected_seed:
        issues.append(
            _issue(
                "plan_seed_mismatch",
                f"{expected_scope} plan seed does not match the runbook seed",
                path=relative_plan_path,
                expected=expected_seed,
                actual=plan.get("seed"),
            )
        )
    if plan.get("claim_scope") != expected_scope:
        issues.append(
            _issue(
                "plan_scope_mismatch",
                f"{expected_scope} plan claim_scope is wrong",
                path=relative_plan_path,
                expected=expected_scope,
                actual=plan.get("claim_scope"),
            )
        )
    if plan.get("distance") != 20:
        issues.append(
            _issue(
                "plan_distance_mismatch",
                f"{expected_scope} plan is not a distance-20 hard-tail proof plan",
                path=relative_plan_path,
                expected=20,
                actual=plan.get("distance"),
            )
        )
    if expected_scope == "full" and plan.get("selected_offset_start") != 0:
        issues.append(
            _issue(
                "full_plan_start_offset_not_zero",
                "full plan does not start from the first public distance-20 hard-tail row",
                path=relative_plan_path,
                actual=plan.get("selected_offset_start"),
            )
        )
    if expected_scope == "full" and plan.get("selected_offset_end") != plan.get("available_scramble_rows"):
        issues.append(
            _issue(
                "full_plan_incomplete_offset_range",
                "full plan does not cover every available public distance-20 hard-tail row",
                path=relative_plan_path,
                selected_offset_end=plan.get("selected_offset_end"),
                available_scramble_rows=plan.get("available_scramble_rows"),
            )
        )

    if expected_workbatch is not None and plan.get("h48_gendata_workbatch") != expected_workbatch:
        issues.append(
            _issue(
                "plan_workbatch_mismatch",
                f"{expected_scope} plan h48_gendata_workbatch does not match the runbook summary",
                path=relative_plan_path,
                expected=expected_workbatch,
                actual=plan.get("h48_gendata_workbatch"),
            )
        )

    stronger = _find_stronger_table_workload(plan, expected_solver)
    checks["stronger_table_workload_present"] = stronger is not None
    if stronger is None:
        issues.append(
            _issue(
                "missing_stronger_table_workload",
                f"{expected_scope} plan does not contain the required stronger-table workload",
                path=relative_plan_path,
                expected_workload_id=f"stronger_table_{expected_solver}",
            )
        )
        return checks

    command_args = list(str(part) for part in stronger.get("command_args", []) or [])
    checks["stronger_table_workload"] = {
        "id": stronger.get("id"),
        "kind": stronger.get("kind"),
        "h48_gendata_workbatch": stronger.get("h48_gendata_workbatch"),
        "required_for_fast_every_state_claim": stronger.get("required_for_fast_every_state_claim") is True,
        "command_args": command_args,
    }
    if stronger.get("required_for_fast_every_state_claim") is not True:
        issues.append(
            _issue(
                "stronger_table_not_required_for_claim",
                f"{expected_scope} stronger-table workload is not marked as required for the fast every-state claim",
                path=relative_plan_path,
            )
        )
    if expected_workbatch is not None and stronger.get("h48_gendata_workbatch") != expected_workbatch:
        issues.append(
            _issue(
                "stronger_table_workbatch_mismatch",
                f"{expected_scope} stronger-table workload workbatch does not match the runbook summary",
                path=relative_plan_path,
                expected=expected_workbatch,
                actual=stronger.get("h48_gendata_workbatch"),
            )
        )
    required_command_flags = [
        ("--target-solver", expected_solver),
        ("--gendata-workbatch", str(expected_workbatch)) if expected_workbatch is not None else ("--gendata-workbatch",),
        ("--mmap-sync-mode", "async"),
        ("--backend-cflag=-march=native",),
        ("--skip-generation-distribution-scan",),
    ]
    for flag in required_command_flags:
        if not _contains_arg(command_args, *flag):
            issues.append(
                _issue(
                    "stronger_table_missing_optimized_command_flag",
                    f"{expected_scope} stronger-table command is missing a required optimized H48H10 flag",
                    path=relative_plan_path,
                    expected_flag=list(flag),
                )
            )
    return checks


def _validate_nonaws_runbook_manifest(*, root: Path, runbook_manifest_path: Path) -> dict[str, Any]:
    """Validate that a generic SSH proof runbook targets the current H48H10 proof package."""

    manifest_path = runbook_manifest_path if runbook_manifest_path.is_absolute() else root / runbook_manifest_path
    issues: list[dict[str, Any]] = []
    if not manifest_path.exists():
        return {
            "passed": False,
            "strict_h48h10_validation": True,
            "manifest_path": _relative(root, manifest_path),
            "issues": [
                _issue(
                    "missing_runbook_manifest",
                    "runbook manifest does not exist",
                    path=_relative(root, manifest_path),
                )
            ],
        }

    try:
        manifest = _load_json(manifest_path)
    except json.JSONDecodeError as exc:
        return {
            "passed": False,
            "strict_h48h10_validation": True,
            "manifest_path": _relative(root, manifest_path),
            "issues": [
                _issue(
                    "invalid_runbook_json",
                    "runbook manifest is not valid JSON",
                    path=_relative(root, manifest_path),
                    error=str(exc),
                )
            ],
        }

    solver = str(manifest.get("solver") or "")
    profile = str(manifest.get("profile")) if manifest.get("profile") is not None else None
    seed = int(manifest["seed"]) if manifest.get("seed") is not None else None
    full_summary = manifest.get("full_plan_summary") or {}
    expected_workbatch = full_summary.get("h48_gendata_workbatch")
    expected_workbatch_int = int(expected_workbatch) if expected_workbatch is not None else None
    strict_h48h10 = solver == "h48h10" or str(full_summary.get("solver") or "") == "h48h10"

    generated = manifest.get("generated_files") or {}
    required_generated_keys = [
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
    missing_generated_keys = [key for key in required_generated_keys if key not in generated]
    missing_generated_files: list[str] = []
    generated_file_fingerprints = manifest.get("generated_file_fingerprints") or {}
    generated_file_fingerprint_checks: list[dict[str, Any]] = []
    missing_generated_fingerprint_keys: list[str] = []
    for key in required_generated_keys:
        value = generated.get(key)
        path = _path_from_manifest(root, manifest_path, value)
        if path is not None and not path.exists():
            missing_generated_files.append(str(value))
    for key, value in sorted(generated.items()):
        path = _path_from_manifest(root, manifest_path, value)
        expected = generated_file_fingerprints.get(key)
        if expected is None:
            missing_generated_fingerprint_keys.append(str(key))
            continue
        check: dict[str, Any] = {
            "key": str(key),
            "path": str(value),
            "expected_path": expected.get("path"),
            "present": path.exists() if path is not None else False,
        }
        generated_file_fingerprint_checks.append(check)
        if path is None or not path.exists():
            continue
        actual = _fingerprint_file(path)
        check.update(
            {
                "expected_size_bytes": expected.get("size_bytes"),
                "actual_size_bytes": actual["size_bytes"],
                "expected_sha256": expected.get("sha256"),
                "actual_sha256": actual["sha256"],
                "expected_mode_octal": expected.get("mode_octal"),
                "actual_mode_octal": actual["mode_octal"],
                "passed": (
                    expected.get("path") == str(value)
                    and expected.get("size_bytes") == actual["size_bytes"]
                    and expected.get("sha256") == actual["sha256"]
                    and expected.get("mode_octal") == actual["mode_octal"]
                ),
            }
        )
        if expected.get("path") != str(value):
            issues.append(
                _issue(
                    "generated_file_fingerprint_path_mismatch",
                    "runbook generated file fingerprint path does not match generated_files entry",
                    key=str(key),
                    expected_path=expected.get("path"),
                    actual_path=str(value),
                )
            )
        if expected.get("size_bytes") != actual["size_bytes"]:
            issues.append(
                _issue(
                    "generated_file_fingerprint_size_mismatch",
                    "runbook generated file size no longer matches the manifest fingerprint",
                    key=str(key),
                    path=str(value),
                    expected_size_bytes=expected.get("size_bytes"),
                    actual_size_bytes=actual["size_bytes"],
                )
            )
        if expected.get("sha256") != actual["sha256"]:
            issues.append(
                _issue(
                    "generated_file_fingerprint_sha256_mismatch",
                    "runbook generated file bytes no longer match the manifest fingerprint",
                    key=str(key),
                    path=str(value),
                    expected_sha256=expected.get("sha256"),
                    actual_sha256=actual["sha256"],
                )
            )
        if expected.get("mode_octal") != actual["mode_octal"]:
            issues.append(
                _issue(
                    "generated_file_fingerprint_mode_mismatch",
                    "runbook generated file mode no longer matches the manifest fingerprint",
                    key=str(key),
                    path=str(value),
                    expected_mode_octal=expected.get("mode_octal"),
                    actual_mode_octal=actual["mode_octal"],
                )
            )

    if solver != "h48h10":
        issues.append(
            _issue(
                "runbook_solver_not_h48h10",
                "the fast every-state proof package must target h48h10",
                expected="h48h10",
                actual=solver,
            )
        )
    if manifest.get("aws_required") is not False:
        issues.append(
            _issue(
                "runbook_allows_or_requires_aws",
                "non-AWS proof wrapper requires a runbook with aws_required=false",
                actual=manifest.get("aws_required"),
            )
        )
    if manifest.get("nonaws_generic_ssh_supported") is not True:
        issues.append(
            _issue(
                "runbook_missing_nonaws_support",
                "runbook does not explicitly support the generic SSH non-AWS proof path",
                actual=manifest.get("nonaws_generic_ssh_supported"),
            )
        )
    if manifest.get("nonaws_entrypoint") not in {None, "scripts/run_h48_fasttarget_nonaws_proof.py"}:
        issues.append(
            _issue(
                "runbook_nonaws_entrypoint_mismatch",
                "runbook points at a different non-AWS entrypoint",
                actual=manifest.get("nonaws_entrypoint"),
            )
        )
    if manifest.get("fast_runtime_proven_for_every_possible_state") is not False:
        issues.append(
            _issue(
                "runbook_claims_runtime_proof",
                "the generated runbook must remain a plan artifact, not runtime proof",
                actual=manifest.get("fast_runtime_proven_for_every_possible_state"),
            )
        )
    if missing_generated_keys:
        issues.append(
            _issue(
                "runbook_missing_generated_file_keys",
                "runbook manifest is missing scripts required for the staged H48H10 proof",
                missing_keys=missing_generated_keys,
            )
        )
    if missing_generated_files:
        issues.append(
            _issue(
                "runbook_missing_generated_files",
                "runbook manifest references proof scripts that are absent on disk",
                missing_files=missing_generated_files,
            )
        )
    if missing_generated_fingerprint_keys:
        issues.append(
            _issue(
                "runbook_missing_generated_file_fingerprints",
                "runbook manifest does not fingerprint every generated file",
                missing_keys=missing_generated_fingerprint_keys,
            )
        )
    if expected_workbatch_int is None:
        issues.append(
            _issue(
                "runbook_missing_h48_gendata_workbatch",
                "full plan summary does not record the H48 generation workbatch",
            )
        )

    plan_checks: list[dict[str, Any]] = []
    for scope in ("canary", "full"):
        plan_path = _path_from_manifest(root, manifest_path, manifest.get(f"{scope}_plan_path"))
        if plan_path is None:
            issues.append(
                _issue(
                    "runbook_missing_plan_path",
                    f"runbook manifest does not reference the {scope} plan path",
                    scope=scope,
                )
            )
            continue
        plan_checks.append(
            _validate_plan(
                root=root,
                manifest=manifest,
                plan_path=plan_path,
                expected_scope=scope,
                expected_solver="h48h10",
                expected_profile=profile,
                expected_seed=seed,
                expected_workbatch=expected_workbatch_int,
                issues=issues,
            )
        )

    return {
        "passed": not issues,
        "strict_h48h10_validation": strict_h48h10,
        "manifest_path": _relative(root, manifest_path),
        "run_suffix": manifest.get("run_suffix"),
        "solver": solver,
        "profile": profile,
        "seed": seed,
        "aws_required": manifest.get("aws_required"),
        "nonaws_generic_ssh_supported": manifest.get("nonaws_generic_ssh_supported"),
        "nonaws_entrypoint": manifest.get("nonaws_entrypoint"),
        "h48_gendata_workbatch": expected_workbatch_int,
        "required_generated_file_keys": required_generated_keys,
        "missing_generated_file_keys": missing_generated_keys,
        "missing_generated_files": missing_generated_files,
        "generated_file_fingerprint_algorithm": manifest.get(
            "generated_file_fingerprint_algorithm"
        ),
        "generated_file_fingerprint_count": len(generated_file_fingerprints),
        "missing_generated_file_fingerprint_keys": missing_generated_fingerprint_keys,
        "generated_file_fingerprint_checks": generated_file_fingerprint_checks,
        "plan_checks": plan_checks,
        "issues": issues,
    }


def _output_path(
    *,
    root: Path,
    runbook_manifest_path: Path,
    artifact_suffix: str,
) -> Path:
    manifest = _load_json(runbook_manifest_path if runbook_manifest_path.is_absolute() else root / runbook_manifest_path)
    run_suffix = _safe_id(str(manifest.get("run_suffix") or runbook_manifest_path.stem))
    suffix = f"_{_safe_id(artifact_suffix)}" if artifact_suffix else ""
    return root / "results" / "processed" / f"h48_fasttarget_nonaws_run_{run_suffix}{suffix}.json"


def _command_has_forbidden_aws(command: list[Any]) -> bool:
    tokens = [str(part) for part in command]
    if tokens and Path(tokens[0]).name == "aws":
        return True
    joined = shlex.join(tokens)
    return any(name in joined for name in FORBIDDEN_SCRIPT_NAMES) or AWS_CLI_RE.search(joined) is not None


def _scan_script_for_aws(root: Path, relative: str) -> list[dict[str, Any]]:
    path = Path(relative)
    resolved = path if path.is_absolute() else root / path
    if not resolved.exists() or not resolved.is_file():
        return []
    text = resolved.read_text(encoding="utf-8", errors="replace")
    matches: list[dict[str, Any]] = []
    if any(name in text for name in FORBIDDEN_SCRIPT_NAMES):
        matches.append(
            {
                "kind": "forbidden_aws_helper_reference",
                "script": _relative(root, resolved),
            }
        )
    if AWS_CLI_RE.search(text):
        matches.append(
            {
                "kind": "aws_cli_invocation_in_script",
                "script": _relative(root, resolved),
            }
        )
    return matches


def scan_planned_steps_for_aws(*, root: Path, steps: list[dict[str, Any]]) -> dict[str, Any]:
    """Check a planned generic SSH proof for AWS helper/CLI usage."""

    matches: list[dict[str, Any]] = []
    for step in steps:
        command = [str(part) for part in step.get("command", [])]
        if _command_has_forbidden_aws(command):
            matches.append(
                {
                    "kind": "forbidden_aws_command",
                    "step_id": step.get("id"),
                    "command": command,
                }
            )
        script = step.get("script")
        if script:
            matches.extend(_scan_script_for_aws(root, str(script)))
        for script_path in step.get("scripts", []) or []:
            matches.extend(_scan_script_for_aws(root, str(script_path)))
    return {
        "passed": not matches,
        "forbidden_aws_match_count": len(matches),
        "matches": matches,
    }


def _planned_steps_payload(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for step in steps:
        command = [str(part) for part in step.get("command", [])]
        rows.append(
            {
                "id": step.get("id"),
                "location": step.get("location"),
                "required": step.get("required") is True,
                "detached": step.get("detached") is True,
                "command": command,
                "shell_command": shlex.join(command),
                "script": step.get("script"),
                "scripts": step.get("scripts"),
            }
        )
    return rows


def _cli_path(root: Path, path: Path) -> str:
    resolved = path if path.is_absolute() else root / path
    return _relative(root, resolved)


def _nonaws_recovery_command(
    *,
    root: Path,
    runbook_manifest_path: Path,
    host: str,
    remote_root: str,
    port: int | None,
    identity_file: Path | None,
    ssh_options: list[str],
    rsync_excludes: list[str],
    rsync_delete: bool,
    skip_sync: bool,
    skip_fetch: bool,
    skip_local_finalize: bool,
    install_fetched_prerequisites: bool,
    prerequisite_bundle_mode: str,
    fetch_diagnostics_on_fail: bool,
    remote_action: str,
    timeout_seconds: float | None,
    prerequisite_wait_timeout_seconds: float,
    prerequisite_poll_interval_seconds: float,
    full_wait_timeout_seconds: float,
    full_poll_interval_seconds: float,
    artifact_suffix: str,
    proof_package_path: Path,
    execute: bool,
) -> list[str]:
    command = [
        "python",
        "scripts/run_h48_fasttarget_nonaws_proof.py",
        "--root",
        str(root),
        "--runbook",
        _cli_path(root, runbook_manifest_path),
        "--host",
        host,
        "--remote-root",
        remote_root,
        "--remote-action",
        remote_action,
        "--prerequisite-bundle-mode",
        prerequisite_bundle_mode,
        "--prerequisite-wait-timeout",
        str(prerequisite_wait_timeout_seconds),
        "--prerequisite-poll-interval",
        str(prerequisite_poll_interval_seconds),
        "--full-wait-timeout",
        str(full_wait_timeout_seconds),
        "--full-poll-interval",
        str(full_poll_interval_seconds),
        "--artifact-suffix",
        artifact_suffix,
        "--proof-package",
        _cli_path(root, proof_package_path),
    ]
    if port is not None:
        command.extend(["--port", str(port)])
    if identity_file is not None:
        command.extend(["--identity-file", str(identity_file)])
    for option in ssh_options:
        command.extend(["--ssh-option", option])
    for pattern in rsync_excludes:
        command.extend(["--rsync-exclude", pattern])
    if rsync_delete:
        command.append("--rsync-delete")
    if skip_sync:
        command.append("--skip-sync")
    if skip_fetch:
        command.append("--skip-fetch")
    if skip_local_finalize:
        command.append("--skip-local-finalize")
    if install_fetched_prerequisites:
        command.append("--install-fetched-prerequisites")
    if not fetch_diagnostics_on_fail:
        command.append("--no-fetch-diagnostics-on-fail")
    if timeout_seconds is not None:
        command.extend(["--timeout", str(timeout_seconds)])
    if execute:
        command.append("--execute")
    return command


def _write_pre_remote_checkpoint(
    *,
    root: Path,
    runbook_manifest_path: Path,
    host: str,
    remote_root: str,
    port: int | None,
    identity_file: Path | None,
    ssh_options: list[str],
    rsync_excludes: list[str],
    rsync_delete: bool,
    skip_sync: bool,
    skip_fetch: bool,
    skip_local_finalize: bool,
    install_fetched_prerequisites: bool,
    prerequisite_bundle_mode: str,
    fetch_diagnostics_on_fail: bool,
    remote_action: str,
    timeout_seconds: float | None,
    prerequisite_wait_timeout_seconds: float,
    prerequisite_poll_interval_seconds: float,
    full_wait_timeout_seconds: float,
    full_poll_interval_seconds: float,
    artifact_suffix: str,
    proof_package_path: Path,
    requested_execute: bool,
    steps: list[dict[str, Any]],
    scan: dict[str, Any],
    runbook_validation: dict[str, Any],
    proof_package_validation: dict[str, Any],
    launchable_proof_package_required: bool,
) -> tuple[dict[str, Any], Path]:
    output = _output_path(
        root=root,
        runbook_manifest_path=runbook_manifest_path,
        artifact_suffix=artifact_suffix,
    )
    resume_command = _nonaws_recovery_command(
        root=root,
        runbook_manifest_path=runbook_manifest_path,
        host=host,
        remote_root=remote_root,
        port=port,
        identity_file=identity_file,
        ssh_options=ssh_options,
        rsync_excludes=rsync_excludes,
        rsync_delete=rsync_delete,
        skip_sync=skip_sync,
        skip_fetch=skip_fetch,
        skip_local_finalize=skip_local_finalize,
        install_fetched_prerequisites=install_fetched_prerequisites,
        prerequisite_bundle_mode=prerequisite_bundle_mode,
        fetch_diagnostics_on_fail=fetch_diagnostics_on_fail,
        remote_action=remote_action,
        timeout_seconds=timeout_seconds,
        prerequisite_wait_timeout_seconds=prerequisite_wait_timeout_seconds,
        prerequisite_poll_interval_seconds=prerequisite_poll_interval_seconds,
        full_wait_timeout_seconds=full_wait_timeout_seconds,
        full_poll_interval_seconds=full_poll_interval_seconds,
        artifact_suffix=artifact_suffix,
        proof_package_path=proof_package_path,
        execute=True,
    )
    status_command = _nonaws_recovery_command(
        root=root,
        runbook_manifest_path=runbook_manifest_path,
        host=host,
        remote_root=remote_root,
        port=port,
        identity_file=identity_file,
        ssh_options=ssh_options,
        rsync_excludes=rsync_excludes,
        rsync_delete=False,
        skip_sync=True,
        skip_fetch=False,
        skip_local_finalize=True,
        install_fetched_prerequisites=False,
        prerequisite_bundle_mode=prerequisite_bundle_mode,
        fetch_diagnostics_on_fail=fetch_diagnostics_on_fail,
        remote_action="status",
        timeout_seconds=timeout_seconds,
        prerequisite_wait_timeout_seconds=prerequisite_wait_timeout_seconds,
        prerequisite_poll_interval_seconds=prerequisite_poll_interval_seconds,
        full_wait_timeout_seconds=full_wait_timeout_seconds,
        full_poll_interval_seconds=full_poll_interval_seconds,
        artifact_suffix=f"{artifact_suffix}_status",
        proof_package_path=proof_package_path,
        execute=False,
    )
    payload = {
        "schema_version": 1,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "checkpoint_kind": "nonaws_pre_remote_proof",
        "status": "nonaws_h48_fasttarget_pre_remote_checkpoint_not_runtime_evidence",
        "execution_provider": EXECUTION_PROVIDER,
        "aws_usage_allowed": False,
        "aws_unlock_env": AWS_UNLOCK_ENV,
        "aws_unlock_env_present": os.environ.get(AWS_UNLOCK_ENV) == AWS_UNLOCK_VALUE,
        "runbook_manifest_path": _relative(root, runbook_manifest_path),
        "remote_host": host,
        "remote_root": remote_root,
        "remote_action": remote_action,
        "prerequisite_bundle_mode": prerequisite_bundle_mode,
        "requested_execute": requested_execute,
        "execute": False,
        "dry_run": True,
        "launchable_proof_package_required": launchable_proof_package_required,
        "planned_step_count": len(steps),
        "rows": _planned_steps_payload(steps),
        "aws_command_scan": scan,
        "runbook_validation": runbook_validation,
        "proof_package_validation": proof_package_validation,
        "checkpoint_resume_command": resume_command,
        "checkpoint_resume_shell_command": shlex.join(resume_command),
        "checkpoint_status_command": status_command,
        "checkpoint_status_shell_command": shlex.join(status_command),
        "pre_remote_checkpoint_written": True,
        "checkpoint_written_before_remote_start": True,
        "passed": False,
        "fast_runtime_proven_for_every_possible_state": False,
        "notes": (
            "This is a recoverability checkpoint written after all generic non-AWS "
            "launch guards pass and before run_remote_fasttarget_proof is called. "
            "It is not runtime proof."
        ),
    }
    write_json(output, payload)
    return payload, output


def _refusal_payload(
    *,
    root: Path,
    runbook_manifest_path: Path,
    host: str,
    remote_root: str,
    remote_action: str,
    prerequisite_bundle_mode: str,
    artifact_suffix: str,
    requested_execute: bool,
    steps: list[dict[str, Any]],
    scan: dict[str, Any],
    runbook_validation: dict[str, Any],
    proof_package_validation: dict[str, Any],
    launchable_proof_package_required: bool,
    reason: str,
) -> tuple[dict[str, Any], Path]:
    output = _output_path(
        root=root,
        runbook_manifest_path=runbook_manifest_path,
        artifact_suffix=artifact_suffix,
    )
    payload = {
        "schema_version": 1,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "execution_provider": EXECUTION_PROVIDER,
        "aws_usage_allowed": False,
        "aws_unlock_env": AWS_UNLOCK_ENV,
        "aws_unlock_env_present": os.environ.get(AWS_UNLOCK_ENV) == AWS_UNLOCK_VALUE,
        "status": "refused_nonaws_guard",
        "reason": reason,
        "runbook_manifest_path": _relative(root, runbook_manifest_path if runbook_manifest_path.is_absolute() else root / runbook_manifest_path),
        "remote_host": host,
        "remote_root": remote_root,
        "remote_action": remote_action,
        "prerequisite_bundle_mode": prerequisite_bundle_mode,
        "requested_execute": requested_execute,
        "execute": False,
        "dry_run": True,
        "planned_step_count": len(steps),
        "rows": _planned_steps_payload(steps),
        "aws_command_scan": scan,
        "runbook_validation": runbook_validation,
        "launchable_proof_package_required": launchable_proof_package_required,
        "proof_package_validation": proof_package_validation,
        "passed": False,
        "fast_runtime_proven_for_every_possible_state": False,
    }
    write_json(output, payload)
    return payload, output


def run_nonaws_fasttarget_proof(
    *,
    root: Path,
    runbook_manifest_path: Path,
    host: str,
    remote_root: str,
    port: int | None = None,
    identity_file: Path | None = None,
    ssh_options: list[str] | None = None,
    rsync_excludes: list[str] | None = None,
    rsync_delete: bool = False,
    skip_sync: bool = False,
    skip_fetch: bool = False,
    skip_local_finalize: bool = False,
    install_fetched_prerequisites: bool = False,
    prerequisite_bundle_mode: str = "archive",
    fetch_diagnostics_on_fail: bool = True,
    remote_action: str = "detached-staged-proof",
    execute: bool = False,
    timeout_seconds: float | None = None,
    prerequisite_wait_timeout_seconds: float = 0.0,
    prerequisite_poll_interval_seconds: float = 30.0,
    full_wait_timeout_seconds: float = 0.0,
    full_poll_interval_seconds: float = 30.0,
    artifact_suffix: str = "nonaws",
    proof_package_path: Path | None = None,
) -> tuple[dict[str, Any], Path]:
    """Run the generic SSH proof path while explicitly forbidding AWS helpers."""

    root = root.resolve()
    runbook = runbook_manifest_path if runbook_manifest_path.is_absolute() else root / runbook_manifest_path
    begin = time.perf_counter()
    runbook_validation = _validate_nonaws_runbook_manifest(
        root=root,
        runbook_manifest_path=runbook,
    )
    empty_scan = {"passed": True, "forbidden_aws_match_count": 0, "matches": []}
    launchable_proof_package_required = bool(
        execute and remote_action in LAUNCHABLE_PACKAGE_REQUIRED_ACTIONS
    )
    proof_package_validation = _proof_package_validation(
        root=root,
        proof_package_path=proof_package_path or DEFAULT_PROOF_PACKAGE,
        runbook_manifest_path=runbook,
        host=host,
        remote_root=remote_root,
        required=launchable_proof_package_required,
    )
    if execute and runbook_validation["passed"] is not True:
        return _refusal_payload(
            root=root,
            runbook_manifest_path=runbook,
            host=host,
            remote_root=remote_root,
            remote_action=remote_action,
            prerequisite_bundle_mode=prerequisite_bundle_mode,
            artifact_suffix=artifact_suffix,
            requested_execute=execute,
            steps=[],
            scan=empty_scan,
            runbook_validation=runbook_validation,
            proof_package_validation=proof_package_validation,
            launchable_proof_package_required=launchable_proof_package_required,
            reason="runbook manifest/plan validation failed for the non-AWS H48H10 proof package",
        )
    steps, _context = build_remote_proof_steps(
        root=root,
        runbook_manifest_path=runbook,
        host=host,
        remote_root=remote_root,
        port=port,
        identity_file=identity_file,
        ssh_options=ssh_options or [],
        rsync_excludes=rsync_excludes or [],
        rsync_delete=rsync_delete,
        skip_sync=skip_sync,
        skip_fetch=skip_fetch,
        skip_local_finalize=skip_local_finalize,
        install_fetched_prerequisites=install_fetched_prerequisites,
        prerequisite_bundle_mode=prerequisite_bundle_mode,
        fetch_diagnostics_on_fail=fetch_diagnostics_on_fail,
        remote_action=remote_action,
        prerequisite_wait_timeout_seconds=prerequisite_wait_timeout_seconds,
        prerequisite_poll_interval_seconds=prerequisite_poll_interval_seconds,
        full_wait_timeout_seconds=full_wait_timeout_seconds,
        full_poll_interval_seconds=full_poll_interval_seconds,
    )
    scan = scan_planned_steps_for_aws(root=root, steps=steps)
    if execute and os.environ.get(AWS_UNLOCK_ENV) == AWS_UNLOCK_VALUE:
        return _refusal_payload(
            root=root,
            runbook_manifest_path=runbook,
            host=host,
            remote_root=remote_root,
            remote_action=remote_action,
            prerequisite_bundle_mode=prerequisite_bundle_mode,
            artifact_suffix=artifact_suffix,
            requested_execute=execute,
            steps=steps,
            scan=scan,
            runbook_validation=runbook_validation,
            proof_package_validation=proof_package_validation,
            launchable_proof_package_required=launchable_proof_package_required,
            reason=(
                f"{AWS_UNLOCK_ENV}=1 is active. The non-AWS proof wrapper refuses execution "
                "while the AWS unlock environment variable is set."
            ),
        )
    if execute and launchable_proof_package_required and proof_package_validation.get("passed") is not True:
        return _refusal_payload(
            root=root,
            runbook_manifest_path=runbook,
            host=host,
            remote_root=remote_root,
            remote_action=remote_action,
            prerequisite_bundle_mode=prerequisite_bundle_mode,
            artifact_suffix=artifact_suffix,
            requested_execute=execute,
            steps=steps,
            scan=scan,
            runbook_validation=runbook_validation,
            proof_package_validation=proof_package_validation,
            launchable_proof_package_required=launchable_proof_package_required,
            reason=(
                "launchable H48H10 proof package validation failed; refusing generic "
                "non-AWS proof execution"
            ),
        )
    if execute and scan["passed"] is not True:
        return _refusal_payload(
            root=root,
            runbook_manifest_path=runbook,
            host=host,
            remote_root=remote_root,
            remote_action=remote_action,
            prerequisite_bundle_mode=prerequisite_bundle_mode,
            artifact_suffix=artifact_suffix,
            requested_execute=execute,
            steps=steps,
            scan=scan,
            runbook_validation=runbook_validation,
            proof_package_validation=proof_package_validation,
            launchable_proof_package_required=launchable_proof_package_required,
            reason="planned proof steps reference AWS helpers or AWS CLI commands",
        )

    pre_remote_checkpoint: dict[str, Any] | None = None
    pre_remote_checkpoint_output: Path | None = None
    if execute and launchable_proof_package_required:
        pre_remote_checkpoint, pre_remote_checkpoint_output = _write_pre_remote_checkpoint(
            root=root,
            runbook_manifest_path=runbook,
            host=host,
            remote_root=remote_root,
            port=port,
            identity_file=identity_file,
            ssh_options=ssh_options or [],
            rsync_excludes=rsync_excludes or [],
            rsync_delete=rsync_delete,
            skip_sync=skip_sync,
            skip_fetch=skip_fetch,
            skip_local_finalize=skip_local_finalize,
            install_fetched_prerequisites=install_fetched_prerequisites,
            prerequisite_bundle_mode=prerequisite_bundle_mode,
            fetch_diagnostics_on_fail=fetch_diagnostics_on_fail,
            remote_action=remote_action,
            timeout_seconds=timeout_seconds,
            prerequisite_wait_timeout_seconds=prerequisite_wait_timeout_seconds,
            prerequisite_poll_interval_seconds=prerequisite_poll_interval_seconds,
            full_wait_timeout_seconds=full_wait_timeout_seconds,
            full_poll_interval_seconds=full_poll_interval_seconds,
            artifact_suffix=artifact_suffix,
            proof_package_path=proof_package_path or DEFAULT_PROOF_PACKAGE,
            requested_execute=execute,
            steps=steps,
            scan=scan,
            runbook_validation=runbook_validation,
            proof_package_validation=proof_package_validation,
            launchable_proof_package_required=launchable_proof_package_required,
        )

    underlying_suffix = f"{artifact_suffix}_underlying_remote" if artifact_suffix else "nonaws_underlying_remote"
    payload, underlying_output = run_remote_fasttarget_proof(
        root=root,
        runbook_manifest_path=runbook,
        host=host,
        remote_root=remote_root,
        port=port,
        identity_file=identity_file,
        ssh_options=ssh_options or [],
        rsync_excludes=rsync_excludes or [],
        rsync_delete=rsync_delete,
        skip_sync=skip_sync,
        skip_fetch=skip_fetch,
        skip_local_finalize=skip_local_finalize,
        install_fetched_prerequisites=install_fetched_prerequisites,
        prerequisite_bundle_mode=prerequisite_bundle_mode,
        fetch_diagnostics_on_fail=fetch_diagnostics_on_fail,
        remote_action=remote_action,
        execute=execute,
        timeout_seconds=timeout_seconds,
        prerequisite_wait_timeout_seconds=prerequisite_wait_timeout_seconds,
        prerequisite_poll_interval_seconds=prerequisite_poll_interval_seconds,
        full_wait_timeout_seconds=full_wait_timeout_seconds,
        full_poll_interval_seconds=full_poll_interval_seconds,
        artifact_suffix=underlying_suffix,
    )
    payload.update(
        {
            "execution_provider": EXECUTION_PROVIDER,
            "aws_usage_allowed": False,
            "aws_unlock_env": AWS_UNLOCK_ENV,
            "aws_unlock_env_present": os.environ.get(AWS_UNLOCK_ENV) == AWS_UNLOCK_VALUE,
            "prerequisite_bundle_mode": prerequisite_bundle_mode,
            "aws_command_scan": scan,
            "runbook_validation": runbook_validation,
            "launchable_proof_package_required": launchable_proof_package_required,
            "proof_package_validation": proof_package_validation,
            "pre_remote_checkpoint_written": pre_remote_checkpoint is not None,
            "pre_remote_checkpoint_path": (
                _relative(root, pre_remote_checkpoint_output)
                if pre_remote_checkpoint_output is not None
                else None
            ),
            "pre_remote_checkpoint_status": (
                pre_remote_checkpoint.get("status")
                if isinstance(pre_remote_checkpoint, dict)
                else None
            ),
            "checkpoint_written_before_remote_start": pre_remote_checkpoint is not None,
            "checkpoint_resume_command": (
                pre_remote_checkpoint.get("checkpoint_resume_command")
                if isinstance(pre_remote_checkpoint, dict)
                else None
            ),
            "checkpoint_status_command": (
                pre_remote_checkpoint.get("checkpoint_status_command")
                if isinstance(pre_remote_checkpoint, dict)
                else None
            ),
            "underlying_remote_artifact": _relative(root, underlying_output),
            "runtime_seconds": round(time.perf_counter() - begin, 6),
            "notes": (
                f"{payload.get('notes', '')} This wrapper is the non-AWS entry point: it uses "
                "the generic SSH/rsync remote runner, records execution_provider=generic_ssh_non_aws, "
                "and refuses execution when planned steps reference AWS helpers or AWS CLI commands."
            ).strip(),
        }
    )
    output = _output_path(
        root=root,
        runbook_manifest_path=runbook,
        artifact_suffix=artifact_suffix,
    )
    write_json(output, payload)
    return payload, output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runbook", type=Path, required=True)
    parser.add_argument("--host", required=True, help="SSH host for an approved non-AWS machine")
    parser.add_argument("--remote-root", required=True, help="Remote checkout directory")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--identity-file", type=Path, default=None)
    parser.add_argument("--ssh-option", action="append", default=[])
    parser.add_argument("--rsync-exclude", action="append", default=[])
    parser.add_argument("--rsync-delete", action="store_true")
    parser.add_argument("--skip-sync", action="store_true")
    parser.add_argument("--skip-fetch", action="store_true")
    parser.add_argument("--skip-local-finalize", action="store_true")
    parser.add_argument("--install-fetched-prerequisites", action="store_true")
    parser.add_argument(
        "--prerequisite-bundle-mode",
        choices=PREREQUISITE_BUNDLE_MODE_CHOICES,
        default="archive",
        help=(
            "How prerequisite H48 tables are collected and fetched through the "
            "generic SSH proof path."
        ),
    )
    parser.add_argument("--no-fetch-diagnostics-on-fail", action="store_true")
    parser.add_argument(
        "--remote-action",
        choices=REMOTE_ACTION_CHOICES,
        default="detached-staged-proof",
        help="Generic SSH runbook slice to execute. Default is the detached staged proof.",
    )
    parser.add_argument("--execute", action="store_true", help="Actually run SSH/rsync/local commands")
    parser.add_argument("--timeout", type=float, default=None, help="Per-step wall timeout")
    parser.add_argument("--prerequisite-wait-timeout", type=float, default=0.0)
    parser.add_argument("--prerequisite-poll-interval", type=float, default=30.0)
    parser.add_argument("--full-wait-timeout", type=float, default=0.0)
    parser.add_argument("--full-poll-interval", type=float, default=30.0)
    parser.add_argument("--artifact-suffix", default="nonaws")
    parser.add_argument(
        "--proof-package",
        type=Path,
        default=DEFAULT_PROOF_PACKAGE,
        help=(
            "Launchable H48H10 proof-package manifest required before execute-mode "
            "actions that can start prerequisite generation or full proof workloads."
        ),
    )
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()

    payload, output = run_nonaws_fasttarget_proof(
        root=args.root,
        runbook_manifest_path=args.runbook,
        host=args.host,
        remote_root=args.remote_root,
        port=args.port,
        identity_file=args.identity_file,
        ssh_options=args.ssh_option,
        rsync_excludes=args.rsync_exclude,
        rsync_delete=args.rsync_delete,
        skip_sync=args.skip_sync,
        skip_fetch=args.skip_fetch,
        skip_local_finalize=args.skip_local_finalize,
        install_fetched_prerequisites=args.install_fetched_prerequisites,
        prerequisite_bundle_mode=args.prerequisite_bundle_mode,
        fetch_diagnostics_on_fail=not args.no_fetch_diagnostics_on_fail,
        remote_action=args.remote_action,
        execute=args.execute,
        timeout_seconds=args.timeout,
        prerequisite_wait_timeout_seconds=args.prerequisite_wait_timeout,
        prerequisite_poll_interval_seconds=args.prerequisite_poll_interval,
        full_wait_timeout_seconds=args.full_wait_timeout,
        full_poll_interval_seconds=args.full_poll_interval,
        artifact_suffix=args.artifact_suffix,
        proof_package_path=args.proof_package,
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "execution_provider": payload["execution_provider"],
                "execute": payload["execute"],
                "passed": payload["passed"],
                "remote_action": payload["remote_action"],
                "prerequisite_bundle_mode": payload["prerequisite_bundle_mode"],
                "remote_host": payload["remote_host"],
                "aws_command_scan_passed": payload["aws_command_scan"]["passed"],
                "runbook_validation_passed": payload["runbook_validation"]["passed"],
                "launchable_proof_package_required": payload[
                    "launchable_proof_package_required"
                ],
                "proof_package_validation_passed": payload["proof_package_validation"]["passed"],
                "fast_runtime_proven_for_every_possible_state": payload[
                    "fast_runtime_proven_for_every_possible_state"
                ],
            },
            indent=2,
        )
    )
    return 0 if payload["passed"] or not args.execute else 1


if __name__ == "__main__":
    raise SystemExit(main())

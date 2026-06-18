#!/usr/bin/env python
"""Evaluate cloud hard-tail campaign workload artifacts."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rubik_optimal.tables.h48 import canonical_h48_solver, estimated_h48_table_size_bytes  # noqa: E402
from scripts.experimental.run_cloud_hardtail_workload import (  # noqa: E402
    select_reusable_workload_result,
    validate_workload_artifact_integrity,
    validate_workload_result_fingerprints,
    workload_result_candidates,
)


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)


def _relative(root: Path, path: Path) -> str:
    return str(path.relative_to(root)) if path.is_relative_to(root) else str(path)


def _latest_workload_result(root: Path, *, plan_stem: str, workload_id: str) -> tuple[Path, dict[str, Any]] | None:
    candidates = workload_result_candidates(
        root,
        plan_stem=plan_stem,
        workload_id=workload_id,
    )
    return candidates[0] if candidates else None


def _artifact_payloads(root: Path, result: dict[str, Any]) -> list[tuple[str, dict[str, Any] | None]]:
    payloads: list[tuple[str, dict[str, Any] | None]] = []
    for summary in result.get("artifact_summaries", []):
        if not isinstance(summary, dict) or not summary.get("path"):
            continue
        path = root / str(summary["path"])
        payloads.append((str(summary["path"]), _load_json(path)))
    return payloads


def _rows_exact_verified(rows: Any) -> bool:
    return isinstance(rows, list) and bool(rows) and all(
        isinstance(row, dict)
        and row.get("status") == "exact"
        and row.get("verified") is True
        for row in rows
    )


def _command_arg_value(command_args: list[Any], flag: str) -> str | None:
    parts = [str(part) for part in command_args]
    try:
        index = parts.index(flag)
    except ValueError:
        return None
    if index + 1 >= len(parts):
        return None
    return parts[index + 1]


def _expected_batch_size(workload: dict[str, Any]) -> int | None:
    raw = _command_arg_value(list(workload.get("command_args", [])), "--benchmark-limit-per-distance")
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _expected_distance(plan: dict[str, Any], workload: dict[str, Any]) -> int | None:
    raw = _command_arg_value(list(workload.get("command_args", [])), "--benchmark-distance")
    if raw is None:
        raw = plan.get("distance")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _target_solver(plan: dict[str, Any]) -> str | None:
    try:
        return canonical_h48_solver(str(plan.get("solver", "")))
    except ValueError:
        return None


def _canonical_solver_or_none(value: Any) -> str | None:
    try:
        return canonical_h48_solver(str(value))
    except (TypeError, ValueError):
        return None


def _payload_solver_matches(payload: dict[str, Any], target_solver: str | None) -> bool:
    if target_solver is None:
        return False
    try:
        payload_solver = canonical_h48_solver(str(payload.get("solver", "")))
    except ValueError:
        return False
    return payload_solver == target_solver


def _payload_target_solver_matches(payload: dict[str, Any], target_solver: str | None) -> bool:
    if target_solver is None:
        return False
    try:
        payload_target_solver = canonical_h48_solver(str(payload.get("target_solver", "")))
    except ValueError:
        return False
    return payload_target_solver == target_solver


def _h48_stronger_dependency_solver(
    plan: dict[str, Any],
    dependency_id: str,
) -> str | None:
    for dependency in plan.get("workloads", []):
        if not isinstance(dependency, dict) or str(dependency.get("id")) != dependency_id:
            continue
        if dependency.get("kind") != "h48_stronger_table_generation_and_certification":
            return None
        target = (
            _command_arg_value(list(dependency.get("command_args", [])), "--target-solver")
            or dependency_id.removeprefix("stronger_table_")
        )
        try:
            return canonical_h48_solver(str(target))
        except ValueError:
            return None
    return None


def _h48_dependency_validation(
    result: dict[str, Any],
    *,
    plan: dict[str, Any],
    workload: dict[str, Any],
) -> dict[str, Any]:
    """Require worker-side full-checksum H48 dependency evidence before hard-tail search counts."""

    required_dependencies: list[dict[str, Any]] = []
    for dependency_id in [str(value) for value in workload.get("depends_on_workload_ids", [])]:
        solver = _h48_stronger_dependency_solver(plan, dependency_id)
        if solver is not None:
            required_dependencies.append({"dependency_id": dependency_id, "solver": solver})
    if not required_dependencies:
        return {
            "required": False,
            "passed": True,
            "required_dependencies": [],
            "checks": [],
            "reasons": [],
        }

    checks = result.get("h48_trusted_dependency_checks")
    if not isinstance(checks, list) or not checks:
        return {
            "required": True,
            "passed": False,
            "required_dependencies": required_dependencies,
            "checks": checks if isinstance(checks, list) else [],
            "reasons": ["missing h48_trusted_dependency_checks in workload result"],
        }

    reasons: list[str] = []
    for dependency in required_dependencies:
        dependency_id = str(dependency["dependency_id"])
        expected_solver = str(dependency["solver"])
        matching = [
            check
            for check in checks
            if isinstance(check, dict) and str(check.get("dependency_id")) == dependency_id
        ]
        if not matching:
            reasons.append(f"missing trusted-table check for dependency {dependency_id}")
            continue
        check = matching[-1]
        actual_solver = _canonical_solver_or_none(check.get("solver"))
        if actual_solver != expected_solver:
            reasons.append(
                f"trusted-table check for {dependency_id} used solver {actual_solver}, expected {expected_solver}"
            )
        if check.get("profile") != plan.get("profile"):
            reasons.append(f"trusted-table check for {dependency_id} used wrong profile")
        if check.get("seed") != plan.get("seed"):
            reasons.append(f"trusted-table check for {dependency_id} used wrong seed")
        if check.get("passed") is not True:
            reasons.append(f"trusted-table check for {dependency_id} did not pass")
        if check.get("trusted_metadata_valid") is not True:
            reasons.append(f"trusted metadata check for {dependency_id} did not pass")
        if check.get("full_checksum_valid") is not True:
            reasons.append(f"full checksum check for {dependency_id} did not pass")

    return {
        "required": True,
        "passed": not reasons,
        "required_dependencies": required_dependencies,
        "checks": checks,
        "reasons": reasons,
    }


def _evaluate_hardtail_artifact(
    payload: dict[str, Any] | None,
    *,
    plan: dict[str, Any],
    workload: dict[str, Any],
) -> bool:
    if not payload or payload.get("passed") is not True:
        return False
    target_solver = _target_solver(plan)
    if not _payload_solver_matches(payload, target_solver):
        return False
    if payload.get("trusted_table") is not True:
        return False
    if int(payload.get("failed_offset_count", 0) or 0) != 0:
        return False
    expected_distance = _expected_distance(plan, workload)
    rows = payload.get("rows")
    return isinstance(rows, list) and bool(rows) and all(
        isinstance(row, dict)
        and row.get("sweep_status") in {"ran_passed", "skipped_existing_passed"}
        and row.get("status") == "exact"
        and row.get("verified") is True
        and (expected_distance is None or row.get("expected_distance") == expected_distance)
        and row.get("source_sequence_provided_to_solver") is not True
        for row in rows
    )


def _evaluate_hardtail_batch_artifact(
    payload: dict[str, Any] | None,
    *,
    plan: dict[str, Any],
    workload: dict[str, Any],
) -> bool:
    if not payload or payload.get("passed") is not True:
        return False
    target_solver = _target_solver(plan)
    if not _payload_solver_matches(payload, target_solver):
        return False
    if payload.get("trusted_table") is not True:
        return False
    if payload.get("all_exact") is not True or payload.get("all_verified") is not True:
        return False
    if payload.get("all_expected_distances_match") is not True:
        return False
    if payload.get("try_certificate_cache") is not False:
        return False
    if plan.get("hardtail_strategy") == "native-h48-only":
        if payload.get("try_upper_lower_certificate") is not False:
            return False
        if payload.get("live_solver_shortcuts_disabled") is not True:
            return False
        if payload.get("require_resident_h48_batch_for_all") is not True:
            return False
        if payload.get("resident_h48_batch_all_rows") is not True:
            return False
    rows = payload.get("rows")
    expected_count = _expected_batch_size(workload)
    expected_distance = _expected_distance(plan, workload)
    if not isinstance(rows, list):
        return False
    if expected_count is not None and len(rows) != expected_count:
        return False
    return bool(rows) and all(
        isinstance(row, dict)
        and row.get("case_kind") == "nissy_core_benchmark_known_distance"
        and row.get("status") == "exact"
        and row.get("verified") is True
        and (
            plan.get("hardtail_strategy") != "native-h48-only"
            or row.get("selected_backend") == "resident-h48-batch"
        )
        and (expected_distance is None or row.get("expected_distance") == expected_distance)
        and (expected_distance is None or row.get("solution_length") == expected_distance)
        and row.get("source_sequence_provided_to_solver") is not True
        for row in rows
    )


def _evaluate_stronger_table_artifact(payload: dict[str, Any] | None, *, plan: dict[str, Any]) -> bool:
    if not payload:
        return False
    target_solver = _target_solver(plan)
    if target_solver is None:
        return False
    if not _payload_target_solver_matches(payload, target_solver):
        return False
    if payload.get("target_estimated_table_size_bytes") != estimated_h48_table_size_bytes(target_solver):
        return False
    return (
        payload.get("passed") is True
        and payload.get("post_campaign_target_trusted_table") is True
        and payload.get("post_campaign_full_checksum_valid") is True
        and payload.get("status") in {"target_table_already_trusted", "generated_and_certified"}
    )


def _evaluate_rubikoptimal_artifact(payload: dict[str, Any] | None) -> bool:
    if not payload:
        return False
    rows = payload.get("rows")
    return (
        payload.get("passed") is True
        and payload.get("all_exact") is True
        and payload.get("all_verified") is True
        and _rows_exact_verified(rows)
        and any(
            isinstance(row, dict)
            and row.get("case_id") == "superflip_distance_20"
            and row.get("expected_distance") == 20
            and row.get("solution_length") == 20
            for row in rows
        )
    )


def _evaluate_contract_artifact(payload: dict[str, Any] | None) -> dict[str, bool]:
    if not payload:
        return {
            "contract_present": False,
            "all_state_exact_contract_supported": False,
            "fast_optimal_oracle_implemented_for_every_valid_3x3_state": False,
            "fast_runtime_proven_for_every_possible_state": False,
        }
    return {
        "contract_present": True,
        "all_state_exact_contract_supported": payload.get("all_state_exact_contract_supported") is True,
        "fast_optimal_oracle_implemented_for_every_valid_3x3_state": (
            payload.get("fast_optimal_oracle_implemented_for_every_valid_3x3_state") is True
        ),
        "fast_runtime_proven_for_every_possible_state": (
            payload.get("fast_runtime_proven_for_every_possible_state") is True
        ),
    }


def _evaluate_workload(
    root: Path,
    plan: dict[str, Any],
    workload: dict[str, Any],
    result: dict[str, Any] | None,
) -> dict[str, Any]:
    if result is None:
        return {
            "workload_id": workload.get("id"),
            "kind": workload.get("kind"),
            "required": bool(workload.get("required_for_fast_every_state_claim", True)),
            "result_present": False,
            "passed": False,
            "reason": "missing workload execution artifact",
        }
    fingerprint_validation = validate_workload_result_fingerprints(
        result,
        plan=plan,
        workload=workload,
    )
    if fingerprint_validation.get("passed") is not True:
        return {
            "workload_id": workload.get("id"),
            "kind": workload.get("kind"),
            "required": bool(workload.get("required_for_fast_every_state_claim", True)),
            "result_present": True,
            "result_path": result.get("_result_path"),
            "passed": False,
            "fingerprint_validation": fingerprint_validation,
            "reason": "workload result does not match the current plan/workload fingerprint",
        }
    if result.get("blocked_by_missing_dependencies") is True:
        return {
            "workload_id": workload.get("id"),
            "kind": workload.get("kind"),
            "required": bool(workload.get("required_for_fast_every_state_claim", True)),
            "result_present": True,
            "passed": False,
            "reason": "workload was blocked before execution because dependency artifacts were missing",
        }
    if result.get("executed") is not True or result.get("passed") is not True:
        return {
            "workload_id": workload.get("id"),
            "kind": workload.get("kind"),
            "required": bool(workload.get("required_for_fast_every_state_claim", True)),
            "result_present": True,
            "passed": False,
            "reason": "workload result was not an executed passing command",
        }

    h48_dependency_validation = _h48_dependency_validation(result, plan=plan, workload=workload)
    if h48_dependency_validation.get("passed") is not True:
        return {
            "workload_id": workload.get("id"),
            "kind": workload.get("kind"),
            "required": bool(workload.get("required_for_fast_every_state_claim", True)),
            "result_present": True,
            "result_path": result.get("_result_path"),
            "passed": False,
            "h48_dependency_validation": h48_dependency_validation,
            "reason": "workload did not prove trusted H48 dependency validation before search",
        }

    artifact_integrity_validation = validate_workload_artifact_integrity(root, result)
    if artifact_integrity_validation.get("passed") is not True:
        return {
            "workload_id": workload.get("id"),
            "kind": workload.get("kind"),
            "required": bool(workload.get("required_for_fast_every_state_claim", True)),
            "result_present": True,
            "result_path": result.get("_result_path"),
            "passed": False,
            "fingerprint_validation": fingerprint_validation,
            "h48_dependency_validation": h48_dependency_validation,
            "artifact_integrity_validation": artifact_integrity_validation,
            "reason": "workload artifact content no longer matches recorded fingerprint",
        }

    artifact_payloads = _artifact_payloads(root, result)
    kind = str(workload.get("kind"))
    if kind == "public_known_distance_hardtail_sweep":
        artifact_passed = bool(artifact_payloads) and all(
            _evaluate_hardtail_artifact(payload, plan=plan, workload=workload)
            for _path, payload in artifact_payloads
        )
    elif kind == "public_known_distance_hardtail_batch":
        artifact_passed = bool(artifact_payloads) and all(
            _evaluate_hardtail_batch_artifact(payload, plan=plan, workload=workload)
            for _path, payload in artifact_payloads
        )
    elif kind == "h48_stronger_table_generation_and_certification":
        artifact_passed = bool(artifact_payloads) and any(
            _evaluate_stronger_table_artifact(payload, plan=plan) for _path, payload in artifact_payloads
        )
    elif kind == "rubikoptimal_table_complete_hardcase":
        artifact_passed = bool(artifact_payloads) and all(
            _evaluate_rubikoptimal_artifact(payload) for _path, payload in artifact_payloads
        )
    elif kind == "postprocess_and_audit":
        artifact_passed = True
    else:
        artifact_passed = result.get("expected_artifacts_found") is True

    return {
        "workload_id": workload.get("id"),
        "kind": kind,
        "required": bool(workload.get("required_for_fast_every_state_claim", True)),
        "result_present": True,
        "result_path": result.get("_result_path"),
        "matched_artifact_paths": [path for path, _payload in artifact_payloads],
        "fingerprint_validation": fingerprint_validation,
        "h48_dependency_validation": h48_dependency_validation,
        "artifact_integrity_validation": artifact_integrity_validation,
        "passed": artifact_passed,
        "reason": "passed" if artifact_passed else "expected workload artifacts did not prove the required condition",
    }


def _required_artifact_integrity_summary(
    plan: dict[str, Any],
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    workloads_by_id = {
        str(workload.get("id")): workload
        for workload in plan.get("workloads", [])
        if isinstance(workload, dict) and workload.get("id") is not None
    }
    required_rows = [row for row in rows if row.get("required") is True]
    checks: list[dict[str, Any]] = []
    for row in required_rows:
        workload_id = str(row.get("workload_id"))
        workload = workloads_by_id.get(workload_id, {})
        expected_artifacts = [
            str(pattern) for pattern in workload.get("expected_artifacts", []) if str(pattern)
        ]
        if not expected_artifacts:
            continue
        validation = row.get("artifact_integrity_validation")
        passed = (
            isinstance(validation, dict)
            and validation.get("required") is True
            and validation.get("passed") is True
        )
        checks.append(
            {
                "workload_id": workload_id,
                "expected_artifact_count": len(expected_artifacts),
                "artifact_integrity_validation_required": (
                    validation.get("required") if isinstance(validation, dict) else None
                ),
                "artifact_integrity_validation_passed": (
                    validation.get("passed") if isinstance(validation, dict) else None
                ),
                "passed": passed,
            }
        )
    return {
        "required_artifact_workload_count": len(checks),
        "passed_artifact_workload_count": sum(1 for check in checks if check["passed"] is True),
        "all_required_artifact_integrity_passed": all(check["passed"] is True for check in checks),
        "checks": checks,
    }


def evaluate_campaign(*, root: Path, plan_path: Path) -> dict[str, Any]:
    plan = _load_json(plan_path)
    if plan is None:
        raise SystemExit(f"cannot read plan JSON: {plan_path}")
    plan_stem = plan_path.stem
    rows: list[dict[str, Any]] = []
    for workload in plan.get("workloads", []):
        workload_id = str(workload.get("id"))
        reusable = select_reusable_workload_result(
            root,
            plan_stem=plan_stem,
            workload_id=workload_id,
            plan=plan,
            workload=workload,
        )
        latest = (
            _latest_workload_result(root, plan_stem=plan_stem, workload_id=workload_id)
            if reusable is None
            else None
        )
        result_payload: dict[str, Any] | None = None
        ignored_results: list[dict[str, Any]] = []
        if reusable is not None:
            result_path, result_payload, _fingerprint_validation, ignored_results = reusable
            result_payload = {
                **result_payload,
                "_result_path": _relative(root, result_path),
                "_ignored_newer_result_count": len(ignored_results),
                "_ignored_newer_results": ignored_results,
            }
        elif latest is not None:
            result_path, result_payload = latest
            result_payload = {**result_payload, "_result_path": _relative(root, result_path)}
        row = _evaluate_workload(root, plan, workload, result_payload)
        if ignored_results:
            row["ignored_newer_result_count"] = len(ignored_results)
            row["ignored_newer_results"] = ignored_results
        rows.append(row)

    required_rows = [row for row in rows if row["required"]]
    all_required_workloads_passed = bool(required_rows) and all(row["passed"] is True for row in required_rows)
    artifact_integrity_summary = _required_artifact_integrity_summary(plan, rows)
    all_required_artifact_integrity_passed = (
        artifact_integrity_summary["all_required_artifact_integrity_passed"] is True
    )
    contract_path = root / "results" / "processed" / f"h48_oracle_contract_seed_{plan.get('seed')}_{plan.get('profile')}_{plan.get('solver')}.json"
    contract_checks = _evaluate_contract_artifact(_load_json(contract_path))
    thesis_audit_payload = _load_json(root / "results" / "processed" / "thesis_audit.json")
    thesis_audit_passed = bool(thesis_audit_payload) and all(
        thesis_audit_payload.get(key) is True
        for key in [
            "acceptance_implementation_passed",
            "acceptance_repository_passed",
            "acceptance_research_passed",
            "acceptance_scale_passed",
        ]
    )
    return {
        "schema_version": 1,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "plan_path": _relative(root, plan_path),
        "plan_objective": plan.get("objective"),
        "plan_claim_scope": plan.get("claim_scope", "full"),
        "plan_profile": plan.get("profile"),
        "plan_seed": plan.get("seed"),
        "plan_solver": plan.get("solver"),
        "plan_distance": plan.get("distance"),
        "plan_selected_offset_start": plan.get("selected_offset_start"),
        "plan_selected_offset_end": plan.get("selected_offset_end"),
        "plan_available_scramble_rows": plan.get("available_scramble_rows"),
        "workload_count": len(plan.get("workloads", [])),
        "evaluated_workload_count": len(rows),
        "all_required_workloads_passed": all_required_workloads_passed,
        "artifact_integrity_required_workload_count": artifact_integrity_summary[
            "required_artifact_workload_count"
        ],
        "artifact_integrity_passed_workload_count": artifact_integrity_summary[
            "passed_artifact_workload_count"
        ],
        "all_required_artifact_integrity_passed": all_required_artifact_integrity_passed,
        "artifact_integrity_checks": artifact_integrity_summary["checks"],
        "cloud_runtime_evidence_passed": (
            all_required_workloads_passed and all_required_artifact_integrity_passed
        ),
        "contract_checks": contract_checks,
        "thesis_audit_acceptance_gates_passed": thesis_audit_passed,
        "fast_runtime_proven_for_every_possible_state": (
            all_required_workloads_passed
            and all_required_artifact_integrity_passed
            and contract_checks["fast_runtime_proven_for_every_possible_state"]
            and thesis_audit_passed
        ),
        "rows": rows,
        "missing_or_failed_workloads": [
            row["workload_id"] for row in rows if row["required"] and row["passed"] is not True
        ],
        "notes": (
            "This evaluator can only mark the final fast-runtime flag true after all cloud workload artifacts pass "
            "and the regenerated contract itself records fast_runtime_proven_for_every_possible_state=true."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output-suffix", default="")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()

    payload = evaluate_campaign(root=args.root, plan_path=args.plan)
    suffix = f"_{args.output_suffix}" if args.output_suffix else ""
    output = (
        args.root
        / "results"
        / "processed"
        / f"cloud_hardtail_campaign_evaluation_{_safe_id(args.plan.stem)}{suffix}.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(output),
                "all_required_workloads_passed": payload["all_required_workloads_passed"],
                "fast_runtime_proven_for_every_possible_state": payload[
                    "fast_runtime_proven_for_every_possible_state"
                ],
                "missing_or_failed_workloads": payload["missing_or_failed_workloads"],
            },
            indent=2,
        )
    )
    return 0 if payload["all_required_workloads_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

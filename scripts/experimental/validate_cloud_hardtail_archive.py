#!/usr/bin/env python
"""Validate fetched cloud hard-tail result archives before local finalization."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rubik_optimal.results import write_json  # noqa: E402
from scripts.experimental.run_cloud_hardtail_workload import fingerprint_json  # noqa: E402


def _safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _relative(root: Path, path: Path) -> str:
    return str(path.relative_to(root)) if path.is_relative_to(root) else str(path)


def _resolve(root: Path, path: str | Path | None) -> Path | None:
    if path is None:
        return None
    candidate = Path(path)
    return candidate if candidate.is_absolute() else root / candidate


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stream_sha256(handle: Any) -> str:
    digest = hashlib.sha256()
    for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def _normal_member_name(name: str) -> str:
    return name.lstrip("./")


def _unsafe_member_name(name: str) -> bool:
    parts = name.replace("\\", "/").split("/")
    return name.startswith("/") or any(part == ".." for part in parts)


def _archive_members(
    archive: Path,
) -> tuple[list[str], list[str], dict[str, dict[str, Any]], list[dict[str, Any]]]:
    unsafe: list[str] = []
    json_payloads: dict[str, dict[str, Any]] = {}
    json_errors: list[dict[str, Any]] = []
    with tarfile.open(archive, "r:gz") as tar:
        members = []
        for member in tar.getmembers():
            name = _normal_member_name(member.name)
            if _unsafe_member_name(member.name):
                unsafe.append(member.name)
            members.append(name)
            if not member.isfile() or not name.endswith(".json"):
                continue
            handle = tar.extractfile(member)
            if handle is None:
                json_errors.append({"member": name, "reason": "cannot open member"})
                continue
            try:
                payload = json.loads(handle.read().decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                json_errors.append({"member": name, "reason": str(exc)})
                continue
            if isinstance(payload, dict):
                json_payloads[name] = payload
            else:
                json_errors.append({"member": name, "reason": "JSON payload is not an object"})
    return sorted(set(members)), unsafe, json_payloads, json_errors


def _archive_artifact_identities(
    archive: Path,
    artifact_paths: set[str],
) -> dict[str, dict[str, Any]]:
    identities: dict[str, dict[str, Any]] = {}
    if not artifact_paths:
        return identities
    targets = {_normal_member_name(path) for path in artifact_paths}
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar.getmembers():
            name = _normal_member_name(member.name)
            if name not in targets or not member.isfile():
                continue
            handle = tar.extractfile(member)
            if handle is None:
                continue
            identities[name] = {
                "source": "archive",
                "size_bytes": member.size,
                "sha256": _stream_sha256(handle),
            }
    return identities


def _has_prefix_match(members: set[str], prefix: str) -> bool:
    return any(member.startswith(prefix) and member.endswith(".json") for member in members)


def _json_candidates(
    json_payloads: dict[str, dict[str, Any]],
    prefix: str,
) -> list[dict[str, Any]]:
    return [
        {"member": member, "payload": payload}
        for member, payload in sorted(json_payloads.items())
        if member.startswith(prefix) and member.endswith(".json")
    ]


def _required_workloads(plan: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        workload
        for workload in plan.get("workloads", [])
        if isinstance(workload, dict)
        and workload.get("id")
        and workload.get("required_for_fast_every_state_claim", True) is True
    ]


def _expected_artifact_patterns(workload: dict[str, Any]) -> list[str]:
    return [str(pattern) for pattern in workload.get("expected_artifacts", []) if str(pattern)]


def _candidate_artifact_paths(payload: dict[str, Any]) -> set[str]:
    paths: set[str] = set()
    summaries = payload.get("artifact_summaries", [])
    if isinstance(summaries, list):
        for summary in summaries:
            if isinstance(summary, dict) and summary.get("path"):
                paths.add(_normal_member_name(str(summary["path"])))
    matched = payload.get("matched_artifacts_by_pattern")
    if isinstance(matched, dict):
        for values in matched.values():
            if isinstance(values, list):
                paths.update(_normal_member_name(str(value)) for value in values if str(value))
    return paths


def _local_artifact_identity(root: Path, relpath: str) -> dict[str, Any] | None:
    path = root / relpath
    if not path.exists() or not path.is_file():
        return None
    return {
        "source": "local_root",
        "size_bytes": path.stat().st_size,
        "sha256": _file_sha256(path),
    }


def _artifact_identity_for_path(
    *,
    root: Path,
    archive_identities: dict[str, dict[str, Any]],
    relpath: str,
) -> dict[str, Any] | None:
    normal = _normal_member_name(relpath)
    if normal in archive_identities:
        return archive_identities[normal]
    return _local_artifact_identity(root, normal)


def _validate_candidate_artifacts(
    *,
    root: Path,
    archive_identities: dict[str, dict[str, Any]],
    payload: dict[str, Any],
    workload: dict[str, Any],
) -> dict[str, Any]:
    reasons: list[str] = []
    checks: list[dict[str, Any]] = []
    expected_patterns = _expected_artifact_patterns(workload)
    matched = payload.get("matched_artifacts_by_pattern")
    if expected_patterns:
        if payload.get("expected_artifacts_found") is not True:
            reasons.append("expected artifacts were not found by workload runner")
        if not isinstance(matched, dict):
            reasons.append("missing matched_artifacts_by_pattern")
        else:
            for pattern in expected_patterns:
                values = matched.get(pattern)
                if not isinstance(values, list) or not values:
                    reasons.append(f"missing matched artifact for expected pattern {pattern}")

    summaries_by_path: dict[str, dict[str, Any]] = {}
    summaries = payload.get("artifact_summaries", [])
    if isinstance(summaries, list):
        for summary in summaries:
            if isinstance(summary, dict) and summary.get("path"):
                summaries_by_path[_normal_member_name(str(summary["path"]))] = summary
    elif expected_patterns:
        reasons.append("artifact_summaries is not a list")

    matched_paths = _candidate_artifact_paths(payload)
    if expected_patterns and not matched_paths:
        reasons.append("no artifact paths recorded for expected artifact workload")

    for relpath in sorted(matched_paths):
        summary = summaries_by_path.get(relpath)
        check: dict[str, Any] = {"path": relpath}
        if summary is None:
            check["passed"] = False
            check["reason"] = "artifact path has no summary"
            reasons.append(f"artifact {relpath} has no summary")
            checks.append(check)
            continue
        expected_size = summary.get("size_bytes")
        expected_sha = summary.get("sha256")
        check["recorded_size_bytes"] = expected_size
        check["recorded_sha256"] = expected_sha
        if expected_size is None or not expected_sha:
            check["passed"] = False
            check["reason"] = "artifact summary missing size or sha256"
            reasons.append(f"artifact {relpath} summary is missing size or sha256")
            checks.append(check)
            continue
        identity = _artifact_identity_for_path(
            root=root,
            archive_identities=archive_identities,
            relpath=relpath,
        )
        if identity is None:
            check["passed"] = False
            check["reason"] = "artifact missing from archive and local root"
            reasons.append(f"artifact {relpath} is missing from archive and local root")
            checks.append(check)
            continue
        check.update(
            {
                "source": identity["source"],
                "current_size_bytes": identity["size_bytes"],
                "current_sha256": identity["sha256"],
            }
        )
        if identity["size_bytes"] != expected_size:
            check["passed"] = False
            check["reason"] = "artifact size mismatch"
            reasons.append(f"artifact {relpath} size mismatch")
        elif identity["sha256"] != expected_sha:
            check["passed"] = False
            check["reason"] = "artifact sha256 mismatch"
            reasons.append(f"artifact {relpath} sha256 mismatch")
        else:
            check["passed"] = True
            check["reason"] = "passed"
        checks.append(check)

    return {
        "required": bool(expected_patterns),
        "passed": not reasons,
        "expected_artifact_patterns": expected_patterns,
        "check_count": len(checks),
        "checks": checks,
        "reasons": reasons,
    }


def _validate_workload_candidate(
    *,
    root: Path,
    archive_identities: dict[str, dict[str, Any]],
    plan: dict[str, Any],
    workload: dict[str, Any],
    member: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    reasons: list[str] = []
    expected_plan_fingerprint = fingerprint_json(plan)
    expected_workload_fingerprint = fingerprint_json(workload)
    if str(payload.get("workload_id")) != str(workload.get("id")):
        reasons.append("workload id mismatch")
    if payload.get("fingerprint_algorithm") != "sha256-canonical-json-v1":
        reasons.append("missing current fingerprint algorithm")
    if payload.get("plan_fingerprint") != expected_plan_fingerprint:
        reasons.append("plan fingerprint mismatch")
    if payload.get("workload_fingerprint") != expected_workload_fingerprint:
        reasons.append("workload fingerprint mismatch")
    if payload.get("executed") is not True:
        reasons.append("workload did not execute")
    if payload.get("dry_run") is not False:
        reasons.append("workload result is a dry run")
    if payload.get("passed") is not True:
        reasons.append("workload result did not pass")
    if payload.get("required_for_fast_every_state_claim") is not True:
        reasons.append("workload result is not marked required for the fast every-state claim")

    artifact_validation = _validate_candidate_artifacts(
        root=root,
        archive_identities=archive_identities,
        payload=payload,
        workload=workload,
    )
    if artifact_validation.get("passed") is not True:
        reasons.append("workload artifact summaries do not match archive/local artifact bytes")

    return {
        "member": member,
        "passed": not reasons,
        "executed": payload.get("executed"),
        "dry_run": payload.get("dry_run"),
        "result_passed": payload.get("passed"),
        "expected_plan_fingerprint": expected_plan_fingerprint,
        "actual_plan_fingerprint": payload.get("plan_fingerprint"),
        "expected_workload_fingerprint": expected_workload_fingerprint,
        "actual_workload_fingerprint": payload.get("workload_fingerprint"),
        "artifact_validation": artifact_validation,
        "reasons": reasons,
    }


def _validate_workload_payloads(
    *,
    root: Path,
    archive_identities: dict[str, dict[str, Any]],
    json_payloads: dict[str, dict[str, Any]],
    plan: dict[str, Any],
    plan_stem: str,
    required_workloads: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for workload in required_workloads:
        workload_id = str(workload["id"])
        prefix = (
            "results/processed/"
            f"cloud_hardtail_workload_{_safe_id(plan_stem)}_{_safe_id(workload_id)}"
        )
        candidates = []
        for candidate in _json_candidates(json_payloads, prefix):
            candidates.append(
                _validate_workload_candidate(
                    root=root,
                    archive_identities=archive_identities,
                    plan=plan,
                    workload=workload,
                    member=str(candidate["member"]),
                    payload=candidate["payload"],
                )
            )
        checks.append(
            {
                "workload_id": workload_id,
                "kind": workload.get("kind"),
                "candidate_count": len(candidates),
                "passed": any(candidate["passed"] is True for candidate in candidates),
                "candidates": candidates,
            }
        )
    return checks


def _evaluation_candidate_check(
    *,
    plan: dict[str, Any],
    plan_path: Path,
    plan_relative: str | None,
    required_workloads: list[dict[str, Any]],
    member: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    reasons: list[str] = []
    expected_claim_scope = plan.get("claim_scope", "full")
    expected_workload_count = len(plan.get("workloads", []))
    if expected_claim_scope != "full":
        reasons.append("plan claim_scope is not full")
    if plan_relative is not None and payload.get("plan_path") != plan_relative:
        reasons.append("evaluation plan_path does not match runbook full_plan_path")
    expected_fields = {
        "plan_claim_scope": expected_claim_scope,
        "plan_profile": plan.get("profile"),
        "plan_seed": plan.get("seed"),
        "plan_solver": plan.get("solver"),
        "plan_distance": plan.get("distance"),
        "workload_count": expected_workload_count,
        "evaluated_workload_count": expected_workload_count,
    }
    for key, expected in expected_fields.items():
        if payload.get(key) != expected:
            reasons.append(f"evaluation {key} mismatch")
    if payload.get("all_required_workloads_passed") is not True:
        reasons.append("evaluation all_required_workloads_passed is not true")
    if payload.get("all_required_artifact_integrity_passed") is not True:
        reasons.append("evaluation all_required_artifact_integrity_passed is not true")
    if payload.get("cloud_runtime_evidence_passed") is not True:
        reasons.append("evaluation cloud_runtime_evidence_passed is not true")
    if payload.get("missing_or_failed_workloads") != []:
        reasons.append("evaluation records missing or failed workloads")

    required_artifact_count = sum(1 for workload in required_workloads if _expected_artifact_patterns(workload))
    artifact_required_count = payload.get("artifact_integrity_required_workload_count")
    artifact_passed_count = payload.get("artifact_integrity_passed_workload_count")
    if required_artifact_count and artifact_required_count != required_artifact_count:
        reasons.append("evaluation artifact_integrity_required_workload_count mismatch")
    if artifact_required_count != artifact_passed_count:
        reasons.append("evaluation artifact integrity passed count does not match required count")

    rows = payload.get("rows")
    rows_by_id: dict[str, dict[str, Any]] = {}
    if not isinstance(rows, list):
        reasons.append("evaluation rows is not a list")
    else:
        for row in rows:
            if isinstance(row, dict) and row.get("workload_id") is not None:
                rows_by_id[str(row["workload_id"])] = row
        for workload in required_workloads:
            workload_id = str(workload["id"])
            row = rows_by_id.get(workload_id)
            if row is None:
                reasons.append(f"evaluation is missing row for {workload_id}")
                continue
            if row.get("required") is not True:
                reasons.append(f"evaluation row for {workload_id} is not required")
            if row.get("passed") is not True:
                reasons.append(f"evaluation row for {workload_id} did not pass")

    return {
        "member": member,
        "passed": not reasons,
        "plan_path": payload.get("plan_path"),
        "expected_plan_path": plan_relative,
        "plan_stem": plan_path.stem,
        "all_required_workloads_passed": payload.get("all_required_workloads_passed"),
        "all_required_artifact_integrity_passed": payload.get(
            "all_required_artifact_integrity_passed"
        ),
        "cloud_runtime_evidence_passed": payload.get("cloud_runtime_evidence_passed"),
        "fast_runtime_proven_for_every_possible_state": payload.get(
            "fast_runtime_proven_for_every_possible_state"
        ),
        "reasons": reasons,
    }


def validate_archive(
    *,
    root: Path,
    runbook_path: Path,
    archive_path: Path,
) -> dict[str, Any]:
    root = root.resolve()
    runbook_path = runbook_path if runbook_path.is_absolute() else root / runbook_path
    archive_path = archive_path if archive_path.is_absolute() else root / archive_path
    runbook = _load_json(runbook_path)
    full_plan_path = _resolve(root, runbook.get("full_plan_path"))
    plan = _load_json(full_plan_path) if full_plan_path is not None and full_plan_path.exists() else None

    errors: list[str] = []
    json_payloads: dict[str, dict[str, Any]] = {}
    json_errors: list[dict[str, Any]] = []
    if not archive_path.exists():
        errors.append("archive does not exist")
        members: list[str] = []
        unsafe_members: list[str] = []
    elif archive_path.stat().st_size <= 0:
        errors.append("archive is empty")
        members = []
        unsafe_members = []
    else:
        try:
            members, unsafe_members, json_payloads, json_errors = _archive_members(archive_path)
        except (tarfile.TarError, OSError) as exc:
            errors.append(f"archive cannot be read: {exc}")
            members = []
            unsafe_members = []
    if unsafe_members:
        errors.append("archive contains unsafe member paths")
    if json_errors:
        errors.append("archive contains unreadable JSON members")

    required_patterns: list[dict[str, Any]] = []
    missing_patterns: list[dict[str, Any]] = []
    evaluation_candidates: list[dict[str, Any]] = []
    workload_payload_checks: list[dict[str, Any]] = []
    archive_artifact_path_count = 0
    member_set = set(members)
    if plan:
        plan_stem = full_plan_path.stem if full_plan_path is not None else ""
        required_workloads = _required_workloads(plan)
        evaluation_prefix = (
            f"results/processed/cloud_hardtail_campaign_evaluation_{_safe_id(plan_stem)}"
        )
        required_patterns.append(
            {
                "kind": "campaign_evaluation",
                "pattern": f"{evaluation_prefix}*.json",
                "present": _has_prefix_match(member_set, evaluation_prefix),
            }
        )
        plan_relative = _relative(root, full_plan_path) if full_plan_path is not None else None
        evaluation_candidates = [
            _evaluation_candidate_check(
                plan=plan,
                plan_path=full_plan_path,
                plan_relative=plan_relative,
                required_workloads=required_workloads,
                member=str(candidate["member"]),
                payload=candidate["payload"],
            )
            for candidate in _json_candidates(json_payloads, evaluation_prefix)
        ]
        for workload in plan.get("workloads", []):
            if not isinstance(workload, dict):
                continue
            if workload.get("required_for_fast_every_state_claim", True) is not True:
                continue
            workload_id = str(workload.get("id") or "")
            if not workload_id:
                continue
            prefix = (
                "results/processed/"
                f"cloud_hardtail_workload_{_safe_id(plan_stem)}_{_safe_id(workload_id)}"
            )
            required_patterns.append(
                {
                    "kind": "workload_result",
                    "workload_id": workload_id,
                    "pattern": f"{prefix}*.json",
                    "present": _has_prefix_match(member_set, prefix),
                }
            )
        candidate_artifact_paths: set[str] = set()
        for workload in required_workloads:
            workload_id = str(workload["id"])
            prefix = (
                "results/processed/"
                f"cloud_hardtail_workload_{_safe_id(plan_stem)}_{_safe_id(workload_id)}"
            )
            for candidate in _json_candidates(json_payloads, prefix):
                candidate_artifact_paths.update(_candidate_artifact_paths(candidate["payload"]))
        archive_artifact_path_count = len(candidate_artifact_paths)
        try:
            archive_identities = (
                _archive_artifact_identities(archive_path, candidate_artifact_paths)
                if archive_path.exists() and archive_path.stat().st_size > 0
                else {}
            )
        except (tarfile.TarError, OSError) as exc:
            errors.append(f"archive artifact content cannot be read: {exc}")
            archive_identities = {}
        workload_payload_checks = _validate_workload_payloads(
            root=root,
            archive_identities=archive_identities,
            json_payloads=json_payloads,
            plan=plan,
            plan_stem=plan_stem,
            required_workloads=required_workloads,
        )
    else:
        errors.append("runbook full_plan_path is missing or unreadable")

    missing_patterns = [item for item in required_patterns if item.get("present") is not True]
    if missing_patterns:
        errors.append("archive is missing required full-plan proof artifacts")
    evaluation_payload_valid = any(candidate["passed"] is True for candidate in evaluation_candidates)
    if plan and not evaluation_payload_valid:
        errors.append("archive campaign evaluation payload does not prove full-plan runtime evidence")
    workload_payload_passed_count = sum(
        1 for check in workload_payload_checks if check.get("passed") is True
    )
    workload_payload_missing_count = sum(
        1 for check in workload_payload_checks if int(check.get("candidate_count") or 0) == 0
    )
    if plan and any(check.get("passed") is not True for check in workload_payload_checks):
        errors.append("archive workload payloads do not match full-plan fingerprints or execution requirements")
    artifact_checks = [
        artifact_check
        for workload_check in workload_payload_checks
        for candidate in workload_check.get("candidates", [])
        for artifact_check in candidate.get("artifact_validation", {}).get("checks", [])
    ]
    archive_artifact_passed_count = sum(1 for check in artifact_checks if check.get("passed") is True)

    return {
        "schema_version": 1,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "runbook_path": _relative(root, runbook_path),
        "archive_path": _relative(root, archive_path),
        "full_plan_path": _relative(root, full_plan_path) if full_plan_path is not None else None,
        "archive_exists": archive_path.exists(),
        "archive_size_bytes": archive_path.stat().st_size if archive_path.exists() else None,
        "member_count": len(members),
        "unsafe_member_count": len(unsafe_members),
        "unsafe_members": unsafe_members,
        "json_member_count": len(json_payloads),
        "json_error_count": len(json_errors),
        "json_errors": json_errors,
        "required_pattern_count": len(required_patterns),
        "missing_required_pattern_count": len(missing_patterns),
        "required_patterns": required_patterns,
        "missing_required_patterns": missing_patterns,
        "evaluation_candidate_count": len(evaluation_candidates),
        "evaluation_payload_valid": evaluation_payload_valid,
        "evaluation_candidates": evaluation_candidates,
        "workload_payload_check_count": len(workload_payload_checks),
        "workload_payload_passed_count": workload_payload_passed_count,
        "workload_payload_missing_count": workload_payload_missing_count,
        "workload_payload_checks": workload_payload_checks,
        "archive_artifact_path_count": archive_artifact_path_count,
        "archive_artifact_check_count": len(artifact_checks),
        "archive_artifact_passed_count": archive_artifact_passed_count,
        "passed": not errors,
        "errors": errors,
        "notes": (
            "This is a payload-level pre-finalization check for fetched cloud hard-tail "
            "archives. It validates full-plan evaluation fields, required workload "
            "execution payloads, plan/workload fingerprints, and recorded artifact "
            "bytes when the artifacts are present in the archive or already installed "
            "locally. It does not prove runtime success by itself; the final H48 oracle "
            "contract still has to pass after unpack/finalization."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runbook", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--artifact-suffix", default="remote")
    args = parser.parse_args()

    payload = validate_archive(
        root=args.root,
        runbook_path=args.runbook,
        archive_path=args.archive,
    )
    suffix = f"_{_safe_id(args.artifact_suffix)}" if args.artifact_suffix else ""
    output = (
        args.root
        / "results"
        / "processed"
        / f"cloud_hardtail_archive_validation{suffix}.json"
    )
    write_json(output, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

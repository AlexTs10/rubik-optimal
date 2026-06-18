#!/usr/bin/env python
"""Execute one workload from a cloud hard-tail campaign plan."""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rubik_optimal.results import write_json  # noqa: E402
from rubik_optimal.runtime import run_process_tree  # noqa: E402
from rubik_optimal.tables.h48 import canonical_h48_solver, validate_trusted_h48_table_checksum  # noqa: E402

ARTIFACT_INTEGRITY_ALGORITHM = "sha256-size-v1"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def fingerprint_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def validate_workload_result_fingerprints(
    result: dict[str, Any],
    *,
    plan: dict[str, Any],
    workload: dict[str, Any],
) -> dict[str, Any]:
    expected_plan_fingerprint = fingerprint_json(plan)
    expected_workload_fingerprint = fingerprint_json(workload)
    actual_plan_fingerprint = result.get("plan_fingerprint")
    actual_workload_fingerprint = result.get("workload_fingerprint")
    workload_id_matches = str(result.get("workload_id")) == str(workload.get("id"))
    passed = (
        actual_plan_fingerprint == expected_plan_fingerprint
        and actual_workload_fingerprint == expected_workload_fingerprint
        and workload_id_matches
    )
    reasons: list[str] = []
    if actual_plan_fingerprint != expected_plan_fingerprint:
        reasons.append("plan fingerprint mismatch")
    if actual_workload_fingerprint != expected_workload_fingerprint:
        reasons.append("workload fingerprint mismatch")
    if not workload_id_matches:
        reasons.append("workload id mismatch")
    return {
        "passed": passed,
        "algorithm": "sha256-canonical-json-v1",
        "expected_plan_fingerprint": expected_plan_fingerprint,
        "actual_plan_fingerprint": actual_plan_fingerprint,
        "expected_workload_fingerprint": expected_workload_fingerprint,
        "actual_workload_fingerprint": actual_workload_fingerprint,
        "workload_id_matches": workload_id_matches,
        "reasons": reasons,
    }


def _find_workload(plan: dict[str, Any], workload_id: str) -> dict[str, Any]:
    for workload in plan.get("workloads", []):
        if workload.get("id") == workload_id:
            return workload
    raise SystemExit(f"workload id not found in plan: {workload_id}")


def _workload_by_id(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(workload.get("id")): workload
        for workload in plan.get("workloads", [])
        if isinstance(workload, dict) and workload.get("id") is not None
    }


def _matching_artifacts(root: Path, patterns: list[str]) -> list[Path]:
    matches: list[Path] = []
    for pattern in patterns:
        raw_pattern = Path(pattern)
        glob_pattern = str(raw_pattern if raw_pattern.is_absolute() else root / pattern)
        matches.extend(Path(path) for path in glob.glob(glob_pattern))
    return sorted(set(matches))


def workload_result_candidates(
    root: Path,
    *,
    plan_stem: str,
    workload_id: str,
) -> list[tuple[Path, dict[str, Any]]]:
    pattern = f"cloud_hardtail_workload_{_safe_id(plan_stem)}_{_safe_id(workload_id)}*.json"
    candidates = sorted(
        (root / "results" / "processed").glob(pattern),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    rows: list[tuple[Path, dict[str, Any]]] = []
    for path in candidates:
        try:
            payload = _load_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        rows.append((path, payload))
    return rows


def _workload_result_reuse_rejection_reason(
    result: dict[str, Any],
    *,
    fingerprint_validation: dict[str, Any],
    artifact_integrity_validation: dict[str, Any],
) -> str:
    if fingerprint_validation.get("passed") is not True:
        return "fingerprint_mismatch"
    if artifact_integrity_validation.get("passed") is not True:
        return "artifact_integrity_mismatch"
    if result.get("passed") is not True:
        return "result_not_passed"
    if result.get("executed") is not True:
        return "result_not_executed"
    return "none"


def _ignored_workload_result_summary(
    root: Path,
    path: Path,
    result: dict[str, Any],
    *,
    plan: dict[str, Any],
    workload: dict[str, Any],
) -> dict[str, Any]:
    fingerprint_validation = validate_workload_result_fingerprints(
        result,
        plan=plan,
        workload=workload,
    )
    artifact_integrity_validation = validate_workload_artifact_integrity(root, result)
    return {
        "result_path": str(path.relative_to(root)) if path.is_relative_to(root) else str(path),
        "passed": result.get("passed"),
        "executed": result.get("executed"),
        "dry_run": result.get("dry_run"),
        "timed_out": result.get("timed_out"),
        "return_code": result.get("return_code"),
        "fingerprint_validation": fingerprint_validation,
        "artifact_integrity_validation": artifact_integrity_validation,
        "rejection_reason": _workload_result_reuse_rejection_reason(
            result,
            fingerprint_validation=fingerprint_validation,
            artifact_integrity_validation=artifact_integrity_validation,
        ),
    }


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_identity(root: Path, path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "path": str(path.relative_to(root)) if path.is_relative_to(root) else str(path),
        "size_bytes": stat.st_size,
        "sha256": _file_sha256(path),
        "modified_time_utc": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
    }


def validate_workload_artifact_integrity(root: Path, result: dict[str, Any]) -> dict[str, Any]:
    summaries = [summary for summary in result.get("artifact_summaries", []) if isinstance(summary, dict)]
    algorithm = result.get("artifact_integrity_algorithm")
    required = bool(summaries) and (
        algorithm == ARTIFACT_INTEGRITY_ALGORITHM
        or result.get("required_for_fast_every_state_claim") is True
    )
    if not required:
        return {
            "required": False,
            "passed": True,
            "algorithm": algorithm,
            "checks": [],
            "reasons": [],
        }

    checks: list[dict[str, Any]] = []
    reasons: list[str] = []
    if algorithm != ARTIFACT_INTEGRITY_ALGORITHM:
        reasons.append("missing current artifact integrity algorithm")

    for summary in summaries:
        relpath = summary.get("path")
        check: dict[str, Any] = {
            "path": relpath,
            "recorded_size_bytes": summary.get("size_bytes"),
            "recorded_sha256": summary.get("sha256"),
        }
        if not relpath:
            check["passed"] = False
            check["reason"] = "artifact summary missing path"
            reasons.append("artifact summary missing path")
            checks.append(check)
            continue
        if summary.get("size_bytes") is None or not summary.get("sha256"):
            check["passed"] = False
            check["reason"] = "artifact summary missing size or sha256"
            reasons.append(f"artifact {relpath} is missing recorded size or sha256")
            checks.append(check)
            continue
        path = root / str(relpath)
        if not path.exists():
            check["passed"] = False
            check["reason"] = "artifact file is missing"
            reasons.append(f"artifact {relpath} is missing")
            checks.append(check)
            continue
        current_size = path.stat().st_size
        check["current_size_bytes"] = current_size
        if current_size != summary.get("size_bytes"):
            check["passed"] = False
            check["reason"] = "artifact size changed"
            reasons.append(f"artifact {relpath} size changed")
            checks.append(check)
            continue
        current_sha = _file_sha256(path)
        check["current_sha256"] = current_sha
        if current_sha != summary.get("sha256"):
            check["passed"] = False
            check["reason"] = "artifact sha256 changed"
            reasons.append(f"artifact {relpath} sha256 changed")
            checks.append(check)
            continue
        check["passed"] = True
        check["reason"] = "passed"
        checks.append(check)

    return {
        "required": True,
        "passed": not reasons,
        "algorithm": ARTIFACT_INTEGRITY_ALGORITHM,
        "checks": checks,
        "reasons": reasons,
    }


def select_reusable_workload_result(
    root: Path,
    *,
    plan_stem: str,
    workload_id: str,
    plan: dict[str, Any],
    workload: dict[str, Any],
) -> tuple[Path, dict[str, Any], dict[str, Any], list[dict[str, Any]]] | None:
    ignored: list[dict[str, Any]] = []
    for path, payload in workload_result_candidates(
        root,
        plan_stem=plan_stem,
        workload_id=workload_id,
    ):
        fingerprint_validation = validate_workload_result_fingerprints(
            payload,
            plan=plan,
            workload=workload,
        )
        artifact_integrity_validation = validate_workload_artifact_integrity(root, payload)
        if (
            fingerprint_validation.get("passed") is True
            and artifact_integrity_validation.get("passed") is True
            and payload.get("passed") is True
            and payload.get("executed") is True
        ):
            return path, payload, fingerprint_validation, ignored
        ignored.append(
            _ignored_workload_result_summary(
                root,
                path,
                payload,
                plan=plan,
                workload=workload,
            )
        )
    return None


def _artifact_summary(root: Path, path: Path) -> dict[str, Any]:
    try:
        base = _artifact_identity(root, path)
    except OSError:
        base = {
            "path": str(path.relative_to(root)) if path.is_relative_to(root) else str(path),
        }
    try:
        payload = _load_json(path)
    except (OSError, json.JSONDecodeError):
        return {**base, "json_loadable": False}
    rows = payload.get("rows")
    return {
        **base,
        "json_loadable": True,
        "passed": payload.get("passed"),
        "status": payload.get("status"),
        "all_exact": payload.get("all_exact"),
        "all_verified": payload.get("all_verified"),
        "failed_offset_count": payload.get("failed_offset_count"),
        "completed_offset_count": payload.get("completed_offset_count"),
        "sweep_complete_for_selected_offsets": payload.get("sweep_complete_for_selected_offsets"),
        "fast_runtime_proven_for_every_possible_state": payload.get(
            "fast_runtime_proven_for_every_possible_state"
        ),
        "row_count": len(rows) if isinstance(rows, list) else None,
    }


def _dependency_checks(root: Path, plan: dict[str, Any], workload: dict[str, Any]) -> list[dict[str, Any]]:
    by_id = _workload_by_id(plan)
    checks: list[dict[str, Any]] = []
    for dependency_id in [str(value) for value in workload.get("depends_on_workload_ids", [])]:
        dependency = by_id.get(dependency_id)
        if dependency is None:
            checks.append(
                {
                    "dependency_id": dependency_id,
                    "dependency_present_in_plan": False,
                    "expected_artifact_patterns": [],
                    "matched_artifacts_by_pattern": {},
                    "passed": False,
                    "reason": "dependency workload id not present in plan",
                }
            )
            continue
        patterns = [str(pattern) for pattern in dependency.get("expected_artifacts", [])]
        matched = {
            pattern: [
                str(path.relative_to(root)) if path.is_relative_to(root) else str(path)
                for path in _matching_artifacts(root, [pattern])
            ]
            for pattern in patterns
        }
        passed = bool(patterns) and all(matched.get(pattern) for pattern in patterns)
        checks.append(
            {
                "dependency_id": dependency_id,
                "dependency_present_in_plan": True,
                "dependency_kind": dependency.get("kind"),
                "expected_artifact_patterns": patterns,
                "matched_artifacts_by_pattern": matched,
                "passed": passed,
                "reason": "passed" if passed else "missing dependency expected artifacts",
            }
        )
    return checks


def _command_arg_value(command_args: list[Any], flag: str) -> str | None:
    parts = [str(part) for part in command_args]
    try:
        index = parts.index(flag)
    except ValueError:
        return None
    if index + 1 >= len(parts):
        return None
    return parts[index + 1]


def _h48_trusted_dependency_checks(
    root: Path,
    plan: dict[str, Any],
    workload: dict[str, Any],
) -> list[dict[str, Any]]:
    by_id = _workload_by_id(plan)
    checks: list[dict[str, Any]] = []
    try:
        seed = int(plan.get("seed", 2026))
    except (TypeError, ValueError):
        seed = 2026
    profile = str(plan.get("profile") or "thesis")
    for dependency_id in [str(value) for value in workload.get("depends_on_workload_ids", [])]:
        dependency = by_id.get(dependency_id)
        if dependency is None or dependency.get("kind") != "h48_stronger_table_generation_and_certification":
            continue
        target = (
            _command_arg_value(list(dependency.get("command_args", [])), "--target-solver")
            or dependency_id.removeprefix("stronger_table_")
            or str(plan.get("solver") or "h48h7")
        )
        details: dict[str, Any] = {}
        try:
            solver = canonical_h48_solver(target)
            trusted, message, details = validate_trusted_h48_table_checksum(
                root=root,
                profile=profile,
                seed=seed,
                solver=solver,
                persistent_cache=True,
            )
        except (OSError, ValueError) as exc:
            solver = str(target)
            trusted = False
            message = str(exc)
        checks.append(
            {
                "dependency_id": dependency_id,
                "dependency_kind": dependency.get("kind"),
                "solver": solver,
                "profile": profile,
                "seed": seed,
                "trusted_metadata_valid": details.get("trusted_metadata_valid") is True,
                "trusted_table_valid": trusted,
                "full_checksum_valid": details.get("full_checksum_valid") is True,
                "checksum_cache_hit": details.get("checksum_cache_hit") is True,
                "checksum_persistent_cache_hit": details.get("checksum_persistent_cache_hit") is True,
                "checksum_persistent_cache_enabled": details.get("checksum_persistent_cache_enabled") is True,
                "checksum_certificate_path": details.get("checksum_certificate_path"),
                "checksum_runtime_seconds": details.get("checksum_runtime_seconds"),
                "passed": trusted,
                "reason": message,
            }
        )
    return checks


def run_workload(
    *,
    root: Path,
    plan_path: Path,
    workload_id: str,
    dry_run: bool,
    timeout_seconds: float | None,
    artifact_suffix: str,
) -> tuple[dict[str, Any], Path]:
    plan = _load_json(plan_path)
    workload = _find_workload(plan, workload_id)
    command = [str(part) for part in workload.get("command_args", [])]
    environment = {str(key): str(value) for key, value in dict(workload.get("environment", {})).items()}
    expected_patterns = [str(pattern) for pattern in workload.get("expected_artifacts", [])]
    dependency_checks = _dependency_checks(root, plan, workload)
    dependency_artifacts_found = all(check.get("passed") is True for check in dependency_checks)
    blocked_by_missing_dependencies = bool(dependency_checks) and not dependency_artifacts_found
    h48_trusted_dependency_checks = _h48_trusted_dependency_checks(root, plan, workload)
    h48_trusted_dependencies_satisfied = all(
        check.get("passed") is True for check in h48_trusted_dependency_checks
    )
    blocked_by_untrusted_h48_dependencies = (
        bool(h48_trusted_dependency_checks)
        and dependency_artifacts_found
        and not h48_trusted_dependencies_satisfied
    )

    begin = time.perf_counter()
    return_code: int | None = None
    timed_out = False
    stdout = ""
    stderr = ""
    executed = (
        not dry_run
        and not blocked_by_missing_dependencies
        and not blocked_by_untrusted_h48_dependencies
    )
    if executed:
        env = os.environ.copy()
        env.update(environment)
        completed = run_process_tree(
            command,
            cwd=root,
            env=env,
            timeout_seconds=timeout_seconds,
        )
        return_code = completed.return_code
        timed_out = completed.timed_out
        stdout = completed.stdout
        stderr = completed.stderr
        terminated_process_group = completed.terminated_process_group
    else:
        terminated_process_group = False

    artifacts = _matching_artifacts(root, expected_patterns)
    matched_patterns = {
        pattern: [
            str(path.relative_to(root)) if path.is_relative_to(root) else str(path)
            for path in _matching_artifacts(root, [pattern])
        ]
        for pattern in expected_patterns
    }
    expected_artifacts_found = all(matched_patterns.get(pattern) for pattern in expected_patterns)
    passed = bool(executed and return_code == 0 and not timed_out and expected_artifacts_found)
    if executed and return_code == 0 and not timed_out and not expected_patterns:
        passed = True

    payload = {
        "schema_version": 1,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "plan_path": str(plan_path.relative_to(root)) if plan_path.is_relative_to(root) else str(plan_path),
        "plan_fingerprint": fingerprint_json(plan),
        "workload_fingerprint": fingerprint_json(workload),
        "fingerprint_algorithm": "sha256-canonical-json-v1",
        "fingerprint_scope": "exact loaded plan JSON and selected workload JSON",
        "plan_objective": plan.get("objective"),
        "workload": workload,
        "workload_id": workload_id,
        "workload_kind": workload.get("kind"),
        "executed": executed,
        "dry_run": dry_run,
        "command_args": command,
        "environment": environment,
        "dependency_checks": dependency_checks,
        "dependency_artifacts_found": dependency_artifacts_found,
        "blocked_by_missing_dependencies": blocked_by_missing_dependencies,
        "h48_trusted_dependency_checks": h48_trusted_dependency_checks,
        "h48_trusted_dependencies_satisfied": h48_trusted_dependencies_satisfied,
        "blocked_by_untrusted_h48_dependencies": blocked_by_untrusted_h48_dependencies,
        "timeout_seconds": timeout_seconds,
        "return_code": return_code,
        "timed_out": timed_out,
        "terminated_process_group": terminated_process_group,
        "runtime_seconds": round(time.perf_counter() - begin, 6),
        "stdout_tail": "\n".join(stdout.splitlines()[-80:]),
        "stderr_tail": "\n".join(stderr.splitlines()[-80:]),
        "expected_artifact_patterns": expected_patterns,
        "matched_artifacts_by_pattern": matched_patterns,
        "expected_artifacts_found": expected_artifacts_found,
        "artifact_integrity_algorithm": ARTIFACT_INTEGRITY_ALGORITHM,
        "artifact_integrity_scope": "matched expected artifact files at workload completion",
        "artifact_summaries": [_artifact_summary(root, path) for path in artifacts],
        "required_for_fast_every_state_claim": bool(
            workload.get("required_for_fast_every_state_claim", True)
        ),
        "fast_runtime_proven_for_every_possible_state": False,
        "passed": passed,
    }
    suffix = f"_{artifact_suffix}" if artifact_suffix else ""
    output = (
        root
        / "results"
        / "processed"
        / f"cloud_hardtail_workload_{_safe_id(plan_path.stem)}_{_safe_id(workload_id)}{suffix}.json"
    )
    write_json(output, payload)
    return payload, output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--workload-id", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--timeout", type=float, default=None)
    parser.add_argument("--artifact-suffix", default="")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()

    payload, output = run_workload(
        root=args.root,
        plan_path=args.plan,
        workload_id=args.workload_id,
        dry_run=args.dry_run,
        timeout_seconds=args.timeout,
        artifact_suffix=args.artifact_suffix,
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "workload_id": payload["workload_id"],
                "executed": payload["executed"],
                "blocked_by_missing_dependencies": payload["blocked_by_missing_dependencies"],
                "blocked_by_untrusted_h48_dependencies": payload[
                    "blocked_by_untrusted_h48_dependencies"
                ],
                "passed": payload["passed"],
                "fast_runtime_proven_for_every_possible_state": payload[
                    "fast_runtime_proven_for_every_possible_state"
                ],
            },
            indent=2,
        )
    )
    return 0 if payload["passed"] or payload["dry_run"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

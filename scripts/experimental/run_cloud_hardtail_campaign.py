#!/usr/bin/env python
"""Run selected workloads from a cloud hard-tail campaign plan."""

from __future__ import annotations

import argparse
import json
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
from scripts.experimental.evaluate_cloud_hardtail_campaign import evaluate_campaign  # noqa: E402
from scripts.experimental.run_cloud_hardtail_workload import (  # noqa: E402
    run_workload,
    select_reusable_workload_result,
    validate_workload_result_fingerprints,
    workload_result_candidates,
)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)


def _relative(root: Path, path: Path) -> str:
    return str(path.relative_to(root)) if path.is_relative_to(root) else str(path)


def _latest_workload_result(
    root: Path,
    *,
    plan_stem: str,
    workload_id: str,
) -> tuple[Path, dict[str, Any]] | None:
    candidates = workload_result_candidates(
        root,
        plan_stem=plan_stem,
        workload_id=workload_id,
    )
    return candidates[0] if candidates else None


def _selected_workloads(
    plan: dict[str, Any],
    *,
    workload_ids: list[str],
    kinds: list[str],
    max_workloads: int | None,
) -> list[dict[str, Any]]:
    workloads = [workload for workload in plan.get("workloads", []) if isinstance(workload, dict)]
    if workload_ids:
        wanted = set(workload_ids)
        workloads = [workload for workload in workloads if str(workload.get("id")) in wanted]
        missing = wanted.difference({str(workload.get("id")) for workload in workloads})
        if missing:
            raise SystemExit(f"workload id(s) not found in plan: {', '.join(sorted(missing))}")
    if kinds:
        wanted_kinds = set(kinds)
        workloads = [workload for workload in workloads if str(workload.get("kind")) in wanted_kinds]
    if max_workloads is not None:
        workloads = workloads[: max(0, int(max_workloads))]
    return workloads


def _timeout_for_workload(
    workload: dict[str, Any],
    *,
    timeout_seconds: float | None,
    use_estimated_timeouts: bool,
    timeout_scale: float,
) -> float | None:
    if timeout_seconds is not None:
        return timeout_seconds
    if not use_estimated_timeouts:
        return None
    estimated = workload.get("estimated_wall_seconds")
    if estimated is None:
        return None
    return max(1.0, float(estimated) * max(0.01, float(timeout_scale)))


def _write_evaluation(root: Path, plan_path: Path, output_suffix: str) -> tuple[dict[str, Any], Path]:
    payload = evaluate_campaign(root=root, plan_path=plan_path)
    suffix = f"_{output_suffix}" if output_suffix else ""
    output = (
        root
        / "results"
        / "processed"
        / f"cloud_hardtail_campaign_evaluation_{_safe_id(plan_path.stem)}{suffix}.json"
    )
    write_json(output, payload)
    return payload, output


def run_campaign(
    *,
    root: Path,
    plan_path: Path,
    dry_run: bool,
    resume: bool,
    stop_on_fail: bool,
    timeout_seconds: float | None,
    use_estimated_timeouts: bool,
    timeout_scale: float,
    artifact_suffix: str,
    workload_ids: list[str] | None = None,
    kinds: list[str] | None = None,
    max_workloads: int | None = None,
    evaluate_after: bool = True,
    evaluation_suffix: str = "",
) -> tuple[dict[str, Any], Path]:
    plan = _load_json(plan_path)
    selected = _selected_workloads(
        plan,
        workload_ids=workload_ids or [],
        kinds=kinds or [],
        max_workloads=max_workloads,
    )
    begin = time.perf_counter()
    rows: list[dict[str, Any]] = []
    halted = False
    for workload in selected:
        workload_id = str(workload.get("id"))
        reusable = (
            select_reusable_workload_result(
                root,
                plan_stem=plan_path.stem,
                workload_id=workload_id,
                plan=plan,
                workload=workload,
            )
            if resume
            else None
        )
        latest = (
            _latest_workload_result(root, plan_stem=plan_path.stem, workload_id=workload_id)
            if resume and reusable is None
            else None
        )
        latest_fingerprint_validation = (
            validate_workload_result_fingerprints(latest[1], plan=plan, workload=workload)
            if latest is not None
            else None
        )
        if reusable is not None:
            reusable_path, _reusable_payload, reusable_validation, ignored_resume_results = reusable
            rows.append(
                {
                    "workload_id": workload_id,
                    "kind": workload.get("kind"),
                    "action": "skipped_existing_passed",
                    "passed": True,
                    "result_path": _relative(root, reusable_path),
                    "fingerprint_validation": reusable_validation,
                    "ignored_newer_result_count": len(ignored_resume_results),
                    "ignored_newer_results": ignored_resume_results,
                }
            )
            continue

        workload_timeout = _timeout_for_workload(
            workload,
            timeout_seconds=timeout_seconds,
            use_estimated_timeouts=use_estimated_timeouts,
            timeout_scale=timeout_scale,
        )
        payload, output = run_workload(
            root=root,
            plan_path=plan_path,
            workload_id=workload_id,
            dry_run=dry_run,
            timeout_seconds=workload_timeout,
            artifact_suffix=artifact_suffix,
        )
        rows.append(
            {
                "workload_id": workload_id,
                "kind": workload.get("kind"),
                "action": (
                    "dry_run"
                    if dry_run
                    else "blocked_missing_dependencies"
                    if payload.get("blocked_by_missing_dependencies") is True
                    else "blocked_untrusted_h48_dependencies"
                    if payload.get("blocked_by_untrusted_h48_dependencies") is True
                    else "executed"
                ),
                "passed": payload.get("passed") is True,
                "executed": payload.get("executed") is True,
                "dry_run": payload.get("dry_run") is True,
                "blocked_by_missing_dependencies": payload.get("blocked_by_missing_dependencies") is True,
                "blocked_by_untrusted_h48_dependencies": (
                    payload.get("blocked_by_untrusted_h48_dependencies") is True
                ),
                "timed_out": payload.get("timed_out") is True,
                "return_code": payload.get("return_code"),
                "timeout_seconds": workload_timeout,
                "result_path": _relative(root, output),
                "ignored_resume_result_path": (
                    _relative(root, latest[0])
                    if latest is not None
                    and latest_fingerprint_validation is not None
                    and latest_fingerprint_validation.get("passed") is not True
                    else None
                ),
                "ignored_resume_result_count": 1 if latest is not None else 0,
                "ignored_resume_fingerprint_validation": (
                    latest_fingerprint_validation
                    if latest is not None
                    and latest_fingerprint_validation is not None
                    and latest_fingerprint_validation.get("passed") is not True
                    else None
                ),
            }
        )
        if stop_on_fail and not dry_run and payload.get("passed") is not True:
            halted = True
            break

    evaluation_payload: dict[str, Any] | None = None
    evaluation_output: Path | None = None
    if evaluate_after:
        evaluation_payload, evaluation_output = _write_evaluation(root, plan_path, evaluation_suffix)

    executed_count = sum(1 for row in rows if row.get("action") == "executed")
    dry_run_count = sum(1 for row in rows if row.get("action") == "dry_run")
    skipped_count = sum(1 for row in rows if row.get("action") == "skipped_existing_passed")
    passed_count = sum(1 for row in rows if row.get("passed") is True)
    failed_count = len(rows) - passed_count
    all_selected_workloads_passed = bool(rows) and failed_count == 0 and dry_run_count == 0
    payload = {
        "schema_version": 1,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "plan_path": _relative(root, plan_path),
        "plan_claim_scope": plan.get("claim_scope", "full"),
        "plan_objective": plan.get("objective"),
        "dry_run": dry_run,
        "resume": resume,
        "stop_on_fail": stop_on_fail,
        "halted": halted,
        "selected_workload_count": len(selected),
        "executed_workload_count": executed_count,
        "dry_run_workload_count": dry_run_count,
        "skipped_existing_passed_count": skipped_count,
        "passed_workload_count": passed_count,
        "failed_workload_count": failed_count,
        "all_selected_workloads_passed": all_selected_workloads_passed,
        "campaign_runtime_seconds": round(time.perf_counter() - begin, 6),
        "evaluation_output": _relative(root, evaluation_output) if evaluation_output else None,
        "evaluation_all_required_workloads_passed": (
            evaluation_payload.get("all_required_workloads_passed") if evaluation_payload else None
        ),
        "fast_runtime_proven_for_every_possible_state": (
            evaluation_payload.get("fast_runtime_proven_for_every_possible_state")
            if evaluation_payload
            else False
        ),
        "rows": rows,
        "notes": (
            "Dry-run rows and canary-scope campaign runs do not prove the final every-state runtime claim. "
            "Use the full-scope plan and the aggregate evaluator for the final proof gate."
        ),
    }
    suffix = f"_{artifact_suffix}" if artifact_suffix else ""
    output = (
        root
        / "results"
        / "processed"
        / f"cloud_hardtail_campaign_run_{_safe_id(plan_path.stem)}{suffix}.json"
    )
    write_json(output, payload)
    return payload, output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--stop-on-fail", action="store_true")
    parser.add_argument("--timeout", type=float, default=None)
    parser.add_argument("--use-estimated-timeouts", action="store_true")
    parser.add_argument("--timeout-scale", type=float, default=1.0)
    parser.add_argument("--artifact-suffix", default="campaign")
    parser.add_argument("--evaluation-suffix", default="")
    parser.add_argument("--workload-id", action="append", default=[])
    parser.add_argument("--kind", action="append", default=[])
    parser.add_argument("--max-workloads", type=int, default=None)
    parser.add_argument("--no-evaluate", action="store_true")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()

    payload, output = run_campaign(
        root=args.root,
        plan_path=args.plan,
        dry_run=args.dry_run,
        resume=args.resume,
        stop_on_fail=args.stop_on_fail,
        timeout_seconds=args.timeout,
        use_estimated_timeouts=args.use_estimated_timeouts,
        timeout_scale=args.timeout_scale,
        artifact_suffix=args.artifact_suffix,
        workload_ids=args.workload_id,
        kinds=args.kind,
        max_workloads=args.max_workloads,
        evaluate_after=not args.no_evaluate,
        evaluation_suffix=args.evaluation_suffix,
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "selected_workload_count": payload["selected_workload_count"],
                "executed_workload_count": payload["executed_workload_count"],
                "dry_run_workload_count": payload["dry_run_workload_count"],
                "skipped_existing_passed_count": payload["skipped_existing_passed_count"],
                "all_selected_workloads_passed": payload["all_selected_workloads_passed"],
                "fast_runtime_proven_for_every_possible_state": payload[
                    "fast_runtime_proven_for_every_possible_state"
                ],
            },
            indent=2,
        )
    )
    return 0 if payload["all_selected_workloads_passed"] or payload["dry_run"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

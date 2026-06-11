#!/usr/bin/env python
"""Build an auditable non-AWS H48 fast-target proof-package manifest."""

from __future__ import annotations

import argparse
import hashlib
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
from scripts.experimental.run_h48_fasttarget_nonaws_proof import (  # noqa: E402
    AWS_UNLOCK_ENV,
    AWS_UNLOCK_VALUE,
    _validate_nonaws_runbook_manifest,
    scan_planned_steps_for_aws,
)
from scripts.experimental.run_h48_fasttarget_remote import build_remote_proof_steps  # noqa: E402


DEFAULT_RUNBOOK = Path(
    "results/processed/cloud_hardtail_runbook_cloud_20260601_h48h10_fasttarget_batch10.json"
)
DEFAULT_ASSUMED_PREFLIGHT = Path(
    "results/processed/cloud_hardtail_preflight_seed_2026_thesis_h48h10_assumed_nonaws_16c64g250g.json"
)
DEFAULT_PROOF_VOLUME_REPORT = Path(
    "results/processed/h48_proof_volume_candidates_seed_2026_thesis_h48h10_local_noaws_current.json"
)
DEFAULT_CONTRACT = Path("results/processed/h48_oracle_contract_seed_2026_thesis_h48h10.json")
PACKAGE_KIND = "h48_fasttarget_nonaws_proof_package"


def _safe_id(value: str) -> str:
    return "".join(char if char.isalnum() or char in "._-" else "_" for char in value)


def _relative(root: Path, path: Path) -> str:
    return str(path.relative_to(root)) if path.is_relative_to(root) else str(path)


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _file_fingerprint(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    return {
        "path": _relative(ROOT, path) if path.is_relative_to(ROOT) else str(path),
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "mode_octal": oct(path.stat().st_mode & 0o777),
    }


def _fingerprints_for_runbook(root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    generated = manifest.get("generated_files") or {}
    rows: dict[str, Any] = {}
    missing: list[str] = []
    for key, relative in sorted(generated.items()):
        path = root / str(relative)
        if not path.exists():
            missing.append(str(relative))
            rows[str(key)] = {"path": str(relative), "present": False}
            continue
        data = path.read_bytes()
        rows[str(key)] = {
            "path": str(relative),
            "present": True,
            "size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "mode_octal": oct(path.stat().st_mode & 0o777),
        }
    return {
        "algorithm": "sha256-size-mode-v1",
        "count": len(rows),
        "missing": missing,
        "rows": rows,
    }


def _digest_components(components: list[dict[str, Any]]) -> str:
    canonical = json.dumps(components, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _required_plan_summary(plan: dict[str, Any] | None) -> dict[str, Any] | None:
    if not plan:
        return None
    required_ids = [
        str(workload.get("id"))
        for workload in plan.get("workloads", []) or []
        if isinstance(workload, dict)
        and workload.get("required_for_fast_every_state_claim") is True
        and workload.get("id") is not None
    ]
    stronger = next(
        (
            workload
            for workload in plan.get("workloads", []) or []
            if isinstance(workload, dict)
            and workload.get("kind") == "h48_stronger_table_generation_and_certification"
        ),
        None,
    )
    return {
        "path_claim_scope": plan.get("claim_scope"),
        "solver": plan.get("solver"),
        "profile": plan.get("profile"),
        "seed": plan.get("seed"),
        "distance": plan.get("distance"),
        "selected_offset_start": plan.get("selected_offset_start"),
        "selected_offset_end": plan.get("selected_offset_end"),
        "available_scramble_rows": plan.get("available_scramble_rows"),
        "h48_gendata_workbatch": plan.get("h48_gendata_workbatch"),
        "required_workload_count": len(required_ids),
        "required_workload_ids": required_ids,
        "stronger_table_workload": stronger,
    }


def _contract_gap_summary(contract: dict[str, Any] | None) -> dict[str, Any]:
    if not contract:
        return {"present": False}
    artifact_checks = contract.get("artifact_checks") or {}
    empirical_checks = contract.get("empirical_checks") or {}
    cloud = contract.get("cloud_runtime_proof") or {}
    return {
        "present": True,
        "passed": contract.get("passed") is True,
        "fast_runtime_proven_for_every_possible_state": (
            contract.get("fast_runtime_proven_for_every_possible_state") is True
        ),
        "all_state_exact_contract_supported": (
            contract.get("all_state_exact_contract_supported") is True
        ),
        "empirical_fast_corpus_supported": contract.get("empirical_fast_corpus_supported") is True,
        "false_artifact_checks": sorted(key for key, value in artifact_checks.items() if value is False),
        "false_empirical_checks": sorted(key for key, value in empirical_checks.items() if value is False),
        "cloud_runtime_proof_passed": cloud.get("passed") is True,
        "cloud_runtime_missing_or_failed_workload_count": cloud.get("missing_or_failed_workload_count"),
        "cloud_runtime_reason": cloud.get("reason"),
    }


def _preflight_is_live_runtime_evidence(preflight: dict[str, Any]) -> bool:
    return (
        bool(preflight)
        and preflight.get("passed") is True
        and preflight.get("machine_source") == "local"
        and preflight.get("assumed_machine_not_runtime_evidence") is not True
    )


def _proof_volume_is_live_launchable(report: dict[str, Any]) -> bool:
    return (
        bool(report)
        and report.get("artifact_kind") == "h48_proof_volume_candidates"
        and report.get("solver") == "h48h10"
        and report.get("machine_source") == "local"
        and report.get("launchable_for_h48_generation") is True
        and int(report.get("launchable_candidate_count", 0) or 0) > 0
        and report.get("fast_runtime_proven_for_every_possible_state") is False
    )


def _command(args: list[str]) -> str:
    return shlex.join(args)


def build_proof_package(
    *,
    root: Path,
    runbook_manifest_path: Path,
    assumed_preflight_path: Path,
    proof_volume_report_path: Path | None,
    contract_path: Path,
    host: str,
    remote_root: str,
    artifact_suffix: str,
    require_live_preflight: bool = False,
    require_proof_volume_report: bool | None = None,
) -> tuple[dict[str, Any], Path]:
    root = root.resolve()
    runbook_path = runbook_manifest_path if runbook_manifest_path.is_absolute() else root / runbook_manifest_path
    assumed_preflight = (
        assumed_preflight_path if assumed_preflight_path.is_absolute() else root / assumed_preflight_path
    )
    proof_volume_report = (
        None
        if proof_volume_report_path is None
        else proof_volume_report_path
        if proof_volume_report_path.is_absolute()
        else root / proof_volume_report_path
    )
    contract_file = contract_path if contract_path.is_absolute() else root / contract_path

    manifest = _load_json(runbook_path) or {}
    profile = str(manifest.get("profile") or "thesis")
    seed = int(manifest.get("seed") or 2026)
    solver = str(manifest.get("solver") or "h48h10")
    runbook_validation = _validate_nonaws_runbook_manifest(
        root=root,
        runbook_manifest_path=runbook_path,
    )
    steps, _context = build_remote_proof_steps(
        root=root,
        runbook_manifest_path=runbook_path,
        host=host,
        remote_root=remote_root,
        skip_sync=False,
        skip_fetch=False,
        skip_local_finalize=False,
        install_fetched_prerequisites=False,
        prerequisite_bundle_mode="split",
        fetch_diagnostics_on_fail=True,
        remote_action="detached-staged-proof",
        prerequisite_wait_timeout_seconds=43200.0,
        prerequisite_poll_interval_seconds=60.0,
        full_wait_timeout_seconds=28800.0,
        full_poll_interval_seconds=60.0,
        ssh_options=[],
        rsync_excludes=[],
        rsync_delete=False,
        port=None,
        identity_file=None,
    )
    aws_scan = scan_planned_steps_for_aws(root=root, steps=steps)
    generated_fingerprints = _fingerprints_for_runbook(root, manifest)

    canary_plan_path = root / str(manifest.get("canary_plan_path", ""))
    full_plan_path = root / str(manifest.get("full_plan_path", ""))
    canary_plan = _load_json(canary_plan_path)
    full_plan = _load_json(full_plan_path)
    assumed_preflight_payload = _load_json(assumed_preflight) or {}
    proof_volume_payload = (_load_json(proof_volume_report) or {}) if proof_volume_report else {}
    contract = _load_json(contract_file)
    preflight_is_live = _preflight_is_live_runtime_evidence(assumed_preflight_payload)
    proof_volume_is_launchable = _proof_volume_is_live_launchable(proof_volume_payload)
    proof_volume_required = require_live_preflight if require_proof_volume_report is None else bool(
        require_proof_volume_report
    )
    preflight_requirement_satisfied = (not require_live_preflight) or preflight_is_live
    proof_volume_requirement_satisfied = (
        (not proof_volume_required) or proof_volume_is_launchable
    )
    package_mode = "launchable" if require_live_preflight else "planning"

    component_fingerprints = [
        {
            "kind": "runbook_manifest",
            **_file_fingerprint(runbook_path),
        },
    ]
    for path in [canary_plan_path, full_plan_path, assumed_preflight]:
        if path.exists():
            component_fingerprints.append(_file_fingerprint(path))
    if proof_volume_report and proof_volume_report.exists():
        component_fingerprints.append(_file_fingerprint(proof_volume_report))
    for row in generated_fingerprints["rows"].values():
        if row.get("present") is True:
            component_fingerprints.append(dict(row))

    required_completion_gates = [
        "trusted h48h10 table bytes exist at the canonical table path",
        "h48h10 metadata exists and validates the full table size/checksum",
        "the stronger_table_h48h10 workload passes",
        "a live proof-volume inspector report records at least one launchable H48H10 candidate",
        "all full-plan distance-20 hard-tail workloads pass",
        "all required proof artifacts pass content-integrity validation",
        "the final cloud/runtime evaluation passes thesis-audit acceptance gates",
        "results/processed/h48_oracle_contract_seed_2026_thesis_h48h10.json records fast_runtime_proven_for_every_possible_state=true",
    ]
    checks = {
        "runbook_validation_passed": runbook_validation.get("passed") is True,
        "aws_scan_passed": aws_scan.get("passed") is True,
        "split_bundle_mode_planned": any(row.get("id") == "fetch_prerequisite_table_parts" for row in steps),
        "archive_fetch_omitted_for_split_mode": not any(
            row.get("id") == "fetch_prerequisite_tables_archive" for row in steps
        ),
        "assumed_preflight_present": bool(assumed_preflight_payload),
        "assumed_preflight_passed": assumed_preflight_payload.get("passed") is True,
        "assumed_preflight_not_runtime_evidence": (
            preflight_is_live
            or assumed_preflight_payload.get("assumed_machine_not_runtime_evidence") is True
        ),
        "preflight_requirement_satisfied": preflight_requirement_satisfied,
        "proof_volume_report_present_or_not_required": (
            bool(proof_volume_payload) or not proof_volume_required
        ),
        "proof_volume_requirement_satisfied": proof_volume_requirement_satisfied,
        "contract_present": contract is not None,
        "contract_still_requires_runtime_proof": (
            contract is not None
            and contract.get("fast_runtime_proven_for_every_possible_state") is not True
        ),
    }
    passed = all(checks.values())

    safe_suffix = _safe_id(artifact_suffix or "nonaws_splitbundle_validated")
    output = (
        root
        / "results"
        / "processed"
        / f"h48_fasttarget_nonaws_proof_package_seed_{seed}_{profile}_{solver}_{safe_suffix}.json"
    )
    payload: dict[str, Any] = {
        "schema_version": 1,
        "artifact_kind": PACKAGE_KIND,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "execution_provider": "generic_ssh_non_aws",
        "profile": profile,
        "seed": seed,
        "solver": solver,
        "runbook_manifest_path": _relative(root, runbook_path),
        "assumed_preflight_path": _relative(root, assumed_preflight),
        "proof_volume_report_path": (
            _relative(root, proof_volume_report) if proof_volume_report else None
        ),
        "contract_path": _relative(root, contract_file),
        "remote_host_placeholder": host,
        "remote_root_placeholder": remote_root,
        "aws_usage_allowed": False,
        "aws_unlock_env": AWS_UNLOCK_ENV,
        "aws_unlock_env_present": os.environ.get(AWS_UNLOCK_ENV) == AWS_UNLOCK_VALUE,
        "package_mode": package_mode,
        "live_preflight_required": require_live_preflight,
        "proof_volume_report_required": proof_volume_required,
        "preflight_is_live_runtime_evidence": preflight_is_live,
        "proof_volume_report_launchable": proof_volume_is_launchable,
        "assumed_preflight_allowed_for_package": not require_live_preflight,
        "launchable_for_execution": bool(
            passed
            and require_live_preflight
            and preflight_is_live
            and proof_volume_is_launchable
        ),
        "readiness_classification": (
            "launchable_nonaws_proof_package"
            if passed and require_live_preflight and preflight_is_live and proof_volume_is_launchable
            else (
                "planning_nonaws_proof_package"
                if passed and not require_live_preflight
                else "not_ready"
            )
        ),
        "prerequisite_bundle_mode": "split",
        "runbook_validation": runbook_validation,
        "aws_command_scan": aws_scan,
        "generated_file_fingerprints": generated_fingerprints,
        "component_fingerprints": component_fingerprints,
        "package_sha256": _digest_components(component_fingerprints),
        "canary_plan_summary": _required_plan_summary(canary_plan),
        "full_plan_summary": _required_plan_summary(full_plan),
        "assumed_preflight_summary": {
            "path": _relative(root, assumed_preflight),
            "present": bool(assumed_preflight_payload),
            "passed": assumed_preflight_payload.get("passed") is True,
            "machine_source": assumed_preflight_payload.get("machine_source"),
            "assumed_machine_not_runtime_evidence": (
                assumed_preflight_payload.get("assumed_machine_not_runtime_evidence") is True
            ),
            "live_runtime_evidence": preflight_is_live,
            "live_preflight_required": require_live_preflight,
            "preflight_requirement_satisfied": preflight_requirement_satisfied,
            "machine": assumed_preflight_payload.get("machine"),
            "target_h48_workspace": assumed_preflight_payload.get("target_h48_workspace"),
            "fast_runtime_proven_for_every_possible_state": (
                assumed_preflight_payload.get("fast_runtime_proven_for_every_possible_state") is True
            ),
        },
        "proof_volume_report_summary": {
            "path": _relative(root, proof_volume_report) if proof_volume_report else None,
            "present": bool(proof_volume_payload),
            "artifact_kind": proof_volume_payload.get("artifact_kind"),
            "machine_source": proof_volume_payload.get("machine_source"),
            "solver": proof_volume_payload.get("solver"),
            "candidate_count": proof_volume_payload.get("candidate_count"),
            "launchable_candidate_count": proof_volume_payload.get("launchable_candidate_count"),
            "launchable_for_h48_generation": proof_volume_payload.get(
                "launchable_for_h48_generation"
            ),
            "host_machine_satisfies": proof_volume_payload.get("host_machine_satisfies"),
            "available_memory_satisfies": proof_volume_payload.get(
                "available_memory_satisfies"
            ),
            "threads_satisfy_cpu": proof_volume_payload.get("threads_satisfy_cpu"),
            "requirements": proof_volume_payload.get("requirements"),
            "machine_reasons": proof_volume_payload.get("machine_reasons"),
            "best_candidate": proof_volume_payload.get("best_candidate"),
            "live_launchable_evidence": proof_volume_is_launchable,
            "proof_volume_report_required": proof_volume_required,
            "proof_volume_requirement_satisfied": proof_volume_requirement_satisfied,
            "fast_runtime_proven_for_every_possible_state": (
                proof_volume_payload.get("fast_runtime_proven_for_every_possible_state") is True
            ),
        },
        "contract_gap_summary": _contract_gap_summary(contract),
        "planned_step_count": len(steps),
        "planned_step_ids": [str(step.get("id")) for step in steps],
        "planned_steps": [
            {
                "id": step.get("id"),
                "location": step.get("location"),
                "required": step.get("required") is True,
                "detached": step.get("detached") is True,
                "command": [str(part) for part in step.get("command", [])],
                "shell_command": _command([str(part) for part in step.get("command", [])]),
                "script": step.get("script"),
                "scripts": step.get("scripts"),
            }
            for step in steps
        ],
        "operator_commands": {
            "local_preflight_probe": _command(
                [
                    "python",
                    "scripts/run_h48_fasttarget_local_proof.py",
                    "--runbook",
                    _relative(root, runbook_path),
                    "--action",
                    "preflight",
                    "--execute",
                    "--timeout",
                    "120",
                    "--artifact-suffix",
                    "h48h10_preflight_real_nonaws_host",
                ]
            ),
            "local_proof_volume_probe": _command(
                [
                    "python",
                    "scripts/inspect_h48_proof_volumes.py",
                    "--profile",
                    profile,
                    "--seed",
                    str(seed),
                    "--solver",
                    solver,
                    "--artifact-suffix",
                    "local_noaws_current",
                    "--min-cpus",
                    "16",
                    "--min-memory-gib",
                    "64",
                    "--min-storage-gib",
                    "250",
                    "--min-mmap-available-memory-gib",
                    "4",
                    "--threads",
                    "16",
                ]
            ),
            "generic_ssh_detached_staged_split_proof": _command(
                [
                    "python",
                    "scripts/run_h48_fasttarget_nonaws_proof.py",
                    "--runbook",
                    _relative(root, runbook_path),
                    "--host",
                    host,
                    "--remote-root",
                    remote_root,
                    "--remote-action",
                    "detached-staged-proof",
                    "--prerequisite-bundle-mode",
                    "split",
                    "--prerequisite-wait-timeout",
                    "43200",
                    "--prerequisite-poll-interval",
                    "60",
                    "--full-wait-timeout",
                    "28800",
                    "--full-poll-interval",
                    "60",
                    "--proof-package",
                    _relative(root, output),
                    "--execute",
                    "--artifact-suffix",
                    "h48h10_detached_staged_nonaws_split_realhost",
                ]
            ),
            "final_contract_refresh": _command(
                [
                    "python",
                    "scripts/generate_h48_oracle_contract.py",
                    "--profile",
                    profile,
                    "--seed",
                    str(seed),
                    "--solver",
                    solver,
                ]
            ),
            "final_audit": "python scripts/verify_results.py && python scripts/thesis_audit.py",
        },
        "checks": checks,
        "required_completion_gates": required_completion_gates,
        "passed": passed,
        "fast_runtime_proven_for_every_possible_state": False,
        "notes": (
            "This artifact proves the non-AWS H48H10 proof package is byte-bound. "
            "Default planning mode may use assumed machine-shape evidence; launchable mode requires "
            "a passing live local preflight and a passing proof-volume launchability report. It is "
            "not table-generation evidence and cannot prove the every-state fast oracle claim."
        ),
    }
    write_json(output, payload)
    return payload, output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runbook", type=Path, default=DEFAULT_RUNBOOK)
    parser.add_argument("--assumed-preflight", type=Path, default=DEFAULT_ASSUMED_PREFLIGHT)
    parser.add_argument("--proof-volume-report", type=Path, default=DEFAULT_PROOF_VOLUME_REPORT)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--host", default="proof-host.example")
    parser.add_argument("--remote-root", default="/mnt/sgarbas-h48")
    parser.add_argument("--artifact-suffix", default="nonaws_splitbundle_validated")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument(
        "--require-live-preflight",
        action="store_true",
        help="Fail unless the preflight artifact is from a real local machine, not assumed specs.",
    )
    parser.add_argument(
        "--require-proof-volume-report",
        action="store_true",
        help=(
            "Fail unless the proof-volume report records a launchable local/non-AWS H48H10 "
            "candidate. Launchable mode implies this requirement."
        ),
    )
    args = parser.parse_args()

    payload, output = build_proof_package(
        root=args.root,
        runbook_manifest_path=args.runbook,
        assumed_preflight_path=args.assumed_preflight,
        proof_volume_report_path=args.proof_volume_report,
        contract_path=args.contract,
        host=args.host,
        remote_root=args.remote_root,
        artifact_suffix=args.artifact_suffix,
        require_live_preflight=args.require_live_preflight,
        require_proof_volume_report=args.require_proof_volume_report or None,
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "passed": payload["passed"],
                "execution_provider": payload["execution_provider"],
                "package_mode": payload["package_mode"],
                "launchable_for_execution": payload["launchable_for_execution"],
                "preflight_is_live_runtime_evidence": payload["preflight_is_live_runtime_evidence"],
                "proof_volume_report_launchable": payload["proof_volume_report_launchable"],
                "package_sha256": payload["package_sha256"],
                "fast_runtime_proven_for_every_possible_state": payload[
                    "fast_runtime_proven_for_every_possible_state"
                ],
            },
            indent=2,
        )
    )
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

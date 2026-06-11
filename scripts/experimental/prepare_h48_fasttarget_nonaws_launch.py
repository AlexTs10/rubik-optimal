#!/usr/bin/env python
"""Prepare a launchable generic non-AWS H48H10 proof package.

This script intentionally does not start H48 table generation or proof
workloads. It gathers live host/volume evidence on the current machine and then
asks the proof-package builder to classify the package as launchable or not.
Run it on the approved non-AWS proof host after syncing the repository there.
"""

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

from rubik_optimal.results import write_json  # noqa: E402
from scripts.experimental.build_h48_fasttarget_proof_package import (  # noqa: E402
    DEFAULT_CONTRACT,
    DEFAULT_RUNBOOK,
    build_proof_package,
)
from scripts.experimental.cloud_hardtail_preflight import write_preflight  # noqa: E402
from scripts.inspect_h48_capacity import H48_MMAP_GENERATION_DISK_MULTIPLIER  # noqa: E402
from scripts.inspect_h48_proof_volumes import write_proof_volume_report  # noqa: E402


ARTIFACT_KIND = "h48_fasttarget_nonaws_launch_preparation"


def _safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value)).strip("_") or "launch"


def _relative(root: Path, path: Path) -> str:
    return str(path.relative_to(root)) if path.is_relative_to(root) else str(path)


def _command(parts: list[str]) -> str:
    import shlex

    return shlex.join(parts)


def prepare_launch_package(
    *,
    root: Path,
    profile: str,
    seed: int,
    solver: str,
    runbook_manifest_path: Path,
    contract_path: Path,
    host: str,
    remote_root: str,
    artifact_suffix: str,
    candidate_roots: list[Path] | None = None,
    include_configured_root: bool = True,
    include_volume_roots: bool = True,
    volume_root: Path = Path("/Volumes"),
    min_cpus: int = 16,
    min_memory_gib: float = 64.0,
    min_storage_gib: float = 250.0,
    min_mmap_available_memory_gib: float = 4.0,
    threads: int = 16,
    workspace_multiplier: float = H48_MMAP_GENERATION_DISK_MULTIPLIER,
    require_external_assets: bool = True,
) -> tuple[dict[str, Any], Path]:
    """Gather live launch evidence and build the launchable package manifest."""

    root = root.resolve()
    safe_suffix = _safe_id(artifact_suffix)
    preflight_suffix = f"{safe_suffix}_live_preflight"
    volume_suffix = f"{safe_suffix}_proof_volume"
    package_suffix = f"{safe_suffix}_launchable_package"

    preflight_payload, preflight_path = write_preflight(
        root=root,
        profile=profile,
        seed=seed,
        solver=solver,
        artifact_suffix=preflight_suffix,
        min_cpus=min_cpus,
        min_memory_gib=min_memory_gib,
        min_free_disk_gib=0.0,
        min_storage_gib=min_storage_gib,
        threads=threads,
        require_external_assets=require_external_assets,
        require_target_table=False,
        disk_multiplier=workspace_multiplier,
    )
    proof_volume_payload, proof_volume_path, proof_volume_table = write_proof_volume_report(
        root=root,
        profile=profile,
        seed=seed,
        solver=solver,
        artifact_suffix=volume_suffix,
        candidate_roots=candidate_roots,
        include_configured_root=include_configured_root,
        include_volume_roots=include_volume_roots,
        volume_root=volume_root,
        min_cpus=min_cpus,
        min_memory_gib=min_memory_gib,
        min_storage_gib=min_storage_gib,
        min_mmap_available_memory_gib=min_mmap_available_memory_gib,
        threads=threads,
        workspace_multiplier=workspace_multiplier,
    )
    package_payload, proof_package_path = build_proof_package(
        root=root,
        runbook_manifest_path=runbook_manifest_path,
        assumed_preflight_path=preflight_path,
        proof_volume_report_path=proof_volume_path,
        contract_path=contract_path,
        host=host,
        remote_root=remote_root,
        artifact_suffix=package_suffix,
        require_live_preflight=True,
        require_proof_volume_report=True,
    )

    launchable = package_payload.get("launchable_for_execution") is True
    status = "launchable" if launchable else "not_launchable"
    run_command = _command(
        [
            "python",
            "scripts/run_h48_fasttarget_nonaws_proof.py",
            "--runbook",
            _relative(root, runbook_manifest_path if runbook_manifest_path.is_absolute() else root / runbook_manifest_path),
            "--host",
            host,
            "--remote-root",
            remote_root,
            "--remote-action",
            "detached-staged-proof",
            "--prerequisite-bundle-mode",
            "split",
            "--proof-package",
            _relative(root, proof_package_path),
            "--execute",
            "--artifact-suffix",
            f"{safe_suffix}_detached_staged_execute",
        ]
    )
    payload: dict[str, Any] = {
        "schema_version": 1,
        "artifact_kind": ARTIFACT_KIND,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "profile": profile,
        "seed": int(seed),
        "solver": solver,
        "execution_provider": "generic_ssh_non_aws",
        "aws_usage_allowed": False,
        "status": status,
        "passed": launchable,
        "launchable_for_execution": launchable,
        "heavy_generation_started": False,
        "proof_workloads_started": False,
        "preflight_path": _relative(root, preflight_path),
        "proof_volume_report_path": _relative(root, proof_volume_path),
        "proof_volume_table_path": _relative(root, proof_volume_table),
        "proof_package_path": _relative(root, proof_package_path),
        "preflight_summary": {
            "passed": preflight_payload.get("passed") is True,
            "machine_source": preflight_payload.get("machine_source"),
            "assumed_machine_not_runtime_evidence": (
                preflight_payload.get("assumed_machine_not_runtime_evidence") is True
            ),
            "require_external_assets": preflight_payload.get("require_external_assets"),
            "missing_external_paths": preflight_payload.get("missing_external_paths"),
            "reasons": preflight_payload.get("reasons"),
            "machine": preflight_payload.get("machine"),
            "target_h48_workspace": preflight_payload.get("target_h48_workspace"),
        },
        "proof_volume_summary": {
            "launchable_for_h48_generation": (
                proof_volume_payload.get("launchable_for_h48_generation") is True
            ),
            "launchable_candidate_count": proof_volume_payload.get("launchable_candidate_count"),
            "candidate_count": proof_volume_payload.get("candidate_count"),
            "machine_reasons": proof_volume_payload.get("machine_reasons"),
            "best_candidate": proof_volume_payload.get("best_candidate"),
            "requirements": proof_volume_payload.get("requirements"),
        },
        "proof_package_summary": {
            "passed": package_payload.get("passed") is True,
            "package_mode": package_payload.get("package_mode"),
            "readiness_classification": package_payload.get("readiness_classification"),
            "launchable_for_execution": package_payload.get("launchable_for_execution") is True,
            "preflight_is_live_runtime_evidence": (
                package_payload.get("preflight_is_live_runtime_evidence") is True
            ),
            "proof_volume_report_launchable": (
                package_payload.get("proof_volume_report_launchable") is True
            ),
            "package_sha256": package_payload.get("package_sha256"),
            "checks": package_payload.get("checks"),
        },
        "next_execute_command_after_approval": run_command if launchable else None,
        "fast_runtime_proven_for_every_possible_state": False,
        "notes": (
            "Launch preparation only. A pass means the current non-AWS host has live "
            "preflight/proof-volume evidence and a launchable proof package. It does "
            "not generate H48H10, run proof workloads, or prove the every-state fast "
            "oracle claim."
        ),
    }
    output = (
        root
        / "results"
        / "processed"
        / f"h48_fasttarget_nonaws_launch_preparation_seed_{seed}_{profile}_{solver}_{safe_suffix}.json"
    )
    write_json(output, payload)
    return payload, output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default="thesis")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--solver", default="h48h10")
    parser.add_argument("--runbook", type=Path, default=DEFAULT_RUNBOOK)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--host", default="proof-host.example")
    parser.add_argument("--remote-root", default="/mnt/sgarbas-h48")
    parser.add_argument("--artifact-suffix", default="current")
    parser.add_argument("--candidate-root", action="append", type=Path, default=[])
    parser.add_argument("--no-configured-root", action="store_true")
    parser.add_argument("--no-volume-roots", action="store_true")
    parser.add_argument("--volume-root", type=Path, default=Path("/Volumes"))
    parser.add_argument("--min-cpus", type=int, default=16)
    parser.add_argument("--min-memory-gib", type=float, default=64.0)
    parser.add_argument("--min-storage-gib", type=float, default=250.0)
    parser.add_argument("--min-mmap-available-memory-gib", type=float, default=4.0)
    parser.add_argument("--threads", type=int, default=16)
    parser.add_argument("--workspace-multiplier", type=float, default=H48_MMAP_GENERATION_DISK_MULTIPLIER)
    parser.add_argument("--skip-external-assets", action="store_true")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()

    payload, output = prepare_launch_package(
        root=args.root,
        profile=args.profile,
        seed=args.seed,
        solver=args.solver,
        runbook_manifest_path=args.runbook,
        contract_path=args.contract,
        host=args.host,
        remote_root=args.remote_root,
        artifact_suffix=args.artifact_suffix,
        candidate_roots=args.candidate_root,
        include_configured_root=not args.no_configured_root,
        include_volume_roots=not args.no_volume_roots,
        volume_root=args.volume_root,
        min_cpus=args.min_cpus,
        min_memory_gib=args.min_memory_gib,
        min_storage_gib=args.min_storage_gib,
        min_mmap_available_memory_gib=args.min_mmap_available_memory_gib,
        threads=args.threads,
        workspace_multiplier=args.workspace_multiplier,
        require_external_assets=not args.skip_external_assets,
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "status": payload["status"],
                "launchable_for_execution": payload["launchable_for_execution"],
                "preflight_path": payload["preflight_path"],
                "proof_volume_report_path": payload["proof_volume_report_path"],
                "proof_package_path": payload["proof_package_path"],
                "heavy_generation_started": payload["heavy_generation_started"],
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

#!/usr/bin/env python
"""Write an auditable machine preflight for cloud hard-tail proof runs."""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rubik_optimal.results import write_json  # noqa: E402
from rubik_optimal.tables.h48 import (  # noqa: E402
    H48_TABLE_ROOT_ENV,
    canonical_h48_solver,
    estimated_h48_table_size_bytes,
    h48_table_root,
    validate_trusted_h48_table_checksum,
)
from scripts.inspect_h48_capacity import evaluate_h48_generation_safety  # noqa: E402


def _gib(bytes_value: int | None) -> float | None:
    if bytes_value is None:
        return None
    return round(bytes_value / (1024**3), 6)


def _bytes_from_gib(value: float | None) -> int | None:
    if value is None:
        return None
    return int(math.ceil(float(value) * 1024**3))


def _tool_status(names: list[str]) -> dict[str, str | None]:
    return {name: shutil.which(name) for name in names}


def _required_external_paths(root: Path) -> list[Path]:
    return [
        root / ".codex_external" / "nissy-2.0.8" / "nissy",
        root / ".codex_external" / "nissy_data" / "tables" / "pt_nxopt31_HTM",
        root / ".codex_external" / "rubikoptimal_tables" / "phase1x24_prun",
    ]


def _relative(root: Path, path: Path) -> str:
    return str(path.relative_to(root)) if path.is_relative_to(root) else str(path)


def build_preflight_payload(
    *,
    root: Path,
    profile: str,
    seed: int,
    solver: str,
    min_cpus: int,
    min_memory_gib: float,
    min_free_disk_gib: float,
    min_storage_gib: float,
    threads: int,
    require_external_assets: bool,
    require_target_table: bool,
    disk_multiplier: float | None = None,
    assume_cpu_count: int | None = None,
    assume_memory_gib: float | None = None,
    assume_available_memory_gib: float | None = None,
    assume_free_disk_gib: float | None = None,
    assume_total_storage_gib: float | None = None,
) -> dict[str, Any]:
    """Return a pass/fail cloud preflight payload without running heavy search."""

    canonical_solver = canonical_h48_solver(solver)
    assumed_machine = any(
        value is not None
        for value in (
            assume_cpu_count,
            assume_memory_gib,
            assume_available_memory_gib,
            assume_free_disk_gib,
            assume_total_storage_gib,
        )
    )
    safety = evaluate_h48_generation_safety(
        root=root,
        solver=canonical_solver,
        threads=threads,
        disk_multiplier=disk_multiplier,
    )
    machine = dict(safety.get("machine") or {})
    disk_root = h48_table_root(root=root)
    disk_root.mkdir(parents=True, exist_ok=True)
    disk_usage = shutil.disk_usage(disk_root)
    if assume_cpu_count is not None:
        machine["cpu_count"] = int(assume_cpu_count)
    if assume_memory_gib is not None:
        machine["memory_bytes"] = _bytes_from_gib(assume_memory_gib)
    if assume_available_memory_gib is not None:
        machine["available_memory_bytes"] = _bytes_from_gib(assume_available_memory_gib)
    elif assume_memory_gib is not None:
        machine["available_memory_bytes"] = _bytes_from_gib(assume_memory_gib)
    if assume_free_disk_gib is not None:
        machine["data_generated_h48_free_bytes"] = _bytes_from_gib(assume_free_disk_gib)
    if assumed_machine:
        machine["load_average"] = (0.0, 0.0, 0.0)
        safety["machine"] = machine
        safety["assumed_machine"] = True

    cpu_count = int(machine.get("cpu_count") or os.cpu_count() or 1)
    memory_bytes = machine.get("memory_bytes")
    free_disk_bytes = machine.get("data_generated_h48_free_bytes")
    total_storage_bytes = _bytes_from_gib(assume_total_storage_gib) or disk_usage.total
    memory_gib = _gib(int(memory_bytes)) if memory_bytes is not None else None
    free_disk_gib = _gib(int(free_disk_bytes)) if free_disk_bytes is not None else None
    total_storage_gib = _gib(total_storage_bytes)
    tool_paths = _tool_status(["python", "cc", "c++", "tar", "gzip"])
    target_table_size_bytes = estimated_h48_table_size_bytes(canonical_solver)
    safety_policy = dict(safety.get("policy") or {})
    workspace_multiplier = float(safety_policy.get("disk_multiplier") or 2.0)
    required_workspace_bytes = int(math.ceil(target_table_size_bytes * workspace_multiplier))
    required_workspace_gib = _gib(required_workspace_bytes)
    workspace_headroom_bytes = (
        int(free_disk_bytes) - required_workspace_bytes if free_disk_bytes is not None else None
    )
    workspace_satisfies = (
        bool(int(free_disk_bytes) >= required_workspace_bytes)
        if free_disk_bytes is not None
        else None
    )
    if assumed_machine:
        assumed_safety_reasons: list[str] = []
        available_memory_bytes = machine.get("available_memory_bytes")
        min_mmap_available = int(
            (safety_policy.get("min_mmap_available_memory_bytes") or 4 * 1024**3)
        )
        if available_memory_bytes is None:
            assumed_safety_reasons.append("assumed available memory is unavailable")
        elif int(available_memory_bytes) < min_mmap_available:
            assumed_safety_reasons.append(
                "assumed available memory is below the mmap generation guard"
            )
        if workspace_satisfies is False:
            assumed_safety_reasons.append("assumed free disk is below the required H48 workspace")
        if max(1, threads) > cpu_count:
            assumed_safety_reasons.append("requested threads exceed assumed CPU count")
        safety["reasons"] = assumed_safety_reasons
        safety["safe_to_start"] = not assumed_safety_reasons

    reasons: list[str] = []
    if cpu_count < min_cpus:
        reasons.append(f"cpu_count {cpu_count} is below required {min_cpus}")
    if memory_gib is None:
        reasons.append("total RAM could not be detected")
    elif memory_gib < min_memory_gib:
        reasons.append(f"memory_gib {memory_gib:.3f} is below required {min_memory_gib:.3f}")
    if free_disk_gib is None:
        reasons.append("free disk could not be detected")
    elif free_disk_gib < min_free_disk_gib:
        reasons.append(f"free_disk_gib {free_disk_gib:.3f} is below required {min_free_disk_gib:.3f}")
    if total_storage_gib is None:
        reasons.append("total storage could not be detected")
    elif total_storage_gib < min_storage_gib:
        reasons.append(
            f"data_generated_h48_total_gib {total_storage_gib:.3f} is below required "
            f"{min_storage_gib:.3f}"
        )
    if workspace_satisfies is False:
        reasons.append(
            f"free disk {free_disk_gib:.3f} GiB is below required H48 workspace "
            f"{required_workspace_gib:.3f} GiB for {canonical_solver}"
        )
    for tool_name, tool_path in tool_paths.items():
        if tool_path is None:
            reasons.append(f"required tool not found on PATH: {tool_name}")

    required_repo_paths = [
        root / "scripts" / "run_cloud_hardtail_campaign.py",
        root / "scripts" / "evaluate_cloud_hardtail_campaign.py",
        root / "scripts" / "generate_h48_oracle_contract.py",
        root / "scripts" / "thesis_audit.py",
    ]
    missing_repo_paths = [str(path.relative_to(root)) for path in required_repo_paths if not path.exists()]
    for path in missing_repo_paths:
        reasons.append(f"required repository path missing: {path}")

    missing_external_paths: list[str] = []
    if require_external_assets:
        missing_external_paths = [
            str(path.relative_to(root))
            for path in _required_external_paths(root)
            if not path.exists()
        ]
        for path in missing_external_paths:
            reasons.append(f"required external asset missing: {path}")

    target_table_validation: dict[str, Any] | None = None
    if require_target_table:
        target_ok, target_message, target_details = validate_trusted_h48_table_checksum(
            root=root,
            profile=profile,
            seed=seed,
            solver=canonical_solver,
            persistent_cache=True,
        )
        target_table_validation = {
            "passed": target_ok,
            "message": target_message,
            **target_details,
        }
        if not target_ok:
            reasons.append(f"target H48 table validation failed: {target_message}")

    passed = not reasons
    return {
        "schema_version": 1,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "profile": profile,
        "seed": seed,
        "solver": canonical_solver,
        "min_cpus": min_cpus,
        "min_memory_gib": min_memory_gib,
        "min_free_disk_gib": min_free_disk_gib,
        "min_storage_gib": min_storage_gib,
        "threads": max(1, threads),
        "machine_source": "assumed" if assumed_machine else "local",
        "assumed_machine_not_runtime_evidence": bool(assumed_machine),
        "assumed_machine": {
            "cpu_count": assume_cpu_count,
            "memory_gib": assume_memory_gib,
            "available_memory_gib": assume_available_memory_gib
            if assume_available_memory_gib is not None
            else assume_memory_gib,
            "data_generated_h48_free_gib": assume_free_disk_gib,
            "data_generated_h48_total_gib": assume_total_storage_gib,
        }
        if assumed_machine
        else None,
        "machine": {
            "cpu_count": cpu_count,
            "load_average": machine.get("load_average"),
            "memory_bytes": memory_bytes,
            "memory_gib": memory_gib,
            "h48_table_root_env": H48_TABLE_ROOT_ENV,
            "h48_table_root": _relative(root, disk_root),
            "data_generated_h48_total_bytes": total_storage_bytes,
            "data_generated_h48_total_gib": total_storage_gib,
            "data_generated_h48_free_bytes": free_disk_bytes,
            "data_generated_h48_free_gib": free_disk_gib,
            "h48_table_root_total_bytes": total_storage_bytes,
            "h48_table_root_total_gib": total_storage_gib,
            "h48_table_root_free_bytes": free_disk_bytes,
            "h48_table_root_free_gib": free_disk_gib,
        },
        "target_h48_workspace": {
            "solver": canonical_solver,
            "target_table_size_bytes": target_table_size_bytes,
            "target_table_size_gib": _gib(target_table_size_bytes),
            "workspace_multiplier": workspace_multiplier,
            "required_workspace_bytes": required_workspace_bytes,
            "required_workspace_gib": required_workspace_gib,
            "available_workspace_bytes": free_disk_bytes,
            "available_workspace_gib": free_disk_gib,
            "workspace_headroom_bytes": workspace_headroom_bytes,
            "workspace_headroom_gib": _gib(workspace_headroom_bytes)
            if workspace_headroom_bytes is not None
            else None,
            "satisfies_workspace": workspace_satisfies,
        },
        "tool_paths": tool_paths,
        "generation_safety": safety,
        "require_external_assets": require_external_assets,
        "missing_external_paths": missing_external_paths,
        "require_target_table": require_target_table,
        "target_table_validation": target_table_validation,
        "reasons": reasons,
        "passed": passed,
        "fast_runtime_proven_for_every_possible_state": False,
        "notes": (
            f"Preflight gate for {canonical_solver} H48 hard-tail proof execution. "
            "A pass only means the machine/repo/table prerequisites are plausible; "
            "it is not runtime evidence and does not prove the every-state fast oracle claim."
            if not assumed_machine
            else (
                "This is an assumed-machine shape check only. It is not evidence that a real "
                "host exists, that the H48 table was generated, or that any runtime workload passed."
            )
        ),
    }


def write_preflight(
    *,
    root: Path,
    profile: str,
    seed: int,
    solver: str,
    artifact_suffix: str,
    min_cpus: int,
    min_memory_gib: float,
    min_free_disk_gib: float,
    min_storage_gib: float,
    threads: int,
    require_external_assets: bool,
    require_target_table: bool,
    disk_multiplier: float | None = None,
    assume_cpu_count: int | None = None,
    assume_memory_gib: float | None = None,
    assume_available_memory_gib: float | None = None,
    assume_free_disk_gib: float | None = None,
    assume_total_storage_gib: float | None = None,
) -> tuple[dict[str, Any], Path]:
    payload = build_preflight_payload(
        root=root,
        profile=profile,
        seed=seed,
        solver=solver,
        min_cpus=min_cpus,
        min_memory_gib=min_memory_gib,
        min_free_disk_gib=min_free_disk_gib,
        min_storage_gib=min_storage_gib,
        threads=threads,
        require_external_assets=require_external_assets,
        require_target_table=require_target_table,
        disk_multiplier=disk_multiplier,
        assume_cpu_count=assume_cpu_count,
        assume_memory_gib=assume_memory_gib,
        assume_available_memory_gib=assume_available_memory_gib,
        assume_free_disk_gib=assume_free_disk_gib,
        assume_total_storage_gib=assume_total_storage_gib,
    )
    suffix_parts = [f"seed_{seed}", profile, payload["solver"]]
    if artifact_suffix:
        suffix_parts.append(artifact_suffix)
    output = root / "results" / "processed" / f"cloud_hardtail_preflight_{'_'.join(suffix_parts)}.json"
    write_json(output, payload)
    return payload, output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default="thesis")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--solver", default="h48h8")
    parser.add_argument("--artifact-suffix", default="cloud")
    parser.add_argument("--min-cpus", type=int, default=16)
    parser.add_argument("--min-memory-gib", type=float, default=64.0)
    parser.add_argument(
        "--min-free-disk-gib",
        type=float,
        default=0.0,
        help=(
            "Additional fixed free-space floor. The H48 table workspace gate is computed "
            "separately from the target solver and is normally the meaningful free-space check."
        ),
    )
    parser.add_argument(
        "--min-storage-gib",
        type=float,
        default=250.0,
        help="Minimum total local storage size for the proof workspace volume.",
    )
    parser.add_argument("--threads", type=int, default=16)
    parser.add_argument(
        "--disk-multiplier",
        type=float,
        default=None,
        help=(
            "Override the H48 table workspace multiplier. Defaults follow the generation storage mode "
            "recorded by the H48 safety helper."
        ),
    )
    parser.add_argument("--skip-external-assets", action="store_true")
    parser.add_argument("--require-target-table", action="store_true")
    parser.add_argument("--assume-cpu-count", type=int, default=None)
    parser.add_argument("--assume-memory-gib", type=float, default=None)
    parser.add_argument("--assume-available-memory-gib", type=float, default=None)
    parser.add_argument("--assume-free-disk-gib", type=float, default=None)
    parser.add_argument("--assume-total-storage-gib", type=float, default=None)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()

    payload, output = write_preflight(
        root=args.root,
        profile=args.profile,
        seed=args.seed,
        solver=args.solver,
        artifact_suffix=args.artifact_suffix,
        min_cpus=args.min_cpus,
        min_memory_gib=args.min_memory_gib,
        min_free_disk_gib=args.min_free_disk_gib,
        min_storage_gib=args.min_storage_gib,
        threads=args.threads,
        require_external_assets=not args.skip_external_assets,
        require_target_table=args.require_target_table,
        disk_multiplier=args.disk_multiplier,
        assume_cpu_count=args.assume_cpu_count,
        assume_memory_gib=args.assume_memory_gib,
        assume_available_memory_gib=args.assume_available_memory_gib,
        assume_free_disk_gib=args.assume_free_disk_gib,
        assume_total_storage_gib=args.assume_total_storage_gib,
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "solver": payload["solver"],
                "passed": payload["passed"],
                "reasons": payload["reasons"],
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

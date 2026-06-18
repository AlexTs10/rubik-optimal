#!/usr/bin/env python
"""Inspect local/non-AWS H48 proof-volume candidates without starting generation."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shlex
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rubik_optimal.results import write_json  # noqa: E402
from rubik_optimal.runtime import available_memory_bytes  # noqa: E402
from rubik_optimal.tables.h48 import (  # noqa: E402
    DEFAULT_H48_GENDATA_WORKBATCH,
    H48_TABLE_ROOT_ENV,
    canonical_h48_solver,
    estimated_h48_table_size_bytes,
    h48_table_root,
)
from scripts.inspect_h48_capacity import (  # noqa: E402
    H48_MMAP_GENERATION_DISK_MULTIPLIER,
    _load_average,
    _memory_bytes,
)


def _gib(bytes_value: int | None) -> float | None:
    if bytes_value is None:
        return None
    return round(bytes_value / (1024**3), 6)


def _bytes_from_gib(value: float) -> int:
    return int(math.ceil(float(value) * 1024**3))


def _relative(root: Path, path: Path) -> str:
    return str(path.relative_to(root)) if path.is_relative_to(root) else str(path)


def _safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value)).strip("_") or "local"


def _nearest_existing_parent(path: Path) -> Path | None:
    current = path
    while not current.exists():
        parent = current.parent
        if parent == current:
            return None
        current = parent
    return current


def _dedupe_candidates(rows: list[tuple[str, str, Path]]) -> list[tuple[str, str, Path]]:
    seen: set[str] = set()
    deduped: list[tuple[str, str, Path]] = []
    for source, label, path in rows:
        key = str(path.expanduser().resolve(strict=False))
        if key in seen:
            continue
        seen.add(key)
        deduped.append((source, label, path.expanduser()))
    return deduped


def _default_candidates(
    *,
    root: Path,
    include_configured_root: bool,
    include_volume_roots: bool,
    volume_root: Path,
    explicit_candidates: list[Path],
) -> list[tuple[str, str, Path]]:
    rows: list[tuple[str, str, Path]] = []
    if include_configured_root:
        source = "configured" if os.environ.get(H48_TABLE_ROOT_ENV) else "default"
        rows.append((source, source, h48_table_root(root=root)))
    if include_volume_roots and volume_root.exists():
        for volume in sorted(volume_root.iterdir(), key=lambda item: item.name.lower()):
            if volume.is_dir():
                rows.append(("mounted_volume", volume.name, volume / "h48"))
    rows.extend(("explicit", path.name or "explicit", path) for path in explicit_candidates)
    return _dedupe_candidates(rows)


def _inspect_candidate(
    *,
    root: Path,
    source: str,
    label: str,
    candidate_root: Path,
    solver: str,
    min_storage_gib: float,
    required_workspace_bytes: int,
    host_machine_satisfies: bool,
    available_memory_satisfies: bool,
    threads_satisfy_cpu: bool,
) -> dict[str, Any]:
    parent = _nearest_existing_parent(candidate_root)
    disk = shutil.disk_usage(parent) if parent is not None else None
    free_bytes = int(disk.free) if disk is not None else None
    total_bytes = int(disk.total) if disk is not None else None
    workspace_headroom = free_bytes - required_workspace_bytes if free_bytes is not None else None
    storage_satisfies = total_bytes is not None and total_bytes >= _bytes_from_gib(min_storage_gib)
    workspace_satisfies = free_bytes is not None and free_bytes >= required_workspace_bytes
    parent_writable = bool(parent is not None and os.access(parent, os.W_OK))
    launchable = (
        host_machine_satisfies
        and available_memory_satisfies
        and threads_satisfy_cpu
        and storage_satisfies
        and workspace_satisfies
        and parent_writable
    )
    quoted_root = shlex.quote(str(candidate_root))
    preflight_command = (
        f"{H48_TABLE_ROOT_ENV}={quoted_root} python scripts/cloud_hardtail_preflight.py "
        f"--profile thesis --seed 2026 --solver {solver} --artifact-suffix live_proof_volume "
        "--min-cpus 16 --min-memory-gib 64 --min-free-disk-gib 0 --min-storage-gib "
        f"{min_storage_gib:g} --threads 16 --skip-external-assets"
    )
    generation_command = (
        f"{H48_TABLE_ROOT_ENV}={quoted_root} nice -n 20 python scripts/generate_h48_tables.py "
        f"--profile thesis --seed 2026 --solver {solver} --threads 16 --mmap-output "
        "--progress-log --require-safe "
        f"--gendata-workbatch {DEFAULT_H48_GENDATA_WORKBATCH} "
        "--skip-generation-distribution-scan --mmap-sync-mode async --backend-cflag=-march=native"
    )
    return {
        "source": source,
        "label": label,
        "solver": solver,
        "h48_table_root": _relative(root, candidate_root),
        "h48_table_root_absolute": str(candidate_root.resolve(strict=False)),
        "exists": candidate_root.exists(),
        "nearest_existing_parent": _relative(root, parent) if parent is not None else None,
        "nearest_existing_parent_absolute": str(parent.resolve(strict=False)) if parent is not None else None,
        "nearest_existing_parent_writable": parent_writable,
        "disk_total_bytes": total_bytes,
        "disk_total_gib": _gib(total_bytes),
        "disk_free_bytes": free_bytes,
        "disk_free_gib": _gib(free_bytes),
        "min_storage_gib": min_storage_gib,
        "satisfies_storage_class": storage_satisfies,
        "required_workspace_bytes": required_workspace_bytes,
        "required_workspace_gib": _gib(required_workspace_bytes),
        "workspace_headroom_bytes": workspace_headroom,
        "workspace_headroom_gib": _gib(workspace_headroom),
        "satisfies_workspace": workspace_satisfies,
        "host_machine_satisfies": host_machine_satisfies,
        "available_memory_satisfies": available_memory_satisfies,
        "threads_satisfy_cpu": threads_satisfy_cpu,
        "launchable_for_h48_generation": launchable,
        "recommended_preflight_command": preflight_command,
        "recommended_generation_command_after_approval": generation_command,
    }


def build_proof_volume_payload(
    *,
    root: Path,
    profile: str,
    seed: int,
    solver: str,
    min_cpus: int = 16,
    min_memory_gib: float = 64.0,
    min_storage_gib: float = 250.0,
    min_mmap_available_memory_gib: float = 4.0,
    threads: int = 16,
    workspace_multiplier: float = H48_MMAP_GENERATION_DISK_MULTIPLIER,
    include_configured_root: bool = True,
    include_volume_roots: bool = True,
    volume_root: Path = Path("/Volumes"),
    candidate_roots: list[Path] | None = None,
) -> dict[str, Any]:
    """Return an auditable proof-volume launchability report.

    This function never starts H48 generation and does not create candidate
    directories.  It only inspects the nearest existing parent for disk space.
    """

    canonical_solver = canonical_h48_solver(solver)
    cpu_count = int(os.cpu_count() or 1)
    memory_bytes = _memory_bytes()
    memory_gib = _gib(memory_bytes)
    available_bytes = available_memory_bytes()
    available_memory_gib = _gib(available_bytes)
    load_average = _load_average()
    table_size_bytes = estimated_h48_table_size_bytes(canonical_solver)
    required_workspace_bytes = int(math.ceil(table_size_bytes * float(workspace_multiplier)))
    host_machine_satisfies = (
        cpu_count >= min_cpus
        and memory_bytes is not None
        and memory_bytes >= _bytes_from_gib(min_memory_gib)
    )
    available_memory_satisfies = (
        available_bytes is not None and available_bytes >= _bytes_from_gib(min_mmap_available_memory_gib)
    )
    threads_satisfy_cpu = max(1, int(threads)) <= cpu_count
    candidate_specs = _default_candidates(
        root=root,
        include_configured_root=include_configured_root,
        include_volume_roots=include_volume_roots,
        volume_root=volume_root,
        explicit_candidates=list(candidate_roots or []),
    )
    candidates = [
        _inspect_candidate(
            root=root,
            source=source,
            label=label,
            candidate_root=path,
            solver=canonical_solver,
            min_storage_gib=min_storage_gib,
            required_workspace_bytes=required_workspace_bytes,
            host_machine_satisfies=host_machine_satisfies,
            available_memory_satisfies=available_memory_satisfies,
            threads_satisfy_cpu=threads_satisfy_cpu,
        )
        for source, label, path in candidate_specs
    ]
    launchable = [row for row in candidates if row["launchable_for_h48_generation"] is True]
    ranked = sorted(
        candidates,
        key=lambda row: (
            bool(row["launchable_for_h48_generation"]),
            bool(row["satisfies_workspace"]),
            bool(row["satisfies_storage_class"]),
            int(row.get("disk_free_bytes") or -1),
        ),
        reverse=True,
    )
    machine_reasons: list[str] = []
    if cpu_count < min_cpus:
        machine_reasons.append(f"cpu_count {cpu_count} is below required {min_cpus}")
    if memory_gib is None:
        machine_reasons.append("total RAM could not be detected")
    elif memory_gib < min_memory_gib:
        machine_reasons.append(f"memory_gib {memory_gib:.3f} is below required {min_memory_gib:.3f}")
    if available_memory_gib is None:
        machine_reasons.append("available memory could not be detected")
    elif available_memory_gib < min_mmap_available_memory_gib:
        machine_reasons.append(
            f"available_memory_gib {available_memory_gib:.3f} is below required "
            f"{min_mmap_available_memory_gib:.3f}"
        )
    if not threads_satisfy_cpu:
        machine_reasons.append(f"threads {threads} exceeds cpu_count {cpu_count}")
    return {
        "schema_version": 1,
        "artifact_kind": "h48_proof_volume_candidates",
        "checked_at_utc": datetime.now(UTC).isoformat(),
        "profile": profile,
        "seed": int(seed),
        "solver": canonical_solver,
        "h48_table_root_env": H48_TABLE_ROOT_ENV,
        "machine_source": "local",
        "machine": {
            "cpu_count": cpu_count,
            "load_average": load_average,
            "memory_bytes": memory_bytes,
            "memory_gib": memory_gib,
            "available_memory_bytes": available_bytes,
            "available_memory_gib": available_memory_gib,
        },
        "requirements": {
            "min_cpus": int(min_cpus),
            "min_memory_gib": float(min_memory_gib),
            "min_storage_gib": float(min_storage_gib),
            "min_mmap_available_memory_gib": float(min_mmap_available_memory_gib),
            "threads": int(threads),
            "target_table_size_bytes": table_size_bytes,
            "target_table_size_gib": _gib(table_size_bytes),
            "workspace_multiplier": float(workspace_multiplier),
            "required_workspace_bytes": required_workspace_bytes,
            "required_workspace_gib": _gib(required_workspace_bytes),
        },
        "machine_reasons": machine_reasons,
        "host_machine_satisfies": host_machine_satisfies,
        "available_memory_satisfies": available_memory_satisfies,
        "threads_satisfy_cpu": threads_satisfy_cpu,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "best_candidate": ranked[0] if ranked else None,
        "launchable_candidate_count": len(launchable),
        "launchable_candidates": launchable,
        "launchable_for_h48_generation": bool(launchable),
        "fast_runtime_proven_for_every_possible_state": False,
        "notes": (
            "This is a local/non-AWS proof-host and proof-volume launch gate. "
            "It does not generate the H48 table and does not prove the every-state fast oracle claim."
        ),
    }


def _write_table(root: Path, payload: dict[str, Any], suffix: str) -> Path:
    output = root / "thesis" / "tables" / f"h48_proof_volume_candidates{suffix}.tex"
    output.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for row in payload["candidates"]:
        rows.append(
            f"{row['source']}:{row['label']} & "
            f"{row['disk_total_gib']} & "
            f"{row['disk_free_gib']} & "
            f"{row['satisfies_workspace']} & "
            f"{row['launchable_for_h48_generation']} \\\\"
        )
    output.write_text(
        "{\\small\n"
        "\\begin{tabular}{lrrrr}\n"
        "\\hline\n"
        "Candidate & Total GiB & Free GiB & Workspace & Launchable \\\\\n"
        "\\hline\n"
        + "\n".join(rows)
        + "\n\\hline\n"
        "\\end{tabular}\n"
        "}\n",
        encoding="utf-8",
    )
    return output


def write_proof_volume_report(
    *,
    root: Path,
    profile: str,
    seed: int,
    solver: str,
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
) -> tuple[dict[str, Any], Path, Path]:
    payload = build_proof_volume_payload(
        root=root,
        profile=profile,
        seed=seed,
        solver=solver,
        min_cpus=min_cpus,
        min_memory_gib=min_memory_gib,
        min_storage_gib=min_storage_gib,
        min_mmap_available_memory_gib=min_mmap_available_memory_gib,
        threads=threads,
        workspace_multiplier=workspace_multiplier,
        include_configured_root=include_configured_root,
        include_volume_roots=include_volume_roots,
        volume_root=volume_root,
        candidate_roots=candidate_roots,
    )
    suffix_parts = [f"seed_{seed}", profile, payload["solver"]]
    if artifact_suffix:
        suffix_parts.append(_safe_id(artifact_suffix))
    suffix = "_" + "_".join(suffix_parts)
    output = root / "results" / "processed" / f"h48_proof_volume_candidates{suffix}.json"
    write_json(output, payload)
    table = _write_table(root, payload, suffix)
    return payload, output, table


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default="thesis")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--solver", default="h48h10")
    parser.add_argument("--artifact-suffix", default="local_noaws_current")
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
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()

    payload, output, table = write_proof_volume_report(
        root=args.root,
        profile=args.profile,
        seed=args.seed,
        solver=args.solver,
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
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "table": str(table),
                "solver": payload["solver"],
                "launchable_for_h48_generation": payload["launchable_for_h48_generation"],
                "launchable_candidate_count": payload["launchable_candidate_count"],
                "machine_reasons": payload["machine_reasons"],
                "fast_runtime_proven_for_every_possible_state": payload[
                    "fast_runtime_proven_for_every_possible_state"
                ],
            },
            indent=2,
        )
    )
    return 0 if payload["launchable_for_h48_generation"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

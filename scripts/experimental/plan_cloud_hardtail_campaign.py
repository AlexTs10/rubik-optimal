#!/usr/bin/env python
"""Plan cloud workloads for the all-state fast optimal-oracle claim."""

from __future__ import annotations

import argparse
import json
import math
import shlex
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rubik_optimal.results import write_json  # noqa: E402
from rubik_optimal.tables.h48 import (  # noqa: E402
    ORACLE_H48_SOLVER,
    canonical_h48_solver,
    estimated_h48_table_size_bytes,
    h48_table_path,
    normalize_h48_backend_extra_cflags,
    normalize_h48_mmap_sync_mode,
    resolve_h48_gendata_workbatch,
)


@dataclass(frozen=True)
class OffsetRange:
    start: int
    end: int


def _scramble_count(root: Path, distance: int) -> int:
    path = root / ".codex_external" / "nissy-core" / "benchmarks" / "scrambles" / f"scrambles-{distance}.txt"
    if not path.exists():
        raise SystemExit(f"missing nissy-core benchmark scramble file: {path}")
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def _relative_or_absolute(root: Path, path: Path) -> str:
    return str(path.relative_to(root)) if path.is_relative_to(root) else str(path)


def _offset_ranges(*, start: int, end: int, shard_size: int) -> list[OffsetRange]:
    if start < 0:
        raise ValueError("start offset must be non-negative")
    if end <= start:
        raise ValueError("end offset must be greater than start offset")
    size = max(1, int(shard_size))
    ranges: list[OffsetRange] = []
    cursor = start
    while cursor < end:
        next_end = min(end, cursor + size)
        ranges.append(OffsetRange(cursor, next_end))
        cursor = next_end
    return ranges


def _shell_command(command: list[str], env: dict[str, str]) -> str:
    env_prefix = ["env", *(f"{key}={value}" for key, value in sorted(env.items()))]
    return shlex.join([*env_prefix, *command])


def _workload(
    *,
    workload_id: str,
    kind: str,
    command_args: list[str],
    env: dict[str, str],
    expected_artifacts: list[str],
    proves: str,
    required_for_claim: bool = True,
    estimated_wall_seconds: float | None = None,
    depends_on_workload_ids: list[str] | None = None,
    notes: str = "",
) -> dict[str, Any]:
    return {
        "id": workload_id,
        "kind": kind,
        "command_args": command_args,
        "environment": env,
        "shell_command": _shell_command(command_args, env),
        "expected_artifacts": expected_artifacts,
        "estimated_wall_seconds": estimated_wall_seconds,
        "proves": proves,
        "required_for_fast_every_state_claim": required_for_claim,
        "depends_on_workload_ids": depends_on_workload_ids or [],
        "run_on_cloud_or_idle_large_machine": True,
        "notes": notes,
    }


def _hardtail_per_row_estimate_seconds(
    *,
    hardtail_strategy: str,
    h48_timeout_seconds: float,
    prepass_timeout_seconds: float,
    fallback_timeout_seconds: float,
    h48_upper_bound_proof_timeout_seconds: float,
    rubikoptimal_timeout_seconds: float,
    symmetry_timeout_seconds: float,
) -> float:
    if hardtail_strategy == "native-h48-only":
        return h48_timeout_seconds
    return (
        h48_timeout_seconds
        + prepass_timeout_seconds
        + fallback_timeout_seconds
        + h48_upper_bound_proof_timeout_seconds
        + (rubikoptimal_timeout_seconds * 4)
        + (symmetry_timeout_seconds * 3)
    )


def _ceil_to(value: float, quantum: int) -> int:
    return int(math.ceil(value / quantum) * quantum)


def _recommended_cloud_machine(
    *,
    worker_threads: int,
    target_solver: str,
) -> dict[str, Any]:
    target_solver = canonical_h48_solver(target_solver)
    target_table_bytes = estimated_h48_table_size_bytes(target_solver)
    target_table_gib = target_table_bytes / (1024**3)
    memory_gib = max(64, _ceil_to(target_table_gib * 2.0, 32))
    local_nvme_gib = max(250, _ceil_to(target_table_gib * 6.0, 250))
    return {
        "cpu_count": max(16, worker_threads),
        "memory_gib": memory_gib,
        "local_nvme_gib": local_nvme_gib,
        "h48_target_solver": target_solver,
        "h48_target_table_size_bytes": target_table_bytes,
        "h48_target_table_size_gib": round(target_table_gib, 6),
        "reason": (
            f"distance-20 hard-tail live exact search and {target_solver} table generation are "
            f"memory/I/O sensitive; the target table alone is about {target_table_gib:.2f} GiB, "
            "so the local 16 GiB Mac is not an appropriate proof machine under load"
        ),
    }


def _hardtail_direct_batch_command(
    *,
    python_executable: str,
    profile: str,
    seed: int,
    solver: str,
    distance: int,
    offset_range: OffsetRange,
    h48_timeout_seconds: float,
    prepass_timeout_seconds: float,
    fallback_timeout_seconds: float,
    h48_upper_bound_proof_timeout_seconds: float,
    h48_upper_bound_proof_max_gap: int,
    rubikoptimal_timeout_seconds: float,
    symmetry_timeout_seconds: float,
    symmetry_max_concurrency: int,
    worker_threads: int,
    command_timeout_seconds: float,
    label: str,
    hardtail_strategy: str,
) -> list[str]:
    range_size = offset_range.end - offset_range.start
    concurrency = max(1, int(symmetry_max_concurrency))
    command = [
        python_executable,
        "scripts/run_universal_oracle_cli.py",
        "--profile",
        profile,
        "--seed",
        str(seed),
        "--solver",
        solver,
        "--no-random-cases",
        "--benchmark-distance",
        str(distance),
        "--benchmark-limit-per-distance",
        str(range_size),
        "--benchmark-offset-per-distance",
        str(offset_range.start),
        "--timeout",
        str(h48_timeout_seconds),
        "--resident-h48-batch-timeout",
        str(h48_timeout_seconds),
        "--command-timeout",
        str(command_timeout_seconds),
        "--threads",
        str(worker_threads),
        "--trusted-table",
        "--no-certificate-cache",
    ]
    if hardtail_strategy == "native-h48-only":
        command.extend(
            [
                "--no-portfolio-prepass",
                "--universal-portfolio-fallback-timeout",
                "0.0",
                "--universal-fallback-nissy-core-direct-timeout",
                "-1.0",
                "--h48-upper-bound-proof-timeout",
                "0.0",
                "--h48-upper-bound-proof-max-gap",
                str(max(1, int(h48_upper_bound_proof_max_gap))),
                "--no-upper-lower-certificate",
                "--require-resident-h48-batch-for-all",
                "--artifact-suffix",
                label,
            ]
        )
        return command
    command.extend(
        [
        "--universal-portfolio-prepass-timeout",
        str(prepass_timeout_seconds),
        "--universal-portfolio-fallback-timeout",
        str(fallback_timeout_seconds),
        "--universal-fallback-nissy-core-direct-timeout",
        str(symmetry_timeout_seconds),
        "--universal-resident-race-prepass-timeout",
        str(symmetry_timeout_seconds),
        "--universal-rubikoptimal-prepass-timeout",
        str(rubikoptimal_timeout_seconds),
        "--universal-rubikoptimal-race-timeout",
        str(rubikoptimal_timeout_seconds),
        "--universal-rubikoptimal-fallback-timeout",
        str(rubikoptimal_timeout_seconds),
        "--universal-rubikoptimal-symmetry-variants",
        "23",
        "--universal-rubikoptimal-symmetry-timeout",
        str(rubikoptimal_timeout_seconds),
        "--universal-rubikoptimal-symmetry-max-concurrency",
        str(concurrency),
        "--nissy-symmetry-variants",
        "23",
        "--nissy-symmetry-timeout",
        str(symmetry_timeout_seconds),
        "--nissy-core-direct-symmetry-variants",
        "23",
        "--nissy-core-direct-symmetry-timeout",
        str(symmetry_timeout_seconds),
        "--nissy-core-direct-symmetry-max-concurrency",
        str(concurrency),
        "--h48-parallel-symmetry-variants",
        "23",
        "--h48-parallel-symmetry-timeout",
        str(h48_timeout_seconds),
        "--h48-parallel-symmetry-max-concurrency",
        str(concurrency),
        "--symmetry-order-by-h48-lower-bound",
        "--symmetry-lower-bound-order-timeout",
        str(min(120.0, max(30.0, prepass_timeout_seconds))),
        "--h48-upper-bound-proof-timeout",
        str(h48_upper_bound_proof_timeout_seconds),
        "--h48-upper-bound-proof-max-gap",
        str(max(1, int(h48_upper_bound_proof_max_gap))),
        "--artifact-suffix",
        label,
        ]
    )
    if h48_upper_bound_proof_timeout_seconds <= 0.0:
        command.append("--no-upper-lower-certificate")
    return command


def _h48_stronger_table_workload(
    *,
    root: Path,
    python_executable: str,
    profile: str,
    seed: int,
    target: str,
    worker_threads: int,
    h48_table_generation_timeout_seconds: float,
    runtime_target_seconds: float,
    h48_timeout_seconds: float,
    artifact_suffix: str,
    env: dict[str, str],
    gendata_workbatch: int | str | None = None,
    skip_generation_distribution_scan: bool = False,
    mmap_sync_mode: str = "sync",
    backend_extra_cflags: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    resolved_workbatch = resolve_h48_gendata_workbatch(gendata_workbatch)
    resolved_mmap_sync_mode = normalize_h48_mmap_sync_mode(mmap_sync_mode)
    resolved_backend_extra_cflags = normalize_h48_backend_extra_cflags(backend_extra_cflags)
    command = [
        python_executable,
        "scripts/run_h48_stronger_table_campaign.py",
        "--profile",
        profile,
        "--seed",
        str(seed),
        "--target-solver",
        target,
        "--threads",
        str(worker_threads),
        "--generation-timeout",
        str(h48_table_generation_timeout_seconds),
        "--certification-timeout",
        str(max(runtime_target_seconds, h48_timeout_seconds)),
        "--runtime-target",
        str(runtime_target_seconds),
        "--artifact-suffix",
        f"{artifact_suffix}_{target}",
        "--gendata-workbatch",
        str(resolved_workbatch),
        "--mmap-sync-mode",
        resolved_mmap_sync_mode,
    ]
    for flag in resolved_backend_extra_cflags:
        command.append(f"--backend-cflag={flag}")
    if skip_generation_distribution_scan:
        command.append("--skip-generation-distribution-scan")
    workload = _workload(
        workload_id=f"stronger_table_{target}",
        kind="h48_stronger_table_generation_and_certification",
        command_args=command,
        env=env,
        expected_artifacts=[
            f"results/processed/h48_stronger_table_campaign_seed_{seed}_{profile}_{target}_{artifact_suffix}_{target}.json",
            f"results/processed/h48_metadata_seed_{seed}_{profile}_{target}.json",
            _relative_or_absolute(
                root,
                h48_table_path(root=root, profile=profile, seed=seed, solver=target),
            ),
        ],
        estimated_wall_seconds=h48_table_generation_timeout_seconds,
        proves=(
            "whether a stronger trusted H48 table can be generated and certified on the cloud machine"
        ),
        notes=(
            "This is the main route toward reducing worst-case H48 search depth variance. "
            "If the hard-tail workloads use this same solver, this workload must finish and its "
            "table plus metadata must be copied to every worker before those workloads start. "
            f"gendata_workbatch={resolved_workbatch}. "
            f"generation_distribution_mode={'expected_constants' if skip_generation_distribution_scan else 'scanned'}. "
            f"mmap_sync_mode={resolved_mmap_sync_mode}. "
            f"backend_extra_cflags={' '.join(resolved_backend_extra_cflags) if resolved_backend_extra_cflags else 'none'}."
        ),
    )
    workload["h48_gendata_workbatch"] = resolved_workbatch
    workload["h48_generation_distribution_mode"] = (
        "expected_constants" if skip_generation_distribution_scan else "scanned"
    )
    workload["h48_generation_distribution_scan_skipped"] = bool(
        skip_generation_distribution_scan
    )
    workload["h48_generation_mmap_sync_mode"] = resolved_mmap_sync_mode
    workload["h48_backend_extra_cflags"] = list(resolved_backend_extra_cflags)
    return workload


def build_cloud_hardtail_plan(
    *,
    root: Path,
    profile: str,
    seed: int,
    solver: str,
    python_executable: str,
    distance: int,
    start_offset: int,
    end_offset: int | None,
    shard_size: int,
    threads: int,
    runtime_target_seconds: float,
    h48_timeout_seconds: float,
    prepass_timeout_seconds: float,
    fallback_timeout_seconds: float,
    h48_upper_bound_proof_timeout_seconds: float,
    h48_upper_bound_proof_max_gap: int,
    rubikoptimal_timeout_seconds: float,
    symmetry_timeout_seconds: float,
    symmetry_max_concurrency: int,
    h48_stronger_target_solver: str,
    h48_table_generation_timeout_seconds: float,
    artifact_suffix: str,
    h48_prerequisite_artifact_suffix: str | None = None,
    claim_scope: str = "full",
    canary_offset_count: int = 3,
    include_h48_stronger_table: bool = True,
    include_rubikoptimal_superflip: bool = True,
    hardtail_execution_mode: str = "sweep",
    hardtail_strategy: str = "portfolio",
    h48_gendata_workbatch: int | str | None = None,
    skip_h48_generation_distribution_scan: bool = False,
    h48_generation_mmap_sync_mode: str = "sync",
    h48_backend_extra_cflags: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    solver = canonical_h48_solver(solver)
    target = canonical_h48_solver(h48_stronger_target_solver)
    resolved_h48_gendata_workbatch = resolve_h48_gendata_workbatch(h48_gendata_workbatch)
    resolved_h48_generation_mmap_sync_mode = normalize_h48_mmap_sync_mode(
        h48_generation_mmap_sync_mode
    )
    resolved_h48_backend_extra_cflags = normalize_h48_backend_extra_cflags(
        h48_backend_extra_cflags
    )
    execution_mode = "batch" if hardtail_execution_mode == "batch" else "sweep"
    available = _scramble_count(root, distance)
    start = max(0, int(start_offset))
    normalized_claim_scope = "canary" if claim_scope == "canary" else "full"
    if end_offset is None and normalized_claim_scope == "canary":
        end = min(available, start + max(1, int(canary_offset_count)))
    else:
        end = available if end_offset is None else min(available, max(start + 1, int(end_offset)))
    ranges = _offset_ranges(start=start, end=end, shard_size=shard_size)
    worker_threads = max(1, int(threads))
    concurrency = max(1, int(symmetry_max_concurrency))
    strategy = "native-h48-only" if hardtail_strategy == "native-h48-only" else "portfolio"
    env = {
        "RUBIK_OPTIMAL_H48_THREADS": str(worker_threads),
        "RUBIK_OPTIMAL_THREADS": str(worker_threads),
    }
    prerequisite_artifact_suffix = h48_prerequisite_artifact_suffix or artifact_suffix

    workloads: list[dict[str, Any]] = []
    stronger_table_workload = (
        _h48_stronger_table_workload(
            root=root,
            python_executable=python_executable,
            profile=profile,
            seed=seed,
            target=target,
            worker_threads=worker_threads,
            h48_table_generation_timeout_seconds=h48_table_generation_timeout_seconds,
            runtime_target_seconds=runtime_target_seconds,
            h48_timeout_seconds=h48_timeout_seconds,
            artifact_suffix=prerequisite_artifact_suffix,
            env=env,
            gendata_workbatch=resolved_h48_gendata_workbatch,
            skip_generation_distribution_scan=skip_h48_generation_distribution_scan,
            mmap_sync_mode=resolved_h48_generation_mmap_sync_mode,
            backend_extra_cflags=resolved_h48_backend_extra_cflags,
        )
        if include_h48_stronger_table
        else None
    )
    hardtail_uses_stronger_target_solver = (
        stronger_table_workload is not None and solver == target
    )
    hardtail_prerequisite_ids = (
        [str(stronger_table_workload["id"])] if hardtail_uses_stronger_target_solver else []
    )
    if hardtail_uses_stronger_target_solver and stronger_table_workload is not None:
        workloads.append(stronger_table_workload)

    hardtail_per_row_estimate = _hardtail_per_row_estimate_seconds(
        hardtail_strategy=strategy,
        h48_timeout_seconds=h48_timeout_seconds,
        prepass_timeout_seconds=prepass_timeout_seconds,
        fallback_timeout_seconds=fallback_timeout_seconds,
        h48_upper_bound_proof_timeout_seconds=h48_upper_bound_proof_timeout_seconds,
        rubikoptimal_timeout_seconds=rubikoptimal_timeout_seconds,
        symmetry_timeout_seconds=symmetry_timeout_seconds,
    )
    baseline_hardtail_per_row_estimate = _hardtail_per_row_estimate_seconds(
        hardtail_strategy="portfolio",
        h48_timeout_seconds=h48_timeout_seconds,
        prepass_timeout_seconds=prepass_timeout_seconds,
        fallback_timeout_seconds=fallback_timeout_seconds,
        h48_upper_bound_proof_timeout_seconds=h48_upper_bound_proof_timeout_seconds,
        rubikoptimal_timeout_seconds=rubikoptimal_timeout_seconds,
        symmetry_timeout_seconds=symmetry_timeout_seconds,
    )
    for index, offset_range in enumerate(ranges):
        label = f"{artifact_suffix}_d{distance}_o{offset_range.start}_{offset_range.end}"
        range_size = offset_range.end - offset_range.start
        estimated_wall_seconds = hardtail_per_row_estimate * range_size
        if execution_mode == "batch":
            command = _hardtail_direct_batch_command(
                python_executable=python_executable,
                profile=profile,
                seed=seed,
                solver=solver,
                distance=distance,
                offset_range=offset_range,
                h48_timeout_seconds=h48_timeout_seconds,
                prepass_timeout_seconds=prepass_timeout_seconds,
                fallback_timeout_seconds=fallback_timeout_seconds,
                h48_upper_bound_proof_timeout_seconds=h48_upper_bound_proof_timeout_seconds,
                h48_upper_bound_proof_max_gap=h48_upper_bound_proof_max_gap,
                rubikoptimal_timeout_seconds=rubikoptimal_timeout_seconds,
                symmetry_timeout_seconds=symmetry_timeout_seconds,
                symmetry_max_concurrency=concurrency,
                worker_threads=worker_threads,
                command_timeout_seconds=estimated_wall_seconds + 600.0,
                label=label,
                hardtail_strategy=strategy,
            )
            kind = "public_known_distance_hardtail_batch"
            expected_artifacts = [
                f"results/processed/universal_oracle_cli_seed_{seed}_{profile}_{solver}_{label}.json"
            ]
            if strategy == "native-h48-only":
                notes = (
                    "Fast-target native-H48 batch mode feeds public distance rows directly to one "
                    "universal-oracle CLI process, disables certificate, portfolio, direct nissy-core, "
                    "RubikOptimal, and symmetry fallback phases, and requires every row to finish through "
                    "resident-h48-batch. This makes the H48 target proof stricter and cuts the configured "
                    "per-row timeout budget, but a timeout remains a failed proof row rather than an exact result."
                )
            else:
                notes = (
                    "Direct batch mode feeds multiple public distance rows into one universal-oracle CLI "
                    "process. It preserves the exact/verified evidence rule while reusing resident native "
                    "H48, Nissy, and RubikOptimal table-loaded sessions across the batch. This reduces "
                    "duplicated process/table setup, but it does not by itself prove a 10x reduction in "
                    "worst-case search-node work."
                )
        else:
            command = [
                python_executable,
                "scripts/run_known_distance20_trimmed_prepass_sweep.py",
                "--profile",
                profile,
                "--seed",
                str(seed),
                "--solver",
                solver,
                "--distance",
                str(distance),
                "--start-offset",
                str(offset_range.start),
                "--end-offset",
                str(offset_range.end),
                "--max-new-runs",
                str(range_size),
                "--timeout",
                str(h48_timeout_seconds),
                "--prepass-timeout",
                str(prepass_timeout_seconds),
                "--fallback-timeout",
                str(fallback_timeout_seconds),
                "--fallback-nissy-core-direct-timeout",
                str(symmetry_timeout_seconds),
                "--resident-race-prepass-timeout",
                str(symmetry_timeout_seconds),
                "--rubikoptimal-prepass-timeout",
                str(rubikoptimal_timeout_seconds),
                "--rubikoptimal-race-timeout",
                str(rubikoptimal_timeout_seconds),
                "--rubikoptimal-fallback-timeout",
                str(rubikoptimal_timeout_seconds),
                "--rubikoptimal-symmetry-variants",
                "23",
                "--rubikoptimal-symmetry-timeout",
                str(rubikoptimal_timeout_seconds),
                "--rubikoptimal-symmetry-max-concurrency",
                str(concurrency),
                "--nissy-symmetry-variants",
                "23",
                "--nissy-symmetry-timeout",
                str(symmetry_timeout_seconds),
                "--nissy-core-direct-symmetry-variants",
                "23",
                "--nissy-core-direct-symmetry-timeout",
                str(symmetry_timeout_seconds),
                "--nissy-core-direct-symmetry-max-concurrency",
                str(concurrency),
                "--h48-parallel-symmetry-variants",
                "23",
                "--h48-parallel-symmetry-timeout",
                str(h48_timeout_seconds),
                "--h48-parallel-symmetry-max-concurrency",
                str(concurrency),
                "--symmetry-order-by-h48-lower-bound",
                "--symmetry-lower-bound-order-timeout",
                str(min(120.0, max(30.0, prepass_timeout_seconds))),
                "--h48-upper-bound-proof-timeout",
                str(h48_upper_bound_proof_timeout_seconds),
                "--h48-upper-bound-proof-max-gap",
                str(max(1, int(h48_upper_bound_proof_max_gap))),
                "--threads",
                str(worker_threads),
                "--no-preload-table",
                "--keep-going",
                "--label",
                label,
            ]
            kind = "public_known_distance_hardtail_sweep"
            expected_artifacts = [
                (
                    "results/processed/known_distance_sweep_seed_"
                    f"{seed}_{profile}_{solver}_known_distance_{distance}_"
                    f"*_{label}.json"
                )
            ]
            notes = (
                "This is the original cloud canary/scale-out workload for the fast every-state claim. "
                "A passed shard is still empirical evidence, not a formal full-state theorem by itself."
            )
        workloads.append(
            _workload(
                workload_id=f"known_distance_{distance}_shard_{index:03d}",
                kind=kind,
                command_args=command,
                env=env,
                expected_artifacts=expected_artifacts,
                estimated_wall_seconds=estimated_wall_seconds,
                depends_on_workload_ids=hardtail_prerequisite_ids,
                proves=(
                    "live exact search over public known-distance hard-tail states with source "
                    "sequences withheld from the public oracle"
                ),
                notes=notes,
            )
        )

    if stronger_table_workload is not None and not hardtail_uses_stronger_target_solver:
        workloads.append(stronger_table_workload)

    if include_rubikoptimal_superflip:
        command = [
            python_executable,
            "scripts/run_rubikoptimal_oracle_corpus.py",
            "--profile",
            profile,
            "--seed",
            str(seed),
            "--include-superflip",
            "--case-id",
            "superflip_distance_20",
            "--timeout",
            str(max(rubikoptimal_timeout_seconds, runtime_target_seconds)),
            "--artifact-suffix",
            f"{artifact_suffix}_superflip",
        ]
        workloads.append(
            _workload(
                workload_id="rubikoptimal_superflip_hardcase",
                kind="rubikoptimal_table_complete_hardcase",
                command_args=command,
                env=env,
                expected_artifacts=[
                    f"results/processed/rubikoptimal_oracle_corpus_seed_{seed}_{profile}_{artifact_suffix}_superflip.json"
                ],
                estimated_wall_seconds=max(rubikoptimal_timeout_seconds, runtime_target_seconds),
                proves="whether table-complete RubikOptimal clears the canonical distance-20 superflip hard state",
                notes=(
                    "The local Mac timed this row out at 300s, so this is a cloud/idle-machine validation target."
                ),
            )
        )

    postprocess_commands = [
        [python_executable, "scripts/generate_h48_oracle_contract.py", "--profile", profile, "--seed", str(seed), "--solver", solver],
        [python_executable, "scripts/verify_results.py"],
        [python_executable, "scripts/thesis_audit.py"],
    ]
    for index, command in enumerate(postprocess_commands):
        script_name = Path(command[1]).name
        if script_name == "generate_h48_oracle_contract.py":
            expected_artifacts = [f"results/processed/h48_oracle_contract_seed_{seed}_{profile}_{solver}.json"]
        elif script_name == "thesis_audit.py":
            expected_artifacts = ["results/processed/thesis_audit.json"]
        else:
            expected_artifacts = []
        workloads.append(
            _workload(
                workload_id=f"postprocess_{index:02d}",
                kind="postprocess_and_audit",
                command_args=command,
                env=env,
                expected_artifacts=expected_artifacts,
                proves="regenerated contract, result verifier, and thesis audit after cloud artifacts are collected",
                required_for_claim=True,
                estimated_wall_seconds=300.0,
            )
        )

    return {
        "schema_version": 1,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "objective": "prove or falsify a fast optimal oracle claim for every valid 3x3 state",
        "claim_scope": normalized_claim_scope,
        "profile": profile,
        "seed": seed,
        "solver": solver,
        "distance": distance,
        "available_scramble_rows": available,
        "selected_offset_start": start,
        "selected_offset_end": end,
        "shard_size": max(1, int(shard_size)),
        "hardtail_execution_mode": execution_mode,
        "hardtail_strategy": strategy,
        "h48_generation_distribution_mode": "expected_constants"
        if skip_h48_generation_distribution_scan
        else "scanned",
        "h48_gendata_workbatch": resolved_h48_gendata_workbatch,
        "h48_generation_distribution_scan_skipped": bool(skip_h48_generation_distribution_scan),
        "h48_generation_mmap_sync_mode": resolved_h48_generation_mmap_sync_mode,
        "h48_backend_extra_cflags": list(resolved_h48_backend_extra_cflags),
        "h48_prerequisite_artifact_suffix": prerequisite_artifact_suffix,
        "hardtail_uses_stronger_target_solver": hardtail_uses_stronger_target_solver,
        "hardtail_prerequisite_workload_ids": hardtail_prerequisite_ids,
        "requires_table_distribution_before_hardtail": hardtail_uses_stronger_target_solver,
        "hardtail_state_count": end - start,
        "hardtail_process_count": len(ranges),
        "hardtail_process_launch_reduction_factor": (
            round((end - start) / len(ranges), 6) if ranges else 0.0
        ),
        "hardtail_per_row_timeout_budget_seconds": hardtail_per_row_estimate,
        "hardtail_baseline_portfolio_per_row_timeout_budget_seconds": (
            baseline_hardtail_per_row_estimate
        ),
        "hardtail_timeout_budget_reduction_factor": (
            round(baseline_hardtail_per_row_estimate / hardtail_per_row_estimate, 6)
            if hardtail_per_row_estimate > 0
            else 0.0
        ),
        "hardtail_compute_efficiency_notes": (
            "Native-H48-only mode removes portfolio, direct nissy-core, RubikOptimal, symmetry, and "
            "upper/lower certificate phases from the fast-target hard-tail workloads. It tests the "
            "claimed resident H48 target directly and treats any timeout as a failed proof row, which "
            "is stricter and substantially cheaper than the fallback portfolio budget."
            if strategy == "native-h48-only"
            else (
            "Batch mode reduces duplicated process startup and table-load work by grouping public "
            "distance rows into fewer universal-oracle CLI invocations. The remaining hard limit is "
            "still exact-search node expansion on the unresolved rows; stronger heuristic tables are "
            "needed for a defensible 10x worst-case compute reduction."
            if execution_mode == "batch"
            else "Sweep mode keeps one artifact per row/range but can repeat CLI and table setup."
            )
        ),
        "worker_threads": worker_threads,
        "recommended_minimum_cloud_machine": _recommended_cloud_machine(
            worker_threads=worker_threads,
            target_solver=target,
        ),
        "runtime_target_seconds": runtime_target_seconds,
        "workload_count": len(workloads),
        "workloads": workloads,
        "completion_gates": [
            "every required workload artifact exists and passes its script-level checks",
            "every hard-tail row reports status=exact and verified=true from state-only public-oracle input",
            "distance-20 public benchmark shards have no timeout/failed rows under the approved runtime target",
            "stronger H48 table campaign either produces trusted metadata or is explicitly removed from the claim",
            "RubikOptimal hardcase rows either pass or remain documented as runtime-limit evidence",
            "regenerated h48 oracle contract and thesis audit preserve all acceptance gates",
            "only after the above can fast_runtime_proven_for_every_possible_state be revisited",
        ],
        "all_state_fast_oracle_goal_satisfied_by_plan": False,
        "fast_runtime_proven_for_every_possible_state": False,
        "notes": (
            "This is an execution plan, not completion evidence. It exists so cloud runs are reproducible, "
            "sharded, and tied to the thesis claim boundary. A canary-scope plan is useful for cost/risk "
            "screening, but only a full-scope plan can support the final every-state runtime proof gate."
        ),
    }


def _tex(value: object) -> str:
    return str(value).replace("\\", "\\textbackslash{}").replace("_", "\\_").replace("&", "\\&")


def _write_table(root: Path, payload: dict[str, Any], suffix: str) -> Path:
    table_path = root / "thesis" / "tables" / f"cloud_hardtail_campaign_plan{suffix}.tex"
    table_path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for workload in payload["workloads"]:
        rows.append(
            f"{_tex(workload['id'])} & {_tex(workload['kind'])} & "
            f"{_tex(workload['required_for_fast_every_state_claim'])} \\\\"
        )
    table_path.write_text(
        "{\\small\n"
        "\\begin{tabular}{lll}\n"
        "\\hline\n"
        "Workload & Type & Required \\\\\n"
        "\\hline\n"
        + "\n".join(rows)
        + "\n\\hline\n\\end{tabular}\n"
        "}\n",
        encoding="utf-8",
    )
    return table_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default="thesis")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--solver", default=ORACLE_H48_SOLVER)
    parser.add_argument("--python-executable", default="python")
    parser.add_argument("--distance", type=int, default=20)
    parser.add_argument("--start-offset", type=int, default=0)
    parser.add_argument("--end-offset", type=int, default=None)
    parser.add_argument("--shard-size", type=int, default=1)
    parser.add_argument("--threads", type=int, default=16)
    parser.add_argument("--runtime-target", type=float, default=300.0)
    parser.add_argument("--h48-timeout", type=float, default=600.0)
    parser.add_argument("--prepass-timeout", type=float, default=60.0)
    parser.add_argument("--fallback-timeout", type=float, default=900.0)
    parser.add_argument("--h48-upper-bound-proof-timeout", type=float, default=600.0)
    parser.add_argument("--h48-upper-bound-proof-max-gap", type=int, default=4)
    parser.add_argument("--rubikoptimal-timeout", type=float, default=900.0)
    parser.add_argument("--symmetry-timeout", type=float, default=300.0)
    parser.add_argument("--symmetry-max-concurrency", type=int, default=4)
    parser.add_argument("--h48-stronger-target-solver", default="h48h8")
    parser.add_argument("--h48-table-generation-timeout", type=float, default=43200.0)
    parser.add_argument("--claim-scope", choices=["full", "canary"], default="full")
    parser.add_argument("--canary", action="store_true", help="Alias for --claim-scope canary.")
    parser.add_argument("--canary-offset-count", type=int, default=3)
    parser.add_argument("--no-h48-stronger-table", action="store_true")
    parser.add_argument("--no-rubikoptimal-superflip", action="store_true")
    parser.add_argument(
        "--hardtail-execution-mode",
        choices=["sweep", "batch"],
        default="sweep",
        help=(
            "Use the historical sweep wrapper, or run each hard-tail range as one direct "
            "universal-oracle batch to reuse resident table-loaded backends."
        ),
    )
    parser.add_argument(
        "--hardtail-strategy",
        choices=["portfolio", "native-h48-only"],
        default="portfolio",
        help=(
            "Portfolio keeps the broad fallback stack. native-h48-only is the fast-target proof mode: "
            "hard-tail batches must be solved by resident H48 itself, with fallback phases disabled."
        ),
    )
    parser.add_argument("--artifact-suffix", default="cloud_hardtail")
    parser.add_argument(
        "--h48-prerequisite-artifact-suffix",
        default=None,
        help=(
            "Optional shared suffix for the stronger-H48 prerequisite artifact. "
            "Use the same value for matching canary and full plans to avoid rerunning "
            "the expensive table campaign under two plan-specific artifact names."
        ),
    )
    parser.add_argument(
        "--skip-h48-generation-distribution-scan",
        action="store_true",
        help=(
            "Add --skip-generation-distribution-scan to the stronger-H48 prerequisite workload. "
            "The table generator then writes canonical expected H48 distribution constants instead "
            "of scanning the completed table once more."
        ),
    )
    parser.add_argument(
        "--h48-generation-mmap-sync-mode",
        choices=["sync", "async", "none"],
        default="sync",
        help=(
            "Add --mmap-sync-mode to the stronger-H48 prerequisite workload. async avoids waiting "
            "for a full blocking mmap writeback; generated tables still require size/checksum metadata."
        ),
    )
    parser.add_argument(
        "--h48-backend-cflag",
        action="append",
        default=[],
        help=(
            "Add an audited extra native H48 backend compiler flag to the stronger-H48 prerequisite, "
            "for example --h48-backend-cflag=-march=native on a dedicated proof host."
        ),
    )
    parser.add_argument(
        "--h48-gendata-workbatch",
        default=None,
        help=(
            "Add --gendata-workbatch to the stronger-H48 prerequisite workload. "
            "Smaller batches improve balancing/progress for H48H10+ generation on proof hosts."
        ),
    )
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()

    payload = build_cloud_hardtail_plan(
        root=args.root,
        profile=args.profile,
        seed=args.seed,
        solver=args.solver,
        python_executable=args.python_executable,
        distance=args.distance,
        start_offset=args.start_offset,
        end_offset=args.end_offset,
        shard_size=args.shard_size,
        threads=args.threads,
        runtime_target_seconds=args.runtime_target,
        h48_timeout_seconds=args.h48_timeout,
        prepass_timeout_seconds=args.prepass_timeout,
        fallback_timeout_seconds=args.fallback_timeout,
        h48_upper_bound_proof_timeout_seconds=args.h48_upper_bound_proof_timeout,
        h48_upper_bound_proof_max_gap=args.h48_upper_bound_proof_max_gap,
        rubikoptimal_timeout_seconds=args.rubikoptimal_timeout,
        symmetry_timeout_seconds=args.symmetry_timeout,
        symmetry_max_concurrency=args.symmetry_max_concurrency,
        h48_stronger_target_solver=args.h48_stronger_target_solver,
        h48_table_generation_timeout_seconds=args.h48_table_generation_timeout,
        claim_scope="canary" if args.canary else args.claim_scope,
        canary_offset_count=args.canary_offset_count,
        include_h48_stronger_table=not args.no_h48_stronger_table,
        include_rubikoptimal_superflip=not args.no_rubikoptimal_superflip,
        hardtail_execution_mode=args.hardtail_execution_mode,
        hardtail_strategy=args.hardtail_strategy,
        h48_gendata_workbatch=args.h48_gendata_workbatch,
        skip_h48_generation_distribution_scan=args.skip_h48_generation_distribution_scan,
        h48_generation_mmap_sync_mode=args.h48_generation_mmap_sync_mode,
        h48_backend_extra_cflags=args.h48_backend_cflag,
        artifact_suffix=args.artifact_suffix,
        h48_prerequisite_artifact_suffix=args.h48_prerequisite_artifact_suffix,
    )
    suffix = f"_seed_{args.seed}_{args.profile}_{canonical_h48_solver(args.solver)}_{args.artifact_suffix}"
    output = args.root / "results" / "processed" / f"cloud_hardtail_campaign_plan{suffix}.json"
    write_json(output, payload)
    table = _write_table(args.root, payload, suffix)
    print(
        json.dumps(
            {
                "output": str(output),
                "table": str(table),
                "workload_count": payload["workload_count"],
                "fast_runtime_proven_for_every_possible_state": payload[
                    "fast_runtime_proven_for_every_possible_state"
                ],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

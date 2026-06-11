#!/usr/bin/env python
"""Record local capacity and table readiness for stronger H48 oracle levels."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rubik_optimal.results import write_json
from rubik_optimal.runtime import available_memory_bytes, suggest_thread_count
from rubik_optimal.tables.h48 import (
    H48_TABLE_ROOT_ENV,
    ORACLE_H48_SOLVER,
    canonical_h48_solver,
    estimated_h48_table_size_bytes,
    h48_solver_h_value,
    h48_table_inventory,
    h48_table_root,
    highest_available_h48_solver,
    normalize_h48_backend_extra_cflags,
    normalize_h48_mmap_sync_mode,
    resolve_h48_gendata_workbatch,
)
from scripts.inspect_nissy_public_tables import (
    PUBLIC_NISSY_TABLES_URL,
    build_manifest,
    fetch_head,
    fetch_zip_tail,
    parse_zip_central_directory,
)

H48_FIRST_STRONGER_SOLVER = "h48h8"
H48_FAST_TARGET_SOLVER = "h48h10"
H48_FASTEST_UPSTREAM_BENCHMARK_SOLVER = "h48h11"
H48_HEAP_GENERATION_DISK_MULTIPLIER = 2.0
H48_MMAP_GENERATION_DISK_MULTIPLIER = 1.15


def _relative(root: Path, path: Path) -> str:
    return str(path.relative_to(root)) if path.is_relative_to(root) else str(path)


def _parse_float_cell(value: str) -> float | None:
    value = value.strip()
    if not value:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", value)
    return float(match.group(0)) if match else None


def _load_h48_16_thread_benchmark_hints(root: Path) -> dict[str, Any]:
    """Parse vendored nissy-core H48 benchmark rows for target selection.

    These are upstream benchmark hints, not thesis runtime evidence.  They are
    useful for deciding which stronger H48 table is worth building next: h48h8
    is the first missing local table, while h48h10 is the smallest upstream
    fast target with published distance-20 and superflip timings in the
    16-thread table. h48h11 remains the faster larger-memory optional target.
    """

    source_path = root / ".codex_external" / "nissy-core" / "benchmarks" / "tables_16_threads.md"
    rows: list[dict[str, Any]] = []
    if not source_path.exists():
        return {
            "available": False,
            "source_path": str(source_path.relative_to(root)) if source_path.is_relative_to(root) else str(source_path),
            "rows": rows,
            "target_solver": H48_FAST_TARGET_SOLVER,
            "target_has_distance20_timing": False,
            "target_has_superflip_timing": False,
        }

    in_time_table = False
    for line in source_path.read_text(encoding="utf-8").splitlines():
        if "Time per cube" in line:
            in_time_table = True
            continue
        if in_time_table and "Speed-up factor" in line:
            break
        if not in_time_table or not line.startswith("|H48 h"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 7:
            continue
        solver_match = re.fullmatch(r"H48 h(?P<h>\d+)", cells[0])
        if not solver_match:
            continue
        solver = f"h48h{solver_match.group('h')}"
        rows.append(
            {
                "solver": solver,
                "size_gib": _parse_float_cell(cells[1]),
                "single_solution_16_threads_seconds": {
                    "distance_17": _parse_float_cell(cells[2]),
                    "distance_18": _parse_float_cell(cells[3]),
                    "distance_19": _parse_float_cell(cells[4]),
                    "distance_20": _parse_float_cell(cells[5]),
                    "superflip": _parse_float_cell(cells[6]),
                },
            }
        )

    target = next((row for row in rows if row["solver"] == H48_FAST_TARGET_SOLVER), None)
    timings = target.get("single_solution_16_threads_seconds", {}) if target else {}
    return {
        "available": bool(rows),
        "source_path": str(source_path.relative_to(root)),
        "rows": rows,
        "target_solver": H48_FAST_TARGET_SOLVER,
        "target_has_distance20_timing": timings.get("distance_20") is not None,
        "target_has_superflip_timing": timings.get("superflip") is not None,
        "notes": (
            "Upstream vendored nissy-core benchmark hints only; thesis fast-runtime "
            "claims still require locally generated artifacts and verification."
        ),
    }


def _run_text(command: list[str]) -> str | None:
    try:
        completed = subprocess.run(command, check=False, text=True, capture_output=True)
    except OSError:
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def _memory_bytes() -> int | None:
    value = _run_text(["sysctl", "-n", "hw.memsize"])
    if value and value.isdigit():
        return int(value)
    try:
        return int(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES"))
    except (AttributeError, OSError, ValueError):
        return None


def _load_average() -> tuple[float, float, float] | None:
    try:
        return tuple(float(value) for value in os.getloadavg())
    except (AttributeError, OSError):
        return None


def evaluate_h48_generation_safety(
    *,
    root: Path,
    solver: str,
    threads: int | None = None,
    mmap_output: bool | None = None,
    memory_fraction_limit: float = 0.35,
    disk_multiplier: float | None = None,
    load_fraction_limit: float = 0.5,
    min_mmap_available_memory_bytes: int = 4 * 1024**3,
) -> dict[str, Any]:
    """Return a conservative local-machine safety decision for H48 generation."""

    solver = canonical_h48_solver(solver)
    h_value = h48_solver_h_value(solver)
    if mmap_output is None:
        mmap_output = h_value >= 8
    effective_disk_multiplier = (
        float(disk_multiplier)
        if disk_multiplier is not None
        else H48_MMAP_GENERATION_DISK_MULTIPLIER
        if mmap_output
        else H48_HEAP_GENERATION_DISK_MULTIPLIER
    )
    table_size = estimated_h48_table_size_bytes(solver)
    disk_root = h48_table_root(root=root)
    disk_root.mkdir(parents=True, exist_ok=True)
    disk = shutil.disk_usage(disk_root)
    memory_bytes = _memory_bytes()
    launch_available_memory = available_memory_bytes() if mmap_output else None
    load_average = _load_average()
    cpu_count = os.cpu_count() or 1
    selected_threads = max(1, int(threads or suggest_thread_count(cpu_count=cpu_count, load_average=load_average[0] if load_average else None)))

    reasons: list[str] = []
    if mmap_output:
        if launch_available_memory is None:
            reasons.append("available memory is unavailable for output-backed mmap generation guard")
        elif launch_available_memory < min_mmap_available_memory_bytes:
            have_gib = launch_available_memory / (1024**3)
            need_gib = min_mmap_available_memory_bytes / (1024**3)
            reasons.append(
                f"available memory {have_gib:.2f} GiB is below the {need_gib:.2f} GiB mmap generation guard"
            )
    elif memory_bytes is not None and table_size > memory_bytes * memory_fraction_limit:
        reasons.append(
            f"{solver} table size exceeds {memory_fraction_limit:.0%} of total RAM before generator overhead"
        )
    if load_average and load_average[0] >= max(1.0, cpu_count * load_fraction_limit):
        reasons.append(
            f"current one-minute load average {load_average[0]:.2f} is at least {load_fraction_limit:.0%} of logical CPUs"
        )
    if disk.free < table_size * effective_disk_multiplier:
        reasons.append(
            f"free disk is below {effective_disk_multiplier:.2f}x the {solver} table size, leaving little room for retries"
        )
    if selected_threads > max(1, cpu_count - int(round(load_average[0] if load_average else 0.0))):
        reasons.append("requested generation threads do not leave the load-aware CPU headroom recommended for this machine")

    return {
        "solver": solver,
        "estimated_table_size_bytes": table_size,
        "estimated_table_size_gib": round(table_size / (1024**3), 6),
        "threads": selected_threads,
        "safe_to_start": not reasons,
        "reasons": reasons,
        "policy": {
            "generation_storage": "mmap_file" if mmap_output else "heap_then_write",
            "mmap_output": mmap_output,
            "memory_fraction_limit": memory_fraction_limit,
            "min_mmap_available_memory_bytes": min_mmap_available_memory_bytes,
            "disk_multiplier": effective_disk_multiplier,
            "disk_multiplier_source": "explicit" if disk_multiplier is not None else "storage_default",
            "load_fraction_limit": load_fraction_limit,
        },
        "machine": {
            "cpu_count": cpu_count,
            "load_average": load_average,
            "memory_bytes": memory_bytes,
            "h48_table_root_env": H48_TABLE_ROOT_ENV,
            "h48_table_root": _relative(root, disk_root),
            "available_memory_bytes": launch_available_memory,
            "data_generated_h48_free_bytes": disk.free,
            "h48_table_root_free_bytes": disk.free,
        },
    }


def _public_manifest_from_existing(root: Path, *, profile: str, seed: int) -> dict[str, Any] | None:
    candidates = sorted((root / "results" / "processed").glob(f"nissy_public_tables_manifest_seed_{seed}_{profile}*.json"))
    for path in reversed(candidates):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        payload["_manifest_path"] = str(path.relative_to(root))
        return payload
    return None


def _refresh_public_manifest(url: str, *, timeout: float) -> dict[str, Any]:
    head = fetch_head(url, timeout=timeout)
    content_length = head.get("content_length")
    if not isinstance(content_length, int):
        raise RuntimeError("public Nissy table archive did not report content-length")
    tail, range_response = fetch_zip_tail(url, tail_bytes=1024 * 1024, timeout=timeout)
    if range_response["status"] != 206:
        raise RuntimeError(f"public Nissy table archive did not honor range request: {range_response['status']}")
    directory = parse_zip_central_directory(tail, content_length=content_length)
    return build_manifest(
        source_url=url,
        head=head,
        range_response=range_response,
        zip_directory=directory,
    )


def _tex(value: object) -> str:
    return str(value).replace("\\", "\\textbackslash{}").replace("_", "\\_").replace("&", "\\&")


def _write_table(root: Path, payload: dict[str, Any], suffix: str) -> Path:
    filename = f"h48_capacity{suffix}.tex" if suffix else "h48_capacity.tex"
    table_path = root / "thesis" / "tables" / filename
    table_path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for row in payload["oracle_grade_rows"]:
        rows.append(
            f"{_tex(row['solver'])} & "
            f"{float(row['estimated_table_size_gib']):.2f} & "
            f"{_tex(row['table_exists'])} & "
            f"{_tex(row['trusted_metadata_valid'])} \\\\"
        )
    table_path.write_text(
        "{\\small\n"
        "\\begin{tabular}{lrrr}\n"
        "\\hline\n"
        "Solver & Estimated GiB & Table present & Trusted metadata \\\\\n"
        "\\hline\n"
        + "\n".join(rows)
        + "\n\\hline\n"
        "\\end{tabular}\n"
        "}\n",
        encoding="utf-8",
    )
    return table_path


def _build_plan_row(
    *,
    root: Path,
    profile: str,
    seed: int,
    solver: str,
    threads: int,
    gendata_workbatch: int | str | None = None,
    skip_generation_distribution_scan: bool = False,
    mmap_sync_mode: str = "sync",
    backend_extra_cflags: tuple[str, ...] = (),
) -> dict[str, Any]:
    resolved_workbatch = resolve_h48_gendata_workbatch(gendata_workbatch)
    mmap_sync_mode = normalize_h48_mmap_sync_mode(mmap_sync_mode)
    backend_extra_cflags = normalize_h48_backend_extra_cflags(backend_extra_cflags)
    safety = evaluate_h48_generation_safety(
        root=root,
        solver=solver,
        threads=threads,
        mmap_output=True,
    )
    command = [
        "nice",
        "-n",
        "20",
        "python",
        "scripts/generate_h48_tables.py",
        "--profile",
        profile,
        "--seed",
        str(seed),
        "--solver",
        safety["solver"],
        "--threads",
        str(threads),
        "--mmap-output",
        "--progress-log",
        "--require-safe",
        "--gendata-workbatch",
        str(resolved_workbatch),
    ]
    if skip_generation_distribution_scan:
        command.append("--skip-generation-distribution-scan")
    command.extend(["--mmap-sync-mode", mmap_sync_mode])
    for flag in backend_extra_cflags:
        command.append(f"--backend-cflag={flag}")
    return {
        "solver": safety["solver"],
        "estimated_table_size_bytes": safety["estimated_table_size_bytes"],
        "estimated_table_size_gib": safety["estimated_table_size_gib"],
        "safe_to_generate_on_current_machine": safety["safe_to_start"],
        "safety_reasons": safety["reasons"],
        "recommended_command": " ".join(command),
        "h48_gendata_workbatch": resolved_workbatch,
        "h48_generation_distribution_mode": "expected_constants"
        if skip_generation_distribution_scan
        else "scanned",
        "h48_generation_distribution_scan_skipped": bool(skip_generation_distribution_scan),
        "h48_generation_mmap_sync_mode": mmap_sync_mode,
        "h48_backend_extra_cflags": list(backend_extra_cflags),
        "completion_evidence_required": [
            f"${{{H48_TABLE_ROOT_ENV}:-data/generated/h48}}/{profile}_seed_{seed}/{safety['solver']}.bin",
            f"results/processed/h48_metadata_seed_{seed}_{profile}_{safety['solver']}.json",
            f"results/processed/h48_oracle_contract_seed_{seed}_{profile}_{safety['solver']}.json",
            "hard-case certification artifact using this solver under the thesis runtime target",
        ],
    }


def build_capacity_payload(
    *,
    root: Path,
    profile: str,
    seed: int,
    refresh_public_nissy: bool = False,
    public_url: str = PUBLIC_NISSY_TABLES_URL,
    public_timeout: float = 30.0,
    skip_generation_distribution_scan: bool = False,
    mmap_sync_mode: str = "sync",
    gendata_workbatch: int | str | None = None,
    backend_extra_cflags: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    resolved_mmap_sync_mode = normalize_h48_mmap_sync_mode(mmap_sync_mode)
    resolved_workbatch = resolve_h48_gendata_workbatch(gendata_workbatch)
    resolved_backend_extra_cflags = normalize_h48_backend_extra_cflags(backend_extra_cflags)
    inventory = h48_table_inventory(root=root, profile=profile, seed=seed)
    for row in inventory:
        row["estimated_table_size_gib"] = round(int(row["estimated_table_size_bytes"]) / (1024**3), 6)
    oracle_rows = [row for row in inventory if bool(row["oracle_grade"])]
    strongest = highest_available_h48_solver(root=root, profile=profile, seed=seed)
    strongest_h = h48_solver_h_value(strongest)
    next_missing = next(
        (row["solver"] for row in oracle_rows if int(row["h_value"]) > strongest_h and not row["table_exists"]),
        None,
    )

    disk_root = h48_table_root(root=root)
    disk_root.mkdir(parents=True, exist_ok=True)
    disk = shutil.disk_usage(disk_root)
    memory_bytes = _memory_bytes()
    load_average = _load_average()
    cpu_count = os.cpu_count() or 1
    suggested_threads = suggest_thread_count(
        cpu_count=cpu_count,
        load_average=load_average[0] if load_average else None,
    )

    public_manifest = _refresh_public_manifest(public_url, timeout=public_timeout) if refresh_public_nissy else None
    public_source = "refreshed" if public_manifest is not None else "existing-artifact"
    if public_manifest is None:
        public_manifest = _public_manifest_from_existing(root, profile=profile, seed=seed)
    public_h48_entries = public_manifest.get("h48_entries", []) if public_manifest else []

    h8_size = estimated_h48_table_size_bytes(H48_FIRST_STRONGER_SOLVER)
    h10_size = estimated_h48_table_size_bytes(H48_FAST_TARGET_SOLVER)
    h11_size = estimated_h48_table_size_bytes(H48_FASTEST_UPSTREAM_BENCHMARK_SOLVER)
    h8_safety = evaluate_h48_generation_safety(
        root=root,
        solver=H48_FIRST_STRONGER_SOLVER,
        threads=suggested_threads,
    )
    fast_target_safety = evaluate_h48_generation_safety(
        root=root,
        solver=H48_FAST_TARGET_SOLVER,
        threads=suggested_threads,
    )
    upstream_benchmark = _load_h48_16_thread_benchmark_hints(root)
    build_plan_rows = [
        _build_plan_row(
            root=root,
            profile=profile,
            seed=seed,
            solver=f"h48h{h_value}",
            threads=suggested_threads,
            gendata_workbatch=resolved_workbatch,
            skip_generation_distribution_scan=skip_generation_distribution_scan,
            mmap_sync_mode=resolved_mmap_sync_mode,
            backend_extra_cflags=resolved_backend_extra_cflags,
        )
        for h_value in range(8, 12)
    ]
    target_solver = H48_FAST_TARGET_SOLVER
    target_row = next((row for row in oracle_rows if row["solver"] == target_solver), None)
    target_table_ready = bool(target_row and target_row["trusted_metadata_valid"] is True)
    target_benchmark_row = next(
        (row for row in upstream_benchmark["rows"] if row["solver"] == target_solver),
        None,
    )
    every_state_fast_gate = {
        "target_solver": target_solver,
        "first_missing_ladder_solver": H48_FIRST_STRONGER_SOLVER,
        "current_strongest_solver": strongest,
        "target_table_trusted": target_table_ready,
        "target_table_expected_size_bytes": h10_size,
        "target_table_expected_size_gib": round(h10_size / (1024**3), 6),
        "target_generation_safe_now": fast_target_safety["safe_to_start"],
        "target_generation_safety_reasons": fast_target_safety["reasons"],
        "upstream_benchmark_source_path": upstream_benchmark["source_path"],
        "target_upstream_benchmark_row": target_benchmark_row,
        "target_upstream_benchmark_has_distance20_timing": upstream_benchmark[
            "target_has_distance20_timing"
        ],
        "target_upstream_benchmark_has_superflip_timing": upstream_benchmark[
            "target_has_superflip_timing"
        ],
        "hard_case_certification_with_target_solver": False,
        "broad_corpus_runtime_target_with_target_solver": False,
        "formal_or_empirical_worst_case_runtime_bound": False,
        "can_claim_fast_oracle_for_every_possible_state": False,
        "reason": (
            "The source supports arbitrary valid 3x3 exact solving, but the fast all-state claim "
            "requires the H48 fast target table plus hard-case and broad-corpus runtime evidence. "
            "H48H8 is only the first missing ladder table; H48H10 is the default target selected "
            "from the vendored upstream 16-thread H48 benchmark rows because it is the smallest "
            "profile with both distance-20 and superflip timings, while H48H11 remains a faster "
            "larger-memory optional target."
        ),
        "remaining_completion_requirements": [
            f"generate trusted {target_solver} H48 table",
            f"validate full checksum for trusted {target_solver} table on each worker",
            f"run hard-case exact certification with {target_solver}",
            f"run broad arbitrary-state runtime corpus with {target_solver}",
            "record final cloud/runtime proof artifact before setting fast_runtime_proven_for_every_possible_state",
        ],
    }

    return {
        "schema_version": 1,
        "checked_at_utc": datetime.now(UTC).isoformat(),
        "profile": profile,
        "seed": seed,
        "default_oracle_solver": ORACLE_H48_SOLVER,
        "strongest_local_oracle_solver": strongest,
        "next_missing_oracle_grade_solver": next_missing,
        "inventory_rows": inventory,
        "oracle_grade_rows": oracle_rows,
        "machine": {
            "cpu_count": cpu_count,
            "load_average": load_average,
            "memory_bytes": memory_bytes,
            "h48_table_root_env": H48_TABLE_ROOT_ENV,
            "h48_table_root": _relative(root, disk_root),
            "data_generated_h48_free_bytes": disk.free,
            "h48_table_root_free_bytes": disk.free,
            "suggested_load_aware_threads": suggested_threads,
        },
        "public_nissy_tables": {
            "source": public_source,
            "source_url": public_url,
            "manifest_path": public_manifest.get("_manifest_path") if public_manifest else None,
            "table_entry_count": public_manifest.get("table_entry_count") if public_manifest else None,
            "contains_h48_entries": bool(public_h48_entries),
            "h48_entries": public_h48_entries,
        },
        "estimated_h48h8_size_bytes": h8_size,
        "estimated_h48h10_size_bytes": h10_size,
        "estimated_h48h11_size_bytes": h11_size,
        "h48_first_stronger_solver": H48_FIRST_STRONGER_SOLVER,
        "h48_fast_target_solver": H48_FAST_TARGET_SOLVER,
        "h48_first_stronger_generation_safety": h8_safety,
        "h48_fast_target_generation_safety": fast_target_safety,
        "h48_stronger_table_generation_plan_options": {
            "h48_gendata_workbatch": resolved_workbatch,
            "h48_generation_distribution_mode": "expected_constants"
            if skip_generation_distribution_scan
            else "scanned",
            "h48_generation_distribution_scan_skipped": bool(skip_generation_distribution_scan),
            "h48_generation_mmap_sync_mode": resolved_mmap_sync_mode,
            "h48_backend_extra_cflags": list(resolved_backend_extra_cflags),
        },
        "h48_16_thread_upstream_benchmark": upstream_benchmark,
        "safe_to_start_h48h8_generation_now": h8_safety["safe_to_start"],
        "h48h8_generation_now_reasons": h8_safety["reasons"],
        "h48_stronger_table_build_plan": build_plan_rows,
        "all_state_fast_oracle_completion_gate": every_state_fast_gate,
        "fast_runtime_proven_for_every_possible_state": False,
        "conclusion": (
            "The optimized exact oracle code path is present and can select stronger local H48 tables, "
            "but the local machine currently has no trusted h48h8-h48h11 table. The first missing "
            "ladder table is h48h8, while the default fast every-state target selected from vendored "
            "upstream benchmark hints is h48h10 because it is the smallest profile with distance-20 "
            "and superflip timings. Public Nissy 2.x tables are useful for the external optimal "
            "backend but do not provide drop-in H48 h48hN artifacts."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default="thesis")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--refresh-public-nissy", action="store_true")
    parser.add_argument("--public-url", default=PUBLIC_NISSY_TABLES_URL)
    parser.add_argument("--public-timeout", type=float, default=30.0)
    parser.add_argument("--artifact-suffix", default="")
    parser.add_argument(
        "--skip-generation-distribution-scan",
        action="store_true",
        help=(
            "Include --skip-generation-distribution-scan in the stronger-table ladder commands. "
            "Use only with trusted checksum/metadata validation after generation."
        ),
    )
    parser.add_argument(
        "--mmap-sync-mode",
        choices=["sync", "async", "none"],
        default="sync",
        help="Include this mmap sync policy in output-backed stronger-table ladder commands.",
    )
    parser.add_argument(
        "--gendata-workbatch",
        default=None,
        help=(
            "Include --gendata-workbatch in output-backed stronger-table ladder commands. "
            "Defaults to the repository/native H48 value."
        ),
    )
    parser.add_argument(
        "--backend-cflag",
        action="append",
        default=[],
        help=(
            "Include an audited extra native backend compiler flag in stronger-table ladder commands, "
            "for example --backend-cflag=-march=native on a dedicated proof host."
        ),
    )
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()

    payload = build_capacity_payload(
        root=args.root,
        profile=args.profile,
        seed=args.seed,
        refresh_public_nissy=args.refresh_public_nissy,
        public_url=args.public_url,
        public_timeout=args.public_timeout,
        skip_generation_distribution_scan=args.skip_generation_distribution_scan,
        mmap_sync_mode=args.mmap_sync_mode,
        gendata_workbatch=args.gendata_workbatch,
        backend_extra_cflags=args.backend_cflag,
    )
    suffix_parts = [f"seed_{args.seed}", args.profile]
    if args.artifact_suffix:
        suffix_parts.append(args.artifact_suffix)
    suffix = "_" + "_".join(suffix_parts)
    output = args.root / "results" / "processed" / f"h48_capacity{suffix}.json"
    write_json(output, payload)
    table = _write_table(args.root, payload, suffix)
    print(
        json.dumps(
            {
                "output": str(output),
                "table": str(table),
                "strongest_local_oracle_solver": payload["strongest_local_oracle_solver"],
                "next_missing_oracle_grade_solver": payload["next_missing_oracle_grade_solver"],
                "safe_to_start_h48h8_generation_now": payload["safe_to_start_h48h8_generation_now"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

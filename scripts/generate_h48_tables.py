#!/usr/bin/env python
"""Generate in-repo native H48 pruning tables with metadata."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rubik_optimal.tables.h48 import (
    DEFAULT_H48_SOLVER,
    ORACLE_H48_SOLVER,
    generate_h48_table,
    normalize_h48_backend_extra_cflags,
    normalize_h48_mmap_sync_mode,
)
from rubik_optimal.tables.h48 import resolve_h48_gendata_workbatch
from rubik_optimal.runtime import parse_gib, parse_thread_setting
from scripts.inspect_h48_capacity import evaluate_h48_generation_safety


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=["quick", "thesis", "stress"], default="thesis")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--solver", default=DEFAULT_H48_SOLVER)
    parser.add_argument("--oracle", action="store_true", help="Generate h48h7, nissy-core's oracle-grade optimal H48 profile")
    parser.add_argument("--threads", default="8", help="Integer thread count, or 'auto' for load-aware sizing")
    parser.add_argument(
        "--require-safe",
        action="store_true",
        help="Refuse generation when current RAM/disk/load checks say this machine is not a safe place to start",
    )
    parser.add_argument(
        "--unsafe-allow-loaded-machine",
        action="store_true",
        help="Override --require-safe after recording the safety decision in stdout JSON",
    )
    storage = parser.add_mutually_exclusive_group()
    storage.add_argument(
        "--mmap-output",
        action="store_true",
        help="Generate directly into an output-backed mmap file; default is automatic for h48h8 and larger",
    )
    storage.add_argument(
        "--heap-output",
        action="store_true",
        help="Generate in aligned heap memory and write the completed table at the end; can be faster if enough RAM is available",
    )
    parser.add_argument(
        "--progress-log",
        action="store_true",
        help="Stream native H48 generator progress logs to stderr while preserving JSON metadata on stdout",
    )
    parser.add_argument(
        "--gendata-workbatch",
        default=None,
        help=(
            "Native H48 short-cube scheduling batch size. Smaller values improve load balancing and progress "
            "visibility for h48h8+ generation; default is RUBIK_OPTIMAL_H48_GENDATA_WORKBATCH or the repo default."
        ),
    )
    parser.add_argument(
        "--skip-generation-distribution-scan",
        action="store_true",
        help=(
            "Write nissy-core's canonical expected H48 distribution values instead of scanning the completed "
            "main H48 table after generation. This is intended for trusted-table H48H10+ proof runs where "
            "full checksum validation and trusted metadata are used before solving."
        ),
    )
    parser.add_argument(
        "--mmap-sync-mode",
        choices=["sync", "async", "none"],
        default="sync",
        help=(
            "Sync policy for --mmap-output generation. 'sync' preserves the historical blocking msync; "
            "'async' asks the OS to schedule writeback without blocking on the whole table; 'none' skips "
            "explicit msync. The generated file is still size-checked and SHA-256 checked before trusted use."
        ),
    )
    parser.add_argument(
        "--backend-cflag",
        action="append",
        default=[],
        help=(
            "Audited extra compiler flag for the native H48 backend, for example "
            "--backend-cflag=-march=native on a dedicated proof host. Only CPU tuning/LTO flags are accepted."
        ),
    )
    parser.add_argument(
        "--min-mmap-available-memory-gib",
        type=float,
        default=None,
        help=(
            "Override the default 4 GiB immediately-available-memory guard for output-backed mmap "
            "generation. Use only for deliberately controlled local runs; the chosen threshold is "
            "recorded in generated metadata."
        ),
    )
    parser.add_argument(
        "--disk-multiplier",
        type=float,
        default=None,
        help=(
            "Override the free-disk headroom multiplier used by --require-safe. Defaults are storage-aware: "
            "staged mmap output uses smaller headroom than heap output."
        ),
    )
    parser.add_argument(
        "--safety-only",
        action="store_true",
        help="Print the H48 generation safety decision and exit without generating or reusing a table.",
    )
    parser.add_argument(
        "--adopt-existing-table-metadata",
        action="store_true",
        help=(
            "If the canonical table file already exists with the exact expected size, run the native "
            "table-check canary, compute SHA-256, and write explicit adoption metadata instead of "
            "regenerating the table. This is intended for retained or interrupted long H48 table runs."
        ),
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    solver = ORACLE_H48_SOLVER if args.oracle else args.solver
    threads = parse_thread_setting(args.threads)
    gendata_workbatch = resolve_h48_gendata_workbatch(args.gendata_workbatch)
    mmap_sync_mode = normalize_h48_mmap_sync_mode(args.mmap_sync_mode)
    backend_extra_cflags = normalize_h48_backend_extra_cflags(args.backend_cflag)
    effective_mmap_output = True if args.mmap_output else False if args.heap_output else None
    safety = evaluate_h48_generation_safety(
        root=args.root,
        solver=solver,
        threads=threads,
        mmap_output=effective_mmap_output,
        min_mmap_available_memory_bytes=(
            parse_gib(args.min_mmap_available_memory_gib) or 4 * 1024**3
            if args.min_mmap_available_memory_gib is not None
            else 4 * 1024**3
        ),
        disk_multiplier=args.disk_multiplier,
    )
    if args.safety_only:
        print(
            json.dumps(
                {
                    "status": "safety_passed" if safety["safe_to_start"] else "safety_failed",
                    "solver": solver,
                    "profile": args.profile,
                    "seed": args.seed,
                    "threads": threads,
                    "would_generate": safety["safe_to_start"] or args.unsafe_allow_loaded_machine,
                    "h48_gendata_workbatch": gendata_workbatch,
                    "h48_generation_distribution_mode": "expected_constants"
                    if args.skip_generation_distribution_scan
                    else "scanned",
                    "h48_generation_mmap_sync_mode": mmap_sync_mode
                    if effective_mmap_output is not False
                    else "not_applicable",
                    "h48_backend_extra_cflags": list(backend_extra_cflags),
                    "safety": safety,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if args.require_safe and not safety["safe_to_start"] and not args.unsafe_allow_loaded_machine:
        print(
            json.dumps(
                {
                    "status": "refused",
                    "reason": "current machine failed H48 generation safety checks",
                    "safety": safety,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 2

    metadata = generate_h48_table(
        root=args.root,
        profile=args.profile,
        seed=args.seed,
        solver=solver,
        threads=threads,
        force=args.force,
        mmap_output=effective_mmap_output,
        progress_log=args.progress_log,
        gendata_workbatch=gendata_workbatch,
        use_expected_distribution=args.skip_generation_distribution_scan,
        mmap_sync_mode=mmap_sync_mode,
        backend_extra_cflags=backend_extra_cflags,
        adopt_existing_table_metadata=args.adopt_existing_table_metadata,
    )
    metadata["generation_safety"] = safety
    print(json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

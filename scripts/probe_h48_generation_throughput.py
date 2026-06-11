#!/usr/bin/env python
"""Run a bounded native H48 generation probe and record throughput evidence."""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rubik_optimal.results import write_json  # noqa: E402
from rubik_optimal.runtime import parse_thread_setting  # noqa: E402
from rubik_optimal.tables.h48 import (  # noqa: E402
    build_h48_backend,
    canonical_h48_solver,
    estimated_h48_table_size_bytes,
    h48_table_path,
    resolve_h48_gendata_workbatch,
)
from scripts.inspect_h48_capacity import evaluate_h48_generation_safety  # noqa: E402


PROGRESS_RE = re.compile(
    r"(?:Scanned\s+(?P<scanned>\d+)\s*/\s*(?P<scan_total>\d+)\s+slots;\s+)?"
    r"Processed\s+(?P<done>\d+)\s*/\s*(?P<total>\d+)\s+cubes"
)


def parse_progress_lines(text: str) -> list[dict[str, int]]:
    """Extract native H48 short-cube progress samples from stderr text."""

    samples: list[dict[str, int]] = []
    for match in PROGRESS_RE.finditer(text):
        scanned = match.group("scanned")
        scan_total = match.group("scan_total")
        samples.append(
            {
                "processed_short_cubes": int(match.group("done")),
                "total_short_cubes": int(match.group("total")),
                "scanned_shortcube_slots": int(scanned) if scanned is not None else None,
                "total_shortcube_slots": int(scan_total) if scan_total is not None else None,
            }
        )
    return samples


def _load_average() -> tuple[float, float, float] | None:
    try:
        return tuple(float(value) for value in os.getloadavg())
    except OSError:
        return None


def _disk_allocated_bytes(path: Path) -> int | None:
    try:
        return int(path.stat().st_blocks) * 512
    except (AttributeError, OSError):
        return None


def _tex(value: object) -> str:
    return str(value).replace("\\", "\\textbackslash{}").replace("_", "\\_").replace("&", "\\&")


def _write_table(root: Path, payload: dict[str, Any], suffix: str) -> Path:
    filename = f"h48_generation_probe{suffix}.tex" if suffix else "h48_generation_probe.tex"
    table_path = root / "thesis" / "tables" / filename
    table_path.parent.mkdir(parents=True, exist_ok=True)
    row = (
        f"{_tex(payload['solver'])} & "
        f"{_tex(payload['status'])} & "
        f"{payload['timeout_seconds']} & "
        f"{payload['threads']} & "
        f"{_tex(payload.get('latest_processed_short_cubes'))} & "
        f"{_tex(payload.get('total_short_cubes'))} & "
        f"{_tex(payload.get('estimated_remaining_seconds'))} \\\\"
    )
    table_path.write_text(
        "{\\small\n"
        "\\begin{tabular}{llrrrrr}\n"
        "\\hline\n"
        "Solver & Probe status & Seconds & Threads & Done & Total & ETA seconds \\\\\n"
        "\\hline\n"
        + row
        + "\n\\hline\n\\end{tabular}\n"
        "}\n",
        encoding="utf-8",
    )
    return table_path


def run_probe(
    *,
    root: Path,
    profile: str,
    seed: int,
    solver: str,
    threads: int,
    timeout_seconds: float,
    artifact_suffix: str,
    gendata_workbatch: int | str | None = None,
    keep_partial: bool = False,
) -> dict[str, Any]:
    solver = canonical_h48_solver(solver)
    resolved_workbatch = resolve_h48_gendata_workbatch(gendata_workbatch)
    expected_size = estimated_h48_table_size_bytes(solver)
    safety = evaluate_h48_generation_safety(root=root, solver=solver, threads=threads)
    binary = build_h48_backend(root=root, threads=threads, gendata_workbatch=resolved_workbatch)
    probe_dir = root / "data" / "generated" / "h48" / f"{profile}_seed_{seed}" / "probes"
    probe_dir.mkdir(parents=True, exist_ok=True)
    partial_path = probe_dir / f"{solver}_{artifact_suffix or 'probe'}.partial.bin"
    if partial_path.exists():
        partial_path.unlink()

    command = [
        str(binary),
        "--generate",
        "--solver",
        solver,
        "--output",
        str(partial_path),
        "--threads",
        str(max(1, threads)),
        "--generate-mmap",
        "--progress-log",
    ]
    begin = time.perf_counter()
    start_load = _load_average()
    status = "timed_out"
    stdout = ""
    stderr = ""
    return_code: int | None = None
    process = subprocess.Popen(
        command,
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
        return_code = process.returncode
        status = "completed" if return_code == 0 else "failed"
    except subprocess.TimeoutExpired:
        status = "timed_out"
        try:
            os.killpg(process.pid, signal.SIGTERM)
            stdout, stderr = process.communicate(timeout=5.0)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate(timeout=5.0)
        return_code = process.returncode
    runtime_seconds = time.perf_counter() - begin
    end_load = _load_average()

    samples = parse_progress_lines(stderr)
    latest = samples[-1] if samples else None
    latest_done = int(latest["processed_short_cubes"]) if latest else None
    latest_total = int(latest["total_short_cubes"]) if latest else None
    latest_scanned = int(latest["scanned_shortcube_slots"]) if latest and latest.get("scanned_shortcube_slots") is not None else None
    latest_scan_total = int(latest["total_shortcube_slots"]) if latest and latest.get("total_shortcube_slots") is not None else None
    throughput = (latest_done / runtime_seconds) if latest_done and runtime_seconds > 0 else None
    scan_throughput = (latest_scanned / runtime_seconds) if latest_scanned and runtime_seconds > 0 else None
    estimated_remaining = (
        ((latest_total - latest_done) / throughput)
        if latest_total is not None and latest_done is not None and throughput and throughput > 0
        else None
    )
    estimated_scan_remaining = (
        ((latest_scan_total - latest_scanned) / scan_throughput)
        if latest_scan_total is not None
        and latest_scanned is not None
        and scan_throughput
        and scan_throughput > 0
        else None
    )
    sparse_size = partial_path.stat().st_size if partial_path.exists() else 0
    allocated_size = _disk_allocated_bytes(partial_path) if partial_path.exists() else 0
    cleanup_status = "not_needed"
    if partial_path.exists() and not keep_partial:
        partial_path.unlink()
        cleanup_status = "deleted_partial_probe_file"
    elif partial_path.exists():
        cleanup_status = "kept_partial_probe_file"

    backend_payload: dict[str, Any] | None = None
    if stdout.strip():
        try:
            backend_payload = json.loads(stdout)
        except json.JSONDecodeError:
            backend_payload = None

    payload: dict[str, Any] = {
        "schema_version": 1,
        "checked_at_utc": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "profile": profile,
        "seed": seed,
        "solver": solver,
        "timeout_seconds": timeout_seconds,
        "threads": max(1, threads),
        "h48_gendata_workbatch": resolved_workbatch,
        "status": status,
        "return_code": return_code,
        "runtime_seconds": round(runtime_seconds, 6),
        "command": " ".join(command),
        "expected_table_size_bytes": expected_size,
        "expected_table_size_gib": round(expected_size / (1024**3), 6),
        "partial_path": str(partial_path.relative_to(root)),
        "partial_sparse_size_bytes_before_cleanup": sparse_size,
        "partial_allocated_size_bytes_before_cleanup": allocated_size,
        "partial_cleanup_status": cleanup_status,
        "progress_samples": samples,
        "latest_processed_short_cubes": latest_done,
        "total_short_cubes": latest_total,
        "latest_scanned_shortcube_slots": latest_scanned,
        "total_shortcube_slots": latest_scan_total,
        "estimated_short_cubes_per_second": round(throughput, 6) if throughput is not None else None,
        "estimated_scanned_slots_per_second": round(scan_throughput, 6) if scan_throughput is not None else None,
        "estimated_remaining_seconds": round(estimated_remaining, 3) if estimated_remaining is not None else None,
        "estimated_remaining_hours": round(estimated_remaining / 3600, 3) if estimated_remaining is not None else None,
        "estimated_scan_remaining_seconds": (
            round(estimated_scan_remaining, 3) if estimated_scan_remaining is not None else None
        ),
        "estimated_scan_remaining_hours": (
            round(estimated_scan_remaining / 3600, 3) if estimated_scan_remaining is not None else None
        ),
        "native_stdout": stdout.strip(),
        "native_stderr_tail": "\n".join(stderr.splitlines()[-20:]),
        "backend_payload": backend_payload,
        "safety": safety,
        "machine": {
            "load_average_start": start_load,
            "load_average_end": end_load,
        },
        "full_table_generated": status == "completed" and backend_payload is not None and backend_payload.get("status") == "generated",
        "probe_completed": status in {"timed_out", "completed"},
        "notes": (
            "Bounded native H48 generation probe. A timed-out status is expected for h48h8+ "
            "short probes; the script records native progress and deletes the partial sparse table "
            "unless --keep-partial is explicitly used."
        ),
    }
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default="thesis")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--solver", default="h48h8")
    parser.add_argument("--threads", default="auto")
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--artifact-suffix", default="lowload")
    parser.add_argument(
        "--gendata-workbatch",
        default=None,
        help=(
            "Native H48 short-cube scheduling batch size used when compiling "
            "the probe backend. Defaults to RUBIK_OPTIMAL_H48_GENDATA_WORKBATCH "
            "or the repository default."
        ),
    )
    parser.add_argument("--keep-partial", action="store_true")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()

    threads = parse_thread_setting(args.threads)
    payload = run_probe(
        root=args.root,
        profile=args.profile,
        seed=args.seed,
        solver=args.solver,
        threads=threads,
        timeout_seconds=max(1.0, args.timeout),
        artifact_suffix=args.artifact_suffix,
        gendata_workbatch=args.gendata_workbatch,
        keep_partial=args.keep_partial,
    )
    suffix_parts = [f"seed_{args.seed}", args.profile, payload["solver"]]
    if args.artifact_suffix:
        suffix_parts.append(args.artifact_suffix)
    suffix = "_" + "_".join(str(part) for part in suffix_parts)
    output = args.root / "results" / "processed" / f"h48_generation_probe{suffix}.json"
    write_json(output, payload)
    table = _write_table(args.root, payload, suffix)
    print(
        json.dumps(
            {
                "output": str(output),
                "table": str(table),
                "status": payload["status"],
                "h48_gendata_workbatch": payload["h48_gendata_workbatch"],
                "latest_processed_short_cubes": payload["latest_processed_short_cubes"],
                "latest_scanned_shortcube_slots": payload["latest_scanned_shortcube_slots"],
                "estimated_remaining_hours": payload["estimated_remaining_hours"],
                "estimated_scan_remaining_hours": payload["estimated_scan_remaining_hours"],
                "partial_cleanup_status": payload["partial_cleanup_status"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if payload["probe_completed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python
"""Probe native Kociemba phase-2 subsearches for superflip handoffs.

This is a Path 2/Path 3 bridge measurement.  It keeps the existing Python
phase-1 handoff collector, but replaces the slow Python phase-2 IDA* with the
own-code C++ phase-2 probe.  A row can only disprove a total length <= U for a
sampled handoff; the whole artifact is a proof only if phase-1 collection
finishes exhaustively for the configured depth.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from rubik_optimal.cube import CubeState
from rubik_optimal.solvers.kociemba import (
    collect_kociemba_phase1_candidates,
    kociemba_phase2_projection_lower_bound,
)


def superflip_cube() -> CubeState:
    return CubeState(
        cp=tuple(range(8)),
        co=(0,) * 8,
        ep=tuple(range(12)),
        eo=(1,) * 12,
    )


def _csv(values: tuple[int, ...]) -> str:
    return ",".join(str(value) for value in values)


def compile_native() -> Path:
    source = ROOT / "native" / "kociemba_phase2_probe" / "kociemba_phase2_probe.cpp"
    binary = ROOT / "native" / "build" / "kociemba_phase2_probe"
    binary.parent.mkdir(parents=True, exist_ok=True)
    if binary.exists() and binary.stat().st_mtime >= source.stat().st_mtime:
        return binary
    subprocess.run(
        ["c++", "-std=c++17", "-O3", "-DNDEBUG", str(source), "-o", str(binary)],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return binary


def native_phase2_row(
    binary: Path,
    cube: CubeState,
    *,
    max_depth: int,
    timeout: float,
    node_limit: int,
) -> dict[str, object]:
    command = [
        str(binary),
        "--cp",
        _csv(cube.cp),
        "--co",
        _csv(cube.co),
        "--ep",
        _csv(cube.ep),
        "--eo",
        _csv(cube.eo),
        "--max-depth",
        str(max_depth),
        "--timeout",
        str(timeout),
        "--node-limit",
        str(node_limit),
    ]
    begin = time.perf_counter()
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    elapsed = time.perf_counter() - begin
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        payload = {
            "status": "failed",
            "solution_length": None,
            "solution_moves": [],
            "error": completed.stderr.strip() or completed.stdout.strip(),
        }
    payload["return_code"] = completed.returncode
    payload["wrapper_elapsed_seconds"] = elapsed
    payload["command"] = command
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="thesis")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--phase1-max-depth", type=int, default=11)
    parser.add_argument("--phase1-timeout", type=float, default=90.0)
    parser.add_argument("--phase1-node-limit", type=int, default=200_000_000)
    parser.add_argument("--phase1-max-candidates", type=int, default=30)
    parser.add_argument("--target-upper-bound", type=int, default=20)
    parser.add_argument("--phase2-timeout", type=float, default=5.0)
    parser.add_argument("--phase2-node-limit", type=int, default=50_000_000)
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "results" / "processed" / "native_kociemba_phase2_superflip_probe_seed_2026.json",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    binary = compile_native()
    cube = superflip_cube()

    phase1_begin = time.perf_counter()
    phase1 = collect_kociemba_phase1_candidates(
        cube,
        max_depth=args.phase1_max_depth,
        timeout_seconds=args.phase1_timeout,
        node_limit=args.phase1_node_limit,
        max_candidates=args.phase1_max_candidates,
    )
    phase1_elapsed = time.perf_counter() - phase1_begin

    rows: list[dict[str, object]] = []
    for index, phase1_solution in enumerate(phase1.solutions):
        handoff = cube.apply_sequence(phase1_solution)
        phase1_len = len(phase1_solution)
        proof_cap = args.target_upper_bound - phase1_len
        if proof_cap < 0:
            phase2 = {
                "status": "lower_bound",
                "solution_length": None,
                "solution_moves": [],
                "final_bound": proof_cap,
                "expanded_nodes": 0,
                "generated_nodes": 0,
                "runtime_seconds": 0.0,
            }
        else:
            phase2 = native_phase2_row(
                binary,
                handoff,
                max_depth=proof_cap,
                timeout=args.phase2_timeout,
                node_limit=args.phase2_node_limit,
            )
        total_length = (
            phase1_len + int(phase2["solution_length"])
            if phase2.get("solution_length") is not None
            else None
        )
        rows.append(
            {
                "candidate_index": index,
                "phase1_length": phase1_len,
                "phase1_moves": list(phase1_solution),
                "phase2_projection_lower_bound": kociemba_phase2_projection_lower_bound(handoff),
                "target_upper_bound": args.target_upper_bound,
                "phase2_proof_cap": proof_cap,
                "phase2": phase2,
                "total_length": total_length,
                "proves_no_total_below_or_equal_target": phase2.get("status") == "lower_bound",
            }
        )

    phase1_exhaustive = (
        "timeout" not in phase1.notes.lower()
        and "node limit" not in phase1.notes.lower()
        and phase1.status == "exact"
        and len(phase1.solutions) < args.phase1_max_candidates
    )
    payload = {
        "schema_version": 1,
        "profile": args.profile,
        "seed": args.seed,
        "target": "superflip",
        "solver": "kociemba_phase2_native_probe",
        "uses_h48_or_nissy": False,
        "proof_policy": (
            "whole artifact is a proof only if phase1_exhaustive is true and every candidate row "
            "proves no phase2 suffix within target_upper_bound - phase1_length"
        ),
        "target_upper_bound": args.target_upper_bound,
        "phase1_max_depth": args.phase1_max_depth,
        "phase1_timeout_seconds": args.phase1_timeout,
        "phase1_node_limit": args.phase1_node_limit,
        "phase1_max_candidates": args.phase1_max_candidates,
        "phase1_status": phase1.status,
        "phase1_notes": phase1.notes,
        "phase1_exhaustive": phase1_exhaustive,
        "phase1_candidate_count": len(phase1.solutions),
        "phase1_expanded_nodes": phase1.expanded_nodes,
        "phase1_generated_nodes": phase1.generated_nodes,
        "phase1_runtime_seconds": phase1_elapsed,
        "phase2_timeout_seconds": args.phase2_timeout,
        "phase2_node_limit": args.phase2_node_limit,
        "rows": rows,
        "artifact_proves_no_solution_at_or_below_target": bool(
            phase1_exhaustive and rows and all(row["proves_no_total_below_or_equal_target"] for row in rows)
        ),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python
"""Run the native Reid single-bound IDA* optimal solver on the superflip.

This is the own-code (no H48/Nissy) optimality-proof driver.  It performs ONE
bounded IDA* search directly to the solved state over all 18 moves, using the
symmetric FlipUDSlice three-axis phase-1 distance max(p_ud, p_rl, p_fb) as an
admissible heuristic, plus full whole-cube root-symmetry masking (the superflip
is invariant under all 48 symmetries, so the first move collapses to U, U2).

Running at ``--target-bound 19`` proves the superflip has no solution of length
<= 19 if and only if the search exhausts the bound with no solved leaf, i.e. the
payload reports ``proves_no_solution_at_or_below_target=true`` with
``status=lower_bound`` (combined with the known length-20 solution, that proves
distance = 20).  A timeout proves nothing.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from rubik_optimal.symmetry import root_symmetry_representative_moves, three_axis_phase1_inputs

from scripts.probe_native_kociemba_phase2_superflip import _csv, compile_native, superflip_cube


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="thesis")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--target-bound", type=int, default=19)
    parser.add_argument("--timeout", type=float, default=3600.0)
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--split-depth", type=int, default=3)
    parser.add_argument("--no-root-symmetry-prune", action="store_true")
    parser.add_argument(
        "--sym-tables",
        type=Path,
        default=ROOT / "data" / "generated" / "phase1_sym_tables.bin",
    )
    parser.add_argument(
        "--sym-phase1-cache",
        type=Path,
        default=ROOT / "data" / "generated" / "kociemba_phase1_sym_depth12.bin",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "results" / "processed" / "native_reid_optimal_superflip_probe_seed_2026.json",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    binary = compile_native()
    cube = superflip_cube()
    inputs = three_axis_phase1_inputs(cube)
    rl = inputs.rl_cube
    fb = inputs.fb_cube
    root_reps = tuple(root_symmetry_representative_moves(cube))

    command = [
        str(binary),
        "--mode",
        "optimal-ida",
        "--target-bound",
        str(args.target_bound),
        "--timeout",
        str(args.timeout),
        "--threads",
        str(args.threads),
        "--split-depth",
        str(args.split_depth),
        "--sym-phase1-pruning",
        "--sym-tables",
        str(args.sym_tables),
        "--sym-phase1-cache",
        str(args.sym_phase1_cache),
        "--three-axis-pruning",
        "--conj-rl",
        ",".join(inputs.conj_rl),
        "--conj-fb",
        ",".join(inputs.conj_fb),
        "--cp-rl", _csv(rl.cp), "--co-rl", _csv(rl.co), "--ep-rl", _csv(rl.ep), "--eo-rl", _csv(rl.eo),
        "--cp-fb", _csv(fb.cp), "--co-fb", _csv(fb.co), "--ep-fb", _csv(fb.ep), "--eo-fb", _csv(fb.eo),
        "--cp", _csv(cube.cp), "--co", _csv(cube.co), "--ep", _csv(cube.ep), "--eo", _csv(cube.eo),
    ]
    if not args.no_root_symmetry_prune:
        command.extend(["--root-move-mask", ",".join(root_reps)])

    begin = time.perf_counter()
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    elapsed = time.perf_counter() - begin
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        payload = {
            "schema_version": 1,
            "solver_name": "kociemba_reid_optimal_ida",
            "status": "failed",
            "error": completed.stderr.strip() or completed.stdout.strip(),
        }
    payload.update(
        {
            "profile": args.profile,
            "seed": args.seed,
            "target": "superflip",
            "return_code": completed.returncode,
            "wrapper_elapsed_seconds": elapsed,
            "command": command,
            "root_symmetry_representatives": list(root_reps),
            "root_symmetry_policy": (
                "full 48-element whole-cube symmetry stabilizer of the superflip; exact-safe because a "
                "shorter solution starting with move m implies one starting with each symmetric image of m"
            ),
            "proof_policy": (
                "proves no solution at or below target only when status=lower_bound and "
                "proves_no_solution_at_or_below_target=true (search exhausted bound with no solved leaf)"
            ),
            "uses_h48_or_nissy": False,
            "stderr": completed.stderr,
        }
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if completed.returncode == 0 else completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())

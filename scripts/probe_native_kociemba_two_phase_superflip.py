#!/usr/bin/env python
"""Run the native two-phase Kociemba bound probe on the superflip.

The probe is own-code only: native phase-1 enumeration plus native phase-2 cap
checks.  It can disprove a target bound only when the native payload reports
``phase1_exhaustive_for_target_bound=true`` and no phase-2 cap row timed out.
Partial-depth artifacts are still useful frontier measurements, but they are not
optimality proofs for the superflip.
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

from rubik_optimal.symmetry import (
    root_g1_preserving_symmetry_representative_moves,
    three_axis_phase1_inputs,
)

from scripts.probe_native_kociemba_phase2_superflip import _csv, compile_native, superflip_cube


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="thesis")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--target-bound", type=int, default=20)
    parser.add_argument("--phase1-start-depth", type=int, default=0)
    parser.add_argument("--phase1-max-depth", type=int, default=13)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--phase1-node-limit", type=int, default=2_000_000_000)
    parser.add_argument("--phase2-node-limit", type=int, default=50_000_000)
    parser.add_argument("--no-root-symmetry-prune", action="store_true")
    parser.add_argument("--no-handoff-dedup", action="store_true")
    parser.add_argument("--no-cp-target-pruning", action="store_true")
    parser.add_argument("--phase1-full-pruning", action="store_true")
    parser.add_argument("--phase1-full-pruning-min-depth", type=int, default=0)
    parser.add_argument("--phase1-full-pruning-max-depth", type=int, default=12)
    parser.add_argument(
        "--phase1-full-pruning-cache",
        type=Path,
        help="Cache path for the full phase-1 CO x EO x UD-slice pruning table; may include {depth}.",
    )
    parser.add_argument(
        "--sym-phase1-pruning",
        action="store_true",
        help="Use the FlipUDSlice 16-symmetry phase-1 pruning table (141 MB, exact to depth 12).",
    )
    parser.add_argument("--sym-phase1-max-depth", type=int, default=12)
    parser.add_argument(
        "--sym-tables",
        type=Path,
        default=ROOT / "data" / "generated" / "phase1_sym_tables.bin",
        help="Path to the phase-1 symmetry reduction tables (generate_phase1_sym_tables.py).",
    )
    parser.add_argument(
        "--sym-phase1-cache",
        type=Path,
        default=ROOT / "data" / "generated" / "kociemba_phase1_sym_depth12.bin",
        help="Cache path for the symmetry-reduced phase-1 pruning table.",
    )
    parser.add_argument(
        "--three-axis-pruning",
        action="store_true",
        help="Add Mike Reid's three-axis phase-1 bound max(p_ud,p_rl,p_fb) (needs --sym-phase1-pruning).",
    )
    parser.add_argument(
        "--allow-threaded-cp-target-pruning",
        action="store_true",
        help="Keep CP-target pruning enabled with threads > 1; default threaded runs still disable it.",
    )
    parser.add_argument("--cp-slice-target-pruning", action="store_true")
    parser.add_argument("--cp-slice-target-min-depth", type=int, default=0)
    parser.add_argument(
        "--cp-slice-target-cache",
        type=Path,
        help="Cache path for the CP x labeled-slice target table; may include {cap} and {depth}.",
    )
    parser.add_argument("--ud-edge-target-pruning", action="store_true")
    parser.add_argument("--ud-edge-target-min-depth", type=int, default=0)
    parser.add_argument(
        "--ud-edge-target-cache",
        type=Path,
        help="Cache path for the labeled UD-edge target table; may include {cap} and {depth}.",
    )
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--split-depth", type=int, default=0)
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "results" / "processed" / "native_kociemba_two_phase_superflip_probe_seed_2026.json",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    binary = compile_native()
    cube = superflip_cube()
    root_reps = tuple(root_g1_preserving_symmetry_representative_moves(cube))
    command = [
        str(binary),
        "--mode",
        "two-phase",
        "--target-bound",
        str(args.target_bound),
        "--phase1-start-depth",
        str(args.phase1_start_depth),
        "--phase1-max-depth",
        str(args.phase1_max_depth),
        "--timeout",
        str(args.timeout),
        "--phase1-node-limit",
        str(args.phase1_node_limit),
        "--phase2-node-limit",
        str(args.phase2_node_limit),
        "--threads",
        str(args.threads),
        "--split-depth",
        str(args.split_depth),
        "--cp",
        _csv(cube.cp),
        "--co",
        _csv(cube.co),
        "--ep",
        _csv(cube.ep),
        "--eo",
        _csv(cube.eo),
    ]
    if not args.no_root_symmetry_prune:
        command.extend(["--root-move-mask", ",".join(root_reps)])
    if args.no_handoff_dedup:
        command.append("--no-handoff-dedup")
    cp_target_pruning_disabled = (
        args.no_cp_target_pruning
        or (args.threads > 1 and not args.allow_threaded_cp_target_pruning)
    )
    if cp_target_pruning_disabled:
        command.append("--no-cp-target-pruning")
    if args.phase1_full_pruning:
        command.append("--phase1-full-pruning")
        command.extend(["--phase1-full-pruning-min-depth", str(args.phase1_full_pruning_min_depth)])
        command.extend(["--phase1-full-pruning-max-depth", str(args.phase1_full_pruning_max_depth)])
        if args.phase1_full_pruning_cache is not None:
            args.phase1_full_pruning_cache.parent.mkdir(parents=True, exist_ok=True)
            command.extend(["--phase1-full-pruning-cache", str(args.phase1_full_pruning_cache)])
    if args.sym_phase1_pruning:
        command.append("--sym-phase1-pruning")
        command.extend(["--sym-phase1-max-depth", str(args.sym_phase1_max_depth)])
        command.extend(["--sym-tables", str(args.sym_tables)])
        if args.sym_phase1_cache is not None:
            args.sym_phase1_cache.parent.mkdir(parents=True, exist_ok=True)
            command.extend(["--sym-phase1-cache", str(args.sym_phase1_cache)])
    three_axis_info: dict[str, object] = {}
    if args.three_axis_pruning:
        inputs = three_axis_phase1_inputs(cube)
        rl_cube = inputs.rl_cube
        fb_cube = inputs.fb_cube
        three_axis_info = {
            "rl_rotation": inputs.rl_rotation,
            "fb_rotation": inputs.fb_rotation,
            "conj_rl": inputs.conj_rl,
            "conj_fb": inputs.conj_fb,
        }
        command.append("--three-axis-pruning")
        command.extend(["--conj-rl", ",".join(inputs.conj_rl)])
        command.extend(["--conj-fb", ",".join(inputs.conj_fb)])
        command.extend(["--cp-rl", _csv(rl_cube.cp), "--co-rl", _csv(rl_cube.co)])
        command.extend(["--ep-rl", _csv(rl_cube.ep), "--eo-rl", _csv(rl_cube.eo)])
        command.extend(["--cp-fb", _csv(fb_cube.cp), "--co-fb", _csv(fb_cube.co)])
        command.extend(["--ep-fb", _csv(fb_cube.ep), "--eo-fb", _csv(fb_cube.eo)])
    if args.cp_slice_target_pruning:
        command.append("--cp-slice-target-pruning")
        command.extend(["--cp-slice-target-min-depth", str(args.cp_slice_target_min_depth)])
        if args.cp_slice_target_cache is not None:
            args.cp_slice_target_cache.parent.mkdir(parents=True, exist_ok=True)
            command.extend(["--cp-slice-target-cache", str(args.cp_slice_target_cache)])
    if args.ud_edge_target_pruning:
        command.append("--ud-edge-target-pruning")
        command.extend(["--ud-edge-target-min-depth", str(args.ud_edge_target_min_depth)])
        if args.ud_edge_target_cache is not None:
            args.ud_edge_target_cache.parent.mkdir(parents=True, exist_ok=True)
            command.extend(["--ud-edge-target-cache", str(args.ud_edge_target_cache)])

    begin = time.perf_counter()
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    elapsed = time.perf_counter() - begin
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        payload = {
            "schema_version": 1,
            "solver_name": "kociemba_two_phase_native_probe",
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
            "root_symmetry_policy": "G1-preserving stabilizer only; safe for fixed-UD-axis Kociemba phase split",
            "cp_target_pruning_policy": (
                "enabled by default for serial native runs; threaded wrapper runs disable it unless "
                "--allow-threaded-cp-target-pruning is passed"
            ),
            "phase1_full_pruning_policy": (
                "opt-in full CO x EO x UD-slice phase-1 pruning table; exact-safe lower bound, cache paths "
                "may use {depth}; disabled unless requested because the byte table is multi-GiB"
            ),
            "sym_phase1_pruning_policy": (
                "opt-in FlipUDSlice 16-symmetry phase-1 pruning table (64,430 classes x 2,187 twist = "
                "140,908,410 entries, ~141 MB, exact phase-1 distance to depth 12); admissible lower bound "
                "validated byte-for-byte against the raw phase-1 BFS table on all known (<=9) entries via "
                "--mode verify-sym-phase1; supersedes the 2.2 GiB raw table at ~16x less memory"
            ),
            "three_axis_pruning_policy": (
                "opt-in Mike Reid/Cube-Explorer three-axis phase-1 bound: prune when g + max(p_ud,p_rl,p_fb) "
                "> target_bound, where p_axis is the symmetric phase-1 distance of the state conjugated onto "
                "that axis (admissible global lower bound on the whole-solution length); the superflip is "
                "axis-symmetric so this only tightens interior (asymmetric) nodes, not the root"
            ),
            "three_axis_info": three_axis_info,
            "cp_slice_target_pruning_policy": (
                "opt-in bounded CP x labeled-UD-slice target table; read-only cached table may be shared "
                "by native workers, and cache paths may use {cap}/{depth} placeholders; disabled unless requested"
            ),
            "ud_edge_target_pruning_policy": (
                "opt-in bounded labeled-UD-edge target table for the phase-2 UD-edge suffix projection; "
                "cache paths may use {cap}/{depth} placeholders; disabled unless requested"
            ),
            "proof_policy": (
                "proves no solution at or below target only when the native payload has "
                "phase1_exhaustive_for_target_bound=true and proves_no_solution_at_or_below_target=true"
            ),
            "stderr": completed.stderr,
        }
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if completed.returncode == 0 else completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python
"""Live demonstration of the native 3x3 optimal-solution oracle.

This drives the package's :class:`FastOptimalOracle` (resident native nissy-core
H48 ``h48h7`` backend) on a small set of real 3x3 states -- the solved cube, a
shallow sequence, deterministic random scrambles at increasing depth, and the
standard superflip (a known half-turn-metric distance-20 representative). For
every state the oracle returns a solution that is bounded by ``max_depth=20``
(the cited God's Number depth bound) and is then **independently re-verified**
by replaying the moves with :func:`rubik_optimal.verify.verify_solution`.

The script proves, per instance, that the returned sequence both solves the cube
and is optimal (status ``exact`` only when the admissible search closed the
bound). It is a per-state demonstration over a chosen corpus; it is not an
exhaustive runtime proof over all ~4.3e19 states (see
``docs/scope_and_hardware_reality.md``).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rubik_optimal.cube import CubeState
from rubik_optimal.oracle import FastOptimalOracle, FastOptimalOracleConfig
from rubik_optimal.results import write_json
from rubik_optimal.scramble import deterministic_scramble
from rubik_optimal.tables.h48 import canonical_h48_solver, h48_table_path
from rubik_optimal.verify import verify_solution
from scripts.run_h48_oracle_certification import superflip_cube

GODS_NUMBER_HTM = 20


def demo_cases(seed: int, *, depths: tuple[int, ...]) -> list[dict[str, object]]:
    """Build the demonstration corpus of real 3x3 states."""

    cases: list[dict[str, object]] = [
        {"case_id": "solved", "kind": "identity", "scramble_depth": 0, "cube": CubeState.solved()},
        {
            "case_id": "sequence_R_U_F2",
            "kind": "sequence",
            "scramble_depth": 3,
            "cube": CubeState.from_sequence("R U F2"),
        },
    ]
    for depth in depths:
        scramble = deterministic_scramble(depth, seed, offset=7000 + depth)
        cases.append(
            {
                "case_id": f"random_depth_{depth}",
                "kind": "deterministic_scramble",
                "scramble_depth": depth,
                "scramble": " ".join(scramble),
                "cube": CubeState.from_sequence(scramble),
            }
        )
    cases.append(
        {
            "case_id": "superflip_distance_20",
            "kind": "superflip",
            "scramble_depth": None,
            "cube": superflip_cube(),
        }
    )
    return cases


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="thesis")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--solver", default="h48h7")
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument(
        "--timeout",
        type=float,
        default=150.0,
        help="per-state deadline; the hardest distance-20 states are the slow ones",
    )
    parser.add_argument(
        "--depths",
        type=int,
        nargs="+",
        default=[8, 12, 16],
        help="deterministic scramble depths to demonstrate",
    )
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()

    solver = canonical_h48_solver(args.solver)
    table_path = h48_table_path(root=args.root, profile=args.profile, seed=args.seed, solver=solver)
    if not table_path.exists():
        raise SystemExit(f"missing H48 table: {table_path}")

    config = FastOptimalOracleConfig(
        profile=args.profile,
        seed=args.seed,
        solver=solver,
        threads=args.threads,
        timeout_seconds=args.timeout,
        max_depth=GODS_NUMBER_HTM,
        trusted_table=True,
        root=args.root,
    )

    print(f"3x3 optimal-solution oracle  |  backend={solver}  table={table_path.stat().st_size/1e9:.2f} GB"
          f"  threads={args.threads}  deadline={args.timeout:.0f}s")
    print("-" * 100)
    print(f"{'case':24s} {'status':9s} {'depth':>6s} {'optimal':>8s} {'<=20':>5s} {'seconds':>10s}  verified")
    print("-" * 100)

    rows: list[dict[str, object]] = []
    runtimes: list[float] = []
    errors: list[str] = []
    oracle = FastOptimalOracle(config)
    try:
        for case in demo_cases(args.seed, depths=tuple(args.depths)):
            cube = case["cube"]
            assert isinstance(cube, CubeState)
            code, message = cube.verify_physical()
            if code != 0:
                errors.append(f"{case['case_id']}: invalid state: {message}")
                continue

            result = oracle.solve(cube)
            solution = list(result.solution_moves)
            runtimes.append(float(result.runtime_seconds))

            # Independent re-verification: replay the moves on the original state.
            independent = verify_solution(cube, solution)
            within_bound = result.solution_length is not None and result.solution_length <= GODS_NUMBER_HTM
            is_exact = result.status == "exact"

            row = {
                "case_id": case["case_id"],
                "kind": case["kind"],
                "scramble_depth": case["scramble_depth"],
                "scramble": case.get("scramble"),
                "state": cube.to_facelets(),
                "status": result.status,
                "optimal_length": result.solution_length,
                "solution": " ".join(solution),
                "runtime_seconds": round(result.runtime_seconds, 4),
                "expanded_nodes": result.expanded_nodes,
                "within_gods_number_bound": bool(within_bound),
                "oracle_verified": bool(result.is_verified),
                "independently_verified": bool(independent.ok),
                "notes": result.notes,
            }
            rows.append(row)

            depth_text = "--" if case["scramble_depth"] is None else str(case["scramble_depth"])
            length_text = "--" if result.solution_length is None else str(result.solution_length)
            print(f"{case['case_id']:24s} {result.status:9s} {depth_text:>6s} {length_text:>8s} "
                  f"{('yes' if within_bound else 'no'):>5s} {result.runtime_seconds:>10.3f}  "
                  f"{'OK' if independent.ok else 'FAIL'}")

            # An "exact" claim must independently verify and respect the depth bound.
            if is_exact:
                if not independent.ok:
                    errors.append(f"{case['case_id']}: exact result failed independent verification: {independent.message}")
                if not within_bound:
                    errors.append(f"{case['case_id']}: exact length {result.solution_length} exceeds God's Number {GODS_NUMBER_HTM}")
                if not result.is_verified:
                    errors.append(f"{case['case_id']}: oracle did not mark the exact result verified")
    finally:
        oracle.close()

    print("-" * 100)
    for row in rows:
        if row["solution"]:
            print(f"  {row['case_id']}: {row['solution']}")

    exact_rows = [r for r in rows if r["status"] == "exact"]
    payload = {
        "schema_version": 1,
        "profile": args.profile,
        "seed": args.seed,
        "api_class": "FastOptimalOracle",
        "solver": solver,
        "metric": "HTM / face-turn metric",
        "depth_bound": GODS_NUMBER_HTM,
        "table_path": str(table_path.relative_to(args.root)),
        "table_size_bytes": table_path.stat().st_size,
        "threads": args.threads,
        "timeout_seconds": args.timeout,
        "rows": rows,
        "row_count": len(rows),
        "exact_count": len(exact_rows),
        "all_exact_independently_verified": all(
            r["independently_verified"] and r["within_gods_number_bound"] for r in exact_rows
        ),
        "max_runtime_seconds": round(max(runtimes, default=0.0), 4),
        "scope_note": "per-instance optimal demonstration over a chosen corpus; not an exhaustive proof over all states",
        "errors": errors,
        "passed": not errors,
    }
    output = args.root / "results" / "processed" / f"demo_3x3_optimal_solution_seed_{args.seed}_{args.profile}.json"
    write_json(output, payload)
    print("-" * 100)
    print(json.dumps({
        "output": str(output),
        "exact": payload["exact_count"],
        "rows": payload["row_count"],
        "all_exact_independently_verified": payload["all_exact_independently_verified"],
        "max_runtime_seconds": payload["max_runtime_seconds"],
        "passed": payload["passed"],
    }, indent=2))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

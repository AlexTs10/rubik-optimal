#!/usr/bin/env python
"""Generate evidence for the Nissy 2.x direct-state optimal bridge."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rubik_optimal.cube import CubeState
from rubik_optimal.results import write_json
from rubik_optimal.solvers.nissy_external import solve_nissy_optimal


def _tex(value: object) -> str:
    return str(value).replace("\\", "\\textbackslash{}").replace("_", "\\_")


def _load_known_distance_case(root: Path, seed: int, profile: str, case_id: str) -> dict[str, object]:
    path = root / "results" / "processed" / (
        f"nissy_benchmark_certificates_seed_{seed}_{profile}_distances16_20.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    for row in payload.get("rows", []):
        if row.get("case_id") == case_id:
            return row
    raise RuntimeError(f"known-distance certificate case not found: {case_id}")


def _write_table(root: Path, payload: dict[str, object], suffix: str) -> Path:
    table_path = root / "thesis" / "tables" / f"nissy2_state_bridge_probe{suffix}.tex"
    table_path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for row in payload["rows"]:
        rows.append(
            f"{_tex(row['case_id'])} & {_tex(row['expected_distance'])} & "
            f"{_tex(row['status'])} & {_tex(row['solution_length'])} & "
            f"{_tex(row['runtime_seconds'])} \\\\"
        )
    table_path.write_text(
        "{\\small\n"
        "\\begin{tabular}{lrrrr}\n"
        "\\hline\n"
        "Case & Expected & Status & Length & Seconds \\\\\n"
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
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--artifact-suffix", default="lowload")
    parser.add_argument("--include-hard-offset2", action="store_true")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()

    cases: list[dict[str, object]] = [
        {
            "case_id": "direct_state_ru",
            "expected_distance": 2,
            "cube": CubeState.from_sequence("R U"),
            "source": "in-repo deterministic cubie state",
        },
        {
            "case_id": "direct_state_ruf2",
            "expected_distance": 3,
            "cube": CubeState.from_sequence("R U F2"),
            "source": "in-repo deterministic cubie state",
        },
    ]
    if args.include_hard_offset2:
        hard = _load_known_distance_case(
            args.root,
            seed=args.seed,
            profile=args.profile,
            case_id="nissy_benchmark_distance_20_2",
        )
        cases.append(
            {
                "case_id": hard["case_id"],
                "expected_distance": hard["expected_distance"],
                "cube": CubeState.from_facelets(str(hard["state"])),
                "source": hard["source_label"],
            }
        )

    rows = []
    for case in cases:
        cube = case["cube"]
        assert isinstance(cube, CubeState)
        result = solve_nissy_optimal(
            cube,
            source_sequence=None,
            timeout_seconds=args.timeout,
            threads=args.threads,
            root=args.root,
        )
        rows.append(
            {
                "case_id": case["case_id"],
                "source": case["source"],
                "expected_distance": case["expected_distance"],
                "state": cube.to_facelets(),
                "solver_name": result.solver_name,
                "status": result.status,
                "verified": result.is_verified,
                "solution": " ".join(result.solution_moves),
                "solution_length": result.solution_length,
                "runtime_seconds": round(result.runtime_seconds, 6),
                "notes": result.notes,
                "used_direct_state_bridge": result.solver_name == "nissy2_state_optimal_external"
                and "input_mode=cube_state" in result.notes,
            }
        )

    suffix = f"_{args.artifact_suffix}" if args.artifact_suffix else ""
    payload = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "profile": args.profile,
        "seed": args.seed,
        "timeout_seconds": args.timeout,
        "threads": args.threads,
        "case_count": len(rows),
        "rows": rows,
        "all_used_direct_state_bridge": all(row["used_direct_state_bridge"] for row in rows),
        "all_exact": all(row["status"] == "exact" for row in rows),
        "all_verified": all(row["verified"] is True for row in rows),
        "max_runtime_seconds": max((float(row["runtime_seconds"]) for row in rows), default=0.0),
        "fast_runtime_proven_for_every_possible_state": False,
        "notes": (
            "Direct cubie-state evidence for the Nissy 2.x public optimal backend. "
            "This proves direct arbitrary-state input plumbing for these rows; it is not "
            "a worst-case runtime proof for every possible 3x3 state."
        ),
    }
    output_path = args.root / "results" / "processed" / (
        f"nissy2_state_bridge_probe_seed_{args.seed}_{args.profile}{suffix}.json"
    )
    write_json(output_path, payload)
    table_path = _write_table(args.root, payload, suffix)
    print(f"wrote {output_path}")
    print(f"wrote {table_path}")
    print(json.dumps({k: payload[k] for k in ("all_exact", "all_verified", "max_runtime_seconds")}))
    return 0 if payload["all_used_direct_state_bridge"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

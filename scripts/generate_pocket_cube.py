#!/usr/bin/env python
"""Generate Pocket Cube optimal-distance case-study artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rubik_optimal.pocket.cube import POCKET_STATE_COUNT, PocketState
from rubik_optimal.pocket.optimal import compute_pocket_distribution
from rubik_optimal.results import write_json
from rubik_optimal.solvers.pocket_cube import solve_pocket_cube_optimal


def _tex(value: object) -> str:
    return str(value).replace("_", "\\_")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=["quick", "thesis", "stress"], default="quick")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()

    max_depth = 4 if args.profile == "quick" else None
    distribution = compute_pocket_distribution(max_depth=max_depth)
    representative_sequences = [
        ["R"],
        ["R", "U"],
        ["R", "U", "F"],
        ["R", "U", "R'", "F2"],
        ["F", "R", "U", "R'", "U'", "F'"],
    ]
    representatives = []
    for index, sequence in enumerate(representative_sequences, start=1):
        pocket_sequence = sequence
        state = PocketState.from_sequence(pocket_sequence)
        result = solve_pocket_cube_optimal(state)
        representatives.append(
            {
                "case_id": f"pocket_rep_{index}",
                "input_sequence": " ".join(pocket_sequence),
                "state_coord": state.coord(),
                "solution": " ".join(result.solution_moves),
                "solution_length": result.solution_length,
                "status": result.status,
                "verified": result.is_verified,
                "expanded_nodes": result.expanded_nodes,
                "generated_nodes": result.generated_nodes,
            }
        )

    payload = {
        "schema_version": 1,
        "profile": args.profile,
        "seed": args.seed,
        "state_space": "fixed DBL reference corner, HTM moves U/R/F",
        "expected_state_count": POCKET_STATE_COUNT,
        "distribution": distribution.__dict__,
        "representative_solutions": representatives,
    }

    raw_path = args.root / "results" / "raw" / f"pocket_cube_distribution_seed_{args.seed}_{args.profile}.json"
    processed_path = args.root / "results" / "processed" / f"pocket_cube_summary_seed_{args.seed}_{args.profile}.json"
    write_json(raw_path, payload)
    write_json(processed_path, payload)

    tables = args.root / "thesis" / "tables"
    tables.mkdir(parents=True, exist_ok=True)
    rows = [
        f"{distance} & {count} \\\\"
        for distance, count in payload["distribution"]["distribution"].items()
    ]
    distribution_tex = (
        "\\begin{tabular}{rr}\n"
        "\\hline\n"
        "Distance & States \\\\\n"
        "\\hline\n"
        + "\n".join(rows)
        + "\n\\hline\n\\end{tabular}\n"
    )
    (tables / f"pocket_cube_distribution_{args.profile}.tex").write_text(distribution_tex, encoding="utf-8")
    if args.profile == "thesis":
        (tables / "pocket_cube_distribution.tex").write_text(distribution_tex, encoding="utf-8")

    rep_rows = [
        f"{_tex(row['case_id'])} & {row['solution_length']} & {_tex(row['solution'])} & {_tex(row['status'])} \\\\"
        for row in representatives
    ]
    representatives_tex = (
        "\\begin{tabular}{p{0.2\\textwidth}rp{0.34\\textwidth}p{0.16\\textwidth}}\n"
        "\\hline\n"
        "Case & Length & Solution & Status \\\\\n"
        "\\hline\n"
        + "\n".join(rep_rows)
        + "\n\\hline\n\\end{tabular}\n"
    )
    (tables / f"pocket_cube_representatives_{args.profile}.tex").write_text(
        representatives_tex,
        encoding="utf-8",
    )
    if args.profile == "thesis":
        (tables / "pocket_cube_representatives.tex").write_text(representatives_tex, encoding="utf-8")

    print(json.dumps({"raw": str(raw_path), "processed": str(processed_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

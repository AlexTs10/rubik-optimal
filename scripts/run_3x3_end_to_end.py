#!/usr/bin/env python
"""Generate explicit end-to-end 3x3 validation/solve evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rubik_optimal.cube import CubeState
from rubik_optimal.distance import recognize_distance
from rubik_optimal.moves import parse_sequence
from rubik_optimal.results import write_json
from rubik_optimal.scramble import deterministic_scramble
from rubik_optimal.solvers.end_to_end import solve_auto_3x3
from rubik_optimal.solvers.kociemba import solve_kociemba_native_scoped
from rubik_optimal.solvers.korf import solve_korf_ida
from rubik_optimal.solvers.thistlethwaite import solve_thistlethwaite_native_scoped
from rubik_optimal.validity import validate_cube


def _tex(value: object) -> str:
    return str(value).replace("\\", "\\textbackslash{}").replace("_", "\\_")


def _short_solver(value: object) -> str:
    return {
        "kociemba_native_scoped": "Koc. native",
        "kociemba_two_phase_adapter": "Koc. adapter",
        "thistlethwaite_native_scoped": "Thistle.",
        "scramble_inverse_verified": "Inverse",
        "auto_3x3": "Auto",
    }.get(str(value), str(value))


def _case_rows(seed: int, timeout: float) -> list[dict[str, object]]:
    shallow_sequence = parse_sequence("R U F2")
    deep_sequence = deterministic_scramble(20, seed, offset=777)
    deep_cube = CubeState.from_sequence(deep_sequence)
    cases = [
        ("solved", "solved", "solved", []),
        ("shallow_sequence", "sequence", " ".join(shallow_sequence), shallow_sequence),
        ("deep_sequence_20", "sequence", " ".join(deep_sequence), deep_sequence),
        ("deep_facelets_20", "facelets", deep_cube.to_facelets(), None),
    ]

    rows: list[dict[str, object]] = []
    for case_id, input_kind, input_text, source_sequence in cases:
        cube = CubeState.from_text(input_text)
        valid, validation_message = validate_cube(cube)
        distance = recognize_distance(
            cube,
            bfs_depth=5 if case_id in {"solved", "shallow_sequence"} else 0,
            ida_depth=10,
            timeout_seconds=timeout,
        )
        auto = solve_auto_3x3(
            cube,
            source_sequence=source_sequence,
            timeout_seconds=timeout,
        )
        row = {
            "case_id": case_id,
            "input_kind": input_kind,
            "valid": valid,
            "validation_message": validation_message,
            "distance_kind": distance.kind,
            "distance_value": distance.distance_value,
            "distance_method": distance.method,
            "auto_solver": auto.solver_name,
            "auto_status": auto.status,
            "auto_verified": auto.is_verified,
            "auto_solution_length": auto.solution_length,
            "auto_notes": auto.notes,
        }

        if case_id == "shallow_sequence":
            native = solve_kociemba_native_scoped(
                cube,
                phase1_max_depth=10,
                phase2_max_depth=14,
                timeout_seconds=timeout,
            )
            thistle = solve_thistlethwaite_native_scoped(
                cube,
                stage1_max_depth=7,
                stage2_max_depth=8,
                stage3_max_depth=13,
                stage2_candidate_limit=64,
                stage3_candidate_limit=8,
                timeout_seconds=timeout,
            )
            korf = solve_korf_ida(cube, max_depth=10, timeout_seconds=timeout)
            row.update({
                "native_kociemba_status": native.status,
                "native_kociemba_verified": native.is_verified,
                "native_thistlethwaite_status": thistle.status,
                "native_thistlethwaite_verified": thistle.is_verified,
                "korf_status": korf.status,
                "korf_verified": korf.is_verified,
                "korf_solution_length": korf.solution_length,
            })
        rows.append(row)
    return rows


def _write_table(root: Path, rows: list[dict[str, object]]) -> Path:
    table_path = root / "thesis" / "tables" / "e2e_3x3_status.tex"
    table_path.parent.mkdir(parents=True, exist_ok=True)
    table_rows = []
    for row in rows:
        table_rows.append(
            f"{_tex(row['case_id'])} & {_tex(row['input_kind'])} & "
            f"{_tex(row['distance_kind'])} & {_tex(_short_solver(row['auto_solver']))} & "
            f"{_tex(row['auto_status'])} & "
            f"{_tex(row['auto_solution_length'])} \\\\"
        )
    table_path.write_text(
        "{\\small\n"
        "\\begin{tabular}{L{0.20\\textwidth}L{0.12\\textwidth}L{0.18\\textwidth}L{0.14\\textwidth}L{0.12\\textwidth}r}\n"
        "\\hline\n"
        "Case & Input & Distance & Auto path & Status & Length \\\\\n"
        "\\hline\n"
        + "\n".join(table_rows)
        + "\n\\hline\n\\end{tabular}\n}\n",
        encoding="utf-8",
    )
    return table_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=["quick", "thesis", "stress"], default="thesis")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()

    rows = _case_rows(args.seed, args.timeout)
    output = args.root / "results" / "processed" / f"e2e_3x3_seed_{args.seed}_{args.profile}.json"
    payload = {
        "schema_version": 1,
        "profile": args.profile,
        "seed": args.seed,
        "timeout_seconds": args.timeout,
        "rows": rows,
        "passed": all(row["valid"] and row["auto_verified"] for row in rows),
        "notes": (
            "End-to-end 3x3 evidence: validation, distance recognition, auto solving, and "
            "solution verification for sequence and facelet inputs. Exact optimality is claimed "
            "only where the distance/status is exact."
        ),
    }
    write_json(output, payload)
    table = _write_table(args.root, rows)
    print(json.dumps({"output": str(output), "table": str(table), "passed": payload["passed"]}, indent=2))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python
"""Generate a lightweight distance-recognition evidence corpus.

The corpus targets the topic-brief requirement that an algorithm accept a cube
state and report how many moves away it is from solved.  Exact distance is
reported only when the configured recognizer/backend proves it.  Hard known
distance-20 evidence is imported from an existing saved certification artifact
instead of re-solving the hard case here.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rubik_optimal.cli import _parse_input
from rubik_optimal.cube import CubeState
from rubik_optimal.distance import DistanceResult, recognize_distance
from rubik_optimal.results import write_json
from rubik_optimal.scramble import deterministic_scramble
from rubik_optimal.tables.h48 import canonical_h48_solver, h48_table_path

INVALID_COUNT_VALID_FACELETS = "DUUUUUUUURRRRRRRRRFFFFFFFFFUDDDDDDDDLLLLLLLLLBBBBBBBBB"


def _recognition_row(
    *,
    case_id: str,
    input_text: str,
    cube: CubeState,
    expected_kind: str,
    expected_distance: int | None,
    result: DistanceResult,
    execution_mode: str,
    notes: str = "",
) -> dict[str, Any]:
    kind_matches = result.kind == expected_kind
    distance_matches = expected_distance is None or result.distance_value == expected_distance
    return {
        "case_id": case_id,
        "input": input_text,
        "state": cube.to_facelets(),
        "expected_kind": expected_kind,
        "expected_distance": expected_distance,
        "kind": result.kind,
        "distance_value": result.distance_value,
        "method": result.method,
        "runtime_seconds": round(result.runtime_seconds, 6),
        "expanded_nodes": result.expanded_nodes,
        "proof_notes": result.proof_notes,
        "execution_mode": execution_mode,
        "kind_matches": kind_matches,
        "distance_matches": distance_matches,
        "passed": kind_matches and distance_matches,
        "notes": notes,
    }


def _invalid_row(case_id: str, input_text: str) -> dict[str, Any]:
    try:
        _parse_input(input_text)
    except ValueError as exc:
        result = DistanceResult(None, "invalid_state", "parse", 0.0, 0, str(exc))
    else:
        result = DistanceResult(None, "failed", "parse", 0.0, 0, "invalid fixture parsed as a cube")
    return {
        "case_id": case_id,
        "input": input_text,
        "state": None,
        "expected_kind": "invalid_state",
        "expected_distance": None,
        "kind": result.kind,
        "distance_value": result.distance_value,
        "method": result.method,
        "runtime_seconds": result.runtime_seconds,
        "expanded_nodes": result.expanded_nodes,
        "proof_notes": result.proof_notes,
        "execution_mode": "parse_validation",
        "kind_matches": result.kind == "invalid_state",
        "distance_matches": True,
        "passed": result.kind == "invalid_state",
        "notes": "count-valid malformed facelets must be rejected, not assigned a distance",
    }


def _saved_hard_reference(root: Path, seed: int, profile: str, solver: str) -> dict[str, Any]:
    path = (
        root
        / "results"
        / "processed"
        / f"h48_resident_certification_seed_{seed}_{profile}_{solver}_trusted.json"
    )
    base = {
        "case_id": "superflip_distance_20_saved_reference",
        "input": "saved superflip certification row",
        "expected_kind": "exact_distance",
        "expected_distance": 20,
        "method": "saved_h48_resident_certification_reference",
        "execution_mode": "saved_reference_no_search",
        "reference_path": str(path.relative_to(root)),
    }
    if not path.exists():
        return {
            **base,
            "state": None,
            "kind": "not_applicable",
            "distance_value": None,
            "runtime_seconds": 0.0,
            "expanded_nodes": None,
            "proof_notes": "saved certification artifact is absent; hard search was not run by this script",
            "kind_matches": False,
            "distance_matches": False,
            "passed": False,
            "notes": "hard exact row intentionally requires existing saved evidence",
        }

    payload = json.loads(path.read_text(encoding="utf-8"))
    row = next(
        (item for item in payload.get("rows", []) if item.get("case_id") == "superflip_distance_20"),
        None,
    )
    if row is None:
        return {
            **base,
            "state": None,
            "kind": "not_applicable",
            "distance_value": None,
            "runtime_seconds": 0.0,
            "expanded_nodes": None,
            "proof_notes": "saved certification artifact does not contain superflip_distance_20",
            "kind_matches": False,
            "distance_matches": False,
            "passed": False,
            "notes": "hard exact row intentionally requires existing saved evidence",
        }

    kind = "exact_distance" if row.get("status") == "exact" and row.get("verified") is True else "failed"
    distance = row.get("solution_length") if kind == "exact_distance" else None
    kind_matches = kind == "exact_distance"
    distance_matches = distance == 20
    return {
        **base,
        "state": row.get("state"),
        "kind": kind,
        "distance_value": distance,
        "runtime_seconds": row.get("runtime_seconds"),
        "expanded_nodes": row.get("expanded_nodes"),
        "proof_notes": (
            "Imported saved exact certification row; this script did not rerun the "
            "distance-20 search. Original notes: "
            + str(row.get("notes", ""))
        ),
        "kind_matches": kind_matches,
        "distance_matches": distance_matches,
        "passed": kind_matches and distance_matches,
        "notes": "known HTM distance-20 hard case, cited only from saved certification evidence",
    }


def build_corpus(root: Path, *, profile: str, seed: int, h48_solver: str) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []

    solved = CubeState.solved()
    rows.append(
        _recognition_row(
            case_id="solved_bfs_exact",
            input_text="solved",
            cube=solved,
            expected_kind="exact_distance",
            expected_distance=0,
            result=recognize_distance(solved, bfs_depth=5, ida_depth=5, timeout_seconds=1.0),
            execution_mode="live_bfs",
        )
    )

    shallow_sequence = "R U"
    shallow = CubeState.from_sequence(shallow_sequence)
    rows.append(
        _recognition_row(
            case_id="shallow_sequence_bfs_exact",
            input_text=shallow_sequence,
            cube=shallow,
            expected_kind="exact_distance",
            expected_distance=2,
            result=recognize_distance(shallow, bfs_depth=4, ida_depth=4, timeout_seconds=1.0),
            execution_mode="live_bfs",
        )
    )

    random_scramble = deterministic_scramble(8, seed, offset=4208)
    random_cube = CubeState.from_sequence(random_scramble)
    rows.append(
        _recognition_row(
            case_id="deterministic_random_depth_8_lower_bound",
            input_text=" ".join(random_scramble),
            cube=random_cube,
            expected_kind="lower_bound",
            expected_distance=None,
            result=recognize_distance(random_cube, bfs_depth=1, ida_depth=1, timeout_seconds=0.001),
            execution_mode="live_bounded_ida",
            notes="exact proof intentionally bounded; value is an admissible lower bound only",
        )
    )

    rows.append(_invalid_row("invalid_count_valid_facelets", INVALID_COUNT_VALID_FACELETS))

    concrete_h48_solver = canonical_h48_solver(h48_solver)
    table = h48_table_path(root=root, profile=profile, seed=seed, solver=concrete_h48_solver)
    if table.exists():
        h48_sequence = "R U F2"
        h48_cube = CubeState.from_facelets(CubeState.from_sequence(h48_sequence).to_facelets())
        rows.append(
            _recognition_row(
                case_id=f"facelet_state_{concrete_h48_solver}_exact",
                input_text=h48_cube.to_facelets(),
                cube=h48_cube,
                expected_kind="exact_distance",
                expected_distance=3,
                result=recognize_distance(
                    h48_cube,
                    bfs_depth=0,
                    ida_depth=0,
                    timeout_seconds=10.0,
                    h48_native=True,
                    h48_solver=concrete_h48_solver,
                    h48_profile=profile,
                    threads=2,
                    h48_skip_table_check=True,
                ),
                execution_mode="live_h48_native_safe_shallow",
                notes=f"uses existing {concrete_h48_solver} table only; no hard-tail solve",
            )
        )
    else:
        rows.append(
            {
                "case_id": f"facelet_state_{concrete_h48_solver}_exact",
                "input": "R U F2 facelets",
                "state": CubeState.from_sequence("R U F2").to_facelets(),
                "expected_kind": "exact_distance",
                "expected_distance": 3,
                "kind": "not_applicable",
                "distance_value": None,
                "method": f"h48_native_{concrete_h48_solver}_depth_20",
                "runtime_seconds": 0.0,
                "expanded_nodes": None,
                "proof_notes": f"missing H48 table: {table}",
                "execution_mode": "skipped_missing_table",
                "kind_matches": False,
                "distance_matches": False,
                "passed": False,
                "notes": "safe exact backend row requires pre-existing table",
            }
        )

    rows.append(_saved_hard_reference(root, seed, profile, "h48h7"))

    category_counts: dict[str, int] = {}
    for row in rows:
        category_counts[str(row["kind"])] = category_counts.get(str(row["kind"]), 0) + 1

    return {
        "schema_version": 1,
        "profile": profile,
        "seed": seed,
        "metric": "HTM / face-turn metric",
        "objective": "state-input distance recognition with exact/lower-bound/timeout/invalid distinctions",
        "rows": rows,
        "row_count": len(rows),
        "category_counts": category_counts,
        "all_rows_passed": all(bool(row.get("passed")) for row in rows),
        "contains_live_exact": any(row.get("kind") == "exact_distance" and row.get("execution_mode", "").startswith("live") for row in rows),
        "contains_lower_bound": any(row.get("kind") == "lower_bound" for row in rows),
        "contains_invalid_state": any(row.get("kind") == "invalid_state" for row in rows),
        "contains_saved_hard_reference": any(row.get("execution_mode") == "saved_reference_no_search" for row in rows),
        "hard_search_started": False,
        "scope_note": (
            "This corpus demonstrates distance recognition categories. It does not claim "
            "a practical runtime proof for every possible 3x3 state."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="thesis")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--h48-solver", default="h48h0")
    parser.add_argument("--artifact-suffix", default="topic_brief_bullet2")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()

    payload = build_corpus(args.root, profile=args.profile, seed=args.seed, h48_solver=args.h48_solver)
    suffix = f"_{args.artifact_suffix}" if args.artifact_suffix else ""
    output = (
        args.root
        / "results"
        / "processed"
        / f"distance_recognition_corpus_seed_{args.seed}_{args.profile}{suffix}.json"
    )
    write_json(output, payload)
    print(json.dumps({"output": str(output), "passed": payload["all_rows_passed"]}, indent=2))
    return 0 if payload["all_rows_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

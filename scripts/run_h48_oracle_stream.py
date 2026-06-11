#!/usr/bin/env python
"""Generate evidence for the public streaming H48 oracle CLI."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rubik_optimal.cube import CubeState
from rubik_optimal.results import write_json
from rubik_optimal.tables.h48 import ORACLE_H48_SOLVER, canonical_h48_solver, h48_table_path


def _cases() -> list[dict[str, str]]:
    return [
        {"case_id": "solved", "input_kind": "solved", "input": "solved"},
        {"case_id": "sequence_shallow", "input_kind": "sequence", "input": "R U F2"},
        {
            "case_id": "facelets_shallow",
            "input_kind": "facelets",
            "input": CubeState.from_sequence("R U F2").to_facelets(),
        },
        {"case_id": "sequence_mixed", "input_kind": "sequence", "input": "R U R' U' F2"},
    ]


def _write_table(root: Path, payload: dict[str, object], suffix: str) -> Path:
    filename = f"h48_oracle_stream{suffix}.tex" if suffix else "h48_oracle_stream.tex"
    table_path = root / "thesis" / "tables" / filename
    table_path.parent.mkdir(parents=True, exist_ok=True)
    body = [
        "{\\small\n",
        "\\begin{tabular}{llrr}\n",
        "\\hline\n",
        "Case & Input & Distance & Seconds \\\\\n",
        "\\hline\n",
    ]
    for row in payload["rows"]:
        case_id = str(row["case_id"]).replace("_", "\\_")
        input_kind = str(row["input_kind"]).replace("_", "\\_")
        distance = "--" if row["distance"] is None else str(row["distance"])
        seconds = f"{float(row['runtime_seconds']):.6f}"
        body.append(f"{case_id} & {input_kind} & {distance} & {seconds} \\\\\n")
    body.extend(["\\hline\n", "\\end{tabular}\n", "}\n"])
    table_path.write_text("".join(body), encoding="utf-8")
    return table_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default="thesis")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--solver", default=ORACLE_H48_SOLVER)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--trusted-table", action="store_true")
    parser.add_argument("--preload-table", action="store_true")
    parser.add_argument("--artifact-suffix", default=None)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()

    root = args.root
    solver = canonical_h48_solver(args.solver)
    artifact_suffix = args.artifact_suffix
    if artifact_suffix is None:
        artifact_suffix = "" if solver == ORACLE_H48_SOLVER else solver
    suffix = f"_{artifact_suffix}" if artifact_suffix else ""
    table_path = h48_table_path(root=root, profile=args.profile, seed=args.seed, solver=solver)
    if not table_path.exists():
        raise SystemExit(f"missing H48 table: {table_path}")

    cases = _cases()
    command = [
        sys.executable,
        "-m",
        "rubik_optimal.cli",
        "oracle",
        "--stream",
        "--h48-solver",
        solver,
        "--h48-profile",
        args.profile,
        "--timeout",
        str(args.timeout),
        "--threads",
        str(args.threads),
    ]
    if args.trusted_table:
        command.append("--h48-trusted-table")
    if args.preload_table:
        command.append("--h48-preload-table")

    begin = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=root,
        input="\n".join(row["input"] for row in cases) + "\n",
        text=True,
        capture_output=True,
        check=False,
        timeout=args.timeout + 30.0,
    )
    wrapper_wall_seconds = time.perf_counter() - begin
    rows = []
    for line in completed.stdout.splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"oracle stream returned non-JSON line: {line!r}; stderr={completed.stderr!r}") from exc

    merged_rows = []
    for case, row in zip(cases, rows):
        merged = dict(row)
        merged["case_id"] = case["case_id"]
        merged_rows.append(merged)

    payload = {
        "schema_version": 1,
        "profile": args.profile,
        "seed": args.seed,
        "solver": solver,
        "command": " ".join(command),
        "return_code": completed.returncode,
        "threads": args.threads,
        "trusted_table": args.trusted_table,
        "preload_table": args.preload_table,
        "timeout_seconds": args.timeout,
        "table_path": str(table_path.relative_to(root)),
        "table_size_bytes": table_path.stat().st_size,
        "wrapper_wall_seconds": round(wrapper_wall_seconds, 6),
        "input_count": len(cases),
        "row_count": len(rows),
        "all_exact": bool(rows) and all(row.get("status") == "exact" for row in rows),
        "all_verified": bool(rows) and all(row.get("verified") is True for row in rows),
        "rows": merged_rows,
    }
    payload["passed"] = (
        completed.returncode == 0
        and payload["row_count"] == payload["input_count"]
        and payload["all_exact"] is True
        and payload["all_verified"] is True
        and all(
            row.get("distance") == 0
            or "resident in-repo native H48 backend" in str(row.get("notes", ""))
            for row in rows
        )
    )

    output = root / "results" / "processed" / f"h48_oracle_stream_seed_{args.seed}_{args.profile}{suffix}.json"
    write_json(output, payload)
    table = _write_table(root, payload, suffix)
    print(json.dumps({"output": str(output), "table": str(table), "passed": payload["passed"]}, indent=2))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

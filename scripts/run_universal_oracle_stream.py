#!/usr/bin/env python
"""Generate evidence for the public streaming UniversalOptimalOracle CLI."""

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

from rubik_optimal.cube import CubeState  # noqa: E402
from rubik_optimal.results import write_json  # noqa: E402
from rubik_optimal.tables.h48 import ORACLE_H48_SOLVER, canonical_h48_solver, h48_table_path  # noqa: E402


def _cases() -> list[dict[str, str]]:
    return [
        {"case_id": "stream_solved", "input_kind": "solved", "input": "solved"},
        {"case_id": "stream_sequence_depth_3", "input_kind": "sequence", "input": "R U F2"},
        {
            "case_id": "stream_facelets_depth_3",
            "input_kind": "facelets",
            "input": CubeState.from_sequence("R U F2").to_facelets(),
        },
    ]


def _tex(value: object) -> str:
    if value is None:
        return "--"
    return str(value).replace("\\", "\\textbackslash{}").replace("_", "\\_")


def _write_table(root: Path, rows: list[dict[str, object]], suffix: str) -> Path:
    filename = f"universal_oracle_stream{suffix}.tex" if suffix else "universal_oracle_stream.tex"
    table_path = root / "thesis" / "tables" / filename
    table_path.parent.mkdir(parents=True, exist_ok=True)
    body = [
        "{\\small\n",
        "\\begin{tabular}{lllr}\n",
        "\\hline\n",
        "Case & Input & Selected backend & Seconds \\\\\n",
        "\\hline\n",
    ]
    for row in rows:
        body.append(
            f"{_tex(row['case_id'])} & {_tex(row['input_kind'])} & "
            f"{_tex(row['selected_backend'])} & {float(row['runtime_seconds']):.6f} \\\\\n"
        )
    body.extend(["\\hline\n", "\\end{tabular}\n", "}\n"])
    table_path.write_text("".join(body), encoding="utf-8")
    return table_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=["quick", "thesis", "stress"], default="thesis")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--solver", default=ORACLE_H48_SOLVER)
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--trusted-table", action="store_true")
    parser.add_argument("--preload-table", action="store_true")
    parser.add_argument("--no-certificate-cache", action="store_true")
    parser.add_argument("--no-upper-lower-certificate", action="store_true")
    parser.add_argument("--artifact-suffix", default="lowload")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()

    root = args.root
    solver = canonical_h48_solver(args.solver)
    suffix = f"_{args.artifact_suffix}" if args.artifact_suffix else ""
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
        "--universal",
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
    if args.no_certificate_cache:
        command.append("--no-universal-certificate-cache")
    if args.no_upper_lower_certificate:
        command.append("--no-universal-upper-lower-certificate")

    begin = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=root,
        input="\n".join(row["input"] for row in cases) + "\n",
        text=True,
        capture_output=True,
        check=False,
        timeout=args.timeout + 45.0,
    )
    wrapper_wall_seconds = time.perf_counter() - begin

    cli_rows: list[dict[str, object]] = []
    for line in completed.stdout.splitlines():
        if not line.strip():
            continue
        try:
            cli_rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise SystemExit(
                f"universal oracle stream returned non-JSON line: {line!r}; stderr={completed.stderr!r}"
            ) from exc

    rows: list[dict[str, object]] = []
    errors: list[str] = []
    for case, row in zip(cases, cli_rows, strict=False):
        merged = dict(row)
        merged["case_id"] = case["case_id"]
        merged["expected_input_kind"] = case["input_kind"]
        rows.append(merged)
        if merged.get("status") != "exact" or merged.get("verified") is not True:
            errors.append(f"{case['case_id']}: expected exact verified, got {merged.get('status')}")
        if merged.get("input_kind") != case["input_kind"]:
            errors.append(
                f"{case['case_id']}: expected input kind {case['input_kind']}, got {merged.get('input_kind')}"
            )
        if merged.get("selected_backend") not in {
            "solved_fast_path",
            "exact-certificate-cache",
            "upper-lower-certificate",
            "nissy-symmetry-batch",
            "resident-h48-symmetry-batch",
            "resident-race",
        }:
            errors.append(f"{case['case_id']}: unexpected universal stream path {merged.get('selected_backend')}")

    if completed.returncode != 0:
        errors.append(f"CLI exited {completed.returncode}: {completed.stderr.strip()}")
    if len(cli_rows) != len(cases):
        errors.append(f"expected {len(cases)} stream rows, got {len(cli_rows)}")
    live_backend_rows = sum(
        1
        for row in rows
        if row.get("selected_backend")
        not in {"solved_fast_path", "exact-certificate-cache", "upper-lower-certificate"}
    )
    if args.no_certificate_cache and args.no_upper_lower_certificate and live_backend_rows < 1:
        errors.append("live solver shortcuts were disabled but no stream row reached a live backend")

    payload = {
        "schema_version": 1,
        "profile": args.profile,
        "seed": args.seed,
        "solver": solver,
        "api_class": "UniversalOptimalOracle",
        "public_interface": "rubik-optimal oracle --stream --universal",
        "command": " ".join(command),
        "return_code": completed.returncode,
        "threads": args.threads,
        "trusted_table": bool(args.trusted_table),
        "preload_table": bool(args.preload_table),
        "try_certificate_cache": not args.no_certificate_cache,
        "try_upper_lower_certificate": not args.no_upper_lower_certificate,
        "live_solver_shortcuts_disabled": args.no_certificate_cache and args.no_upper_lower_certificate,
        "timeout_seconds": args.timeout,
        "table_path": str(table_path.relative_to(root)),
        "table_size_bytes": table_path.stat().st_size,
        "wrapper_wall_seconds": round(wrapper_wall_seconds, 6),
        "input_count": len(cases),
        "row_count": len(cli_rows),
        "selected_backends": sorted({str(row.get("selected_backend")) for row in rows}),
        "all_exact": bool(rows) and all(row.get("status") == "exact" for row in rows),
        "all_verified": bool(rows) and all(row.get("verified") is True for row in rows),
        "all_universal_stream_cli": bool(rows)
        and all("universal exact oracle" in str(row.get("notes", "")) for row in rows),
        "live_backend_rows": live_backend_rows,
        "max_runtime_seconds": max((float(row.get("runtime_seconds") or 0.0) for row in rows), default=0.0),
        "fast_runtime_proven_for_every_possible_state": False,
        "rows": rows,
        "errors": errors,
        "passed": not errors,
    }

    output = (
        root
        / "results"
        / "processed"
        / f"universal_oracle_stream_seed_{args.seed}_{args.profile}_{solver}{suffix}.json"
    )
    write_json(output, payload)
    table = _write_table(root, rows, f"_{solver}{suffix}")
    print(json.dumps({"output": str(output), "table": str(table), "passed": payload["passed"]}, indent=2))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

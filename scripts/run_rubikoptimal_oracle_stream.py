#!/usr/bin/env python
"""Generate public streaming CLI evidence for resident RubikOptimal solving."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rubik_optimal.cube import CubeState  # noqa: E402
from rubik_optimal.results import write_json  # noqa: E402
from rubik_optimal.solvers.rubikoptimal_external import (  # noqa: E402
    RUBIKOPTIMAL_TABLE_SIZES,
    default_rubikoptimal_table_dir,
    rubikoptimal_table_bytes,
    rubikoptimal_table_inventory,
    rubikoptimal_tables_ready,
)
from rubik_optimal.validity import validate_cube  # noqa: E402


@dataclass(frozen=True)
class RubikOptimalStreamCase:
    case_id: str
    cube: CubeState
    expected_distance: int
    description: str


def build_cases() -> list[RubikOptimalStreamCase]:
    return [
        RubikOptimalStreamCase(
            "stream_facelets_solved",
            CubeState.solved(),
            0,
            "solved state supplied as facelets",
        ),
        RubikOptimalStreamCase(
            "stream_facelets_depth_2",
            CubeState.from_sequence("R U"),
            2,
            "known two-move state supplied as facelets",
        ),
        RubikOptimalStreamCase(
            "stream_facelets_depth_3",
            CubeState.from_sequence("R U F2"),
            3,
            "known three-move state supplied as facelets",
        ),
    ]


def _tex(value: object) -> str:
    if value is None:
        return "--"
    return str(value).replace("\\", "\\textbackslash{}").replace("_", "\\_")


def _write_table(root: Path, rows: list[dict[str, object]], suffix: str) -> Path:
    filename = (
        f"rubikoptimal_oracle_stream{suffix}.tex"
        if suffix
        else "rubikoptimal_oracle_stream.tex"
    )
    table_path = root / "thesis" / "tables" / filename
    table_path.parent.mkdir(parents=True, exist_ok=True)
    body = [
        "{\\small\n",
        "\\begin{tabular}{lrrrr}\n",
        "\\hline\n",
        "Case & Input & Backend & Length & Seconds \\\\\n",
        "\\hline\n",
    ]
    for row in rows:
        body.append(
            f"{_tex(row['case_id'])} & {_tex(row['input_kind'])} & "
            f"{_tex(row['selected_backend'])} & {_tex(row['solution_length'])} & "
            f"{float(row['runtime_seconds']):.6f} \\\\\n"
        )
    body.extend(["\\hline\n", "\\end{tabular}\n", "}\n"])
    table_path.write_text("".join(body), encoding="utf-8")
    return table_path


def _json_rows(stdout: str, stderr: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise SystemExit(
                f"RubikOptimal stream returned non-JSON line: {line!r}; stderr={stderr!r}"
            ) from exc
    return rows


def run_stream(
    *,
    root: Path,
    profile: str,
    seed: int,
    cases: list[RubikOptimalStreamCase],
    timeout_seconds: float,
    executable: Path | None,
    package_path: Path | None,
    table_dir: Path,
    artifact_suffix: str,
) -> tuple[dict[str, object], Path, Path]:
    table_ready = rubikoptimal_tables_ready(table_dir)
    table_bytes = rubikoptimal_table_bytes(table_dir)
    errors: list[str] = []

    input_lines: list[str] = []
    for case in cases:
        valid, message = validate_cube(case.cube)
        if not valid:
            errors.append(f"{case.case_id}: generated invalid state: {message}")
        input_lines.append(case.cube.to_facelets())

    command = [
        sys.executable,
        "-m",
        "rubik_optimal.cli",
        "oracle",
        "--stream",
        "--rubikoptimal",
        "--timeout",
        str(timeout_seconds),
        "--rubikoptimal-table-dir",
        str(table_dir),
    ]
    if executable is not None:
        command.extend(["--rubikoptimal-executable", str(executable)])
    if package_path is not None:
        command.extend(["--rubikoptimal-package-path", str(package_path)])

    begin = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=root,
        input="\n".join(input_lines) + "\n",
        text=True,
        capture_output=True,
        check=False,
        timeout=max(30.0, timeout_seconds * max(1, len(cases)) + 90.0),
    )
    wrapper_wall_seconds = time.perf_counter() - begin
    cli_rows = _json_rows(completed.stdout, completed.stderr)

    rows: list[dict[str, object]] = []
    for case, row in zip(cases, cli_rows, strict=False):
        merged = dict(row)
        merged.update(
            {
                "case_id": case.case_id,
                "description": case.description,
                "state": case.cube.to_facelets(),
                "expected_distance": case.expected_distance,
                "source_sequence_provided_to_solver": False,
                "expected_distance_matches": (
                    merged.get("status") == "exact"
                    and merged.get("solution_length") == case.expected_distance
                ),
                "resident_process_reused": "resident_process_reused=true"
                in str(merged.get("notes", "")),
            }
        )
        rows.append(merged)
        if merged.get("input_kind") != "facelets":
            errors.append(f"{case.case_id}: expected facelet input, got {merged.get('input_kind')}")
        if merged.get("selected_backend") != "rubikoptimal_resident":
            errors.append(
                f"{case.case_id}: expected resident RubikOptimal backend, got "
                f"{merged.get('selected_backend')}"
            )
        if merged.get("backend_solver") != "rubikoptimal_external":
            errors.append(
                f"{case.case_id}: expected rubikoptimal_external backend solver, got "
                f"{merged.get('backend_solver')}"
            )
        if merged.get("status") != "exact" or merged.get("verified") is not True:
            errors.append(f"{case.case_id}: expected exact verified, got {merged.get('status')}")
        if merged["expected_distance_matches"] is not True:
            errors.append(
                f"{case.case_id}: expected distance {case.expected_distance}, got "
                f"{merged.get('solution_length')}"
            )
        if "selected_backend=rubikoptimal_resident" not in str(merged.get("notes", "")):
            errors.append(f"{case.case_id}: missing resident backend note")

    if completed.returncode != 0:
        errors.append(f"CLI exited {completed.returncode}: {completed.stderr.strip()}")
    if len(cli_rows) != len(cases):
        errors.append(f"expected {len(cases)} stream rows, got {len(cli_rows)}")
    if table_ready is not True:
        errors.append(f"RubikOptimal tables are not complete under {table_dir}")
    if table_bytes != sum(RUBIKOPTIMAL_TABLE_SIZES.values()):
        errors.append(
            f"expected RubikOptimal table bytes {sum(RUBIKOPTIMAL_TABLE_SIZES.values())}, "
            f"got {table_bytes}"
        )
    if sum(1 for row in rows if row.get("resident_process_reused") is True) < 1:
        errors.append("expected at least one streamed row to prove resident process reuse")

    suffix = f"_{artifact_suffix}" if artifact_suffix else ""
    runtimes = [float(row.get("runtime_seconds") or 0.0) for row in rows]
    payload: dict[str, object] = {
        "schema_version": 1,
        "profile": profile,
        "seed": seed,
        "backend": "rubikoptimal_resident_stream",
        "public_interface": "rubik-optimal oracle --stream --rubikoptimal",
        "command": " ".join(command),
        "return_code": completed.returncode,
        "timeout_seconds": timeout_seconds,
        "table_dir": str(table_dir.relative_to(root)) if table_dir.is_relative_to(root) else str(table_dir),
        "table_ready": table_ready,
        "table_bytes": table_bytes,
        "expected_table_bytes": sum(RUBIKOPTIMAL_TABLE_SIZES.values()),
        "table_inventory": rubikoptimal_table_inventory(table_dir),
        "wrapper_wall_seconds": round(wrapper_wall_seconds, 6),
        "input_count": len(cases),
        "row_count": len(cli_rows),
        "input_mode": "facelets_only",
        "all_state_input_only": all(row.get("source_sequence_provided_to_solver") is False for row in rows),
        "all_exact": bool(rows) and all(row.get("status") == "exact" for row in rows),
        "all_verified": bool(rows) and all(row.get("verified") is True for row in rows),
        "all_expected_distances_match": bool(rows)
        and all(row.get("expected_distance_matches") is True for row in rows),
        "all_rubikoptimal_resident": bool(rows)
        and all(row.get("selected_backend") == "rubikoptimal_resident" for row in rows),
        "resident_reused_rows": sum(1 for row in rows if row.get("resident_process_reused") is True),
        "selected_backends": sorted({str(row.get("selected_backend")) for row in rows}),
        "max_runtime_seconds": max(runtimes, default=0.0),
        "mean_runtime_seconds": round(statistics.fmean(runtimes), 6) if runtimes else 0.0,
        "rubikoptimal_table_complete": table_ready and table_bytes == sum(RUBIKOPTIMAL_TABLE_SIZES.values()),
        "algorithmic_contract": {
            "state_scope": "physically valid 3x3 facelet states accepted by the local verifier",
            "input_mode": "the public CLI receives facelets only, never the generating scramble",
            "metric": "HTM / face-turn metric",
            "exactness_rule": "a row is exact only when RubikOptimal returns a line and the local verifier accepts it",
            "runtime_claim": "this artifact proves the recorded stream corpus, not exhaustive every-state timing",
        },
        "fast_runtime_proven_for_every_possible_state": False,
        "rows": rows,
        "errors": errors,
        "passed": not errors,
    }

    output = (
        root
        / "results"
        / "processed"
        / f"rubikoptimal_oracle_stream_seed_{seed}_{profile}{suffix}.json"
    )
    write_json(output, payload)
    table = _write_table(root, rows, suffix)
    return payload, output, table


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=["thesis", "stress"], default="thesis")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--rubikoptimal-table-dir", type=Path, default=None)
    parser.add_argument("--rubikoptimal-executable", type=Path, default=None)
    parser.add_argument("--rubikoptimal-package-path", type=Path, default=None)
    parser.add_argument("--artifact-suffix", default="lowload")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()

    table_dir = args.rubikoptimal_table_dir or default_rubikoptimal_table_dir(args.root)
    payload, output, table = run_stream(
        root=args.root,
        profile=args.profile,
        seed=args.seed,
        cases=build_cases(),
        timeout_seconds=args.timeout,
        executable=args.rubikoptimal_executable,
        package_path=args.rubikoptimal_package_path,
        table_dir=table_dir,
        artifact_suffix=args.artifact_suffix,
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "table": str(table),
                "passed": payload["passed"],
                "row_count": payload["row_count"],
                "max_runtime_seconds": payload["max_runtime_seconds"],
            },
            indent=2,
        )
    )
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

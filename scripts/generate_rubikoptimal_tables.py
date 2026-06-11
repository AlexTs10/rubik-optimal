#!/usr/bin/env python
"""Generate or inspect external RubikOptimal pruning tables safely."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rubik_optimal.results import write_json  # noqa: E402
from rubik_optimal.solvers.rubikoptimal_external import (  # noqa: E402
    RUBIKOPTIMAL_TABLE_SIZES,
    default_rubikoptimal_pythonpath,
    default_rubikoptimal_table_dir,
    find_rubikoptimal_executable,
    rubikoptimal_table_bytes,
    rubikoptimal_table_inventory,
    rubikoptimal_tables_ready,
)


def _load_average() -> tuple[float, float, float] | None:
    try:
        return tuple(float(value) for value in os.getloadavg())
    except (AttributeError, OSError):
        return None


def evaluate_rubikoptimal_generation_safety(
    *,
    root: Path,
    table_dir: Path,
    load_fraction_limit: float = 0.5,
    disk_multiplier: float = 2.0,
) -> dict[str, Any]:
    """Return a conservative safety decision for the large RubikOptimal table build."""

    table_dir.mkdir(parents=True, exist_ok=True)
    current_bytes = rubikoptimal_table_bytes(table_dir) or 0
    expected_bytes = sum(RUBIKOPTIMAL_TABLE_SIZES.values())
    remaining_bytes = max(0, expected_bytes - current_bytes)
    disk = shutil.disk_usage(table_dir)
    load_average = _load_average()
    cpu_count = os.cpu_count() or 1

    reasons: list[str] = []
    if load_average and load_average[0] >= max(1.0, cpu_count * load_fraction_limit):
        reasons.append(
            f"current one-minute load average {load_average[0]:.2f} is at least "
            f"{load_fraction_limit:.0%} of logical CPUs"
        )
    if disk.free < remaining_bytes * disk_multiplier:
        reasons.append(
            f"free disk is below {disk_multiplier:.1f}x the remaining RubikOptimal table bytes"
        )

    return {
        "safe_to_start": not reasons,
        "reasons": reasons,
        "expected_total_size_bytes": expected_bytes,
        "current_table_bytes": current_bytes,
        "remaining_table_bytes": remaining_bytes,
        "policy": {
            "load_fraction_limit": load_fraction_limit,
            "disk_multiplier": disk_multiplier,
        },
        "machine": {
            "cpu_count": cpu_count,
            "load_average": load_average,
            "table_dir_free_bytes": disk.free,
        },
        "table_dir": str(table_dir.relative_to(root) if table_dir.is_relative_to(root) else table_dir),
    }


def _cornerprun_code() -> str:
    return (
        "import array as ar\n"
        "from pathlib import Path\n"
        "import optimal.face\n"
        "import optimal.defs as defs\n"
        "import optimal.enums as enums\n"
        "import optimal.moves as mv\n"
        "path = Path('cornerprun')\n"
        "if path.exists() and path.stat().st_size == defs.N_CORNERS:\n"
        "    print('cornerprun already ready')\n"
        "else:\n"
        "    print('creating cornerprun table...')\n"
        "    corner_depth = ar.array('b', [-1] * defs.N_CORNERS)\n"
        "    corner_depth[0] = 0\n"
        "    done = 1\n"
        "    depth = 0\n"
        "    while done != defs.N_CORNERS:\n"
        "        for corners in range(defs.N_CORNERS):\n"
        "            if corner_depth[corners] != depth:\n"
        "                continue\n"
        "            base = defs.N_MOVE * corners\n"
        "            for move in enums.Move:\n"
        "                corners1 = mv.corners_move[base + move]\n"
        "                if corner_depth[corners1] == -1:\n"
        "                    corner_depth[corners1] = depth + 1\n"
        "                    done += 1\n"
        "        depth += 1\n"
        "    with path.open('wb') as fh:\n"
        "        corner_depth.tofile(fh)\n"
        "    print('cornerprun ready')\n"
    )


def _run_cornerprun_generation(
    *,
    table_dir: Path,
    executable: Path,
    package_path: str,
    timeout_seconds: float,
) -> tuple[list[str], dict[str, Any]]:
    command = [
        "nice",
        "-n",
        "20",
        str(executable),
        "-c",
        _cornerprun_code(),
    ]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(package_path) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    begin = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=table_dir,
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
        check=False,
    )
    return command, {
        "return_code": completed.returncode,
        "timed_out": False,
        "runtime_seconds": round(time.perf_counter() - begin, 6),
        "stdout_tail": "\n".join(completed.stdout.splitlines()[-80:]),
        "stderr_tail": "\n".join(completed.stderr.splitlines()[-80:]),
    }


def _tex(value: object) -> str:
    return str(value).replace("\\", "\\textbackslash{}").replace("_", "\\_").replace("&", "\\&")


def _write_table(root: Path, payload: dict[str, Any], suffix: str) -> Path:
    table_path = root / "thesis" / "tables" / f"rubikoptimal_tables{suffix}.tex"
    table_path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for row in payload["inventory"]:
        rows.append(
            f"{_tex(row['name'])} & "
            f"{int(row['expected_size_bytes'])} & "
            f"{_tex(row['exists'])} & "
            f"{_tex(row['size_matches'])} \\\\"
        )
    table_path.write_text(
        "{\\small\n"
        "\\begin{tabular}{lrrr}\n"
        "\\hline\n"
        "Table & Expected bytes & Present & Size OK \\\\\n"
        "\\hline\n"
        + "\n".join(rows)
        + "\n\\hline\n\\end{tabular}\n"
        "}\n",
        encoding="utf-8",
    )
    return table_path


def build_payload(
    *,
    root: Path,
    table_dir: Path,
    executable: Path | None,
    package_path: str | None,
    timeout_seconds: float,
    dry_run: bool,
    require_safe: bool = False,
    force: bool = False,
    cornerprun_only: bool = False,
) -> dict[str, Any]:
    started = time.perf_counter()
    command: list[str] | None = None
    run_result: dict[str, Any] | None = None
    errors: list[str] = []
    status = "dry_run" if dry_run else "not_started"

    if executable is None:
        errors.append("RubikOptimal executable was not found; set RUBIKOPTIMAL_PYTHON or install pypy3")
    if package_path is None:
        errors.append("RubikOptimal package path was not found; install RubikOptimal or set RUBIKOPTIMAL_PACKAGE_PATH")

    table_dir.mkdir(parents=True, exist_ok=True)
    before_ready = rubikoptimal_tables_ready(table_dir)
    safety = evaluate_rubikoptimal_generation_safety(root=root, table_dir=table_dir)

    if not dry_run and not before_ready and not errors and cornerprun_only:
        status = "cornerprun_only"
        try:
            command, run_result = _run_cornerprun_generation(
                table_dir=table_dir,
                executable=executable,
                package_path=str(package_path),
                timeout_seconds=timeout_seconds,
            )
            if run_result["return_code"] != 0:
                errors.append(f"RubikOptimal cornerprun generation exited with {run_result['return_code']}")
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
            run_result = {
                "return_code": 124,
                "timed_out": True,
                "runtime_seconds": timeout_seconds,
                "stdout_tail": "\n".join(stdout.splitlines()[-80:]),
                "stderr_tail": "\n".join(stderr.splitlines()[-80:]),
            }
            errors.append(f"RubikOptimal cornerprun generation timed out after {timeout_seconds}s")
    elif not dry_run and not before_ready and not errors:
        if require_safe and not force and not safety["safe_to_start"]:
            status = "refused_unsafe_generation"
            errors.append("RubikOptimal table generation refused by --require-safe")
        else:
            status = "full_generation"
            command = [
                "nice",
                "-n",
                "20",
                str(executable),
                "-c",
                "import optimal.solver; print('rubikoptimal_tables_ready')",
            ]
            env = os.environ.copy()
            env["PYTHONPATH"] = str(package_path) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
            begin = time.perf_counter()
            try:
                completed = subprocess.run(
                    command,
                    cwd=table_dir,
                    env=env,
                    text=True,
                    capture_output=True,
                    timeout=timeout_seconds,
                    check=False,
                )
                run_result = {
                    "return_code": completed.returncode,
                    "timed_out": False,
                    "runtime_seconds": round(time.perf_counter() - begin, 6),
                    "stdout_tail": "\n".join(completed.stdout.splitlines()[-80:]),
                    "stderr_tail": "\n".join(completed.stderr.splitlines()[-80:]),
                }
                if completed.returncode != 0:
                    errors.append(f"RubikOptimal table generation exited with {completed.returncode}")
            except subprocess.TimeoutExpired as exc:
                stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
                stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
                run_result = {
                    "return_code": 124,
                    "timed_out": True,
                    "runtime_seconds": round(time.perf_counter() - begin, 6),
                    "stdout_tail": "\n".join(stdout.splitlines()[-80:]),
                    "stderr_tail": "\n".join(stderr.splitlines()[-80:]),
                }
                errors.append(f"RubikOptimal table generation timed out after {timeout_seconds}s")
    elif before_ready:
        status = "already_ready"

    inventory = rubikoptimal_table_inventory(table_dir)
    ready = all(row["size_matches"] is True for row in inventory)
    missing = [row["name"] for row in inventory if row["size_matches"] is not True]
    return {
        "schema_version": 1,
        "checked_at_utc": datetime.now(UTC).isoformat(),
        "table_dir": str(table_dir.relative_to(root) if table_dir.is_relative_to(root) else table_dir),
        "executable": str(executable) if executable else None,
        "package_path": package_path,
        "dry_run": dry_run,
        "timeout_seconds": timeout_seconds,
        "status": status,
        "require_safe": require_safe,
        "force": force,
        "cornerprun_only": cornerprun_only,
        "safety": safety,
        "expected_table_count": len(RUBIKOPTIMAL_TABLE_SIZES),
        "expected_total_size_bytes": sum(RUBIKOPTIMAL_TABLE_SIZES.values()),
        "before_ready": before_ready,
        "ready": ready,
        "table_bytes": rubikoptimal_table_bytes(table_dir),
        "missing_or_wrong_tables": missing,
        "command": " ".join(command) if command else None,
        "run_result": run_result,
        "inventory": inventory,
        "runtime_seconds": round(time.perf_counter() - started, 6),
        "errors": errors,
        "passed": ready and not errors,
        "operation_succeeded": (dry_run or status == "already_ready" or (cornerprun_only and not errors) or ready),
        "notes": (
            "RubikOptimal is a separate public optimal-solver backend. Its table generation is isolated under "
            ".codex_external so importing optimal.solver never writes large pruning files into the repository root."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--table-dir", type=Path, default=None)
    parser.add_argument("--executable", type=Path, default=None)
    parser.add_argument("--package-path", default=None)
    parser.add_argument("--timeout", type=float, default=1800.0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--require-safe", action="store_true")
    parser.add_argument("--force", action="store_true", help="Override --require-safe for a full table-generation run")
    parser.add_argument(
        "--cornerprun-only",
        action="store_true",
        help="Generate only the small cornerprun table without importing optimal.pruning",
    )
    parser.add_argument("--profile", default="thesis")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--artifact-suffix", default="lowload")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()

    table_dir = args.table_dir or default_rubikoptimal_table_dir(args.root)
    executable = find_rubikoptimal_executable(args.executable)
    package_path = args.package_path or default_rubikoptimal_pythonpath()
    payload = build_payload(
        root=args.root,
        table_dir=table_dir,
        executable=executable,
        package_path=package_path,
        timeout_seconds=args.timeout,
        dry_run=args.dry_run,
        require_safe=args.require_safe,
        force=args.force,
        cornerprun_only=args.cornerprun_only,
    )
    suffix_parts = [f"seed_{args.seed}", args.profile]
    if args.artifact_suffix:
        suffix_parts.append(args.artifact_suffix)
    suffix = "_" + "_".join(suffix_parts)
    output = args.root / "results" / "processed" / f"rubikoptimal_tables{suffix}.json"
    write_json(output, payload)
    table = _write_table(args.root, payload, suffix)
    print(
        json.dumps(
            {
                "output": str(output),
                "table": str(table),
                "ready": payload["ready"],
                "passed": payload["passed"],
                "status": payload["status"],
                "operation_succeeded": payload["operation_succeeded"],
                "missing_or_wrong_tables": payload["missing_or_wrong_tables"],
            },
            indent=2,
        )
    )
    if payload["operation_succeeded"]:
        return 0
    if payload["status"] == "refused_unsafe_generation":
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

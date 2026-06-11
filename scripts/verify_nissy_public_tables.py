#!/usr/bin/env python
"""Verify that all public Nissy 2.x table archive entries are installed."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rubik_optimal.results import write_json
from scripts.inspect_nissy_public_tables import (
    PUBLIC_NISSY_TABLES_URL,
    build_manifest,
    fetch_head,
    fetch_zip_tail,
    parse_zip_central_directory,
)


MISSING_TABLE_WARNING = "Some pruning tables are missing or unreadable"


def _find_nissy_binary(root: Path, binary_path: str | Path | None) -> Path | None:
    if binary_path is not None:
        path = Path(binary_path)
        return path if path.exists() else None
    env_path = os.environ.get("NISSY_BINARY")
    if env_path:
        path = Path(env_path)
        return path if path.exists() else None
    local = root / ".codex_external" / "nissy-2.0.8" / "nissy"
    if local.exists():
        return local
    found = shutil.which("nissy")
    return Path(found) if found else None


def _fetch_manifest(*, url: str, tail_bytes: int, timeout: float) -> dict[str, Any]:
    head = fetch_head(url, timeout=timeout)
    content_length = head.get("content_length")
    if not isinstance(content_length, int):
        raise RuntimeError("server did not report a content-length")
    tail, range_response = fetch_zip_tail(url, tail_bytes=tail_bytes, timeout=timeout)
    if range_response["status"] != 206:
        raise RuntimeError(f"server did not honor range request: status {range_response['status']}")
    zip_directory = parse_zip_central_directory(tail, content_length=content_length)
    return build_manifest(
        source_url=url,
        head=head,
        range_response=range_response,
        zip_directory=zip_directory,
    )


def _run_nissy_ptable(
    *,
    root: Path,
    table_dir: Path,
    binary_path: str | Path | None,
    timeout: float,
) -> dict[str, Any]:
    binary = _find_nissy_binary(root, binary_path)
    if binary is None:
        return {
            "available": False,
            "binary": None,
            "return_code": None,
            "stdout": "",
            "stderr": "",
            "combined_output": "",
            "reports_missing_tables": True,
            "listed_pruning_tables": [],
            "error": "Nissy binary not found; set NISSY_BINARY or install nissy on PATH",
        }

    env = os.environ.copy()
    env["NISSYDATA"] = str(table_dir.parent)
    try:
        completed = subprocess.run(
            [str(binary), "ptable"],
            cwd=root,
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        combined = "\n".join(part for part in (stdout, stderr) if part)
        listed = [
            line.strip()
            for line in combined.splitlines()
            if line.strip().startswith("pt_")
        ]
        return {
            "available": True,
            "binary": str(binary),
            "return_code": completed.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "combined_output": combined,
            "reports_missing_tables": MISSING_TABLE_WARNING in combined,
            "listed_pruning_tables": listed,
            "error": None,
        }
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        combined = "\n".join(str(part) for part in (stdout, stderr) if part)
        return {
            "available": True,
            "binary": str(binary),
            "return_code": None,
            "stdout": stdout,
            "stderr": stderr,
            "combined_output": combined,
            "reports_missing_tables": MISSING_TABLE_WARNING in combined,
            "listed_pruning_tables": [],
            "error": f"nissy ptable timed out after {timeout}s",
        }


def build_public_table_completeness_payload(
    *,
    root: Path,
    profile: str,
    seed: int,
    table_dir: Path,
    manifest: dict[str, Any],
    binary_path: str | Path | None = None,
    ptable_timeout: float = 30.0,
) -> dict[str, Any]:
    entries = list(manifest.get("table_entries") or [])
    rows: list[dict[str, Any]] = []
    for entry in entries:
        name = str(entry["name"])
        basename = Path(name).name
        target = table_dir / basename
        expected_size = int(entry["uncompressed_size"])
        actual_size = target.stat().st_size if target.exists() else None
        rows.append(
            {
                "name": name,
                "target_path": str(target.relative_to(root) if target.is_absolute() else target),
                "exists": target.exists(),
                "expected_size_bytes": expected_size,
                "actual_size_bytes": actual_size,
                "size_matches_archive": actual_size == expected_size,
                "crc32": entry.get("crc32"),
            }
        )

    missing_tables = [row["name"] for row in rows if not row["exists"]]
    wrong_size_tables = [row["name"] for row in rows if row["exists"] and not row["size_matches_archive"]]
    ptable = _run_nissy_ptable(
        root=root,
        table_dir=table_dir,
        binary_path=binary_path,
        timeout=ptable_timeout,
    )
    expected_pruning_tables = sorted(
        Path(str(entry["name"])).name
        for entry in entries
        if Path(str(entry["name"])).name.startswith("pt_")
    )
    listed_pruning_tables = sorted(str(name) for name in ptable.get("listed_pruning_tables", []))
    missing_from_ptable = [
        table for table in expected_pruning_tables if table not in listed_pruning_tables
    ]
    passed = (
        bool(entries)
        and not missing_tables
        and not wrong_size_tables
        and ptable.get("available") is True
        and ptable.get("return_code") == 0
        and ptable.get("reports_missing_tables") is False
        and not missing_from_ptable
    )
    return {
        "schema_version": 1,
        "checked_at_utc": datetime.now(UTC).isoformat(),
        "profile": profile,
        "seed": seed,
        "source_url": manifest.get("source_url"),
        "table_dir": str(table_dir.relative_to(root) if table_dir.is_absolute() else table_dir),
        "archive_table_entry_count": len(entries),
        "installed_table_count": sum(1 for row in rows if row["exists"]),
        "all_archive_tables_installed": not missing_tables,
        "all_archive_table_sizes_match": not wrong_size_tables,
        "expected_total_uncompressed_bytes": sum(int(row["expected_size_bytes"]) for row in rows),
        "installed_total_bytes": sum(int(row["actual_size_bytes"] or 0) for row in rows),
        "missing_tables": missing_tables,
        "wrong_size_tables": wrong_size_tables,
        "expected_pruning_tables": expected_pruning_tables,
        "missing_from_ptable": missing_from_ptable,
        "nissy_ptable": ptable,
        "table_rows": rows,
        "fast_runtime_proven_for_every_possible_state": False,
        "notes": (
            "Completeness check for the installed public Nissy 2.x table archive. "
            "Passing this check removes the external backend's missing-table warning, "
            "but it is installation evidence, not a worst-case runtime proof for every 3x3 state."
        ),
        "passed": passed,
    }


def _tex(value: object) -> str:
    return str(value).replace("\\", "\\textbackslash{}").replace("_", "\\_").replace("&", "\\&")


def _write_latex_table(root: Path, payload: dict[str, Any], suffix: str) -> Path:
    table_path = root / "thesis" / "tables" / f"nissy_public_tables_complete{suffix}.tex"
    table_path.parent.mkdir(parents=True, exist_ok=True)
    table_path.write_text(
        "{\\small\n"
        "\\begin{tabular}{lrrl}\n"
        "\\hline\n"
        "Check & Expected & Actual & Status \\\\\n"
        "\\hline\n"
        f"Archive table files & {payload['archive_table_entry_count']} & "
        f"{payload['installed_table_count']} & {_tex(payload['all_archive_tables_installed'])} \\\\\n"
        f"Bytes & {payload['expected_total_uncompressed_bytes']} & "
        f"{payload['installed_total_bytes']} & {_tex(payload['all_archive_table_sizes_match'])} \\\\\n"
        f"Nissy ptable warning & 0 & "
        f"{int(bool(payload['nissy_ptable']['reports_missing_tables']))} & "
        f"{_tex(not payload['nissy_ptable']['reports_missing_tables'])} \\\\\n"
        "\\hline\n"
        "\\end{tabular}\n"
        "}\n",
        encoding="utf-8",
    )
    return table_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=PUBLIC_NISSY_TABLES_URL)
    parser.add_argument("--profile", default="thesis")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--table-dir", type=Path, default=ROOT / ".codex_external" / "nissy_data" / "tables")
    parser.add_argument("--nissy-binary", default=None)
    parser.add_argument("--tail-bytes", type=int, default=1024 * 1024)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--artifact-suffix", default="complete_public")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()

    manifest = _fetch_manifest(url=args.url, tail_bytes=args.tail_bytes, timeout=args.timeout)
    payload = build_public_table_completeness_payload(
        root=args.root,
        profile=args.profile,
        seed=args.seed,
        table_dir=args.table_dir,
        manifest=manifest,
        binary_path=args.nissy_binary,
        ptable_timeout=args.timeout,
    )
    suffix_parts = [f"seed_{args.seed}", args.profile]
    if args.artifact_suffix:
        suffix_parts.append(args.artifact_suffix)
    suffix = "_" + "_".join(str(part) for part in suffix_parts)
    output = args.root / "results" / "processed" / f"nissy_public_tables_complete{suffix}.json"
    write_json(output, payload)
    table = _write_latex_table(args.root, payload, suffix)
    print(
        json.dumps(
            {
                "output": str(output),
                "table": str(table),
                "passed": payload["passed"],
                "archive_table_entry_count": payload["archive_table_entry_count"],
                "installed_table_count": payload["installed_table_count"],
                "nissy_reports_missing_tables": payload["nissy_ptable"]["reports_missing_tables"],
                "fast_runtime_proven_for_every_possible_state": payload[
                    "fast_runtime_proven_for_every_possible_state"
                ],
            },
            indent=2,
        )
    )
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python
"""Build and run the native 3x3 corner pattern-database generator."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rubik_optimal.results import write_json
from rubik_optimal.source_state import capture_source_state
from rubik_optimal.tables.metadata import sha256_file

CORNER_PERMUTATION_COUNT = 40_320
CORNER_ORIENTATION_COUNT = 2_187
CORNER_STATE_COUNT = CORNER_PERMUTATION_COUNT * CORNER_ORIENTATION_COUNT


def _compile(root: Path, compiler: str) -> Path:
    source = root / "native" / "corner_pdb" / "corner_pdb.cpp"
    binary = root / "native" / "build" / "corner_pdb"
    binary.parent.mkdir(parents=True, exist_ok=True)
    command = [
        compiler,
        "-std=c++17",
        "-O3",
        "-DNDEBUG",
        str(source),
        "-o",
        str(binary),
    ]
    subprocess.run(command, cwd=root, check=True)
    return binary


def _write_metadata_table(root: Path, metadata: dict[str, object]) -> None:
    table_path = root / "thesis" / "tables" / "corner_pdb_metadata.tex"
    table_path.parent.mkdir(parents=True, exist_ok=True)
    distribution = metadata["distribution"]  # type: ignore[index]
    table_path.write_text(
        "{\\small\n"
        "\\begin{tabular}{lr}\n"
        "\\hline\n"
        "Metric & Value \\\\\n"
        "\\hline\n"
        f"Projected states & {metadata['state_count']} \\\\\n"
        f"Visited states & {metadata['visited_states']} \\\\\n"
        f"Complete & {metadata['complete']} \\\\\n"
        f"Maximum distance & {metadata['max_distance']} \\\\\n"
        f"Binary size bytes & {metadata['size_bytes']} \\\\\n"
        f"Runtime seconds & {float(metadata['runtime_seconds']):.3f} \\\\\n"
        f"Distribution buckets & {len(distribution)} \\\\\n"
        "\\hline\n"
        "\\end{tabular}\n"
        "}\n",
        encoding="utf-8",
    )


def generate_corner_pdb(
    *,
    root: Path,
    output_root: Path | None = None,
    profile: str,
    seed: int,
    compiler: str,
    max_depth: int | None,
) -> dict[str, object]:
    output_root = output_root or root
    binary = _compile(root, compiler)
    output = output_root / "data" / "generated" / f"{profile}_seed_{seed}_corner_state_pdb.bin"
    output.parent.mkdir(parents=True, exist_ok=True)

    command = [str(binary), "--output", str(output)]
    if max_depth is not None:
        command.extend(["--max-depth", str(max_depth)])
    begin = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=root,
        check=True,
        text=True,
        capture_output=True,
    )
    runtime_seconds = time.perf_counter() - begin
    native_stats = json.loads(completed.stdout)
    source = root / "native" / "corner_pdb" / "corner_pdb.cpp"
    source_state = capture_source_state(root)
    metadata = {
        "schema_version": 1,
        "table_name": "corner_state_pdb",
        "table_kind": "pattern_database",
        "profile": profile,
        "seed": seed,
        "domain_size": CORNER_STATE_COUNT,
        "entry_count": CORNER_STATE_COUNT,
        "corner_permutation_count": CORNER_PERMUTATION_COUNT,
        "corner_orientation_count": CORNER_ORIENTATION_COUNT,
        "file_path": str(output.relative_to(output_root)),
        "checksum_sha256": sha256_file(output),
        "generated_at_utc": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "generator": "native/corner_pdb/corner_pdb.cpp via scripts/generate_corner_pdb.py",
        "native_source": str(source.relative_to(root)),
        "native_binary": str(binary.relative_to(root)),
        "compiler": compiler,
        "runtime_seconds": runtime_seconds,
        "native_runtime_seconds": native_stats["runtime_seconds"],
        "size_bytes": output.stat().st_size,
        "source_state": source_state["state"],
        "source_state_details": source_state,
        "source_snapshot_reproducible": source_state["is_reproducible_checkout"],
        "source_snapshot_limitation": source_state["limitation"],
        "source_reproduction_plan": source_state["reproduction_plan"],
        "notes": "3x3 corner-state pattern database over 8! * 3^7 projected states; one byte per distance",
        **native_stats,
    }
    metadata_path = output_root / "results" / "processed" / f"corner_pdb_metadata_seed_{seed}_{profile}.json"
    write_json(metadata_path, metadata)
    _write_metadata_table(output_root, metadata)
    return {"binary": str(output), "metadata": str(metadata_path), "stats": metadata}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=["quick", "thesis", "stress"], default="quick")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output-root", type=Path, default=None)
    parser.add_argument("--compiler", default="c++")
    parser.add_argument(
        "--max-depth",
        type=int,
        default=None,
        help="Optional depth-limited generation for tests; omit for complete thesis PDB",
    )
    args = parser.parse_args()
    result = generate_corner_pdb(
        root=args.root,
        output_root=args.output_root,
        profile=args.profile,
        seed=args.seed,
        compiler=args.compiler,
        max_depth=args.max_depth,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

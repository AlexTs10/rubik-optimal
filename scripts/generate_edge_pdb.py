#!/usr/bin/env python
"""Build and run the native 6-edge pattern-database generator."""

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
from rubik_optimal.tables.edge_pdb import (
    DEFAULT_ADDITIVE_EDGE_PDB_SPECS,
    DEFAULT_EDGE_SUBSETS,
    EDGE_PDB_STATE_COUNT,
    MOVE_NAMES,
    AdditiveEdgePDBSpec,
    additive_edge_pdb_label,
    default_additive_edge_pdb_path,
    edge_subset_label,
)
from rubik_optimal.tables.metadata import sha256_file


def _compile(root: Path, compiler: str) -> Path:
    source = root / "native" / "edge_pdb" / "edge_pdb.cpp"
    binary = root / "native" / "build" / "edge_pdb"
    binary.parent.mkdir(parents=True, exist_ok=True)
    # Skip recompilation when the binary is already up to date. This makes it
    # safe to launch several generation processes in parallel (one per subset)
    # without racing on the shared output binary.
    if binary.exists() and binary.stat().st_mtime >= source.stat().st_mtime:
        return binary
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


def _write_metadata_table(
    root: Path, metadatas: list[dict[str, object]], *, additive: bool = False, subset_size: int = 6
) -> None:
    # 6-edge thesis tables live under thesis/ (the frozen LaTeX tree). The
    # optional 7-edge follow-up (WORSTCASE Path 1) is NOT part of the frozen
    # thesis evidence, so its table is emitted under results/ to avoid touching
    # thesis/ at all.
    if subset_size != 6:
        table_path = root / "results" / "processed" / f"edge_pdb{subset_size}_metadata.tex"
    else:
        table_path = root / "thesis" / "tables" / ("edge_cpdb_metadata.tex" if additive else "edge_pdb_metadata.tex")
    table_path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for metadata in metadatas:
        rows.append(
            f"{str(metadata.get('cost_partition_label') or metadata['subset_label']).replace('_', ',')} & "
            f"{metadata['state_count']} & "
            f"{metadata['complete']} & "
            f"{metadata['max_distance']} & "
            f"{metadata['size_bytes']} & "
            f"{float(metadata['runtime_seconds']):.3f} \\\\"
        )
    header = (
        "Cost partition & States & Complete & Max dist. & Bytes & Seconds \\\\\n"
        if additive
        else "Subset & States & Complete & Max dist. & Bytes & Seconds \\\\\n"
    )
    content = (
        "{\\small\n"
        "\\begin{tabular}{lrrrrr}\n"
        "\\hline\n"
        + header
        + "\\hline\n"
        + "\n".join(rows)
        + "\n\\hline\n\\end{tabular}\n"
        + "}\n"
    )
    table_path.write_text(
        content,
        encoding="utf-8",
    )


def _parse_subset(text: str) -> tuple[int, ...]:
    values = tuple(int(value.strip()) for value in text.split(",") if value.strip())
    if len(values) not in {6, 7} or len(set(values)) != len(values) or any(value < 0 or value >= 12 for value in values):
        raise argparse.ArgumentTypeError("edge subsets must contain six or seven distinct ids in [0, 11]")
    return values


def _parse_move_costs(text: str) -> tuple[int, ...]:
    values = tuple(int(value.strip()) for value in text.split(",") if value.strip())
    if len(values) != len(MOVE_NAMES) or any(value not in {0, 1} for value in values):
        raise argparse.ArgumentTypeError("move costs must contain exactly 18 comma-separated 0/1 values")
    return values


def generate_edge_pdbs(
    *,
    root: Path,
    output_root: Path | None = None,
    profile: str,
    seed: int,
    compiler: str,
    subsets: tuple[tuple[int, ...], ...],
    max_depth: int | None,
    move_costs: tuple[int, ...] | None = None,
    additive_specs: tuple[AdditiveEdgePDBSpec, ...] = (),
) -> dict[str, object]:
    output_root = output_root or root
    binary = _compile(root, compiler)
    source = root / "native" / "edge_pdb" / "edge_pdb.cpp"
    source_state = capture_source_state(root)
    outputs: list[dict[str, object]] = []
    metadata_paths: list[str] = []

    specs: list[tuple[tuple[int, ...], str, Path, Path, tuple[int, ...] | None, str | None]] = []
    if additive_specs:
        for spec in additive_specs:
            label = edge_subset_label(spec.subset_edges)
            cpdb_label = additive_edge_pdb_label(spec)
            output = default_additive_edge_pdb_path(spec, root=output_root, profile=profile, seed=seed)
            metadata_path = (
                output_root
                / "results"
                / "processed"
                / f"edge_cpdb_metadata_{cpdb_label}_seed_{seed}_{profile}.json"
            )
            specs.append((spec.subset_edges, label, output, metadata_path, spec.move_costs, spec.label))
    else:
        for subset in subsets:
            label = edge_subset_label(subset)
            output = output_root / "data" / "generated" / f"{profile}_seed_{seed}_edge_subset_{label}_pdb.bin"
            metadata_path = (
                output_root / "results" / "processed" / f"edge_pdb_metadata_subset_{label}_seed_{seed}_{profile}.json"
            )
            specs.append((subset, label, output, metadata_path, move_costs, None))

    for subset, label, output, metadata_path, table_move_costs, cost_partition_label in specs:
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.exists() and metadata_path.exists():
            existing = json.loads(metadata_path.read_text(encoding="utf-8"))
            if existing.get("complete") is True and max_depth is None and bool(existing.get("cost_partitioned")) == bool(table_move_costs and any(cost == 0 for cost in table_move_costs)):
                metadata_paths.append(str(metadata_path))
                outputs.append(existing)
                continue
        command = [str(binary), "--output", str(output), "--subset", ",".join(str(edge) for edge in subset)]
        if table_move_costs is not None:
            command.extend(["--move-costs", ",".join(str(cost) for cost in table_move_costs)])
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
        metadata = {
            "schema_version": 1,
            "table_name": (
                f"edge_cpdb_{cost_partition_label}_{label}" if cost_partition_label else f"edge_subset_{label}_pdb"
            ),
            "table_kind": (
                "cost_partitioned_edge_pattern_database"
                if native_stats.get("cost_partitioned")
                else "pattern_database"
            ),
            "profile": profile,
            "seed": seed,
            "subset_edges": list(subset),
            "subset_label": label,
            "cost_partition_label": cost_partition_label,
            "move_costs": list(table_move_costs) if table_move_costs is not None else [1] * len(MOVE_NAMES),
            "domain_size": int(native_stats["state_count"]),
            "entry_count": int(native_stats["state_count"]),
            "file_path": str(output.relative_to(output_root)),
            "checksum_sha256": sha256_file(output),
            "generated_at_utc": datetime.now(UTC).replace(microsecond=0).isoformat(),
            "generator": "native/edge_pdb/edge_pdb.cpp via scripts/generate_edge_pdb.py",
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
            "notes": (
                f"{int(native_stats['subset_size'])}-edge cost-partitioned 3x3 pattern database with 0/1 HTM "
                "operator costs; compatible tables may be summed when their move costs partition each move"
                if native_stats.get("cost_partitioned")
                else (
                    f"{int(native_stats['subset_size'])}-edge 3x3 pattern database over "
                    f"C(12,{int(native_stats['subset_size'])}) * {int(native_stats['subset_size'])}! * "
                    f"2^{int(native_stats['subset_size'])} projected states; one byte per distance"
                )
            ),
            **native_stats,
        }
        write_json(metadata_path, metadata)
        metadata_paths.append(str(metadata_path))
        outputs.append(metadata)

    subset_size = len(subsets[0]) if subsets else 6
    state_count_per_subset = int(outputs[0]["state_count"]) if outputs else EDGE_PDB_STATE_COUNT
    summary = {
        "schema_version": 1,
        "profile": profile,
        "seed": seed,
        "table_kind": "cost_partitioned_edge_pattern_database_set" if additive_specs else "edge_pattern_database_set",
        "subset_size": subset_size,
        "subset_count": len(outputs),
        "cost_partition_count": len(outputs) if additive_specs else 0,
        "state_count_per_subset": state_count_per_subset,
        "total_state_count": sum(int(item["state_count"]) for item in outputs),
        "cost_partitioned": bool(additive_specs),
        "complete": all(bool(item["complete"]) for item in outputs),
        "total_size_bytes": sum(int(item["size_bytes"]) for item in outputs),
        "total_runtime_seconds": sum(float(item["runtime_seconds"]) for item in outputs),
        "subsets": outputs,
    }
    # 7-edge follow-up tables get a size-tagged summary so they never clobber the
    # frozen 6-edge thesis summary that scripts/verify_results.py audits.
    size_tag = "" if subset_size == 6 else str(subset_size)
    summary_name = (
        f"edge_cpdb{size_tag}_metadata_seed_{seed}_{profile}.json"
        if additive_specs
        else f"edge_pdb{size_tag}_metadata_seed_{seed}_{profile}.json"
    )
    summary_path = output_root / "results" / "processed" / summary_name
    write_json(summary_path, summary)
    _write_metadata_table(output_root, outputs, additive=bool(additive_specs), subset_size=subset_size)
    return {"summary": str(summary_path), "metadata": metadata_paths, "stats": summary}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=["quick", "thesis", "stress"], default="quick")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output-root", type=Path, default=None)
    parser.add_argument("--compiler", default="c++")
    parser.add_argument(
        "--subset",
        type=_parse_subset,
        action="append",
        default=None,
        help="Comma-separated six-edge subset. May be repeated. Default: four thesis 6-edge subsets.",
    )
    parser.add_argument(
        "--max-depth",
        type=int,
        default=None,
        help="Optional depth-limited generation for tests; omit for complete thesis PDBs",
    )
    parser.add_argument(
        "--move-costs",
        type=_parse_move_costs,
        default=None,
        help="Optional 18-entry comma-separated 0/1 move-cost vector for all requested subsets",
    )
    parser.add_argument(
        "--additive-face-partition",
        action="store_true",
        help="Generate the default compatible cost-partitioned edge-PDB set",
    )
    args = parser.parse_args()
    subsets = tuple(args.subset) if args.subset is not None else DEFAULT_EDGE_SUBSETS
    result = generate_edge_pdbs(
        root=args.root,
        output_root=args.output_root,
        profile=args.profile,
        seed=args.seed,
        compiler=args.compiler,
        subsets=subsets,
        max_depth=args.max_depth,
        move_costs=args.move_costs,
        additive_specs=DEFAULT_ADDITIVE_EDGE_PDB_SPECS if args.additive_face_partition else (),
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

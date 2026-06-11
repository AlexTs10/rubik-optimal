"""Reproducible generation of move and pruning tables."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path

from rubik_optimal.coordinates import GENERATED_TABLE_SPECS
from rubik_optimal.moves import ALL_MOVES
from rubik_optimal.results import write_json
from rubik_optimal.source_state import capture_source_state
from rubik_optimal.tables.metadata import GeneratedTableMetadata, sha256_file
from rubik_optimal.tables.move_tables import CoordinateSpec, build_move_table
from rubik_optimal.tables.pruning_tables import build_pruning_table


def _table_path(root: Path, profile: str, seed: int, spec_name: str, kind: str) -> Path:
    return root / "data" / "generated" / f"{profile}_seed_{seed}_{spec_name}_{kind}.json"


def _write_table_payload(
    path: Path,
    *,
    table_name: str,
    table_kind: str,
    profile: str,
    seed: int,
    moves: tuple[str, ...],
    rows: list[list[int]] | list[int],
) -> None:
    write_json(
        path,
        {
            "schema_version": 1,
            "table_name": table_name,
            "table_kind": table_kind,
            "profile": profile,
            "seed": seed,
            "moves": list(moves),
            "rows": rows,
        },
    )


def _moves_for_spec(spec: CoordinateSpec) -> tuple[str, ...]:
    return tuple(getattr(spec, "moves", ALL_MOVES))


def _tex(value: object) -> str:
    return str(value).replace("\\", "\\textbackslash{}").replace("_", "\\_")


def _display_table_name(value: object) -> str:
    return {
        "corner_orientation": "CO",
        "edge_orientation": "EO",
        "ud_slice": "UD slice",
        "phase2_corner_permutation": "P2 corner perm.",
        "phase2_ud_edge_permutation": "P2 U/D edge perm.",
        "phase2_slice_edge_permutation": "P2 slice edge perm.",
    }.get(str(value), str(value))


def _write_latex_metadata_table(root: Path, rows: list[dict[str, object]]) -> None:
    table_path = root / "thesis" / "tables" / "generated_table_metadata.tex"
    table_path.parent.mkdir(parents=True, exist_ok=True)
    body = []
    for row in rows:
        body.append(
            f"{_tex(_display_table_name(row['table_name']))} & {_tex(row['table_kind'])} & "
            f"{row['domain_size']} & {row['entry_count']} & {len(row['moves'])} \\\\"
        )
    table_path.write_text(
        "{\\small\n\\begin{tabular}{L{0.27\\textwidth}L{0.18\\textwidth}rrr}\n"
        "\\hline\n"
        "Table & Kind & Domain & Entries & Moves \\\\\n"
        "\\hline\n"
        + "\n".join(body)
        + "\n\\hline\n\\end{tabular}\n}\n",
        encoding="utf-8",
    )


def generate_coordinate_tables(
    *,
    root: Path | None = None,
    profile: str = "quick",
    seed: int = 2026,
    specs: tuple[CoordinateSpec, ...] = GENERATED_TABLE_SPECS,
) -> dict[str, object]:
    """Generate checked table files and return a manifest payload."""

    root = root or Path.cwd()
    generated_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    source_state = capture_source_state(root)
    source_state_label = str(source_state["state"])
    metadata_rows: list[dict[str, object]] = []

    for spec in specs:
        moves = _moves_for_spec(spec)
        begin = time.perf_counter()
        move_table = build_move_table(spec, moves=moves)
        move_runtime = time.perf_counter() - begin
        move_path = _table_path(root, profile, seed, spec.name, "move_table")
        _write_table_payload(
            move_path,
            table_name=spec.name,
            table_kind="move_table",
            profile=profile,
            seed=seed,
            moves=moves,
            rows=move_table,
        )
        row = GeneratedTableMetadata(
            table_name=spec.name,
            table_kind="move_table",
            profile=profile,
            seed=seed,
            domain_size=spec.domain_size,
            entry_count=sum(len(row) for row in move_table),
            file_path=str(move_path.relative_to(root)),
            checksum_sha256=sha256_file(move_path),
            generated_at_utc=generated_at,
            generator="rubik_optimal.tables.generation.generate_coordinate_tables",
            runtime_seconds=move_runtime,
            size_bytes=move_path.stat().st_size,
            moves=list(moves),
            source_state=source_state_label,
            notes=spec.description,
        ).to_dict()
        row.update({
            "source_state_details": source_state,
            "source_snapshot_reproducible": source_state["is_reproducible_checkout"],
            "source_snapshot_limitation": source_state["limitation"],
            "source_reproduction_plan": source_state["reproduction_plan"],
        })
        metadata_rows.append(row)

        begin = time.perf_counter()
        pruning_table = build_pruning_table(move_table, solved_coord=spec.solved_coord)
        pruning_runtime = time.perf_counter() - begin
        pruning_path = _table_path(root, profile, seed, spec.name, "pruning_table")
        _write_table_payload(
            pruning_path,
            table_name=spec.name,
            table_kind="pruning_table",
            profile=profile,
            seed=seed,
            moves=moves,
            rows=pruning_table,
        )
        row = GeneratedTableMetadata(
            table_name=spec.name,
            table_kind="pruning_table",
            profile=profile,
            seed=seed,
            domain_size=spec.domain_size,
            entry_count=len(pruning_table),
            file_path=str(pruning_path.relative_to(root)),
            checksum_sha256=sha256_file(pruning_path),
            generated_at_utc=generated_at,
            generator="rubik_optimal.tables.generation.generate_coordinate_tables",
            runtime_seconds=pruning_runtime,
            size_bytes=pruning_path.stat().st_size,
            moves=list(moves),
            source_state=source_state_label,
            notes=f"Projection-distance table for {spec.description}",
        ).to_dict()
        row.update({
            "source_state_details": source_state,
            "source_snapshot_reproducible": source_state["is_reproducible_checkout"],
            "source_snapshot_limitation": source_state["limitation"],
            "source_reproduction_plan": source_state["reproduction_plan"],
        })
        metadata_rows.append(row)

    manifest = {
        "schema_version": 1,
        "profile": profile,
        "seed": seed,
        "generated_at_utc": generated_at,
        "source_state": source_state_label,
        "source_state_details": source_state,
        "source_snapshot_reproducible": source_state["is_reproducible_checkout"],
        "source_snapshot_limitation": source_state["limitation"],
        "source_reproduction_plan": source_state["reproduction_plan"],
        "tables": metadata_rows,
    }
    manifest_path = root / "data" / "generated" / f"table_manifest_{profile}_seed_{seed}.json"
    write_json(manifest_path, manifest)
    processed_path = root / "results" / "processed" / f"table_metadata_{profile}_seed_{seed}.json"
    write_json(processed_path, manifest)
    _write_latex_metadata_table(root, metadata_rows)
    return {"manifest": str(manifest_path), "metadata": str(processed_path), "tables": metadata_rows}

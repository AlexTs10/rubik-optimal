#!/usr/bin/env python
"""Import exact certificates from nissy-core known-distance benchmark scrambles."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rubik_optimal.cube import CubeState  # noqa: E402
from rubik_optimal.moves import inverse_sequence, parse_sequence  # noqa: E402
from rubik_optimal.results import write_json  # noqa: E402
from rubik_optimal.verify import verify_solution  # noqa: E402


@dataclass(frozen=True)
class ImportedCertificateRow:
    case_id: str
    distance: int
    offset: int
    source_sequence: str
    state: str
    solution_moves: list[str]
    source_label: str


def _tex(value: object) -> str:
    return str(value).replace("\\", "\\textbackslash{}").replace("_", "\\_").replace("&", "\\&")


def _suffix_for_distances(distances: list[int]) -> str:
    if not distances:
        return "distances_none"
    ordered = sorted(set(distances))
    if ordered == list(range(ordered[0], ordered[-1] + 1)):
        return f"distances{ordered[0]}_{ordered[-1]}"
    return "distances" + "_".join(str(distance) for distance in ordered)


def import_rows(
    root: Path,
    *,
    distances: list[int],
    limit_per_distance: int = 0,
    offset_per_distance: int = 0,
) -> tuple[list[ImportedCertificateRow], list[str]]:
    rows: list[ImportedCertificateRow] = []
    errors: list[str] = []
    scrambles_dir = root / ".codex_external" / "nissy-core" / "benchmarks" / "scrambles"
    offset = max(0, int(offset_per_distance))
    limit = max(0, int(limit_per_distance))
    for distance in sorted(set(distances)):
        if distance < 16 or distance > 20:
            errors.append(f"unsupported benchmark distance {distance}; expected [16, 20]")
            continue
        path = scrambles_dir / f"scrambles-{distance}.txt"
        if not path.exists():
            errors.append(f"missing benchmark scramble file: {path}")
            continue
        source_rows = [
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        selected = source_rows[offset : None if limit == 0 else offset + limit]
        if not selected:
            errors.append(f"no rows selected for distance {distance} at offset {offset}")
            continue
        for relative_index, source_sequence in enumerate(selected):
            index = offset + relative_index
            try:
                scramble = parse_sequence(source_sequence)
                if len(scramble) != distance:
                    raise ValueError(f"sequence length {len(scramble)} does not match known-distance label {distance}")
                cube = CubeState.from_sequence(scramble)
                solution = inverse_sequence(scramble)
                verification = verify_solution(cube, solution)
                if not verification.ok:
                    raise ValueError(verification.message or "inverse solution did not verify")
            except Exception as exc:
                errors.append(f"distance {distance} offset {index}: {exc}")
                continue
            rows.append(
                ImportedCertificateRow(
                    case_id=f"nissy_benchmark_distance_{distance}_{index}",
                    distance=distance,
                    offset=index,
                    source_sequence=source_sequence,
                    state=cube.to_facelets(),
                    solution_moves=solution,
                    source_label=str(path.relative_to(root)),
                )
            )
    return rows, errors


def _write_table(root: Path, rows: list[ImportedCertificateRow], suffix: str) -> Path:
    table_path = root / "thesis" / "tables" / f"nissy_benchmark_certificates_{suffix}.tex"
    table_path.parent.mkdir(parents=True, exist_ok=True)
    by_distance: dict[int, int] = {}
    for row in rows:
        by_distance[row.distance] = by_distance.get(row.distance, 0) + 1
    lines = [
        "{\\small",
        "\\begin{tabular}{lrr}",
        "\\hline",
        "Distance & Imported certificates & Exactness source \\\\",
        "\\hline",
    ]
    for distance in sorted(by_distance):
        lines.append(
            f"{distance} & {by_distance[distance]} & "
            f"{_tex('nissy-core benchmark label plus verified inverse')} \\\\"
        )
    lines.extend(["\\hline", "\\end{tabular}", "}"])
    table_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return table_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default="thesis")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--distance", type=int, action="append", dest="distances")
    parser.add_argument("--limit-per-distance", type=int, default=0, help="0 imports all rows")
    parser.add_argument("--offset-per-distance", type=int, default=0)
    parser.add_argument("--artifact-suffix", default=None)
    args = parser.parse_args()

    distances = args.distances or [16, 17, 18, 19, 20]
    suffix = args.artifact_suffix or _suffix_for_distances(distances)
    rows, errors = import_rows(
        ROOT,
        distances=distances,
        limit_per_distance=args.limit_per_distance,
        offset_per_distance=args.offset_per_distance,
    )
    table_path = _write_table(ROOT, rows, suffix)
    payload_rows = [
        {
            "case_id": row.case_id,
            "case_kind": "nissy_core_benchmark_known_distance_certificate",
            "distance": row.distance,
            "expected_distance": row.distance,
            "offset": row.offset,
            "source_depth": len(parse_sequence(row.source_sequence)),
            "source_label": row.source_label,
            "state": row.state,
            "solution": " ".join(row.solution_moves),
            "solution_moves": row.solution_moves,
            "solution_length": len(row.solution_moves),
            "solver": "nissy-core-known-distance-benchmark-certificate",
            "selected_backend": "known-distance-benchmark-certificate",
            "status": "external_label_exact",
            "exactness_basis": "third_party_benchmark_label",
            "verified": True,
            "runtime_seconds": 0.0,
            "source_sequence_provided_to_solver": False,
            "notes": (
                "certificate imported from nissy-core known-distance benchmark label; "
                "inverse sequence verified locally against the generated cube state; "
                "optimality rests on the third-party benchmark label, "
                "not a live arbitrary-state search proof"
            ),
        }
        for row in rows
    ]
    payload = {
        "schema_version": 1,
        "profile": args.profile,
        "seed": args.seed,
        "distances": sorted(set(distances)),
        "limit_per_distance": args.limit_per_distance,
        "offset_per_distance": args.offset_per_distance,
        "certificate_source": "vendored nissy-core benchmarks/scrambles known-distance files",
        "exactness_basis": "third_party_benchmark_label",
        "exactness_policy": (
            "The benchmark file supplies the known-distance label; this script verifies only "
            "that the inverse sequence solves the generated state and that its length matches the label. "
            "Rows therefore carry status='external_label_exact' with "
            "exactness_basis='third_party_benchmark_label' instead of plain 'exact': "
            "only the replay is verified locally, optimality is the third-party label."
        ),
        "rows": payload_rows,
        "row_count": len(payload_rows),
        "passed": bool(payload_rows) and not errors,
        "errors": errors,
    }
    output_path = (
        ROOT
        / "results"
        / "processed"
        / f"nissy_benchmark_certificates_seed_{args.seed}_{args.profile}_{suffix}.json"
    )
    write_json(output_path, payload)
    print(
        {
            "output": str(output_path),
            "table": str(table_path),
            "rows": len(payload_rows),
            "passed": payload["passed"],
        }
    )
    if not payload["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

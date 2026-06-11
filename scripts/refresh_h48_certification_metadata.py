#!/usr/bin/env python
"""Refresh embedded H48 table metadata in certification artifacts.

The certification rows are solver evidence.  When the H48 table metadata is
explicitly re-adopted without changing the table checksum, those rows do not
need to be re-solved just to replace a stale embedded metadata copy.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rubik_optimal.results import write_json
from rubik_optimal.tables.h48 import canonical_h48_solver, h48_metadata_path


DEFAULT_ARTIFACTS = [
    "results/processed/h48_oracle_certification_seed_2026_thesis.json",
    "results/processed/h48_oracle_certification_seed_2026_thesis_trusted.json",
    "results/processed/h48_oracle_certification_seed_2026_thesis_trusted_no_preload.json",
    "results/processed/h48_oracle_certification_seed_2026_thesis_trusted_preload.json",
    "results/processed/h48_oracle_certification_seed_2026_thesis_auto_min.json",
]


def _load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def refresh_artifact(path: Path, metadata: dict[str, object], metadata_path: Path) -> dict[str, object]:
    payload = _load_json(path)
    previous_metadata = payload.get("metadata")
    if not isinstance(previous_metadata, dict):
        raise ValueError(f"{path} does not contain an embedded metadata object")

    previous_checksum = str(previous_metadata.get("checksum_sha256") or "")
    new_checksum = str(metadata.get("checksum_sha256") or "")
    if previous_checksum != new_checksum:
        raise ValueError(
            f"{path} embeds checksum {previous_checksum}, but adopted metadata has {new_checksum}"
        )

    payload["metadata"] = metadata
    payload["metadata_refresh"] = {
        "schema_version": 1,
        "refreshed_at_utc": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "metadata_path": str(metadata_path),
        "rows_preserved": True,
        "previous_metadata_state_label": str(previous_metadata.get("source_state") or ""),
        "new_metadata_state_label": str(metadata.get("source_state") or ""),
        "checksum_sha256": new_checksum,
        "reason": (
            "Replaced stale embedded H48 table metadata after explicit table adoption; "
            "certification rows, statuses, timings, and solutions were preserved."
        ),
    }
    write_json(path, payload)
    return {
        "path": str(path),
        "previous_metadata_state_label": previous_metadata.get("source_state"),
        "new_metadata_state_label": metadata.get("source_state"),
        "checksum_sha256": new_checksum,
        "rows_preserved": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default="thesis")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--solver", default="h48h7")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("artifacts", nargs="*", help="Certification artifact paths to refresh")
    args = parser.parse_args()

    root = args.root
    solver = canonical_h48_solver(args.solver)
    metadata_path = h48_metadata_path(root=root, profile=args.profile, seed=args.seed, solver=solver)
    metadata = _load_json(metadata_path)
    artifact_paths = args.artifacts or DEFAULT_ARTIFACTS
    refreshed = []
    for relative in artifact_paths:
        path = Path(relative)
        path = path if path.is_absolute() else root / path
        if not path.exists():
            continue
        refreshed.append(refresh_artifact(path, metadata, metadata_path.relative_to(root)))

    print(json.dumps({"metadata_path": str(metadata_path), "refreshed": refreshed}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

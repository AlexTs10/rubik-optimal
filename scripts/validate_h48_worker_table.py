#!/usr/bin/env python
"""Validate a copied H48 table on a cloud hard-tail worker."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rubik_optimal.results import write_json  # noqa: E402
from rubik_optimal.tables.h48 import canonical_h48_solver, validate_trusted_h48_table_checksum  # noqa: E402


def validate_worker_table(
    *,
    root: Path,
    profile: str,
    seed: int,
    solver: str,
    artifact_suffix: str,
    use_cache: bool = True,
    persistent_cache: bool = False,
) -> tuple[dict[str, Any], Path]:
    """Write an auditable full-checksum validation artifact for one H48 table."""

    canonical_solver = canonical_h48_solver(solver)
    passed, message, details = validate_trusted_h48_table_checksum(
        root=root,
        profile=profile,
        seed=seed,
        solver=canonical_solver,
        use_cache=use_cache,
        persistent_cache=persistent_cache,
    )
    payload: dict[str, Any] = {
        "schema_version": 1,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "profile": profile,
        "seed": seed,
        "solver": canonical_solver,
        "artifact_suffix": artifact_suffix,
        "trusted_metadata_valid": details.get("trusted_metadata_valid") is True,
        "full_checksum_valid": details.get("full_checksum_valid") is True,
        "checksum_cache_hit": details.get("checksum_cache_hit") is True,
        "checksum_persistent_cache_hit": details.get("checksum_persistent_cache_hit") is True,
        "checksum_persistent_cache_enabled": details.get("checksum_persistent_cache_enabled") is True,
        "checksum_certificate_path": details.get("checksum_certificate_path"),
        "checksum_certificate_written": details.get("checksum_certificate_written") is True,
        "checksum_runtime_seconds": details.get("checksum_runtime_seconds"),
        "table_path": details.get("table_path"),
        "metadata_path": details.get("metadata_path"),
        "table_size_bytes": details.get("table_size_bytes"),
        "message": message,
        "details": details,
        "passed": passed,
        "fast_runtime_proven_for_every_possible_state": False,
        "notes": (
            "Worker-side H48 table validation for cloud hard-tail proof runs. "
            "This validates the actual copied table bytes before expensive exact search starts; "
            "it is prerequisite evidence, not a runtime proof by itself."
        ),
    }
    suffix_parts = [f"seed_{seed}", profile, canonical_solver]
    if artifact_suffix:
        suffix_parts.append(artifact_suffix)
    output = (
        root
        / "results"
        / "processed"
        / f"h48_worker_table_validation_{'_'.join(str(part) for part in suffix_parts)}.json"
    )
    write_json(output, payload)
    return payload, output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default="thesis")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--solver", default="h48h8")
    parser.add_argument("--artifact-suffix", default="worker")
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument(
        "--persistent-cache",
        action="store_true",
        help=(
            "Reuse a prior full-checksum certificate when table and metadata identities exactly match. "
            "This avoids repeatedly hashing multi-GiB H48 tables across fresh worker/status processes."
        ),
    )
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()

    payload, output = validate_worker_table(
        root=args.root,
        profile=args.profile,
        seed=args.seed,
        solver=args.solver,
        artifact_suffix=args.artifact_suffix,
        use_cache=not args.no_cache,
        persistent_cache=args.persistent_cache,
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "solver": payload["solver"],
                "trusted_metadata_valid": payload["trusted_metadata_valid"],
                "full_checksum_valid": payload["full_checksum_valid"],
                "passed": payload["passed"],
                "checksum_persistent_cache_hit": payload["checksum_persistent_cache_hit"],
                "checksum_certificate_path": payload["checksum_certificate_path"],
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

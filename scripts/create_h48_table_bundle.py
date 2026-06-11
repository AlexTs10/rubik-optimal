#!/usr/bin/env python
"""Create a split, checksummed H48 table bundle for proof-host transfer."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rubik_optimal.results import write_json  # noqa: E402
from rubik_optimal.tables import h48 as h48_tables  # noqa: E402
from rubik_optimal.tables.metadata import sha256_file  # noqa: E402

MANIFEST_NAME = "h48_table_bundle_manifest.json"
DEFAULT_PART_SIZE_MIB = 1024
STREAM_CHUNK_BYTES = 8 * 1024 * 1024


def _relative(root: Path, path: Path) -> str:
    return str(path.relative_to(root)) if path.is_relative_to(root) else str(path)


def _artifact_output_path(
    *,
    root: Path,
    profile: str,
    seed: int,
    solver: str,
    artifact_suffix: str,
) -> Path:
    suffix_parts = [f"seed_{seed}", profile, solver]
    if artifact_suffix:
        suffix_parts.append(artifact_suffix)
    return (
        root
        / "results"
        / "processed"
        / f"h48_table_bundle_manifest_{'_'.join(str(part) for part in suffix_parts)}.json"
    )


def _default_output_dir(
    *,
    root: Path,
    profile: str,
    seed: int,
    solver: str,
    artifact_suffix: str,
) -> Path:
    suffix_parts = [f"seed_{seed}", profile, solver]
    if artifact_suffix:
        suffix_parts.append(artifact_suffix)
    return root / "results" / f"h48_table_bundle_{'_'.join(str(part) for part in suffix_parts)}_parts"


def _load_existing_manifest(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _part_name(solver: str, index: int) -> str:
    return f"{solver}.bin.part{index:05d}"


def _hash_next_bytes(handle, limit: int) -> tuple[int, str]:
    digest = hashlib.sha256()
    written = 0
    while written < limit:
        chunk = handle.read(min(STREAM_CHUNK_BYTES, limit - written))
        if not chunk:
            break
        digest.update(chunk)
        written += len(chunk)
    return written, digest.hexdigest()


def _write_next_part(handle, path: Path, limit: int) -> tuple[int, str]:
    digest = hashlib.sha256()
    written = 0
    tmp_path = path.with_name(path.name + ".tmp")
    with tmp_path.open("wb") as output:
        while written < limit:
            chunk = handle.read(min(STREAM_CHUNK_BYTES, limit - written))
            if not chunk:
                break
            output.write(chunk)
            digest.update(chunk)
            written += len(chunk)
    if written == 0:
        tmp_path.unlink(missing_ok=True)
    else:
        os.replace(tmp_path, path)
    return written, digest.hexdigest()


def _matching_existing_part(
    *,
    part_path: Path,
    expected_size: int,
    expected_sha256: str,
) -> bool:
    if not part_path.exists() or part_path.stat().st_size != expected_size:
        return False
    return sha256_file(part_path).lower() == expected_sha256.lower()


def create_h48_table_bundle(
    *,
    root: Path,
    profile: str,
    seed: int,
    solver: str,
    output_dir: Path | None = None,
    part_size_bytes: int | None = None,
    artifact_suffix: str = "bundle_parts",
    force: bool = False,
) -> tuple[dict[str, Any], Path]:
    canonical_solver = h48_tables.canonical_h48_solver(solver)
    root = root.resolve()
    table_path = h48_tables.h48_table_path(
        root=root,
        profile=profile,
        seed=seed,
        solver=canonical_solver,
    )
    metadata_path = h48_tables.h48_metadata_path(
        root=root,
        profile=profile,
        seed=seed,
        solver=canonical_solver,
    )
    selected_output_dir = output_dir or _default_output_dir(
        root=root,
        profile=profile,
        seed=seed,
        solver=canonical_solver,
        artifact_suffix=artifact_suffix,
    )
    if not selected_output_dir.is_absolute():
        selected_output_dir = root / selected_output_dir
    output = _artifact_output_path(
        root=root,
        profile=profile,
        seed=seed,
        solver=canonical_solver,
        artifact_suffix=artifact_suffix,
    )
    part_size = int(part_size_bytes or DEFAULT_PART_SIZE_MIB * 1024 * 1024)
    if part_size <= 0:
        raise ValueError("part_size_bytes must be positive")

    selected_output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = selected_output_dir / MANIFEST_NAME
    existing_manifest = None if force else _load_existing_manifest(manifest_path)

    checksum_ok, checksum_message, checksum_details = h48_tables.validate_trusted_h48_table_checksum(
        root=root,
        profile=profile,
        seed=seed,
        solver=canonical_solver,
        table_path=table_path,
        use_cache=False,
        persistent_cache=True,
    )
    if not checksum_ok:
        payload = {
            "schema_version": 1,
            "bundle_kind": "h48_split_table_bundle",
            "created_at_utc": datetime.now(UTC).isoformat(),
            "profile": profile,
            "seed": seed,
            "solver": canonical_solver,
            "artifact_suffix": artifact_suffix,
            "output_dir": _relative(root, selected_output_dir),
            "manifest_path": _relative(root, manifest_path),
            "source_table_path": _relative(root, table_path),
            "source_metadata_path": _relative(root, metadata_path),
            "source_full_checksum_valid": False,
            "source_full_checksum_message": checksum_message,
            "source_full_checksum_details": checksum_details,
            "passed": False,
            "fast_runtime_proven_for_every_possible_state": False,
        }
        write_json(output, payload)
        return payload, output

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    expected_checksum = str(metadata["checksum_sha256"]).lower()
    table_size = table_path.stat().st_size
    metadata_copy = selected_output_dir / metadata_path.name
    metadata_copy.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    metadata_sha256 = sha256_file(metadata_copy)

    old_parts: dict[int, dict[str, Any]] = {}
    if (
        existing_manifest
        and existing_manifest.get("bundle_kind") == "h48_split_table_bundle"
        and existing_manifest.get("solver") == canonical_solver
        and existing_manifest.get("profile") == profile
        and int(existing_manifest.get("seed", -1)) == int(seed)
        and int(existing_manifest.get("table_size_bytes", -1)) == table_size
        and str(existing_manifest.get("table_checksum_sha256", "")).lower() == expected_checksum
        and int(existing_manifest.get("part_size_bytes", -1)) == part_size
    ):
        for part in existing_manifest.get("parts") or []:
            if isinstance(part, dict) and isinstance(part.get("index"), int):
                old_parts[int(part["index"])] = part

    parts: list[dict[str, Any]] = []
    reused = 0
    written = 0
    total = 0
    with table_path.open("rb") as source:
        index = 0
        while True:
            part_path = selected_output_dir / _part_name(canonical_solver, index)
            old = old_parts.get(index)
            if old:
                start = source.tell()
                size, digest = _hash_next_bytes(source, part_size)
                if size == 0:
                    break
                if (
                    old.get("path") == part_path.name
                    and int(old.get("size_bytes", -1)) == size
                    and str(old.get("sha256", "")).lower() == digest
                    and _matching_existing_part(
                        part_path=part_path,
                        expected_size=size,
                        expected_sha256=digest,
                    )
                ):
                    reused += 1
                else:
                    source.seek(start)
                    size, digest = _write_next_part(source, part_path, part_size)
                    written += 1
            else:
                size, digest = _write_next_part(source, part_path, part_size)
                if size == 0:
                    break
                written += 1
            parts.append(
                {
                    "index": index,
                    "path": part_path.name,
                    "size_bytes": size,
                    "sha256": digest,
                }
            )
            total += size
            index += 1

    passed = total == table_size and bool(parts)
    manifest = {
        "schema_version": 1,
        "bundle_kind": "h48_split_table_bundle",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "profile": profile,
        "seed": seed,
        "solver": canonical_solver,
        "source_table_path": _relative(root, table_path),
        "source_metadata_path": _relative(root, metadata_path),
        "metadata_path": metadata_copy.name,
        "metadata_sha256": metadata_sha256,
        "table_size_bytes": table_size,
        "table_checksum_sha256": expected_checksum,
        "part_size_bytes": part_size,
        "part_count": len(parts),
        "parts": parts,
        "split_reused_part_count": reused,
        "split_written_part_count": written,
        "fast_runtime_proven_for_every_possible_state": False,
    }
    write_json(manifest_path, manifest)

    payload = {
        **manifest,
        "artifact_suffix": artifact_suffix,
        "output_dir": _relative(root, selected_output_dir),
        "manifest_path": _relative(root, manifest_path),
        "source_full_checksum_valid": checksum_ok,
        "source_full_checksum_message": checksum_message,
        "source_full_checksum_details": checksum_details,
        "assembled_size_bytes": total,
        "passed": passed,
        "notes": (
            "Created a split H48 table bundle with per-part SHA-256 hashes. "
            "This improves proof-host transfer/resume ergonomics for large H48 tables, "
            "but the fast every-state oracle claim still requires installing the table, "
            "validating the full checksum, and passing the hard-tail proof workloads."
        ),
    }
    write_json(output, payload)
    return payload, output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default="thesis")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--solver", required=True)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--part-size-mib", type=int, default=DEFAULT_PART_SIZE_MIB)
    parser.add_argument("--artifact-suffix", default="bundle_parts")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()

    payload, output = create_h48_table_bundle(
        root=args.root,
        profile=args.profile,
        seed=args.seed,
        solver=args.solver,
        output_dir=args.output_dir,
        part_size_bytes=args.part_size_mib * 1024 * 1024,
        artifact_suffix=args.artifact_suffix,
        force=args.force,
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "manifest_path": payload.get("manifest_path"),
                "solver": payload.get("solver"),
                "part_count": payload.get("part_count"),
                "passed": payload.get("passed"),
                "fast_runtime_proven_for_every_possible_state": payload.get(
                    "fast_runtime_proven_for_every_possible_state"
                ),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if payload.get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())

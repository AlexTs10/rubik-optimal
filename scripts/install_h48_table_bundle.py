#!/usr/bin/env python
"""Install a generated H48 table bundle with size and checksum validation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rubik_optimal.results import write_json  # noqa: E402
from rubik_optimal.tables import h48 as h48_tables  # noqa: E402
from rubik_optimal.tables.metadata import sha256_file  # noqa: E402

SPLIT_MANIFEST_NAME = "h48_table_bundle_manifest.json"
STREAM_CHUNK_BYTES = 8 * 1024 * 1024


def _relative(root: Path, path: Path) -> str:
    return str(path.relative_to(root)) if path.is_relative_to(root) else str(path)


def _safe_extract_tar(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with tarfile.open(archive) as handle:
        for member in handle.getmembers():
            target = (destination / member.name).resolve()
            if not target.is_relative_to(root):
                raise ValueError(f"refusing unsafe tar member path: {member.name}")
            if member.issym() or member.islnk():
                raise ValueError(f"refusing linked tar member: {member.name}")
        handle.extractall(destination, filter="data")


def _find_one(base: Path, patterns: list[str], label: str) -> Path:
    matches: list[Path] = []
    for pattern in patterns:
        matches.extend(path for path in base.glob(pattern) if path.is_file())
    matches = sorted(set(matches))
    if not matches:
        raise FileNotFoundError(f"no {label} found under {base}")
    if len(matches) > 1:
        raise ValueError(f"ambiguous {label} candidates: {', '.join(str(path) for path in matches)}")
    return matches[0]


def _find_split_manifest(base: Path) -> Path | None:
    canonical = base / SPLIT_MANIFEST_NAME
    if canonical.is_file():
        return canonical
    matches = sorted(path for path in base.glob("h48_table_bundle_manifest*.json") if path.is_file())
    if not matches:
        return None
    if len(matches) > 1:
        raise ValueError(
            f"ambiguous H48 split-manifest candidates: {', '.join(str(path) for path in matches)}"
        )
    return matches[0]


def _safe_child(base: Path, relative: str, label: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute():
        raise ValueError(f"{label} path must be relative inside split bundle: {relative}")
    resolved = (base / candidate).resolve()
    if not resolved.is_relative_to(base.resolve()):
        raise ValueError(f"{label} path escapes split bundle: {relative}")
    return resolved


def _load_split_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid H48 split-manifest JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"H48 split manifest is not an object: {path}")
    return payload


def _assemble_split_manifest_bundle(
    *,
    root: Path,
    base: Path,
    manifest_path: Path,
    profile: str,
    seed: int,
    solver: str,
) -> tuple[Path, Path, tempfile.TemporaryDirectory[str], dict[str, Any]]:
    manifest = _load_split_manifest(manifest_path)
    if manifest.get("bundle_kind") != "h48_split_table_bundle":
        raise ValueError("H48 split manifest has unexpected bundle_kind")
    if manifest.get("solver") != solver:
        raise ValueError(f"H48 split manifest solver {manifest.get('solver')} does not match {solver}")
    if manifest.get("profile") != profile:
        raise ValueError(f"H48 split manifest profile {manifest.get('profile')} does not match {profile}")
    if int(manifest.get("seed", -1)) != int(seed):
        raise ValueError(f"H48 split manifest seed {manifest.get('seed')} does not match {seed}")
    expected_size = h48_tables.estimated_h48_table_size_bytes(solver)
    if int(manifest.get("table_size_bytes", -1)) != expected_size:
        raise ValueError("H48 split manifest table size does not match expected solver size")
    expected_checksum = str(manifest.get("table_checksum_sha256", "")).lower()
    if len(expected_checksum) != 64 or any(char not in "0123456789abcdef" for char in expected_checksum):
        raise ValueError("H48 split manifest checksum is missing or malformed")

    metadata_path = _safe_child(base, str(manifest.get("metadata_path", "")), "metadata")
    metadata_sha = str(manifest.get("metadata_sha256", "")).lower()
    if not metadata_path.is_file():
        raise FileNotFoundError(f"missing split-bundle metadata: {metadata_path}")
    if len(metadata_sha) == 64 and sha256_file(metadata_path).lower() != metadata_sha:
        raise ValueError("split-bundle metadata checksum does not match manifest")

    parts = manifest.get("parts")
    if not isinstance(parts, list) or not parts:
        raise ValueError("H48 split manifest has no parts")
    expected_part_count = int(manifest.get("part_count", -1))
    if expected_part_count != len(parts):
        raise ValueError("H48 split manifest part_count does not match parts")

    tempdir = tempfile.TemporaryDirectory(prefix=f"h48_{solver}_split_", dir=root / "tmp")
    assembled = Path(tempdir.name) / f"{solver}.bin"
    assembled_digest = hashlib.sha256()
    assembled_size = 0
    part_details: list[dict[str, Any]] = []
    with assembled.open("wb") as output:
        for expected_index, part in enumerate(parts):
            if not isinstance(part, dict):
                raise ValueError("H48 split manifest part is not an object")
            if int(part.get("index", -1)) != expected_index:
                raise ValueError("H48 split manifest part index is not contiguous")
            part_path = _safe_child(base, str(part.get("path", "")), "part")
            expected_part_size = int(part.get("size_bytes", -1))
            expected_part_sha = str(part.get("sha256", "")).lower()
            if not part_path.is_file():
                raise FileNotFoundError(f"missing split-bundle part: {part_path}")
            actual_part_size = part_path.stat().st_size
            if actual_part_size != expected_part_size:
                raise ValueError(f"split-bundle part size mismatch: {part_path}")
            if len(expected_part_sha) != 64:
                raise ValueError(f"split-bundle part checksum is malformed: {part_path}")
            part_digest = hashlib.sha256()
            with part_path.open("rb") as part_input:
                while True:
                    chunk = part_input.read(STREAM_CHUNK_BYTES)
                    if not chunk:
                        break
                    output.write(chunk)
                    part_digest.update(chunk)
                    assembled_digest.update(chunk)
                    assembled_size += len(chunk)
            actual_part_sha = part_digest.hexdigest()
            if actual_part_sha != expected_part_sha:
                raise ValueError(f"split-bundle part checksum mismatch: {part_path}")
            part_details.append(
                {
                    "index": expected_index,
                    "path": str(part_path),
                    "size_bytes": actual_part_size,
                    "sha256": actual_part_sha,
                }
            )
    actual_checksum = assembled_digest.hexdigest()
    if assembled_size != expected_size:
        raise ValueError("assembled split-bundle table size does not match expected solver size")
    if actual_checksum != expected_checksum:
        raise ValueError("assembled split-bundle table checksum does not match manifest")
    temp_metadata = Path(tempdir.name) / metadata_path.name
    shutil.copy2(metadata_path, temp_metadata)
    details = {
        "bundle_resolution_kind": "split_manifest",
        "manifest_path": str(manifest_path),
        "assembled_table_path": str(assembled),
        "assembled_metadata_path": str(temp_metadata),
        "assembled_size_bytes": assembled_size,
        "assembled_checksum_sha256": actual_checksum,
        "part_count": len(part_details),
        "parts_validated": True,
    }
    return assembled, temp_metadata, tempdir, details


def _resolve_bundle_inputs(
    *,
    root: Path,
    profile: str,
    seed: int,
    solver: str,
    bundle: Path | None,
    table_path: Path | None,
    metadata_path: Path | None,
) -> tuple[Path, Path, tempfile.TemporaryDirectory[str] | None, dict[str, Any]]:
    tempdir: tempfile.TemporaryDirectory[str] | None = None
    resolution_details: dict[str, Any] = {"bundle_resolution_kind": "direct_paths"}
    if bundle is not None:
        bundle = bundle if bundle.is_absolute() else root / bundle
        if not bundle.exists():
            raise FileNotFoundError(f"missing H48 bundle: {bundle}")
        if bundle.is_dir():
            base = bundle
            resolution_details = {"bundle_resolution_kind": "directory"}
        else:
            tempdir = tempfile.TemporaryDirectory(prefix=f"h48_{solver}_bundle_", dir=root / "tmp")
            base = Path(tempdir.name)
            _safe_extract_tar(bundle, base)
            resolution_details = {"bundle_resolution_kind": "archive", "extracted_to": str(base)}
        manifest_path = _find_split_manifest(base)
        if manifest_path is not None:
            return _assemble_split_manifest_bundle(
                root=root,
                base=base,
                manifest_path=manifest_path,
                profile=profile,
                seed=seed,
                solver=solver,
            )
        if table_path is None:
            table_path = _find_one(base, [f"**/{solver}.bin"], f"{solver} table")
        if metadata_path is None:
            metadata_path = _find_one(
                base,
                [f"**/h48_metadata_*_{solver}.json"],
                f"{solver} metadata",
            )
    if table_path is None or metadata_path is None:
        raise ValueError("provide --bundle or both --table and --metadata")
    table_path = table_path if table_path.is_absolute() else root / table_path
    metadata_path = metadata_path if metadata_path.is_absolute() else root / metadata_path
    return table_path, metadata_path, tempdir, resolution_details


def _load_metadata(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid H48 metadata JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"H48 metadata is not an object: {path}")
    return payload


def _is_within(path: Path, base: Path) -> bool:
    try:
        return path.resolve().is_relative_to(base.resolve())
    except OSError:
        return False


def _stage_table_file(
    *,
    source_table: Path,
    staged_table: Path,
    tempdir: tempfile.TemporaryDirectory[str] | None,
) -> tuple[str, dict[str, Any]]:
    """Stage a validated table with the least safe I/O available.

    Tables extracted from an archive live in a private temporary directory that
    is removed after installation.  Hard-linking that private source into the
    staged target avoids a second multi-GiB data copy while still leaving a
    normal canonical file after the temporary tree is deleted.  Non-temporary
    sources use copy semantics to avoid tying the canonical table to a mutable
    operator-supplied path.
    """

    details: dict[str, Any] = {
        "source_table": str(source_table),
        "staged_table": str(staged_table),
        "hardlink_attempted": False,
        "hardlink_succeeded": False,
        "fallback_copy_used": False,
    }
    if tempdir is not None and _is_within(source_table, Path(tempdir.name)):
        details["hardlink_attempted"] = True
        try:
            os.link(source_table, staged_table)
            details["hardlink_succeeded"] = True
            return "hardlink_from_extracted_bundle", details
        except OSError as exc:
            details["hardlink_error"] = str(exc)
    shutil.copy2(source_table, staged_table)
    details["fallback_copy_used"] = True
    return "copy2", details


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
        / f"h48_table_bundle_install_{'_'.join(str(part) for part in suffix_parts)}.json"
    )


def _validate_source(
    *,
    table_path: Path,
    metadata_path: Path,
    metadata: dict[str, Any],
    profile: str,
    seed: int,
    solver: str,
    prevalidated_checksum_sha256: str | None = None,
) -> tuple[bool, list[str], dict[str, Any]]:
    reasons: list[str] = []
    if not table_path.exists():
        reasons.append(f"source table missing: {table_path}")
    if not metadata_path.exists():
        reasons.append(f"source metadata missing: {metadata_path}")
    expected_size = h48_tables.estimated_h48_table_size_bytes(solver)
    actual_size = table_path.stat().st_size if table_path.exists() else None
    if actual_size != expected_size:
        reasons.append(f"source table size {actual_size} does not match expected {expected_size}")
    if metadata.get("table_kind") != "h48_pruning_table":
        reasons.append("metadata table_kind is not h48_pruning_table")
    if metadata.get("solver") != solver:
        reasons.append(f"metadata solver {metadata.get('solver')} does not match {solver}")
    if metadata.get("profile") != profile:
        reasons.append(f"metadata profile {metadata.get('profile')} does not match {profile}")
    if int(metadata.get("seed", -1)) != int(seed):
        reasons.append(f"metadata seed {metadata.get('seed')} does not match {seed}")
    if metadata.get("backend_source") != "vendored_nissy_core_h48":
        reasons.append("metadata backend_source is not vendored_nissy_core_h48")
    if metadata.get("license") != "GPL-3.0-or-later":
        reasons.append("metadata license is not GPL-3.0-or-later")
    expected_checksum = str(metadata.get("checksum_sha256", "")).lower()
    if len(expected_checksum) != 64 or any(char not in "0123456789abcdef" for char in expected_checksum):
        reasons.append("metadata checksum_sha256 is missing or malformed")
        actual_checksum = None
        checksum_source = None
    else:
        if prevalidated_checksum_sha256 and table_path.exists():
            actual_checksum = prevalidated_checksum_sha256.lower()
            checksum_source = "prevalidated_split_manifest_assembly"
        else:
            actual_checksum = sha256_file(table_path) if table_path.exists() else None
            checksum_source = "source_file_sha256"
        if actual_checksum != expected_checksum:
            reasons.append("source table checksum does not match metadata checksum_sha256")
    details = {
        "source_table_path": str(table_path),
        "source_metadata_path": str(metadata_path),
        "expected_size_bytes": expected_size,
        "actual_size_bytes": actual_size,
        "expected_checksum_sha256": expected_checksum,
        "actual_checksum_sha256": actual_checksum,
        "checksum_source": checksum_source,
    }
    return not reasons, reasons, details


def install_h48_table_bundle(
    *,
    root: Path,
    profile: str,
    seed: int,
    solver: str,
    bundle: Path | None = None,
    table_path: Path | None = None,
    metadata_path: Path | None = None,
    artifact_suffix: str = "bundle",
    force: bool = False,
) -> tuple[dict[str, Any], Path]:
    canonical_solver = h48_tables.canonical_h48_solver(solver)
    root = root.resolve()
    (root / "tmp").mkdir(parents=True, exist_ok=True)
    output = _artifact_output_path(
        root=root,
        profile=profile,
        seed=seed,
        solver=canonical_solver,
        artifact_suffix=artifact_suffix,
    )
    target_table = h48_tables.h48_table_path(
        root=root,
        profile=profile,
        seed=seed,
        solver=canonical_solver,
    )
    target_metadata = h48_tables.h48_metadata_path(
        root=root,
        profile=profile,
        seed=seed,
        solver=canonical_solver,
    )

    existing_ok, existing_message = (
        h48_tables.validate_trusted_h48_table(
            root=root,
            profile=profile,
            seed=seed,
            solver=canonical_solver,
            table_path=target_table,
        )
        if target_table.exists() and target_metadata.exists()
        else (False, "missing existing target table or metadata")
    )
    if existing_ok and not force:
        checksum_ok, checksum_message, checksum_details = h48_tables.validate_trusted_h48_table_checksum(
            root=root,
            profile=profile,
            seed=seed,
            solver=canonical_solver,
            table_path=target_table,
            use_cache=False,
            persistent_cache=True,
        )
        if checksum_ok:
            payload: dict[str, Any] = {
                "schema_version": 1,
                "created_at_utc": datetime.now(UTC).isoformat(),
                "profile": profile,
                "seed": seed,
                "solver": canonical_solver,
                "artifact_suffix": artifact_suffix,
                "bundle_path": str(bundle) if bundle else None,
                "source_table_path": str(table_path) if table_path else None,
                "source_metadata_path": str(metadata_path) if metadata_path else None,
                "target_table_path": _relative(root, target_table),
                "target_metadata_path": _relative(root, target_metadata),
                "source_validation_passed": None,
                "source_validation_skipped": True,
                "source_validation_skip_reason": (
                    "canonical target table already has trusted metadata and full checksum validation"
                ),
                "source_validation_reasons": [],
                "source_validation_details": {},
                "existing_target_trusted_before_install": existing_ok,
                "existing_target_message": existing_message,
                "existing_target_full_checksum_valid_before_install": checksum_ok,
                "existing_target_full_checksum_message": checksum_message,
                "existing_target_full_checksum_details": checksum_details,
                "target_table_already_installed": True,
                "copied_table": False,
                "table_install_method": None,
                "table_install_details": {},
                "status": "target_table_already_trusted",
                "post_install_full_checksum_valid": checksum_ok,
                "post_install_message": checksum_message,
                "post_install_details": checksum_details,
                "passed": True,
                "fast_runtime_proven_for_every_possible_state": False,
                "notes": (
                    "Skipped source bundle resolution because the canonical H48 target table already "
                    "passed trusted metadata and full checksum validation. This avoids repeated "
                    "multi-GiB install/hash work during proof-host resume, but the fast every-state "
                    "oracle claim still requires the hard-tail runtime workloads and regenerated "
                    "contract to pass."
                ),
            }
            write_json(output, payload)
            return payload, output

    tempdir: tempfile.TemporaryDirectory[str] | None = None
    try:
        source_table, source_metadata, tempdir, bundle_resolution_details = _resolve_bundle_inputs(
            root=root,
            profile=profile,
            seed=seed,
            solver=canonical_solver,
            bundle=bundle,
            table_path=table_path,
            metadata_path=metadata_path,
        )
        metadata = _load_metadata(source_metadata)
        source_ok, source_reasons, source_details = _validate_source(
            table_path=source_table,
            metadata_path=source_metadata,
            metadata=metadata,
            profile=profile,
            seed=seed,
            solver=canonical_solver,
            prevalidated_checksum_sha256=bundle_resolution_details.get("assembled_checksum_sha256"),
        )

        status = "source_validation_failed"
        copied = False
        if source_ok:
            if existing_ok and not force:
                status = "target_table_already_trusted"
            else:
                target_table.parent.mkdir(parents=True, exist_ok=True)
                target_metadata.parent.mkdir(parents=True, exist_ok=True)
                staged_table = h48_tables.staged_h48_table_path(target_table)
                if staged_table.exists():
                    staged_table.unlink()
                table_install_method, table_install_details = _stage_table_file(
                    source_table=source_table,
                    staged_table=staged_table,
                    tempdir=tempdir,
                )
                if staged_table.stat().st_size != source_details["expected_size_bytes"]:
                    staged_table.unlink()
                    raise RuntimeError("copied H48 table changed size during staging")
                staged_table.replace(target_table)
                normalized_metadata = dict(metadata)
                normalized_metadata.update(
                    {
                        "file_path": _relative(root, target_table),
                        "table_size_bytes": target_table.stat().st_size,
                        "estimated_table_size_bytes": h48_tables.estimated_h48_table_size_bytes(
                            canonical_solver
                        ),
                        "estimated_size_matches_actual": True,
                        "imported_at_utc": datetime.now(UTC).isoformat(),
                        "imported_from_table": str(source_table),
                        "imported_from_metadata": str(source_metadata),
                        "import_status": "installed_from_bundle",
                    }
                )
                write_json(target_metadata, normalized_metadata)
                copied = True
                status = "installed_from_bundle"
        checksum_ok, checksum_message, checksum_details = (
            h48_tables.validate_trusted_h48_table_checksum(
                root=root,
                profile=profile,
                seed=seed,
                solver=canonical_solver,
                table_path=target_table,
                use_cache=False,
                persistent_cache=True,
            )
            if status in {"installed_from_bundle", "target_table_already_trusted"}
            else (False, "source validation failed before target validation", {})
        )
        passed = status in {"installed_from_bundle", "target_table_already_trusted"} and checksum_ok
        payload: dict[str, Any] = {
            "schema_version": 1,
            "created_at_utc": datetime.now(UTC).isoformat(),
            "profile": profile,
            "seed": seed,
            "solver": canonical_solver,
            "artifact_suffix": artifact_suffix,
            "bundle_path": str(bundle) if bundle else None,
            "source_table_path": str(source_table),
            "source_metadata_path": str(source_metadata),
            "bundle_resolution_details": bundle_resolution_details,
            "target_table_path": _relative(root, target_table),
            "target_metadata_path": _relative(root, target_metadata),
            "source_validation_passed": source_ok,
            "source_validation_reasons": source_reasons,
            "source_validation_details": source_details,
            "existing_target_trusted_before_install": existing_ok,
            "existing_target_message": existing_message,
            "source_validation_skipped": False,
            "target_table_already_installed": status == "target_table_already_trusted",
            "copied_table": copied,
            "table_install_method": table_install_method if copied else None,
            "table_install_details": table_install_details if copied else {},
            "status": status,
            "post_install_full_checksum_valid": checksum_ok,
            "post_install_message": checksum_message,
            "post_install_details": checksum_details,
            "passed": passed,
            "fast_runtime_proven_for_every_possible_state": False,
            "notes": (
                "Validated H48 table import path. This can make a generated H48 table reusable on another "
                "machine, but the fast every-state oracle claim still requires the hard-tail runtime workloads "
                "and regenerated contract to pass."
            ),
        }
    finally:
        if tempdir is not None:
            tempdir.cleanup()

    write_json(output, payload)
    return payload, output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default="thesis")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--solver", required=True)
    parser.add_argument("--bundle", type=Path, default=None)
    parser.add_argument("--table", type=Path, default=None)
    parser.add_argument("--metadata", type=Path, default=None)
    parser.add_argument("--artifact-suffix", default="bundle")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()

    payload, output = install_h48_table_bundle(
        root=args.root,
        profile=args.profile,
        seed=args.seed,
        solver=args.solver,
        bundle=args.bundle,
        table_path=args.table,
        metadata_path=args.metadata,
        artifact_suffix=args.artifact_suffix,
        force=args.force,
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "solver": payload["solver"],
                "status": payload["status"],
                "passed": payload["passed"],
                "post_install_full_checksum_valid": payload["post_install_full_checksum_valid"],
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

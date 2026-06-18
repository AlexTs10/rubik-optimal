#!/usr/bin/env python
"""Run a local end-to-end smoke for split H48 table bundles."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rubik_optimal.results import write_json  # noqa: E402
from rubik_optimal.tables import h48 as h48_tables  # noqa: E402
from scripts.create_h48_table_bundle import (  # noqa: E402
    MANIFEST_NAME,
    create_h48_table_bundle,
)
from scripts.install_h48_table_bundle import install_h48_table_bundle  # noqa: E402


DEFAULT_PART_SIZE_MIB = 8


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
        / f"h48_split_bundle_smoke_{'_'.join(str(part) for part in suffix_parts)}.json"
    )


def _default_bundle_dir(
    *,
    root: Path,
    profile: str,
    seed: int,
    solver: str,
    artifact_suffix: str,
) -> Path:
    return (
        root
        / "results"
        / f"h48_split_bundle_smoke_seed_{seed}_{profile}_{solver}_{artifact_suffix}_parts"
    )


def _default_install_root(
    *,
    root: Path,
    profile: str,
    seed: int,
    solver: str,
    artifact_suffix: str,
) -> Path:
    return (
        root
        / "results"
        / f"h48_split_bundle_smoke_seed_{seed}_{profile}_{solver}_{artifact_suffix}_install_root"
    )


def _safe_generated_dir(root: Path, path: Path, label: str) -> Path:
    resolved_root = root.resolve()
    resolved_path = path.resolve()
    generated_results = (resolved_root / "results").resolve()
    generated_tmp = (resolved_root / "tmp").resolve()
    if not (
        resolved_path.is_relative_to(generated_results)
        or resolved_path.is_relative_to(generated_tmp)
    ):
        raise ValueError(f"{label} must live under results/ or tmp/: {path}")
    if resolved_path == generated_results or resolved_path == generated_tmp:
        raise ValueError(f"{label} must not be the whole generated root: {path}")
    return resolved_path


def _clean_dir(root: Path, path: Path, label: str) -> None:
    safe_path = _safe_generated_dir(root, path, label)
    if safe_path.exists():
        shutil.rmtree(safe_path)


def _load_json_or_empty(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def run_h48_split_bundle_smoke(
    *,
    root: Path,
    profile: str = "thesis",
    seed: int = 2026,
    solver: str = "h48h0",
    bundle_dir: Path | None = None,
    install_root: Path | None = None,
    part_size_bytes: int = DEFAULT_PART_SIZE_MIB * 1024 * 1024,
    artifact_suffix: str = "local",
    clean: bool = True,
) -> tuple[dict[str, Any], Path]:
    """Create and install a real split bundle in an isolated generated root."""

    started = time.perf_counter()
    root = root.resolve()
    canonical_solver = h48_tables.canonical_h48_solver(solver)
    if part_size_bytes <= 0:
        raise ValueError("part_size_bytes must be positive")

    selected_bundle_dir = bundle_dir or _default_bundle_dir(
        root=root,
        profile=profile,
        seed=seed,
        solver=canonical_solver,
        artifact_suffix=artifact_suffix,
    )
    selected_install_root = install_root or _default_install_root(
        root=root,
        profile=profile,
        seed=seed,
        solver=canonical_solver,
        artifact_suffix=artifact_suffix,
    )
    if not selected_bundle_dir.is_absolute():
        selected_bundle_dir = root / selected_bundle_dir
    if not selected_install_root.is_absolute():
        selected_install_root = root / selected_install_root

    output = _artifact_output_path(
        root=root,
        profile=profile,
        seed=seed,
        solver=canonical_solver,
        artifact_suffix=artifact_suffix,
    )
    source_table = h48_tables.h48_table_path(
        root=root,
        profile=profile,
        seed=seed,
        solver=canonical_solver,
    )
    source_metadata = h48_tables.h48_metadata_path(
        root=root,
        profile=profile,
        seed=seed,
        solver=canonical_solver,
    )
    bundle_payload: dict[str, Any] = {}
    install_payload: dict[str, Any] = {}
    bundle_output: Path | None = None
    install_output: Path | None = None
    error: str | None = None

    try:
        _safe_generated_dir(root, selected_bundle_dir, "bundle_dir")
        _safe_generated_dir(root, selected_install_root, "install_root")
        if clean:
            _clean_dir(root, selected_bundle_dir, "bundle_dir")
            _clean_dir(root, selected_install_root, "install_root")

        bundle_payload, bundle_output = create_h48_table_bundle(
            root=root,
            profile=profile,
            seed=seed,
            solver=canonical_solver,
            output_dir=selected_bundle_dir,
            part_size_bytes=part_size_bytes,
            artifact_suffix=f"{artifact_suffix}_source",
            force=clean,
        )
        if bundle_payload.get("passed") is True:
            install_payload, install_output = install_h48_table_bundle(
                root=selected_install_root,
                profile=profile,
                seed=seed,
                solver=canonical_solver,
                bundle=selected_bundle_dir,
                artifact_suffix=f"{artifact_suffix}_install",
                force=True,
            )
    except Exception as exc:  # pragma: no cover - exercised through CLI failure artifacts.
        error = f"{type(exc).__name__}: {exc}"

    manifest_path = selected_bundle_dir / MANIFEST_NAME
    manifest_payload = _load_json_or_empty(manifest_path)
    installed_table = h48_tables.h48_table_path(
        root=selected_install_root,
        profile=profile,
        seed=seed,
        solver=canonical_solver,
    )
    installed_metadata = h48_tables.h48_metadata_path(
        root=selected_install_root,
        profile=profile,
        seed=seed,
        solver=canonical_solver,
    )
    bundle_resolution = install_payload.get("bundle_resolution_details") or {}
    post_details = install_payload.get("post_install_details") or {}
    source_details = bundle_payload.get("source_full_checksum_details") or {}
    source_checksum = str(bundle_payload.get("table_checksum_sha256") or "").lower()
    installed_checksum = str(post_details.get("actual_checksum_sha256") or "").lower()
    expected_size = h48_tables.estimated_h48_table_size_bytes(canonical_solver)
    source_size = source_table.stat().st_size if source_table.exists() else None
    installed_size = installed_table.stat().st_size if installed_table.exists() else None
    part_count = int(bundle_payload.get("part_count") or 0)
    h_value = h48_tables.h48_solver_h_value(canonical_solver)
    oracle_grade = h_value >= h48_tables.h48_solver_h_value(h48_tables.ORACLE_H48_SOLVER)

    passed = (
        error is None
        and bundle_payload.get("passed") is True
        and install_payload.get("passed") is True
        and bundle_payload.get("source_full_checksum_valid") is True
        and manifest_payload.get("bundle_kind") == "h48_split_table_bundle"
        and manifest_payload.get("solver") == canonical_solver
        and part_count > 1
        and int(manifest_payload.get("part_count") or 0) == part_count
        and bundle_resolution.get("bundle_resolution_kind") == "split_manifest"
        and bundle_resolution.get("parts_validated") is True
        and install_payload.get("status") == "installed_from_bundle"
        and install_payload.get("post_install_full_checksum_valid") is True
        and installed_table.exists()
        and installed_metadata.exists()
        and installed_size == expected_size
        and bool(source_checksum)
        and installed_checksum == source_checksum
    )

    payload: dict[str, Any] = {
        "schema_version": 1,
        "artifact_kind": "h48_split_bundle_smoke",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "profile": profile,
        "seed": seed,
        "solver": canonical_solver,
        "h_value": h_value,
        "oracle_grade": oracle_grade,
        "artifact_suffix": artifact_suffix,
        "source_table_path": _relative(root, source_table),
        "source_metadata_path": _relative(root, source_metadata),
        "source_table_size_bytes": source_size,
        "bundle_dir": _relative(root, selected_bundle_dir),
        "bundle_manifest_path": _relative(root, manifest_path),
        "bundle_artifact_path": _relative(root, bundle_output) if bundle_output else None,
        "install_root": _relative(root, selected_install_root),
        "install_artifact_path": _relative(root, install_output) if install_output else None,
        "installed_table_path": _relative(root, installed_table),
        "installed_metadata_path": _relative(root, installed_metadata),
        "part_size_bytes": part_size_bytes,
        "bundle_part_count": part_count,
        "bundle_written_part_count": bundle_payload.get("split_written_part_count"),
        "bundle_reused_part_count": bundle_payload.get("split_reused_part_count"),
        "source_full_checksum_valid": bundle_payload.get("source_full_checksum_valid"),
        "source_checksum_persistent_cache_hit": source_details.get("checksum_persistent_cache_hit"),
        "split_manifest_validated": bundle_resolution.get("bundle_resolution_kind")
        == "split_manifest",
        "split_parts_validated": bundle_resolution.get("parts_validated") is True,
        "installed_from_split_manifest": install_payload.get("status") == "installed_from_bundle",
        "installed_table_size_bytes": installed_size,
        "expected_table_size_bytes": expected_size,
        "installed_checksum_sha256": installed_checksum or None,
        "source_checksum_sha256": source_checksum or None,
        "post_install_full_checksum_valid": install_payload.get("post_install_full_checksum_valid"),
        "post_install_checksum_runtime_seconds": post_details.get("checksum_runtime_seconds"),
        "isolated_install_root_preserved": selected_install_root.exists(),
        "cleaned_before_run": clean,
        "error": error,
        "runtime_seconds": round(time.perf_counter() - started, 6),
        "passed": passed,
        "fast_runtime_proven_for_every_possible_state": False,
        "claim_scope": (
            "Local transfer/install smoke for a trusted H48 table split into checksummed parts. "
            "This proves split-bundle assembly and full installed checksum validation for the selected "
            "table; it is not H48H10 generation evidence and not every-state runtime proof."
        ),
    }
    write_json(output, payload)
    return payload, output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default="thesis")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--solver", default="h48h0")
    parser.add_argument("--bundle-dir", type=Path, default=None)
    parser.add_argument("--install-root", type=Path, default=None)
    parser.add_argument("--part-size-mib", type=int, default=DEFAULT_PART_SIZE_MIB)
    parser.add_argument("--part-size-bytes", type=int, default=None)
    parser.add_argument("--artifact-suffix", default="local")
    parser.add_argument("--reuse-existing", action="store_true")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()

    part_size_bytes = (
        args.part_size_bytes
        if args.part_size_bytes is not None
        else args.part_size_mib * 1024 * 1024
    )
    payload, output = run_h48_split_bundle_smoke(
        root=args.root,
        profile=args.profile,
        seed=args.seed,
        solver=args.solver,
        bundle_dir=args.bundle_dir,
        install_root=args.install_root,
        part_size_bytes=part_size_bytes,
        artifact_suffix=args.artifact_suffix,
        clean=not args.reuse_existing,
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "solver": payload["solver"],
                "bundle_part_count": payload["bundle_part_count"],
                "post_install_full_checksum_valid": payload["post_install_full_checksum_valid"],
                "passed": payload["passed"],
                "fast_runtime_proven_for_every_possible_state": payload[
                    "fast_runtime_proven_for_every_possible_state"
                ],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

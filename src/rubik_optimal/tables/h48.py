"""Native H48 table generation helpers.

The backend wraps a vendored snapshot of nissy-core's H48 implementation.
Generated tables are stored under data/generated with checksums and metadata so
they can be cited by the thesis and verified by scripts.
"""

from __future__ import annotations

from copy import deepcopy
import json
import os
import platform
import re
import subprocess
import time
from datetime import UTC, datetime
from math import comb
from pathlib import Path

from rubik_optimal.results import write_json
from rubik_optimal.source_state import capture_source_state
from rubik_optimal.tables.metadata import sha256_file

NISSY_CORE_COMMIT = "3cb60bcbf4ab9af4e9452a43681f1e7176b0c88f"
NISSY_CORE_SOURCE_URL = "https://git.tronto.net/nissy-core"
DEFAULT_H48_SOLVER = "h48h0"
ORACLE_H48_SOLVER = "h48h7"
H48_OPTIMAL_ALIAS = "optimal"
H48_AUTO_SOLVER = "auto"
H48_FASTEST_SOLVER = "fastest"
H48_GENERATOR = "native/h48_backend/h48_backend.c"
H48_TABLE_ROOT_ENV = "RUBIK_OPTIMAL_H48_TABLE_ROOT"
DEFAULT_H48_GENDATA_WORKBATCH = 256
H48_MMAP_SYNC_MODES = frozenset({"sync", "async", "none"})
_H48_BACKEND_EXTRA_CFLAG_ALLOWLIST = frozenset(
    {"-flto", "-fno-plt", "-fomit-frame-pointer", "-funroll-loops", "-pipe"}
)
_H48_BACKEND_EXTRA_CFLAG_PREFIXES = ("-march=", "-mcpu=", "-mtune=")
_INFOSIZE = 512
_COCSEP_CLASSES = 3393
_COCSEP_TABLESIZE = (3**7) << 7
_COCSEP_FULLSIZE = _INFOSIZE + 4 * _COCSEP_TABLESIZE
_ESEP_MAX = comb(12, 4) * comb(8, 4)
_EOESEP_TABLESIZE = 782 << 11
_EOESEP_BUF = (_EOESEP_TABLESIZE + 1) // 2
_EOESEP_FULLSIZE = _INFOSIZE + _EOESEP_BUF + 4 * _ESEP_MAX
_H48_COORDMAX_NOEO = _COCSEP_CLASSES * _ESEP_MAX
_H48_LINE_COORDS = (512 - 4) // 2
_H48_LINE_BYTES = 512 // 8
_H48_SOLVER_RE = re.compile(r"^h48h(?P<h>\d{1,2})$")
_H48_FULL_CHECKSUM_CACHE: dict[
    tuple[str, int, int, str, int, int, str],
    tuple[bool, str, dict[str, object]],
] = {}
_H48_CHECKSUM_CERTIFICATE_KIND = "h48_full_checksum_validation_certificate"
_H48_ADOPTION_CANARY_CUBE = "CEIVLBWH=DFCIBAGLJHKE=A"
_H48_ADOPTION_CANARY_EXPECTED_DISTANCE = 3


def h48_solver_h_value(solver: str) -> int:
    """Return the H48 h-value encoded by a nissy solver name."""

    if solver == H48_OPTIMAL_ALIAS:
        return 7
    match = _H48_SOLVER_RE.match(solver)
    if not match:
        raise ValueError(f"unsupported H48 solver name: {solver}")
    value = int(match.group("h"))
    if not 0 <= value <= 11:
        raise ValueError(f"H48 solver h-value must be in [0, 11], got {value}")
    return value


def canonical_h48_solver(solver: str) -> str:
    """Return the concrete h48hN name for aliases used by nissy-core."""

    return f"h48h{h48_solver_h_value(solver)}"


def normalize_h48_mmap_sync_mode(mode: str) -> str:
    normalized = str(mode).strip().lower()
    if normalized not in H48_MMAP_SYNC_MODES:
        raise ValueError(
            f"unsupported H48 mmap sync mode: {mode!r}; "
            f"expected one of {', '.join(sorted(H48_MMAP_SYNC_MODES))}"
        )
    return normalized


def normalize_h48_backend_extra_cflags(flags: list[str] | tuple[str, ...] | None = None) -> tuple[str, ...]:
    """Return audited extra compiler flags for native H48 proof builds."""

    normalized: list[str] = []
    for raw_flag in flags or ():
        flag = str(raw_flag).strip()
        if not flag:
            continue
        allowed = flag in _H48_BACKEND_EXTRA_CFLAG_ALLOWLIST or any(
            flag.startswith(prefix) for prefix in _H48_BACKEND_EXTRA_CFLAG_PREFIXES
        )
        if not allowed:
            raise ValueError(
                f"unsupported H48 backend extra compiler flag: {flag!r}; "
                "allowed flags are CPU tuning/LTO flags only"
            )
        normalized.append(flag)
    return tuple(normalized)


def estimated_h48_table_size_bytes(solver: str) -> int:
    """Return the exact nissy-core H48 table byte size for this h-value."""

    h_value = h48_solver_h_value(solver)
    coord_count = _H48_COORDMAX_NOEO << h_value
    h48_lines = (coord_count + _H48_LINE_COORDS - 1) // _H48_LINE_COORDS
    h48_table_size = _H48_LINE_BYTES * h48_lines
    return _COCSEP_FULLSIZE + _INFOSIZE + h48_table_size + _EOESEP_FULLSIZE


def repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def h48_vendor_root(root: Path | None = None) -> Path:
    root = root or repository_root()
    return root / "native" / "h48_backend" / "third_party" / "nissy_core"


def h48_binary_path(root: Path | None = None) -> Path:
    root = root or repository_root()
    return root / "native" / "build" / "h48_backend"


def h48_table_root(root: Path | None = None) -> Path:
    """Return the configured root directory for generated H48 table bytes."""

    root = root or repository_root()
    configured = os.environ.get(H48_TABLE_ROOT_ENV)
    if configured:
        path = Path(configured).expanduser()
        return path if path.is_absolute() else root / path
    return root / "data" / "generated" / "h48"


def h48_table_path(
    *,
    root: Path | None = None,
    profile: str = "thesis",
    seed: int = 2026,
    solver: str = DEFAULT_H48_SOLVER,
) -> Path:
    root = root or repository_root()
    solver = canonical_h48_solver(solver)
    return h48_table_root(root=root) / f"{profile}_seed_{seed}" / f"{solver}.bin"


def h48_metadata_path(
    *,
    root: Path | None = None,
    profile: str = "thesis",
    seed: int = 2026,
    solver: str = DEFAULT_H48_SOLVER,
) -> Path:
    root = root or repository_root()
    solver = canonical_h48_solver(solver)
    return root / "results" / "processed" / f"h48_metadata_seed_{seed}_{profile}_{solver}.json"


def h48_checksum_certificate_path(
    *,
    root: Path | None = None,
    profile: str = "thesis",
    seed: int = 2026,
    solver: str = DEFAULT_H48_SOLVER,
) -> Path:
    """Return the persistent full-checksum certificate path for a trusted H48 table."""

    root = root or repository_root()
    solver = canonical_h48_solver(solver)
    return root / "results" / "processed" / f"h48_checksum_certificate_seed_{seed}_{profile}_{solver}.json"


def staged_h48_table_path(table_path: Path) -> Path:
    """Return the temporary path used before atomically publishing a table."""

    return table_path.with_name(f".{table_path.name}.partial")


def _relative_or_absolute(root: Path, path: Path) -> str:
    return str(path.relative_to(root)) if path.is_relative_to(root) else str(path)


def _file_identity(root: Path, path: Path) -> dict[str, object]:
    stat = path.stat()
    return {
        "path": _relative_or_absolute(root, path),
        "resolved_path": str(path.resolve()),
        "size_bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "ctime_ns": int(stat.st_ctime_ns),
        "inode": int(getattr(stat, "st_ino", 0)),
        "device": int(getattr(stat, "st_dev", 0)),
    }


def _checksum_certificate_identity(
    *,
    root: Path,
    profile: str,
    seed: int,
    solver: str,
    table_path: Path,
    metadata_path: Path,
    expected_checksum: str,
) -> dict[str, object]:
    return {
        "certificate_kind": _H48_CHECKSUM_CERTIFICATE_KIND,
        "profile": profile,
        "seed": int(seed),
        "solver": canonical_h48_solver(solver),
        "expected_checksum_sha256": expected_checksum.lower(),
        "table": _file_identity(root, table_path),
        "metadata": _file_identity(root, metadata_path),
    }


def _load_matching_h48_checksum_certificate(
    certificate_path: Path,
    *,
    expected_identity: dict[str, object],
) -> tuple[bool, dict[str, object], str]:
    if not certificate_path.exists():
        return False, {}, "missing checksum certificate"
    try:
        payload = json.loads(certificate_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return False, {}, f"invalid checksum certificate: {exc}"
    if not isinstance(payload, dict):
        return False, {}, "checksum certificate is not a JSON object"
    if payload.get("certificate_kind") != _H48_CHECKSUM_CERTIFICATE_KIND:
        return False, payload, "checksum certificate kind mismatch"
    if payload.get("identity") != expected_identity:
        return False, payload, "checksum certificate identity mismatch"
    expected_checksum = str(expected_identity.get("expected_checksum_sha256") or "").lower()
    if payload.get("full_checksum_valid") is not True:
        return False, payload, "checksum certificate is not a valid-pass certificate"
    if str(payload.get("actual_checksum_sha256") or "").lower() != expected_checksum:
        return False, payload, "checksum certificate actual checksum mismatch"
    return True, payload, "checksum certificate identity validated"


def _write_h48_checksum_certificate(
    certificate_path: Path,
    *,
    identity: dict[str, object],
    actual_checksum: str,
    checksum_runtime_seconds: float,
) -> None:
    certificate_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "certificate_kind": _H48_CHECKSUM_CERTIFICATE_KIND,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "identity": identity,
        "actual_checksum_sha256": actual_checksum.lower(),
        "full_checksum_valid": True,
        "checksum_runtime_seconds": round(checksum_runtime_seconds, 6),
        "reuse_policy": (
            "Reusable only while the canonical table and metadata file identities exactly match "
            "the recorded paths, sizes, mtimes, ctimes, inodes, devices, and expected checksum."
        ),
    }
    tmp_path = certificate_path.with_suffix(certificate_path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp_path, certificate_path)


def validate_trusted_h48_table(
    *,
    root: Path | None = None,
    profile: str = "thesis",
    seed: int = 2026,
    solver: str = DEFAULT_H48_SOLVER,
    table_path: Path | None = None,
) -> tuple[bool, str]:
    """Validate the metadata contract for fast trusted H48 table use.

    This intentionally avoids recomputing the full SHA-256 digest on every
    solve. Full checksum verification is handled by ``scripts/verify_results.py``.
    The fast path checks the generated metadata, canonical table path, table
    size, expected-size match, backend identity, and recorded checksum shape
    before allowing the native distribution scan to be skipped.
    """

    root = root or repository_root()
    solver = canonical_h48_solver(solver)
    expected_table_path = h48_table_path(root=root, profile=profile, seed=seed, solver=solver)
    selected_table_path = table_path or expected_table_path
    if selected_table_path.resolve() != expected_table_path.resolve():
        return False, "trusted H48 mode requires the canonical generated table path"
    metadata_path = h48_metadata_path(root=root, profile=profile, seed=seed, solver=solver)
    if not metadata_path.exists():
        return False, f"missing trusted H48 metadata: {metadata_path}"
    if not selected_table_path.exists():
        return False, f"missing trusted H48 table: {selected_table_path}"
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False, f"invalid trusted H48 metadata JSON: {metadata_path}"
    recorded_table_path = _relative_or_absolute(root, selected_table_path)
    checksum = str(metadata.get("checksum_sha256", ""))
    if metadata.get("table_kind") != "h48_pruning_table":
        return False, "trusted H48 metadata has unexpected table_kind"
    if metadata.get("backend_source") != "vendored_nissy_core_h48":
        return False, "trusted H48 metadata has unexpected backend_source"
    if metadata.get("solver") != solver:
        return False, f"trusted H48 metadata solver mismatch: {metadata.get('solver')} != {solver}"
    if metadata.get("file_path") != recorded_table_path:
        return False, "trusted H48 metadata file_path does not match selected table"
    actual_size = selected_table_path.stat().st_size
    computed_size = estimated_h48_table_size_bytes(solver)
    if int(metadata.get("table_size_bytes", -1)) != actual_size:
        return False, "trusted H48 metadata table size does not match selected table"
    if int(metadata.get("estimated_table_size_bytes", computed_size)) != actual_size:
        return False, "trusted H48 metadata estimated size does not match selected table"
    if metadata.get("estimated_size_matches_actual", actual_size == computed_size) is not True:
        return False, "trusted H48 metadata does not confirm estimated size match"
    if computed_size != actual_size:
        return False, "trusted H48 computed expected size does not match selected table"
    if len(checksum) != 64 or any(char not in "0123456789abcdef" for char in checksum.lower()):
        return False, "trusted H48 metadata checksum is missing or malformed"
    return True, f"trusted H48 metadata validated without per-call checksum scan: {metadata_path}"


def validate_trusted_h48_table_checksum(
    *,
    root: Path | None = None,
    profile: str = "thesis",
    seed: int = 2026,
    solver: str = DEFAULT_H48_SOLVER,
    table_path: Path | None = None,
    use_cache: bool = True,
    persistent_cache: bool = False,
    certificate_path: Path | None = None,
) -> tuple[bool, str, dict[str, object]]:
    """Validate trusted H48 metadata and the full table checksum.

    The normal trusted-table solve path intentionally avoids hashing multi-GiB
    H48 tables on every call.  Cloud hard-tail proof workers need a stronger
    preflight: after a generated table is copied to a worker, verify that the
    actual table bytes match the metadata checksum before starting expensive
    exact-search workloads.  A process-local cache avoids re-reading the same
    unchanged table for later workloads in one campaign run.  The optional
    persistent certificate gives separate worker/status processes the same
    shortcut, but only when the table and metadata identities exactly match the
    previously validated expected checksum.
    """

    root = root or repository_root()
    solver = canonical_h48_solver(solver)
    selected_table_path = table_path or h48_table_path(
        root=root,
        profile=profile,
        seed=seed,
        solver=solver,
    )
    metadata_path = h48_metadata_path(root=root, profile=profile, seed=seed, solver=solver)
    trusted_ok, trusted_message = validate_trusted_h48_table(
        root=root,
        profile=profile,
        seed=seed,
        solver=solver,
        table_path=selected_table_path,
    )
    details: dict[str, object] = {
        "solver": solver,
        "profile": profile,
        "seed": seed,
        "table_path": str(selected_table_path.relative_to(root))
        if selected_table_path.is_relative_to(root)
        else str(selected_table_path),
        "metadata_path": str(metadata_path.relative_to(root))
        if metadata_path.is_relative_to(root)
        else str(metadata_path),
        "trusted_metadata_valid": trusted_ok,
        "full_checksum_valid": False,
        "checksum_cache_hit": False,
        "checksum_persistent_cache_hit": False,
    }
    if not trusted_ok:
        return False, trusted_message, details

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    expected_checksum = str(metadata.get("checksum_sha256", "")).lower()
    table_stat = selected_table_path.stat()
    metadata_stat = metadata_path.stat()
    selected_certificate_path = certificate_path or h48_checksum_certificate_path(
        root=root,
        profile=profile,
        seed=seed,
        solver=solver,
    )
    certificate_identity = _checksum_certificate_identity(
        root=root,
        profile=profile,
        seed=seed,
        solver=solver,
        table_path=selected_table_path,
        metadata_path=metadata_path,
        expected_checksum=expected_checksum,
    )
    details.update(
        {
            "expected_checksum_sha256": expected_checksum,
            "table_size_bytes": table_stat.st_size,
            "checksum_certificate_path": str(selected_certificate_path.relative_to(root))
            if selected_certificate_path.is_relative_to(root)
            else str(selected_certificate_path),
            "checksum_persistent_cache_enabled": persistent_cache,
        }
    )
    cache_key = (
        str(selected_table_path.resolve()),
        int(table_stat.st_size),
        int(table_stat.st_mtime_ns),
        str(metadata_path.resolve()),
        int(metadata_stat.st_size),
        int(metadata_stat.st_mtime_ns),
        expected_checksum,
    )
    if use_cache and cache_key in _H48_FULL_CHECKSUM_CACHE:
        cached_ok, cached_message, cached_details = _H48_FULL_CHECKSUM_CACHE[cache_key]
        return (
            cached_ok,
            cached_message,
            {**cached_details, "checksum_cache_hit": True},
        )

    if persistent_cache:
        certificate_ok, certificate_payload, certificate_message = _load_matching_h48_checksum_certificate(
            selected_certificate_path,
            expected_identity=certificate_identity,
        )
        details.update(
            {
                "checksum_certificate_present": bool(certificate_payload) or selected_certificate_path.exists(),
                "checksum_certificate_message": certificate_message,
            }
        )
        if certificate_ok:
            certified_runtime = certificate_payload.get("checksum_runtime_seconds")
            details.update(
                {
                    "actual_checksum_sha256": expected_checksum,
                    "full_checksum_valid": True,
                    "checksum_persistent_cache_hit": True,
                    "checksum_runtime_seconds": certified_runtime,
                    "checksum_certificate_created_at_utc": certificate_payload.get("created_at_utc"),
                }
            )
            message = f"trusted H48 full checksum certificate reused: {selected_certificate_path}"
            result = (True, message, details)
            if use_cache:
                _H48_FULL_CHECKSUM_CACHE[cache_key] = (True, message, deepcopy(details))
            return result

    begin = time.perf_counter()
    actual_checksum = sha256_file(selected_table_path).lower()
    runtime_seconds = time.perf_counter() - begin
    checksum_ok = actual_checksum == expected_checksum
    details.update(
        {
            "actual_checksum_sha256": actual_checksum,
            "full_checksum_valid": checksum_ok,
            "checksum_runtime_seconds": round(runtime_seconds, 6),
        }
    )
    if not checksum_ok:
        message = "trusted H48 full checksum mismatch"
        result = (False, message, details)
    else:
        if persistent_cache:
            _write_h48_checksum_certificate(
                selected_certificate_path,
                identity=certificate_identity,
                actual_checksum=actual_checksum,
                checksum_runtime_seconds=runtime_seconds,
            )
            details["checksum_certificate_written"] = True
        message = f"trusted H48 full checksum validated: {metadata_path}"
        result = (True, message, details)
    if use_cache:
        _H48_FULL_CHECKSUM_CACHE[cache_key] = result
    return result


def h48_table_inventory(
    *,
    root: Path | None = None,
    profile: str = "thesis",
    seed: int = 2026,
    min_h: int = 0,
    max_h: int = 11,
) -> list[dict[str, object]]:
    """Return local H48 table availability and trusted-metadata status."""

    root = root or repository_root()
    rows: list[dict[str, object]] = []
    for h_value in range(min_h, max_h + 1):
        solver = f"h48h{h_value}"
        table_path = h48_table_path(root=root, profile=profile, seed=seed, solver=solver)
        metadata_path = h48_metadata_path(root=root, profile=profile, seed=seed, solver=solver)
        table_exists = table_path.exists()
        metadata_exists = metadata_path.exists()
        trusted_ok = False
        trusted_message = "missing table or metadata"
        if table_exists and metadata_exists:
            trusted_ok, trusted_message = validate_trusted_h48_table(
                root=root,
                profile=profile,
                seed=seed,
                solver=solver,
                table_path=table_path,
            )
        rows.append(
            {
                "solver": solver,
                "h_value": h_value,
                "oracle_grade": h_value >= h48_solver_h_value(ORACLE_H48_SOLVER),
                "estimated_table_size_bytes": estimated_h48_table_size_bytes(solver),
                "table_path": _relative_or_absolute(root, table_path),
                "metadata_path": _relative_or_absolute(root, metadata_path),
                "table_exists": table_exists,
                "metadata_exists": metadata_exists,
                "trusted_metadata_valid": trusted_ok,
                "trusted_metadata_message": trusted_message,
                "actual_table_size_bytes": table_path.stat().st_size if table_exists else None,
            }
        )
    return rows


def highest_available_h48_solver(
    *,
    root: Path | None = None,
    profile: str = "thesis",
    seed: int = 2026,
    min_h: int = 7,
    max_h: int = 11,
    fallback: str = ORACLE_H48_SOLVER,
) -> str:
    """Return the strongest generated, trusted H48 solver for this profile."""

    rows = h48_table_inventory(
        root=root,
        profile=profile,
        seed=seed,
        min_h=min_h,
        max_h=max_h,
    )
    for row in sorted(rows, key=lambda item: int(item["h_value"]), reverse=True):
        if row["trusted_metadata_valid"] is True:
            return str(row["solver"])
    return canonical_h48_solver(fallback)


def resolve_h48_solver(
    solver: str,
    *,
    root: Path | None = None,
    profile: str = "thesis",
    seed: int = 2026,
    auto_min_h: int = 7,
) -> str:
    """Resolve aliases, including automatic strongest-local-table selection."""

    normalized = solver.strip().lower()
    if normalized in {H48_AUTO_SOLVER, H48_FASTEST_SOLVER, "best"}:
        return highest_available_h48_solver(
            root=root,
            profile=profile,
            seed=seed,
            min_h=auto_min_h,
        )
    return canonical_h48_solver(solver)


def _detect_arch() -> str:
    machine = platform.machine().lower()
    if machine in {"arm64", "aarch64"}:
        return "NEON"
    if machine in {"x86_64", "amd64"}:
        return "AVX2"
    return "PORTABLE"


def resolve_h48_gendata_workbatch(value: int | str | None = None) -> int:
    """Resolve the native H48 generator work-batch size.

    Large H48 tables can have highly uneven per-short-cube generation cost.
    Keeping the batch size explicit makes long local runs auditable and lets
    stronger-table campaigns trade a little scheduling overhead for better load
    balancing and more useful progress logs.
    """

    raw_value = value
    if raw_value is None:
        raw_value = os.environ.get("RUBIK_OPTIMAL_H48_GENDATA_WORKBATCH")
    if raw_value is None:
        raw_value = DEFAULT_H48_GENDATA_WORKBATCH
    try:
        parsed = int(str(raw_value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"H48 generator workbatch must be a positive integer, got {raw_value!r}") from exc
    if parsed < 1:
        raise ValueError(f"H48 generator workbatch must be a positive integer, got {parsed}")
    return parsed


def _run_h48_adoption_native_canary(
    *,
    root: Path,
    solver: str,
    table_path: Path,
    threads: int,
    gendata_workbatch: int | str | None = None,
    use_expected_distribution: bool = False,
    backend_extra_cflags: list[str] | tuple[str, ...] | None = None,
) -> dict[str, object]:
    """Require nissy-core table validation before adopting existing H48 bytes."""

    binary = build_h48_backend(
        root=root,
        threads=threads,
        gendata_workbatch=gendata_workbatch,
        use_expected_distribution=use_expected_distribution,
        extra_cflags=backend_extra_cflags,
    )
    command = [
        str(binary),
        "--solve",
        "--solver",
        solver,
        "--table",
        str(table_path),
        "--cube",
        _H48_ADOPTION_CANARY_CUBE,
        "--threads",
        str(max(1, threads)),
        "--max-depth",
        str(_H48_ADOPTION_CANARY_EXPECTED_DISTANCE),
    ]
    begin = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    runtime = time.perf_counter() - begin
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        payload = {
            "status": "failed",
            "error": (completed.stderr or "").strip() or completed.stdout.strip(),
        }
    status = str(payload.get("status") or "")
    table_check = str(payload.get("table_check") or "")
    solution_length = payload.get("solution_length")
    passed = (
        completed.returncode == 0
        and status == "exact"
        and table_check == "verified"
        and int(solution_length) == _H48_ADOPTION_CANARY_EXPECTED_DISTANCE
    )
    return {
        "passed": passed,
        "command": " ".join(command),
        "return_code": completed.returncode,
        "runtime_seconds": round(runtime, 6),
        "solver": solver,
        "table_path": _relative_or_absolute(root, table_path),
        "canary_cube": _H48_ADOPTION_CANARY_CUBE,
        "expected_solution_length": _H48_ADOPTION_CANARY_EXPECTED_DISTANCE,
        "native_payload": payload,
        "stderr_tail": "\n".join(completed.stderr.splitlines()[-20:]),
        "trust_boundary": (
            "This canary runs the native backend without --skip-table-check, so nissy_checkdata "
            "must accept the H48 table before metadata recovery can mark it as adopted."
        ),
    }


def build_h48_backend(
    *,
    root: Path | None = None,
    compiler: str = "cc",
    threads: int = 8,
    arch: str | None = None,
    gendata_workbatch: int | str | None = None,
    use_expected_distribution: bool = False,
    extra_cflags: list[str] | tuple[str, ...] | None = None,
) -> Path:
    """Compile the in-repo native H48 wrapper if needed."""

    root = root or repository_root()
    resolved_workbatch = resolve_h48_gendata_workbatch(gendata_workbatch)
    resolved_extra_cflags = normalize_h48_backend_extra_cflags(extra_cflags)
    vendor = h48_vendor_root(root)
    source = root / "native" / "h48_backend" / "h48_backend.c"
    nissy_source = vendor / "src" / "nissy.c"
    binary = h48_binary_path(root)
    binary.parent.mkdir(parents=True, exist_ok=True)
    dependencies = [source, nissy_source, *vendor.glob("src/**/*.h")]
    selected_arch = arch or _detect_arch()
    build_metadata_path = binary.with_suffix(".build.json")
    desired_build = {
        "arch": selected_arch,
        "threads": max(1, threads),
        "h48_gendata_workbatch": resolved_workbatch,
        "h48_gendata_distribution_mode": "expected_constants"
        if use_expected_distribution
        else "scanned",
        "h48_backend_extra_cflags": list(resolved_extra_cflags),
        "backend_source_commit": NISSY_CORE_COMMIT,
    }
    existing_build = None
    if build_metadata_path.exists():
        try:
            existing_build = json.loads(build_metadata_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing_build = None
    if (
        binary.exists()
        and binary.stat().st_mtime >= max(path.stat().st_mtime for path in dependencies)
        and existing_build == desired_build
    ):
        return binary
    command = [
        compiler,
        "-std=c11",
        "-fPIC",
        "-D_POSIX_C_SOURCE=199309L",
        "-pthread",
        "-pedantic",
        "-Wall",
        "-Wextra",
        "-Wno-unused-parameter",
        "-Wno-unused-function",
        f"-DTHREADS={max(1, threads)}",
        f"-DH48_GENDATA_WORKBATCH={resolved_workbatch}",
        f"-DH48_GENDATA_USE_EXPECTED_DISTRIBUTION={1 if use_expected_distribution else 0}",
        f"-D{selected_arch}",
        "-O3",
        *resolved_extra_cflags,
        "-I",
        str(vendor / "src"),
        "-o",
        str(binary),
        str(nissy_source),
        str(source),
    ]
    subprocess.run(command, cwd=root, check=True)
    write_json(build_metadata_path, desired_build)
    return binary


def write_h48_latex_table(root: Path, rows: list[dict[str, object]]) -> Path:
    table_path = root / "thesis" / "tables" / "h48_metadata.tex"
    table_path.parent.mkdir(parents=True, exist_ok=True)
    body = []
    for row in rows:
        body.append(
            f"{row['solver']} & {row['profile']} & {row['table_size_bytes']} & "
            f"{row['checksum_sha256'][:12]} & {row['generation_status']} \\\\"
        )
    table_path.write_text(
        "{\\small\n"
        "\\begin{tabular}{llrll}\n"
        "\\hline\n"
        "Solver & Profile & Bytes & SHA-256 prefix & Status \\\\\n"
        "\\hline\n"
        + "\n".join(body)
        + "\n\\hline\n\\end{tabular}\n"
        "}\n",
        encoding="utf-8",
    )
    return table_path


def _all_h48_metadata_rows(root: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for path in sorted((root / "results" / "processed").glob("h48_metadata_seed_*_*.json")):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if row.get("table_kind") == "h48_pruning_table":
            rows.append(row)
    return sorted(rows, key=lambda row: (str(row.get("profile", "")), int(row.get("h_value", -1)), str(row.get("solver", ""))))


def generate_h48_table(
    *,
    root: Path | None = None,
    profile: str = "thesis",
    seed: int = 2026,
    solver: str = DEFAULT_H48_SOLVER,
    threads: int = 8,
    force: bool = False,
    mmap_output: bool | None = None,
    progress_log: bool = False,
    gendata_workbatch: int | str | None = None,
    use_expected_distribution: bool = False,
    mmap_sync_mode: str = "sync",
    backend_extra_cflags: list[str] | tuple[str, ...] | None = None,
    adopt_existing_table_metadata: bool = False,
) -> dict[str, object]:
    """Generate or reuse an H48 pruning table and write metadata."""

    root = root or repository_root()
    requested_solver = solver
    solver = canonical_h48_solver(solver)
    resolved_workbatch = resolve_h48_gendata_workbatch(gendata_workbatch)
    resolved_mmap_sync_mode = normalize_h48_mmap_sync_mode(mmap_sync_mode)
    resolved_backend_extra_cflags = normalize_h48_backend_extra_cflags(backend_extra_cflags)
    h_value = h48_solver_h_value(solver)
    estimated_size = estimated_h48_table_size_bytes(solver)
    if mmap_output is None:
        mmap_output = h_value >= 8
    table_path = h48_table_path(root=root, profile=profile, seed=seed, solver=solver)
    metadata_path = h48_metadata_path(root=root, profile=profile, seed=seed, solver=solver)
    partial_path = staged_h48_table_path(table_path)
    table_path.parent.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    generation_status = "reused"
    generation_runtime = 0.0
    backend_payload: dict[str, object] = {}
    reused_metadata: dict[str, object] | None = None

    if force or not table_path.exists():
        binary = build_h48_backend(
            root=root,
            threads=threads,
            gendata_workbatch=resolved_workbatch,
            use_expected_distribution=use_expected_distribution,
            extra_cflags=resolved_backend_extra_cflags,
        )
        if partial_path.exists():
            partial_path.unlink()
        begin = time.perf_counter()
        command = [
            str(binary),
            "--generate",
            "--solver",
            solver,
            "--output",
            str(partial_path),
            "--threads",
            str(max(1, threads)),
        ]
        if mmap_output:
            command.extend(["--generate-mmap", "--mmap-sync-mode", resolved_mmap_sync_mode])
        if progress_log:
            command.append("--progress-log")
        completed = subprocess.run(
            command,
            cwd=root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=None if progress_log else subprocess.PIPE,
            check=False,
        )
        generation_runtime = time.perf_counter() - begin
        try:
            backend_payload = json.loads(completed.stdout)
        except json.JSONDecodeError:
            backend_payload = {
                "status": "failed",
                "error": (completed.stderr or "").strip() or completed.stdout.strip(),
            }
        if completed.returncode != 0 or backend_payload.get("status") != "generated":
            if partial_path.exists():
                partial_path.unlink()
            raise RuntimeError(f"H48 generation failed: {backend_payload}")
        if not partial_path.exists():
            raise RuntimeError(f"H48 generation did not create staged table: {partial_path}")
        if partial_path.stat().st_size != estimated_size:
            observed_size = partial_path.stat().st_size
            partial_path.unlink()
            raise RuntimeError(
                f"H48 generation produced unexpected staged size for {solver}: "
                f"{observed_size} bytes != {estimated_size} bytes"
            )
        partial_path.replace(table_path)
        generation_status = "generated"
    else:
        actual_size = table_path.stat().st_size
        if actual_size != estimated_size:
            raise RuntimeError(
                f"refusing to reuse existing H48 table with unexpected size for {solver}: "
                f"{actual_size} bytes != {estimated_size} bytes; rerun with --force to regenerate"
            )
        trusted_ok = False
        trusted_message = f"missing trusted H48 metadata: {metadata_path}"
        if metadata_path.exists():
            trusted_ok, trusted_message = validate_trusted_h48_table(
                root=root,
                profile=profile,
                seed=seed,
                solver=solver,
                table_path=table_path,
            )
        if trusted_ok and not adopt_existing_table_metadata:
            try:
                reused_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"invalid existing H48 metadata JSON: {metadata_path}") from exc
            result = dict(reused_metadata)
            result.update(
                {
                    "generation_status": "reused_trusted_table",
                    "reused_existing_metadata": True,
                    "reuse_trusted_metadata_valid": True,
                    "reuse_trusted_metadata_message": trusted_message,
                    "requested_solver": requested_solver,
                }
            )
            write_h48_latex_table(root, _all_h48_metadata_rows(root))
            return result
        if metadata_path.exists():
            try:
                reused_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                reused_metadata = None
        if not adopt_existing_table_metadata:
            if not metadata_path.exists():
                raise RuntimeError(
                    f"refusing to reuse existing H48 table without trusted metadata: {metadata_path}; "
                    "rerun with --force to regenerate, or use explicit recovery metadata adoption"
                )
            raise RuntimeError(
                f"refusing to reuse existing H48 table because metadata is not trusted: "
                f"{trusted_message}; rerun with --force to regenerate, or use explicit recovery metadata adoption"
            )
        adoption_canary = _run_h48_adoption_native_canary(
            root=root,
            solver=solver,
            table_path=table_path,
            threads=threads,
            gendata_workbatch=resolved_workbatch,
            use_expected_distribution=use_expected_distribution,
            backend_extra_cflags=resolved_backend_extra_cflags,
        )
        if adoption_canary.get("passed") is not True:
            raise RuntimeError(
                "refusing to adopt existing H48 table because native table-check canary failed: "
                f"{adoption_canary}"
            )
        backend_payload = {
            "status": "adopted_existing_table_metadata",
            "runtime_seconds": 0.0,
            "generation_storage": "existing_table_recovery",
            "previous_trusted_metadata_message": trusted_message,
            "previous_metadata_present": reused_metadata is not None,
            "previous_generation_status": reused_metadata.get("generation_status", "")
            if isinstance(reused_metadata, dict)
            else "",
            "previous_source_state": reused_metadata.get("source_state", "")
            if isinstance(reused_metadata, dict)
            else "",
            "previous_source_snapshot_reproducible": reused_metadata.get(
                "source_snapshot_reproducible", None
            )
            if isinstance(reused_metadata, dict)
            else None,
            "previous_checksum_sha256": reused_metadata.get("checksum_sha256", "")
            if isinstance(reused_metadata, dict)
            else "",
            "adoption_native_table_check": adoption_canary,
        }
        generation_status = "adopted_existing_table_metadata"

    checksum = sha256_file(table_path)
    source_state = capture_source_state(root)
    row = {
        "schema_version": 1,
        "table_name": f"{solver}_h48_pruning_table",
        "table_kind": "h48_pruning_table",
        "profile": profile,
        "seed": seed,
        "solver": solver,
        "requested_solver": requested_solver,
        "h_value": h_value,
        "oracle_grade": h_value >= 7,
        "file_path": _relative_or_absolute(root, table_path),
        "h48_table_root_env": H48_TABLE_ROOT_ENV,
        "h48_table_root": _relative_or_absolute(root, h48_table_root(root=root)),
        "checksum_sha256": checksum,
        "generated_at_utc": generated_at,
        "generator": H48_GENERATOR,
        "generation_status": generation_status,
        "adopted_existing_table_metadata": generation_status == "adopted_existing_table_metadata",
        "adoption_requires_explicit_flag": generation_status == "adopted_existing_table_metadata",
        "adoption_trust_boundary": (
            "Recovered metadata for an existing exact-size H48 table after explicit operator request. "
            "The table first passed a native nissy_checkdata-backed canary solve without --skip-table-check. "
            "Trusted use still requires canonical path/size metadata validation, full SHA-256 validation, "
            "solver certification, and downstream proof workloads."
            if generation_status == "adopted_existing_table_metadata"
            else ""
        ),
        "adoption_previous_trusted_metadata_message": backend_payload.get(
            "previous_trusted_metadata_message", ""
        ),
        "adoption_previous_metadata_present": backend_payload.get("previous_metadata_present", False),
        "adoption_previous_generation_status": backend_payload.get("previous_generation_status", ""),
        "adoption_previous_source_state": backend_payload.get("previous_source_state", ""),
        "adoption_previous_source_snapshot_reproducible": backend_payload.get(
            "previous_source_snapshot_reproducible", None
        ),
        "adoption_previous_checksum_sha256": backend_payload.get("previous_checksum_sha256", ""),
        "adoption_native_table_check_passed": (
            backend_payload.get("adoption_native_table_check", {}).get("passed") is True
            if isinstance(backend_payload.get("adoption_native_table_check"), dict)
            else False
        ),
        "adoption_native_table_check": backend_payload.get("adoption_native_table_check", {}),
        "runtime_seconds": round(float(backend_payload.get("runtime_seconds") or generation_runtime), 6),
        "table_size_bytes": table_path.stat().st_size,
        "estimated_table_size_bytes": estimated_size,
        "estimated_size_matches_actual": table_path.stat().st_size == estimated_size,
        "source_state": source_state["state"],
        "source_state_details": source_state,
        "source_snapshot_reproducible": source_state["is_reproducible_checkout"],
        "source_snapshot_limitation": source_state["limitation"],
        "source_reproduction_plan": source_state["reproduction_plan"],
        "backend_source": "vendored_nissy_core_h48",
        "backend_source_url": NISSY_CORE_SOURCE_URL,
        "backend_source_commit": NISSY_CORE_COMMIT,
        "license": "GPL-3.0-or-later",
        "threads": max(1, threads),
        "h48_gendata_workbatch": resolved_workbatch,
        "h48_backend_extra_cflags": list(resolved_backend_extra_cflags),
        "h48_generation_distribution_mode": "expected_constants"
        if use_expected_distribution
        else "scanned",
        "h48_generation_distribution_scan_skipped": bool(use_expected_distribution),
        "h48_generation_mmap_sync_mode": resolved_mmap_sync_mode
        if mmap_output and generation_status == "generated"
        else "not_applicable",
        "h48_generation_mmap_sync_runtime_seconds": round(
            float(backend_payload.get("mmap_sync_runtime_seconds") or 0.0),
            6,
        ),
        "staged_generation": True,
        "staged_output_path": _relative_or_absolute(root, partial_path),
        "generation_storage": backend_payload.get(
            "generation_storage",
            "mmap_file" if mmap_output and generation_status == "generated" else "heap_then_write",
        ),
        "notes": (
            "In-repository native H48 table generated through the vendored nissy-core H48 API. "
            "h48h0 is the smallest H48 table and is suitable for reproducible thesis runs; "
            "nissy-core aliases 'optimal' to h48h7, which is the first oracle-grade profile used here. "
            "Larger h-values require substantially more memory; h>=8 generation defaults to output-backed mmap "
            "to avoid a second full-table heap-to-file copy. New generation writes to a staged partial file first "
            "and atomically publishes it only after native generation succeeds and the expected table size matches."
        ),
    }
    write_json(metadata_path, row)
    write_h48_latex_table(root, _all_h48_metadata_rows(root))
    return row

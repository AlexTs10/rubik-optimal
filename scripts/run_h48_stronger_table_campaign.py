#!/usr/bin/env python
"""Run the stronger-H48-table campaign needed for a faster all-state oracle."""

from __future__ import annotations

import argparse
from collections import deque
import json
import os
import re
import selectors
import signal
import shlex
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rubik_optimal.results import write_json  # noqa: E402
from rubik_optimal.runtime import parse_gib, parse_thread_setting, run_process_tree  # noqa: E402
from rubik_optimal.tables.h48 import (  # noqa: E402
    canonical_h48_solver,
    estimated_h48_table_size_bytes,
    h48_metadata_path,
    h48_solver_h_value,
    h48_table_path,
    normalize_h48_backend_extra_cflags,
    normalize_h48_mmap_sync_mode,
    resolve_h48_gendata_workbatch,
    staged_h48_table_path,
    validate_trusted_h48_table,
    validate_trusted_h48_table_checksum,
)
from scripts.inspect_h48_capacity import (  # noqa: E402
    build_capacity_payload,
    evaluate_h48_generation_safety,
)


H48_GENDATA_PROGRESS_RE = re.compile(
    r"(?:Scanned\s+(?P<scanned>\d+)\s*/\s*(?P<scan_total>\d+)\s+slots;\s+)?"
    r"Processed\s+(?P<done>\d+)\s*/\s*(?P<total>\d+)\s+cubes"
)
H48_GENDATA_COMPUTED_RE = re.compile(r"Computed\s+(?P<positions>\d+)\s+positions")


def _tex(value: object) -> str:
    return str(value).replace("\\", "\\textbackslash{}").replace("_", "\\_").replace("&", "\\&")


def _terminate_process_group(process: subprocess.Popen[str], *, grace_seconds: float = 2.0) -> bool:
    terminated_group = False
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGTERM)
            terminated_group = True
        except ProcessLookupError:
            return terminated_group
        except OSError:
            process.terminate()
    else:
        process.terminate()
    try:
        process.wait(timeout=max(0.0, grace_seconds))
        return terminated_group
    except subprocess.TimeoutExpired:
        pass
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
            terminated_group = True
        except ProcessLookupError:
            return terminated_group
        except OSError:
            process.kill()
    else:
        process.kill()
    return terminated_group


def _run_streaming_command(
    command: list[str],
    *,
    root: Path,
    timeout_seconds: float | None,
) -> dict[str, Any]:
    """Run a command while forwarding merged output to this process' stdout."""

    begin = time.perf_counter()
    process = subprocess.Popen(
        command,
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
        start_new_session=os.name == "posix",
    )
    output_tail: deque[str] = deque(maxlen=80)
    timed_out = False
    terminated_group = False
    selector = selectors.DefaultSelector()
    if process.stdout is not None:
        selector.register(process.stdout, selectors.EVENT_READ)
    deadline = time.monotonic() + timeout_seconds if timeout_seconds is not None else None
    try:
        while True:
            if deadline is not None and time.monotonic() >= deadline:
                timed_out = True
                terminated_group = _terminate_process_group(process)
                break
            timeout = 0.25
            if deadline is not None:
                timeout = max(0.0, min(timeout, deadline - time.monotonic()))
            events = selector.select(timeout)
            for key, _event in events:
                line = key.fileobj.readline()
                if not line:
                    continue
                print(line, end="", flush=True)
                output_tail.append(line.rstrip("\n"))
            if process.poll() is not None:
                if process.stdout is not None:
                    for line in process.stdout.readlines():
                        print(line, end="", flush=True)
                        output_tail.append(line.rstrip("\n"))
                break
    finally:
        selector.close()
    return_code = 124 if timed_out else int(process.wait() or 0)
    return {
        "command": shlex.join(command),
        "return_code": return_code,
        "timed_out": timed_out,
        "terminated_process_group": terminated_group,
        "runtime_seconds": round(time.perf_counter() - begin, 6),
        "stdout_tail": "\n".join(output_tail),
        "stderr_tail": "",
        "streamed_output": True,
    }


def _run_command(
    command: list[str],
    *,
    root: Path,
    timeout_seconds: float | None,
    stream_output: bool = False,
) -> dict[str, Any]:
    if stream_output:
        return _run_streaming_command(command, root=root, timeout_seconds=timeout_seconds)
    completed = run_process_tree(
        command,
        cwd=root,
        timeout_seconds=timeout_seconds,
    )
    return {
        "command": shlex.join(command),
        "return_code": completed.return_code,
        "timed_out": completed.timed_out,
        "terminated_process_group": completed.terminated_process_group,
        "runtime_seconds": completed.runtime_seconds,
        "stdout_tail": "\n".join(completed.stdout.splitlines()[-40:]),
        "stderr_tail": "\n".join(completed.stderr.splitlines()[-40:]),
        "streamed_output": False,
    }


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_thread_setting(thread_setting: int | str) -> int:
    if isinstance(thread_setting, int):
        return max(1, int(thread_setting))
    return parse_thread_setting(str(thread_setting))


def wait_for_generation_safety(
    *,
    root: Path,
    solver: str,
    threads: int | str,
    timeout_seconds: float,
    check_interval_seconds: float,
    required_consecutive_checks: int,
    min_mmap_available_memory_bytes: int = 4 * 1024**3,
    disk_multiplier: float | None = None,
    sleeper=time.sleep,
    monotonic=time.monotonic,
    sample_reporter: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Wait until a stronger H48 generation target passes the local safety gate."""

    timeout = max(0.0, float(timeout_seconds))
    interval = max(0.0, float(check_interval_seconds))
    required = max(1, int(required_consecutive_checks))
    started = monotonic()
    deadline = started + timeout
    consecutive = 0
    samples: list[dict[str, Any]] = []

    while True:
        resolved_threads = _resolve_thread_setting(threads)
        safety = evaluate_h48_generation_safety(
            root=root,
            solver=solver,
            threads=resolved_threads,
            mmap_output=True,
            min_mmap_available_memory_bytes=min_mmap_available_memory_bytes,
            disk_multiplier=disk_multiplier,
        )
        elapsed = round(monotonic() - started, 6)
        sample = {
            "sample_index": len(samples) + 1,
            "elapsed_seconds": elapsed,
            "thread_setting": str(threads),
            "resolved_threads": resolved_threads,
            "dynamic_thread_selection": not isinstance(threads, int),
            "safe_to_start": safety["safe_to_start"],
            "reasons": safety["reasons"],
            "safety": safety,
        }
        samples.append(sample)
        if sample_reporter is not None:
            sample_reporter(sample)
        if safety["safe_to_start"]:
            consecutive += 1
            if consecutive >= required:
                return {
                    "waited": True,
                    "safe_to_start": True,
                    "status": "safety_wait_passed",
                    "required_consecutive_checks": required,
                    "completed_consecutive_checks": consecutive,
                    "timeout_seconds": timeout,
                    "check_interval_seconds": interval,
                    "sample_count": len(samples),
                    "samples": samples,
                    "final_safety": safety,
                }
        else:
            consecutive = 0
        if monotonic() >= deadline:
            return {
                "waited": True,
                "safe_to_start": False,
                "status": "safety_wait_timeout",
                "required_consecutive_checks": required,
                "completed_consecutive_checks": consecutive,
                "timeout_seconds": timeout,
                "check_interval_seconds": interval,
                "sample_count": len(samples),
                "samples": samples,
                "final_safety": safety,
            }
        sleeper(interval)


def _report_wait_sample(sample: dict[str, Any]) -> None:
    """Emit a compact heartbeat line for detached wait-safe logs."""

    safety = sample.get("safety") if isinstance(sample.get("safety"), dict) else {}
    machine = safety.get("machine", {}) if isinstance(safety, dict) else {}
    payload = {
        "event": "h48_generation_safety_sample",
        "checked_at_utc": datetime.now(UTC).isoformat(),
        "sample_index": sample.get("sample_index"),
        "elapsed_seconds": sample.get("elapsed_seconds"),
        "thread_setting": sample.get("thread_setting"),
        "resolved_threads": sample.get("resolved_threads"),
        "dynamic_thread_selection": sample.get("dynamic_thread_selection"),
        "threads": safety.get("threads") if isinstance(safety, dict) else None,
        "safe_to_start": sample.get("safe_to_start"),
        "reasons": sample.get("reasons"),
        "available_memory_bytes": machine.get("available_memory_bytes") if isinstance(machine, dict) else None,
        "load_average": machine.get("load_average") if isinstance(machine, dict) else None,
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True), flush=True)


def _validate_target_table_with_checksum(
    *,
    root: Path,
    profile: str,
    seed: int,
    solver: str,
) -> tuple[bool, str, bool, str, dict[str, Any]]:
    table = h48_table_path(root=root, profile=profile, seed=seed, solver=solver)
    metadata = h48_metadata_path(root=root, profile=profile, seed=seed, solver=solver)
    if not table.exists() or not metadata.exists():
        message = "missing target table or metadata after campaign"
        details: dict[str, Any] = {
            "trusted_metadata_valid": False,
            "full_checksum_valid": False,
            "table_exists": table.exists(),
            "metadata_exists": metadata.exists(),
            "table_path": str(table.relative_to(root)),
            "metadata_path": str(metadata.relative_to(root)),
        }
        return False, message, False, message, details

    trusted_ok, trusted_message = validate_trusted_h48_table(
        root=root,
        profile=profile,
        seed=seed,
        solver=solver,
        table_path=table,
    )
    checksum_ok, checksum_message, checksum_details = validate_trusted_h48_table_checksum(
        root=root,
        profile=profile,
        seed=seed,
        solver=solver,
        table_path=table,
        use_cache=False,
        persistent_cache=True,
    )
    return trusted_ok, trusted_message, checksum_ok, checksum_message, checksum_details


def build_campaign_decision(
    *,
    root: Path,
    profile: str,
    seed: int,
    target_solver: str,
    threads: int,
    thread_setting: str | None = None,
    dynamic_thread_selection: bool = False,
    allow_unsafe_generation: bool,
    dry_run: bool,
    capacity_payload: dict[str, Any] | None = None,
    safety: dict[str, Any] | None = None,
    min_mmap_available_memory_bytes: int = 4 * 1024**3,
    disk_multiplier: float | None = None,
    gendata_workbatch: int | str | None = None,
    skip_generation_distribution_scan: bool = False,
    mmap_sync_mode: str = "sync",
    backend_extra_cflags: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Build the preflight decision for a stronger H48 generation campaign."""

    solver = canonical_h48_solver(target_solver)
    resolved_workbatch = resolve_h48_gendata_workbatch(gendata_workbatch)
    resolved_mmap_sync_mode = normalize_h48_mmap_sync_mode(mmap_sync_mode)
    resolved_backend_extra_cflags = normalize_h48_backend_extra_cflags(backend_extra_cflags)
    h_value = h48_solver_h_value(solver)
    if h_value < 8:
        raise ValueError("stronger-table campaign targets h48h8 or larger")
    capacity = capacity_payload or build_capacity_payload(root=root, profile=profile, seed=seed)
    safety_payload = safety or evaluate_h48_generation_safety(
        root=root,
        solver=solver,
        threads=threads,
        mmap_output=True,
        min_mmap_available_memory_bytes=min_mmap_available_memory_bytes,
        disk_multiplier=disk_multiplier,
    )
    table = h48_table_path(root=root, profile=profile, seed=seed, solver=solver)
    metadata = h48_metadata_path(root=root, profile=profile, seed=seed, solver=solver)
    trusted_ok, trusted_message = (
        validate_trusted_h48_table(
            root=root,
            profile=profile,
            seed=seed,
            solver=solver,
            table_path=table,
        )
        if table.exists() and metadata.exists()
        else (False, "missing target table or metadata")
    )

    generation_command = [
        "nice",
        "-n",
        "20",
        sys.executable,
        "scripts/generate_h48_tables.py",
        "--profile",
        profile,
        "--seed",
        str(seed),
        "--solver",
        solver,
        "--threads",
        str(max(1, threads)),
        "--mmap-output",
        "--progress-log",
        "--gendata-workbatch",
        str(resolved_workbatch),
        "--mmap-sync-mode",
        resolved_mmap_sync_mode,
        "--require-safe",
        "--min-mmap-available-memory-gib",
        str(min_mmap_available_memory_bytes / (1024**3)),
        "--adopt-existing-table-metadata",
    ]
    for flag in resolved_backend_extra_cflags:
        generation_command.append(f"--backend-cflag={flag}")
    if disk_multiplier is not None:
        generation_command.extend(["--disk-multiplier", str(disk_multiplier)])
    if skip_generation_distribution_scan:
        generation_command.append("--skip-generation-distribution-scan")
    if allow_unsafe_generation:
        generation_command.append("--unsafe-allow-loaded-machine")

    can_start = trusted_ok or safety_payload["safe_to_start"] or allow_unsafe_generation
    if trusted_ok:
        status = "target_table_already_trusted"
    elif dry_run and not can_start:
        status = "dry_run_refused_unsafe_generation"
    elif dry_run:
        status = "planned"
    elif not can_start:
        status = "refused_unsafe_generation"
    else:
        status = "ready_to_generate"

    return {
        "target_solver": solver,
        "target_h_value": h_value,
        "target_table_path": str(table.relative_to(root)),
        "target_metadata_path": str(metadata.relative_to(root)),
        "target_estimated_table_size_bytes": estimated_h48_table_size_bytes(solver),
        "target_trusted_table": trusted_ok,
        "target_trusted_message": trusted_message,
        "current_strongest_local_oracle_solver": capacity.get("strongest_local_oracle_solver"),
        "current_next_missing_oracle_grade_solver": capacity.get("next_missing_oracle_grade_solver"),
        "safety": safety_payload,
        "thread_setting": thread_setting or str(max(1, threads)),
        "dynamic_thread_selection": dynamic_thread_selection,
        "generation_threads": max(1, threads),
        "h48_gendata_workbatch": resolved_workbatch,
        "h48_backend_extra_cflags": list(resolved_backend_extra_cflags),
        "h48_generation_distribution_mode": "expected_constants"
        if skip_generation_distribution_scan
        else "scanned",
        "h48_generation_distribution_scan_skipped": bool(skip_generation_distribution_scan),
        "h48_generation_mmap_sync_mode": resolved_mmap_sync_mode,
        "allow_unsafe_generation": allow_unsafe_generation,
        "dry_run": dry_run,
        "status": status,
        "generation_command": " ".join(generation_command),
        "generation_command_args": generation_command,
        "should_run_generation": status == "ready_to_generate",
        "all_state_fast_oracle_goal_satisfied_by_this_decision": False,
        "remaining_completion_requirements": [
            f"trusted {solver} table metadata and checksum",
            f"hard-case exact certification with {solver}",
            f"broad arbitrary-state corpus under thesis runtime target with {solver}",
            "formal or supervisor-approved empirical worst-case runtime boundary",
        ],
    }


def _write_table(root: Path, payload: dict[str, Any], suffix: str) -> Path:
    table_path = root / "thesis" / "tables" / f"h48_stronger_table_campaign{suffix}.tex"
    table_path.parent.mkdir(parents=True, exist_ok=True)
    row = (
        f"{_tex(payload['target_solver'])} & "
        f"{_tex(payload['status'])} & "
        f"{_tex(payload['target_trusted_table'])} & "
        f"{_tex((payload.get('safety') or {}).get('safe_to_start'))} & "
        f"{_tex(payload['all_state_fast_oracle_goal_satisfied'])} \\\\"
    )
    table_path.write_text(
        "{\\small\n"
        "\\begin{tabular}{lllll}\n"
        "\\hline\n"
        "Target & Campaign status & Trusted table & Safe now & Goal satisfied \\\\\n"
        "\\hline\n"
        + row
        + "\n\\hline\n\\end{tabular}\n"
        "}\n",
        encoding="utf-8",
    )
    return table_path


def _suffix(seed: int, profile: str, solver: str, artifact_suffix: str) -> str:
    suffix_parts = [f"seed_{seed}", profile, solver]
    if artifact_suffix:
        suffix_parts.append(artifact_suffix)
    return "_" + "_".join(str(part) for part in suffix_parts)


def _detached_output_path(root: Path, *, seed: int, profile: str, solver: str, artifact_suffix: str) -> Path:
    return root / "results" / "processed" / f"h48_stronger_table_detached{_suffix(seed, profile, solver, artifact_suffix)}.json"


def _canonical_detached_status_source_path(
    root: Path,
    *,
    seed: int,
    profile: str,
    solver: str,
    artifact_suffix: str,
) -> Path:
    return _detached_output_path(
        root,
        seed=seed,
        profile=profile,
        solver=canonical_h48_solver(solver),
        artifact_suffix=artifact_suffix,
    )


def _write_detached_table(root: Path, payload: dict[str, Any]) -> Path:
    table_path = (
        root
        / "thesis"
        / "tables"
        / f"h48_stronger_table_detached{_suffix(payload['seed'], payload['profile'], payload['target_solver'], payload['artifact_suffix'])}.tex"
    )
    table_path.parent.mkdir(parents=True, exist_ok=True)
    row = (
        f"{_tex(payload['target_solver'])} & "
        f"{_tex(payload['status'])} & "
        f"{_tex(payload['execute'])} & "
        f"{_tex(payload.get('pid'))} & "
        f"{_tex(payload['fast_runtime_proven_for_every_possible_state'])} \\\\"
    )
    table_path.write_text(
        "{\\small\n"
        "\\begin{tabular}{lllll}\n"
        "\\hline\n"
        "Target & Detached status & Executed & PID & Fast claim \\\\\n"
        "\\hline\n"
        + row
        + "\n\\hline\n\\end{tabular}\n"
        "}\n",
        encoding="utf-8",
    )
    return table_path


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _resolve_payload_path(root: Path, raw_path: object) -> Path | None:
    if not raw_path:
        return None
    path = Path(str(raw_path))
    return path if path.is_absolute() else root / path


def _read_text_tail(path: Path | None, *, max_lines: int = 40) -> str:
    if not path or not path.exists():
        return ""
    return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-max_lines:])


def _disk_allocated_bytes(path: Path) -> int | None:
    try:
        return int(path.stat().st_blocks) * 512
    except (AttributeError, OSError):
        return None


def _parse_h48_generation_progress(text: str, *, partial_path: Path | None = None) -> dict[str, Any]:
    progress_samples: list[dict[str, Any]] = []
    computed_positions: int | None = None
    saw_processing_phase = False
    for line in text.splitlines():
        if "Processing 'short cubes'" in line:
            saw_processing_phase = True
        computed_match = H48_GENDATA_COMPUTED_RE.search(line)
        if computed_match:
            computed_positions = int(computed_match.group("positions"))
        progress_match = H48_GENDATA_PROGRESS_RE.search(line)
        if progress_match:
            done = int(progress_match.group("done"))
            total = int(progress_match.group("total"))
            progress_samples.append(
                {
                    "processed_short_cubes": done,
                    "total_short_cubes": total,
                    "scanned_shortcube_slots": int(progress_match.group("scanned"))
                    if progress_match.group("scanned") is not None
                    else None,
                    "total_shortcube_slots": int(progress_match.group("scan_total"))
                    if progress_match.group("scan_total") is not None
                    else None,
                    "progress_fraction": round(done / total, 9) if total else None,
                    "line": line,
                }
            )
    latest = progress_samples[-1] if progress_samples else None
    partial_exists = bool(partial_path and partial_path.exists())
    partial_size = partial_path.stat().st_size if partial_path and partial_path.exists() else 0
    partial_allocated = _disk_allocated_bytes(partial_path) if partial_path and partial_path.exists() else None
    return {
        "available": bool(progress_samples or computed_positions is not None or saw_processing_phase or partial_exists),
        "saw_processing_phase": saw_processing_phase,
        "computed_short_positions": computed_positions,
        "progress_sample_count": len(progress_samples),
        "latest_processed_short_cubes": latest.get("processed_short_cubes") if latest else None,
        "total_short_cubes": latest.get("total_short_cubes") if latest else computed_positions,
        "latest_scanned_shortcube_slots": latest.get("scanned_shortcube_slots") if latest else None,
        "total_shortcube_slots": latest.get("total_shortcube_slots") if latest else None,
        "latest_progress_fraction": latest.get("progress_fraction") if latest else None,
        "latest_progress_line": latest.get("line") if latest else "",
        "recent_progress_samples": progress_samples[-5:],
        "partial_table_exists": partial_exists,
        "partial_table_size_bytes": partial_size,
        "partial_table_allocated_bytes": partial_allocated,
    }


def _parse_wait_safety_progress(text: str) -> dict[str, Any]:
    """Parse JSON wait-safe heartbeat lines from a detached H48 campaign log."""

    samples: list[dict[str, Any]] = []
    for line in text.splitlines():
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict) or payload.get("event") != "h48_generation_safety_sample":
            continue
        sample = {
            "sample_index": payload.get("sample_index"),
            "checked_at_utc": payload.get("checked_at_utc"),
            "elapsed_seconds": payload.get("elapsed_seconds"),
            "thread_setting": payload.get("thread_setting"),
            "resolved_threads": payload.get("resolved_threads"),
            "dynamic_thread_selection": payload.get("dynamic_thread_selection"),
            "threads": payload.get("threads"),
            "safe_to_start": payload.get("safe_to_start"),
            "reasons": payload.get("reasons") if isinstance(payload.get("reasons"), list) else [],
            "available_memory_bytes": payload.get("available_memory_bytes"),
            "load_average": payload.get("load_average") if isinstance(payload.get("load_average"), list) else [],
        }
        samples.append(sample)

    if not samples:
        return {
            "available": False,
            "sample_count": 0,
            "ever_safe_to_start": False,
            "latest_sample": None,
            "latest_safe_to_start": None,
            "latest_reasons": [],
            "latest_available_memory_bytes": None,
            "max_available_memory_bytes": None,
            "consecutive_safe_tail_count": 0,
            "recent_samples": [],
        }

    latest = samples[-1]
    available_values = [
        int(sample["available_memory_bytes"])
        for sample in samples
        if isinstance(sample.get("available_memory_bytes"), int)
    ]
    consecutive_safe_tail_count = 0
    for sample in reversed(samples):
        if sample.get("safe_to_start") is True:
            consecutive_safe_tail_count += 1
        else:
            break

    return {
        "available": True,
        "sample_count": len(samples),
        "first_checked_at_utc": samples[0].get("checked_at_utc"),
        "last_checked_at_utc": latest.get("checked_at_utc"),
        "ever_safe_to_start": any(sample.get("safe_to_start") is True for sample in samples),
        "latest_sample": latest,
        "latest_sample_index": latest.get("sample_index"),
        "latest_elapsed_seconds": latest.get("elapsed_seconds"),
        "latest_safe_to_start": latest.get("safe_to_start"),
        "latest_reasons": latest.get("reasons") if isinstance(latest.get("reasons"), list) else [],
        "latest_available_memory_bytes": latest.get("available_memory_bytes"),
        "latest_resolved_threads": latest.get("resolved_threads"),
        "latest_load_average": latest.get("load_average") if isinstance(latest.get("load_average"), list) else [],
        "max_available_memory_bytes": max(available_values) if available_values else None,
        "min_available_memory_bytes": min(available_values) if available_values else None,
        "consecutive_safe_tail_count": consecutive_safe_tail_count,
        "recent_samples": samples[-5:],
    }


def _read_pid_file(pid_file: Path | None) -> int | None:
    if not pid_file or not pid_file.exists():
        return None
    try:
        return int(pid_file.read_text(encoding="utf-8").strip())
    except ValueError:
        return None


def _relative(root: Path, path: Path) -> str:
    return str(path.relative_to(root)) if path.is_relative_to(root) else str(path)


def _extract_arg_value(args: list[Any], flag: str) -> str | None:
    try:
        index = [str(arg) for arg in args].index(flag)
    except ValueError:
        return None
    if index + 1 >= len(args):
        return None
    return str(args[index + 1])


def _native_processes_by_basename(*, names: set[str]) -> dict[str, Any]:
    """Return native process matches using comm-only process names, not argv text."""

    try:
        completed = subprocess.run(
            ["ps", "-Ao", "pid=,comm="],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        return {"available": False, "error": str(exc), "matches": []}

    matches: list[dict[str, Any]] = []
    if completed.returncode == 0:
        for line in completed.stdout.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            parts = stripped.split(maxsplit=1)
            if len(parts) != 2:
                continue
            raw_pid, command = parts
            try:
                pid = int(raw_pid)
            except ValueError:
                continue
            basename = Path(command).name
            if basename in names:
                matches.append({"pid": pid, "command": command, "basename": basename})

    return {
        "available": completed.returncode == 0,
        "return_code": completed.returncode,
        "stderr_tail": "\n".join(completed.stderr.splitlines()[-20:]),
        "matches": matches,
    }


def probe_detached_job(payload: dict[str, Any], *, root: Path | None = None) -> dict[str, Any]:
    """Return read-only status for a detached stronger-table process."""

    root = root or ROOT
    pid = payload.get("pid")
    log_path = _resolve_payload_path(root, payload.get("log_path"))
    pid_file = _resolve_payload_path(root, payload.get("pid_file_path"))
    pid_file_pid = _read_pid_file(pid_file)
    effective_pid = int(pid) if isinstance(pid, int) else pid_file_pid
    pid_alive = _pid_alive(effective_pid) if effective_pid is not None else None
    return {
        "pid": pid,
        "pid_file_pid": pid_file_pid,
        "effective_pid": effective_pid,
        "pid_alive": pid_alive,
        "pid_file_exists": bool(pid_file and pid_file.exists()),
        "log_path_exists": bool(log_path and log_path.exists()),
        "log_tail": _read_text_tail(log_path),
        "process_resources": _process_resource_snapshot([effective_pid] if effective_pid is not None else []),
    }


def _process_command_line(pid: int) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        return {"available": False, "error": str(exc), "command": ""}
    return {
        "available": completed.returncode == 0,
        "return_code": completed.returncode,
        "command": completed.stdout.strip(),
        "stderr_tail": "\n".join(completed.stderr.splitlines()[-20:]),
    }


def _process_resource_snapshot(pids: list[int]) -> dict[str, Any]:
    unique_pids = sorted({int(pid) for pid in pids if int(pid) > 0})
    if not unique_pids:
        return {"available": True, "matches": []}
    try:
        completed = subprocess.run(
            [
                "ps",
                "-p",
                ",".join(str(pid) for pid in unique_pids),
                "-o",
                "pid=,ppid=,pgid=,stat=,etime=,%cpu=,%mem=,rss=,command=",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        return {"available": False, "error": str(exc), "matches": []}

    matches: list[dict[str, Any]] = []
    for line in completed.stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parts = stripped.split(maxsplit=8)
        if len(parts) < 9:
            continue
        raw_pid, raw_ppid, raw_pgid, stat, elapsed, raw_cpu, raw_mem, raw_rss, command = parts
        try:
            pid = int(raw_pid)
            ppid = int(raw_ppid)
            pgid = int(raw_pgid)
            cpu_percent = float(raw_cpu)
            mem_percent = float(raw_mem)
            rss_kib = int(raw_rss)
        except ValueError:
            continue
        matches.append(
            {
                "pid": pid,
                "ppid": ppid,
                "pgid": pgid,
                "stat": stat,
                "elapsed": elapsed,
                "cpu_percent": cpu_percent,
                "mem_percent": mem_percent,
                "rss_kib": rss_kib,
                "rss_bytes": rss_kib * 1024,
                "command": command,
            }
        )
    return {
        "available": completed.returncode == 0 or bool(matches),
        "return_code": completed.returncode,
        "stderr_tail": "\n".join(completed.stderr.splitlines()[-20:]),
        "matches": matches,
    }


def _signal_process_group_or_pid(pid: int, sig: int) -> bool:
    if os.name == "posix":
        try:
            os.killpg(pid, sig)
            return True
        except ProcessLookupError:
            return True
        except OSError:
            pass
    try:
        os.kill(pid, sig)
    except ProcessLookupError:
        return True
    except OSError:
        return False
    return False


def _wait_until_pid_exits(pid: int, *, timeout_seconds: float, sleeper=time.sleep) -> bool:
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    while time.monotonic() < deadline:
        if not _pid_alive(pid):
            return True
        sleeper(0.1)
    return not _pid_alive(pid)


def _detached_stop_output_path(
    root: Path,
    *,
    seed: int,
    profile: str,
    solver: str,
    artifact_suffix: str,
) -> Path:
    return root / "results" / "processed" / f"h48_stronger_table_detached_stop{_suffix(seed, profile, solver, artifact_suffix)}.json"


def _write_detached_stop_table(root: Path, payload: dict[str, Any], *, artifact_suffix: str) -> Path:
    table_path = (
        root
        / "thesis"
        / "tables"
        / f"h48_stronger_table_detached_stop{_suffix(payload['seed'], payload['profile'], payload['target_solver'], artifact_suffix)}.tex"
    )
    table_path.parent.mkdir(parents=True, exist_ok=True)
    row = (
        f"{_tex(payload['target_solver'])} & "
        f"{_tex(payload['status'])} & "
        f"{_tex(payload['stopped_pid'])} & "
        f"{_tex(payload['native_h48_backend_running_before_stop'])} & "
        f"{_tex(payload['stopped_without_native_backend'])} & "
        f"{_tex(payload['fast_runtime_proven_for_every_possible_state'])} \\\\"
    )
    table_path.write_text(
        "{\\small\n"
        "\\begin{tabular}{llllll}\n"
        "\\hline\n"
        "Target & Stop status & PID & Native H48 before stop & Safe stop & Fast claim \\\\\n"
        "\\hline\n"
        + row
        + "\n\\hline\n\\end{tabular}\n"
        "}\n",
        encoding="utf-8",
    )
    return table_path


def stop_detached_campaign(
    *,
    root: Path,
    detached_payload_path: Path,
    terminate_timeout_seconds: float = 5.0,
) -> dict[str, Any]:
    """Stop a detached local waiter only when no native H48 backend is running."""

    status_payload = build_detached_status_payload(
        root=root,
        detached_payload_path=detached_payload_path,
        full_checksum=False,
    )
    detached_status = status_payload["detached_status"]
    effective_pid = detached_status.get("effective_pid")
    native_running = bool(status_payload["native_h48_backend_running"])
    command_line: dict[str, Any] = {}
    command_safe = False
    stop_signal_sent: str | None = None
    stopped_pid: int | None = None
    stopped_without_native_backend = False
    refusal_reasons: list[str] = []

    if native_running:
        refusal_reasons.append("native h48_backend process is running")
    if effective_pid is None:
        refusal_reasons.append("detached launch has no effective pid")
    elif detached_status.get("pid_alive") is not True:
        refusal_reasons.append("detached pid is not alive")
    else:
        stopped_pid = int(effective_pid)
        command_line = _process_command_line(stopped_pid)
        command = str(command_line.get("command") or "")
        command_safe = (
            "scripts/run_h48_stronger_table_campaign.py" in command
            and "--target-solver" in command
            and status_payload["target_solver"] in command
        )
        if not command_safe:
            refusal_reasons.append("effective pid command is not the expected stronger-table campaign")

    if refusal_reasons:
        status = "detached_stop_refused"
        pid_alive_after = detached_status.get("pid_alive")
    else:
        assert stopped_pid is not None
        stop_signal_sent = "SIGTERM"
        _signal_process_group_or_pid(stopped_pid, signal.SIGTERM)
        exited = _wait_until_pid_exits(stopped_pid, timeout_seconds=terminate_timeout_seconds)
        if not exited:
            stop_signal_sent = "SIGKILL"
            _signal_process_group_or_pid(stopped_pid, signal.SIGKILL)
            exited = _wait_until_pid_exits(stopped_pid, timeout_seconds=terminate_timeout_seconds)
        pid_alive_after = not exited
        stopped_without_native_backend = exited and not native_running
        status = "detached_waiter_stopped" if exited else "detached_stop_failed_pid_still_alive"

    return {
        "schema_version": 1,
        "checked_at_utc": datetime.now(UTC).isoformat(),
        "profile": status_payload["profile"],
        "seed": status_payload["seed"],
        "target_solver": status_payload["target_solver"],
        "artifact_suffix": status_payload["artifact_suffix"],
        "status": status,
        "detached_payload_path": status_payload["detached_payload_path"],
        "pre_stop_status": status_payload,
        "stopped_pid": stopped_pid,
        "stop_signal_sent": stop_signal_sent,
        "process_command_line": command_line,
        "process_command_safe_to_stop": command_safe,
        "native_h48_backend_running_before_stop": native_running,
        "pid_alive_after_stop": pid_alive_after,
        "stopped_without_native_backend": stopped_without_native_backend,
        "refusal_reasons": refusal_reasons,
        "fast_runtime_proven_for_every_possible_state": False,
        "notes": (
            "Audited local no-AWS stop for a detached stronger-table waiter. It refuses to stop when a native "
            "H48 backend is running or when the effective PID is not the expected campaign process."
        ),
    }


def build_detached_status_payload(
    *,
    root: Path,
    detached_payload_path: Path,
    full_checksum: bool = False,
) -> dict[str, Any]:
    """Build a read-only status payload for a detached local stronger-table campaign."""

    resolved_payload_path = detached_payload_path if detached_payload_path.is_absolute() else root / detached_payload_path
    launch_payload = json.loads(resolved_payload_path.read_text(encoding="utf-8"))
    profile = str(launch_payload.get("profile", "thesis"))
    seed = int(launch_payload.get("seed", 2026))
    solver = canonical_h48_solver(str(launch_payload.get("target_solver", "h48h8")))
    artifact_suffix = str(launch_payload.get("artifact_suffix", ""))
    child_args = list(launch_payload.get("child_command_args", []))
    child_threads = _extract_arg_value(child_args, "--threads") or "auto"
    parsed_threads = parse_thread_setting(child_threads)
    child_gendata_workbatch = _extract_arg_value(child_args, "--gendata-workbatch")
    child_mmap_sync_mode = _extract_arg_value(child_args, "--mmap-sync-mode") or "sync"
    child_backend_extra_cflags = [
        str(arg).split("=", 1)[1]
        for arg in child_args
        if isinstance(arg, str) and arg.startswith("--backend-cflag=")
    ]
    child_skips_distribution_scan = "--skip-generation-distribution-scan" in child_args
    min_mmap_available_memory_gib = launch_payload.get("min_mmap_available_memory_gib")
    min_mmap_available_memory_bytes = parse_gib(min_mmap_available_memory_gib) or 4 * 1024**3
    h48_disk_multiplier = launch_payload.get("h48_disk_multiplier")
    disk_multiplier = float(h48_disk_multiplier) if h48_disk_multiplier is not None else None

    detached_status = probe_detached_job(launch_payload, root=root)
    native_processes = _native_processes_by_basename(names={"h48_backend"})
    native_process_pids = [
        int(match["pid"])
        for match in native_processes.get("matches", [])
        if isinstance(match, dict) and isinstance(match.get("pid"), int)
    ]
    native_process_resources = _process_resource_snapshot(native_process_pids)
    table = h48_table_path(root=root, profile=profile, seed=seed, solver=solver)
    metadata = h48_metadata_path(root=root, profile=profile, seed=seed, solver=solver)
    partial = staged_h48_table_path(table)
    campaign_result = root / "results" / "processed" / f"h48_stronger_table_campaign{_suffix(seed, profile, solver, artifact_suffix)}.json"
    campaign_payload = _load_json(campaign_result) if campaign_result.exists() else None
    log_path = _resolve_payload_path(root, launch_payload.get("log_path"))
    progress_log_text = _read_text_tail(log_path, max_lines=5000)
    generation_progress = _parse_h48_generation_progress(progress_log_text, partial_path=partial)
    wait_safe_progress = _parse_wait_safety_progress(progress_log_text)

    target_trusted_ok = False
    target_trusted_message = "missing target table or metadata"
    full_checksum_valid: bool | None = None
    full_checksum_message = "not requested"
    full_checksum_details: dict[str, Any] = {}
    if table.exists() and metadata.exists():
        target_trusted_ok, target_trusted_message = validate_trusted_h48_table(
            root=root,
            profile=profile,
            seed=seed,
            solver=solver,
            table_path=table,
        )
        if full_checksum:
            full_checksum_valid, full_checksum_message, full_checksum_details = validate_trusted_h48_table_checksum(
                root=root,
                profile=profile,
                seed=seed,
                solver=solver,
                table_path=table,
                use_cache=False,
                persistent_cache=True,
            )

    native_running = bool(native_processes.get("matches"))
    if target_trusted_ok:
        status = "target_table_present_trusted_not_runtime_proof"
    elif native_running:
        status = "native_generation_or_solver_process_running_not_runtime_evidence"
    elif detached_status["pid_alive"] is True:
        if wait_safe_progress["available"] and generation_progress["available"] is False:
            status = "detached_python_alive_waiting_safety_gate_no_trusted_table"
        else:
            status = "detached_python_alive_waiting_or_running_no_trusted_table"
    elif campaign_payload is not None:
        status = "detached_campaign_result_present_no_trusted_table"
    elif detached_status["pid_alive"] is False:
        status = "detached_process_not_alive_no_trusted_table"
    else:
        status = "detached_launch_artifact_only_no_running_process"

    return {
        "schema_version": 1,
        "checked_at_utc": datetime.now(UTC).isoformat(),
        "profile": profile,
        "seed": seed,
        "target_solver": solver,
        "artifact_suffix": artifact_suffix,
        "status": status,
        "detached_payload_path": _relative(root, resolved_payload_path),
        "detached_launch_status": launch_payload.get("status"),
        "child_command_args": child_args,
        "h48_gendata_workbatch": int(child_gendata_workbatch)
        if child_gendata_workbatch is not None and str(child_gendata_workbatch).isdigit()
        else child_gendata_workbatch,
        "h48_generation_distribution_mode": "expected_constants"
        if child_skips_distribution_scan
        else "scanned",
        "h48_generation_distribution_scan_skipped": child_skips_distribution_scan,
        "h48_generation_mmap_sync_mode": child_mmap_sync_mode,
        "h48_backend_extra_cflags": child_backend_extra_cflags,
        "detached_status": detached_status,
        "pid": detached_status.get("pid"),
        "pid_file_pid": detached_status.get("pid_file_pid"),
        "effective_pid": detached_status.get("effective_pid"),
        "pid_alive": detached_status.get("pid_alive"),
        "native_h48_backend_running": native_running,
        "native_h48_backend_processes": native_processes,
        "native_h48_backend_process_resources": native_process_resources,
        "current_safety": evaluate_h48_generation_safety(
            root=root,
            solver=solver,
            threads=parsed_threads,
            mmap_output=True,
            min_mmap_available_memory_bytes=min_mmap_available_memory_bytes,
            disk_multiplier=disk_multiplier,
        ),
        "target_table": {
            "path": _relative(root, table),
            "exists": table.exists(),
            "size_bytes": table.stat().st_size if table.exists() else 0,
            "expected_size_bytes": estimated_h48_table_size_bytes(solver),
        },
        "target_metadata": {
            "path": _relative(root, metadata),
            "exists": metadata.exists(),
            "size_bytes": metadata.stat().st_size if metadata.exists() else 0,
        },
        "target_partial_table": {
            "path": _relative(root, partial),
            "exists": partial.exists(),
            "size_bytes": partial.stat().st_size if partial.exists() else 0,
            "allocated_bytes": _disk_allocated_bytes(partial) if partial.exists() else None,
        },
        "wait_safe_progress": wait_safe_progress,
        "generation_log_progress": generation_progress,
        "target_trusted_table": target_trusted_ok,
        "target_trusted_message": target_trusted_message,
        "full_checksum_requested": full_checksum,
        "full_checksum_valid": full_checksum_valid,
        "full_checksum_message": full_checksum_message,
        "full_checksum_details": full_checksum_details,
        "campaign_result_path": _relative(root, campaign_result),
        "campaign_result_exists": campaign_result.exists(),
        "campaign_result_status": campaign_payload.get("status") if isinstance(campaign_payload, dict) else None,
        "campaign_result_passed": campaign_payload.get("passed") if isinstance(campaign_payload, dict) else None,
        "fast_runtime_proven_for_every_possible_state": False,
        "notes": (
            "Read-only local no-AWS detached status. This proves process/table state only; the fast every-state "
            "claim remains false until trusted stronger-table metadata, full checksum, certification, broad "
            "runtime evidence, and a worst-case runtime boundary exist."
        ),
    }


def _detached_status_output_path(
    root: Path,
    *,
    seed: int,
    profile: str,
    solver: str,
    artifact_suffix: str,
) -> Path:
    return root / "results" / "processed" / f"h48_stronger_table_detached_status{_suffix(seed, profile, solver, artifact_suffix)}.json"


def _write_detached_status_table(root: Path, payload: dict[str, Any], *, artifact_suffix: str) -> Path:
    table_path = (
        root
        / "thesis"
        / "tables"
        / f"h48_stronger_table_detached_status{_suffix(payload['seed'], payload['profile'], payload['target_solver'], artifact_suffix)}.tex"
    )
    table_path.parent.mkdir(parents=True, exist_ok=True)
    row = (
        f"{_tex(payload['target_solver'])} & "
        f"{_tex(payload['status'])} & "
        f"{_tex(payload['detached_status'].get('pid_alive'))} & "
        f"{_tex(payload['native_h48_backend_running'])} & "
        f"{_tex(payload['target_trusted_table'])} & "
        f"{_tex(payload['fast_runtime_proven_for_every_possible_state'])} \\\\"
    )
    table_path.write_text(
        "{\\small\n"
        "\\begin{tabular}{llllll}\n"
        "\\hline\n"
        "Target & Status & PID alive & Native H48 & Trusted table & Fast claim \\\\\n"
        "\\hline\n"
        + row
        + "\n\\hline\n\\end{tabular}\n"
        "}\n",
        encoding="utf-8",
    )
    return table_path


def launch_detached_campaign(
    *,
    root: Path,
    profile: str,
    seed: int,
    target_solver: str,
    threads: str,
    allow_unsafe_generation: bool,
    generation_timeout_seconds: float | None,
    certification_timeout_seconds: float,
    runtime_target_seconds: float,
    artifact_suffix: str,
    wait_for_safe: bool,
    safety_wait_timeout_seconds: float,
    safety_check_interval_seconds: float,
    safety_required_consecutive_checks: int,
    execute: bool,
    log_dir: Path | None = None,
    min_mmap_available_memory_bytes: int = 4 * 1024**3,
    disk_multiplier: float | None = None,
    gendata_workbatch: int | str | None = None,
    skip_generation_distribution_scan: bool = False,
    mmap_sync_mode: str = "sync",
    backend_extra_cflags: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Plan or start a detached local stronger-table campaign."""

    solver = canonical_h48_solver(target_solver)
    resolved_workbatch = resolve_h48_gendata_workbatch(gendata_workbatch)
    resolved_mmap_sync_mode = normalize_h48_mmap_sync_mode(mmap_sync_mode)
    resolved_backend_extra_cflags = normalize_h48_backend_extra_cflags(backend_extra_cflags)
    suffix = _suffix(seed, profile, solver, artifact_suffix)
    log_root = log_dir or root / "results" / "logs"
    log_root.mkdir(parents=True, exist_ok=True)
    log_path = log_root / f"h48_stronger_table_detached{suffix}.log"
    pid_file = root / "results" / "processed" / f"h48_stronger_table_detached{suffix}.pid"
    command = [
        sys.executable,
        "scripts/run_h48_stronger_table_campaign.py",
        "--profile",
        profile,
        "--seed",
        str(seed),
        "--target-solver",
        solver,
        "--threads",
        threads,
        "--certification-timeout",
        str(certification_timeout_seconds),
        "--runtime-target",
        str(runtime_target_seconds),
        "--artifact-suffix",
        artifact_suffix,
    ]
    if generation_timeout_seconds is not None:
        command.extend(["--generation-timeout", str(generation_timeout_seconds)])
    if wait_for_safe:
        command.extend(
            [
                "--wait-for-safe",
                "--safety-wait-timeout",
                str(safety_wait_timeout_seconds),
                "--safety-check-interval",
                str(safety_check_interval_seconds),
                "--safety-required-consecutive-checks",
                str(safety_required_consecutive_checks),
            ]
        )
    command.extend(
        [
            "--min-mmap-available-memory-gib",
            str(min_mmap_available_memory_bytes / (1024**3)),
        ]
    )
    if disk_multiplier is not None:
        command.extend(["--disk-multiplier", str(disk_multiplier)])
    command.extend(["--gendata-workbatch", str(resolved_workbatch)])
    command.extend(["--mmap-sync-mode", resolved_mmap_sync_mode])
    for flag in resolved_backend_extra_cflags:
        command.append(f"--backend-cflag={flag}")
    if skip_generation_distribution_scan:
        command.append("--skip-generation-distribution-scan")
    if allow_unsafe_generation:
        command.append("--allow-unsafe-generation")

    preflight = evaluate_h48_generation_safety(
        root=root,
        solver=solver,
        threads=parse_thread_setting(threads),
        mmap_output=True,
        min_mmap_available_memory_bytes=min_mmap_available_memory_bytes,
        disk_multiplier=disk_multiplier,
    )
    dynamic_thread_selection = str(threads).strip().lower() == "auto"
    process_pid: int | None = None
    status = "detached_waitsafe_dryrun_planned_not_runtime_evidence" if wait_for_safe else "detached_dryrun_planned_not_runtime_evidence"
    if execute:
        with log_path.open("a", encoding="utf-8") as log_handle:
            process = subprocess.Popen(
                command,
                cwd=root,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                start_new_session=os.name == "posix",
            )
        process_pid = int(process.pid)
        pid_file.parent.mkdir(parents=True, exist_ok=True)
        pid_file.write_text(str(process_pid), encoding="utf-8")
        status = "detached_waitsafe_started_not_runtime_evidence" if wait_for_safe else "detached_started_not_runtime_evidence"

    payload: dict[str, Any] = {
        "schema_version": 1,
        "checked_at_utc": datetime.now(UTC).isoformat(),
        "profile": profile,
        "seed": seed,
        "target_solver": solver,
        "artifact_suffix": artifact_suffix,
        "status": status,
        "execute": execute,
        "pid": process_pid,
        "pid_file_path": str(pid_file.relative_to(root)),
        "log_path": str(log_path.relative_to(root)),
        "child_command": shlex.join(command),
        "child_command_args": command,
        "thread_setting": threads,
        "dynamic_thread_selection": dynamic_thread_selection,
        "min_mmap_available_memory_gib": min_mmap_available_memory_bytes / (1024**3),
        "h48_disk_multiplier": disk_multiplier,
        "h48_gendata_workbatch": resolved_workbatch,
        "h48_backend_extra_cflags": list(resolved_backend_extra_cflags),
        "h48_generation_mmap_sync_mode": resolved_mmap_sync_mode,
        "h48_generation_distribution_mode": "expected_constants"
        if skip_generation_distribution_scan
        else "scanned",
        "h48_generation_distribution_scan_skipped": bool(skip_generation_distribution_scan),
        "preflight_safety": preflight,
        "detached_status": {},
        "fast_runtime_proven_for_every_possible_state": False,
        "notes": (
            "Local no-AWS detached stronger-table launcher. A started process is still not runtime evidence; "
            "the fast every-state claim requires the resulting trusted table, checksum, certification, broad "
            "runtime corpus, and final contract proof."
        ),
    }
    payload["detached_status"] = probe_detached_job(payload, root=root)
    return payload


def run_campaign(
    *,
    root: Path,
    profile: str,
    seed: int,
    target_solver: str,
    threads: int,
    thread_setting: str | None = None,
    allow_unsafe_generation: bool,
    dry_run: bool,
    generation_timeout_seconds: float | None,
    certification_timeout_seconds: float,
    runtime_target_seconds: float,
    artifact_suffix: str,
    wait_for_safe: bool = False,
    safety_wait_timeout_seconds: float = 0.0,
    safety_check_interval_seconds: float = 60.0,
    safety_required_consecutive_checks: int = 2,
    min_mmap_available_memory_bytes: int = 4 * 1024**3,
    disk_multiplier: float | None = None,
    gendata_workbatch: int | str | None = None,
    skip_generation_distribution_scan: bool = False,
    mmap_sync_mode: str = "sync",
    backend_extra_cflags: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    requested_thread_setting = thread_setting if thread_setting is not None else str(max(1, threads))
    dynamic_thread_selection = thread_setting is not None and str(thread_setting).strip().lower() == "auto"
    initial_threads = _resolve_thread_setting(requested_thread_setting) if dynamic_thread_selection else max(1, threads)
    decision = build_campaign_decision(
        root=root,
        profile=profile,
        seed=seed,
        target_solver=target_solver,
        threads=initial_threads,
        thread_setting=requested_thread_setting,
        dynamic_thread_selection=dynamic_thread_selection,
        allow_unsafe_generation=allow_unsafe_generation,
        dry_run=dry_run,
        min_mmap_available_memory_bytes=min_mmap_available_memory_bytes,
        disk_multiplier=disk_multiplier,
        gendata_workbatch=gendata_workbatch,
        skip_generation_distribution_scan=skip_generation_distribution_scan,
        mmap_sync_mode=mmap_sync_mode,
        backend_extra_cflags=backend_extra_cflags,
    )
    solver = str(decision["target_solver"])
    commands: list[dict[str, Any]] = []
    status = str(decision["status"])
    safety_wait: dict[str, Any] | None = None

    if (
        wait_for_safe
        and not dry_run
        and not allow_unsafe_generation
        and status == "refused_unsafe_generation"
    ):
        safety_wait = wait_for_generation_safety(
            root=root,
            solver=solver,
            threads=requested_thread_setting if dynamic_thread_selection else max(1, threads),
            min_mmap_available_memory_bytes=min_mmap_available_memory_bytes,
            disk_multiplier=disk_multiplier,
            timeout_seconds=safety_wait_timeout_seconds,
            check_interval_seconds=safety_check_interval_seconds,
            required_consecutive_checks=safety_required_consecutive_checks,
            sample_reporter=_report_wait_sample,
        )
        if safety_wait["safe_to_start"]:
            final_threads = int(safety_wait["final_safety"].get("threads") or initial_threads)
            decision = build_campaign_decision(
                root=root,
                profile=profile,
                seed=seed,
                target_solver=target_solver,
                threads=final_threads,
                thread_setting=requested_thread_setting,
                dynamic_thread_selection=dynamic_thread_selection,
                allow_unsafe_generation=allow_unsafe_generation,
                dry_run=dry_run,
                safety=safety_wait["final_safety"],
                min_mmap_available_memory_bytes=min_mmap_available_memory_bytes,
                disk_multiplier=disk_multiplier,
                gendata_workbatch=gendata_workbatch,
                skip_generation_distribution_scan=skip_generation_distribution_scan,
                mmap_sync_mode=mmap_sync_mode,
                backend_extra_cflags=backend_extra_cflags,
            )
            status = str(decision["status"])
        else:
            decision = {
                **decision,
                "safety": safety_wait["final_safety"],
                "status": "deferred_by_safety_wait",
                "should_run_generation": False,
            }
            status = "deferred_by_safety_wait"

    if decision["should_run_generation"]:
        selected_threads = max(1, int(decision.get("generation_threads") or threads))
        command = [str(part) for part in decision["generation_command_args"]]
        generation = _run_command(
            command,
            root=root,
            timeout_seconds=generation_timeout_seconds,
            stream_output=True,
        )
        commands.append({"phase": "generate_table", **generation})
        if generation["return_code"] == 0 and not generation["timed_out"]:
            status = "generated_table"
            certification_command = [
                sys.executable,
                "scripts/run_h48_oracle_certification.py",
                "--profile",
                profile,
                "--seed",
                str(seed),
                "--solver",
                solver,
                "--timeout",
                str(certification_timeout_seconds),
                "--runtime-target",
                str(runtime_target_seconds),
                "--threads",
                str(selected_threads),
                "--trusted-table",
                "--artifact-suffix",
                artifact_suffix or f"{solver}_stronger_campaign",
            ]
            certification = _run_command(
                certification_command,
                root=root,
                timeout_seconds=max(certification_timeout_seconds * 4, certification_timeout_seconds + 60),
                stream_output=True,
            )
            commands.append({"phase": "certify_hard_cases", **certification})
            status = "generated_and_certified" if certification["return_code"] == 0 and not certification["timed_out"] else "generated_but_certification_failed"
        else:
            status = "generation_failed_or_timed_out"

    trusted_ok, trusted_message, checksum_ok, checksum_message, checksum_details = (
        _validate_target_table_with_checksum(
            root=root,
            profile=profile,
            seed=seed,
            solver=solver,
        )
    )
    all_state_goal_satisfied = False
    passed = (
        status in {"target_table_already_trusted", "generated_and_certified"}
        and trusted_ok
        and checksum_ok
    )
    payload = {
        "schema_version": 1,
        "checked_at_utc": datetime.now(UTC).isoformat(),
        "profile": profile,
        "seed": seed,
        "artifact_suffix": artifact_suffix,
        **decision,
        "status": status,
        "post_campaign_target_trusted_table": trusted_ok,
        "post_campaign_target_trusted_message": trusted_message,
        "post_campaign_full_checksum_valid": checksum_ok,
        "post_campaign_full_checksum_message": checksum_message,
        "post_campaign_checksum_details": checksum_details,
        "commands": commands,
        "safety_wait": safety_wait,
        "all_state_fast_oracle_goal_satisfied": all_state_goal_satisfied,
        "fast_runtime_proven_for_every_possible_state": False,
        "passed": passed,
        "notes": (
            "Stronger H48 table campaign for the requested fast optimal oracle over every valid 3x3 state. "
            "This artifact is deliberately not a completion claim unless the target table is trusted, the full "
            "table checksum matches its metadata, hard-case certification passes, broad runtime evidence exists, "
            "and a worst-case runtime boundary is documented."
        ),
    }
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default="thesis")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--target-solver", default="h48h8")
    parser.add_argument("--threads", default="auto")
    parser.add_argument("--allow-unsafe-generation", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--generation-timeout", type=float, default=None)
    parser.add_argument("--certification-timeout", type=float, default=300.0)
    parser.add_argument("--runtime-target", type=float, default=300.0)
    parser.add_argument(
        "--wait-for-safe",
        action="store_true",
        help="Wait for the local stronger-table safety gate before launching generation.",
    )
    parser.add_argument("--safety-wait-timeout", type=float, default=0.0)
    parser.add_argument("--safety-check-interval", type=float, default=60.0)
    parser.add_argument("--safety-required-consecutive-checks", type=int, default=2)
    parser.add_argument(
        "--min-mmap-available-memory-gib",
        type=float,
        default=None,
        help=(
            "Override the default 4 GiB immediately-available-memory guard used for local H48 mmap "
            "generation. The chosen value is recorded in the launch/campaign artifacts."
        ),
    )
    parser.add_argument(
        "--disk-multiplier",
        type=float,
        default=None,
        help=(
            "Override the free-disk headroom multiplier for stronger-table safety checks. "
            "By default the H48 safety helper uses a staged-mmap-specific multiplier for h48h8+."
        ),
    )
    parser.add_argument(
        "--gendata-workbatch",
        default=None,
        help=(
            "Native H48 short-cube scheduling batch size forwarded to generate_h48_tables.py. "
            "Smaller values improve h48h8+ load balancing and progress visibility."
        ),
    )
    parser.add_argument(
        "--skip-generation-distribution-scan",
        action="store_true",
        help=(
            "Forward generate_h48_tables.py --skip-generation-distribution-scan so the generated table "
            "uses canonical expected H48 distribution constants instead of a final full-table scan."
        ),
    )
    parser.add_argument(
        "--mmap-sync-mode",
        choices=["sync", "async", "none"],
        default="sync",
        help=(
            "Forward generate_h48_tables.py --mmap-sync-mode for output-backed mmap generation. "
            "Use async/none only with staged files plus post-generation checksum validation."
        ),
    )
    parser.add_argument(
        "--backend-cflag",
        action="append",
        default=[],
        help=(
            "Forward an audited extra native backend compiler flag to generate_h48_tables.py, "
            "for example --backend-cflag=-march=native on a dedicated proof host."
        ),
    )
    parser.add_argument(
        "--detach",
        action="store_true",
        help="Start the stronger-table campaign as a detached local process and return a launch artifact.",
    )
    parser.add_argument(
        "--detach-dry-run",
        action="store_true",
        help="With --detach, record the detached command without starting a process.",
    )
    parser.add_argument("--detached-log-dir", type=Path, default=None)
    parser.add_argument(
        "--detached-status-from",
        type=Path,
        default=None,
        help="Write a read-only status artifact for an existing detached launch JSON.",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help=(
            "Read-only shorthand for --detached-status-from using the canonical detached launch artifact "
            "for --profile/--seed/--target-solver/--artifact-suffix."
        ),
    )
    parser.add_argument(
        "--status-artifact-suffix",
        default=None,
        help=(
            "Artifact suffix for the written status JSON/table. Defaults to --artifact-suffix, which keeps "
            "backwards compatibility with --detached-status-from."
        ),
    )
    parser.add_argument(
        "--detached-status-full-checksum",
        action="store_true",
        help="With --status or --detached-status-from, run the expensive full target-table checksum if the table exists.",
    )
    parser.add_argument(
        "--detached-stop-from",
        type=Path,
        default=None,
        help=(
            "Stop an existing detached local waiter after proving no native H48 backend is running. "
            "Writes an audited stop artifact and does not start a replacement process."
        ),
    )
    parser.add_argument(
        "--detached-stop-timeout",
        type=float,
        default=5.0,
        help="Seconds to wait after SIGTERM/SIGKILL when stopping a detached local waiter.",
    )
    parser.add_argument("--artifact-suffix", default="lowload")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    min_mmap_available_memory_bytes = (
        parse_gib(args.min_mmap_available_memory_gib) or 4 * 1024**3
        if args.min_mmap_available_memory_gib is not None
        else 4 * 1024**3
    )

    if args.status and args.detached_status_from is not None:
        parser.error("--status cannot be combined with --detached-status-from")

    detached_status_from = args.detached_status_from
    if args.status:
        detached_status_from = _canonical_detached_status_source_path(
            args.root,
            seed=args.seed,
            profile=args.profile,
            solver=args.target_solver,
            artifact_suffix=args.artifact_suffix,
        )

    if detached_status_from is not None:
        payload = build_detached_status_payload(
            root=args.root,
            detached_payload_path=detached_status_from,
            full_checksum=args.detached_status_full_checksum,
        )
        status_artifact_suffix = args.status_artifact_suffix or args.artifact_suffix
        output = _detached_status_output_path(
            args.root,
            seed=payload["seed"],
            profile=payload["profile"],
            solver=payload["target_solver"],
            artifact_suffix=status_artifact_suffix,
        )
        write_json(output, payload)
        table = _write_detached_status_table(args.root, payload, artifact_suffix=status_artifact_suffix)
        print(
            json.dumps(
                {
                    "output": str(output),
                    "table": str(table),
                    "status": payload["status"],
                    "pid_alive": payload["detached_status"].get("pid_alive"),
                    "native_h48_backend_running": payload["native_h48_backend_running"],
                    "target_trusted_table": payload["target_trusted_table"],
                    "fast_runtime_proven_for_every_possible_state": payload[
                        "fast_runtime_proven_for_every_possible_state"
                    ],
                },
                indent=2,
            )
        )
        return 0

    if args.detached_stop_from is not None:
        payload = stop_detached_campaign(
            root=args.root,
            detached_payload_path=args.detached_stop_from,
            terminate_timeout_seconds=args.detached_stop_timeout,
        )
        output = _detached_stop_output_path(
            args.root,
            seed=payload["seed"],
            profile=payload["profile"],
            solver=payload["target_solver"],
            artifact_suffix=args.artifact_suffix,
        )
        write_json(output, payload)
        table = _write_detached_stop_table(args.root, payload, artifact_suffix=args.artifact_suffix)
        print(
            json.dumps(
                {
                    "output": str(output),
                    "table": str(table),
                    "status": payload["status"],
                    "stopped_pid": payload["stopped_pid"],
                    "stop_signal_sent": payload["stop_signal_sent"],
                    "native_h48_backend_running_before_stop": payload[
                        "native_h48_backend_running_before_stop"
                    ],
                    "stopped_without_native_backend": payload["stopped_without_native_backend"],
                    "fast_runtime_proven_for_every_possible_state": payload[
                        "fast_runtime_proven_for_every_possible_state"
                    ],
                },
                indent=2,
            )
        )
        return 0 if payload["status"] == "detached_waiter_stopped" else 1

    if args.detach:
        payload = launch_detached_campaign(
            root=args.root,
            profile=args.profile,
            seed=args.seed,
            target_solver=args.target_solver,
            threads=args.threads,
            allow_unsafe_generation=args.allow_unsafe_generation,
            generation_timeout_seconds=args.generation_timeout,
            certification_timeout_seconds=args.certification_timeout,
            runtime_target_seconds=args.runtime_target,
            artifact_suffix=args.artifact_suffix,
            wait_for_safe=args.wait_for_safe,
            safety_wait_timeout_seconds=args.safety_wait_timeout,
            safety_check_interval_seconds=args.safety_check_interval,
            safety_required_consecutive_checks=args.safety_required_consecutive_checks,
            min_mmap_available_memory_bytes=min_mmap_available_memory_bytes,
            disk_multiplier=args.disk_multiplier,
            gendata_workbatch=args.gendata_workbatch,
            skip_generation_distribution_scan=args.skip_generation_distribution_scan,
            mmap_sync_mode=args.mmap_sync_mode,
            backend_extra_cflags=args.backend_cflag,
            execute=not args.detach_dry_run,
            log_dir=args.detached_log_dir,
        )
        output = _detached_output_path(
            args.root,
            seed=args.seed,
            profile=args.profile,
            solver=payload["target_solver"],
            artifact_suffix=args.artifact_suffix,
        )
        write_json(output, payload)
        table = _write_detached_table(args.root, payload)
        print(
            json.dumps(
                {
                    "output": str(output),
                    "table": str(table),
                    "status": payload["status"],
                    "execute": payload["execute"],
                    "pid": payload["pid"],
                    "fast_runtime_proven_for_every_possible_state": payload[
                        "fast_runtime_proven_for_every_possible_state"
                    ],
                },
                indent=2,
            )
        )
        return 0

    threads = parse_thread_setting(args.threads)
    payload = run_campaign(
        root=args.root,
        profile=args.profile,
        seed=args.seed,
        target_solver=args.target_solver,
        threads=threads,
        thread_setting=args.threads,
        allow_unsafe_generation=args.allow_unsafe_generation,
        dry_run=args.dry_run,
        generation_timeout_seconds=args.generation_timeout,
        certification_timeout_seconds=args.certification_timeout,
        runtime_target_seconds=args.runtime_target,
        artifact_suffix=args.artifact_suffix,
        wait_for_safe=args.wait_for_safe,
        safety_wait_timeout_seconds=args.safety_wait_timeout,
        safety_check_interval_seconds=args.safety_check_interval,
        safety_required_consecutive_checks=args.safety_required_consecutive_checks,
        min_mmap_available_memory_bytes=min_mmap_available_memory_bytes,
        disk_multiplier=args.disk_multiplier,
        gendata_workbatch=args.gendata_workbatch,
        skip_generation_distribution_scan=args.skip_generation_distribution_scan,
        mmap_sync_mode=args.mmap_sync_mode,
        backend_extra_cflags=args.backend_cflag,
    )
    suffix = _suffix(args.seed, args.profile, payload["target_solver"], args.artifact_suffix)
    output = args.root / "results" / "processed" / f"h48_stronger_table_campaign{suffix}.json"
    write_json(output, payload)
    table = _write_table(args.root, payload, suffix)
    print(
        json.dumps(
            {
                "output": str(output),
                "table": str(table),
                "status": payload["status"],
                "passed": payload["passed"],
                "target_trusted_table": payload["post_campaign_target_trusted_table"],
                "full_checksum_valid": payload["post_campaign_full_checksum_valid"],
                "fast_runtime_proven_for_every_possible_state": payload[
                    "fast_runtime_proven_for_every_possible_state"
                ],
            },
            indent=2,
        )
    )
    non_execution_statuses = {
        "planned",
        "dry_run_refused_unsafe_generation",
        "refused_unsafe_generation",
        "deferred_by_safety_wait",
    }
    return 0 if payload["passed"] or payload["status"] in non_execution_statuses else 1


if __name__ == "__main__":
    raise SystemExit(main())

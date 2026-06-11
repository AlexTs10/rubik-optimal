"""Runtime sizing helpers for long native solver jobs."""

from __future__ import annotations

import re
import os
import signal
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from collections.abc import Mapping, Sequence
from typing import Callable


_GIB = 1024**3


@dataclass(frozen=True)
class IdleStatus:
    """Machine pressure snapshot for deciding whether to launch heavy jobs."""

    idle: bool
    cpu_count: int
    load_average_1m: float | None
    load_average_5m: float | None
    available_memory_bytes: int | None
    max_load_1m: float | None
    max_load_5m: float | None
    min_available_memory_bytes: int | None
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ProcessTreeResult:
    """Captured result from a subprocess whose descendants share its process group."""

    command: tuple[str, ...]
    return_code: int
    timed_out: bool
    runtime_seconds: float
    stdout: str
    stderr: str
    terminated_process_group: bool


def suggest_thread_count(
    *,
    max_threads: int = 8,
    cpu_count: int | None = None,
    load_average: float | None = None,
) -> int:
    """Return a conservative thread count for the current machine load.

    Exact H48 searches can keep all workers busy for minutes on hard states.
    This helper keeps the default aggressive on an idle workstation, while
    reserving capacity when the one-minute load average already consumes cores.
    """

    cpus = max(1, int(cpu_count if cpu_count is not None else (os.cpu_count() or 1)))
    cap = max(1, min(int(max_threads), cpus))
    if load_average is None:
        try:
            load_average = float(os.getloadavg()[0])
        except (AttributeError, OSError):
            return cap
    if load_average <= 1.0:
        return cap
    busy_cores = int(round(load_average))
    return max(1, min(cap, cpus - busy_cores))


def _terminate_process_tree(process: subprocess.Popen[str], *, grace_seconds: float) -> bool:
    """Terminate a process and its descendants when the platform supports it."""

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


def run_process_tree(
    command: Sequence[str | os.PathLike[str]],
    *,
    cwd: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    timeout_seconds: float | None = None,
    terminate_grace_seconds: float = 2.0,
) -> ProcessTreeResult:
    """Run a command and enforce timeout on the whole descendant process tree.

    Heavy thesis workloads often launch Python wrappers that then launch native
    solver children. Plain ``subprocess.run(timeout=...)`` can kill only the
    immediate wrapper, leaving expensive descendants alive. This helper starts a
    new POSIX session where available and terminates that process group on
    timeout.
    """

    args = tuple(str(part) for part in command)
    begin = time.perf_counter()
    process = subprocess.Popen(
        args,
        cwd=str(cwd) if cwd is not None else None,
        env=dict(env) if env is not None else None,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=os.name == "posix",
    )
    timed_out = False
    terminated_group = False
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
        return_code = int(process.returncode or 0)
    except subprocess.TimeoutExpired:
        timed_out = True
        terminated_group = _terminate_process_tree(
            process,
            grace_seconds=terminate_grace_seconds,
        )
        stdout, stderr = process.communicate()
        return_code = 124
    return ProcessTreeResult(
        command=args,
        return_code=return_code,
        timed_out=timed_out,
        runtime_seconds=round(time.perf_counter() - begin, 6),
        stdout=stdout or "",
        stderr=stderr or "",
        terminated_process_group=terminated_group,
    )


def parse_thread_setting(
    raw: str | None,
    *,
    max_threads: int = 8,
    cpu_count: int | None = None,
    load_average: float | None = None,
) -> int:
    """Parse an explicit integer or ``auto`` thread setting."""

    if raw is None or raw.strip() == "" or raw.strip().lower() == "auto":
        return suggest_thread_count(
            max_threads=max_threads,
            cpu_count=cpu_count,
            load_average=load_average,
        )
    try:
        return max(1, int(raw))
    except ValueError:
        return suggest_thread_count(
            max_threads=max_threads,
            cpu_count=cpu_count,
            load_average=load_average,
        )


def default_thread_count(
    *,
    max_threads: int = 8,
    env_keys: tuple[str, ...] = ("RUBIK_OPTIMAL_H48_THREADS", "RUBIK_OPTIMAL_THREADS"),
) -> int:
    """Return the configured or load-aware default solver thread count."""

    for key in env_keys:
        raw = os.environ.get(key)
        if raw is not None:
            return parse_thread_setting(raw, max_threads=max_threads)
    return suggest_thread_count(max_threads=max_threads)


def parse_gib(raw: float | int | str | None) -> int | None:
    """Parse a GiB value used by CLI memory guards."""

    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return int(value * _GIB)


def parse_vm_stat_available_bytes(output: str) -> int | None:
    """Return a conservative macOS available-memory estimate from ``vm_stat``.

    The value intentionally counts only immediately reusable page classes:
    free, speculative, and purgeable pages.  It is a launch guard for expensive
    native jobs, not a replacement for Activity Monitor's richer pressure model.
    """

    page_match = re.search(r"page size of (\d+) bytes", output)
    if not page_match:
        return None
    page_size = int(page_match.group(1))
    page_counts: dict[str, int] = {}
    for line in output.splitlines():
        match = re.match(r'\s*"?([^":]+)"?:\s+(\d+)\.', line)
        if match:
            page_counts[match.group(1).strip()] = int(match.group(2))
    reusable_pages = (
        page_counts.get("Pages free", 0)
        + page_counts.get("Pages speculative", 0)
        + page_counts.get("Pages purgeable", 0)
    )
    return reusable_pages * page_size


def available_memory_bytes() -> int | None:
    """Best-effort available memory in bytes for launch guards."""

    meminfo = "/proc/meminfo"
    if os.path.exists(meminfo):
        try:
            with open(meminfo, "r", encoding="utf-8") as handle:
                for line in handle:
                    if line.startswith("MemAvailable:"):
                        parts = line.split()
                        return int(parts[1]) * 1024
        except OSError:
            pass
    try:
        completed = subprocess.run(
            ["vm_stat"],
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return parse_vm_stat_available_bytes(completed.stdout)


def evaluate_idle_status(
    *,
    cpu_count: int | None = None,
    load_average: tuple[float, float, float] | None = None,
    available_bytes: int | None = None,
    max_load_1m: float | None = None,
    max_load_5m: float | None = None,
    min_available_memory_bytes: int | None = None,
) -> IdleStatus:
    """Evaluate whether the current machine is safe for a heavy native run."""

    cpus = max(1, int(cpu_count if cpu_count is not None else (os.cpu_count() or 1)))
    if load_average is None:
        try:
            load_average = tuple(float(value) for value in os.getloadavg())  # type: ignore[assignment]
        except (AttributeError, OSError):
            load_average = None
    load_1m = load_average[0] if load_average is not None else None
    load_5m = load_average[1] if load_average is not None else None
    if available_bytes is None and min_available_memory_bytes is not None:
        available_bytes = available_memory_bytes()

    reasons: list[str] = []
    if max_load_1m is not None:
        if load_1m is None:
            reasons.append("one-minute load average unavailable")
        elif load_1m > max_load_1m:
            reasons.append(f"one-minute load {load_1m:.2f} exceeds {max_load_1m:.2f}")
    if max_load_5m is not None:
        if load_5m is None:
            reasons.append("five-minute load average unavailable")
        elif load_5m > max_load_5m:
            reasons.append(f"five-minute load {load_5m:.2f} exceeds {max_load_5m:.2f}")
    if min_available_memory_bytes is not None:
        if available_bytes is None:
            reasons.append("available memory unavailable")
        elif available_bytes < min_available_memory_bytes:
            have_gib = available_bytes / _GIB
            need_gib = min_available_memory_bytes / _GIB
            reasons.append(f"available memory {have_gib:.2f} GiB below {need_gib:.2f} GiB")

    return IdleStatus(
        idle=not reasons,
        cpu_count=cpus,
        load_average_1m=load_1m,
        load_average_5m=load_5m,
        available_memory_bytes=available_bytes,
        max_load_1m=max_load_1m,
        max_load_5m=max_load_5m,
        min_available_memory_bytes=min_available_memory_bytes,
        reasons=tuple(reasons),
    )


def wait_for_idle(
    *,
    max_load_1m: float | None,
    max_load_5m: float | None,
    min_available_memory_bytes: int | None,
    required_consecutive_checks: int = 2,
    check_interval_seconds: float = 60.0,
    timeout_seconds: float | None = None,
    status_provider: Callable[[], IdleStatus] | None = None,
    sleeper: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> tuple[bool, list[IdleStatus]]:
    """Wait until the machine passes the idle guard for enough checks."""

    required = max(1, int(required_consecutive_checks))
    interval = max(0.0, float(check_interval_seconds))
    deadline = None if timeout_seconds is None or timeout_seconds < 0 else monotonic() + timeout_seconds
    consecutive = 0
    samples: list[IdleStatus] = []

    def snapshot() -> IdleStatus:
        if status_provider is not None:
            return status_provider()
        return evaluate_idle_status(
            max_load_1m=max_load_1m,
            max_load_5m=max_load_5m,
            min_available_memory_bytes=min_available_memory_bytes,
        )

    while True:
        status = snapshot()
        samples.append(status)
        if status.idle:
            consecutive += 1
            if consecutive >= required:
                return True, samples
        else:
            consecutive = 0
        if deadline is not None and monotonic() >= deadline:
            return False, samples
        sleeper(interval)

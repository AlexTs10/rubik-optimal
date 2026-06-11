"""Git source snapshot metadata for reproducible generated artifacts."""

from __future__ import annotations

import subprocess
from pathlib import Path


def _run_git(root: Path, args: list[str]) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=root,
            check=False,
            text=True,
            capture_output=True,
        )
    except OSError:
        return None


def capture_source_state(root: Path) -> dict[str, object]:
    """Return source-state metadata suitable for result files.

    A clean commit is reproducible by checkout. An unborn branch or dirty tree is
    useful development evidence, but not a final source baseline.
    """

    inside = _run_git(root, ["rev-parse", "--is-inside-work-tree"])
    if inside is None or inside.returncode != 0 or inside.stdout.strip() != "true":
        return {
            "schema_version": 1,
            "state": "git_unavailable",
            "git_available": inside is not None,
            "has_commit": False,
            "dirty": None,
            "is_reproducible_checkout": False,
            "limitation": "Git repository state could not be inspected; archive the exact source tree before final submission.",
            "reproduction_plan": [
                "Run git status --short and resolve missing Git metadata.",
                "Create an approved source archive or commit before regenerating final artifacts.",
                "Rerun the relevant generation scripts and python scripts/thesis_audit.py.",
            ],
        }

    commit_proc = _run_git(root, ["rev-parse", "HEAD"])
    short_proc = _run_git(root, ["rev-parse", "--short", "HEAD"])
    has_commit = bool(commit_proc and commit_proc.returncode == 0 and commit_proc.stdout.strip())
    commit = commit_proc.stdout.strip() if has_commit and commit_proc else None
    short_commit = short_proc.stdout.strip() if has_commit and short_proc and short_proc.returncode == 0 else None

    status_proc = _run_git(root, ["status", "--porcelain=v1"])
    status_ok = bool(status_proc and status_proc.returncode == 0)
    status_lines = status_proc.stdout.splitlines() if status_ok else []
    # Fail closed: when `git status` itself fails, the working-tree state is
    # UNKNOWN and must never be stamped as a clean (reproducible) checkout.
    dirty: bool | None = bool(status_lines) if status_ok else None

    if not has_commit:
        state = "no_commit"
    else:
        state = str(short_commit or commit)
    if not status_ok:
        state = f"{state}+status_unknown"
    elif dirty:
        state = f"{state}+dirty"

    is_reproducible = has_commit and status_ok and not dirty
    if not status_ok:
        limitation = (
            "git status --porcelain failed, so working-tree cleanliness could not be inspected; "
            "treat this artifact as non-reproducible until the tree state is verified."
        )
    elif is_reproducible:
        limitation = ""
    elif not has_commit and dirty:
        limitation = (
            "Generated from an unborn Git branch with uncommitted/untracked files; "
            "the exact source cannot be checked out by commit SHA."
        )
    elif not has_commit:
        limitation = "Generated before the repository had an initial commit; the exact source cannot be checked out by commit SHA."
    else:
        limitation = "Generated from a dirty working tree; the commit alone does not reproduce the exact source."

    return {
        "schema_version": 1,
        "state": state,
        "git_available": True,
        "has_commit": has_commit,
        "commit": commit,
        "commit_short": short_commit,
        "dirty": dirty,
        "status_entry_count": len(status_lines) if status_ok else None,
        "status_sample": status_lines[:20],
        "is_reproducible_checkout": is_reproducible,
        "limitation": limitation,
        "reproduction_plan": [
            "Review git status --short and decide the intentional source baseline.",
            "Create a real commit or an approved source archive; do not treat no_commit+dirty artifacts as final-submission evidence.",
            "Regenerate final result metadata from that baseline and rerun python scripts/thesis_audit.py.",
        ],
    }


def source_state_label(root: Path) -> str:
    """Return the compact source-state label kept for backward compatibility."""

    return str(capture_source_state(root)["state"])

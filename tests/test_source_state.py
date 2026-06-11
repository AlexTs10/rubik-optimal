import subprocess

from rubik_optimal.source_state import capture_source_state, source_state_label


def _git(root, *args):
    return subprocess.run(["git", *args], cwd=root, text=True, capture_output=True, check=True)


def test_capture_source_state_reports_unborn_dirty_repo(tmp_path):
    _git(tmp_path, "init")
    (tmp_path / "artifact.py").write_text("print('draft')\n", encoding="utf-8")

    state = capture_source_state(tmp_path)

    assert state["state"] == "no_commit+dirty"
    assert state["has_commit"] is False
    assert state["dirty"] is True
    assert state["is_reproducible_checkout"] is False
    assert "cannot be checked out by commit SHA" in state["limitation"]
    assert source_state_label(tmp_path) == "no_commit+dirty"


def test_capture_source_state_accepts_clean_committed_repo(tmp_path):
    _git(tmp_path, "init")
    (tmp_path / "artifact.py").write_text("print('baseline')\n", encoding="utf-8")
    _git(tmp_path, "add", "artifact.py")
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Codex Test",
            "-c",
            "user.email=codex-test@example.invalid",
            "commit",
            "-m",
            "baseline",
        ],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=True,
    )

    state = capture_source_state(tmp_path)

    assert state["has_commit"] is True
    assert state["dirty"] is False
    assert state["is_reproducible_checkout"] is True
    assert state["state"] == state["commit_short"]
    assert state["limitation"] == ""

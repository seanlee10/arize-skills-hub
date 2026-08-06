import subprocess
from pathlib import Path

import pytest

from harness.targets import all_skills, changed_paths, select_targets


def _run(cwd: Path, *args: str) -> None:
    subprocess.run(args, cwd=cwd, check=True, capture_output=True)


def _write_skill(root: Path, name: str, body: str = "# skill\n") -> Path:
    path = root / "skills" / name / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _run(tmp_path, "git", "init", "-b", "main")
    _run(tmp_path, "git", "config", "user.email", "t@example.com")
    _run(tmp_path, "git", "config", "user.name", "T")
    return tmp_path


def _commit(root: Path, message: str) -> None:
    _run(root, "git", "add", "-A")
    _run(root, "git", "commit", "-m", message)


def test_all_skills_excludes_fixtures(repo: Path):
    _write_skill(repo, "dialog-summary")
    fixture = repo / "skills" / "_fixtures" / "malicious-sample" / "SKILL.md"
    fixture.parent.mkdir(parents=True, exist_ok=True)
    fixture.write_text("# evil\n", encoding="utf-8")

    assert [p.parent.name for p in all_skills(repo)] == ["dialog-summary"]


def test_changed_paths_is_none_on_first_commit(repo: Path):
    _write_skill(repo, "a")
    _commit(repo, "first")
    assert changed_paths(repo) is None


def test_changed_paths_lists_files_from_last_commit(repo: Path):
    _write_skill(repo, "a")
    _commit(repo, "first")
    _write_skill(repo, "b")
    _commit(repo, "second")
    assert changed_paths(repo) == ["skills/b/SKILL.md"]


def test_select_targets_scans_everything_on_first_commit(repo: Path):
    _write_skill(repo, "a")
    _write_skill(repo, "b")
    _commit(repo, "first")
    assert [p.parent.name for p in select_targets(repo)] == ["a", "b"]


def test_select_targets_scans_only_changed_skills(repo: Path):
    _write_skill(repo, "a")
    _write_skill(repo, "b")
    _commit(repo, "first")
    _write_skill(repo, "b", "# changed\n")
    _commit(repo, "second")
    assert [p.parent.name for p in select_targets(repo)] == ["b"]


def test_policy_change_forces_full_scan(repo: Path):
    _write_skill(repo, "a")
    _write_skill(repo, "b")
    _commit(repo, "first")
    policy = repo / "policy" / "rules.yaml"
    policy.parent.mkdir(parents=True, exist_ok=True)
    policy.write_text("rules: []\n", encoding="utf-8")
    _commit(repo, "tighten policy")
    assert [p.parent.name for p in select_targets(repo)] == ["a", "b"]


def test_force_all_overrides_diff(repo: Path):
    _write_skill(repo, "a")
    _write_skill(repo, "b")
    _commit(repo, "first")
    _write_skill(repo, "b", "# changed\n")
    _commit(repo, "second")
    assert [p.parent.name for p in select_targets(repo, force_all=True)] == ["a", "b"]


def test_deleted_skill_is_not_a_target(repo: Path):
    _write_skill(repo, "a")
    _write_skill(repo, "b")
    _commit(repo, "first")
    (repo / "skills" / "b" / "SKILL.md").unlink()
    _commit(repo, "remove b")
    assert select_targets(repo) == []


def test_genuine_root_commit_emits_no_warning(repo: Path, capsys):
    """A genuine first commit returns None silently with no warning."""
    _write_skill(repo, "a")
    _commit(repo, "first")
    result = changed_paths(repo)
    assert result is None
    captured = capsys.readouterr()
    assert captured.err == ""


def test_shallow_clone_parent_failure_emits_warning(tmp_path: Path, capsys):
    """A shallow clone where parent lookup fails returns None with a warning."""
    # Create a normal repo with three commits
    full_repo = tmp_path / "full"
    full_repo.mkdir(parents=True, exist_ok=True)
    _run(full_repo, "git", "init", "-b", "main")
    _run(full_repo, "git", "config", "user.email", "t@example.com")
    _run(full_repo, "git", "config", "user.name", "T")
    _write_skill(full_repo, "a")
    _commit(full_repo, "first")
    _write_skill(full_repo, "b")
    _commit(full_repo, "second")
    _write_skill(full_repo, "c")
    _commit(full_repo, "third")

    # Create a shallow clone using file:// URL to actually trigger shallow cloning
    shallow = tmp_path / "shallow"
    _run(
        tmp_path,
        "git",
        "clone",
        "--depth",
        "1",
        f"file://{full_repo}",
        str(shallow),
    )

    # On the shallow clone, HEAD has no parent accessible in the shallow history
    # changed_paths should emit a warning but still return None
    result = changed_paths(shallow)
    assert result is None
    captured = capsys.readouterr()
    assert "Warning: Failed to find parent commit for scanning" in captured.err


def test_damaged_refs_non_shallow_failure_emits_warning(tmp_path: Path, capsys):
    """A repo with damaged refs (parent object missing) emits warning.

    This tests the non-shallow failure case: HEAD has a parent that exists
    in the commit graph but whose object was removed, causing HEAD^ to fail.
    """
    # Create a repo with two commits
    repo = tmp_path / "damaged"
    repo.mkdir(parents=True, exist_ok=True)
    _run(repo, "git", "init", "-b", "main")
    _run(repo, "git", "config", "user.email", "t@example.com")
    _run(repo, "git", "config", "user.name", "T")
    _write_skill(repo, "a")
    _commit(repo, "first")
    _write_skill(repo, "b")
    _commit(repo, "second")

    # Get the hash of the first commit (parent of HEAD)
    parent_hash = subprocess.run(
        ["git", "rev-parse", "HEAD^"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    # Remove the parent object from the git object database
    parent_object = repo / ".git" / "objects" / parent_hash[:2] / parent_hash[2:]
    parent_object.unlink()

    # Now HEAD^ should fail because the parent object is missing
    result = changed_paths(repo)
    assert result is None
    captured = capsys.readouterr()
    assert "Warning: Failed to find parent commit for scanning" in captured.err

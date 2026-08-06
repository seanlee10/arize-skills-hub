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

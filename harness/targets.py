"""Decide which skills a commit needs scanned."""

import subprocess
from pathlib import Path

SKILL_GLOB = "skills/*/SKILL.md"
POLICY_PREFIX = "policy/"


def all_skills(repo_root: Path) -> list[Path]:
    """Every SKILL.md matching the target glob, sorted.

    Fixtures sit one level deeper at skills/_fixtures/<name>/SKILL.md and so do
    not match this glob.
    """
    return sorted(repo_root.glob(SKILL_GLOB))


def changed_paths(repo_root: Path) -> list[str] | None:
    """Paths changed by the last commit, or None when it has no parent."""
    parent = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD^"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if parent.returncode != 0:
        return None

    diff = subprocess.run(
        ["git", "diff", "--name-only", "HEAD^", "HEAD"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in diff.stdout.splitlines() if line]


def select_targets(repo_root: Path, force_all: bool = False) -> list[Path]:
    """Return the SKILL.md paths to scan.

    Falls back to a full scan when force_all is set, when there is no parent
    commit, or when policy/ changed — if the criteria move, already registered
    skills have to be re-judged against them, or the gate keeps a hole.
    """
    if force_all:
        return all_skills(repo_root)

    changed = changed_paths(repo_root)
    if changed is None:
        return all_skills(repo_root)
    if any(path.startswith(POLICY_PREFIX) for path in changed):
        return all_skills(repo_root)

    existing = set(all_skills(repo_root))
    targets = {repo_root / path for path in changed if (repo_root / path) in existing}
    return sorted(targets)

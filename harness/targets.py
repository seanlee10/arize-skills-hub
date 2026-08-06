"""Decide which skills a commit needs scanned."""

import subprocess
import sys
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
    """Paths changed by the last commit, or None when it has no parent.

    If the parent lookup fails, distinguishes between a genuine root commit
    (returns None silently) and other git failures (returns None but emits
    a diagnostic warning to stderr).
    """
    parent = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD^"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if parent.returncode != 0:
        # Parent lookup failed. Determine if HEAD is actually a root commit
        # by checking if it appears in the list of repository root commits.
        root_commits = subprocess.run(
            ["git", "rev-list", "--max-parents=0", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )

        # If rev-list failed, treat as a non-root error case and warn
        if root_commits.returncode != 0:
            parent_error = parent.stderr.strip() if parent.stderr else "(no error message)"
            revlist_error = root_commits.stderr.strip() if root_commits.stderr else "(no error message)"
            print(
                f"Warning: Failed to find parent commit for scanning: {parent_error} "
                f"(diagnostic: {revlist_error})",
                file=sys.stderr,
            )
            return None

        # Get HEAD's commit hash
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        if head.returncode != 0:
            # Unable to get HEAD, treat as error case
            parent_error = parent.stderr.strip() if parent.stderr else "(no error message)"
            print(
                f"Warning: Failed to find parent commit for scanning: {parent_error}",
                file=sys.stderr,
            )
            return None

        head_commit = head.stdout.strip()
        root_commit_list = root_commits.stdout.strip()

        # If HEAD is listed as a root commit, check if it's a genuine root or shallow clone
        if head_commit == root_commit_list:
            # Use git rev-parse --git-dir to find the actual git directory
            # (works even in worktrees/submodules where .git is a file)
            gitdir = subprocess.run(
                ["git", "rev-parse", "--git-dir"],
                cwd=repo_root,
                capture_output=True,
                text=True,
            )
            if gitdir.returncode == 0:
                git_dir_path = Path(gitdir.stdout.strip())
                # Handle relative paths
                if not git_dir_path.is_absolute():
                    git_dir_path = repo_root / git_dir_path
                shallow_file = git_dir_path / "shallow"
                if shallow_file.exists():
                    # Shallow clone - emit warning
                    error_msg = parent.stderr.strip() if parent.stderr else "(no error message)"
                    print(
                        f"Warning: Failed to find parent commit for scanning: {error_msg}",
                        file=sys.stderr,
                    )
                    return None
            # Genuine root commit - return silently
            return None

        # HEAD has a parent but it couldn't be resolved - emit warning
        error_msg = parent.stderr.strip() if parent.stderr else "(no error message)"
        print(
            f"Warning: Failed to find parent commit for scanning: {error_msg}",
            file=sys.stderr,
        )
        return None

    diff = subprocess.run(
        ["git", "diff", "--name-only", "HEAD^", "HEAD"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if diff.returncode != 0:
        # Diff failed (e.g., due to missing objects) - emit warning and return None
        error_msg = diff.stderr.strip() if diff.stderr else "(no error message)"
        print(
            f"Warning: Failed to find parent commit for scanning: {error_msg}",
            file=sys.stderr,
        )
        return None
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

"""run_cli locates JSON inside ax's chatty stdout. These cover what else is in
there besides JSON."""

import subprocess

import pytest

from harness import arize_judge
from harness.arize_judge import JudgeError, run_cli

BANNER = "⚠ New version of ax available.\n"
TRACEBACK = (
    "\x1b[91mTraceback (most recent call last):\n"
    '  File "harness/skill_task.py", line 71, in run_skill\n'
    "skill_task.SkillTaskError: model call failed: overloaded_error\x1b[0m\n"
)


@pytest.fixture
def ax(monkeypatch):
    """Replace the ax subprocess with canned output."""

    def install(stdout="", stderr="", returncode=0):
        def fake_run(*_args, **_kwargs):
            return subprocess.CompletedProcess(
                args=["ax"], returncode=returncode, stdout=stdout, stderr=stderr
            )

        monkeypatch.setattr(arize_judge.subprocess, "run", fake_run)

    return install


class TestJsonLocation:
    def test_finds_json_after_the_upgrade_banner(self, ax):
        ax(stdout=BANNER + '{"id": "EXP1"}')
        assert run_cli(["experiments", "run"])["id"] == "EXP1"

    def test_wraps_a_list_response(self, ax):
        ax(stdout=BANNER + '[{"id": "A"}]')
        assert run_cli(["datasets", "export"])["__list__"] == [{"id": "A"}]

    def test_ignores_the_bracket_inside_an_ansi_escape(self, ax):
        # "\x1b[32m" contains a '[', so a coloured line before the JSON used to
        # be mistaken for the start of a JSON array.
        ax(stdout="\x1b[32mℹ Creating experiment\x1b[0m\n" + '{"id": "EXP1"}')
        assert run_cli(["experiments", "run"])["id"] == "EXP1"


class TestFailureReporting:
    def test_surfaces_a_traceback_instead_of_a_parse_error(self, ax):
        # ax exits 0 but prints a coloured traceback when task rows raise. The
        # bracket in the escape made this a JSON error, which hid the real one.
        ax(stdout=BANNER + TRACEBACK)
        with pytest.raises(JudgeError) as excinfo:
            run_cli(["experiments", "run"])
        assert "SkillTaskError" in str(excinfo.value)
        assert "overloaded_error" in str(excinfo.value)

    def test_does_not_echo_the_payload_when_json_is_missing(self, ax):
        # Argument values carry whole skill bodies; the command label exists so
        # they stay out of error messages, Slack, and job summaries.
        ax(stdout=BANNER)
        with pytest.raises(JudgeError) as excinfo:
            run_cli(["datasets", "append", "DS1", "--json", "SECRET SKILL BODY"])
        assert "SECRET SKILL BODY" not in str(excinfo.value)
        assert "ax datasets append" in str(excinfo.value)

    def test_does_not_echo_the_payload_when_json_is_malformed(self, ax):
        ax(stdout='{"id": ')
        with pytest.raises(JudgeError) as excinfo:
            run_cli(["datasets", "append", "DS1", "--json", "SECRET SKILL BODY"])
        assert "SECRET SKILL BODY" not in str(excinfo.value)

    def test_still_reports_a_non_zero_exit(self, ax):
        ax(stderr="boom", returncode=4)
        with pytest.raises(JudgeError, match="exited 4"):
            run_cli(["tasks", "create-evaluation"])

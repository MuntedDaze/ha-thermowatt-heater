"""Temporary CI formatter diagnostic; delete before approving the PR."""

import subprocess
import sys


def test_show_exact_ruff_format_diff():
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "format", "--diff", "tests/test_audit_regressions_0_9_1.py"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert not result.stdout, result.stdout + result.stderr

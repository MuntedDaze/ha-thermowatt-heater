"""Temporary formatting diagnostic; remove before review."""

import subprocess
import sys


def test_exact_polling_advisor_formatting():
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "format", "--diff", "custom_components/thermann_shadow/polling_advisor.py"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert not result.stdout, result.stdout + result.stderr

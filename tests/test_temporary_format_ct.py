"""Temporary formatter diagnostic; deleted after CI captures the exact diff."""

import subprocess
import sys


def test_exact_ruff_formatter_difference():
    process = subprocess.run(
        [sys.executable, "-m", "ruff", "format", "--diff", "tests/test_generic_heater_power_0_9_2.py"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert not process.stdout, process.stdout + process.stderr

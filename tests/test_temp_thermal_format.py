"""Temporary formatting diagnostic; remove before completion."""

import subprocess
import sys


def test_exact_ruff_diff():
    result = subprocess.run(
        [
            sys.executable, "-m", "ruff", "format", "--diff",
            "custom_components/thermann_shadow/thermal.py",
            "tests/test_metered_thermal_observer_0_9_2.py",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert not result.stdout, result.stdout + result.stderr

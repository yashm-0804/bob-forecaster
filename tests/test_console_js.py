"""Runs the console's JavaScript unit tests (tests/js) under Node.

Skipped only when Node is not installed; CI installs it, so there they run.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

JS_TESTS = Path(__file__).parent / "js" / "console.test.mjs"


def test_console_rendering_and_escaping():
    if shutil.which("node") is None:
        # Optional on a laptop; never silently skipped in CI.
        if os.environ.get("CI"):
            pytest.fail("Node.js is required in CI for the console tests")
        pytest.skip("Node.js is not installed")
    result = subprocess.run(["node", str(JS_TESTS)], capture_output=True, text=True,
                            timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr

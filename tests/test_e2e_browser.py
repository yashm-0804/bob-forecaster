"""The approve-then-dispatch flow in a real browser, against a real server.

Starts the API on a free port with an operator access code set and temporary
stores, then runs tests/e2e/approve_dispatch.mjs, which drives headless Chrome.
Skipped where Chrome or Node is missing; CI has both.
"""

import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    shutil.which("google-chrome") or "", shutil.which("google-chrome-stable") or "",
    shutil.which("chromium") or "", shutil.which("chromium-browser") or "",
]
#: A code of the length the server requires.
CODE = "e2e-access-code-0123456789"
CHROME = next((c for c in CHROME_CANDIDATES if c and Path(c).exists()), None)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _run_in_browser(tmp_path, script, *args):
    """Start the API on a free port with temporary stores, and run one of
    tests/e2e/*.mjs against it in Chrome."""
    if CHROME is None or shutil.which("node") is None:
        if os.environ.get("CI"):
            pytest.fail("Chrome and Node are required in CI for the browser test")
        pytest.skip("needs Chrome and Node")
    port = _free_port()
    env = dict(os.environ, BOB_OPERATOR_TOKEN=CODE,
               BOB_AUDIT_DB=str(tmp_path / "audit.sqlite3"),
               BOB_TELEMETRY_DB=str(tmp_path / "telemetry.sqlite3"))
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api.main:app", "--port", str(port)],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        url = f"http://127.0.0.1:{port}"
        for _ in range(100):
            try:
                urllib.request.urlopen(f"{url}/api/health", timeout=1).close()
                break
            except OSError:
                time.sleep(0.1)
        result = subprocess.run(
            ["node", str(ROOT / "tests" / "e2e" / script), CHROME, url, *args],
            capture_output=True, text=True, timeout=180)
        assert result.returncode == 0, result.stdout + result.stderr
        return result.stdout
    finally:
        server.terminate()
        server.wait(timeout=10)


def test_approve_then_dispatch_in_a_browser(tmp_path):
    _run_in_browser(tmp_path, "approve_dispatch.mjs", CODE)


@pytest.mark.network
def test_the_maplibre_map_in_a_browser(tmp_path):
    """The real map: vendored MapLibre, software WebGL, the live CARTO
    basemap, under the content policy. Needs the network for the basemap,
    so it runs with BOB_NETWORK_TESTS=1, like the other live-service tests."""
    out = _run_in_browser(tmp_path, "maplibre.mjs")
    assert "loaded the basemap and every layer" in out

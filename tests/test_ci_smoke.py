"""CI's image smoke test, run here against a server started as the image
starts it: the Dockerfile's settings, its uvicorn flags, and the settings
ci.yml passes to each container.

Found in review: the smoke test expected a healthy server from an image
started without access codes -- which the image refuses by design -- so the
image job could never have passed. No Docker here, so the image itself is
not built; what it would be started with is."""

import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SMOKE = ROOT / "scripts" / "smoke_test.sh"


def _image_env() -> dict[str, str]:
    """The Dockerfile's ENV settings."""
    text = (ROOT / "Dockerfile").read_text()
    block = re.search(r"^ENV (.*?)(?:\n\n|\n(?=[A-Z]+ ))", text, re.S | re.M)
    assert block, "the Dockerfile sets its environment with ENV"
    lines = [ln.split("#")[0].rstrip(" \\") for ln in block[1].splitlines()]
    return dict(pair.split("=", 1) for ln in lines for pair in ln.split() if "=" in pair)


def _uvicorn_flags() -> list[str]:
    cmd = next(ln for ln in (ROOT / "Dockerfile").read_text().splitlines() if ln.startswith("CMD"))
    return re.findall(r"--(?:no-)?proxy-headers", cmd)


def _ci_containers() -> list[tuple[dict[str, str], str]]:
    """(settings, smoke-test mode) for each container the image job starts."""
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    runs = {}
    for line in ci.splitlines():
        words = shlex.split(line.strip()) if "docker run -d" in line else []
        if words:
            port = next(w.split(":")[0] for w in words if re.fullmatch(r"\d+:8080", w))
            runs[port] = dict(words[i + 1].split("=", 1) for i, w in enumerate(words) if w == "-e")
    calls = re.findall(r"scripts/smoke_test\.sh http://localhost:(\d+) (\S+)", ci)
    assert calls and {port for port, _ in calls} == set(runs), "every container is smoke-tested"
    return [(runs[port], mode) for port, mode in calls]


def _run_as(tmp_path, settings: dict[str, str], mode: str) -> str:
    """Start a server as the image would be started with `settings`, run the
    smoke test against it in `mode`, and return what it printed."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {k: v for k, v in os.environ.items() if not k.startswith("BOB_")}
    env.update(_image_env(), **settings)
    # The image's store paths are under /tmp; these are this test's own.
    env.update(BOB_AUDIT_DB=str(tmp_path / "audit.sqlite3"),
               BOB_TELEMETRY_DB=str(tmp_path / "telemetry.sqlite3"))
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api.main:app", "--port", str(port), *_uvicorn_flags()],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        # Straight to the local server, whatever proxy the environment names.
        smoke_env = {k: v for k, v in os.environ.items() if "proxy" not in k.lower()}
        result = subprocess.run(["bash", str(SMOKE), f"http://localhost:{port}", mode],
                                env=smoke_env, capture_output=True, text=True, timeout=60)
    finally:
        server.terminate()
        server.wait(timeout=10)
    assert result.returncode == 0, f"exit {result.returncode}: {result.stdout}{result.stderr}"
    return result.stdout


needs_curl = pytest.mark.skipif(shutil.which("curl") is None, reason="the smoke test uses curl")


@needs_curl
@pytest.mark.parametrize("settings, mode", _ci_containers())
def test_the_image_smoke_test_passes_as_ci_runs_it(tmp_path, settings, mode):
    assert f"smoke test passed ({mode})" in _run_as(tmp_path, settings, mode)


@needs_curl
def test_the_smoke_test_fails_on_the_mistake_it_was_written_for(tmp_path):
    """An image started without codes is not healthy, and the check for a
    configured image says so rather than passing."""
    settings = next(s for s, mode in _ci_containers() if mode == "no-codes")
    assert "BOB_OPERATOR_TOKEN" not in settings
    assert _image_env().get("BOB_REQUIRE_TOKENS") == "1", "the image fails closed"
    with pytest.raises(AssertionError, match="exit 1"):
        _run_as(tmp_path, settings, "configured")

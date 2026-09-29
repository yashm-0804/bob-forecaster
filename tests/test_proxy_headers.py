"""The server as the image and run.sh start it: X-Forwarded-For is not
trusted, so a caller cannot pose as many addresses to the wrong-code limit.

Found in review: with uvicorn's default, a caller on 127.0.0.1 rotating
X-Forwarded-For got 40 answers of 401 and never a 429."""

import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CODE = "proxy-test-access-code-0123456789"
#: Straight to the local server: an HTTP_PROXY in the environment is for
#: the outside world, and would take these requests elsewhere.
DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _flags_from(path: Path) -> list[str]:
    """The uvicorn flags a launcher passes, so this test follows it."""
    command = next(line for line in path.read_text().splitlines()
                   if "uvicorn api.main:app" in line and not line.lstrip().startswith("#"))
    return re.findall(r"--(?:no-)?proxy-headers", command)


def test_the_image_and_run_sh_both_refuse_forwarded_addresses():
    assert _flags_from(ROOT / "Dockerfile") == ["--no-proxy-headers"]
    assert _flags_from(ROOT / "run.sh") == ["--no-proxy-headers"]


def test_rotating_x_forwarded_for_does_not_escape_the_wrong_code_limit(tmp_path):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = dict(os.environ, BOB_OPERATOR_TOKEN=CODE, BOB_FAILED_AUTH_PER_MIN="5",
               BOB_AUDIT_DB=str(tmp_path / "a.sqlite3"), BOB_TELEMETRY_DB=str(tmp_path / "t.sqlite3"))
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api.main:app", "--port", str(port), *_flags_from(ROOT / "Dockerfile")],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        base = f"http://127.0.0.1:{port}"
        for _ in range(100):
            try:
                DIRECT.open(f"{base}/api/health", timeout=1).close()
                break
            except OSError:
                time.sleep(0.1)
        codes = []
        for i in range(12):
            req = urllib.request.Request(
                f"{base}/api/advisory/NOPE/approve", data=b'{"operator": "X. Guess"}', method="POST",
                headers={"Content-Type": "application/json", "Authorization": "Bearer wrong",
                         "X-Forwarded-For": f"203.0.113.{i}"})
            try:
                DIRECT.open(req, timeout=5).close()
                codes.append(200)
            except urllib.error.HTTPError as e:
                codes.append(e.code)
        assert codes.count(401) == 5 and codes.count(429) == 7, codes
    finally:
        server.terminate()
        server.wait(timeout=10)

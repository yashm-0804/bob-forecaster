"""Time the things the README quotes, and print a table to paste into
docs/BENCHMARK.md.

    python scripts/benchmark.py

The pipeline timing needs a warm data cache (run a replay first); without
one it is skipped and says so. Earth Engine is switched off and Gemini is not
called, so only the model's own work is timed.
"""

from __future__ import annotations

import gzip
import json
import os
import platform
import statistics
import sys
import tempfile
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["EARTHENGINE_OFF"] = "1"
os.environ.pop("GEMINI_API_KEY", None)
os.environ.pop("BOB_OPERATOR_TOKEN", None)
# Time the work, not the write budget: thousands of posts a minute from one
# client is what the budget exists to refuse.
os.environ["BOB_TELEMETRY_WRITES_PER_MIN"] = "1000000"
os.environ["BOB_OPERATOR_WRITES_PER_MIN"] = "1000000"


def timed(fn: Callable[[], object], repeat: int) -> list[float]:
    out: list[float] = []
    for _ in range(repeat):
        start = time.perf_counter()
        fn()
        out.append(time.perf_counter() - start)
    return out


def row(label: str, samples: list[float], unit: str = "ms") -> str:
    scale = 1000 if unit == "ms" else 1
    med = statistics.median(samples) * scale
    p90 = sorted(samples)[int(0.9 * (len(samples) - 1))] * scale
    return f"| {label} | {len(samples)} | {med:.1f} {unit} | {p90:.1f} {unit} |"


def ingest_timings(client: Any, nodes: int, where: Callable[[int], tuple[float, float]],
                   readings: int) -> list[float]:
    """Post `readings` readings round-robin from `nodes` nodes, into a fresh
    store, and time each post."""
    import api.main as main_mod
    from api.audit import AuditLog
    from telemetry.ingest import TelemetryStore

    tmp = Path(tempfile.mkdtemp())
    main_mod.use_stores(AuditLog(tmp / "audit.sqlite3"), TelemetryStore(tmp / "telemetry.sqlite3"))
    t0 = datetime(2025, 10, 28, 12, 0)
    counter = iter(range(readings))

    def ingest() -> None:
        i = next(counter)
        lat, lon = where(i % nodes)
        r = client.post("/api/telemetry", json={
            "node_id": f"B{i % nodes:04d}", "tier": "A", "lat": lat, "lon": lon,
            "elev_m": 3.0, "site_class": "sea_level",
            "ts": (t0 + timedelta(minutes=15 * (i // nodes))).isoformat(),
            "pressure_hpa": 1004.0, "temp_c": 29.0, "rh_pct": 80.0, "battery_v": 3.9, "rssi": -95})
        if r.status_code != 200:
            raise RuntimeError(f"ingest refused a benchmark reading: {r.text}")

    return timed(ingest, readings)


def _under_load(label: str, call: Callable[[], int], clients: int, each: int) -> str:
    """`clients` threads each calling `each` times; one table row, with the
    rate and every answer that was not a 200."""
    import threading

    samples: list[float] = []
    statuses: list[int] = []
    lock = threading.Lock()

    def worker() -> None:
        for _ in range(each):
            start = time.perf_counter()
            status = call()
            with lock:
                samples.append(time.perf_counter() - start)
                statuses.append(status)

    began = time.perf_counter()
    threads = [threading.Thread(target=worker) for _ in range(clients)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wall = time.perf_counter() - began
    others = {c: statuses.count(c) for c in sorted(set(statuses)) if c != 200}
    return row(f"Server, {clients} concurrent clients: {label} "
               f"({len(samples) / wall:.0f}/s; not 200: {others or 'none'})", samples)


def concurrent_rows(clients: int = 50, each: int = 20) -> list[str]:
    """A real server (uvicorn, one worker, as deployed) under `clients`
    concurrent callers: reading a run, and approving with the access code.
    Reports latency and every answer that was not a 200."""
    import socket
    import subprocess
    import urllib.error
    import urllib.request

    code = "benchmark-access-code-0123456789"
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    tmp = Path(tempfile.mkdtemp())
    env = dict(os.environ, BOB_OPERATOR_TOKEN=code, BOB_AUDIT_DB=str(tmp / "audit.sqlite3"),
               BOB_TELEMETRY_DB=str(tmp / "telemetry.sqlite3"))
    server = subprocess.Popen(  # noqa: S603 - this interpreter, fixed arguments, no shell
        [sys.executable, "-m", "uvicorn", "api.main:app", "--port", str(port),
         "--log-level", "warning"],
        cwd=Path(__file__).resolve().parent.parent, env=env)
    base = f"http://127.0.0.1:{port}"

    def local(path: str, body: bytes | None = None, timeout: float = 30) -> Any:
        """A request to the server started above, on this machine: plain
        http to 127.0.0.1 is the point here, not an oversight."""
        req = urllib.request.Request(base + path, data=body, headers={  # noqa: S310 - local
            "Accept-Encoding": "gzip", "Content-Type": "application/json",
            "Authorization": f"Bearer {code}"})
        return urllib.request.urlopen(req, timeout=timeout)  # noqa: S310 - local server

    def status(path: str, body: bytes | None = None) -> int:
        try:
            with local(path, body) as r:
                r.read()
                return int(r.status)
        except urllib.error.HTTPError as e:
            return int(e.code)

    try:
        for _ in range(100):
            try:
                local("/api/health", timeout=1).close()
                break
            except OSError:
                time.sleep(0.1)
        with local("/api/run/montha/48") as r:
            raw = r.read()
            text = gzip.decompress(raw) if r.headers.get("Content-Encoding") == "gzip" else raw
            ident = json.loads(text)["advisories"][0]["identifier"]
        approve = f"/api/advisory/{ident}/approve"
        return [_under_load("GET a run", lambda: status("/api/run/montha/48"), clients, each),
                _under_load("approve an advisory",
                            lambda: status(approve, b'{"operator": "K. Ramesh"}'), clients, each)]
    finally:
        server.terminate()
        server.wait(timeout=10)


def main() -> None:
    import pipeline
    from api.audit import AuditLog
    from telemetry.ingest import TelemetryStore

    rows: list[str] = []
    cache = Path(pipeline.__file__).parent / "data" / "cache"
    if list(cache.glob("osm_15.7_80.6_17.4_82.6_*.json")):
        runs = timed(lambda: pipeline.run("MONTHA", 2025, lead_hours=48.0, use_gemini=False), 3)
        rows.append(row("Pipeline: one Montha forecast cycle, 6,418 assets", runs, "s"))
    else:
        rows.append("| Pipeline cycle | - | skipped: no warm data cache | - |")

    from fastapi.testclient import TestClient

    import api.main as main_mod

    tmp = Path(tempfile.mkdtemp())
    main_mod.use_stores(AuditLog(tmp / "audit.sqlite3"), TelemetryStore(tmp / "telemetry.sqlite3"))
    client = TestClient(main_mod.app, base_url="http://localhost")
    client.get("/api/run/montha/48")                                   # warm the run cache
    rows.append(row("API: GET a run (about 260 KB)", timed(
        lambda: client.get("/api/run/montha/48"), 50)))
    ident = client.get("/api/run/montha/48").json()["advisories"][0]["identifier"]
    rows.append(row("API: approve an advisory", timed(
        lambda: client.post(f"/api/advisory/{ident}/approve", json={"operator": "K. Ramesh"}), 50)))

    rows.append(row("API: ingest one reading, 80 reporting nodes",
                    ingest_timings(client, 80, lambda i: (16.0 + i * 0.01, 81.0 + i * 0.01), 400)))
    # Larger networks, spread over the Andhra-Odisha coast (15.5-20.5 N,
    # 80.5-86.5 E) rather than along one line; each node reports every 15 min.
    for n in (500, 2000):
        side = int(n ** 0.5) + 1
        rows.append(row(f"API: ingest one reading, {n:,} reporting nodes", ingest_timings(
            client, n, lambda i, side=side: (15.5 + 5.0 * (i // side) / side,
                                             80.5 + 6.0 * (i % side) / side), 2 * n)))

    rows.extend(concurrent_rows())

    print(f"Measured {datetime.now():%Y-%m-%d} on {platform.platform()}, "
          f"Python {platform.python_version()}, {platform.processor() or platform.machine()}.\n")
    print("| What | Samples | Median | 90th percentile |")
    print("|---|---:|---:|---:|")
    print("\n".join(rows))


if __name__ == "__main__":
    main()

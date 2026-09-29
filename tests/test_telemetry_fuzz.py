"""Whatever a gateway sends, ingest answers with a result or a refusal --
never an unhandled error.

Seeded, so a failure reproduces. Every field of a valid message is replaced,
one or several at a time, with values of every JSON type and awkward size,
and some messages lose fields or gain unknown ones. Both the store and the
HTTP endpoint are exercised: the store may only raise its three documented
refusals, and the endpoint may only answer 200, 403, 409 or 422.
"""

import json
import random
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from telemetry.ingest import (
    DuplicateObservation,
    TelemetryStore,
    UnknownNode,
    ValidationError,
)

T0 = datetime(2025, 10, 28, 12, 0)

WEIRD = [
    None, True, False, 0, -1, 1, 10**400, -(10**400), 1e308, -1e308, 0.5, "", "x",
    "16.5", "2025-10-28T12:00:00", "0001-01-01T00:00:00", "9999-12-31T23:59:59",
    "A", "Z", "sea_level", [], [1, 2], [None], {}, {"a": 1}, "‮", "a" * 5000,
]


def base(i: int) -> dict:
    return {"node_id": f"F{i % 7:03d}", "tier": "A", "lat": 16.5 + (i % 5) * 0.01,
            "lon": 81.5 + (i % 3) * 0.01, "elev_m": 4.0, "site_class": "sea_level",
            "ts": (T0 + timedelta(minutes=i)).isoformat(), "pressure_hpa": 1004.0,
            "temp_c": 29.0, "rh_pct": 80.0, "battery_v": 3.9, "rssi": -95}


def mutations(n: int, seed: int = 20251028):
    rng = random.Random(seed)
    keys = list(base(0)) + ["rain_mm_15m", "soil_vwc_pct", "tilt_deg", "datum_ref",
                            "water_level_m", "qc_flags", "unknown_field"]
    for i in range(n):
        m = base(i)
        for _ in range(rng.randint(1, 3)):
            action = rng.random()
            key = rng.choice(keys)
            if action < 0.8:
                m[key] = rng.choice(WEIRD)
            elif key in m:
                del m[key]
        yield m


def test_the_store_only_ever_refuses_in_its_documented_ways(tmp_path):
    store = TelemetryStore(tmp_path / "fuzz.sqlite3")
    outcomes = {"stored": 0, "refused": 0}
    for body in mutations(2000):
        try:
            result = store.ingest(body)
        except (ValidationError, DuplicateObservation, UnknownNode):
            outcomes["refused"] += 1
            continue
        assert isinstance(result["fusable"], bool)
        outcomes["stored"] += 1
    assert outcomes["stored"] > 100 and outcomes["refused"] > 100, outcomes


def test_the_endpoint_never_answers_500(tmp_path, monkeypatch):
    import api.main as main

    monkeypatch.setattr(main, "_telemetry", TelemetryStore(tmp_path / "api.sqlite3"))
    client = TestClient(main.app, base_url="http://localhost", raise_server_exceptions=False)
    codes = set()
    for body in mutations(600, seed=7):
        r = client.post("/api/telemetry", content=json.dumps(body),
                        headers={"content-type": "application/json"})
        codes.add(r.status_code)
        assert r.status_code in (200, 403, 409, 413, 422), (r.status_code, body, r.text[:200])
    assert {200, 422} <= codes


@pytest.mark.parametrize("raw", [b"", b"null", b"[]", b"1", b'"x"', b"{", b"\xff\xfe"])
def test_bodies_that_are_not_objects_are_refused(raw, tmp_path, monkeypatch):
    import api.main as main

    monkeypatch.setattr(main, "_telemetry", TelemetryStore(tmp_path / "api.sqlite3"))
    client = TestClient(main.app, base_url="http://localhost", raise_server_exceptions=False)
    r = client.post("/api/telemetry", content=raw, headers={"content-type": "application/json"})
    assert r.status_code in (400, 422), (raw, r.status_code)

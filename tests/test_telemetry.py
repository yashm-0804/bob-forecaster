"""Telemetry ingest, the QC fixes the simulation forced, and features.

The regressions here are the ones a simulated network exposed on its first
run: slow drift never caught, the eye of a cyclone mistaken for a broken
barometer, and the reading after every spike flagged as a second spike.
"""

import math
from datetime import datetime, timedelta

import numpy as np
import pytest

from telemetry import qc
from telemetry.features import pressure_tendency_3h, rain_accumulation
from telemetry.ingest import TelemetryStore, ValidationError, parse

T0 = datetime(2025, 10, 28, 12, 0)


def msg(node: str = "A001", tier: str = "A", lat: object = 16.5, lon: object = 81.5,
        t: datetime = T0, p: float | None = 1004.0, **extra: object) -> dict:
    m = {"node_id": node, "tier": tier, "lat": lat, "lon": lon, "elev_m": 4.0,
         "site_class": "sea_level", "ts": t.isoformat(), "pressure_hpa": p,
         "temp_c": 29.0 + (t.minute % 30) * 0.01 + (t.hour % 5) * 0.1,
         "rh_pct": 80.0 + t.hour % 7, "battery_v": 3.9, "rssi": -95}
    m.update(extra)
    return m


@pytest.fixture
def store(tmp_path):
    return TelemetryStore(tmp_path / "t.sqlite3")


# --- ingest --------------------------------------------------------------

def test_malformed_messages_are_rejected_with_a_reason():
    with pytest.raises(ValidationError, match="missing field"):
        parse({"node_id": "x"})
    with pytest.raises(ValidationError, match="unknown fields"):
        parse(msg(wind_gust_vibes=3))
    with pytest.raises(ValidationError):
        parse(msg(tier="Z"))


def test_clean_reading_is_stored_and_fusable(store):
    r = store.ingest(msg())
    assert r["fusable"] and r["qc_flags"] == []
    assert store.nodes()[0]["readings"] == 1


def test_flagged_readings_are_kept_not_dropped(store):
    """A flagged reading is the evidence for the node's maintenance ticket."""
    r = store.ingest(msg(rain_mm_15m=4.0))      # Tier A has no rain gauge
    assert not r["fusable"]
    assert store.nodes()[0]["flagged"] == 1
    assert store.series("A001", fusable_only=False)
    assert not store.series("A001", fusable_only=True)


def test_reading_after_a_spike_is_not_a_second_spike(store):
    """Regression: the recovery was compared against the spiked reading."""
    store.ingest(msg(t=T0, p=1004.0))
    assert not store.ingest(msg(t=T0 + timedelta(minutes=15), p=1030.0))["fusable"]
    back = store.ingest(msg(t=T0 + timedelta(minutes=30), p=1003.8))
    assert back["fusable"], back["qc_flags"]


def test_spike_limit_scales_with_the_gap():
    """A dropped packet is not a pressure jump."""
    prev = parse(msg(t=T0, p=1004.0))
    later = parse(msg(t=T0 + timedelta(hours=2), p=996.0))   # 8 hPa in 2 h
    assert not qc.has(qc.check_spike(later, prev), qc.Flag.SPIKE)


def test_saturated_humidity_is_not_a_seized_sensor():
    """Air in a cyclone reads 100% for hours. That is weather."""
    hist = [parse(msg(t=T0 + timedelta(minutes=15 * i), rh_pct=100.0,
                      temp_c=27.0 + i * 0.1, p=1004.0 - 0.2 * i)) for i in range(8)]
    assert qc.on(qc.Flag.FLATLINE, "rh_pct") not in qc.check_flatline(hist)


def test_humidity_stuck_below_saturation_is_still_caught():
    """The physical-limit exemption must not become a blind spot."""
    hist = [parse(msg(t=T0 + timedelta(minutes=15 * i), rh_pct=87.0,
                      temp_c=27.0 + i * 0.1, p=1004.0 - 0.2 * i)) for i in range(8)]
    assert qc.on(qc.Flag.FLATLINE, "rh_pct") in qc.check_flatline(hist)


# --- neighbour and drift checks ------------------------------------------

def ring(t, centre_p, n=8, radius_km=25.0, gradient=0.0):
    """Neighbours on a ring, optionally with a linear east-west gradient."""
    out = []
    for k in range(n):
        a = 2 * math.pi * k / n
        dlat = radius_km * math.sin(a) / 111.0
        dlon = radius_km * math.cos(a) / (111.0 * math.cos(math.radians(16.5)))
        out.append(parse(msg(node=f"N{k}", lat=16.5 + dlat, lon=81.5 + dlon, t=t,
                             p=centre_p + gradient * radius_km * math.cos(a))))
    return out


def test_a_storm_gradient_is_not_a_fault():
    """Regression: the median check flagged 186 clean readings near the storm.
    A 0.3 hPa/km gradient puts 15 hPa across the ring; the plane absorbs it."""
    here = parse(msg(p=1000.0))
    assert qc.check_neighbours(here, ring(T0, 1000.0, gradient=0.3)) == []


def road(t, p0, gradient=0.0, jitter_km=0.0, noise=0.0, seed=0):
    """Five nodes along a north-south coast road 5 km west of the node under
    test, the way coastal networks are sited. `gradient` is hPa per km along
    the road."""
    rng = np.random.default_rng(seed)
    out = []
    for k in range(5):
        north_km = -10.0 + 5.0 * k
        east_km = -5.0 + rng.uniform(-jitter_km, jitter_km)
        out.append(parse(msg(node=f"R{k}", t=t, lat=16.5 + north_km / 111.0,
                             lon=81.5 + east_km / (111.0 * math.cos(math.radians(16.5))),
                             p=p0 + gradient * north_km + rng.uniform(-noise, noise))))
    return out


def test_neighbours_along_one_road_do_not_invent_a_gradient_across_it():
    """Found in review: with collinear neighbours the plane's slope across the
    road is undetermined, and a clean node 5 km off it read 966 hPa out."""
    here = parse(msg(p=1004.0))
    fit = qc.neighbour_fit(here, road(T0, 1004.0))
    assert fit is not None and abs(fit[0]) < 0.01
    flagged = sum(bool(qc.check_neighbours(parse(msg(p=1004.0)), road(T0, 1004.0, jitter_km=0.2,
                                                                         noise=0.2, seed=s)))
                  for s in range(200))
    assert flagged == 0


def test_a_gradient_along_the_road_is_absorbed_and_a_fault_beside_it_is_not():
    """0.3 hPa/km along the road puts 6 hPa between its ends; that is the
    storm. A barometer 8 hPa low beside the road is still broken."""
    assert qc.check_neighbours(parse(msg(p=1004.0)), road(T0, 1004.0, gradient=0.3)) == []
    assert qc.check_neighbours(parse(msg(p=996.0)), road(T0, 1004.0, gradient=0.3)) != []


def test_the_neighbour_box_never_cuts_off_a_neighbour_within_the_radius():
    """The query now filters by a box in SQL; the box must hold every point
    the exact distance check would accept, wherever the node is."""
    from telemetry.ingest import NEIGHBOUR_RADIUS_KM, _km, neighbour_box

    rng = np.random.default_rng(7)
    for lat, lon in [(16.5, 81.5), (0.0, 0.0), (-45.0, 170.0), (70.0, 20.0), (84.0, -40.0),
                     (10.0, 179.8), (-10.0, -179.9)] + list(zip(rng.uniform(-85, 85, 200),
                                                                  rng.uniform(-180, 180, 200),
                                                                  strict=True)):
        south, north, west, east = neighbour_box(lat, lon, NEIGHBOUR_RADIUS_KM)
        for bearing in np.linspace(0, 2 * math.pi, 72, endpoint=False):
            for frac in (0.5, 0.99, 1.0):
                d = NEIGHBOUR_RADIUS_KM * frac
                nlat = lat + d * math.cos(bearing) / 111.0
                nlon = lon + d * math.sin(bearing) / (111.0 * max(math.cos(math.radians(nlat)), 1e-6))
                if abs(nlon) > 180 or abs(nlat) > 90:
                    continue
                if _km(lat, lon, nlat, nlon) <= NEIGHBOUR_RADIUS_KM:
                    assert south <= nlat <= north and west <= nlon <= east, (lat, lon, nlat, nlon)


def test_only_nearby_rows_are_read_for_the_neighbour_check(tmp_path):
    """A far node's readings are not neighbours, and no longer leave the
    database to be discarded."""
    store = TelemetryStore(tmp_path / "t.sqlite3")
    for k in range(5):
        store.ingest(msg(node=f"N{k}", lat=16.5 + 0.05 * k, lon=81.55, t=T0))
    store.ingest(msg(node="FAR", lat=19.5, lon=85.0, t=T0))
    ctx = store.context(parse(msg(node="ME", lat=16.6, lon=81.5, t=T0 + timedelta(minutes=5))))
    assert ctx.neighbours is not None
    assert sorted(n.node_id for n in ctx.neighbours) == [f"N{k}" for k in range(5)]


def test_neighbours_posting_at_once_are_checked_against_each_other(tmp_path):
    """Found in review: QC read its neighbours outside the store lock, so two
    nodes posting together were each checked without the other. Now the
    second is always checked against the first, whichever wins the race."""
    import threading

    for trial in range(20):
        store = TelemetryStore(tmp_path / f"t{trial}.sqlite3")
        for k in range(4):              # four settled neighbours around a point
            store.ingest(msg(node=f"N{k}", lat=16.5 + 0.05 * (k % 2), lon=81.5 + 0.05 * (k // 2),
                             t=T0))
        seen: dict[str, int] = {}
        real = store.context

        def counting(obs, real=real, seen=seen):
            ctx = real(obs)
            seen[obs.node_id] = len(ctx.neighbours or [])
            return ctx

        store.context = counting
        barrier = threading.Barrier(2)

        def post(node, barrier=barrier, store=store):
            barrier.wait()
            store.ingest(msg(node=node, lat=16.525, lon=81.525, t=T0 + timedelta(minutes=1)))

        threads = [threading.Thread(target=post, args=(n,)) for n in ("P", "Q")]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert sorted(seen.values()) == [4, 5], seen


def test_a_broken_barometer_still_disagrees():
    here = parse(msg(p=1010.0))
    assert qc.check_neighbours(here, ring(T0, 1000.0)) != []


def test_the_eye_is_not_a_fault_when_a_background_explains_it():
    """Regression: the node 9 km from landfall read the eye and was flagged."""
    here = parse(msg(p=992.0))
    nbrs = ring(T0, 1000.0)
    assert qc.check_neighbours(here, nbrs) != []            # no background: looks broken
    eye = lambda lat, lon: 992.0 if abs(lat - 16.5) < 0.05 and abs(lon - 81.5) < 0.05 else 1000.0
    assert qc.check_neighbours(here, nbrs, background=eye) == []


def test_slow_drift_is_caught():
    """Regression: a 0.06 hPa/h creep went uncaught for two days."""
    residuals = [1.5 + 0.01 * i for i in range(20)]
    assert qc.has(qc.check_drift(residuals), qc.Flag.DRIFT_SUSPECTED)


def test_a_recovered_node_is_not_drifting():
    """Regression: after the eye passed, the 12 h mean kept flagging a node
    that was reading correctly again."""
    residuals = [0.0] * 8 + [-3.5] * 6 + [0.1] * 8
    assert qc.check_drift(residuals) == []


# --- features ------------------------------------------------------------

def test_pressure_tendency_over_three_hours():
    series = [parse(msg(t=T0 + timedelta(minutes=15 * i), p=1004.0 - 0.3 * i)) for i in range(13)]
    assert pressure_tendency_3h(series, T0 + timedelta(hours=3)) == pytest.approx(-3.6, abs=0.01)


def test_tendency_refuses_a_short_record():
    series = [parse(msg(t=T0 + timedelta(minutes=15 * i))) for i in range(3)]
    assert pressure_tendency_3h(series, T0 + timedelta(minutes=30)) is None


def test_rain_accumulates_only_from_gauges():
    series = [parse(msg(tier="B", t=T0 + timedelta(minutes=15 * i), rain_mm_15m=2.5)) for i in range(4)]
    assert rain_accumulation(series, T0 + timedelta(hours=1)) == 10.0


# --- API -----------------------------------------------------------------

def test_api_ingest_and_listing(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import api.main as main
    monkeypatch.setattr(main, "_telemetry", TelemetryStore(tmp_path / "live.sqlite3"))
    client = TestClient(main.app, base_url="http://localhost")
    assert client.post("/api/telemetry", json=msg()).json()["fusable"] is True
    assert client.post("/api/telemetry", json={"node_id": "x"}).status_code == 422
    assert client.get("/api/telemetry/nodes").json()[0]["node_id"] == "A001"


# --- validation: what cannot be a reading is refused before it is stored -----

@pytest.mark.parametrize("field, value, reason", [
    ("lat", "abc", "lat must be a number"),
    ("lat", 1e308, "outside"),
    ("lon", -181.0, "outside"),
    ("pressure_hpa", "x", "pressure_hpa must be a number"),
    ("battery_v", [1, 2], "battery_v must be a number"),
    ("temp_c", True, "temp_c must be a number"),
    ("pressure_hpa", float("nan"), "finite"),
    ("node_id", 123, "node_id"),
    ("node_id", "../../etc", "node_id"),
    ("node_id", "x" * 65, "node_id"),
    ("ts", 20251028, "ISO 8601"),
    ("ts", "2099-01-01T00:00:00", "future"),
    ("soil_vwc_pct", "wet", "soil_vwc_pct"),
    ("datum_ref", "d" * 65, "datum_ref"),
])
def test_values_that_cannot_be_readings_are_refused(field, value, reason):
    with pytest.raises(ValidationError, match=reason):
        parse(msg(**{field: value}))


def test_a_poisoned_message_cannot_break_ingest_for_its_neighbours(store):
    """A text latitude used to be stored as trusted, and then crashed the
    neighbour check for every node within 40 km."""
    with pytest.raises(ValidationError):
        store.ingest(msg(node="BAD", lat="abc"))
    r = store.ingest(msg(node="A002", t=T0 + timedelta(minutes=1)))
    assert r["fusable"] is True


def test_a_dead_channel_is_null_not_missing():
    assert parse(msg(temp_c=None)).temp_c is None
    body = msg(); del body["temp_c"]
    with pytest.raises(ValidationError, match="missing field: temp_c"):
        parse(body)


def test_timestamps_are_stored_as_one_utc_form():
    """Text comparison of times in SQL only works if every row is written the
    same way; an offset and its UTC equivalent must land identically."""
    assert parse(msg(t=T0)).ts == "2025-10-28T12:00:00"
    assert parse(msg(ts="2025-10-28T17:30:00+05:30")).ts == "2025-10-28T12:00:00"
    assert parse(msg(ts="2025-10-28T12:00:00Z")).ts == "2025-10-28T12:00:00"


def test_flags_are_computed_never_taken_from_the_sender():
    assert parse(msg(qc_flags=["trust_me"])).qc_flags == []


def test_a_timestamp_before_the_network_existed_is_refused_not_a_crash():
    """Year 1 used to overflow the window arithmetic and return 500."""
    for ts in ("0001-01-01T00:00:00", "0001-01-01T00:00:00+05:30", "1999-12-31T23:59:59"):
        with pytest.raises(ValidationError):
            parse(msg(ts=ts))


def test_a_repeated_reading_is_refused(store):
    from telemetry.ingest import DuplicateObservation

    store.ingest(msg())
    with pytest.raises(DuplicateObservation):
        store.ingest(msg())
    assert len(store.series("A001", fusable_only=False)) == 1


def test_with_a_registry_only_registered_nodes_may_report(tmp_path):
    """Invented neighbours could otherwise outvote a real node's barometer."""
    from telemetry.ingest import UnknownNode, load_registry

    reg = tmp_path / "nodes.json"
    reg.write_text('["A001", "A002"]')
    store = TelemetryStore(tmp_path / "t.sqlite3", registry=load_registry(str(reg)))
    assert store.ingest(msg())["fusable"] is True
    with pytest.raises(UnknownNode):
        store.ingest(msg(node="FAKE1"))
    assert load_registry(None) is None
    reg.write_text('{"not": "a list"}')
    with pytest.raises(ValueError, match="JSON list"):
        load_registry(str(reg))


@pytest.mark.parametrize("setting", ['["A001"]', "/no/such/nodes.json", "not json", '{"A001": 1}'])
def test_a_misconfigured_registry_refuses_telemetry_and_says_so(tmp_path, monkeypatch, setting):
    """Found in review: the README described the setting as a JSON list, the
    code read it as a path, and every post was a bare 500 while health said
    ok. Now: a 503 naming the problem, and health reporting it."""
    from fastapi.testclient import TestClient

    import api.main as main

    target = setting
    if setting in ("not json", '{"A001": 1}'):
        target = str(tmp_path / "nodes.json")
        (tmp_path / "nodes.json").write_text(setting)
    monkeypatch.setenv("BOB_NODE_REGISTRY", target)
    monkeypatch.setenv("BOB_TELEMETRY_DB", str(tmp_path / "live.sqlite3"))
    monkeypatch.setattr(main, "_telemetry", None)
    client = TestClient(main.app, base_url="http://localhost")
    r = client.post("/api/telemetry", json=msg())
    assert r.status_code == 503
    assert "node registry" in r.json()["detail"] and "JSON list" in r.json()["detail"]
    assert main._telemetry is None                   # nothing was opened to all nodes
    health = client.get("/api/health").json()
    assert health["ok"] is False and "node registry" in health["problems"][0]
    assert target not in str(health)                 # no path in a public response


def test_a_good_registry_is_healthy(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import api.main as main

    (tmp_path / "nodes.json").write_text('["A001"]')
    monkeypatch.setenv("BOB_NODE_REGISTRY", str(tmp_path / "nodes.json"))
    health = TestClient(main.app, base_url="http://localhost").get("/api/health").json()
    assert health["ok"] is True and health["problems"] == []


def test_the_api_maps_telemetry_refusals_to_status_codes(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import api.main as main
    from telemetry.ingest import load_registry

    reg = tmp_path / "nodes.json"
    reg.write_text('["A001"]')
    monkeypatch.setattr(main, "_telemetry", TelemetryStore(
        tmp_path / "live.sqlite3", registry=load_registry(str(reg))))
    client = TestClient(main.app, base_url="http://localhost")
    assert client.post("/api/telemetry", json=msg()).status_code == 200
    assert client.post("/api/telemetry", json=msg()).status_code == 409
    assert client.post("/api/telemetry", json=msg(node="FAKE1")).status_code == 403
    assert client.post("/api/telemetry", json=msg(ts="0001-01-01T00:00:00")).status_code == 422


# --- dead sensors and late readings -------------------------------------------

def test_a_dead_barometer_is_kept_flagged_and_never_crashes_its_neighbours(store):
    """Found in review: a null pressure passed validation, was stored as
    fusable, and then raised in every nearby node's neighbour check."""
    store.ingest(msg(node="A001"))
    dead = store.ingest(msg(node="A002", p=None, t=T0 + timedelta(minutes=1)))
    assert "missing:pressure_hpa" in dead["qc_flags"]
    assert dead["fusable"] is False
    after = store.ingest(msg(node="A003", t=T0 + timedelta(minutes=2)))
    assert after["fusable"] is True


def test_a_dead_battery_monitor_is_a_maintenance_note_not_a_crash(store):
    r = store.ingest(msg(battery_v=None))
    assert "missing:battery_v" in r["qc_flags"]
    assert r["fusable"] is True, "the readings themselves are fine"


def test_a_dead_thermometer_leaves_pressure_usable():
    obs = parse(msg(temp_c=None))
    flags = qc.run(obs)
    assert "missing:temp_c" in flags
    assert qc.is_fusable(flags, channel="pressure_hpa")
    assert not qc.is_fusable(flags)


def test_live_ingest_flags_a_reading_that_arrives_late(tmp_path):
    from telemetry.ingest import utc_now

    live = TelemetryStore(tmp_path / "live.sqlite3", clock=utc_now)
    fresh = live.ingest(msg(t=utc_now() - timedelta(minutes=5)))
    late = live.ingest(msg(node="A002", t=utc_now() - timedelta(hours=3)))
    assert qc.Flag.STALE not in fresh["qc_flags"]
    assert qc.Flag.STALE in late["qc_flags"] and late["fusable"] is False


@pytest.mark.parametrize("field, value", [
    ("lat", 10**400), ("rssi", 10**400), ("soil_vwc_pct", [10**400]),
])
def test_numbers_too_large_for_a_float_are_refused_not_a_crash(field, value):
    """Found in review: an integer literal beyond float range raised
    OverflowError, which was not caught, and the API returned 500."""
    body = msg()
    body[field] = value
    if field == "soil_vwc_pct":
        body["tier"] = "E"
    with pytest.raises(ValidationError):
        parse(body)

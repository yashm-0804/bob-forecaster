"""The whole pipeline, end to end, with no network and no caches.

Everything external is replaced by something local: a small set of assets
standing in for OpenStreetMap, flat placeholder terrain, the perturbed
ensemble and parametric rain. Outbound HTTP is made to fail, so this test
proves the run needs none -- a fresh clone on a CI runner exercises the same
code path as a laptop with a warm cache.
"""

import json
import urllib.request

import pytest

import pipeline
from advisory import cap
from exposure.osm import Asset

ASSETS = [
    Asset("n1", "substation", "Kakinada Sub station", 16.95, 82.24,
          {"power": "substation", "voltage": "220000"}),
    Asset("n2", "substation", "Narasapuram Substation", 16.44, 81.70,
          {"power": "substation", "voltage": "132000"}),
    Asset("n3", "hospital", "Government Hospital, Narasapuram", 16.43, 81.69,
          {"amenity": "hospital", "emergency": "yes"}),
    Asset("n4", "hospital", "Area Hospital, Amalapuram", 16.58, 82.01,
          {"amenity": "hospital"}),
    Asset("w5", "road_segment", "", 16.60, 81.90, {"highway": "trunk", "ref": "NH216"}),
    Asset("n6", "shelter", "Cyclone Shelter, Antarvedi", 16.33, 81.73,
          {"amenity": "shelter", "shelter_type": "cyclone"}),
]


def _no_network(*args, **kwargs):
    raise AssertionError("the offline pipeline tried to use the network")


@pytest.fixture(scope="module")
def offline_run(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    mp.setenv("EARTHENGINE_OFF", "1")
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY_2"):
        mp.delenv(name, raising=False)
    mp.setattr(urllib.request, "urlopen", _no_network)
    mp.setattr(pipeline, "load_assets", lambda bbox: list(ASSETS))
    try:
        result = pipeline.run("MONTHA", 2025, lead_hours=48.0, n_members=8,
                              terrain_prefer="flat", ensemble_source="perturbed",
                              rain_source="r-cliper")
        path = pipeline.export(result, tmp_path_factory.mktemp("runs"))
    finally:
        mp.undo()
    return result, path


def _strict(text):
    """Parse as a browser would: NaN and Infinity are not JSON."""
    def refuse(token):
        raise ValueError(f"{token} is not valid JSON")
    return json.loads(text, parse_constant=refuse)


def test_every_asset_is_scored_and_ranked(offline_run):
    result, _ = offline_run
    assert len(result.risks) == len(ASSETS)
    scores = [r.consequence for r in result.risks]
    assert scores == sorted(scores, reverse=True)
    assert all(0.0 <= r.p_failure_mean <= 1.0 for r in result.risks)


def test_the_export_is_strict_json_a_browser_can_parse(offline_run):
    _, path = offline_run
    payload = _strict(path.read_text())
    assert payload["summary"]["storm"] == "Montha"
    assert len(payload["assets"]) == len(ASSETS)
    assert {"p_gust_90kmh", "p_tide_1m", "rain_mm"} <= set(payload["layers"])


def test_sources_are_recorded_as_what_actually_ran(offline_run):
    s = offline_run[0].summary
    assert s["terrain_source"] == "flat-placeholder"
    assert s["ensemble"]["source"] == "perturbed"
    assert s["rainfall"]["source"] == "r-cliper"
    assert s["drafting"]["engine"] == "template"
    assert s["drafting"]["drafted_by_model"] == 0


def test_satellite_checks_say_why_they_did_not_run(offline_run):
    observed = offline_run[0].summary["verification"]["observed"]
    assert observed == {"available": False, "reason": observed["reason"]}
    assert "EARTHENGINE_OFF" in observed["reason"]


def test_ensemble_verification_reports_its_own_limitation(offline_run):
    """Self-verification must not read as a skill claim."""
    v = offline_run[0].summary["verification"]["ensemble"]
    assert "not whether the underlying forecast has skill" in v["caveat"]
    assert 0.0 <= v["envelope_hit_rate"] <= 1.0
    assert v["mean_track_error_km"] >= 0


def test_cap_certainty_follows_probability_and_urgency_the_lead_time(offline_run):
    """Found in review: urgency and certainty came from the consequence band,
    so an advisory whose assets were 13-18% likely to fail said "Likely".
    Now certainty follows the most likely listed asset, urgency the lead
    time, and the send time is the forecast cycle, not the replay's clock."""
    import re

    for a in offline_run[0].advisories:
        xml = a.to_cap_xml()
        worst = max(asset["p_failure"] for asset in a.assets)
        certainty = re.findall(r"<certainty>(\w+)</certainty>", xml)
        assert certainty and set(certainty) == {cap.cap_certainty(worst)}
        if worst <= 0.5:
            assert "Likely" not in certainty
        assert set(re.findall(r"<urgency>(\w+)</urgency>", xml)) == {cap.cap_urgency(a.hours_to_landfall)}
        assert a.sent.tzinfo is not None, "the forecast cycle, in UTC"


def test_cap_urgency_and_certainty_by_their_definitions():
    assert [cap.cap_urgency(h) for h in (6, 12, 13, 24, 25, 72, None)] == [
        "Immediate", "Immediate", "Expected", "Expected", "Future", "Future", "Unknown"]
    assert [cap.cap_certainty(p) for p in (0.9, 0.51, 0.5, 0.18, 0.05, 0.04, 0.0, None)] == [
        "Likely", "Likely", "Possible", "Possible", "Possible", "Unlikely", "Unlikely", "Unknown"]


def test_every_advisory_is_an_exercise_awaiting_approval(offline_run):
    for a in offline_run[0].advisories:
        assert "<status>Exercise</status>" in a.to_cap_xml()
        assert a.approved is False


def test_an_unknown_source_is_an_error_not_a_silent_fallback():
    with pytest.raises(ValueError, match="rain_source"):
        pipeline.run(rain_source="gsf")
    with pytest.raises(ValueError, match="ensemble_source"):
        pipeline.run(ensemble_source="weatherlabs")


# --- satellite checks, with the satellites replaced ------------------------

@pytest.fixture
def signed_in(monkeypatch):
    """Earth Engine 'available', and each observation a recorded array."""
    import numpy as np

    from ingest import earthengine
    from verify import satellite

    monkeypatch.setattr(earthengine, "availability", lambda: (True, "signed in, project test"))

    def rain(start, end, lats, lons):
        return np.full(lats.shape, 120.0), {"source": "fake IMERG", "start": start.isoformat(),
                                             "end": end.isoformat()}

    def flood(landfall, bbox, lats, lons):
        f = np.zeros(lats.shape); f[: lats.shape[0] // 2] = 0.3
        return f, {"source": "fake S1"}

    def lights(landfall, lats, lons):
        return np.full(lats.shape, 0.6), {"source": "fake VIIRS", "lit_cells": lats.size}

    monkeypatch.setattr(satellite, "observed_rain", rain)
    monkeypatch.setattr(satellite, "flood_fraction", flood)
    monkeypatch.setattr(satellite, "nightlight_drop", lights)
    return satellite


def _observe(result, grids_members=2):
    from datetime import datetime

    g = result.grids
    s = result.summary
    return pipeline._observe(
        result.storm, datetime.fromisoformat(s["landfall_time"]), pipeline.ANDHRA_COAST,
        g, result.land, result.risks, [g.rain_mm] * grids_members, [g.rain_mm] * grids_members,
        s["rainfall"], datetime.fromisoformat(s["forecast_time"]))


def test_every_check_runs_when_its_observation_arrives(offline_run, signed_in):
    observed, rain_index = _observe(offline_run[0])
    assert observed["available"] is True
    assert observed["rain"]["forecast"]["label"] == "r-cliper"
    assert "r_cliper" not in observed["rain"], "R-CLIPER is not compared with itself"
    assert observed["flood"]["observed_flooded_cells"] > 0
    assert observed["flood"]["where"]["observed_flooded"] is not None
    assert observed["outage"]["substations_with_lights"] == 2
    assert rain_index is not None and float(rain_index.max()) == 120.0


def test_one_failed_check_does_not_take_the_others_down(offline_run, signed_in, monkeypatch):
    def no_pass(landfall, bbox, lats, lons):
        raise LookupError("no same-orbit Sentinel-1 pair around landfall")

    monkeypatch.setattr(signed_in, "flood_fraction", no_pass)
    observed, _ = _observe(offline_run[0])
    assert observed["flood"] == {"error": "LookupError: no same-orbit Sentinel-1 pair around landfall"}
    assert "forecast" in observed["rain"]
    assert observed["outage"]["substations_with_lights"] == 2   # scored, not errored
    json.dumps(pipeline.json_safe(observed), allow_nan=False)


def test_an_approval_covers_exactly_the_text_that_was_read(offline_run):
    """Identifiers carry a fingerprint of the final text, so a regenerated
    cycle whose words changed cannot inherit the old approval."""
    import re
    from dataclasses import replace

    for a in offline_run[0].advisories:
        base, digest = a.identifier.rsplit("-", 1)
        assert re.fullmatch(r"[0-9a-f]{8}", digest)
        unsealed = replace(a, identifier=base)
        assert unsealed.sealed().identifier == a.identifier, "same text, same identifier"
        edited = replace(unsealed, instruction=a.instruction + " Also check the pumps.")
        assert edited.sealed().identifier != a.identifier
        later = replace(unsealed, sent=unsealed.sent.replace(year=2030))
        assert later.sealed().identifier == a.identifier, "the send time is not content"
        assert f"<identifier>{a.identifier}</identifier>" in a.to_cap_xml()


# --- the thesis, recomputed rather than read back ------------------------------

def test_a_weak_storm_damages_through_water_not_wind(offline_run):
    """Montha peaked at 93 km/h, barely past the wind damage threshold. Run
    through the model -- not read from the committed snapshot -- no asset's
    risk is driven by wind."""
    result = offline_run[0]
    assert result.summary["peak_wind_kmh"] < 100
    assert result.summary["driver_split"]["wind"] == 0


def test_the_export_has_the_shape_of_the_committed_runs(offline_run):
    """The committed replays and today's exporter must agree on structure,
    so a code change that alters the payload cannot leave stale files behind
    unnoticed."""
    from pathlib import Path

    _, path = offline_run
    fresh = _strict(path.read_text())
    committed = _strict((Path(__file__).resolve().parent.parent
                         / "data" / "runs" / "montha_48h.json").read_text())
    committed.pop("changes", None)                  # added by the agent, not export
    assert set(fresh) == set(committed)
    assert set(fresh["summary"]) == set(committed["summary"])
    assert set(fresh["advisories"][0]) == set(committed["advisories"][0])
    assert set(fresh["assets"][0]) == set(committed["assets"][0])


def test_the_flood_check_scores_without_terrain(offline_run, signed_in):
    """With no terrain the check cannot say where the water sits, but it
    must still score rather than fail."""
    from dataclasses import replace

    result = offline_run[0]
    no_terrain = replace(result, grids=replace(result.grids, terrain=None))
    observed, _ = _observe(no_terrain)
    assert "contingency_at_p50" in observed["flood"]
    assert "where" not in observed["flood"]

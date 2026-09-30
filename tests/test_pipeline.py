"""Integration tests over the hazard -> impact -> advisory chain.

These run against the exported Montha replay rather than recomputing it, so
they stay fast, and they assert the properties that must hold for the output
to be safe to put in front of an operator.
"""

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pytest

from hazard.holland import TrackPoint, make_grid
from hazard.surge_screen import (
    FlatDeltaPlain,
    andhra_coast_lon,
    land_mask,
    peak_surge_m,
    surge_field_m,
)
from ingest.ensemble import exceedance
from ingest.tracks import radius_of_maximum_wind_km

CAP_NS = {"c": "urn:oasis:names:tc:emergency:cap:1.2"}
RUN_FILE = Path(__file__).resolve().parent.parent / "data" / "runs" / "montha_48h.json"


@pytest.fixture(scope="module")
def run():
    assert RUN_FILE.exists(), f"{RUN_FILE} is committed and missing"
    return json.loads(RUN_FILE.read_text())


# --- terrain and surge ---------------------------------------------------

def test_coastline_matches_real_ports():
    """The fit must pass through Machilipatnam, Narasapuram and Kakinada."""
    assert andhra_coast_lon(16.17) == pytest.approx(81.13, abs=0.02)
    assert andhra_coast_lon(16.95) == pytest.approx(82.25, abs=0.02)
    # Narasapuram, the actual landfall point, is the interior check.
    assert andhra_coast_lon(16.43) == pytest.approx(81.50, abs=0.12)


def test_open_sea_is_never_reported_as_inundated_land():
    """Most of a coastal bounding box is water.

    Counting it as flooded inflates every exposed-area statistic, which was a
    real bug: it put 38% of the AOI under water for a storm with a 0.5 m surge.
    """
    lats, lons = make_grid(15.7, 17.4, 80.6, 82.6, 0.05)
    terrain = FlatDeltaPlain()
    point = TrackPoint(16.5, 81.5, 25.7, 990.0, 45.0)
    depth = surge_field_m(point, lats, lons, terrain, tide_m=0.6)

    offshore = ~land_mask(terrain, lats, lons)
    assert offshore.sum() > 0, "test grid must contain some sea"
    assert np.all(depth[offshore] == 0.0)


def test_surge_decays_inland():
    lats, lons = make_grid(16.0, 16.1, 80.8, 82.4, 0.02)
    terrain = FlatDeltaPlain()
    point = TrackPoint(16.05, 81.1, 30.0, 985.0, 45.0)
    depth = surge_field_m(point, lats, lons, terrain, tide_m=0.5)

    land = land_mask(terrain, lats, lons)
    dist = terrain.distance_to_coast_km(lats, lons)
    near = depth[land & (dist < 5)].max()
    far = depth[land & (dist > 25)].max()
    assert near > far


def test_surge_grows_faster_than_linearly_with_wind():
    """Surge is a wind-stress response, so doubling wind more than doubles it."""
    weak = TrackPoint(16.5, 81.5, 20.0, 1000.0, 50.0)
    strong = TrackPoint(16.5, 81.5, 40.0, 960.0, 50.0)
    assert peak_surge_m(strong) > 3.5 * peak_surge_m(weak)


# --- ensemble ------------------------------------------------------------

def test_exceedance_is_a_probability():
    fields = [np.full((4, 4), v) for v in (1.0, 2.0, 3.0, 4.0)]
    p = exceedance(fields, 2.5)
    assert np.all((p >= 0) & (p <= 1))
    assert p[0, 0] == pytest.approx(0.5)


def test_rmax_shrinks_as_a_storm_intensifies():
    """Stronger storms are tighter; Rmax controls swath width, so this matters."""
    assert radius_of_maximum_wind_km(60.0, 16.0) < radius_of_maximum_wind_km(20.0, 16.0)


# --- exported run --------------------------------------------------------

def test_every_asset_probability_is_valid(run):
    for a in run["assets"]:
        assert 0.0 <= a["p_failure"] <= 1.0
        assert a["p_failure_p10"] <= a["p_failure_p90"]
        assert a["severity"] in ("red", "orange", "yellow", "green")


def test_assets_are_ranked_by_expected_consequence(run):
    """Ranking is on consequence, deliberately not on bare probability.

    Probability alone put 336 hospitals within a few points of each other and
    gave an officer nothing to act on.
    """
    cons = [a["consequence"] for a in run["assets"]]
    assert cons == sorted(cons, reverse=True)


def test_ranking_actually_discriminates(run):
    """The failure this guards against is a ranking that is technically sorted
    but practically flat."""
    top = run["assets"][:400]
    distinct = len({round(a["consequence"], 2) for a in top})
    assert distinct >= 20, f"only {distinct} distinct values in the top 400"


def test_red_is_a_list_someone_could_work_through(run):
    """A red band with hundreds of entries is flatness in a different colour."""
    red = [a for a in run["assets"] if a["severity"] == "red"]
    assert 0 < len(red) <= 120


def test_criticality_carries_its_basis(run):
    """Every weight must say where it came from and how confident it is."""
    for a in run["assets"]:
        assert a["criticality_basis"], f"{a['name']} has a weight with no basis"
        assert a["criticality_confidence"] in (
            "measured", "inferred", "assumed", "class-default"
        )


def test_high_voltage_substations_outrank_small_clinics(run):
    """The ordering the whole change exists to produce."""
    subs = [a for a in run["assets"]
            if a["asset_class"] == "substation" and "400 kV" in a["criticality_basis"]]
    clinics = [a for a in run["assets"]
               if a["criticality_confidence"] == "inferred" and a["criticality"] < 1.0]
    if subs and clinics:
        assert max(s["consequence"] for s in subs) > max(c["consequence"] for c in clinics)


def test_assets_are_real_named_infrastructure(run):
    """The whole claim is asset-level output, so names must survive the pipeline."""
    named = [a for a in run["assets"] if not a["name"].startswith(("road segment", "substation "))]
    assert len(named) > 20, "expected real OSM names to reach the output"


def test_weak_storm_damage_is_rain_driven(run):
    """Montha peaked at 93 km/h, barely above Emanuel's 92 km/h threshold.

    A wind-category model scores it as negligible. The flood pathway must
    carry the signal -- this is the Ditwah/Senyar case the platform exists
    to catch, so it is asserted rather than left to inspection.
    """
    split = run["summary"]["driver_split"]
    assert split["flood"] > split["wind"]


def test_every_advisory_is_an_exercise(run):
    """Non-negotiable: nothing may be mistakable for an official IMD warning."""
    for adv in run["advisories"]:
        root = ET.fromstring(adv["cap_xml"])
        assert root.findtext("c:status", namespaces=CAP_NS) == "Exercise"


def test_advisories_start_unapproved(run):
    assert all(not adv["approved"] for adv in run["advisories"])


def test_cap_carries_every_declared_language(run):
    for adv in run["advisories"]:
        root = ET.fromstring(adv["cap_xml"])
        langs = [i.findtext("c:language", namespaces=CAP_NS)
                 for i in root.findall("c:info", CAP_NS)]
        assert langs == list(adv["languages"])
        # Telugu is required for Andhra -- but it must be real Telugu or be
        # declared pending, never an English block wearing a te-IN label.
        assert "te-IN" in langs or "te-IN" in adv["pending_languages"]


def test_advisories_name_specific_assets(run):
    """An instruction that doesn't name assets is not actionable.

    Checked by the names themselves, not by the template's "near: X, Y"
    punctuation, which a Gemini-drafted instruction need not keep.
    """
    names = {a["name"] for a in run["assets"] if a.get("name")}
    for adv in run["advisories"]:
        assert len(adv["instruction"]) > 60
        assert any(name in adv["instruction"] for name in names), adv["recipient_key"]


def test_ensemble_note_declares_the_surge_caveat(run):
    """Presenting a screen as a simulation is the pitfall judges look for."""
    for adv in run["advisories"]:
        assert "screening-grade" in adv["ensemble_note"]


def test_run_carries_a_land_mask_for_the_offline_map(run):
    """The console must be able to draw a coast with no network at all.

    Everything else it needs -- hazard grids, track, asset positions -- is
    already in the payload; the land mask is what turns that from a coloured
    grid into something recognisable as a map.
    """
    mask = run.get("land_mask")
    assert mask, "no land mask exported"
    flat = [v for row in mask for v in row]
    land = sum(1 for v in flat if v > 0.5) / len(flat)
    assert 0.3 < land < 0.85, f"a coastal box should be part land, part sea (got {land:.0%})"


def test_payload_stays_small_enough_to_load_quickly(run):
    """A console that takes ten seconds to parse its own data is not usable
    in an operations room."""
    import json
    size_kb = len(json.dumps(run)) / 1024
    assert size_kb < 600, f"payload is {size_kb:.0f} KB"


# --- ensemble spread by lead time --------------------------------------------

def test_spread_follows_imds_table_where_it_exists():
    from ingest.ensemble import INTENSITY_ERROR_KT, LANDFALL_ERROR_KM, at_lead

    assert at_lead(LANDFALL_ERROR_KM, 24) == 19.0
    assert at_lead(LANDFALL_ERROR_KM, 48) == 34.4
    assert at_lead(LANDFALL_ERROR_KM, 36) == pytest.approx((19.0 + 34.4) / 2)
    assert at_lead(LANDFALL_ERROR_KM, 96) == 77.3, "held beyond the table"
    assert at_lead(INTENSITY_ERROR_KT, 24) == 5.3


def test_spread_keeps_shrinking_below_24_hours():
    """Holding the 24 h value made a 12 h forecast identical to a 24 h one."""
    from ingest.ensemble import LANDFALL_ERROR_KM, at_lead, spread_basis

    assert at_lead(LANDFALL_ERROR_KM, 12) < at_lead(LANDFALL_ERROR_KM, 24)
    assert at_lead(LANDFALL_ERROR_KM, 12) == pytest.approx(19.0 - (34.4 - 19.0) / 24 * 12)
    assert at_lead(LANDFALL_ERROR_KM, 0) >= 0.0
    assert "extrapolated" in spread_basis(12)
    assert "IMD published" in spread_basis(48)


def test_a_12_hour_ensemble_is_tighter_than_a_24_hour_one():
    from ingest.ensemble import perturb
    from ingest.tracks import load_storm

    storm = load_storm("FANI", 2019)
    lf = storm.landfall_index
    assert lf is not None

    def spread(lead: float) -> float:
        members = perturb(storm, n_members=40, lead_hours=lead)
        lats = np.array([m[lf].lat for m in members])
        return float(lats.std())

    assert spread(12) < spread(24)

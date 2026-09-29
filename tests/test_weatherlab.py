"""Real WeatherNext 3 forecasts from the Weather Lab archive.

The archived files come from tests/fixtures/weatherlab -- the North Indian
Ocean rows of two real forecast files -- so these run on a fresh clone with
no network, rather than skipping.
"""

import math
from datetime import datetime
from pathlib import Path

import pytest

from ingest import weatherlab

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "weatherlab"
MONTHA_LANDFALL = datetime(2025, 10, 28, 21)


@pytest.fixture(autouse=True)
def _archive_from_fixtures(monkeypatch):
    monkeypatch.setattr(weatherlab, "CACHE_DIR", FIXTURES)


def cached(init):
    path = FIXTURES / f"WNV3_{init:%Y_%m_%dT%H}_00_paired.csv"
    assert path.exists(), f"missing test fixture {path.name}"
    return weatherlab.fetch(init)


def test_issue_time_rounds_down_never_up():
    """A T-48 advisory must use a forecast that existed 48 hours out."""
    assert weatherlab.issue_time_for(MONTHA_LANDFALL, 48) == datetime(2025, 10, 26, 18)
    assert weatherlab.issue_time_for(MONTHA_LANDFALL, 12) == datetime(2025, 10, 28, 6)
    issued = weatherlab.issue_time_for(MONTHA_LANDFALL, 30)
    assert (MONTHA_LANDFALL - issued).total_seconds() / 3600 >= 30


def test_coverage_excludes_storms_before_the_archive():
    assert weatherlab.covered(datetime(2025, 10, 26))
    assert not weatherlab.covered(datetime(2019, 5, 1)), "Fani predates WNV3"


def test_files_are_global_so_the_storm_is_picked_by_position():
    """The Montha file also carries Hurricane Melissa and a Pacific storm."""
    df = cached(datetime(2025, 10, 26, 18))
    assert weatherlab.find_track(df, 11.6, 85.9) == "IO032025"


def test_an_invest_is_found_before_it_is_named():
    """At T-75 h Montha is still invest 94B; a southern-hemisphere storm
    shares the basin code and must not be picked instead."""
    df = cached(datetime(2025, 10, 25, 18))
    assert weatherlab.find_track(df, 11.0, 87.7) == "IO942025"


def test_nothing_nearby_is_refused_not_guessed():
    df = cached(datetime(2025, 10, 26, 18))
    with pytest.raises(LookupError, match="no forecast track"):
        weatherlab.find_track(df, -40.0, 20.0)


@pytest.fixture(scope="module")
def montha():
    from ingest.tracks import apply_land_decay, load_storm
    return apply_land_decay(load_storm("MONTHA", 2025))


def test_members_span_the_storm_and_are_all_finite(montha):
    """Regression: the invest has no intensity at lead zero, and one NaN would
    have spread into every wind field built from that member."""
    init = datetime(2025, 10, 25, 18)
    cached(init)
    members, prov = weatherlab.members_for(montha, init)
    assert prov["members"] == len(members) > 0
    for m in members:
        assert len(m) == len(montha.track)
        assert all(math.isfinite(p.vmax_ms) and math.isfinite(p.pcen_hpa) for p in m)


def test_the_past_is_the_best_track_and_land_decay_is_not_doubled(montha):
    init = datetime(2025, 10, 26, 18)
    cached(init)
    members, _ = weatherlab.members_for(montha, init)
    for i, when in enumerate(montha.times):
        if when < init:
            assert members[0][i] == montha.track[i], "known history, not forecast"
        else:
            assert members[0][i].hours_inland == 0.0, \
                "model intensity already weakens over land"


def test_verification_ignores_positions_before_issue(montha):
    """Scoring pre-issue positions would count known history as skill."""
    from verify.ensemble_skill import verify_ensemble

    init = datetime(2025, 10, 26, 18)
    cached(init)
    members, _ = weatherlab.members_for(montha, init)
    v = verify_ensemble(montha, members, source="weatherlab", from_time=init)
    assert all(montha.times[s.step] >= init for s in v.steps)
    assert v.is_skill and "Real verification" in v.as_dict()["caveat"]
    assert v.landfall_mean_track_error_km <= v.landfall_error_km, \
        "the ensemble mean is never further from truth than its members on average"


def test_perturbed_ensemble_never_claims_skill(montha):
    from ingest.ensemble import perturb
    from verify.ensemble_skill import verify_ensemble

    v = verify_ensemble(montha, perturb(montha, n_members=6))
    assert not v.is_skill
    assert "Self-verification" in v.as_dict()["caveat"]

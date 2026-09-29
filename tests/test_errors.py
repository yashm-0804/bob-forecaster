"""A failed data source degrades with a reason; a bug does not.

Found in review: the broad handlers around data sources would have turned the
code's own mistakes -- a TypeError, an AttributeError -- into a line of
provenance that reads like an archive being down."""

from datetime import datetime
from typing import Any

import numpy as np
import pytest

import pipeline
from advisory import gemini
from common.errors import BUGS, reraise_bugs
from ingest import weatherlab
from ingest.tracks import load_storm
from tests.test_gemini import advisory

#: Stands in for a value the code wrongly assumed was something else.
NOTHING: Any = None


def test_bugs_are_raised_and_failed_sources_are_not():
    for bug in (TypeError("x"), AttributeError("x"), NameError("x"), AssertionError("x")):
        with pytest.raises(type(bug)):
            reraise_bugs(bug)
    for failure in (OSError("down"), TimeoutError("slow"), ValueError("bad reply"), LookupError("no pass")):
        reraise_bugs(failure)            # returns: the caller records it
    assert ImportError not in BUGS, "a missing optional package is an environment's state"


@pytest.fixture
def montha():
    return load_storm("MONTHA", 2025)


def _covered(monkeypatch):
    monkeypatch.setattr(weatherlab, "covered", lambda when, model=weatherlab.DEFAULT_MODEL: True)


def test_an_archive_that_is_down_falls_back_with_its_reason(monkeypatch, montha):
    _covered(monkeypatch)

    def down(storm, issued):
        raise OSError("Weather Lab unreachable")

    monkeypatch.setattr(weatherlab, "members_for", down)
    landfall = montha.times[montha.landfall_index]
    members, provenance = pipeline._ensemble(montha, landfall, 48.0, 6, "auto")
    assert len(members) == 6 and "Weather Lab unavailable (OSError" in str(provenance)


def test_a_bug_in_the_archive_path_is_raised_not_recorded(monkeypatch, montha):
    _covered(monkeypatch)

    def bug(storm, issued):
        return NOTHING + 1               # the code's own mistake: a TypeError

    monkeypatch.setattr(weatherlab, "members_for", bug)
    landfall = montha.times[montha.landfall_index]
    with pytest.raises(TypeError):
        pipeline._ensemble(montha, landfall, 48.0, 6, "auto")


def test_a_model_that_fails_keeps_the_template_and_a_bug_is_raised():
    def overloaded(prompt):
        raise OSError("503 overloaded")

    out = gemini.enhance(advisory(), overloaded)
    assert out.drafted_by == "template" and "OSError" in " ".join(out.draft_notes)

    def mistake(prompt):
        raise AttributeError("'NoneType' object has no attribute 'text'")

    with pytest.raises(AttributeError):
        gemini.enhance(advisory(), mistake)


def test_a_failed_satellite_check_costs_only_its_own_check_and_a_bug_is_raised(monkeypatch):
    from verify import satellite

    grid_lats, grid_lons = np.meshgrid(np.linspace(16, 17, 3), np.linspace(81, 82, 3), indexing="ij")

    from ingest import earthengine

    monkeypatch.setattr(earthengine, "availability", lambda: (True, "signed in to Earth Engine"))

    class Grids:
        lats, lons = grid_lats, grid_lons
        depth_members = [np.zeros((3, 3))]
        terrain = None

    def missing(*a, **k):
        raise LookupError("no same-orbit Sentinel-1 pair around landfall")

    monkeypatch.setattr(satellite, "observed_rain", missing)
    monkeypatch.setattr(satellite, "flood_fraction", missing)
    monkeypatch.setattr(satellite, "nightlight_drop", missing)
    landfall = datetime(2025, 10, 28, 21)
    args: tuple[Any, ...] = (None, landfall, None, Grids(), np.ones((3, 3), bool), [], [np.zeros((3, 3))],
            [np.zeros((3, 3))], {"source": "r-cliper"}, landfall)
    out, _ = pipeline._observe(*args)
    assert {k: "LookupError" in out[k]["error"] for k in ("rain", "flood", "outage")} == {
        "rain": True, "flood": True, "outage": True}

    def bug(*a, **k):
        return len(NOTHING)          # a TypeError

    monkeypatch.setattr(satellite, "flood_fraction", bug)
    with pytest.raises(TypeError):
        pipeline._observe(*args)

"""Scoring against satellite observations, without calling a satellite.

Earth Engine is off for the whole suite (see conftest.py). The satellite
module is tested at its seams instead: the grid it asks Earth Engine for,
the cache it keeps, the Sentinel-1 pair it picks, and what it does with the
arrays that come back. The scoring functions are tested on arrays whose
right answer is known by construction.
"""

import json
from datetime import datetime
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from verify import observed_skill, satellite
from verify.metrics import Contingency

# --- undefined scores ------------------------------------------------------

def test_undefined_scores_are_null_not_nan():
    """No observed events leaves POD undefined. NaN is not JSON; null is."""
    d = Contingency(hits=0, false_alarms=3, misses=0, correct_negatives=10).as_dict()
    assert d["pod"] is None and d["bias"] is None
    assert d["far"] == 1.0
    json.dumps(d, allow_nan=False)


def test_json_safe_clears_nan_all_the_way_down():
    import pipeline

    clean = pipeline.json_safe({"a": [1.0, float("nan"), {"b": float("inf")}],
                                "c": np.float64("nan"), "d": "text"})
    assert clean == {"a": [1.0, None, {"b": None}], "c": None, "d": "text"}
    json.dumps(clean, allow_nan=False)


# --- rain ------------------------------------------------------------------

def _land(shape=(6, 6)):
    land = np.ones(shape, dtype=bool)
    land[:, :2] = False
    return land


def test_rain_skill_on_a_perfect_forecast():
    rng = np.random.default_rng(1)
    observed = rng.uniform(20, 200, (6, 6))
    out = observed_skill.rain_skill(observed, observed * 0.5, observed, _land(), "gfs")
    f = out["forecast"]
    assert f["bias_ratio"] == 1.0 and f["rmse_mm"] == 0.0 and f["correlation"] == 1.0
    assert f["label"] == "gfs"
    assert out["r_cliper"]["bias_ratio"] == 0.5


def test_rain_skill_ignores_the_sea():
    observed = np.full((6, 6), 100.0)
    forecast = observed.copy()
    land = _land()
    forecast[~land] = 5000.0                       # absurd, but offshore
    out = observed_skill.rain_skill(forecast, forecast, observed, land, "gfs")
    assert out["forecast"]["cells"] == int(land.sum())
    assert out["forecast"]["rmse_mm"] == 0.0


def test_rain_skill_does_not_compare_r_cliper_with_itself():
    observed = np.full((6, 6), 100.0)
    out = observed_skill.rain_skill(observed, observed, observed, _land(), "r-cliper")
    assert "r_cliper" not in out


def test_rain_skill_skips_cells_the_satellite_did_not_see():
    observed = np.full((6, 6), 100.0)
    observed[3:, :] = np.nan
    out = observed_skill.rain_skill(observed, observed, observed, _land(), "gfs")
    assert out["forecast"]["cells"] == 12


# --- flood -----------------------------------------------------------------

def test_flood_skill_on_a_perfect_forecast():
    land = _land()
    observed = np.zeros((6, 6)); observed[0, 3:] = 0.4
    p = (observed > 0).astype(float)
    out = observed_skill.flood_skill(p, observed, land)
    c = out["contingency_at_p50"]
    assert c["hits"] == 3 and c["misses"] == 0 and c["false_alarms"] == 0
    assert out["brier"] == 0.0


def test_flood_skill_reports_where_a_miss_happened():
    """Predicted water at the coast, observed water inland and higher up."""
    land = _land()
    elevation = np.tile(np.arange(6.0) * 10, (6, 1))
    coast_km = np.tile(np.arange(6.0) * 20, (6, 1))
    observed = np.zeros((6, 6)); observed[:, 5] = 1.0
    p = np.zeros((6, 6)); p[:, 2] = 0.9
    out = observed_skill.flood_skill(p, observed, land, elevation, coast_km)
    assert out["contingency_at_p50"]["pod"] == 0.0
    where = out["where"]
    assert where["observed_flooded"]["median_km_from_coast"] == 100.0
    assert where["predicted_flooded"]["median_km_from_coast"] == 40.0
    assert where["observed_flooded"]["median_elevation_m"] > \
        where["predicted_flooded"]["median_elevation_m"]


def test_flood_skill_with_nothing_observed_leaves_skill_undefined():
    land = _land()
    out = observed_skill.flood_skill(np.zeros((6, 6)), np.zeros((6, 6)), land,
                                     np.zeros((6, 6)), np.zeros((6, 6)))
    assert out["brier_skill_vs_climatology"] is None
    assert out["contingency_at_p50"]["pod"] is None
    assert out["where"]["observed_flooded"] is None
    json.dumps(out, allow_nan=False)


# --- outage ----------------------------------------------------------------

def _grids(n: int = 6) -> Any:
    lats, lons = np.meshgrid(np.arange(n, dtype=float), np.arange(n, dtype=float),
                             indexing="ij")
    return SimpleNamespace(cell_of=lambda lat, lon: (int(round(lat)), int(round(lon))),
                           lats=lats, lons=lons)


def _risk(i: int, j: int, p: float, cls: str = "substation") -> Any:
    asset = SimpleNamespace(lat=float(i), lon=float(j), asset_class=cls, label=f"{cls} {i},{j}")
    return SimpleNamespace(asset=asset, p_failure_mean=p)


def test_outage_skill_uses_separate_thresholds_for_forecast_and_observation():
    drop = np.full((6, 6), np.nan)
    drop[0, 0], drop[1, 1], drop[2, 2], drop[3, 3] = 0.8, 0.1, 0.9, 0.0
    risks = [_risk(0, 0, 0.6), _risk(1, 1, 0.5), _risk(2, 2, 0.1), _risk(3, 3, 0.05)]
    out = observed_skill.outage_skill(risks, drop, _grids())
    c = out["contingency"]
    assert (c["hits"], c["false_alarms"], c["misses"], c["correct_negatives"]) == (1, 1, 1, 1)
    assert out["observed_outages"] == 2


def test_outage_skill_ignores_other_assets_and_unseen_cells():
    drop = np.full((6, 6), np.nan)
    drop[0, 0] = 0.8
    risks = [_risk(0, 0, 0.6), _risk(1, 1, 0.9), _risk(0, 0, 0.9, cls="hospital")]
    out = observed_skill.outage_skill(risks, drop, _grids())
    assert out["substations_with_lights"] == 1
    assert "too few" in out["note"]


def test_outage_skill_with_no_observed_outages_is_valid_json():
    drop = np.full((6, 6), 0.1)
    risks = [_risk(i, i, 0.1 * i) for i in range(6)]
    out = observed_skill.outage_skill(risks, drop, _grids())
    assert out["observed_outages"] == 0
    assert out["contingency"]["pod"] is None
    json.dumps(out, allow_nan=False)


# --- the satellite module's seams --------------------------------------------

def test_pick_pair_insists_on_the_same_orbit():
    landfall = datetime(2025, 10, 28, 21)
    scenes = [
        (datetime(2025, 10, 20, 0, 30), 19),
        (datetime(2025, 10, 26, 0, 31), 92),
        (datetime(2025, 10, 26, 0, 32), 92),       # second frame of the same pass
        (datetime(2025, 10, 30, 0, 30), 165),      # first after landfall, but no pair
        (datetime(2025, 11, 1, 0, 31), 92),
    ]
    before, after, orbit = satellite.pick_pair(scenes, landfall)
    assert orbit == 92
    assert before == datetime(2025, 10, 26, 0)
    assert after == datetime(2025, 11, 1, 0)


def test_pick_pair_says_when_there_is_none():
    landfall = datetime(2025, 10, 28, 21)
    with pytest.raises(LookupError, match="same-orbit"):
        satellite.pick_pair([(datetime(2025, 10, 30), 165)], landfall)


class _FakeEE:
    """Stands in for `ee`: records the request, returns rows north first."""

    def __init__(self, bands):
        self.request = None
        self.bands = bands
        self.data = SimpleNamespace(computePixels=self._compute)

    def _compute(self, request):
        self.request = request
        first = next(iter(self.bands.values()))
        out = np.zeros(first.shape, dtype=[(k, "f8") for k in self.bands])
        for k, v in self.bands.items():
            out[k] = v
        return out


def test_on_grid_asks_for_the_hazard_grid_and_flips_it_south_up():
    lats, lons = np.meshgrid(np.array([15.0, 15.5, 16.0]), np.array([80.0, 80.5]),
                             indexing="ij")
    north_first = np.array([[3.0, 3.0], [2.0, 2.0], [1.0, 1.0]])
    ee = _FakeEE({"v": north_first})
    got = satellite._on_grid(ee, "image", lats, lons)["v"]
    assert ee.request is not None
    assert got[0, 0] == 1.0 and got[-1, 0] == 3.0   # row 0 is the southern row
    grid = ee.request["grid"]
    assert grid["dimensions"] == {"width": 2, "height": 3}
    t = grid["affineTransform"]
    # Pixel edges, not centres: the top-left corner is half a step outside.
    assert t["translateX"] == pytest.approx(79.75)
    assert t["translateY"] == pytest.approx(16.25)
    assert t["scaleY"] < 0


def test_cache_computes_once(tmp_path, monkeypatch):
    monkeypatch.setattr(satellite, "CACHE_DIR", tmp_path)
    calls = []

    def compute():
        calls.append(1)
        return {"x": np.arange(3.0)}, {"source": "test"}

    arrays, meta = satellite._cached("k", compute)
    arrays, meta = satellite._cached("k", compute)
    assert len(calls) == 1
    assert list(arrays["x"]) == [0.0, 1.0, 2.0] and meta == {"source": "test"}


def test_night_light_drop_leaves_unlit_and_cloudy_cells_unknown(tmp_path, monkeypatch):
    """A cloudy night after the storm is 'unknown', never 'lights on'."""
    monkeypatch.setattr(satellite, "CACHE_DIR", tmp_path)
    lats, lons = np.meshgrid(np.array([15.0, 15.5]), np.array([80.0, 80.5]), indexing="ij")
    landfall = datetime(2025, 10, 28, 21)
    pre = np.array([[10.0, 10.0], [0.5, 10.0]])
    post = np.array([[5.0, -1.0], [0.1, 12.0]])     # -1 = no clear night
    key = f"viirs_{landfall:%Y%m%d%H}_{satellite._grid_key(lats, lons)}"
    np.savez_compressed(tmp_path / f"{key}.npz", pre=pre, post=post)
    (tmp_path / f"{key}.json").write_text("{}")

    drop, meta = satellite.nightlight_drop(landfall, lats, lons)
    assert drop[0, 0] == pytest.approx(0.5)
    assert np.isnan(drop[0, 1])                    # lit, but clouded over after
    assert np.isnan(drop[1, 0])                    # never lit
    assert drop[1, 1] == pytest.approx(-0.2)       # brighter after
    assert meta["lit_cells"] == 3 and meta["lit_cells_unknown_after"] == 1

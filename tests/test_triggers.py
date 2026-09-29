"""Parametric triggers and basis risk."""

from types import SimpleNamespace
from typing import Any, cast

import numpy as np
import pytest

from impact.triggers import RAIN, WIND, Zone, evaluate


def test_tiers_pay_the_highest_reached():
    assert WIND.payout_for(100) == 0.0
    assert WIND.payout_for(118) == 0.5      # IMD Very Severe boundary
    assert WIND.payout_for(170) == 1.0      # IMD Extremely Severe boundary
    assert RAIN.payout_for(300) == 1.0      # CDRI's 300 mm over three days


def grid():
    lats, lons = np.meshgrid(np.linspace(16.0, 17.0, 21), np.linspace(81.5, 82.5, 21), indexing="ij")
    return lats, lons


def risk(lat, lon, severity="red", consequence=1.2):
    return SimpleNamespace(asset=SimpleNamespace(lat=lat, lon=lon),
                           severity=severity, consequence=consequence)


def run(wind_ms, rain_mm, red_assets):
    lats, lons = grid()
    w = np.full(lats.shape, wind_ms); r = np.full(lats.shape, rain_mm)
    # Stand-ins with only the fields evaluate() reads.
    risks = cast(list[Any], [risk(16.5, 82.0) for _ in range(red_assets)])
    report = evaluate("andhra", lats, lons, [w, w], [r, r], w, r, risks)
    return next(z for z in report["zones"] if z["zone"].startswith("Amalapuram"))


def test_a_rain_storm_under_a_wind_index_is_loss_without_payout():
    """The Montha case: real damage, nothing crosses a threshold."""
    z = run(wind_ms=24.0, rain_mm=150.0, red_assets=12)
    assert z["observed_payout"] == 0.0
    assert z["basis_risk"] == "loss without payout"


def test_a_trigger_that_fires_on_little_damage_is_flagged_the_other_way():
    z = run(wind_ms=50.0, rain_mm=50.0, red_assets=0)
    assert z["observed_payout"] > 0
    assert z["basis_risk"] == "payout without modelled loss"


def test_aligned_when_payout_and_loss_agree():
    z = run(wind_ms=50.0, rain_mm=50.0, red_assets=20)
    assert z["basis_risk"] == "aligned"


def test_probabilities_come_from_the_ensemble():
    lats, lons = grid()
    calm, storm = np.full(lats.shape, 20.0), np.full(lats.shape, 50.0)
    rain = np.zeros(lats.shape)
    rep = evaluate("andhra", lats, lons, [calm, storm, storm, storm], [rain] * 4,
                   calm, rain, [])
    wind = rep["zones"][0]["perils"][0]
    assert wind["p_partial_or_more"] == pytest.approx(0.75)


def test_everything_is_labelled_illustrative():
    lats, lons = grid(); z = np.zeros(lats.shape)
    rep = evaluate("andhra", lats, lons, [z], [z], z, z, [])
    assert rep["illustrative"] is True
    assert "not real policies" in rep["note"]


def test_unknown_region_has_no_zones_rather_than_borrowed_ones():
    lats, lons = grid(); z = np.zeros(lats.shape)
    assert evaluate("atlantis", lats, lons, [z], [z], z, z, [])["zones"] == []


def test_zone_membership():
    zone = Zone("X", 16.5, 82.0, radius_km=10)
    assert zone.contains(16.5, 82.0)
    assert not zone.contains(17.0, 82.0)

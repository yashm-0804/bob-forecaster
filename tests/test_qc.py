"""QC gate tests.

The plan's verification step calls for injecting a spike and a flatline and
asserting both are caught. These cover that plus tier permissions, which are
the check that stops a simulated or misconfigured node from reporting fields
it has no instrument for.
"""

from datetime import datetime, timedelta
from typing import Any

import pytest

from telemetry import qc
from telemetry.qc import Flag, QCContext
from telemetry.schema import NodeObservation, SiteClass, Tier

TS = "2025-10-26T09:00:00"


def node(tier: Tier = Tier.ATMOSPHERIC, **overrides: Any) -> NodeObservation:
    """A clean baseline observation, overridable per test."""
    base: dict[str, Any] = dict(
        node_id="AP-KRI-014",
        tier=tier,
        lat=16.45,
        lon=81.70,
        elev_m=4.0,
        site_class=SiteClass.SEA_LEVEL,
        ts=TS,
        pressure_hpa=1004.0,
        temp_c=29.0,
        rh_pct=82.0,
        battery_v=3.9,
        rssi=-96,
    )
    base.update(overrides)
    return NodeObservation(**base)


def test_clean_observation_passes():
    flags = qc.run(node())
    assert flags == []
    assert qc.is_fusable(flags)


def test_tier_a_may_not_report_rainfall():
    """A Tier A node has no rain gauge, so a rain value means something is wrong."""
    flags = qc.run(node(rain_mm_15m=12.0))
    assert qc.has(flags, Flag.TIER_VIOLATION)
    assert not qc.is_fusable(flags)


def test_tier_b_may_report_rainfall():
    assert qc.run(node(tier=Tier.RAIN, rain_mm_15m=12.0)) == []


def test_tier_c_inherits_tier_b_rain_gauge():
    """A wind mast carries the rain gauge too, so both fields are permitted."""
    obs = node(tier=Tier.WIND_MAST, rain_mm_15m=8.0, wind_ms=31.0, wind_dir_deg=140.0)
    assert qc.run(obs) == []


def test_water_level_without_datum_is_rejected():
    """A level reading with no datum reference is not comparable to anything."""
    flags = qc.run(node(tier=Tier.WATER_LEVEL, water_level_m=2.4))
    assert qc.has(flags, Flag.MISSING_DATUM)


def test_water_level_with_datum_passes():
    obs = node(tier=Tier.WATER_LEVEL, water_level_m=2.4, datum_ref="CD-Machilipatnam")
    assert qc.run(obs) == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("pressure_hpa", 1400.0),
        ("pressure_hpa", 500.0),
        ("rh_pct", 140.0),
        ("temp_c", 95.0),
    ],
)
def test_out_of_range_is_caught(field, value):
    assert qc.has(qc.run(node(**{field: value})), Flag.OUT_OF_RANGE)


def test_cyclone_pressure_is_not_flagged_as_out_of_range():
    """912 hPa was real -- the 1999 Odisha Super Cyclone. Ranges catch broken
    sensors, not extreme weather."""
    assert not qc.has(qc.run(node(pressure_hpa=915.0)), Flag.OUT_OF_RANGE)


def test_spike_is_caught():
    previous = node(pressure_hpa=1004.0)
    current = node(pressure_hpa=985.0)  # 19 hPa in one 15-min step
    flags = qc.run(current, QCContext(previous=previous))
    assert qc.has(flags, Flag.SPIKE)
    assert not qc.is_fusable(flags)


def test_real_deepening_rate_is_not_flagged_as_a_spike():
    """Amphan deepened at roughly 2 hPa/hr. A 15-min step of 0.5 hPa is real."""
    previous = node(pressure_hpa=1004.0)
    current = node(pressure_hpa=1003.5)
    assert not qc.has(qc.run(current, QCContext(previous=previous)), Flag.SPIKE)


def test_flatline_is_caught():
    """A seized sensor repeating one value across the window."""
    history = [node(pressure_hpa=1004.0) for _ in range(6)]
    assert qc.has(qc.run(node(), QCContext(history=history)), Flag.FLATLINE)


def test_varying_history_is_not_flatlined():
    history = [
        node(pressure_hpa=1004.0 + i * 0.4, temp_c=29.0 + i * 0.3, rh_pct=82.0 + i)
        for i in range(6)
    ]
    assert not qc.has(qc.run(node(), QCContext(history=history)), Flag.FLATLINE)


def test_flatline_names_the_stuck_channel():
    """The flag doubles as a maintenance ticket, so it must say which sensor."""
    history = [
        node(pressure_hpa=1004.0 + i * 0.4, rh_pct=82.0 + i, temp_c=29.0)
        for i in range(6)
    ]
    flags = qc.run(node(), QCContext(history=history))
    assert qc.on(Flag.FLATLINE, "temp_c") in flags
    assert qc.on(Flag.FLATLINE, "pressure_hpa") not in flags


def test_seized_thermometer_does_not_invalidate_pressure():
    """Tier A pressure is the network backbone; one dead channel must not cost it."""
    history = [
        node(pressure_hpa=1004.0 + i * 0.4, rh_pct=82.0 + i, temp_c=29.0)
        for i in range(6)
    ]
    flags = qc.run(node(), QCContext(history=history))
    assert qc.is_fusable(flags, channel="pressure_hpa")
    assert not qc.is_fusable(flags, channel="temp_c")
    assert not qc.is_fusable(flags)


def test_tier_violation_invalidates_the_whole_reading():
    """A node reporting an instrument it doesn't have is misconfigured outright."""
    flags = qc.run(node(rain_mm_15m=12.0))
    assert not qc.is_fusable(flags, channel="pressure_hpa")


def test_neighbour_disagreement_is_caught():
    neighbours = [node(pressure_hpa=1004.0) for _ in range(4)]
    rogue = node(pressure_hpa=996.0)  # 8 hPa from the local median
    assert qc.has(qc.run(rogue, QCContext(neighbours=neighbours)), Flag.NEIGHBOUR_DISAGREE)


def test_elevated_node_is_not_penalised_for_altitude():
    """Without reduction to MSL an elevated node would fail this check every cycle."""
    sea_level = [node(pressure_hpa=1004.0) for _ in range(4)]
    hill = node(
        elev_m=250.0,
        site_class=SiteClass.ELEVATED,
        pressure_hpa=1004.0 - 250.0 * 0.12,
    )
    assert not qc.has(qc.run(hill, QCContext(neighbours=sea_level)), Flag.NEIGHBOUR_DISAGREE)


def test_stale_reading_is_flagged():
    now = datetime.fromisoformat(TS) + timedelta(hours=5)
    assert qc.has(qc.run(node(), QCContext(now=now)), Flag.STALE)


def test_low_battery_flags_but_still_fuses():
    """Low battery is a maintenance ticket, not a reason to distrust the reading."""
    flags = qc.run(node(battery_v=3.1))
    assert qc.has(flags, Flag.LOW_BATTERY)
    assert qc.is_fusable(flags)

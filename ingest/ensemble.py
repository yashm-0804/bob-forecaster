"""Track ensembles.

Rapid intensification is the main reason cyclone triggers fail -- the Red
Cross typhoon trigger never fired for Rai because it intensified inside 24
hours. A single deterministic track hides that risk, so every hazard layer is
computed per member and reported as an exceedance probability.

A live system would take real ensemble members from Weather Lab or
WeatherNext Cyclones. This module perturbs a known track instead, which is
what the dossier recommends for storms predating the ensemble archive, and
keeps the downstream interface identical either way.
"""

from __future__ import annotations

import math
from dataclasses import replace

import numpy as np

from hazard.holland import TrackPoint
from ingest.tracks import Storm, radius_of_maximum_wind_km

#: IMD landfall-point error, 2021-25 average, in km by lead time. Perturbation
#: is scaled to these so the spread reflects real forecast skill rather than an
#: arbitrary number. Source: IMD via Mission Mausam, Mar 2026.
LANDFALL_ERROR_KM = {24: 19.0, 48: 34.4, 72: 77.3}

#: IMD intensity error in knots by lead time, same source.
INTENSITY_ERROR_KT = {24: 5.3, 48: 7.5, 72: 9.1}

KT_TO_MS = 0.514444


def at_lead(table: dict[int, float], lead_hours: float) -> float:
    """A table value at any lead time.

    Inside the table: interpolated. Beyond 72 h: held at the 72 h value.
    Below 24 h, where IMD publishes nothing, the 24-48 h trend is continued
    down (floored at zero). Holding the 24 h value there instead made a 12 h
    forecast identical to a 24 h one, and the agent then reported "no change"
    between cycles when the only thing that had changed was the lead time.
    """
    leads = sorted(table)
    if lead_hours >= leads[0]:
        return float(np.interp(lead_hours, leads, [table[k] for k in leads]))
    (t0, v0), (t1, v1) = (leads[0], table[leads[0]]), (leads[1], table[leads[1]])
    return max(0.0, v0 - (v1 - v0) / (t1 - t0) * (t0 - lead_hours))


def spread_basis(lead_hours: float) -> str:
    """Where the ensemble's spread at this lead comes from, for the record."""
    leads = sorted(LANDFALL_ERROR_KM)
    if lead_hours < leads[0]:
        return (f"extrapolated from IMD's {leads[0]}-{leads[1]} h error trend; "
                f"IMD publishes no error below {leads[0]} h")
    if lead_hours > leads[-1]:
        return f"held at IMD's {leads[-1]} h error"
    return "IMD published landfall and intensity error, 2021-25"


def _cross_track_offset(
    point: TrackPoint, offset_km: float
) -> tuple[float, float]:
    """Shift a position perpendicular to its direction of travel.

    Cross-track error dominates landfall-point error, so displacing along the
    normal produces a more realistic spread than scattering in lat/lon.
    """
    normal = math.radians(point.trans_dir_deg + 90.0)
    dlat = offset_km * math.cos(normal) / 111.0
    dlon = (
        offset_km
        * math.sin(normal)
        / (111.0 * math.cos(math.radians(point.lat)) or 1e-6)
    )
    return point.lat + dlat, point.lon + dlon


def perturb(
    storm: Storm, n_members: int = 50, lead_hours: float = 48.0, seed: int = 20251028
) -> list[list[TrackPoint]]:
    """Generate `n_members` plausible tracks around a known one.

    Error grows with lead time: members agree near the analysis and diverge
    toward landfall, which is the shape real ensembles have. Each member gets
    one cross-track bias and one intensity bias held for its whole life, so
    members stay physically coherent instead of jittering point to point.
    """
    rng = np.random.default_rng(seed)
    sigma_km = at_lead(LANDFALL_ERROR_KM, lead_hours)
    sigma_kt = at_lead(INTENSITY_ERROR_KT, lead_hours)

    members: list[list[TrackPoint]] = []
    for _ in range(n_members):
        track_bias = rng.normal(0.0, sigma_km)
        intensity_bias = rng.normal(0.0, sigma_kt) * KT_TO_MS

        member: list[TrackPoint] = []
        for step, point in enumerate(storm.track):
            # Error ramps in over the track; the analysis time is well known.
            growth = min(step / max(len(storm.track) - 1, 1), 1.0)
            lat, lon = _cross_track_offset(point, track_bias * growth)
            vmax = max(point.vmax_ms + intensity_bias * growth, 5.0)

            # Pressure must move with intensity or Holland's B goes incoherent.
            dp = (point.penv_hpa - point.pcen_hpa) * (vmax / max(point.vmax_ms, 1e-6)) ** 2
            member.append(
                replace(
                    point,
                    lat=lat,
                    lon=lon,
                    vmax_ms=vmax,
                    pcen_hpa=point.penv_hpa - min(dp, 110.0),
                    rmax_km=radius_of_maximum_wind_km(vmax, lat),
                )
            )
        members.append(member)
    return members


def exceedance(fields: list[np.ndarray], threshold: float) -> np.ndarray:
    """Fraction of ensemble members exceeding a threshold at each grid cell.

    This is the number that goes in an advisory -- "70-85% chance of gusts
    above 90 km/h" -- rather than a single deterministic value.
    """
    stack = np.stack(fields)
    return (stack > threshold).mean(axis=0)


def percentile(fields: list[np.ndarray], q: float) -> np.ndarray:
    """Per-cell percentile across members, for p10/p50/p90 map layers."""
    return np.percentile(np.stack(fields), q, axis=0)

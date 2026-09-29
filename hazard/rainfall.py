"""Rainfall accumulation from a cyclone track.

This is a first-class damage pathway, not an afterthought. The two costliest
storms of 2025 -- Senyar (US$19.8bn) and Ditwah (US$4.1bn, ~4% of Sri Lanka's
GDP) -- never exceeded 85 km/h. Both did their damage through rain-driven
flooding and landslides. A wind-category model scores both as minor.

Uses R-CLIPER (Tuleya et al. 2007), the operational parametric rainfall
climatology: a symmetric rain-rate profile scaled by storm intensity. It is
deliberately simple. In the full pipeline it is replaced by GFS QPF for the
forecast and GPM IMERG for observation, with this as the fallback when
neither is reachable.
"""

from __future__ import annotations

import numpy as np

from hazard.holland import TrackPoint, haversine_km

#: R-CLIPER profile parameters. Rain peaks just inside Rmax and decays
#: exponentially outward, with a shallower inner gradient. The e-folding
#: distance must stay well inside the AOI width, or accumulation saturates
#: the whole domain and every "area above X mm" statistic becomes useless.
_R_INNER_FACTOR = 1.0
_E_FOLD_KM = 120.0


def rain_rate_mm_hr(point: TrackPoint, r_km: np.ndarray) -> np.ndarray:
    """Instantaneous rain rate at radius r from the centre, mm/hr.

    Peak rate scales with intensity but far more weakly than wind damage does
    -- which is exactly why weak, wet storms are dangerous and why intensity
    category is a poor proxy for rainfall risk.
    """
    vmax_kt = point.vmax_ms / 0.514444
    peak = 1.5 + 0.13 * vmax_kt          # mm/hr at the radius of peak rain
    r_peak = point.rmax_km * _R_INNER_FACTOR

    inner = peak * (r_km / max(r_peak, 1e-6))
    outer = peak * np.exp(-(r_km - r_peak) / _E_FOLD_KM)
    return np.where(r_km < r_peak, inner, outer)


def accumulation_mm(
    track: list[TrackPoint],
    times_hr: list[float],
    lats: np.ndarray,
    lons: np.ndarray,
) -> np.ndarray:
    """Total rainfall over a track, mm.

    Integrates rain rate over time, so a slow-moving storm dumps far more on
    one place than a fast one of the same intensity. That is the mechanism
    behind Michaung's Chennai floods and Senyar's 335 mm day at Hat Yai.
    """
    total = np.zeros_like(lats, dtype=float)
    for i, point in enumerate(track):
        if i == 0:
            hours = times_hr[1] - times_hr[0] if len(times_hr) > 1 else 3.0
        else:
            hours = times_hr[i] - times_hr[i - 1]
        r_km = haversine_km(point.lat, point.lon, lats, lons)
        total += rain_rate_mm_hr(point, r_km) * hours
    return total


def flood_susceptibility(
    elevation_m: np.ndarray, distance_to_water_km: np.ndarray
) -> np.ndarray:
    """Relative likelihood that rainfall ponds rather than drains, 0-1.

    Low, flat ground near an existing watercourse floods first. The full
    pipeline replaces this with height-above-nearest-drainage from the
    Copernicus DEM and the JRC permanent-water mask.
    """
    low = np.exp(-np.maximum(elevation_m, 0.0) / 12.0)
    near = np.exp(-np.maximum(distance_to_water_km, 0.0) / 5.0)
    return np.clip(0.65 * low + 0.35 * near, 0.0, 1.0)


def inland_flood_depth_m(
    rain_mm: np.ndarray, susceptibility: np.ndarray, runoff_coefficient: float = 0.55
) -> np.ndarray:
    """Screening-grade ponded depth from rainfall, metres.

    A bulk runoff conversion, not a hydraulic model: it says where water
    collects and roughly how deep, which is enough to rank assets. It is not
    a flood forecast and must not be presented as one.
    """
    return np.clip(rain_mm / 1000.0 * runoff_coefficient * susceptibility * 4.0, 0.0, 5.0)

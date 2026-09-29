"""Holland (1980) parametric wind field.

Turns a forecast track -- centre position, central pressure, maximum wind and
radius of maximum wind -- into a gridded surface wind swath. This is the first
link in the hazard chain, so its errors propagate into surge, fragility and
every downstream impact number. Kept deliberately plain and testable for that
reason.

Reference implementation to check against: CLIMADA's TropCyclone module.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

#: Air density at the surface, kg/m3.
RHO_AIR = 1.15

#: Earth angular velocity, rad/s, for the Coriolis parameter.
OMEGA = 7.292e-5

EARTH_RADIUS_KM = 6371.0

#: Gradient-to-surface wind reduction. Holland returns the gradient-level wind;
#: what damages infrastructure is the 10 m wind. 0.9 is the commonly used
#: open-water factor.
GRADIENT_TO_SURFACE = 0.90

#: Fraction of the storm's forward motion added to the wind field. Winds are
#: stronger on the right-hand side of the track in the northern hemisphere
#: because translation adds vectorially to the rotational wind.
TRANSLATION_FACTOR = 0.60

#: Kaplan & DeMaria overland decay, per hour after landfall.
LAND_DECAY_PER_HR = 0.095


@dataclass(frozen=True)
class TrackPoint:
    """One position along a forecast or best track."""

    lat: float
    lon: float
    #: Maximum sustained wind, m/s. IMD reports 3-minute sustained; keep the
    #: averaging period consistent across the whole pipeline.
    vmax_ms: float
    #: Central pressure, hPa.
    pcen_hpa: float
    #: Radius of maximum wind, km. Controls how wide the damage swath is.
    rmax_km: float
    #: Environmental pressure, hPa.
    penv_hpa: float = 1010.0
    #: Storm forward motion, m/s and degrees true.
    trans_speed_ms: float = 0.0
    trans_dir_deg: float = 0.0
    #: Hours since the centre crossed the coast; 0 while offshore.
    hours_inland: float = 0.0


def coriolis(lat_deg: float) -> float:
    """Coriolis parameter f at a given latitude, s^-1."""
    return 2.0 * OMEGA * np.sin(np.radians(abs(lat_deg)))


def holland_b(point: TrackPoint) -> float:
    """Holland shape parameter B.

    Controls peakedness of the wind profile. Derived from the storm's own
    vmax and pressure deficit rather than assumed, then clamped to the
    physically observed 1.0-2.5 range.
    """
    dp_pa = max((point.penv_hpa - point.pcen_hpa) * 100.0, 1.0)
    b = (point.vmax_ms**2) * RHO_AIR * np.e / dp_pa
    return float(np.clip(b, 1.0, 2.5))


def haversine_km(
    lat1: float, lon1: float, lat2: np.ndarray, lon2: np.ndarray
) -> np.ndarray:
    """Great-circle distance from one point to a grid of points, km."""
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi = p2 - p1
    dlam = np.radians(lon2 - lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlam / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(a))


def bearing_deg(
    lat1: float, lon1: float, lat2: np.ndarray, lon2: np.ndarray
) -> np.ndarray:
    """Initial bearing from the centre to each grid point, degrees true."""
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dlam = np.radians(lon2 - lon1)
    y = np.sin(dlam) * np.cos(p2)
    x = np.cos(p1) * np.sin(p2) - np.sin(p1) * np.cos(p2) * np.cos(dlam)
    return (np.degrees(np.arctan2(y, x)) + 360.0) % 360.0


def gradient_wind(point: TrackPoint, r_km: np.ndarray) -> np.ndarray:
    """Holland (1980) gradient wind at radius r from the centre.

        V(r) = sqrt( (B/rho)(Rmax/r)^B (pn - pc) exp(-(Rmax/r)^B)
                     + (r f / 2)^2 ) - r f / 2

    Returns m/s. The eye (r -> 0) is handled by flooring the radius rather
    than special-casing, which keeps the array arithmetic branch-free.
    """
    b = holland_b(point)
    f = coriolis(point.lat)
    dp_pa = max((point.penv_hpa - point.pcen_hpa) * 100.0, 1.0)

    r_m = np.maximum(r_km, 0.1) * 1000.0
    rmax_m = point.rmax_km * 1000.0

    scaled = (rmax_m / r_m) ** b
    core = (b / RHO_AIR) * scaled * dp_pa * np.exp(-scaled)
    rf_half = r_m * f / 2.0

    return np.sqrt(core + rf_half**2) - rf_half


def asymmetry(point: TrackPoint, azimuth_deg: np.ndarray) -> np.ndarray:
    """Additive wind from the storm's forward motion.

    Peaks to the right of the direction of travel in the northern hemisphere
    and cancels to the left, which is why the right-front quadrant does the
    most damage.
    """
    if point.trans_speed_ms <= 0.0:
        return np.zeros_like(azimuth_deg)
    # Angle between each grid point and the right-hand side of the track.
    offset = np.radians(azimuth_deg - (point.trans_dir_deg + 90.0))
    return TRANSLATION_FACTOR * point.trans_speed_ms * np.cos(offset)


def land_decay(point: TrackPoint) -> float:
    """Exponential weakening once the centre is over land."""
    if point.hours_inland <= 0.0:
        return 1.0
    return float(np.exp(-LAND_DECAY_PER_HR * point.hours_inland))


def wind_field(
    point: TrackPoint, lats: np.ndarray, lons: np.ndarray
) -> np.ndarray:
    """Surface wind speed over a lat/lon grid for one track point, m/s.

    `lats` and `lons` are 2-D grids of the same shape, as produced by
    np.meshgrid.
    """
    r_km = haversine_km(point.lat, point.lon, lats, lons)
    azimuth = bearing_deg(point.lat, point.lon, lats, lons)

    v = gradient_wind(point, r_km) * GRADIENT_TO_SURFACE
    v = v + asymmetry(point, azimuth)
    v = v * land_decay(point)

    return np.maximum(v, 0.0)


def swath(
    track: list[TrackPoint], lats: np.ndarray, lons: np.ndarray
) -> np.ndarray:
    """Peak surface wind at every grid cell over a whole track.

    The swath is the running maximum across track points: what matters for
    infrastructure fragility is the strongest wind a location ever saw, not
    the wind at any one time.
    """
    peak = np.zeros_like(lats, dtype=float)
    for point in track:
        np.maximum(peak, wind_field(point, lats, lons), out=peak)
    return peak


def make_grid(
    lat_min: float, lat_max: float, lon_min: float, lon_max: float, step_deg: float
) -> tuple[np.ndarray, np.ndarray]:
    """Regular lat/lon grid for an area of interest."""
    lat_axis = np.arange(lat_min, lat_max + step_deg, step_deg)
    lon_axis = np.arange(lon_min, lon_max + step_deg, step_deg)
    return np.meshgrid(lat_axis, lon_axis, indexing="ij")

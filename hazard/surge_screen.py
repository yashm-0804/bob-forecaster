"""Storm surge screening.

This is a SCREEN, not a simulation, and every label in the UI says so. A real
surge forecast needs a coupled tide-surge-wave model over resolved
bathymetry: ADCIRC, SCHISM, or the IIT Delhi 3.7 km model that has run
operationally in this basin for over a decade. What this does is rank which
stretches of coast and which assets are exposed, fast enough to run per
ensemble member.

The northern Bay turns storms into surge because of a broad shallow shelf, a
concave coast and tides up to ~6 m near Sandwip. The Andhra-Odisha stretch
has the tightest wind-surge coupling in the basin, which is why a
wind-driven parametric estimate is defensible here specifically.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

import numpy as np

from hazard.holland import TrackPoint, haversine_km


class ElevationSource(Protocol):
    """Terrain heights for the grid.

    Swapping the Copernicus 30 m DEM in later means implementing this and
    nothing else changes.
    """

    def elevation_m(self, lats: np.ndarray, lons: np.ndarray) -> np.ndarray: ...

    def distance_to_coast_km(
        self, lats: np.ndarray, lons: np.ndarray
    ) -> np.ndarray: ...


#: Coastline anchors along the Andhra shore, (lat, lon), from real ports.
#: The shore runs NE-SW here, so longitude of the coast climbs with latitude.
ANDHRA_COAST_ANCHORS = ((16.17, 81.13), (16.43, 81.70), (16.95, 82.25))


def andhra_coast_lon(lat: float) -> float:
    """Longitude of the coastline at a given latitude, linear in the anchors."""
    (la1, lo1), _, (la3, lo3) = ANDHRA_COAST_ANCHORS
    return lo1 + (lat - la1) * (lo3 - lo1) / (la3 - la1)


class FlatDeltaPlain:
    """Placeholder terrain for the Godavari-Krishna delta.

    A linear ramp inland from a straight coastline. It is standing in for
    COPERNICUS/DEM/GLO30 until Earth Engine access is live, and it is wrong in
    the specific way that matters -- it has no creeks, embankments or
    distributary channels, which are what actually route surge inland. Results
    computed on it are directional only.
    """

    def __init__(self, coast_lon_at: Callable[[float], float] | None = None,
                 slope_m_per_km: float = 0.9) -> None:
        self._coast_lon_at = coast_lon_at or andhra_coast_lon
        self._slope = slope_m_per_km

    def distance_to_coast_km(self, lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
        coast_lon = np.vectorize(self._coast_lon_at)(lats)
        km_per_deg = 111.0 * np.cos(np.radians(lats))
        return (coast_lon - lons) * km_per_deg  # negative offshore

    def elevation_m(self, lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
        return np.maximum(self.distance_to_coast_km(lats, lons), 0.0) * self._slope


def peak_surge_m(point: TrackPoint, shelf_factor: float = 1.0) -> float:
    """Peak open-coast surge height for a storm, metres.

    Scales with the square of wind speed -- surge is a wind-stress response,
    so it amplifies non-linearly with intensity, which is why a probabilistic
    study of 2,570 synthetic Bay cyclones found 50-year surges above 8 m in
    the northern Bay.

    `shelf_factor` carries the local geometry: >1 for a broad shallow shelf
    and concave coast, <1 where the shelf drops off quickly.
    """
    return float(0.0010 * point.vmax_ms**2 * shelf_factor)


def surge_field_m(
    point: TrackPoint,
    lats: np.ndarray,
    lons: np.ndarray,
    terrain: ElevationSource,
    tide_m: float = 0.0,
    shelf_factor: float = 1.0,
) -> np.ndarray:
    """Storm tide depth above ground across the grid, metres.

    Storm tide, not surge: surge plus astronomical tide is what actually
    floods, and the tide phase at landfall can dominate the outcome.

    Three reductions are applied -- alongshore decay away from the landfall
    point, the right-of-track bias that makes onshore winds pile water up,
    and attenuation inland -- then ground elevation is subtracted so the
    result is inundation depth rather than water level.
    """
    peak = peak_surge_m(point, shelf_factor) + tide_m

    dist_along = haversine_km(point.lat, point.lon, lats, lons)
    alongshore = np.exp(-((dist_along / (point.rmax_km * 3.0)) ** 2))

    # Onshore winds are right of track in the northern hemisphere; water
    # piles up there and is drawn down on the left.
    bias = np.clip(1.0 + 0.35 * np.sign(lats - point.lat), 0.65, 1.35)

    inland_km = np.maximum(terrain.distance_to_coast_km(lats, lons), 0.0)
    inland = np.exp(-inland_km / 12.0)

    water_level = peak * alongshore * bias * inland
    depth = water_level - terrain.elevation_m(lats, lons)

    # Two masks, both necessary.
    #
    # Offshore cells are open sea. Reporting an "inundation depth" there is
    # meaningless and, since most of a coastal bounding box is water, it
    # inflates every exposed-area statistic computed from this field.
    #
    # Inland, keep only water connected to the sea. Without that, the screen
    # fills isolated low pockets far from the coast -- the classic bathtub
    # failure that makes a screen look like a simulation and be wrong.
    raw_distance = terrain.distance_to_coast_km(lats, lons)
    onshore = raw_distance >= 0.0
    connected = raw_distance < 45.0

    return np.where(onshore & connected, np.maximum(depth, 0.0), 0.0)


def land_mask(terrain: ElevationSource, lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
    """True on land. Every area statistic must be taken over this, not the grid."""
    return terrain.distance_to_coast_km(lats, lons) >= 0.0

"""Forecast rainfall from NOAA's GFS, fetched without Earth Engine.

The rainfall pathway is the centre of this project's argument, and until now
it ran on R-CLIPER: a symmetric, climatological rain profile around the storm
centre. GFS is a real forecast. NOAA publishes its archive openly on AWS, and
every file carries an index of byte offsets, so the one field needed -- total
precipitation accumulated over the first three days -- is a single range
request of about 600 KB out of a ~500 MB file. No credentials.

GFS is one deterministic forecast; the hazard runs per ensemble member. So
GFS sets the amount and the spatial pattern, and each member redistributes it
along its own track -- see `member_fields`.

Coverage: the AWS archive starts in 2021. Earlier storms fall back to
R-CLIPER, and the run says so.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from ingest.net import https_open, https_request

BASE = "https://noaa-gfs-bdp-pds.s3.amazonaws.com"
CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache" / "gfs"
COVERAGE_START = datetime(2021, 1, 1)
INIT_HOURS = (0, 6, 12, 18)

#: The 72-hour file carries the whole three-day accumulation as one field.
LEAD_HOURS = 72
FIELD = ("APCP", "0-3 day acc")

#: Bounds on how far a member may redistribute GFS rain relative to the
#: ensemble mean. Without a cap, a cell the mean barely rains on could be
#: multiplied into a downpour by one member's track.
RATIO_BOUNDS = (0.0, 3.0)

ATTRIBUTION = "NOAA GFS 0.25°, via the NOAA Open Data Dissemination program on AWS"



def issue_time_for(forecast_time: datetime) -> datetime:
    """Latest GFS cycle at or before the forecast time. Never after."""
    hour = max(h for h in INIT_HOURS if h <= forecast_time.hour)
    return forecast_time.replace(hour=hour, minute=0, second=0, microsecond=0)


def covered(init: datetime) -> bool:
    return init >= COVERAGE_START


def _url(init: datetime) -> str:
    return (f"{BASE}/gfs.{init:%Y%m%d}/{init:%H}/atmos/"
            f"gfs.t{init:%H}z.pgrb2.0p25.f{LEAD_HOURS:03d}")


def fetch_accumulation(init: datetime, timeout: int = 120
                       ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Global three-day rainfall accumulation, mm, and its lat/lon axes.

    Cached as .npz, so the network is touched once per forecast cycle.
    """
    cache = CACHE_DIR / f"apcp72_{init:%Y%m%d%H}.npz"
    if cache.exists():
        z = np.load(cache)
        return z["lats"], z["lons"], z["mm"]

    import eccodes

    url = _url(init)
    with https_open(url + ".idx", timeout=timeout) as resp:
        idx = resp.read().decode().splitlines()
    records = [line.split(":") for line in idx]
    k = next((i for i, r in enumerate(records)
              if r[3] == FIELD[0] and FIELD[1] in r[5]), None)
    if k is None or k + 1 >= len(records):
        raise LookupError(f"no {FIELD[0]} {FIELD[1]} field in {url}")
    start, end = int(records[k][1]), int(records[k + 1][1]) - 1

    req = https_request(url, headers={"Range": f"bytes={start}-{end}"})
    with https_open(req, timeout=timeout) as resp:
        blob = resp.read()

    gid = eccodes.codes_new_from_message(blob)
    try:
        # Typed getters: a malformed message fails here, loudly, rather than
        # handing a string or None to reshape.
        ni = int(eccodes.codes_get_long(gid, "Ni"))
        nj = int(eccodes.codes_get_long(gid, "Nj"))
        mm = np.asarray(eccodes.codes_get_values(gid), dtype=float).reshape(nj, ni)
        la1 = float(eccodes.codes_get_double(gid, "latitudeOfFirstGridPointInDegrees"))
        lo1 = float(eccodes.codes_get_double(gid, "longitudeOfFirstGridPointInDegrees"))
        dj = float(eccodes.codes_get_double(gid, "jDirectionIncrementInDegrees"))
        di = float(eccodes.codes_get_double(gid, "iDirectionIncrementInDegrees"))
        north_to_south = int(eccodes.codes_get_long(gid, "jScansPositively")) == 0
    finally:
        eccodes.codes_release(gid)

    lats = la1 - np.arange(nj) * dj if north_to_south else la1 + np.arange(nj) * dj
    lons = lo1 + np.arange(ni) * di

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(cache, lats=lats, lons=lons, mm=mm.astype("float32"))
    return lats, lons, mm


def on_grid(init: datetime, lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
    """The accumulation bilinearly interpolated onto the hazard grid, mm."""
    from scipy.interpolate import RegularGridInterpolator

    g_lats, g_lons, mm = fetch_accumulation(init)
    if g_lats[0] > g_lats[-1]:                      # interpolator wants ascending
        g_lats, mm = g_lats[::-1], mm[::-1]
    interp = RegularGridInterpolator((g_lats, g_lons), mm, bounds_error=False, fill_value=0.0)
    points = np.column_stack([lats.ravel(), np.mod(lons.ravel(), 360.0)])
    return np.maximum(interp(points).reshape(lats.shape), 0.0)


def member_fields(gfs_mm: np.ndarray, parametric: list[np.ndarray]) -> list[np.ndarray]:
    """Spread a deterministic GFS field across the ensemble.

    Each member keeps GFS's amount and pattern but shifts it the way its own
    track shifts the rain: GFS × (member's parametric rain / ensemble mean).
    Giving every member the identical field would collapse every rainfall
    probability to 0 or 1.
    """
    mean = np.mean(np.stack(parametric), axis=0)
    safe = np.where(mean > 1.0, mean, 1.0)
    lo, hi = RATIO_BOUNDS
    return [gfs_mm * np.clip(np.where(mean > 1.0, p / safe, 1.0), lo, hi) for p in parametric]


def window(init: datetime) -> tuple[datetime, datetime]:
    return init, init + timedelta(hours=LEAD_HOURS)

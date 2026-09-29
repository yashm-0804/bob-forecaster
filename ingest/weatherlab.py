"""Real AI ensemble forecasts from Google DeepMind's Weather Lab archive.

Until this existed, the ensemble was built by perturbing IMD's best track --
which means the verification panel was scoring the ensemble against the very
track it was made from. That measures whether the spread is honestly sized; it
cannot measure skill.

Weather Lab publishes the cyclone forecasts its models actually issued, per
initialisation time, with every ensemble member: position, central pressure,
maximum wind and a radius of maximum wind. For a storm inside the archive's
coverage (2022 onward) that is a forecast made *before* landfall, and scoring
it against the best track is real verification.

Licence: data relating to a time more than 48 hours ago is CC BY 4.0. Every
storm replayed here is historical. Attribution: Google DeepMind Weather Lab.

Three deliberate choices, each documented where it is made:
  - past positions come from the best track, because at issue time the past
    is known;
  - no land-decay factor is applied, because the model's own intensity
    already weakens the storm over land;
  - a member whose track ends is continued as a dissipated storm, not
    dropped, so every member spans the whole replay.
"""

from __future__ import annotations

import io
import math
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    import pandas as pd

from hazard.holland import TrackPoint
from ingest.net import https_open, https_request
from ingest.tracks import KT_TO_MS, PENV_HPA, Storm, radius_of_maximum_wind_km

BASE_URL = "https://deepmind.google.com/science/weatherlab/download/cyclones"
CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache" / "weatherlab"

#: WeatherNext 3 -- the model family the brief's dossier points at.
DEFAULT_MODEL = "WNV3"

#: First initialisation time each model family has in the archive.
COVERAGE_START = {"WNV3": datetime(2024, 1, 1), "FNV3P2": datetime(2022, 1, 1)}

#: Forecasts are initialised four times a day.
INIT_HOURS = (0, 6, 12, 18)

#: A member that has dissipated still needs a track point for every replay
#: time. It is held at its last position with this intensity -- weak enough
#: that it contributes no wind damage above Emanuel's 25.7 m/s threshold.
DISSIPATED_VMAX_MS = 5.0

ATTRIBUTION = "Google DeepMind Weather Lab, CC BY 4.0"



def issue_time_for(landfall: datetime, lead_hours: float) -> datetime:
    """The latest initialisation at or before `lead_hours` ahead of landfall.

    Rounded down, never up: a T-48 advisory must use a forecast that existed
    48 hours out, not one issued three hours later.
    """
    target = landfall - timedelta(hours=lead_hours)
    hour = max(h for h in INIT_HOURS if h <= target.hour)
    return target.replace(hour=hour, minute=0, second=0, microsecond=0)


def covered(when: datetime, model: str = DEFAULT_MODEL) -> bool:
    return when >= COVERAGE_START.get(model, datetime.max)


def fetch(init: datetime, model: str = DEFAULT_MODEL, timeout: int = 300) -> pd.DataFrame:
    """The ensemble CSV for one initialisation time, cached on disk.

    The archive is slow -- a single file can take over a minute -- so every
    download is cached and never repeated.
    """
    import pandas as pd

    name = f"{model}_{init:%Y_%m_%dT%H}_00_paired.csv"
    cache = CACHE_DIR / name
    if not cache.exists():
        url = f"{BASE_URL}/{model}/ensemble/paired/csv/{name}"
        req = https_request(url, headers={"User-Agent": "bob-forecaster/0.1"})
        with https_open(req, timeout=timeout) as resp:
            body = resp.read()
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(body)
    return pd.read_csv(io.StringIO(cache.read_text()), comment="#",
                       parse_dates=["init_time", "valid_time"])


def find_track(df: pd.DataFrame, lat: float, lon: float, max_km: float = 300.0) -> str:
    """The forecast track that starts nearest a known storm position.

    Files are global -- the Montha file also carries Hurricane Melissa and an
    eastern Pacific storm -- so the storm is picked by position at lead zero,
    and refused if nothing starts within `max_km`.
    """
    start = df[df.lead_time_hours == 0].groupby("track_id")[["lat", "lon"]].mean()
    if start.empty:
        raise LookupError("forecast file has no tracks")
    lats = start["lat"].to_numpy(dtype=float)
    lons = start["lon"].to_numpy(dtype=float)
    km = 111.0 * np.hypot(lats - lat, (lons - lon) * math.cos(math.radians(lat)))
    k = int(np.argmin(km))
    best = str(start.index[k])
    if km[k] > max_km:
        raise LookupError(
            f"no forecast track within {max_km:.0f} km of {lat:.1f}N {lon:.1f}E "
            f"(nearest {best} at {km[k]:.0f} km)"
        )
    return best


def _motion(lat1: float, lon1: float, lat2: float, lon2: float,
            hours: float) -> tuple[float, float]:
    if hours <= 0:
        return 0.0, 0.0
    dy = (lat2 - lat1) * 111.0
    dx = (lon2 - lon1) * 111.0 * math.cos(math.radians((lat1 + lat2) / 2))
    bearing = (math.degrees(math.atan2(dx, dy)) + 360.0) % 360.0
    return bearing, math.hypot(dx, dy) * 1000.0 / (hours * 3600.0)


def _interp_finite(hours: np.ndarray, at: np.ndarray, values: np.ndarray) -> np.ndarray:
    """Interpolate onto `hours` using only the finite values.

    An invest -- a disturbance not yet named -- is archived with no intensity
    at lead zero, and a single NaN would otherwise spread into every wind
    field computed from that member.
    """
    ok = np.isfinite(values)
    if not ok.any():
        return np.full_like(hours, np.nan, dtype=float)
    return np.interp(hours, at[ok], values[ok])


def members_for(storm: Storm, init: datetime, model: str = DEFAULT_MODEL,
                df: pd.DataFrame | None = None) -> tuple[list[list[TrackPoint]], dict[str, Any]]:
    """Every ensemble member, resampled onto the storm's best-track times.

    Returns the members and a provenance record for the run summary. Times
    before `init` take the best track -- the past was known when the forecast
    was issued -- and times after are interpolated from each member.
    """
    if df is None:
        df = fetch(init, model)

    anchor = storm.at(init)
    track_id = find_track(df, storm.track[anchor].lat, storm.track[anchor].lon)
    fc = df[df.track_id == track_id]

    t0 = storm.times[0]
    hours = np.array([(t - t0).total_seconds() / 3600.0 for t in storm.times])
    init_h = (init - t0).total_seconds() / 3600.0

    members: list[list[TrackPoint]] = []
    for _, m in fc.groupby("sample"):
        m = m.sort_values("valid_time")
        mh = ((m.valid_time - t0).dt.total_seconds() / 3600.0).to_numpy()

        def interp(col: str, m: pd.DataFrame = m, mh: np.ndarray = mh) -> np.ndarray:
            return _interp_finite(hours, mh, m[col].to_numpy(dtype=float))

        lat, lon = interp("lat"), interp("lon")
        vmax = interp("maximum_sustained_wind_speed_knots") * KT_TO_MS
        pmin = interp("minimum_sea_level_pressure_hpa")
        if not np.isfinite(vmax).all() or not np.isfinite(pmin).all():
            continue  # a member with no usable intensity at all is dropped, not guessed
        rmax = interp("radius_of_maximum_winds_km")
        ended = hours > mh.max()

        track: list[TrackPoint] = []
        for i, h in enumerate(hours):
            if h < init_h:                      # already observed at issue time
                track.append(storm.track[i])
                continue
            if ended[i]:                        # dissipated in this member
                last = track[-1]
                track.append(TrackPoint(**{**last.__dict__, "vmax_ms": DISSIPATED_VMAX_MS,
                                           "pcen_hpa": PENV_HPA - 1.0, "trans_speed_ms": 0.0}))
                continue
            j = min(i + 1, len(hours) - 1)
            bearing, speed = _motion(lat[i], lon[i], lat[j], lon[j], hours[j] - hours[i])
            r = rmax[i] if np.isfinite(rmax[i]) and rmax[i] > 0 else \
                radius_of_maximum_wind_km(vmax[i], lat[i])
            track.append(TrackPoint(
                lat=float(lat[i]), lon=float(lon[i]),
                vmax_ms=float(vmax[i]),
                pcen_hpa=float(min(pmin[i], PENV_HPA - 1.0)),
                rmax_km=float(np.clip(r, 8.0, 150.0)),
                penv_hpa=PENV_HPA,
                trans_speed_ms=speed, trans_dir_deg=bearing,
                hours_inland=0.0,               # model intensity already decays over land
            ))
        members.append(track)

    provenance = {
        "source": "weatherlab",
        "model": model,
        "track_id": track_id,
        "issued": init.isoformat(),
        "members": len(members),
        "attribution": ATTRIBUTION,
    }
    return members, provenance

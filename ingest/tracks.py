"""Storm tracks from the IMD RSMC New Delhi best-track record.

`imdtrack` publishes IMD's official post-analysis positions for every North
Indian Ocean system since 1982. Best track is the after-the-fact truth, so it
is what we replay against; a live run would swap this for the forecast track
parsed out of an IMD bulletin, which produces the same TrackPoint list.

Two quantities the model needs are not in the best-track record and are
derived here: the radius of maximum wind, and the storm's forward motion.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from hazard.holland import TrackPoint
from ingest.net import use_certifi_globally

KT_TO_MS = 0.514444

#: Environmental pressure for the Bay of Bengal in cyclone season.
PENV_HPA = 1008.0

#: IMD 3-minute-sustained intensity categories, lower bound in knots.
IMD_GRADES = {
    "D": "Depression",
    "DD": "Deep Depression",
    "CS": "Cyclonic Storm",
    "SCS": "Severe Cyclonic Storm",
    "VSCS": "Very Severe Cyclonic Storm",
    "ESCS": "Extremely Severe Cyclonic Storm",
    "SuCS": "Super Cyclonic Storm",
}



def radius_of_maximum_wind_km(vmax_ms: float, lat_deg: float) -> float:
    """Estimate Rmax from intensity and latitude.

    Willoughby & Rahn (2004), fitted to aircraft reconnaissance. Rmax is not
    in the IMD record but it sets how wide the damage swath is, so it cannot
    simply be assumed constant -- weaker, higher-latitude storms are broader.
    """
    rmax = 46.4 * math.exp(-0.0155 * vmax_ms + 0.0169 * abs(lat_deg))
    return float(min(max(rmax, 15.0), 150.0))


def _bearing_and_speed(
    lat1: float, lon1: float, t1: datetime, lat2: float, lon2: float, t2: datetime
) -> tuple[float, float]:
    """Forward motion between two track positions: (bearing deg, speed m/s)."""
    hours = (t2 - t1).total_seconds() / 3600.0
    if hours <= 0:
        return 0.0, 0.0

    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlam = math.radians(lon2 - lon1)
    y = math.sin(dlam) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dlam)
    bearing = (math.degrees(math.atan2(y, x)) + 360.0) % 360.0

    dy = (lat2 - lat1) * 111.0
    dx = (lon2 - lon1) * 111.0 * math.cos(math.radians((lat1 + lat2) / 2))
    speed = math.hypot(dx, dy) * 1000.0 / (hours * 3600.0)
    return bearing, speed


@dataclass
class Storm:
    """A named system with its track and the metadata the UI needs."""

    storm_id: str
    name: str
    basin: str
    track: list[TrackPoint]
    times: list[datetime]
    grades: list[str]
    #: Index of the track point at landfall, if the storm made one.
    landfall_index: int | None = None

    @property
    def peak_grade(self) -> str:
        order = list(IMD_GRADES)
        return max(self.grades, key=lambda g: order.index(g) if g in order else -1)

    @property
    def peak_vmax_ms(self) -> float:
        return max(p.vmax_ms for p in self.track)

    @property
    def min_pressure_hpa(self) -> float:
        return min(p.pcen_hpa for p in self.track)

    def at(self, when: datetime) -> int:
        """Index of the track point nearest a given time."""
        return min(range(len(self.times)), key=lambda i: abs(self.times[i] - when))

    def up_to(self, when: datetime) -> list[TrackPoint]:
        """Track points at or before a time.

        Replaying a forecast means using only what was known then, so every
        hazard computation is bounded by this rather than the full track.
        """
        return [p for p, t in zip(self.track, self.times, strict=True) if t <= when]


def load_storm(name: str, year: int | None = None) -> Storm:
    """Load one named storm from the IMD best-track record.

    Raises LookupError if the name is not in the record, which is more useful
    than silently returning an empty track.
    """
    # imdtrack opens its own connections; see ingest/net.py.
    use_certifi_globally()
    import imdtrack

    df = imdtrack.load().to_dataframe()
    sel = df[df["name"].astype(str).str.upper() == name.upper()]
    if year is not None:
        sel = sel[sel["year"] == year]
    if sel.empty:
        raise LookupError(f"{name!r} not found in the IMD best-track record")

    sel = sel.sort_values("time_resolved").reset_index(drop=True)
    times = [t.to_pydatetime() for t in sel["time_resolved"]]

    # Plain arrays, iterated by position: clearer than iterrows, and exactly
    # typed where pandas' row index is not.
    lats = sel["lat"].to_numpy(dtype=float)
    lons = sel["lon"].to_numpy(dtype=float)
    winds = sel["wind"].to_numpy(dtype=float)
    pressures = sel["pressure"].to_numpy(dtype=float)

    points: list[TrackPoint] = []
    for i in range(len(sel)):
        vmax_ms = float(winds[i]) * KT_TO_MS
        lat, lon = float(lats[i]), float(lons[i])

        # Forward motion from the neighbouring positions. The last point
        # inherits the previous step's motion rather than reporting zero,
        # which would drop the asymmetry term exactly at landfall.
        if i + 1 < len(sel):
            bearing, speed = _bearing_and_speed(
                lat, lon, times[i], float(lats[i + 1]), float(lons[i + 1]), times[i + 1],
            )
        elif points:
            bearing, speed = points[-1].trans_dir_deg, points[-1].trans_speed_ms
        else:
            bearing, speed = 0.0, 0.0

        points.append(
            TrackPoint(
                lat=lat,
                lon=lon,
                vmax_ms=vmax_ms,
                pcen_hpa=float(pressures[i]),
                rmax_km=radius_of_maximum_wind_km(vmax_ms, lat),
                penv_hpa=PENV_HPA,
                trans_speed_ms=speed,
                trans_dir_deg=bearing,
            )
        )

    storm = Storm(
        storm_id=str(sel.loc[0, "storm_id"]),
        name=str(sel.loc[0, "name"]).title(),
        basin=str(sel.loc[0, "basin"]),
        track=points,
        times=times,
        grades=[str(g) for g in sel["grade"]],
    )
    storm.landfall_index = _detect_landfall(storm)
    return storm


def _detect_landfall(storm: Storm) -> int | None:
    """First track point at which the storm begins decaying over land.

    Best track carries no landfall flag, so infer it: the step where the
    system both starts weakening and is moving onto the coast. Used to set
    `hours_inland`, which drives the overland decay term.
    """
    for i in range(1, len(storm.track)):
        prev, cur = storm.track[i - 1], storm.track[i]
        weakening = cur.vmax_ms < prev.vmax_ms and cur.pcen_hpa > prev.pcen_hpa
        if weakening and prev.vmax_ms >= 17.0:
            return i
    return None


def apply_land_decay(storm: Storm) -> Storm:
    """Set hours_inland on every track point after landfall."""
    if storm.landfall_index is None:
        return storm
    t0 = storm.times[storm.landfall_index]
    storm.track = [
        TrackPoint(
            **{
                **p.__dict__,
                "hours_inland": max((t - t0).total_seconds() / 3600.0, 0.0),
            }
        )
        for p, t in zip(storm.track, storm.times, strict=True)
    ]
    return storm

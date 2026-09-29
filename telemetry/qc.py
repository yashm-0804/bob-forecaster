"""Quality control for incoming node telemetry.

A network of cheap, drifting sensors that disagrees with IMD's calibrated
stations is a liability in an alerting system, not an asset. Every observation
passes through here before it reaches BigQuery, and anything flagged is
excluded from model fusion until a human clears it.

Checks run in order of cost: tier permissions and range checks are free,
temporal checks need the node's recent history, and neighbour consistency
needs the surrounding network.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np

from .schema import NodeObservation, permitted_fields


class Flag:
    """QC flag constants. Presence of any flag excludes a reading from fusion."""

    TIER_VIOLATION = "tier_violation"
    OUT_OF_RANGE = "out_of_range"
    SPIKE = "spike"
    FLATLINE = "flatline"
    NEIGHBOUR_DISAGREE = "neighbour_disagree"
    DRIFT_SUSPECTED = "drift_suspected"
    STALE = "stale"
    LOW_BATTERY = "low_battery"
    MISSING_DATUM = "missing_datum"
    #: A channel the node reported as null: a dead or unplugged sensor.
    MISSING = "missing"


def on(flag: str, channel: str) -> str:
    """Name the channel a flag applies to, e.g. ``flatline:temp_c``.

    A seized thermometer should not invalidate a good pressure reading, and
    operationally the flag doubles as a maintenance ticket naming the sensor
    to replace.
    """
    return f"{flag}:{channel}"


def has(flags: list[str], flag: str) -> bool:
    """Whether any flag of this kind is present, on any channel."""
    return any(f == flag or f.startswith(f"{flag}:") for f in flags)


#: Expected sea-level pressure at a position, hPa: the storm analysis QC
#: compares observations against.
Background = Callable[[float, float], float]


def channel_of(flag: str) -> str | None:
    """The channel a flag names, or None if it applies to the whole reading."""
    return flag.split(":", 1)[1] if ":" in flag else None


#: Plausible physical ranges for the Bay of Bengal coast. Deliberately wide --
#: these catch broken sensors, not unusual weather. The 1999 Odisha Super
#: Cyclone bottomed out at 912 hPa, so the pressure floor sits below that.
RANGES: dict[str, tuple[float, float]] = {
    "pressure_hpa": (900.0, 1080.0),
    "temp_c": (-5.0, 55.0),
    "rh_pct": (0.0, 100.0),
    "rain_mm_15m": (0.0, 150.0),
    "wind_ms": (0.0, 90.0),
    "wind_dir_deg": (0.0, 360.0),
    "water_level_m": (-5.0, 20.0),
    "tilt_deg": (-90.0, 90.0),
    "battery_v": (2.8, 4.3),
}

#: Largest believable change between consecutive 15-minute readings.
#: Anything beyond this is a sensor fault, not weather. Amphan deepened at
#: roughly 2 hPa/hr sustained, so 6 hPa in 15 min is comfortably above any
#: real rate of change.
SPIKE_LIMITS: dict[str, float] = {
    "pressure_hpa": 6.0,
    "temp_c": 8.0,
    "rh_pct": 40.0,
    "water_level_m": 2.0,
}

#: The spike limits above are per 15-minute reporting interval. A gap in the
#: record -- a dropped packet -- scales them, so two readings 45 minutes apart
#: are not held to a 15-minute limit.
REPORT_INTERVAL = timedelta(minutes=15)

#: Readings that must change over this window or the sensor has seized. Two
#: hours of 15-minute reports is eight readings; a working sensor with 0.01
#: resolution does not repeat itself to within these margins that many times.
#: This was six hours, which let a seized thermometer through for six hours.
FLATLINE_WINDOW = timedelta(hours=2)
FLATLINE_MIN_READINGS = 6
FLATLINE_EPSILON = {"pressure_hpa": 0.05, "temp_c": 0.05, "rh_pct": 0.5}

#: Values pinned at a physical limit are legitimately constant: saturated air
#: reads 100% humidity for hours in a cyclone. Not a seized sensor.
PHYSICAL_LIMITS = {"rh_pct": (0.5, 99.5)}

STALE_AFTER = timedelta(hours=2)
LOW_BATTERY_V = 3.3

#: Pressure is smooth over tens of km, so a node disagreeing sharply with its
#: neighbours after reduction to MSL is broken rather than observing something
#: real. Wind and rain are deliberately excluded -- they decorrelate too fast
#: for this check to mean anything.
NEIGHBOUR_TOLERANCE_HPA = 3.0
#: The RMS distance, in km, neighbours must be spread along a direction for
#: a pressure gradient to be fitted along it. Tier A spacing is ~25 km, so
#: neighbours spread less than this are, for a gradient, one place.
MIN_NEIGHBOUR_SPREAD_KM = 2.0

#: A slow drift never trips the neighbour tolerance: a barometer creeping
#: 0.06 hPa an hour stays inside 3 hPa for two days, and in the first
#: simulated run only 7 of 162 drifting readings were caught. So each
#: reading's residual against its neighbours is kept, and a node whose
#: residuals stay biased one way over DRIFT_WINDOW is flagged.
DRIFT_WINDOW = timedelta(hours=12)
DRIFT_MIN_READINGS = 16
DRIFT_BIAS_HPA = 1.0
DRIFT_SIGN_AGREEMENT = 0.8
#: The most recent readings, which must also show the bias.
DRIFT_RECENT_READINGS = 8
#: Neighbour misfit above which a residual is not counted towards drift.
DRIFT_MAX_FIELD_MISFIT = 1.0

#: Standard atmosphere lapse for reducing station pressure to MSL.
_LAPSE_HPA_PER_M = 0.12


@dataclass
class QCContext:
    """What the checks need beyond the observation itself."""

    #: Most recent prior observation from this node, if any.
    previous: NodeObservation | None = None
    #: Readings from this node over FLATLINE_WINDOW, oldest first.
    history: list[NodeObservation] | None = None
    #: Concurrent readings from nearby nodes, for consistency checking.
    neighbours: list[NodeObservation] | None = None
    #: Wall-clock time to judge staleness against.
    now: datetime | None = None
    #: This node's neighbour residuals over DRIFT_WINDOW, oldest first.
    residual_history: list[float] | None = None
    #: Expected sea-level pressure at a point from the current storm
    #: analysis -- (lat, lon) -> hPa -- or None when there is no storm.
    background: Background | None = None


def pressure_msl(obs: NodeObservation) -> float:
    """Reduce station pressure to mean sea level.

    Without this, an ELEVATED node reads systematically low and would fail
    neighbour consistency against sea-level nodes every single cycle. Only
    called on readings that have a pressure; see `_with_pressure`.
    """
    if obs.pressure_hpa is None:
        raise ValueError(f"{obs.node_id} reported no pressure")
    return obs.pressure_hpa + obs.elev_m * _LAPSE_HPA_PER_M


def _with_pressure(nodes: list[NodeObservation] | None) -> list[NodeObservation]:
    """Neighbours that can take part in a pressure comparison at all."""
    return [n for n in nodes or [] if n.pressure_hpa is not None]


#: The channels every node carries. A null here is a dead sensor, not a
#: missing field: it is flagged so the reading is kept but never fused.
BASE_CHANNELS = ("pressure_hpa", "temp_c", "rh_pct")


def check_missing(obs: NodeObservation) -> list[str]:
    """Name each base channel -- and the battery -- that came back null."""
    flags = [on(Flag.MISSING, name) for name in BASE_CHANNELS if getattr(obs, name) is None]
    if obs.battery_v is None:
        flags.append(on(Flag.MISSING, "battery_v"))
    return flags


def check_tier_permissions(obs: NodeObservation) -> list[str]:
    """Reject fields the node has no instrument to measure."""
    allowed = permitted_fields(obs.tier)
    populated = obs.populated_optional_fields()
    if populated - allowed:
        return [Flag.TIER_VIOLATION]
    # A water level without a datum reference is not comparable to anything.
    if obs.water_level_m is not None and not obs.datum_ref:
        return [Flag.MISSING_DATUM]
    return []


def check_ranges(obs: NodeObservation) -> list[str]:
    """Catch readings outside physical plausibility, per channel."""
    flags: list[str] = []
    for name, (lo, hi) in RANGES.items():
        value = getattr(obs, name, None)
        if value is not None and not (lo <= value <= hi):
            flags.append(on(Flag.OUT_OF_RANGE, name))
    if obs.soil_vwc_pct is not None and any(not (0.0 <= v <= 100.0) for v in obs.soil_vwc_pct):
        flags.append(on(Flag.OUT_OF_RANGE, "soil_vwc_pct"))
    return flags


def check_spike(obs: NodeObservation, previous: NodeObservation | None) -> list[str]:
    """Catch step changes too large to be weather, allowing for gaps."""
    if previous is None:
        return []
    try:
        gap = datetime.fromisoformat(obs.ts) - datetime.fromisoformat(previous.ts)
        intervals = max(gap / REPORT_INTERVAL, 1.0)
    except (TypeError, ValueError):
        intervals = 1.0
    flags: list[str] = []
    for name, limit in SPIKE_LIMITS.items():
        current, prior = getattr(obs, name, None), getattr(previous, name, None)
        if current is not None and prior is not None and abs(current - prior) > limit * intervals:
            flags.append(on(Flag.SPIKE, name))
    return flags


def check_flatline(history: list[NodeObservation] | None) -> list[str]:
    """Catch a seized sensor reporting the same value indefinitely."""
    if not history or len(history) < FLATLINE_MIN_READINGS:
        return []
    flags: list[str] = []
    for name, epsilon in FLATLINE_EPSILON.items():
        values = [getattr(o, name) for o in history if getattr(o, name) is not None]
        if len(values) < FLATLINE_MIN_READINGS:
            continue
        lo, hi = PHYSICAL_LIMITS.get(name, (-math.inf, math.inf))
        if all(v >= hi or v <= lo for v in values):
            continue          # pinned at a physical limit, not seized
        if (max(values) - min(values)) < epsilon:
            flags.append(on(Flag.FLATLINE, name))
    return flags


def _no_background(lat: float, lon: float) -> float:
    return 0.0


def neighbour_fit(
    obs: NodeObservation, neighbours: list[NodeObservation] | None,
    background: Background | None = None,
) -> tuple[float, float] | None:
    """This node's pressure residual against its neighbours, and how well
    the neighbours agree with each other.

    With four or more neighbours a plane is fitted through their sea-level
    pressures by position and evaluated here -- or a line, when they lie
    along one, or nothing but their median when they are all in one place.
    The median used before assumed pressure is flat across 40 km -- true on
    a quiet day, badly false near a cyclone, where in simulation it flagged
    186 clean readings. A plane absorbs the gradient.

    It cannot absorb curvature, and the deepest curvature is the eye. The
    second value -- the RMS misfit of the neighbours to their own plane --
    says how disturbed the field is, so the checks can be exactly as
    confident as the neighbours are consistent.
    """
    neighbours = _with_pressure(neighbours)
    if not neighbours or obs.pressure_hpa is None:
        return None
    # With a background, compare observation-minus-expected rather than raw
    # pressure: the storm's own structure cancels and what is left is sensor
    # error. Without it, a node alone inside the eye -- a feature smaller than
    # the network spacing -- is indistinguishable from a broken one, which is
    # exactly what the first simulation showed.
    bg: Background = background or _no_background
    here = pressure_msl(obs) - bg(obs.lat, obs.lon)
    readings = np.array([pressure_msl(n) - bg(n.lat, n.lon) for n in neighbours])
    if len(neighbours) >= 4:
        kx = 111.0 * math.cos(math.radians(obs.lat))
        xy = np.array([[(n.lon - obs.lon) * kx, (n.lat - obs.lat) * 111.0] for n in neighbours])
        centre = xy.mean(axis=0)
        # Fit only along directions the neighbours actually span. Along a
        # coast road they span one: a plane through them has no slope across
        # the road, and least squares then invents one -- it once put a clean
        # node 5 km off the road 966 hPa from its neighbours. There the fit
        # is a line along the road, with no gradient assumed across it.
        _, spread, axes = np.linalg.svd(xy - centre, full_matrices=False)
        spanned = axes[spread / math.sqrt(len(neighbours)) >= MIN_NEIGHBOUR_SPREAD_KM]
        if len(spanned):
            A = np.column_stack([np.ones(len(neighbours)), (xy - centre) @ spanned.T])
            coef, *_ = np.linalg.lstsq(A, readings, rcond=None)
            expected = float(coef[0] + (-centre @ spanned.T) @ coef[1:])
            misfit = float(np.sqrt(np.mean((A @ coef - readings) ** 2)))
            return float(here - expected), misfit
    return float(here - np.median(readings)), float(np.std(readings))


def neighbour_residual(
    obs: NodeObservation, neighbours: list[NodeObservation] | None,
    background: Background | None = None,
) -> float | None:
    """A residual fit to count as evidence of drift, or None.

    None when the neighbours themselves disagree by more than
    DRIFT_MAX_FIELD_MISFIT: a node beside a passing eye reads far below its
    neighbours for hours, and in simulation that alone produced 16 false
    drift flags -- on the node 9 km from landfall, the most valuable reading
    in the network.
    """
    fit = neighbour_fit(obs, neighbours, background)
    if fit is None or fit[1] > DRIFT_MAX_FIELD_MISFIT:
        return None
    return fit[0]


def check_neighbours(
    obs: NodeObservation, neighbours: list[NodeObservation] | None,
    background: Background | None = None,
) -> list[str]:
    """Compare sea-level pressure against the surrounding network.

    The tolerance widens with the neighbours' own misfit: where they cannot
    agree on a smooth field, one node disagreeing with them is weak evidence.
    """
    fit = neighbour_fit(obs, neighbours, background)
    if fit is None:
        return []
    residual, misfit = fit
    if abs(residual) > max(NEIGHBOUR_TOLERANCE_HPA, 3.0 * misfit):
        return [on(Flag.NEIGHBOUR_DISAGREE, "pressure_hpa")]
    return []


def _sign(x: float) -> int:
    return (x > 0) - (x < 0)


def check_drift(residuals: list[float] | None) -> list[str]:
    """A barometer that sits consistently to one side of its neighbours."""
    if not residuals or len(residuals) < DRIFT_MIN_READINGS:
        return []
    # Median, not mean, and the bias must still be there now. A drifting
    # sensor stays off; a node that read an eye for four hours and has since
    # returned to agreeing with its neighbours is not drifting -- but a
    # 12-hour mean kept flagging it for hours after it recovered.
    level = float(np.median(residuals))
    recent = float(np.median(residuals[-DRIFT_RECENT_READINGS:]))
    same_sign = sum(_sign(r) == _sign(level) for r in residuals) / len(residuals)
    if (abs(level) > DRIFT_BIAS_HPA and abs(recent) > DRIFT_BIAS_HPA
            and _sign(recent) == _sign(level)
            and same_sign >= DRIFT_SIGN_AGREEMENT):
        return [on(Flag.DRIFT_SUSPECTED, "pressure_hpa")]
    return []


def check_housekeeping(
    obs: NodeObservation, now: datetime | None
) -> list[str]:
    """Staleness and battery state."""
    flags: list[str] = []
    if now is not None:
        age = now - datetime.fromisoformat(obs.ts)
        if age > STALE_AFTER:
            flags.append(Flag.STALE)
    if obs.battery_v is not None and obs.battery_v < LOW_BATTERY_V:
        flags.append(Flag.LOW_BATTERY)
    return flags


def run(obs: NodeObservation, ctx: QCContext | None = None) -> list[str]:
    """Run every check and return the accumulated flags.

    Returns an empty list for a clean reading. The caller writes the flags onto
    the observation before it lands in BigQuery, so bad data is retained and
    visible rather than silently dropped -- a flagged node is a maintenance
    ticket, and the record of when it started drifting is the evidence.
    """
    ctx = ctx or QCContext()
    flags: list[str] = []
    flags += check_tier_permissions(obs)
    flags += check_missing(obs)
    flags += check_ranges(obs)
    flags += check_spike(obs, ctx.previous)
    flags += check_flatline(ctx.history)
    flags += check_neighbours(obs, ctx.neighbours, ctx.background)
    flags += check_drift(ctx.residual_history)
    flags += check_housekeeping(obs, ctx.now)
    return flags


#: Flags that describe the reading as a whole rather than one sensor.
_WHOLE_READING = {Flag.TIER_VIOLATION, Flag.MISSING_DATUM, Flag.STALE}

#: Flags that are maintenance signals, not reasons to distrust the data.
_ADVISORY_ONLY = {Flag.LOW_BATTERY}
#: A null battery is a maintenance signal too: the readings are unaffected.
_ADVISORY_CHANNELS = {on(Flag.MISSING, "battery_v")}


def is_fusable(flags: list[str], channel: str | None = None) -> bool:
    """Whether a reading may enter model fusion.

    With no ``channel``, asks whether the reading is clean overall. With one,
    asks only about that variable: a node whose thermometer has seized still
    contributes a usable pressure observation, which matters because Tier A
    pressure is the backbone of the whole network.
    """
    for flag in flags:
        base = flag.split(":", 1)[0]
        if base in _ADVISORY_ONLY or flag in _ADVISORY_CHANNELS:
            continue
        if base in _WHOLE_READING:
            return False
        if channel is None or channel_of(flag) in (None, channel):
            return False
    return True

"""Telemetry ingest: validate, quality-check, store.

The production path is gateway -> Cloud Run -> Pub/Sub -> QC -> BigQuery.
This is the same pipeline with SQLite standing in for the last two hops: one
table shaped like the BigQuery table would be, and the same QC gate in front
of it. Swapping the store is the only change needed to move it to the cloud.

Nothing is dropped. A reading that fails QC is stored with its flags and
excluded from fusion, because a node's record of when it started drifting is
the evidence for its maintenance ticket.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
import threading
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import asdict, fields
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from common.sqlite import connect
from telemetry import qc
from telemetry.schema import NodeObservation, SiteClass, Tier

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "telemetry.sqlite3"

#: How far to look for neighbours, and how close in time they must be.
NEIGHBOUR_RADIUS_KM = 40.0
NEIGHBOUR_WINDOW = timedelta(minutes=20)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS observations (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id   TEXT NOT NULL,
    tier      TEXT NOT NULL,
    ts        TEXT NOT NULL,
    lat       REAL NOT NULL,
    lon       REAL NOT NULL,
    elev_m    REAL NOT NULL,
    body      TEXT NOT NULL,   -- the full observation, JSON
    qc_flags  TEXT NOT NULL,   -- JSON list
    fusable   INTEGER NOT NULL,
    nbr_residual REAL          -- pressure minus what neighbours imply, hPa
);
CREATE INDEX IF NOT EXISTS obs_by_node ON observations (node_id, ts);
CREATE INDEX IF NOT EXISTS obs_by_time ON observations (ts);
"""


class ValidationError(ValueError):
    """The message could not be read as an observation at all."""


class DuplicateObservation(ValueError):
    """This node has already reported for this time."""


class UnknownNode(ValueError):
    """The node is not in the registry this deployment was given."""


def utc_now() -> datetime:
    """Wall-clock time in the form timestamps are stored in: naive UTC."""
    return datetime.now(UTC).replace(tzinfo=None)


class RegistryError(ValueError):
    """A node registry was configured and cannot be used."""


def load_registry(path: str | None) -> frozenset[str] | None:
    """Node ids allowed to report, from a file holding a JSON list; None
    means any.

    Without a registry, anyone holding the ingest code can invent nodes, and
    enough invented neighbours can outvote a real node in the buddy check.
    A registry that is configured but unreadable is an error, never "any":
    a typo must not open ingest to every node.
    """
    if not path:
        return None
    try:
        raw: object = json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise RegistryError(
            f"the node registry cannot be read ({type(exc).__name__}); "
            "BOB_NODE_REGISTRY names a file holding a JSON list of node ids") from exc
    items = cast(list[object], raw) if isinstance(raw, list) else None
    if items is None or not all(isinstance(i, str) for i in items):
        raise RegistryError("the node registry must be a JSON list of node ids")
    return frozenset(cast(list[str], items))


def registry_problem(path: str | None) -> str | None:
    """Why the configured registry cannot be used, or None if it can (or
    none is configured)."""
    try:
        load_registry(path)
    except RegistryError as exc:
        return str(exc)
    return None


#: Numeric channels. A value may be absent (None: a dead or missing channel)
#: but never the wrong type or non-finite. Out-of-range *readings* are left to
#: QC, which flags rather than drops them; this only rejects what cannot be a
#: reading at all.
_NUMBERS = ("pressure_hpa", "temp_c", "rh_pct", "battery_v", "rssi", "rain_mm_15m",
            "wind_ms", "wind_dir_deg", "water_level_m", "tilt_deg", "rtk_displacement_mm")

#: Where a node is must be a real place: a bad position cannot be flagged and
#: kept, because every neighbour check would be computed from it.
_POSITION = {"lat": (-90.0, 90.0), "lon": (-180.0, 180.0), "elev_m": (-500.0, 9000.0)}

_NODE_ID = re.compile(r"[A-Za-z0-9_.-]{1,64}")
#: A node clock this far ahead is broken, and its readings would sit in every
#: later reading's history window.
MAX_CLOCK_AHEAD = timedelta(hours=1)
#: Nothing this network could have recorded predates it. The bound also keeps
#: window arithmetic (ts minus hours) inside what datetime can represent.
EARLIEST = datetime(2000, 1, 1)


def _finite(name: str, value: object) -> float:
    # bool is an int in Python; true/false is not a reading.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{name} must be a number, got {type(value).__name__}")
    try:
        # JSON integers are unbounded; one past float range overflows here.
        number = float(value)
    except OverflowError as exc:
        raise ValidationError(f"{name} is too large to be a reading") from exc
    if not math.isfinite(number):
        raise ValidationError(f"{name} must be finite")
    return number


def _utc_iso(name: str, value: object) -> str:
    """ISO 8601 in, naive-UTC ISO out: the one form stored, so that time
    comparisons in SQL (which compare text) compare like with like. A
    timestamp without an offset is taken to be UTC already."""
    if not isinstance(value, str):
        raise ValidationError(f"{name} must be an ISO 8601 string")
    try:
        when = datetime.fromisoformat(value)
        if when.tzinfo is not None:
            when = when.astimezone(UTC).replace(tzinfo=None)
    except (ValueError, OverflowError) as exc:
        raise ValidationError(f"{name}: {exc}") from exc
    if when < EARLIEST:
        raise ValidationError(f"{name} is before {EARLIEST:%Y}: {value}")
    if when > datetime.now(UTC).replace(tzinfo=None) + MAX_CLOCK_AHEAD:
        raise ValidationError(f"{name} is in the future: {value}")
    return when.isoformat()


def _check_identity(data: dict[str, Any]) -> None:
    """Who and where: the fields every neighbour check is computed from."""
    node_id = data["node_id"]
    if not isinstance(node_id, str) or not _NODE_ID.fullmatch(node_id):
        raise ValidationError("node_id must be 1-64 letters, digits, '.', '_' or '-'")
    data["tier"] = Tier(data["tier"])
    data["site_class"] = SiteClass(data["site_class"])
    data["ts"] = _utc_iso("ts", data["ts"])
    for name, (lo, hi) in _POSITION.items():
        data[name] = _finite(name, data[name])
        if not lo <= data[name] <= hi:
            raise ValidationError(f"{name} {data[name]} is outside {lo}..{hi}")


def _check_readings(data: dict[str, Any]) -> None:
    """The measurements: present where required, numeric where given."""
    # Base channels must be present, even if null for a dead sensor.
    absent = [n for n in ("pressure_hpa", "temp_c", "rh_pct", "battery_v", "rssi")
              if n not in data]
    if absent:
        raise ValidationError(f"missing field: {absent[0]}")
    for name in _NUMBERS:
        if data.get(name) is not None:
            data[name] = _finite(name, data[name])
    if data.get("rssi") is not None:
        data["rssi"] = round(data["rssi"])
    soil = data.get("soil_vwc_pct")
    if soil is not None:
        values = cast(list[object], soil) if isinstance(soil, list) else None
        if values is None or not 1 <= len(values) <= 8:
            raise ValidationError("soil_vwc_pct must be a list of 1-8 numbers")
        data["soil_vwc_pct"] = [_finite("soil_vwc_pct", v) for v in values]
    datum = data.get("datum_ref")
    if datum is not None and (not isinstance(datum, str) or len(datum) > 64):
        raise ValidationError("datum_ref must be a string of at most 64 characters")


def parse(body: object) -> NodeObservation:
    """Turn a message into an observation, or say exactly what is wrong.

    Every field is checked for type before anything is stored. A message that
    got through with a text latitude used to be stored as trusted, and then
    crashed the neighbour check for every other node near it.
    """
    if not isinstance(body, dict):
        raise ValidationError("an observation must be a JSON object")
    data = dict(cast(dict[str, Any], body))
    unknown = set(data) - {f.name for f in fields(NodeObservation)}
    if unknown:
        raise ValidationError(f"unknown fields: {sorted(unknown)}")
    try:
        _check_identity(data)
        _check_readings(data)
    except KeyError as exc:
        raise ValidationError(f"missing field: {exc.args[0]}") from exc
    except ValidationError:
        raise
    except (TypeError, ValueError) as exc:
        raise ValidationError(str(exc)) from exc
    # Flags are computed here, never taken from the sender.
    data["qc_flags"] = []
    return NodeObservation(**data)


def _km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dy = (lat2 - lat1) * 111.0
    dx = (lon2 - lon1) * 111.0 * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(dx, dy)


def neighbour_box(lat: float, lon: float, km: float) -> tuple[float, float, float, float]:
    """South, north, west, east bounds holding every point within `km` of
    (lat, lon) by `_km`, with a margin; the exact distance is checked after.

    The west-east half-width uses the cosine at the box's poleward edge, the
    narrowest a degree of longitude gets inside it, so the box never cuts a
    neighbour off. Near a pole or across the antimeridian the longitude
    bounds are simply opened.
    """
    dlat = km / 111.0 * 1.01
    south, north = lat - dlat, lat + dlat
    cos_edge = math.cos(math.radians(max(abs(south), abs(north))))
    if cos_edge < 0.05:
        return south, north, -180.0, 180.0
    dlon = km / (111.0 * cos_edge) * 1.01
    if lon - dlon < -180.0 or lon + dlon > 180.0:
        return south, north, -180.0, 180.0
    return south, north, lon - dlon, lon + dlon


class TelemetryStore:
    def __init__(self, path: Path = DEFAULT_DB,
                 registry: frozenset[str] | None = None,
                 clock: Callable[[], datetime] | None = None) -> None:
        self.path = Path(path)
        self.registry = registry
        #: Wall-clock time in naive UTC, for flagging readings that arrive
        #: late. None for replays and tests, whose timestamps are historical
        #: and would otherwise all read as stale.
        self.clock = clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._db() as db:
            db.executescript(_SCHEMA)

    def probe(self) -> None:
        """Raise if the store cannot be read (see /api/health)."""
        with self._db() as db:
            db.execute("SELECT 1 FROM observations LIMIT 1").fetchall()

    def _db(self) -> AbstractContextManager[sqlite3.Connection]:
        return connect(self.path)

    @staticmethod
    def _obs(row: sqlite3.Row) -> NodeObservation:
        return parse(json.loads(row["body"]))

    #: Expected pressure from the current storm analysis, or None. Set by
    #: whatever knows where the storm is -- the pipeline, or the simulator.
    background_for: Callable[[datetime], qc.Background | None] | None = None

    def context(self, obs: NodeObservation) -> qc.QCContext:
        """Everything QC needs beyond the observation itself."""
        ts = datetime.fromisoformat(obs.ts)
        with self._db() as db:
            # The last *trusted* reading. Comparing against the last reading
            # of any kind flagged the recovery after every spike as a second
            # spike -- the good reading judged against the bad one. The spike
            # limit scales with the gap, so a longer look-back is safe.
            prev = db.execute(
                "SELECT body FROM observations WHERE node_id=? AND ts<? AND fusable=1"
                " ORDER BY ts DESC LIMIT 1",
                (obs.node_id, obs.ts)).fetchone()
            hist = db.execute(
                "SELECT body FROM observations WHERE node_id=? AND ts>=? AND ts<? ORDER BY ts",
                (obs.node_id, (ts - qc.FLATLINE_WINDOW).isoformat(), obs.ts)).fetchall()
            # Only rows near this node leave the database; which of them are
            # within the radius is decided below, exactly.
            south, north, west, east = neighbour_box(obs.lat, obs.lon, NEIGHBOUR_RADIUS_KM)
            near = db.execute(
                "SELECT body, lat, lon FROM observations WHERE node_id!=? AND ts BETWEEN ? AND ? "
                "AND fusable=1 AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?",
                (obs.node_id, (ts - NEIGHBOUR_WINDOW).isoformat(),
                 (ts + NEIGHBOUR_WINDOW).isoformat(), south, north, west, east)).fetchall()
            resid = db.execute(
                "SELECT nbr_residual FROM observations WHERE node_id=? AND ts>=? AND ts<?"
                " AND nbr_residual IS NOT NULL ORDER BY ts",
                (obs.node_id, (ts - qc.DRIFT_WINDOW).isoformat(), obs.ts)).fetchall()
        neighbours = [self._obs(r) for r in near
                      if _km(obs.lat, obs.lon, r["lat"], r["lon"]) <= NEIGHBOUR_RADIUS_KM]
        background = self.background_for(ts) if self.background_for else None
        current = qc.neighbour_residual(obs, neighbours or None, background)
        residuals = [r["nbr_residual"] for r in resid]
        if current is not None:
            residuals.append(current)
        return qc.QCContext(
            previous=self._obs(prev) if prev else None,
            history=[self._obs(r) for r in hist] + [obs],
            neighbours=neighbours or None,
            residual_history=residuals or None,
            background=background,
            now=self.clock() if self.clock else None,
        )

    def ingest(self, body: dict[str, Any]) -> dict[str, Any]:
        """Validate, QC and store one message. Returns what happened to it."""
        obs = parse(body)
        if self.registry is not None and obs.node_id not in self.registry:
            raise UnknownNode(f"node {obs.node_id} is not registered")
        # Reading the context, QC and the insert are one step under the lock:
        # two neighbours posting at once are checked in turn, the second
        # against the first's stored reading, not both against neither.
        with self._lock:
            with self._db() as db:
                # A repeat of the same node and time -- a gateway retry, or a
                # replay -- would count twice in every later window.
                if db.execute("SELECT 1 FROM observations WHERE node_id=? AND ts=? LIMIT 1",
                              (obs.node_id, obs.ts)).fetchone():
                    raise DuplicateObservation(f"{obs.node_id} already reported at {obs.ts}")
            ctx = self.context(obs)
            flags = qc.run(obs, ctx)
            residual = qc.neighbour_residual(obs, ctx.neighbours, ctx.background)
            obs.qc_flags = flags
            fusable = qc.is_fusable(flags)
            self._insert(obs, flags, fusable, residual)
        return {"node_id": obs.node_id, "ts": obs.ts, "qc_flags": flags, "fusable": fusable}

    def _insert(self, obs: NodeObservation, flags: list[str], fusable: bool,
                residual: float | None) -> None:
        with self._db() as db:
            db.execute(
                "INSERT INTO observations (node_id, tier, ts, lat, lon, elev_m, body, qc_flags,"
                " fusable, nbr_residual) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (obs.node_id, obs.tier.value, obs.ts, obs.lat, obs.lon, obs.elev_m,
                 json.dumps(asdict(obs), default=str), json.dumps(flags), int(fusable),
                 residual))

    def nodes(self) -> list[dict[str, Any]]:
        """Latest reading per node, with how many of its readings were flagged."""
        with self._db() as db:
            rows = db.execute("""
                SELECT o.*, s.n, s.flagged FROM observations o
                JOIN (SELECT node_id, MAX(id) AS last, COUNT(*) AS n,
                             SUM(1 - fusable) AS flagged
                      FROM observations GROUP BY node_id) s ON o.id = s.last
                ORDER BY o.node_id""").fetchall()
        return [{"node_id": r["node_id"], "tier": r["tier"], "lat": r["lat"], "lon": r["lon"],
                 "last_ts": r["ts"], "last_flags": json.loads(r["qc_flags"]),
                 "readings": r["n"], "flagged": r["flagged"]} for r in rows]

    def series(self, node_id: str, fusable_only: bool = True) -> list[NodeObservation]:
        with self._db() as db:
            # Two fixed queries rather than one assembled from pieces.
            query = ("SELECT body FROM observations WHERE node_id=? AND fusable=1 ORDER BY ts"
                     if fusable_only else
                     "SELECT body FROM observations WHERE node_id=? ORDER BY ts")
            rows = db.execute(query, (node_id,)).fetchall()
        return [self._obs(r) for r in rows]

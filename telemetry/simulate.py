"""A simulated sensor network, observing a real storm, with faults injected.

The telemetry schema and QC were built before anything fed them. This places
virtual nodes by the tier siting rules, has them observe a storm from the
record -- the best track driving a Holland pressure field, R-CLIPER rainfall,
tide plus surge at water-level sites, soil wetting with accumulated rain --
and sends every reading through the real ingest path.

Faults are injected deliberately, because a QC gate that has only ever seen
clean data has never been tested:

  drift        a barometer creeping upward, as cheap sensors do
  seized       a thermometer stuck at one value
  misconfig    a Tier A node reporting rainfall it has no gauge for
  spike        a single impossible pressure jump

The result states which faults QC caught and how many clean readings it
flagged by mistake. Both numbers matter: a gate that catches every fault by
flagging everything is useless.

This is a simulation. The observations are generated from the same physics
the model uses, so it tests the plumbing and the QC, not the model.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

import numpy as np

from hazard.holland import TrackPoint, holland_b
from hazard.rainfall import rain_rate_mm_hr
from ingest.tracks import Storm

if TYPE_CHECKING:
    from collections.abc import Iterator

    from exposure.osm import BBox
    from hazard.surge_screen import ElevationSource as Terrain
    from telemetry.ingest import TelemetryStore
    from telemetry.qc import Background

STEP = timedelta(minutes=15)
SEED = 20251028


@dataclass(frozen=True)
class Node:
    node_id: str
    tier: str
    lat: float
    lon: float
    elev_m: float
    site_class: str


def _site_class(elev: float, coast_km: float) -> str:
    if elev > 60:
        return "elevated"
    return "sea_level" if coast_km < 3 else "delta_flat"


def place_nodes(terrain: Terrain, bbox: BBox,
                cluster: tuple[float, float] | None = None) -> list[Node]:
    """Nodes by the tier siting rules.

    Tier A on a 25 km grid over land; Tier B at 5 km across one coastal
    cluster (a demonstration patch, not the whole coast); Tier D at the coast;
    Tier E on the steepest ground available.
    """
    nodes: list[Node] = []

    def add(tier: str, lat: float, lon: float, i: int) -> Node | None:
        e = float(terrain.elevation_m(np.array([lat]), np.array([lon]))[0])
        c = float(terrain.distance_to_coast_km(np.array([lat]), np.array([lon]))[0])
        if c < 0.5:           # in the sea, or on the waterline
            return None
        node = Node(f"{tier}{i:03d}", tier, round(lat, 4), round(lon, 4),
                    round(e, 1), _site_class(e, c))
        nodes.append(node)
        return node

    _place_backbone(add, bbox)
    if cluster:
        _place_rain_cluster(add, cluster)
    _place_water_level(add, terrain, bbox)
    _place_slopes(add, terrain, bbox)
    return nodes


AddNode = Callable[[str, float, float, int], "Node | None"]


def _place_backbone(add: AddNode, bbox: BBox) -> None:
    """Tier A on a 25 km grid over land."""
    step_a = 25.0 / 111.0
    i = 0
    for lat in np.arange(bbox.south + step_a / 2, bbox.north, step_a):
        step_lon = step_a / math.cos(math.radians(lat))
        for lon in np.arange(bbox.west + step_a / 2, bbox.east, step_lon):
            if add("A", lat, lon, i):
                i += 1


def _place_rain_cluster(add: AddNode, cluster: tuple[float, float]) -> None:
    """Tier B at 5 km across one 7 x 7 demonstration patch."""
    step_b = 5.0 / 111.0
    i = 0
    for dlat in np.arange(-3, 4) * step_b:
        for dlon in np.arange(-3, 4) * step_b:
            if add("B", cluster[0] + dlat, cluster[1] + dlon, i):
                i += 1


def _place_water_level(add: AddNode, terrain: Terrain, bbox: BBox) -> None:
    """Tier D needs a structure at the shoreline: the land points closest to
    the coast along the box."""
    i = 0
    for lat in np.linspace(bbox.south + 0.2, bbox.north - 0.2, 4):
        lons = np.linspace(bbox.west, bbox.east, 400)
        d = terrain.distance_to_coast_km(np.full_like(lons, lat), lons)
        ok = np.where((d >= 0.5) & (d < 3.0))[0]
        if len(ok):
            node = add("D", lat, float(lons[ok[0]]), i)
            i += 1 if node else 0


def _place_slopes(add: AddNode, terrain: Terrain, bbox: BBox) -> None:
    """Tier E where the ground rises fastest."""
    lats = np.linspace(bbox.south, bbox.north, 60)
    lons = np.linspace(bbox.west, bbox.east, 60)
    LA, LO = np.meshgrid(lats, lons, indexing="ij")
    z = terrain.elevation_m(LA, LO)
    gy, gx = np.gradient(z)
    order = np.argsort(np.hypot(gx, gy), axis=None)[::-1][:4]
    for i, k in enumerate(order.tolist()):
        add("E", float(LA.flat[int(k)]), float(LO.flat[int(k)]), i)


def _storm_at(storm: Storm, when: datetime) -> TrackPoint | None:
    """Best-track state at an arbitrary time, linearly interpolated."""
    times = storm.times
    if when < times[0] or when > times[-1]:
        return None
    j = next(k for k in range(1, len(times)) if times[k] >= when) if when > times[0] else 1
    a, b = storm.track[j - 1], storm.track[j]
    f = (when - times[j - 1]) / (times[j] - times[j - 1]) if times[j] > times[j - 1] else 0.0

    def mix(x: float, y: float) -> float:
        return x + (y - x) * f

    return TrackPoint(mix(a.lat, b.lat), mix(a.lon, b.lon), mix(a.vmax_ms, b.vmax_ms),
                      mix(a.pcen_hpa, b.pcen_hpa), mix(a.rmax_km, b.rmax_km), a.penv_hpa)


def _msl_pressure(p: TrackPoint, r_km: float) -> float:
    """Holland's radial pressure profile."""
    b = holland_b(p)
    r = max(r_km, 1.0)
    return p.pcen_hpa + (p.penv_hpa - p.pcen_hpa) * math.exp(-((p.rmax_km / r) ** b))


def _dist(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    return math.hypot((lat2 - lat1) * 111.0,
                      (lon2 - lon1) * 111.0 * math.cos(math.radians(lat1)))


FAULTS = ("drift", "seized", "misconfig", "spike")


def _tier_fields(msg: dict[str, Any], n: Node, hours: float, p: TrackPoint | None, r: float,
                 rain15: float, rain_so_far: float, rng: np.random.Generator) -> None:
    """The instruments only some tiers carry. Random draws stay in the same
    order as before, so a seed gives the same network it always did."""
    if n.tier == "B":
        msg["rain_mm_15m"] = round(rain15, 2)
    if n.tier == "D":
        tide = 0.6 * math.sin(2 * math.pi * hours / 12.42)
        surge = 0.0010 * (p.vmax_ms ** 2) * math.exp(-(r / 120.0) ** 2) if p else 0.0
        msg["water_level_m"] = round(1.2 + tide + surge + rng.normal(0, 0.03), 2)
        msg["datum_ref"] = f"CD-{n.node_id}"
    if n.tier == "E":
        wet = 20 + 35 * (1 - math.exp(-rain_so_far / 120.0))
        msg["soil_vwc_pct"] = [round(wet, 1), round(wet * 0.85, 1), round(wet * 0.7, 1)]
        msg["tilt_deg"] = round(rng.normal(0, 0.05), 3)


def _inject(msg: dict[str, Any], fault: str | None, hours: float, rain15: float,
            seized_temp: dict[str, float], node_id: str) -> str | None:
    """Apply this node's fault to the message, if it is active now."""
    if fault == "drift" and hours > 12:
        # A slow creep, as cheap barometers do: 0.06 hPa an hour.
        msg["pressure_hpa"] = round(msg["pressure_hpa"] + 0.06 * (hours - 12), 2)
        return "drift"
    if fault == "seized" and hours > 6:
        seized_temp.setdefault(node_id, msg["temp_c"])
        msg["temp_c"] = seized_temp[node_id]
        return "seized"
    if fault == "misconfig" and 20 < hours < 22:
        msg["rain_mm_15m"] = round(rain15, 2)
        return "misconfig"
    if fault == "spike" and abs(hours - 30) < 0.01:
        msg["pressure_hpa"] = round(msg["pressure_hpa"] + 25.0, 2)
        return "spike"
    return None


def simulate(storm: Storm, nodes: list[Node], start: datetime, end: datetime,
             dropout: float = 0.03, seed: int = SEED,
             ) -> Iterator[tuple[dict[str, Any], str | None]]:
    """Yield (message, fault) pairs in time order. `fault` is None when clean."""
    rng = np.random.default_rng(seed)
    a_nodes = [n for n in nodes if n.tier == "A"]
    faulty: dict[str, str] = {}
    picks = rng.choice(len(a_nodes), size=min(4, len(a_nodes)), replace=False)
    # strict=False on purpose: a region with fewer Tier A nodes gets fewer faults.
    for fault, k in zip(FAULTS, picks.tolist(), strict=False):
        faulty[a_nodes[int(k)].node_id] = fault

    rain_total = {n.node_id: 0.0 for n in nodes}
    seized_temp: dict[str, float] = {}
    t = start
    k = 0
    while t <= end:
        p = _storm_at(storm, t)
        hours = (t - start).total_seconds() / 3600
        for n in nodes:
            if rng.random() < dropout:
                continue
            r = _dist(p.lat, p.lon, n.lat, n.lon) if p else 1e4
            msl = _msl_pressure(p, r) if p else 1008.0
            rate = float(rain_rate_mm_hr(p, np.array([r]))[0]) if p else 0.0
            rain15 = max(rate * 0.25 * rng.lognormal(0, 0.35), 0.0)
            rain_total[n.node_id] += rain15

            msg = {
                "node_id": n.node_id, "tier": n.tier, "lat": n.lat, "lon": n.lon,
                "elev_m": n.elev_m, "site_class": n.site_class,
                "ts": t.isoformat(),
                "pressure_hpa": round(msl - n.elev_m * 0.12 + rng.normal(0, 0.08), 2),
                "temp_c": round(28.5 - 0.0065 * n.elev_m - min(rate, 20) * 0.15
                                + 2.0 * math.sin(2 * math.pi * (hours - 9) / 24)
                                + rng.normal(0, 0.15), 2),
                "rh_pct": round(min(100.0, 78 + min(rate, 20) * 1.1 + rng.normal(0, 1.5)), 1),
                "battery_v": round(3.95 - 0.0004 * k + rng.normal(0, 0.01), 3),
                "rssi": int(-92 + rng.normal(0, 4)),
            }
            _tier_fields(msg, n, hours, p, r, rain15, rain_total[n.node_id], rng)

            active = _inject(msg, faulty.get(n.node_id), hours, rain15, seized_temp, n.node_id)
            yield msg, active
        t += STEP
        k += 1


def background(storm: Storm, error_km: float) -> Callable[[datetime], Background | None]:
    """Expected pressure from a storm analysis that is `error_km` off.

    QC's background must not be the truth the observations were generated
    from, or the test is rigged. The analysis centre is displaced by
    `error_km` -- 20 km matches the WeatherNext ensemble-mean error measured
    for Montha at 15 hours' lead, the shortest lead available.
    """
    def for_time(when: datetime) -> Background | None:
        p = _storm_at(storm, when)
        if p is None:
            return None
        shift = error_km / 111.0
        centre = TrackPoint(**{**p.__dict__, "lat": p.lat + shift * 0.6,
                               "lon": p.lon + shift * 0.8 / math.cos(math.radians(p.lat))})
        return lambda lat, lon: _msl_pressure(centre, _dist(centre.lat, centre.lon, lat, lon))
    return for_time


def run(storm: Storm, terrain: Terrain, bbox: BBox, store: TelemetryStore,
        cluster: tuple[float, float] | None = None,
        hours_before: float = 48.0, hours_after: float = 6.0,
        background_error_km: float | None = 20.0) -> dict[str, Any]:
    """Place, simulate and ingest; report what QC caught and what it wrongly flagged."""
    store.background_for = (background(storm, background_error_km)
                            if background_error_km is not None else None)
    nodes = place_nodes(terrain, bbox, cluster)
    if storm.landfall_index is None:
        raise ValueError(f"{storm.name} made no landfall to simulate a network around")
    landfall = storm.times[storm.landfall_index]
    start, end = landfall - timedelta(hours=hours_before), landfall + timedelta(hours=hours_after)

    caught = {f: 0 for f in FAULTS}
    injected = {f: 0 for f in FAULTS}
    clean = clean_flagged = 0
    false_flags: dict[str, int] = {}

    for msg, fault in simulate(storm, nodes, start, end):
        result = store.ingest(msg)
        if fault:
            injected[fault] += 1
            caught[fault] += int(not result["fusable"])
        else:
            clean += 1
            if not result["fusable"]:
                clean_flagged += 1
                for f in result["qc_flags"]:
                    key = f.split(":")[0]
                    false_flags[key] = false_flags.get(key, 0) + 1

    return {
        "nodes": {t: sum(1 for n in nodes if n.tier == t)
                  for t in "ABCDE" if any(n.tier == t for n in nodes)},
        "window": [start.isoformat(), end.isoformat()],
        "faults_injected": injected,
        "faults_caught": caught,
        "clean_readings": clean,
        "clean_flagged": clean_flagged,
        "false_flag_rate": round(clean_flagged / clean, 4) if clean else 0.0,
        "false_flags_by_check": false_flags,
    }


def main() -> None:
    """Simulate a storm's sensor network and save the QC report for the console."""
    import argparse
    import json
    from pathlib import Path

    from ingest.net import use_certifi_globally

    use_certifi_globally()

    from exposure.osm import REGIONS
    from hazard.terrain import load_terrain
    from ingest.tracks import apply_land_decay, load_storm
    from telemetry.features import pressure_tendency_3h
    from telemetry.ingest import TelemetryStore

    ap = argparse.ArgumentParser(description="Simulate a sensor network observing a storm.")
    ap.add_argument("storm"); ap.add_argument("year", type=int)
    ap.add_argument("--region", default="andhra")
    ap.add_argument("--cluster", nargs=2, type=float, default=[16.58, 82.01],
                    help="centre of the 5 km Tier B cluster")
    args = ap.parse_args()

    root = Path(__file__).resolve().parent.parent
    out_dir = root / "data" / "telemetry"
    out_dir.mkdir(parents=True, exist_ok=True)
    db = out_dir / f"{args.storm.lower()}.sqlite3"
    if db.exists():
        db.unlink()

    bbox = REGIONS[args.region]
    storm = apply_land_decay(load_storm(args.storm.upper(), args.year))
    terrain, _ = load_terrain(bbox.south, bbox.north, bbox.west, bbox.east)
    store = TelemetryStore(db)
    report = run(storm, terrain, bbox, store, cluster=tuple(args.cluster))

    # The strongest pressure fall any node saw in the three hours before
    # landfall -- the signal the backbone tier exists to deliver.
    if storm.landfall_index is None:              # run() has already refused this
        raise ValueError(f"{storm.name} made no landfall")
    landfall = storm.times[storm.landfall_index]
    falls: list[tuple[float, str]] = []
    for n in store.nodes():
        t = pressure_tendency_3h(store.series(n["node_id"]), landfall)
        if t is not None:
            falls.append((t, n["node_id"]))
    falls.sort()
    report["storm"] = storm.name
    report["strongest_3h_fall_at_landfall"] = (
        {"node_id": falls[0][1], "hpa": falls[0][0]} if falls else None)
    report["note"] = ("Simulated network observing the best track. Tests the ingest "
                      "path and QC, not the model. Faults injected deliberately.")
    (out_dir / f"{args.storm.lower()}_report.json").write_text(json.dumps(report, indent=1))
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()

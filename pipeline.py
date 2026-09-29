"""End-to-end run: storm -> hazard -> exposure -> impact -> advisories.

This is the agent loop the brief's "automate early-warning advisory
dispatches" clause asks for. In production it wakes on each new IMD bulletin;
here it replays a storm from best track at a chosen forecast time, which
exercises exactly the same path.

Everything is computed per ensemble member so that what reaches an operator
is a probability with a spread, not a single number with false confidence.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, cast

import numpy as np

from advisory import gemini
from advisory.cap import RECIPIENTS, Advisory, draft
from common.errors import reraise_bugs
from exposure.osm import ANDHRA_COAST, REGIONS, BBox, load_assets
from hazard.holland import TrackPoint, make_grid, swath
from hazard.rainfall import accumulation_mm, flood_susceptibility, inland_flood_depth_m
from hazard.surge_screen import land_mask, surge_field_m
from hazard.terrain import load_terrain
from impact import triggers
from impact.rollup import AssetRisk, HazardGrids, by_class, population_affected, score_all
from ingest import gfs, weatherlab
from ingest.ensemble import LANDFALL_ERROR_KM, at_lead, exceedance, perturb, spread_basis
from ingest.tracks import Storm, apply_land_decay, load_storm
from verify.ensemble_skill import compare_with_imd_skill, verify_ensemble
from verify.observations import availability

OUT_DIR = Path(__file__).resolve().parent / "data" / "runs"

#: Broad, shallow shelf and a concave coast amplify surge here. The
#: Odisha-Andhra stretch shows the tightest wind-surge coupling in the basin.
ANDHRA_SHELF_FACTOR = 1.25

#: Astronomical tide at landfall. Storm tide is surge + tide, and the phase
#: can dominate the outcome, so it is an explicit input rather than a constant
#: buried in the surge code.
DEFAULT_TIDE_M = 0.6


@dataclass
class RunResult:
    storm: Storm
    forecast_time: datetime
    hours_to_landfall: float
    grids: HazardGrids
    land: np.ndarray
    risks: list[AssetRisk]
    advisories: list[Advisory]
    summary: dict[str, Any]


ENSEMBLE_SOURCES = ("auto", "weatherlab", "perturbed")
RAIN_SOURCES = ("auto", "gfs", "r-cliper")


def run(
    storm_name: str = "MONTHA",
    year: int = 2025,
    lead_hours: float = 48.0,
    n_members: int = 50,
    bbox: BBox = ANDHRA_COAST,
    grid_step: float = 0.02,
    tide_m: float = DEFAULT_TIDE_M,
    terrain_prefer: str = "auto",
    use_gemini: bool = True,
    ensemble_source: str = "auto",
    rain_source: str = "auto",
) -> RunResult:
    """Replay a storm as if forecasting it `lead_hours` before landfall."""
    # An unrecognised source used to fall through to the fallback silently,
    # so a typo produced a different model with no error.
    if ensemble_source not in ENSEMBLE_SOURCES:
        raise ValueError(f"ensemble_source must be one of {ENSEMBLE_SOURCES}, "
                         f"not {ensemble_source!r}")
    if rain_source not in RAIN_SOURCES:
        raise ValueError(f"rain_source must be one of {RAIN_SOURCES}, not {rain_source!r}")
    storm = apply_land_decay(load_storm(storm_name, year))
    if storm.landfall_index is None:
        raise ValueError(f"{storm_name} has no detected landfall to forecast toward")

    landfall_time = storm.times[storm.landfall_index]
    forecast_time = landfall_time - timedelta(hours=lead_hours)

    lats, lons = make_grid(bbox.south, bbox.north, bbox.west, bbox.east, grid_step)

    # Real terrain where we can get it. The coastline is then derived from the
    # elevation itself, so surge follows the delta's actual inlets rather than
    # a fitted straight line. Falls back through Earth Engine, then AWS, then
    # the flat placeholder -- which announces itself, because results computed
    # on it are directional only.
    terrain, terrain_source = load_terrain(
        bbox.south, bbox.north, bbox.west, bbox.east, prefer=terrain_prefer
    )
    land = land_mask(terrain, lats, lons)

    hours = [(t - storm.times[0]).total_seconds() / 3600 for t in storm.times]

    # Inland flooding from rainfall, which for a weak storm is the whole
    # story. Senyar and Ditwah were 75-85 km/h systems that did US$24bn of
    # damage almost entirely through rain. Water depth at an asset is the
    # deeper of surge and rain-driven ponding, so both pathways compete
    # rather than one silently winning.
    susceptibility = flood_susceptibility(
        terrain.elevation_m(lats, lons),
        np.abs(terrain.distance_to_coast_km(lats, lons)),
    )

    # Hazard, per ensemble member.
    members, provenance = _ensemble(storm, landfall_time, lead_hours, n_members,
                                    ensemble_source)
    n_members = len(members)
    wind_members: list[np.ndarray] = []
    surges: list[np.ndarray] = []
    parametric: list[np.ndarray] = []
    for member in members:
        wind_members.append(swath(member, lats, lons))
        lf = member[storm.landfall_index]
        surges.append(surge_field_m(lf, lats, lons, terrain, tide_m, ANDHRA_SHELF_FACTOR))
        parametric.append(accumulation_mm(member, hours, lats, lons))

    # Rainfall: the real GFS forecast where the archive reaches, spread across
    # the ensemble along each member's track; R-CLIPER otherwise. Either way
    # the run records which, because the two support different claims.
    rain_members, rain, rain_provenance = _rainfall(
        forecast_time, lats, lons, parametric, rain_source)

    depth_members = [
        np.maximum(surge, inland_flood_depth_m(r, susceptibility))
        for surge, r in zip(surges, rain_members, strict=True)
    ]

    # The post-event trigger index needs *observed* rain. IMERG replaces this
    # below when Earth Engine is reachable; otherwise the best track through
    # R-CLIPER stands in, and the trigger report says which it used.
    rain_index = accumulation_mm(storm.track, hours, lats, lons)

    grids = HazardGrids(lats, lons, wind_members, depth_members, rain, terrain=terrain)

    # Exposure and impact.
    assets = load_assets(bbox)
    risks = score_all(assets, grids)

    # Advisories, one per department, all pending approval.
    region = next((k for k, v in REGIONS.items() if v == bbox), "custom")
    # Named per region: this said "coastal Andhra Pradesh" for every run, so
    # Fani's Odisha advisories named the wrong state in their CAP area.
    place = REGION_NAMES.get(region, "the area of interest")
    area = f"{bbox.south}-{bbox.north}N, {bbox.west}-{bbox.east}E ({place})"
    advisories = [
        a for key in RECIPIENTS
        if (a := draft(key, risks, storm.name, lead_hours, area,
                       region=region, n_members=n_members,
                       forecast_time=forecast_time)) is not None
    ]
    # Gemini rewrites prose and translates where it can; every number it
    # returns is checked against the computed facts, and anything unverified
    # is dropped. Without a key this is a no-op that says so.
    drafting_ok, drafting_reason = gemini.availability()
    if use_gemini:
        advisories = gemini.enhance_all(advisories)
    # Sealed last, over the final text: an approval then covers exactly what
    # the officer read (see Advisory.sealed).
    advisories = [a.sealed() for a in advisories]
    drafted = sum(1 for a in advisories if a.drafted_by == gemini.MODEL)

    # What the satellites saw, where Earth Engine is available: observed rain
    # for the trigger index, and rain, flood and outage checks on the forecast.
    observed, observed_rain_index = _observe(
        storm, landfall_time, bbox, grids, land, risks, rain_members, parametric,
        rain_provenance, forecast_time)

    # Parametric triggers. The wind index is the official best track run
    # through the same wind model -- how cat-in-grid products compute payouts.
    # The rain index is observed rainfall (IMERG) when available.
    trigger_report = triggers.evaluate(
        region, lats, lons, wind_members, rain_members,
        wind_observed=swath(storm.track, lats, lons),
        rain_observed=observed_rain_index if observed_rain_index is not None else rain_index,
        risks=risks,
    )
    if observed_rain_index is not None:
        trigger_report["observed_rain_source"] = (
            "GPM IMERG observed rainfall, 48 h before to 24 h after landfall")

    # Verify what can honestly be verified, and say plainly what cannot.
    skill = verify_ensemble(
        storm, members, source=provenance["source"],
        from_time=datetime.fromisoformat(provenance["issued"])
        if provenance["source"] == "weatherlab" else None,
    )

    summary = {
        "storm": storm.name,
        "storm_id": storm.storm_id,
        "region": region,
        "peak_grade": storm.peak_grade,
        "peak_wind_kmh": round(storm.peak_vmax_ms * 3.6),
        "min_pressure_hpa": storm.min_pressure_hpa,
        "landfall_time": landfall_time.isoformat(),
        "forecast_time": forecast_time.isoformat(),
        "hours_to_landfall": lead_hours,
        "ensemble_members": n_members,
        "ensemble": provenance,
        "rainfall": rain_provenance,
        "assets_scored": len(risks),
        "by_class": by_class(risks),
        "people_without_power_est": population_affected(risks),
        "p_gust_over_90kmh_land_pct": round(
            float(exceedance(wind_members, 90 / 3.6)[land].mean()) * 100, 1
        ),
        "p_storm_tide_over_1m_land_pct": round(
            float(exceedance(depth_members, 1.0)[land].mean()) * 100, 1
        ),
        "terrain_source": terrain_source,
        "land_fraction_pct": round(float(land.mean()) * 100, 1),
        "max_rain_mm": round(float(rain[land].max())),
        "p_rain_over_200mm_land_pct": round(
            float(exceedance(rain_members, 200.0)[land].mean()) * 100, 1
        ),
        "driver_split": {
            d: sum(1 for r in risks if r.dominant_driver == d)
            for d in ("wind", "flood", "none")
        },
        "ranked_by": "expected consequence (probability x criticality)",
        "assets_shipped": min(len(risks), 400),
        "advisories_pending": len(advisories),
        "triggers": trigger_report,
        # What actually drafted the text, not what was available: a key that
        # hit its quota must not show the model's name over template prose.
        "drafting": {
            "engine": gemini.MODEL if drafted else "template",
            "drafted_by_model": drafted,
            "advisories": len(advisories),
            "available": drafting_ok,
            "reason": drafting_reason,
        },
        "verification": {
            "ensemble": skill.as_dict(),
            "vs_imd": compare_with_imd_skill(skill),
            "observations": availability(),
            "observed": observed,
        },
    }

    return RunResult(
        storm=storm,
        forecast_time=forecast_time,
        hours_to_landfall=lead_hours,
        grids=grids,
        land=land,
        risks=risks,
        advisories=advisories,
        summary=summary,
    )


def _ensemble(storm: Storm, landfall_time: datetime, lead_hours: float, n_members: int,
              source: str) -> tuple[list[list[TrackPoint]], dict[str, Any]]:
    """Real forecast members where the archive has them, perturbed otherwise.

    "auto" uses Weather Lab when the storm falls inside its coverage and the
    download succeeds. Anything else falls back to perturbing the best track,
    and the provenance record says which happened and why, because the two
    support very different claims: a real forecast can be scored for skill,
    a perturbed one only for honest spread.
    """
    fallback_reason = None
    if source in ("auto", "weatherlab"):
        issued = weatherlab.issue_time_for(landfall_time, lead_hours)
        if weatherlab.covered(issued):
            try:
                return weatherlab.members_for(storm, issued)
            except Exception as exc:  # noqa: BLE001 - network or matching failure
                reraise_bugs(exc)          # a bug is not a failed source
                fallback_reason = f"Weather Lab unavailable ({type(exc).__name__}: {exc})"
                if source == "weatherlab":
                    raise
        else:
            since = weatherlab.COVERAGE_START[weatherlab.DEFAULT_MODEL]
            fallback_reason = (f"{storm.name} predates the Weather Lab archive "
                               f"(coverage from {since:%Y})")

    members = perturb(storm, n_members=n_members, lead_hours=lead_hours)
    return members, {
        "source": "perturbed",
        "model": "best track + IMD published error",
        "issued": (landfall_time - timedelta(hours=lead_hours)).isoformat(),
        "members": len(members),
        "reason": fallback_reason or "requested",
        "cross_track_sigma_km": round(at_lead(LANDFALL_ERROR_KM, lead_hours), 1),
        "spread_basis": spread_basis(lead_hours),
    }


def _rainfall(forecast_time: datetime, lats: np.ndarray, lons: np.ndarray,
              parametric: list[np.ndarray], source: str
              ) -> tuple[list[np.ndarray], np.ndarray, dict[str, Any]]:
    """Member rain fields, the displayed rain field, and where they came from."""
    reason = None
    if source in ("auto", "gfs"):
        issued = gfs.issue_time_for(forecast_time)
        if gfs.covered(issued):
            try:
                field = gfs.on_grid(issued, lats, lons)
                start, end = gfs.window(issued)
                return gfs.member_fields(field, parametric), field, {
                    "source": "gfs",
                    "issued": issued.isoformat(),
                    "window": [start.isoformat(), end.isoformat()],
                    "attribution": gfs.ATTRIBUTION,
                }
            except Exception as exc:  # noqa: BLE001 - network or decode failure
                reraise_bugs(exc)          # a bug is not a failed source
                reason = f"GFS unavailable ({type(exc).__name__}: {exc})"
                if source == "gfs":
                    raise
        else:
            reason = f"predates the open GFS archive (from {gfs.COVERAGE_START:%Y})"
    mean = np.mean(np.stack(parametric), axis=0)
    return parametric, mean, {"source": "r-cliper", "reason": reason or "requested"}


REGION_NAMES = {
    "andhra": "coastal Andhra Pradesh",
    "odisha": "coastal Odisha",
    "vizag": "north coastal Andhra Pradesh",
}


def _observe(storm: Storm, landfall_time: datetime, bbox: BBox, grids: HazardGrids,
             land: np.ndarray, risks: list[AssetRisk], rain_members: list[np.ndarray],
             parametric: list[np.ndarray], rain_provenance: dict[str, Any], forecast_time: datetime,
             ) -> tuple[dict[str, Any], np.ndarray | None]:
    """Satellite observations and the forecast scored against them.

    Returns the verification record and the observed rain index for the
    triggers (None when unavailable). Each check fails on its own: a missing
    Sentinel-1 pass costs the flood check, not the rain check.
    """
    from ingest import earthengine
    from verify import observed_skill, satellite

    ok, why = earthengine.availability()
    if not ok:
        return {"available": False, "reason": why}, None

    lats, lons = grids.lats, grids.lons
    out: dict[str, Any] = {"available": True, "reason": why}
    rain_index = None

    try:
        if rain_provenance.get("source") == "gfs":
            start, end = (datetime.fromisoformat(t) for t in rain_provenance["window"])
        else:
            start, end = forecast_time, forecast_time + timedelta(hours=72)
        obs_rain, meta = satellite.observed_rain(start, end, lats, lons)
        forecast_mean = np.mean(np.stack(rain_members), axis=0)
        param_mean = np.mean(np.stack(parametric), axis=0)
        out["rain"] = dict(observed_skill.rain_skill(
            forecast_mean, param_mean, obs_rain, land, rain_provenance.get("source", "?")),
            provenance=meta)
        rain_index, _ = satellite.observed_rain(
            landfall_time - timedelta(hours=48), landfall_time + timedelta(hours=24), lats, lons)
    except Exception as exc:  # noqa: BLE001
        reraise_bugs(exc)          # a bug is not a failed source
        out["rain"] = {"error": f"{type(exc).__name__}: {exc}"}

    try:
        fraction, meta = satellite.flood_fraction(landfall_time, bbox, lats, lons)
        p_flood = exceedance(grids.depth_members, observed_skill.FLOOD_DEPTH_M)
        terrain = grids.terrain
        # Where the flooding sits needs terrain; without it the check still
        # scores, it just cannot say how far inland or how high.
        where = ((terrain.elevation_m(lats, lons), np.abs(terrain.distance_to_coast_km(lats, lons)))
                 if terrain is not None else (None, None))
        out["flood"] = dict(observed_skill.flood_skill(p_flood, fraction, land, *where),
                            provenance=meta)
    except Exception as exc:  # noqa: BLE001
        reraise_bugs(exc)          # a bug is not a failed source
        out["flood"] = {"error": f"{type(exc).__name__}: {exc}"}

    try:
        drop, meta = satellite.nightlight_drop(landfall_time, lats, lons)
        out["outage"] = dict(observed_skill.outage_skill(risks, drop, grids), provenance=meta)
    except Exception as exc:  # noqa: BLE001
        reraise_bugs(exc)          # a bug is not a failed source
        out["outage"] = {"error": f"{type(exc).__name__}: {exc}"}

    return out, rain_index


def export(
    result: RunResult, out_dir: Path = OUT_DIR, extra: dict[str, Any] | None = None
) -> Path:
    """Write the run to disk as JSON for the dashboard to serve.

    `extra` is merged into the payload -- the agent uses it to attach what
    changed since the previous forecast cycle.

    The file is written beside its final name and moved into place, so the
    console, which serves this directory while cycles run, sees the previous
    cycle or this one, never half of one.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{result.storm.name.lower()}_{int(result.hours_to_landfall)}h.json"
    staged = out_dir / f".{path.name}.{os.getpid()}.partial"
    try:
        staged.write_text(payload_json(result, extra))
        os.replace(staged, path)
    finally:
        staged.unlink(missing_ok=True)
    return path


def payload_json(result: RunResult, extra: dict[str, Any] | None = None) -> str:
    """The run as the JSON text the console reads."""
    # allow_nan=False: a stray NaN would write a literal the browser's JSON
    # parser rejects, blanking the console. Undefined values become null first.
    return json.dumps(json_safe(payload(result, extra)), allow_nan=False)


def payload(result: RunResult, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """The run as the console's payload, before it is serialised."""
    grids = result.grids

    payload: dict[str, Any] = {
        "summary": result.summary,
        "track": [
            {"lat": p.lat, "lon": p.lon, "vmax_ms": round(p.vmax_ms, 1),
             "pressure": p.pcen_hpa, "rmax_km": round(p.rmax_km),
             "time": t.isoformat(), "grade": g}
            for p, t, g in zip(result.storm.track, result.storm.times, result.storm.grades,
                                 strict=True)
        ],
        "landfall_index": result.storm.landfall_index,
        "grid": {
            "lat_min": float(grids.lats.min()), "lat_max": float(grids.lats.max()),
            "lon_min": float(grids.lons.min()), "lon_max": float(grids.lons.max()),
            "rows": int(grids.lats.shape[0]), "cols": int(grids.lats.shape[1]),
        },
        "layers": {
            "p_gust_90kmh": _downsample(exceedance(grids.wind_members, 90 / 3.6)),
            "p_tide_1m": _downsample(exceedance(grids.depth_members, 1.0)),
            "rain_mm": _downsample(grids.rain_mm),
        },
        # Land/sea at grid resolution, so the console can draw a recognisable
        # coast with no basemap and no network. Small -- a few KB -- and it is
        # what turns the offline fallback from an abstract grid into a map.
        "land_mask": _downsample(result.land.astype(float)),
        "assets": [r.to_dict() for r in result.risks[:400]],
        # Every red asset, not just the 400 shipped for the table: the agent
        # diffs cycles on this, and a strong storm can have far more than 400.
        "red_assets": [[r.asset.osm_id, r.asset.label] for r in result.risks
                       if r.severity == "red"],
        "advisories": [
            {
                "identifier": a.identifier,
                "recipient_key": a.recipient.key,
                "recipient": a.recipient.name,
                "lead_hours": list(a.recipient.lead_hours),
                "languages": a.languages,
                "pending_languages": a.pending_languages,
                "drafted_by": a.drafted_by,
                "draft_notes": a.draft_notes,
                "translations": a.translations,
                "headline": a.headline,
                "instruction": a.instruction,
                "ensemble_note": a.ensemble_note,
                "severity": a.severity,
                "approved": a.approved,
                "asset_count": len(a.assets),
                "cap_xml": a.to_cap_xml(),
            }
            for a in result.advisories
        ],
    }

    if extra:
        payload.update(extra)
    return payload


def json_safe(value: object) -> object:
    """Replace NaN and infinity with None, all the way down."""
    if isinstance(value, float):
        return value if np.isfinite(value) else None
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in cast(dict[object, object], value).items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in cast(list[object], value)]
    if isinstance(value, np.generic):
        item = cast(object, value.item())   # numpy types .item() loosely
        return json_safe(item)
    return value


def _downsample(field: np.ndarray, factor: int = 2) -> list[list[float]]:
    """Thin a grid for transport to the browser.

    Full resolution is far more than a map overlay needs and makes the payload
    slow to parse; the hazard model still runs at full resolution.
    """
    thin = field[::factor, ::factor]
    return [[round(float(v), 3) for v in row] for row in thin]

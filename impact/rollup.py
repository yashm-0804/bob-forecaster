"""Scoring every asset, and rolling the result up to a decision.

This is where the platform earns its claim: not a district shaded orange, but
"Nidadavolu Sub-station, 62% probability of failure, wind-driven, 41 hours to
landfall". Each asset is sampled from the ensemble hazard fields at its own
coordinates and scored through its own fragility curve.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from exposure.osm import Asset
from hazard.surge_screen import ElevationSource
from impact.consequence import Criticality, criticality, expected_consequence
from impact.fragility import FLOOD_CURVES, WIND_CURVES

#: How much extra water a local hollow may add, metres.
#:
#: Sub-grid terrain redistributes flooding within a cell; it does not invent
#: new water, and without a cap a valley floor 150 m below its cell's mean
#: gets 150 m of flood.
#:
#: This is the single most sensitive parameter in the impact model. Measured
#: on the Montha replay:
#:
#:   cap    red   max substation p   distinct values in top 400
#:   0.0      0   0.12                35
#:   0.3      0   0.51                69
#:   0.5      5   0.69                58
#:   1.0     67   0.92                26
#:
#: 0.3 m is chosen on two grounds. It is what a screening model can defend --
#: sub-grid relief across a 2.2 km delta cell is decimetres, not metres -- and
#: it also gives the sharpest ranking, because a larger cap saturates the
#: depth-damage curve and collapses everything back towards a single value.
#: Any figure derived from this should be read as sensitive to it.
MAX_LOCAL_DEEPENING = 0.3


@dataclass
class HazardGrids:
    """Ensemble hazard fields over a common grid.

    Wind and depth are per-member so asset scores carry a distribution, not a
    point estimate -- the advisory quotes a range because the forecast has one.
    """

    lats: np.ndarray
    lons: np.ndarray
    wind_members: list[np.ndarray]
    depth_members: list[np.ndarray]
    rain_mm: np.ndarray
    #: Terrain, used to refine flood depth below grid resolution. Optional so
    #: the grids still work with the flat placeholder or in tests.
    terrain: ElevationSource | None = None
    #: Mean ground height of each grid cell, cached on first use.
    _cell_elevation: np.ndarray | None = None

    def cell_of(self, lat: float, lon: float) -> tuple[int, int]:
        i = int(np.abs(self.lats[:, 0] - lat).argmin())
        j = int(np.abs(self.lons[0, :] - lon).argmin())
        return i, j

    def contains(self, lat: float, lon: float) -> bool:
        return (
            self.lats.min() <= lat <= self.lats.max()
            and self.lons.min() <= lon <= self.lons.max()
        )

    def elevation_offset_m(self, lat: float, lon: float) -> float:
        """How far this point sits above its grid cell's mean ground height.

        The hazard grid is 0.02 degrees, about 2.2 km. The terrain underneath
        it is 123 m. Without this correction every asset in a cell receives the
        cell's average flood depth, so a hospital on a 12 m rise and one on a
        3 m flat are scored identically -- which is most of why the ranking
        collapses into a handful of repeated values.

        Returns 0.0 when no terrain is available, leaving behaviour unchanged.
        """
        if self.terrain is None:
            return 0.0
        if self._cell_elevation is None:
            self._cell_elevation = self.terrain.elevation_m(self.lats, self.lons)

        i, j = self.cell_of(lat, lon)
        here = float(
            self.terrain.elevation_m(np.array([lat]), np.array([lon]))[0]
        )
        return here - float(self._cell_elevation[i, j])

    def refined_depth_m(self, cell_depth: float, rise: float) -> float:
        """Adjust a cell's flood depth for an asset's own ground height.

        Raising an asset above its cell's mean drains it, without limit: at
        enough height it simply does not flood.

        Lowering it is capped at MAX_LOCAL_DEEPENING. Where the terrain is
        hilly a 2.2 km cell can average over a 150 m range, and a naive
        subtraction then pours a hundred metres of water into any valley
        floor -- which is how this first went wrong, driving substation
        failure probabilities to 1.00 in a 93 km/h storm.

        A cell with no water stays dry. Sub-grid terrain redistributes
        flooding within a cell; it cannot create it.
        """
        if cell_depth <= 0.0:
            return 0.0
        effective = max(rise, -MAX_LOCAL_DEEPENING)
        return float(np.clip(cell_depth - effective, 0.0, cell_depth + MAX_LOCAL_DEEPENING))


@dataclass
class AssetRisk:
    """One asset's scored risk, with the evidence behind it."""

    asset: Asset
    p_failure_mean: float
    p_failure_p10: float
    p_failure_p90: float
    wind_ms_median: float
    depth_m_median: float
    rain_mm: float
    #: Which hazard contributes most -- decides which department is advised.
    dominant_driver: str
    member_probabilities: list[float] = field(default_factory=list[float])
    #: How much depends on this asset, and where that judgement came from.
    criticality: Criticality | None = None
    #: p_failure x criticality. What the table actually ranks on.
    consequence: float = 0.0
    #: Height of this asset above its grid cell's mean, metres.
    elevation_offset_m: float = 0.0

    @property
    def severity(self) -> str:
        """Banding on expected consequence, not bare probability.

        Ranking on probability alone put 336 hospitals within a few points of
        each other and gave an officer nothing to act on. Banding on
        consequence means a 30% chance of losing a 400 kV substation outranks
        a 70% chance of losing a small clinic -- which is the ordering someone
        with one crew and one night actually needs.

        Read the thresholds in typical-asset-equivalents. Consequence is a
        probability times a criticality weight where 1.0 is a typical asset of
        its class, so the bands say how much is expected to be lost:

          red     >= 1.00   a whole typical asset, expected lost. Act tonight.
          orange  >= 0.60   most of one. Prepare.
          yellow  >= 0.25   a meaningful fraction. Monitor.

        Calibrated on the Montha replay so red stays a list a district can
        actually work through in one night -- 0.8% of assets, 49 entries. An
        earlier calibration put 783 assets in red, which is the same flatness
        problem wearing a different colour.

        These bands move with MAX_LOCAL_DEEPENING; see the sensitivity table
        on that constant before reading anything into the counts.
        """
        c = self.consequence
        if c >= 1.00:
            return "red"
        if c >= 0.60:
            return "orange"
        if c >= 0.25:
            return "yellow"
        return "green"

    def to_dict(self) -> dict[str, Any]:
        return {
            "osm_id": self.asset.osm_id,
            "name": self.asset.label,
            "asset_class": self.asset.asset_class,
            "lat": self.asset.lat,
            "lon": self.asset.lon,
            "p_failure": round(self.p_failure_mean, 4),
            "p_failure_p10": round(self.p_failure_p10, 4),
            "p_failure_p90": round(self.p_failure_p90, 4),
            "wind_ms": round(self.wind_ms_median, 1),
            "wind_kmh": round(self.wind_ms_median * 3.6, 0),
            "depth_m": round(self.depth_m_median, 2),
            "rain_mm": round(self.rain_mm, 0),
            "driver": self.dominant_driver,
            "severity": self.severity,
            "consequence": round(self.consequence, 3),
            "criticality": round(self.criticality.score, 2) if self.criticality else 1.0,
            "criticality_basis": self.criticality.basis if self.criticality else "",
            "criticality_confidence": (
                self.criticality.confidence if self.criticality else "class-default"
            ),
            "elevation_offset_m": round(self.elevation_offset_m, 1),
        }


def score_asset(asset: Asset, grids: HazardGrids) -> AssetRisk | None:
    """Score one asset across every ensemble member."""
    if not grids.contains(asset.lat, asset.lon):
        return None
    i, j = grids.cell_of(asset.lat, asset.lon)

    wind_curve = WIND_CURVES.get(asset.asset_class)
    flood_curve = FLOOD_CURVES.get(asset.asset_class)

    # Water finds the low ground. An asset standing above its cell's mean
    # height sees correspondingly less depth, and one in a hollow sees more.
    rise = grids.elevation_offset_m(asset.lat, asset.lon)

    winds: list[float] = []
    depths: list[float] = []
    probs: list[float] = []
    for wind_field, depth_field in zip(grids.wind_members, grids.depth_members, strict=True):
        wind = float(wind_field[i, j])
        depth = grids.refined_depth_m(float(depth_field[i, j]), rise)
        winds.append(wind)
        depths.append(depth)

        pw = float(wind_curve.failure_probability(wind)) if wind_curve else 0.0
        pf = float(flood_curve.failure_probability(depth)) if flood_curve else 0.0
        probs.append(1.0 - (1.0 - pw) * (1.0 - pf))

    wind_median = float(np.median(winds))
    depth_median = float(np.median(depths))

    # Attribute to whichever hazard drives the probability, because that
    # decides who gets advised: wind failures go to the utility's tree-cutting
    # and crew staging, flood failures to drainage and pump readiness.
    pw = float(wind_curve.failure_probability(wind_median)) if wind_curve else 0.0
    pf = float(flood_curve.failure_probability(depth_median)) if flood_curve else 0.0
    if pw == pf == 0.0:
        driver = "none"
    else:
        driver = "wind" if pw >= pf else "flood"

    crit = criticality(asset)
    p_mean = float(np.mean(probs))

    return AssetRisk(
        asset=asset,
        p_failure_mean=p_mean,
        p_failure_p10=float(np.percentile(probs, 10)),
        p_failure_p90=float(np.percentile(probs, 90)),
        wind_ms_median=wind_median,
        depth_m_median=depth_median,
        rain_mm=float(grids.rain_mm[i, j]),
        dominant_driver=driver,
        member_probabilities=probs,
        criticality=crit,
        consequence=expected_consequence(p_mean, crit.score),
        elevation_offset_m=rise,
    )


def score_all(assets: list[Asset], grids: HazardGrids) -> list[AssetRisk]:
    """Score every asset, worst expected consequence first."""
    scored = [r for a in assets if (r := score_asset(a, grids)) is not None]
    return sorted(scored, key=lambda r: r.consequence, reverse=True)


def by_class(risks: list[AssetRisk]) -> dict[str, dict[str, Any]]:
    """Summary per asset class, for the dashboard's headline counters."""
    out: dict[str, dict[str, Any]] = {}
    for risk in risks:
        entry = out.setdefault(
            risk.asset.asset_class,
            {"total": 0, "red": 0, "orange": 0, "yellow": 0, "green": 0,
             "expected_failures": 0.0},
        )
        entry["total"] += 1
        entry[risk.severity] += 1
        # Summing probabilities gives the expected count of failures, which is
        # the number a utility can actually plan crews and spares against.
        entry["expected_failures"] += risk.p_failure_mean
    for entry in out.values():
        entry["expected_failures"] = round(entry["expected_failures"], 1)
    return out


def population_affected(
    risks: list[AssetRisk], people_per_typical_substation: int = 12_000
) -> int:
    """Rough headcount losing supply, weighted by substation size.

    Scaled by each substation's criticality, so a 400 kV node counts for far
    more than an unmapped local one -- which is closer to the truth than the
    flat per-substation figure it replaces, since transmission voltage really
    does track downstream load.

    The weights are **normalised to their own mean**, so criticality
    redistributes the headcount towards high-voltage nodes without changing
    its magnitude. Criticality is a relative measure -- 1.0 is a typical asset
    -- so multiplying an already-arbitrary per-substation figure by it would
    simply inflate the total. Skipping that normalisation took this estimate
    from 59,000 to 1,247,000 on the same storm with no new evidence, which is
    precisely the kind of unsupported precision this project exists to avoid.

    Still an estimate, and labelled as one everywhere it is shown. The real
    calculation needs GHSL population under each substation's service polygon,
    which we do not have.
    """
    subs = [r for r in risks if r.asset.asset_class == "substation"]
    if not subs:
        return 0

    weights = [r.criticality.score if r.criticality else 1.0 for r in subs]
    mean_weight = sum(weights) / len(weights)
    if mean_weight <= 0:
        mean_weight = 1.0

    return int(
        sum(
            r.p_failure_mean * people_per_typical_substation * (w / mean_weight)
            for r, w in zip(subs, weights, strict=True)
        )
    )

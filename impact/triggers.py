"""Parametric insurance: will a trigger fire, and will it fire for the right reason?

A parametric policy pays when a measured index crosses a pre-agreed
threshold, instead of waiting months for loss adjusters. That speed is the
point -- the brief's "parametric insurance liquidity" -- and the price is
basis risk: the index and the actual loss can disagree, in either direction.

Two numbers per zone, per peril:

  before landfall  the probability each payout tier is reached, across the
                   forecast ensemble. What a state finance department can
                   plan liquidity against.

  after landfall   whether the index actually fired, computed the way
                   cat-in-grid products compute it -- the official best track
                   run through a parametric wind model -- set against the
                   modelled damage in the same zone.

The zones and thresholds below are ILLUSTRATIVE. They are not real policies
and carry no monetary amounts, only a share of the sum insured. The tier
boundaries are anchored to published structures so they are not arbitrary:

  wind  partial at 118 km/h, full at 167 km/h -- IMD's Very Severe and
        Extremely Severe category boundaries
  rain  partial at 200 mm, full at 300 mm over the event -- the 300 mm over
        three days used in CDRI's 2026 Odisha parametric study
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from impact.rollup import AssetRisk

KMH_TO_MS = 1 / 3.6


@dataclass(frozen=True)
class Tier:
    threshold: float
    payout: float          # share of sum insured, 0-1


@dataclass(frozen=True)
class Peril:
    name: str              # "wind" | "rain"
    unit: str
    tiers: tuple[Tier, ...]

    def payout_for(self, index: float) -> float:
        """Highest tier the index reaches."""
        reached = [t.payout for t in self.tiers if index >= t.threshold]
        return max(reached, default=0.0)


WIND = Peril("wind", "km/h", (Tier(118.0, 0.5), Tier(167.0, 1.0)))
RAIN = Peril("rain", "mm", (Tier(200.0, 0.5), Tier(300.0, 1.0)))


@dataclass(frozen=True)
class Zone:
    """A circular policy zone around a district headquarters."""

    name: str
    lat: float
    lon: float
    radius_km: float = 50.0

    def mask(self, lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
        dy = (lats - self.lat) * 111.0
        dx = (lons - self.lon) * 111.0 * np.cos(np.radians(self.lat))
        return np.hypot(dx, dy) <= self.radius_km

    def contains(self, lat: float, lon: float) -> bool:
        dy = (lat - self.lat) * 111.0
        dx = (lon - self.lon) * 111.0 * math.cos(math.radians(self.lat))
        return math.hypot(dx, dy) <= self.radius_km


#: Illustrative zones, one per district headquarters in each region.
ZONES: dict[str, tuple[Zone, ...]] = {
    "andhra": (
        Zone("Kakinada", 16.95, 82.24),
        Zone("Amalapuram (Konaseema)", 16.58, 82.01),
        Zone("Narasapuram (West Godavari)", 16.43, 81.70),
        Zone("Machilipatnam (Krishna)", 16.17, 81.13),
    ),
    "odisha": (
        Zone("Puri", 19.81, 85.83),
        Zone("Bhubaneswar (Khordha)", 20.30, 85.82),
        Zone("Berhampur (Ganjam)", 19.31, 84.79),
    ),
    "vizag": (
        Zone("Visakhapatnam", 17.69, 83.22),
        Zone("Anakapalli", 17.69, 83.00),
    ),
}

#: How many red assets -- each "a whole typical asset expected lost" -- make a
#: zone count as having suffered material loss for basis-risk purposes.
#:
#: Counted in red assets rather than by summing consequence over the zone.
#: The sum is dominated by road segments, and OpenStreetMap splits roads into
#: fragments of arbitrary length, so it mostly measured how finely a road had
#: been mapped. A red asset means the same thing wherever it is.
MATERIAL_RED_ASSETS = 5


def _zone_index(field: np.ndarray, mask: np.ndarray, peril: Peril) -> float:
    """The index a policy would read: peak wind, or mean rain, over the zone."""
    if not mask.any():
        return 0.0
    values = field[mask]
    if peril is WIND:
        return float(values.max()) / KMH_TO_MS      # m/s -> km/h
    return float(values.mean())


def evaluate(
    region: str,
    lats: np.ndarray,
    lons: np.ndarray,
    wind_members: list[np.ndarray],
    rain_members: list[np.ndarray],
    wind_observed: np.ndarray,
    rain_observed: np.ndarray,
    risks: list[AssetRisk],
) -> dict[str, Any]:
    """Trigger probabilities before landfall, and outcome and basis risk after."""
    zones = ZONES.get(region, ())
    out: list[dict[str, Any]] = []
    for zone in zones:
        mask = zone.mask(lats, lons)
        loss = sum(r.consequence for r in risks if zone.contains(r.asset.lat, r.asset.lon))
        red = sum(1 for r in risks if r.severity == "red"
                  and zone.contains(r.asset.lat, r.asset.lon))

        perils: list[dict[str, Any]] = []
        for peril, members, observed in ((WIND, wind_members, wind_observed),
                                         (RAIN, rain_members, rain_observed)):
            indices = [_zone_index(f, mask, peril) for f in members]
            payouts = [peril.payout_for(i) for i in indices]
            observed_index = _zone_index(observed, mask, peril)
            perils.append({
                "peril": peril.name,
                "unit": peril.unit,
                "tiers": [{"threshold": t.threshold, "payout": t.payout} for t in peril.tiers],
                "p_partial_or_more": round(float(np.mean([p > 0 for p in payouts])), 3),
                "p_full": round(float(np.mean([p >= 1.0 for p in payouts])), 3),
                "expected_payout": round(float(np.mean(payouts)), 3),
                "index_p10": round(float(np.percentile(indices, 10)), 1),
                "index_p90": round(float(np.percentile(indices, 90)), 1),
                "observed_index": round(observed_index, 1),
                "observed_payout": peril.payout_for(observed_index),
            })

        paid = max(float(p["observed_payout"]) for p in perils)
        material = red >= MATERIAL_RED_ASSETS
        if paid > 0 and not material:
            basis = "payout without modelled loss"
        elif paid == 0 and material:
            basis = "loss without payout"
        else:
            basis = "aligned"

        out.append({
            "zone": zone.name,
            "lat": zone.lat, "lon": zone.lon, "radius_km": zone.radius_km,
            "perils": perils,
            # Reported, not used for basis risk -- see MATERIAL_RED_ASSETS.
            "modelled_loss": round(loss, 2),
            "red_assets": red,
            "observed_payout": paid,
            "basis_risk": basis,
        })

    return {
        "illustrative": True,
        "note": ("Illustrative zones and thresholds, not real policies. Tiers are "
                 "anchored to IMD category boundaries (wind) and the 300 mm / 3-day "
                 "trigger in CDRI's Odisha study (rain). Payouts are shares of sum "
                 "insured; no monetary amounts are modelled."),
        "material_loss_rule": f"at least {MATERIAL_RED_ASSETS} red assets in the zone",
        "observed_rain_source": ("best track through R-CLIPER -- observed rainfall "
                                 "(GPM IMERG) needs Earth Engine or an Earthdata login"),
        "zones": out,
    }

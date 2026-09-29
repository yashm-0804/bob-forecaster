"""Predictions scored against what the satellites saw.

Three comparisons, each over land only (scoring sea cells would flood the
tables with easy correct negatives) and each reported with its sample size,
because a skill score from twelve cells is not the same claim as one from a
thousand:

  rain     the rainfall forecast the run used -- and R-CLIPER alongside it --
           against GPM IMERG over the same window. The second column exists
           to test, rather than assume, that moving to GFS was an improvement.
  flood    the ensemble probability of standing water against Sentinel-1
           flood extent: contingency scores and a Brier score.
  outage   predicted substation failure against the night-light drop in the
           substation's own cell.

Nothing here is tuned to make the numbers look good. Where the model does
badly, the table says so.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from impact.rollup import AssetRisk, HazardGrids

from verify.metrics import Contingency, brier_score, brier_skill_score, contingency

#: Rain at which a cell counts as heavily rained on, mm over the window.
RAIN_EVENT_MM = 100.0
#: Modelled water depth that counts as a flooded cell, m.
FLOOD_DEPTH_M = 0.2
#: Share of a cell Sentinel-1 must see newly flooded to count it as flooded.
FLOOD_FRACTION = 0.05
#: Substation failure probability treated as a predicted outage.
OUTAGE_P = 0.3
#: Night-light drop treated as an observed outage.
OUTAGE_DROP = 0.5


def _stats(forecast: np.ndarray, observed: np.ndarray) -> dict[str, Any]:
    ok = np.isfinite(forecast) & np.isfinite(observed)
    f, o = forecast[ok], observed[ok]
    if f.size < 3:
        return {"cells": int(f.size)}
    c = contingency(f, o, RAIN_EVENT_MM)
    return {
        "cells": int(f.size),
        "mean_forecast_mm": round(float(f.mean()), 1),
        "mean_observed_mm": round(float(o.mean()), 1),
        "bias_ratio": round(float(f.mean() / o.mean()), 2) if o.mean() > 0 else None,
        "correlation": round(float(np.corrcoef(f, o)[0, 1]), 2) if f.std() and o.std() else None,
        "rmse_mm": round(float(np.sqrt(np.mean((f - o) ** 2))), 1),
        f"over_{int(RAIN_EVENT_MM)}mm": c.as_dict(),
    }


def rain_skill(forecast_mm: np.ndarray, parametric_mm: np.ndarray, observed_mm: np.ndarray,
               land: np.ndarray, forecast_label: str) -> dict[str, Any]:
    """The run's rain forecast and R-CLIPER, both against IMERG, over land."""
    out = {"threshold_mm": RAIN_EVENT_MM,
           "forecast": dict(_stats(forecast_mm[land], observed_mm[land]), label=forecast_label)}
    if forecast_label != "r-cliper":
        out["r_cliper"] = dict(_stats(parametric_mm[land], observed_mm[land]), label="r-cliper")
    return out


def _where(mask: np.ndarray, elevation_m: np.ndarray,
           coast_km: np.ndarray) -> dict[str, Any] | None:
    """Median ground height and distance from the sea of a set of cells."""
    if not mask.any():
        return None
    return {"cells": int(mask.sum()),
            "median_elevation_m": round(float(np.median(elevation_m[mask])), 1),
            "median_km_from_coast": round(float(np.median(coast_km[mask])), 1)}


def flood_skill(p_flooded: np.ndarray, observed_fraction: np.ndarray, land: np.ndarray,
                elevation_m: np.ndarray | None = None,
                coast_km: np.ndarray | None = None) -> dict[str, Any]:
    """Ensemble flood probability against Sentinel-1 flood extent.

    With terrain supplied, it also says *where* the observed and predicted
    flooding sit -- height and distance inland. A miss is only useful if it
    says what kind of miss it was: water where the model's pathways cannot
    reach is a different fix from water in the right place at the wrong depth.
    """
    observed = (observed_fraction >= FLOOD_FRACTION).astype(float)
    p = p_flooded[land]
    o = observed[land]
    c = contingency(np.where(land, p_flooded, 0.0), np.where(land, observed, 0.0), 0.5, mask=land)
    out = {
        "cells": int(land.sum()),
        "observed_flooded_cells": int(o.sum()),
        "predicted_flooded_cells": int((p >= 0.5).sum()),
        "contingency_at_p50": c.as_dict(),
        "brier": round(brier_score(p, o), 4),
        "brier_skill_vs_climatology": (round(brier_skill_score(p, o), 3)
                                       if 0 < o.mean() < 1 else None),
        "rule": (f"predicted: ensemble P(depth > {FLOOD_DEPTH_M} m) >= 0.5; observed: "
                 f">= {int(FLOOD_FRACTION * 100)}% of the cell newly flooded"),
    }
    if elevation_m is not None and coast_km is not None:
        out["where"] = {
            "observed_flooded": _where(land & (observed > 0), elevation_m, coast_km),
            "predicted_flooded": _where(land & (p_flooded >= 0.5), elevation_m, coast_km),
            "all_land": _where(land, elevation_m, coast_km),
        }
    return out


def outage_skill(risks: Sequence[AssetRisk], drop: np.ndarray,
                 grids: HazardGrids) -> dict[str, Any]:
    """Predicted substation failure against the light drop in its cell."""
    pairs: list[tuple[float, float, str]] = []
    for r in risks:
        if r.asset.asset_class != "substation":
            continue
        i, j = grids.cell_of(r.asset.lat, r.asset.lon)
        d = drop[i, j]
        if np.isfinite(d):
            pairs.append((r.p_failure_mean, float(d), r.asset.label))
    if len(pairs) < 3:
        return {"substations_with_lights": len(pairs),
                "note": "too few lit substations with a clear post-storm night to score"}

    p = np.array([x[0] for x in pairs])
    d = np.array([x[1] for x in pairs])
    # Prediction and observation use different thresholds, so the table is
    # built directly rather than through contingency(), which takes one.
    hits = int(((p >= OUTAGE_P) & (d >= OUTAGE_DROP)).sum())
    false_alarms = int(((p >= OUTAGE_P) & (d < OUTAGE_DROP)).sum())
    misses = int(((p < OUTAGE_P) & (d >= OUTAGE_DROP)).sum())
    correct_neg = int(((p < OUTAGE_P) & (d < OUTAGE_DROP)).sum())
    c = Contingency(hits, false_alarms, misses, correct_neg)

    order = np.argsort(np.argsort(p)), np.argsort(np.argsort(d))
    spearman = float(np.corrcoef(order[0], order[1])[0, 1]) if len(pairs) > 2 else None
    high = d[p >= np.quantile(p, 0.75)]
    rest = d[p < np.quantile(p, 0.75)]
    return {
        "substations_with_lights": len(pairs),
        "observed_outages": int((d >= OUTAGE_DROP).sum()),
        "contingency": c.as_dict(),
        "rank_correlation": round(spearman, 2) if spearman is not None else None,
        "mean_drop_top_quarter_predicted": round(float(high.mean()), 2) if high.size else None,
        "mean_drop_rest": round(float(rest.mean()), 2) if rest.size else None,
        "rule": (f"predicted: substation P(failure) >= {OUTAGE_P}; observed: night-time "
                 f"radiance down >= {int(OUTAGE_DROP * 100)}% in its cell"),
    }

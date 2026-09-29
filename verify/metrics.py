"""Forecast verification metrics.

Standard contingency-table scores from operational meteorology. They exist
here rather than as ad-hoc comparisons because the interesting question is
never "did we get it right" but "right in which direction, and how often".

A model that flags everything scores a perfect hit rate and is useless. A
model that flags nothing has no false alarms and is equally useless. Every
score below is reported with its counterpart for that reason.

References: Jolliffe & Stephenson, *Forecast Verification*; WMO guidance on
deterministic and probabilistic verification.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass(frozen=True)
class Contingency:
    """The 2x2 table every deterministic score is built from."""

    hits: int              # forecast yes, observed yes
    false_alarms: int      # forecast yes, observed no
    misses: int            # forecast no,  observed yes
    correct_negatives: int # forecast no,  observed no

    @property
    def total(self) -> int:
        return self.hits + self.false_alarms + self.misses + self.correct_negatives

    @property
    def probability_of_detection(self) -> float:
        """Fraction of observed events that were forecast. Perfect = 1.

        Also called the hit rate. On its own it rewards over-forecasting, so
        never read it without the false alarm ratio.
        """
        denom = self.hits + self.misses
        return self.hits / denom if denom else float("nan")

    @property
    def false_alarm_ratio(self) -> float:
        """Fraction of forecast events that did not happen. Perfect = 0.

        The number that decides whether anyone keeps answering your alerts.
        """
        denom = self.hits + self.false_alarms
        return self.false_alarms / denom if denom else float("nan")

    @property
    def critical_success_index(self) -> float:
        """Hits over everything either forecast or observed. Perfect = 1.

        Ignores correct negatives, which is what makes it useful for rare
        events: in a cyclone footprint most of the map is correctly quiet, and
        a score that counts those looks excellent no matter what you do.
        """
        denom = self.hits + self.false_alarms + self.misses
        return self.hits / denom if denom else float("nan")

    @property
    def bias(self) -> float:
        """Forecast events over observed events. 1 = right frequency.

        Above 1 is over-forecasting, below 1 under-forecasting. Says nothing
        about whether the right places were picked.
        """
        denom = self.hits + self.misses
        return (self.hits + self.false_alarms) / denom if denom else float("nan")

    def as_dict(self) -> dict[str, Any]:
        """The table and its scores. A score with no defined value -- POD
        when nothing was observed, say -- is None, not NaN: NaN is not valid
        JSON, and "undefined" is the honest reading anyway."""

        def score(x: float) -> float | None:
            return round(x, 3) if x == x else None

        return {
            "hits": self.hits,
            "false_alarms": self.false_alarms,
            "misses": self.misses,
            "correct_negatives": self.correct_negatives,
            "pod": score(self.probability_of_detection),
            "far": score(self.false_alarm_ratio),
            "csi": score(self.critical_success_index),
            "bias": score(self.bias),
        }


def contingency(
    forecast: np.ndarray,
    observed: np.ndarray,
    threshold: float,
    mask: np.ndarray | None = None,
) -> Contingency:
    """Build the table by thresholding both fields into yes/no.

    `mask` restricts the comparison, which matters: scoring over sea cells
    inflates correct negatives and makes everything look excellent.
    """
    if forecast.shape != observed.shape:
        raise ValueError(
            f"forecast {forecast.shape} and observed {observed.shape} must match"
        )

    f = forecast >= threshold
    o = observed >= threshold
    if mask is not None:
        f, o = f & mask, o & mask
        valid = mask
    else:
        valid = np.ones_like(f, dtype=bool)

    return Contingency(
        hits=int((f & o).sum()),
        false_alarms=int((f & ~o & valid).sum()),
        misses=int((~f & o & valid).sum()),
        correct_negatives=int((~f & ~o & valid).sum()),
    )


def brier_score(probabilities: np.ndarray, observed: np.ndarray) -> float:
    """Mean squared error of probabilistic forecasts. Perfect = 0.

    The right score for an ensemble, because it penalises confident wrong
    answers far more than hedged ones -- which is the behaviour you want from
    a system feeding evacuation decisions.
    """
    p = np.asarray(probabilities, dtype=float)
    o = np.asarray(observed, dtype=float)
    if p.shape != o.shape:
        raise ValueError("probability and observation fields must match")
    return float(np.mean((p - o) ** 2))


def brier_skill_score(
    probabilities: np.ndarray, observed: np.ndarray, reference: float | None = None
) -> float:
    """Brier score against a reference forecast. Positive = better than it.

    The reference defaults to climatology -- always forecasting the observed
    base rate. Beating that is the minimum bar for a model to be worth
    running, and plenty of impressive-looking systems do not clear it.
    """
    o = np.asarray(observed, dtype=float)
    base = float(np.mean(o)) if reference is None else reference
    bs = brier_score(probabilities, o)
    bs_ref = brier_score(np.full_like(o, base), o)
    return float(1.0 - bs / bs_ref) if bs_ref > 0 else float("nan")


def reliability_bins(
    probabilities: np.ndarray, observed: np.ndarray, n_bins: int = 10
) -> list[dict[str, Any]]:
    """Forecast probability against observed frequency, binned.

    A well-calibrated model that says 70% is right about 70% of the time.
    This is what exposes the common failure of a confident model that is
    confidently wrong.
    """
    p = np.asarray(probabilities, dtype=float).ravel()
    o = np.asarray(observed, dtype=float).ravel()
    edges = np.linspace(0.0, 1.0, n_bins + 1)

    out: list[dict[str, Any]] = []
    for lo, hi in zip(edges[:-1], edges[1:], strict=True):
        sel = (p >= lo) & (p < hi if hi < 1.0 else p <= hi)
        n = int(sel.sum())
        out.append({
            "bin_lo": round(float(lo), 2),
            "bin_hi": round(float(hi), 2),
            "n": n,
            "mean_forecast": round(float(p[sel].mean()), 3) if n else None,
            "observed_frequency": round(float(o[sel].mean()), 3) if n else None,
        })
    return out

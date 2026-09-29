"""Fragility curves: hazard intensity to probability of asset failure.

The chain is hazard -> exposure -> vulnerability -> impact, and this is the
vulnerability link. Errors here dominate the final numbers, and curves
imported wholesale are known to mislead: Eberenz et al. (2021) found
US-calibrated curves biased simulated damage by up to 36x when applied to the
north-west Pacific.

The curves below are first-pass fits. They are compared with recorded damage
from two Bay of Bengal storms (`calibration_report`), not fitted to it; the
fit against held-out storms is planned in docs/MODEL_SKILL.md.

Reference damage:
  Fani 2019   ~156,000 distribution poles down, 3.5m households cut, ESCS
  Hudhud 2014  27,041 poles down, 70% of comms lost, 185 km/h at Visakhapatnam
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

#: Emanuel's threshold: no wind damage below this. 25.7 m/s = 92 km/h.
V_THRESH_MS = 25.7


@dataclass(frozen=True)
class WindFragility:
    """Emanuel sigmoid, as used in CLIMADA.

        f = v^3 / (1 + v^3),  v = max(V - V_thresh, 0) / (V_half - V_thresh)

    `v_half_ms` is the wind at which the asset class reaches 50% damage, and
    is the parameter that must be fitted regionally.
    """

    asset_class: str
    v_half_ms: float
    note: str = ""

    def __post_init__(self) -> None:
        if self.v_half_ms <= V_THRESH_MS:
            raise ValueError("v_half must exceed the damage threshold")

    def failure_probability(self, wind_ms: np.ndarray | float) -> np.ndarray:
        wind = np.asarray(wind_ms, dtype=float)
        v = np.maximum(wind - V_THRESH_MS, 0.0) / (self.v_half_ms - V_THRESH_MS)
        return v**3 / (1.0 + v**3)


@dataclass(frozen=True)
class FloodFragility:
    """Depth-damage curve.

    Piecewise-linear in water depth, which is the standard form for flood and
    is adequate given that the surge layer is a screen rather than a coupled
    model. Reporting a smooth analytic curve on top of screening-grade depths
    would imply precision that isn't there.
    """

    asset_class: str
    depth_m: tuple[float, ...]
    damage: tuple[float, ...]
    note: str = ""

    def failure_probability(self, depth_m: np.ndarray | float) -> np.ndarray:
        return np.interp(
            np.asarray(depth_m, dtype=float), self.depth_m, self.damage, left=0.0
        )


#: Wind curves by asset class. v_half values are first-pass fits to be
#: refined against the Fani and Hudhud pole counts -- see calibration_report().
#: "lv_pole" and "transmission_tower" are used by that report only: they are
#: not asset classes the exposure layer loads.
WIND_CURVES: dict[str, WindFragility] = {
    "lv_pole": WindFragility(
        "lv_pole", 42.0,
        "11 kV / LT concrete and wooden poles. The dominant failure mode: Fani "
        "took ~156,000 and most outage duration traces to these, not towers.",
    ),
    "transmission_tower": WindFragility(
        "transmission_tower", 62.0,
        "Steel lattice, designed to IS 802. Survives far more than distribution, "
        "but each failure cuts a much larger area.",
    ),
    "substation": WindFragility(
        "substation", 55.0,
        "Wind damage is to bushings, gantries and control buildings; the larger "
        "risk to a coastal substation is flooding.",
    ),
    # Keyed by the asset class it scores. It was once keyed
    # "road_tree_blockage", which no asset carries, so every road silently
    # scored zero from wind (tests/test_fragility_coverage.py now guards this).
    "road_segment": WindFragility(
        "road_segment", 33.0,
        "Blockage by falling trees, not pavement failure. Low threshold -- "
        "Hudhud destroyed ~70% of Visakhapatnam's tree canopy and blocked "
        "6,075 km of road.",
    ),
    "hospital": WindFragility(
        "hospital", 58.0,
        "Roofing, glazing and rooftop plant. Fani took the roof off Bhubaneswar "
        "air-traffic control, so institutional roofs are not immune.",
    ),
    "shelter": WindFragility(
        "shelter", 72.0,
        "Purpose-built multipurpose cyclone shelters, engineered for this load. "
        "Odisha ran 879 of them through Fani.",
    ),
    "telecom_tower": WindFragility(
        "telecom_tower", 52.0,
        "Tower plus backhaul. Hudhud took out 70% of local communications.",
    ),
}

#: Depth-damage curves. Substations are the sharp one: switchgear flooding is
#: close to a step function once water reaches equipment level.
FLOOD_CURVES: dict[str, FloodFragility] = {
    "substation": FloodFragility(
        "substation", (0.0, 0.3, 0.6, 1.0, 2.0), (0.0, 0.15, 0.6, 0.9, 1.0),
        "Ground-level switchgear and control rooms. Near-total loss of function "
        "once water passes ~1 m.",
    ),
    "road_segment": FloodFragility(
        "road_segment", (0.0, 0.3, 0.5, 1.0, 2.0), (0.0, 0.2, 0.5, 0.85, 1.0),
        "Impassability rather than destruction: ~0.3 m stops most vehicles and "
        "0.5 m stops relief trucks.",
    ),
    "hospital": FloodFragility(
        "hospital", (0.0, 0.2, 0.5, 1.0, 2.0), (0.0, 0.25, 0.6, 0.9, 1.0),
        "Ground-floor wards, generators and oxygen plant are usually at grade.",
    ),
    "shelter": FloodFragility(
        "shelter", (0.0, 0.5, 1.5, 3.0), (0.0, 0.05, 0.3, 0.8),
        "Raised plinths by design -- the reason they work as surge refuges.",
    ),
    "lv_pole": FloodFragility(
        "lv_pole", (0.0, 1.0, 2.0, 4.0), (0.0, 0.05, 0.2, 0.6),
        "Poles mostly survive water; the damage is delay, as crews cannot reach "
        "them. Rural Odisha waited ~2 months after Fani.",
    ),
}


#: Classes scored on wind alone, and why. Everything else the exposure layer
#: loads must have both curves.
WIND_ONLY = {
    "telecom_tower": "masts fail by wind; no depth-damage data for their "
                     "equipment shelters, so flooding is not scored rather than guessed",
}

#: Curves kept for calibration_report(), not for scoring loaded assets.
CALIBRATION_ONLY = {"lv_pole", "transmission_tower"}


def combined_failure(
    asset_class: str, wind_ms: float, depth_m: float = 0.0
) -> float:
    """Probability an asset fails from wind or flood.

    Combined as independent competing causes: P = 1 - (1-Pw)(1-Pf). They are
    not strictly independent -- the same storm drives both -- but treating
    them as such is standard and avoids double-counting the overlap.
    """
    wind_curve = WIND_CURVES.get(asset_class)
    flood_curve = FLOOD_CURVES.get(asset_class)
    pw = float(wind_curve.failure_probability(wind_ms)) if wind_curve else 0.0
    pf = float(flood_curve.failure_probability(depth_m)) if flood_curve else 0.0
    return 1.0 - (1.0 - pw) * (1.0 - pf)


def calibration_report() -> str:
    """Predicted damage ratio at the peak winds of two calibration storms.

    Printed rather than asserted: these are first-pass fits, and the honest
    statement for the pitch is what the curves currently imply, not a claim
    that they reproduce the recorded counts.
    """
    lines = ["asset_class          Hudhud 51 m/s   Fani 69 m/s"]
    for name, curve in WIND_CURVES.items():
        h = float(curve.failure_probability(51.4))
        f = float(curve.failure_probability(69.4))
        lines.append(f"{name:<20} {h:>11.3f} {f:>13.3f}")
    return "\n".join(lines)

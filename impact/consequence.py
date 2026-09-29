"""How much depends on an asset, and what it would cost to lose it.

Probability of failure alone does not answer the question an officer actually
has at 48 hours out, which is "where do I send the one crew I have tonight".
Two hospitals at the same hazard are not the same decision if one is a
district referral centre and the other is a six-bed nursing home.

Everything here is derived from attributes that are really present in
OpenStreetMap, and every weight carries its basis and a confidence level that
travels through to the UI. Where the data does not support a judgement, the
asset gets the class default and says so. Nothing is invented to make a
ranking look more decisive than the evidence allows.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from exposure.osm import Asset


@dataclass(frozen=True)
class Criticality:
    """A relative weight on how much is lost if this asset fails.

    `score` is ordinal, not a headcount: 1.0 is a typical asset of its class,
    3.0 means roughly three times as consequential. It is deliberately not
    expressed in people, because for most classes the data cannot support that
    and a fabricated headcount would be worse than an honest ordering.
    """

    score: float
    basis: str
    confidence: str          # measured | inferred | class-default


#: Transmission voltage is the one hard criticality signal OSM carries for
#: power infrastructure, and it is physically meaningful: a 400 kV substation
#: sits further up the network than a 132 kV one and carries a correspondingly
#: larger downstream load. Present on 79 of 146 substations in this AOI.
_VOLTAGE_WEIGHTS = (
    (400_000, 6.0),
    (220_000, 4.0),
    (132_000, 2.5),
    (66_000, 1.5),
    (33_000, 1.0),
)

#: Name patterns that indicate a large public facility. Crude, and labelled as
#: inferred wherever it fires -- but "Government General Hospital" really does
#: mean something different from "Renuka Nursing Home", and ignoring that
#: signal leaves 336 hospitals ranked identically.
_LARGE_HOSPITAL = re.compile(
    r"\b(government|govt|general|district|area|civil|medical college|"
    r"teaching|referral)\b", re.I
)
_SMALL_HOSPITAL = re.compile(
    r"\b(nursing home|clinic|dental|eye|skin|ent|polyclinic|dispensary|"
    r"physio|ayurved|homoeo|homeo|medical shop|medical store|pharmac|"
    r"diagnost|scan centre|scan center|laborator)\b", re.I
)

#: Fallback weight when nothing in the tags distinguishes one asset from
#: another of its class.
_CLASS_DEFAULT = {
    "substation": 1.5,
    "hospital": 1.0,
    "shelter": 2.0,
    "road_segment": 1.0,
    "telecom_tower": 1.2,
    "transmission_tower": 2.0,
    "lv_pole": 0.3,
}


def _max_voltage(tag: str) -> int | None:
    """Highest voltage in an OSM voltage tag.

    The tag is often multi-valued, e.g. "220000;132000" for a substation that
    steps between levels. The highest is what determines its position in the
    network.
    """
    levels = [int(v) for v in re.findall(r"\d+", tag or "")]
    return max(levels) if levels else None


def _substation(tags: dict[str, Any], default: float) -> Criticality:
    volts = _max_voltage(tags.get("voltage", ""))
    if not volts:
        return Criticality(default, "voltage not mapped", "class-default")
    weight = next((w for threshold, w in _VOLTAGE_WEIGHTS if volts >= threshold), 1.0)
    return Criticality(weight, f"{volts // 1000} kV substation", "measured")


def _hospital(tags: dict[str, Any], default: float) -> Criticality:
    name = tags.get("name", "")
    small = _SMALL_HOSPITAL.search(name)
    if tags.get("emergency") == "yes":
        # The name vetoes the tag when the two disagree. OSM's
        # `emergency=yes` is applied loosely: in this area it sits on a
        # dental hospital and on "Koteswara rao medical shop", which then
        # ranked third overall. A shop is not an emergency referral facility
        # however it is tagged, and an artifact at the top of the list costs
        # more credibility than one buried in it.
        if small:
            return Criticality(
                0.8, "tagged emergency, but the name indicates a small facility", "inferred")
        return Criticality(3.0, "tagged emergency capability", "measured")
    if _LARGE_HOSPITAL.search(name):
        return Criticality(2.5, "name indicates a public referral facility", "inferred")
    if small:
        return Criticality(0.6, "name indicates a small or specialist clinic", "inferred")
    return Criticality(default, "no capacity signal in tags", "class-default")


def _road(tags: dict[str, Any], default: float) -> Criticality:
    highway = tags.get("highway")
    if highway == "trunk":
        return Criticality(2.0, "trunk road", "measured")
    if highway == "primary":
        return Criticality(1.0, "primary road", "measured")
    return Criticality(default, "road class not mapped", "class-default")


def _shelter(tags: dict[str, Any], default: float) -> Criticality:
    # Capacity is not in OSM. Shelters are weighted above a typical asset
    # regardless, because losing one during an evacuation removes the
    # destination people are being sent to.
    return Criticality(default, "evacuation destination", "assumed")


_BY_CLASS = {"substation": _substation, "hospital": _hospital,
             "road_segment": _road, "shelter": _shelter}


def criticality(asset: Asset) -> Criticality:
    """Weight one asset by how much depends on it."""
    default = _CLASS_DEFAULT.get(asset.asset_class, 1.0)
    rule = _BY_CLASS.get(asset.asset_class)
    if rule is None:
        return Criticality(default, "class default", "class-default")
    return rule(asset.tags, default)


def expected_consequence(p_failure: float, weight: float) -> float:
    """Expected loss: probability of failing times how much that costs.

    This is what the asset table ranks on. A 30% chance of losing a 400 kV
    substation outranks a 70% chance of losing a small clinic, which is the
    ordering an officer with one crew actually needs.
    """
    return p_failure * weight

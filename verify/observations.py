"""Which post-landfall observations this run can check against, and why not.

The verification loop this project claims -- predict, then check against what
actually happened, and report the misses -- needs observed fields: rainfall,
night lights for power outages, radar backscatter for flood extent. All
three come through Earth Engine (see `verify/satellite.py`), so all three
are available exactly when Earth Engine is.

The rule this module exists to enforce: **an unavailable observation produces
a reason, never a number.** A run on a machine that is not signed in, or with
EARTHENGINE_OFF set, says so in its output instead of skipping the step
quietly or, worse, filling it with something plausible. A fabricated
verification is worse than none, because it manufactures exactly the
confidence the whole design is meant to withhold.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ObservationSource:
    """What a source is and what it is used to check."""

    key: str
    name: str
    measures: str
    dataset: str
    requires: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "measures": self.measures,
            "dataset": self.dataset,
            "requires": self.requires,
        }


SOURCES: dict[str, ObservationSource] = {
    "rain": ObservationSource(
        key="rain",
        name="GPM IMERG",
        measures="rainfall that fell, to score the rain forecast and set the trigger index",
        dataset="NASA/GPM_L3/IMERG_V07",
        requires="Earth Engine",
    ),
    "nightlights": ObservationSource(
        key="nightlights",
        name="VIIRS Black Marble",
        measures="power outage extent, from the drop in night-time radiance",
        dataset="NASA/VIIRS/002/VNP46A2",
        requires="Earth Engine",
    ),
    "flood_sar": ObservationSource(
        key="flood_sar",
        name="Sentinel-1 SAR",
        measures="flood extent, through cloud",
        dataset="COPERNICUS/S1_GRD",
        requires="Earth Engine",
    ),
}


def availability() -> dict[str, Any]:
    """What can and cannot be verified right now, and why.

    The Earth Engine state is checked live, so the reason names the actual
    blocker -- not signed in, project not registered, switched off -- rather
    than a sentence written when the code was.
    """
    from ingest import earthengine

    signed_in, why = earthengine.availability()
    reason = why[0].upper() + why[1:]
    sources = [dict(s.as_dict(), available=signed_in, reason=reason)
               for s in SOURCES.values()]
    return {
        "sources": sources,
        "any_available": signed_in,
        "note": (
            "Each check reports its own result or its own failure: a missing "
            "Sentinel-1 pass costs the flood check, not the rain check."
            if signed_in else
            "No observation is reachable on this run, so nothing is scored "
            "against one. No substitute figure is produced."
        ),
    }

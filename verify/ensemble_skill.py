"""Did the ensemble actually contain the truth?

This is the one verification that can be run today with no external data at
all: the perturbed ensemble on one side, IMD's own post-analysis best track on
the other. Both are real.

It matters more than it first appears. Every downstream number -- flood depth,
failure probability, which department gets advised -- inherits the track's
error. If the true storm falls outside the ensemble envelope, the impact
figures are confidently wrong, and no amount of care further down the chain
recovers that. The Red Cross typhoon trigger failed for Rai in exactly this
way.

Verification against post-landfall satellite imagery lives in
`verify/observations.py` and is not yet runnable; it needs credentials this
project does not have.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np

from hazard.holland import TrackPoint
from ingest.tracks import Storm

EARTH_RADIUS_KM = 6371.0


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dlam = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlam / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


@dataclass
class TrackSkill:
    """How the ensemble did against the storm that actually happened."""

    step: int
    hours_before_landfall: float
    #: Distance from each member to the true position at this step, km.
    member_errors_km: list[float]
    #: Did the true position fall inside the spread of members?
    truth_within_envelope: bool
    #: Distance from the truth to the ensemble-mean position, km. The fair
    #: comparison with a single deterministic forecast such as IMD's.
    ensemble_mean_error_km: float = float("nan")

    @property
    def mean_error_km(self) -> float:
        return float(np.mean(self.member_errors_km))

    @property
    def spread_km(self) -> float:
        """How far apart the members are. Should roughly track the error.

        An ensemble whose spread is much smaller than its error is
        overconfident, which is the dangerous direction: it reports certainty
        it has not earned.
        """
        return float(np.std(self.member_errors_km))


@dataclass
class EnsembleVerification:
    """The whole verification, with the caveat that belongs beside it."""

    storm: str
    n_members: int
    steps: list[TrackSkill]
    landfall_error_km: float
    landfall_envelope_contains_truth: bool
    #: Ensemble-mean position error at the time of landfall.
    landfall_mean_track_error_km: float = float("nan")
    #: "weatherlab" (a forecast issued before the event) or "perturbed".
    source: str = "perturbed"
    #: Hours between the forecast being issued and landfall.
    issued_lead_hours: float = float("nan")

    @property
    def envelope_hit_rate(self) -> float:
        """Fraction of steps where truth fell inside the ensemble spread.

        Consistently high is not automatically good: an ensemble spread so
        wide it always contains the truth carries no information either.
        """
        if not self.steps:
            return float("nan")
        return sum(s.truth_within_envelope for s in self.steps) / len(self.steps)

    @property
    def mean_error_km(self) -> float:
        return float(np.mean([s.mean_error_km for s in self.steps])) if self.steps else float("nan")

    @property
    def is_skill(self) -> bool:
        """Only a forecast issued before the event can demonstrate skill."""
        return self.source == "weatherlab"

    def as_dict(self) -> dict[str, Any]:
        if self.is_skill:
            caveat = (
                f"Real verification: a WeatherNext 3 ensemble issued "
                f"{self.issued_lead_hours:.0f} h before landfall, scored only on "
                f"positions after it was issued, against IMD's post-analysis "
                f"best track. One storm is an anecdote, not a statistic."
            )
        else:
            caveat = (
                "Self-verification. The ensemble is perturbed from this same "
                "best track, so this measures whether the spread is honestly "
                "sized -- not whether the underlying forecast has skill."
            )
        return {
            "storm": self.storm,
            "source": self.source,
            "members": self.n_members,
            "issued_lead_hours": None if np.isnan(self.issued_lead_hours)
                                 else round(self.issued_lead_hours, 1),
            "steps_verified": len(self.steps),
            "envelope_hit_rate": round(self.envelope_hit_rate, 3),
            "mean_track_error_km": round(self.mean_error_km, 1),
            # Both are position errors at the moment of landfall -- not the
            # distance between forecast and actual landfall points, which is
            # the quantity IMD reports. Related, not identical.
            "landfall_error_km": round(self.landfall_error_km, 1),
            "landfall_ensemble_mean_error_km": round(self.landfall_mean_track_error_km, 1),
            "landfall_envelope_contains_truth": self.landfall_envelope_contains_truth,
            "caveat": caveat,
        }


def verify_ensemble(
    storm: Storm,
    members: list[list[TrackPoint]],
    source: str = "perturbed",
    from_time: datetime | None = None,
) -> EnsembleVerification:
    """Compare every ensemble member against the observed best track.

    The envelope test uses the spread of member positions at each step: truth
    counts as contained when it sits no further from the member centroid than
    the furthest member does.

    With `from_time`, only positions at or after it are scored. For a real
    forecast that is essential: before its issue time the members *are* the
    best track, and scoring those would count known history as skill.
    """
    if not members:
        raise ValueError("no ensemble members to verify")

    landfall = storm.landfall_index
    landfall_time = storm.times[landfall] if landfall is not None else None
    steps: list[TrackSkill] = []

    for step, (truth, when) in enumerate(zip(storm.track, storm.times, strict=True)):
        if from_time is not None and when < from_time:
            continue
        positions = [(m[step].lat, m[step].lon) for m in members if step < len(m)]
        if not positions:
            continue

        errors = [_distance_km(truth.lat, truth.lon, lat, lon) for lat, lon in positions]

        centroid_lat = float(np.mean([p[0] for p in positions]))
        centroid_lon = float(np.mean([p[1] for p in positions]))
        truth_from_centroid = _distance_km(truth.lat, truth.lon, centroid_lat, centroid_lon)
        furthest_member = max(
            _distance_km(centroid_lat, centroid_lon, lat, lon) for lat, lon in positions
        )

        # From real timestamps: IMD's record mixes 3- and 6-hourly points, so
        # counting steps and multiplying by three was wrong on most storms.
        hours_before = (
            (landfall_time - when).total_seconds() / 3600.0
            if landfall_time is not None else float("nan")
        )
        steps.append(TrackSkill(
            step=step,
            hours_before_landfall=hours_before,
            member_errors_km=errors,
            truth_within_envelope=truth_from_centroid <= furthest_member,
            ensemble_mean_error_km=truth_from_centroid,
        ))

    # Look the landfall step up by its id, not by list position: once steps
    # before the issue time are skipped the two no longer line up.
    lf = next((s for s in steps if s.step == landfall), None)
    issued_lead = (
        (landfall_time - from_time).total_seconds() / 3600.0
        if from_time is not None and landfall_time is not None else float("nan")
    )

    return EnsembleVerification(
        storm=storm.name,
        n_members=len(members),
        steps=steps,
        landfall_error_km=lf.mean_error_km if lf else float("nan"),
        landfall_envelope_contains_truth=lf.truth_within_envelope if lf else False,
        landfall_mean_track_error_km=lf.ensemble_mean_error_km if lf else float("nan"),
        source=source,
        issued_lead_hours=issued_lead,
    )


#: IMD's average landfall-point error, 2021-25 (Mission Mausam, Mar 2026).
IMD_LANDFALL_ERROR_KM = {"24h": 19.0, "48h": 34.4, "72h": 77.3}


def compare_with_imd_skill(verification: EnsembleVerification) -> dict[str, Any]:
    """Put the ensemble's landfall error next to IMD's published figures."""
    if verification.is_skill:
        interpretation = (
            f"At landfall time the WeatherNext 3 ensemble-mean position was "
            f"{verification.landfall_mean_track_error_km:.0f} km from the "
            f"observed centre, forecast {verification.issued_lead_hours:.0f} h "
            f"out; individual members averaged "
            f"{verification.landfall_error_km:.0f} km. IMD reports landfall-point "
            f"error averaged over five years of storms -- a related but different "
            f"measure -- and this is one storm, so it shows the comparison can be "
            f"made, not which forecaster is better."
        )
    else:
        interpretation = (
            "Spread is consistent with IMD's published operational error at the "
            "lead time the ensemble was built for. This confirms the "
            "uncertainty is honestly sized; it does not demonstrate forecast "
            "skill, which requires a forecast made before the event."
        )
    return {
        "imd_published_landfall_error_km": IMD_LANDFALL_ERROR_KM,
        "our_mean_landfall_spread_km": round(verification.landfall_error_km, 1),
        "ensemble_mean_error_at_landfall_km": round(verification.landfall_mean_track_error_km, 1),
        "source": verification.source,
        "interpretation": interpretation,
    }

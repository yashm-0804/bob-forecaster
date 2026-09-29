"""What the network is for: features computed from trusted readings only.

Only fusable readings are used. A flagged reading stays in the store as
evidence for maintenance, but it never reaches a number the model consumes.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from telemetry.qc import pressure_msl
from telemetry.schema import NodeObservation


def pressure_tendency_3h(series: list[NodeObservation], at: datetime) -> float | None:
    """Change in sea-level pressure over the three hours ending at `at`, hPa.

    The oldest and most dependable storm signal a barometer gives: a fall of a
    few hPa in three hours means something is coming. None when the record
    does not reach back far enough to say.
    """
    window = [o for o in series if at - timedelta(hours=3, minutes=20)
              <= datetime.fromisoformat(o.ts) <= at]
    if len(window) < 2:
        return None
    first, last = window[0], window[-1]
    span = datetime.fromisoformat(last.ts) - datetime.fromisoformat(first.ts)
    if span < timedelta(hours=2, minutes=30):
        return None
    return round(pressure_msl(last) - pressure_msl(first), 2)


def rain_accumulation(series: list[NodeObservation], at: datetime,
                      hours: float = 72.0) -> float | None:
    """Rain over the window ending at `at`, mm. Tier B and C only."""
    readings = [o.rain_mm_15m for o in series
                if o.rain_mm_15m is not None
                and at - timedelta(hours=hours) <= datetime.fromisoformat(o.ts) <= at]
    return round(sum(readings), 1) if readings else None

"""Node tier definitions and the telemetry wire schema.

Instrument choice follows site role, not a uniform build. Each tier exists
because a specific measurement needs a specific siting condition to mean
anything -- rain gauges need convective-scale spacing, wind needs an
obstruction-free mast, water level needs a structure surveyed to a datum.

This module is the single source of truth for what a node of a given tier is
allowed to report. `qc.py` rejects fields a tier has no instrument for.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Tier(StrEnum):
    """Node tiers, ordered by instrument cost."""

    ATMOSPHERIC = "A"
    RAIN = "B"
    WIND_MAST = "C"
    WATER_LEVEL = "D"
    SLOPE = "E"


class SiteClass(StrEnum):
    """Vertical siting class.

    Drives reduction of station pressure to MSL, supplies lapse-rate sanity
    checks for QC, and marks which nodes are candidate LoRa gateway hosts
    (ELEVATED sites have the line-of-sight).
    """

    SEA_LEVEL = "sea_level"
    DELTA_FLAT = "delta_flat"
    ELEVATED = "elevated"


@dataclass(frozen=True)
class TierSpec:
    """What a tier carries, what it costs, and how far apart to place them."""

    tier: Tier
    role: str
    instruments: tuple[str, ...]
    #: Reported fields this tier is permitted to populate, beyond the base set.
    optional_fields: frozenset[str]
    cost_inr: tuple[int, int]
    #: Nominal spacing in km. None where the tier is sited by opportunity
    #: (a jetty pile, an at-risk slope) rather than on a grid.
    spacing_km: float | None
    spacing_rationale: str


#: Fields every node reports regardless of tier.
BASE_FIELDS = frozenset(
    {
        "node_id",
        "tier",
        "lat",
        "lon",
        "elev_m",
        "site_class",
        "ts",
        "pressure_hpa",
        "temp_c",
        "rh_pct",
        "battery_v",
        "rssi",
        "qc_flags",
    }
)


TIER_SPECS: dict[Tier, TierSpec] = {
    Tier.ATMOSPHERIC: TierSpec(
        tier=Tier.ATMOSPHERIC,
        role="Network backbone. Pressure tendency field and the QC reference "
        "for every other tier.",
        instruments=("BME280 (T/RH/P)", "GPS (one-time fix)", "LoRa", "solar + battery"),
        optional_fields=frozenset(),
        cost_inr=(6_000, 8_000),
        spacing_km=25.0,
        spacing_rationale=(
            "Surface pressure is spatially smooth; a single well-sited sensor is "
            "representative over tens of km, so density buys little."
        ),
    ),
    Tier.RAIN: TierSpec(
        tier=Tier.RAIN,
        role="Flat and urban catchments, convective corridors.",
        instruments=("Tier A", "Hydreon RG-15 optical gauge"),
        optional_fields=frozenset({"rain_mm_15m"}),
        cost_inr=(15_000, 18_000),
        spacing_km=5.0,
        spacing_rationale=(
            "Convective cells are 1-5 km across. This is the one variable where "
            "density genuinely changes what the model can see, and it targets the "
            "rainfall damage pathway that wind-category systems miss."
        ),
    ),
    Tier.WIND_MAST: TierSpec(
        tier=Tier.WIND_MAST,
        role="Open, obstruction-free sites: ports, exposed headlands.",
        instruments=("Tier B", "ultrasonic anemometer on 3-10 m mast"),
        optional_fields=frozenset({"wind_ms", "wind_dir_deg"}),
        cost_inr=(35_000, 45_000),
        spacing_km=None,
        spacing_rationale=(
            "Sited, not spaced. Wind decorrelates over hundreds of metres near "
            "trees and buildings, so density cannot rescue a bad site. Feeds "
            "fragility-curve calibration, not forecasting."
        ),
    ),
    Tier.WATER_LEVEL: TierSpec(
        tier=Tier.WATER_LEVEL,
        role="Fixed structures only: jetty piles, bridge abutments, embankments.",
        instruments=(
            "Tier A",
            "submersible pressure transducer or radar ranger",
            "1-6 min wave-averaging firmware",
        ),
        optional_fields=frozenset({"water_level_m", "datum_ref"}),
        cost_inr=(30_000, 50_000),
        spacing_km=None,
        spacing_rationale=(
            "One per estuary or inlet, mounted rigidly and surveyed to a vertical "
            "datum. Without the datum the reading is not comparable to anything; "
            "without wave averaging it measures swell, not storm tide."
        ),
    ),
    Tier.SLOPE: TierSpec(
        tier=Tier.SLOPE,
        role="Hill slopes, embankments, eroding shoreline segments.",
        instruments=(
            "Tier A",
            "capacitive soil moisture at 2-3 depths",
            "IMU tilt",
            "optional RTK-GNSS rover",
        ),
        optional_fields=frozenset({"soil_vwc_pct", "tilt_deg", "rtk_displacement_mm"}),
        cost_inr=(12_000, 80_000),
        spacing_km=None,
        spacing_rationale=(
            "Clustered on at-risk slopes, not distributed. Highest-value tier: "
            "satellite soil moisture (SMAP) is 9-36 km, far too coarse for "
            "slope-scale landslide triggering, so antecedent moisture here is a "
            "genuine gap fill. RTK is what actually detects ground movement -- a "
            "+/-3 m consumer GPS fix detects nothing."
        ),
    ),
}


def permitted_fields(tier: Tier) -> frozenset[str]:
    """Every field a node of this tier may populate.

    Tiers are cumulative in instruments but not in reported fields: a Tier C
    mast carries Tier B's rain gauge, so it inherits B's optional fields.
    """
    inherited: frozenset[str] = frozenset()
    if tier in (Tier.WIND_MAST,):
        inherited = TIER_SPECS[Tier.RAIN].optional_fields
    return BASE_FIELDS | TIER_SPECS[tier].optional_fields | inherited


@dataclass
class NodeObservation:
    """One telemetry message.

    Sized to fit a LoRa payload (~50 bytes) once CBOR-encoded with the static
    fields -- node_id, tier, lat, lon, elev_m, site_class -- resolved from a
    registry at the gateway rather than sent on every message.
    """

    node_id: str
    tier: Tier
    lat: float
    lon: float
    elev_m: float
    site_class: SiteClass
    ts: str  # ISO 8601, UTC

    # Base instruments (Tier A and up). None is a dead sensor: the field is
    # still required on the wire, and QC flags the channel as missing.
    pressure_hpa: float | None
    temp_c: float | None
    rh_pct: float | None

    # Housekeeping
    battery_v: float | None
    rssi: int | None

    # Tier B
    rain_mm_15m: float | None = None

    # Tier C
    wind_ms: float | None = None
    wind_dir_deg: float | None = None

    # Tier D
    water_level_m: float | None = None
    datum_ref: str | None = None

    # Tier E
    soil_vwc_pct: list[float] | None = None
    tilt_deg: float | None = None
    rtk_displacement_mm: float | None = None

    qc_flags: list[str] = field(default_factory=list[str])

    def populated_optional_fields(self) -> set[str]:
        """Optional fields carrying a value, for tier-permission checking."""
        optional = {
            "rain_mm_15m",
            "wind_ms",
            "wind_dir_deg",
            "water_level_m",
            "datum_ref",
            "soil_vwc_pct",
            "tilt_deg",
            "rtk_displacement_mm",
        }
        return {f for f in optional if getattr(self, f) is not None}

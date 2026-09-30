"""Common Alerting Protocol 1.2 emission.

CAP (ITU X.1303) is the XML standard behind SACHET, India's national alert
system, which has delivered 134bn+ SMS in 19+ languages, and behind cell
broadcast. The dispatch pipe already exists and works; what is thin is what
goes into it. So we emit well-formed, asset-level, department-specific CAP
and feed that pipe rather than rebuilding delivery.

Every alert produced here carries status=Exercise. Issuing real cyclone
warnings in India is IMD's statutory role; this is decision support, and the
demo must never be mistakable for an official warning.
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from impact.rollup import AssetRisk

CAP_NS = "urn:oasis:names:tc:emergency:cap:1.2"
#: Who issues these advisories, for CAP <senderName> ("the originator").
#: The department an advisory is for is its <audience>.
SENDER_NAME = ("Project CYCLOPS, Bay of Bengal cyclone impact forecaster "
               "(exercise; not an IMD warning)")


@dataclass(frozen=True)
class Recipient:
    """A department, and the lead time at which its advisory is useful."""

    key: str
    name: str
    lead_hours: tuple[int, int]
    asset_classes: tuple[str, ...]


@dataclass(frozen=True)
class RegionProfile:
    """What changes about an advisory when the coast changes.

    Language and utility used to be fixed per department, which sent the
    Odisha run's advisories to Andhra utilities with a Telugu label. Both are
    properties of the region, not the department.
    """

    languages: tuple[str, ...]
    discom: str


#: Local language and the distribution utilities serving each named region.
REGION_PROFILES: dict[str, RegionProfile] = {
    # East and West Godavari are APEPDCL; Krishna moved to APCPDCL in 2020.
    "andhra": RegionProfile(("en-IN", "te-IN"), "APEPDCL / APCPDCL"),
    # Puri and Khordha are TPCODL; Ganjam is TPSODL.
    "odisha": RegionProfile(("en-IN", "or-IN"), "TPCODL / TPSODL"),
    "vizag": RegionProfile(("en-IN", "te-IN"), "APEPDCL"),
}

#: Used for a custom area: English only, and a utility name that says what
#: it is rather than guessing.
DEFAULT_PROFILE = RegionProfile(("en-IN",), "the local distribution utility")

LANGUAGE_NAMES = {"en-IN": "English", "te-IN": "Telugu", "or-IN": "Odia",
                  "bn-IN": "Bengali", "ta-IN": "Tamil", "hi-IN": "Hindi"}


#: Who gets advised about what. Lead times follow the dossier's recipient
#: table: utilities need 72-24 h to stage crews, municipal drainage 72-6 h.
RECIPIENTS: dict[str, Recipient] = {
    "discom": Recipient(
        "discom", "Distribution utility", (72, 24),
        ("substation", "transmission_tower", "lv_pole"),
    ),
    "collector": Recipient(
        "collector", "District Collector / District Disaster Management Authority",
        (48, 24), ("shelter", "hospital"),
    ),
    "pwd": Recipient(
        "pwd", "Public Works / Highways", (48, 12), ("road_segment",),
    ),
    "health": Recipient(
        "health", "Health Department", (48, 12), ("hospital",),
    ),
    "municipal": Recipient(
        "municipal", "Municipal Corporation", (72, 6),
        ("road_segment", "substation"),
    ),
}


def recipient_for(key: str, profile: RegionProfile) -> Recipient:
    """The recipient as addressed in a particular region."""
    base = RECIPIENTS[key]
    if key == "discom":
        return Recipient(base.key, f"Distribution utility ({profile.discom})",
                         base.lead_hours, base.asset_classes)
    return base

#: CAP severity by consequence band. Urgency and certainty are not the
#: band's to say: urgency follows the lead time (`cap_urgency`), certainty the
#: ensemble probability (`cap_certainty`). Taking all three from the band once
#: marked a 13-18% chance of failure "Likely".
CAP_SEVERITY = {"red": "Extreme", "orange": "Severe", "yellow": "Moderate", "green": "Minor"}


def cap_urgency(hours_to_landfall: float | None) -> str:
    """CAP 1.2 urgency from the lead time. Immediate: act now; Expected: act
    soon; Future: act in the near future. Unknown without a lead time."""
    if hours_to_landfall is None:
        return "Unknown"
    if hours_to_landfall <= 12:
        return "Immediate"
    return "Expected" if hours_to_landfall <= 24 else "Future"


def cap_certainty(p_failure: float | None) -> str:
    """CAP 1.2 certainty from the probability of the event -- here, that the
    most likely listed asset fails. Likely: more than about 50%; Possible:
    not negligible; Unlikely: about zero. Unknown without a probability."""
    if p_failure is None:
        return "Unknown"
    if p_failure > 0.5:
        return "Likely"
    return "Possible" if p_failure >= 0.05 else "Unlikely"


@dataclass
class Advisory:
    """A drafted advisory, pending human approval.

    `approved` starts False and nothing may be dispatched until an operator
    sets it. That gate is a product requirement, not a formality.
    """

    identifier: str
    recipient: Recipient
    headline: str
    instruction: str
    severity: str
    assets: list[dict[str, Any]]
    sent: datetime
    area_desc: str
    ensemble_note: str
    approved: bool = False
    approved_by: str | None = None
    #: Text in languages other than the English source, keyed by CAP language
    #: code. Only a language present here is ever emitted.
    translations: dict[str, dict[str, str]] = field(default_factory=dict[str, dict[str, str]])
    #: Languages the region needs, whether or not text exists for them yet.
    requested_languages: tuple[str, ...] = ("en-IN",)
    #: Who wrote the prose: "template" or a model id. Numbers are always code's.
    drafted_by: str = "template"
    #: Anything the drafting step rejected or could not do, for the operator.
    draft_notes: list[str] = field(default_factory=list[str])
    #: Hours from this forecast cycle to landfall, for CAP urgency.
    hours_to_landfall: float | None = None

    def content_digest(self) -> str:
        """A fingerprint of everything an approving officer reads.

        The send time is left out, so re-running a cycle that produces the
        same text keeps the same identifier -- and its approval. Any change to
        the words, the assets or the severity changes it.
        """
        import hashlib
        import json

        content = {
            "recipient": self.recipient.key, "severity": self.severity,
            "headline": self.headline, "instruction": self.instruction,
            "ensemble_note": self.ensemble_note, "area": self.area_desc,
            "translations": self.translations,
            "assets": [(a.get("name"), a.get("p_failure")) for a in self.assets],
        }
        blob = json.dumps(content, sort_keys=True, ensure_ascii=False).encode()
        return hashlib.sha256(blob).hexdigest()[:8]

    def sealed(self) -> Advisory:
        """This advisory with its content fingerprint in the identifier.

        Approvals are recorded against the identifier. Keyed by cycle alone,
        a regenerated cycle with different text inherited the approval given
        to the old text; sealed, it cannot.
        """
        return replace(self, identifier=f"{self.identifier}-{self.content_digest()}")

    @property
    def languages(self) -> list[str]:
        """Languages this advisory actually has text in.

        An earlier version emitted a te-IN block for every advisory and filled
        it with the English text whenever no translation existed -- a Telugu
        label on English words, and on the Odisha run a Telugu label on an
        Odia-speaking district. A block now exists only if its text does.
        """
        return ["en-IN"] + [
            lang for lang in self.requested_languages
            if lang != "en-IN" and lang in self.translations
        ]

    @property
    def pending_languages(self) -> list[str]:
        """Languages the region needs that have no text yet."""
        return [
            lang for lang in self.requested_languages
            if lang != "en-IN" and lang not in self.translations
        ]

    def to_cap_xml(self) -> str:
        """Render as CAP 1.2 XML, one <info> block per language with text."""
        sev = CAP_SEVERITY[self.severity]
        urgency = cap_urgency(self.hours_to_landfall)
        probabilities = [float(a["p_failure"]) for a in self.assets
                         if a.get("p_failure") is not None]
        certainty = cap_certainty(max(probabilities) if probabilities else None)
        infos: list[str] = []
        for lang in self.languages:
            t = self.translations.get(lang, {})
            headline = t.get("headline", self.headline)
            instruction = t.get("instruction", self.instruction)
            description = t.get("description", self.ensemble_note)
            infos.append(f"""  <info>
    <language>{lang}</language>
    <category>Met</category>
    <category>Infra</category>
    <event>Cyclone: infrastructure exposure advisory</event>
    <urgency>{urgency}</urgency>
    <severity>{sev}</severity>
    <certainty>{certainty}</certainty>
    <audience>{html.escape(self.recipient.name)}</audience>
    <senderName>{html.escape(SENDER_NAME)}</senderName>
    <headline>{html.escape(headline)}</headline>
    <description>{html.escape(description)}</description>
    <instruction>{html.escape(instruction)}</instruction>
    <area>
      <areaDesc>{html.escape(self.area_desc)}</areaDesc>
    </area>
  </info>""")

        return f"""<?xml version="1.0" encoding="UTF-8"?>
<alert xmlns="{CAP_NS}">
  <identifier>{self.identifier}</identifier>
  <sender>advisories@project-cyclops.example</sender>
  <sent>{_cap_time(self.sent)}</sent>
  <status>Exercise</status>
  <msgType>Alert</msgType>
  <scope>Restricted</scope>
  <restriction>Municipal and disaster management authorities</restriction>
{chr(10).join(infos)}
</alert>"""


IST = ZoneInfo("Asia/Kolkata")


def _cap_time(when: datetime) -> str:
    """CAP time in IST with a correct offset, wherever this runs.

    This used to format local time and append "+05:30" as a literal: right on
    a laptop in India, wrong by 5 h 30 m on a UTC server such as Cloud Run.
    A naive datetime is taken as the machine's local time, then converted.
    """
    aware = when if when.tzinfo else when.astimezone()
    return aware.astimezone(IST).isoformat(timespec="seconds")


def draft(
    recipient_key: str,
    risks: list[AssetRisk],
    storm_name: str,
    hours_to_landfall: float,
    area_desc: str,
    top_n: int = 10,
    region: str = "custom",
    n_members: int = 50,
    forecast_time: datetime | None = None,
) -> Advisory | None:
    """Draft an advisory for one department from scored assets.

    Deterministic and template-based. `advisory/gemini.py` may later replace
    the prose and add the local-language text -- but every number stays
    computed here and is passed to the model as a fact to cite, never
    generated by it.
    """
    profile = REGION_PROFILES.get(region, DEFAULT_PROFILE)
    recipient = recipient_for(recipient_key, profile)
    relevant = [
        r for r in risks
        if r.asset.asset_class in recipient.asset_classes
        and r.severity in ("red", "orange")
    ][:top_n]
    if not relevant:
        return None

    worst = "red" if any(r.severity == "red" for r in relevant) else "orange"
    n_red = sum(1 for r in relevant if r.severity == "red")
    drivers = [r.dominant_driver for r in relevant]
    driver = max(("wind", "flood"), key=drivers.count)

    lo = min(r.p_failure_p10 for r in relevant)
    hi = max(r.p_failure_p90 for r in relevant)

    headline = (
        f"{len(relevant)} assets at risk from {storm_name}: "
        f"{n_red} high-probability, {hours_to_landfall:.0f} h to landfall"
    )
    instruction = _instruction_for(recipient_key, relevant, driver)
    ensemble_note = (
        f"Across a {n_members}-member track ensemble, failure probability for "
        f"the listed assets spans {lo:.0%}-{hi:.0%} (10th-90th percentile). "
        f"Dominant driver: {driver}. Surge figures are screening-grade, not a "
        f"coupled hydrodynamic simulation."
    )

    # Identified by forecast cycle, not wall clock. A minute-resolution
    # timestamp let two cycles run in the same minute share identifiers, so an
    # approval given to one cycle's advisory could silently cover the next.
    cycle = f"{forecast_time:%Y%m%d%H}Z" if forecast_time else f"{datetime.now():%Y%m%d%H%M}"
    return Advisory(
        identifier=(
            f"T5-{storm_name.upper()}-{recipient_key.upper()}-"
            f"{cycle}-T{hours_to_landfall:.0f}"
        ),
        recipient=recipient,
        headline=headline,
        instruction=instruction,
        severity=worst,
        assets=[r.to_dict() for r in relevant],
        # Sent at the forecast cycle it belongs to -- in UTC, as IMD issues
        # it -- not when this replay happened to run.
        sent=forecast_time.replace(tzinfo=UTC) if forecast_time else datetime.now(),
        hours_to_landfall=hours_to_landfall,
        area_desc=area_desc,
        ensemble_note=ensemble_note,
        requested_languages=profile.languages,
    )


def _instruction_for(key: str, risks: list[AssetRisk], driver: str) -> str:
    """Department-specific action, naming the actual assets."""
    names = ", ".join(r.asset.label for r in risks[:5])
    if key == "discom":
        return (
            f"Pre-position repair crews and spare poles near: {names}. "
            f"Stage transformers at the nearest division store. "
            + ("Plan pre-emptive de-energisation of coastal feeders ahead of "
               "peak winds." if driver == "wind" else
               "Raise or isolate ground-level switchgear at flood-exposed sites.")
        )
    if key == "collector":
        return (
            f"Verify shelter readiness and stocks at: {names}. "
            "Confirm evacuation transport and cross-check shelter capacity "
            "against the population in the surge-exposed wards."
        )
    if key == "pwd":
        return (
            f"Stage tree-cutting teams and earthmovers covering: {names}. "
            "Identify diversions for evacuation routes likely to be blocked."
        )
    if key == "health":
        return (
            f"Confirm generator fuel days and check access routes for: {names}. "
            "Move ground-floor critical care and oxygen plant above expected "
            "water level where flood is the driver."
        )
    return (
        f"Clear drains and confirm pump readiness around: {names}. "
        "Position dewatering equipment at known waterlogging points."
    )

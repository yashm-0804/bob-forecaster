"""The agent the brief asks for: wake on each bulletin, re-run, re-advise.

"Automate early-warning advisory dispatches" means an officer should arrive to
a prepared decision, not a blank map. So on each forecast cycle this re-runs
the whole pipeline, drafts fresh advisories, and -- the part that matters on
hour 36 of a storm -- works out what changed since the last cycle. A
department that was already told to stage crews does not need the same list
again; it needs to know that two substations went from orange to red.

Two sources of cycles:

  ReplaySource  replays a storm from the record as IMD would have issued it,
                at fixed lead times before landfall. Runs anywhere, offline.

  LiveSource    watches for new bulletins. IMD issues them as PDFs, and
                reading a PDF into a storm state is Gemini's job, so without a
                key this reports itself unavailable instead of pretending.

Approval never carries over between cycles. Advisory identifiers are keyed to
the forecast cycle, so a changed advisory is a new advisory and needs a named
officer's approval again.

Run:
    python -m agent.watch --replay MONTHA 2025
    python -m agent.watch --replay FANI 2019 --region odisha --leads 72 48 24
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "data" / "agent_log.jsonl"

SEVERITY_RANK = {"green": 0, "yellow": 1, "orange": 2, "red": 3}


@dataclass(frozen=True)
class Cycle:
    """One forecast cycle: which storm, and how far out."""

    storm: str
    year: int
    lead_hours: int
    region: str


class CycleSource(Protocol):
    def cycles(self) -> Iterator[Cycle]: ...


class ReplaySource:
    """A storm from the record, issued as a sequence of bulletins."""

    def __init__(self, storm: str, year: int, region: str = "andhra",
                 leads: tuple[int, ...] = (72, 48, 24, 12)) -> None:
        self.storm, self.year, self.region = storm, year, region
        self.leads = tuple(sorted(leads, reverse=True))   # far out first

    def cycles(self) -> Iterator[Cycle]:
        for lead in self.leads:
            yield Cycle(self.storm, self.year, lead, self.region)


class LiveSource:
    """New IMD bulletins, as they are issued.

    Not runnable without Gemini: bulletins are PDFs, and extracting a storm
    state from one is the task the brief assigns to the model. This source
    says so rather than falling back to anything that looks live but is not.
    """

    def __init__(self, poll_seconds: int = 1800) -> None:
        self.poll_seconds = poll_seconds

    def cycles(self) -> Iterator[Cycle]:
        from advisory import gemini

        ok, reason = gemini.availability()
        if not ok:
            raise RuntimeError(
                f"live bulletin watching needs Gemini to read IMD PDFs: {reason}"
            )
        raise NotImplementedError(
            "bulletin PDF parsing is not wired yet; use --replay"
        )


def _advisory_changes(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, list[str]]:
    """Departments newly advised, escalated, eased or no longer advised."""
    prev_adv = {a["recipient_key"]: a for a in previous.get("advisories", [])}
    curr_adv = {a["recipient_key"]: a for a in current.get("advisories", [])}
    out: dict[str, list[str]] = {"new": [], "escalated": [], "eased": [], "withdrawn": []}
    for key, adv in curr_adv.items():
        if key not in prev_adv:
            out["new"].append(adv["recipient"])
            continue
        before = SEVERITY_RANK[prev_adv[key]["severity"]]
        after = SEVERITY_RANK[adv["severity"]]
        if after != before:
            out["escalated" if after > before else "eased"].append(adv["recipient"])
    out["withdrawn"] = [prev_adv[k]["recipient"] for k in prev_adv if k not in curr_adv]
    return out


def _red(payload: dict[str, Any]) -> dict[str, str]:
    """Red assets by OSM id -> name: all of them where the run lists them,
    else the ones in the shipped table (runs exported before that list)."""
    if "red_assets" in payload:
        return {osm_id: name for osm_id, name in payload["red_assets"]}
    return {a["osm_id"]: a["name"] for a in payload.get("assets", [])
            if a["severity"] == "red"}


def _summary(counts: list[tuple[int, str, str]]) -> str:
    """"3 assets newly red; 1 advisory escalated." -- or "no material change"."""
    parts = [f"{n} {one if n == 1 else many}" for n, one, many in counts if n]
    return "; ".join(parts or ["no material change"]) + "."


def diff_cycles(previous: dict[str, Any] | None, current: dict[str, Any]) -> dict[str, Any]:
    """What an officer needs to know that the last cycle did not tell them."""
    if previous is None:
        return {"first_cycle": True, "summary": "First forecast cycle for this storm."}

    adv = _advisory_changes(previous, current)
    red_before, red_now = _red(previous), _red(current)
    newly_red = [red_now[k] for k in red_now if k not in red_before]
    no_longer_red = [red_before[k] for k in red_before if k not in red_now]
    ps, cs = previous["summary"], current["summary"]
    new, escalated, eased, withdrawn = adv["new"], adv["escalated"], adv["eased"], adv["withdrawn"]
    summary = _summary([
        (len(newly_red), "asset newly red", "assets newly red"),
        (len(no_longer_red), "no longer red", "no longer red"),
        (len(escalated), "advisory escalated", "advisories escalated"),
        (len(eased), "advisory eased", "advisories eased"),
        (len(new), "department newly advised", "departments newly advised"),
        (len(withdrawn), "advisory withdrawn", "advisories withdrawn"),
    ])

    return {
        "first_cycle": False,
        "previous_lead_hours": ps["hours_to_landfall"],
        "summary": summary,
        "advisories_new": new,
        "advisories_escalated": escalated,
        "advisories_eased": eased,
        "advisories_withdrawn": withdrawn,
        "assets_newly_red": newly_red[:25],
        "assets_no_longer_red": no_longer_red[:25],
        "red_count": {"before": len(red_before), "now": len(red_now)},
        "people_without_power_est": {
            "before": ps["people_without_power_est"],
            "now": cs["people_without_power_est"],
        },
    }


def run_cycle(cycle: Cycle, previous: dict[str, Any] | None,
              out_dir: Path | None = None) -> tuple[dict[str, Any], Path]:
    import pipeline
    from exposure.osm import REGIONS

    out_dir = out_dir or pipeline.OUT_DIR

    result = pipeline.run(
        cycle.storm, cycle.year, lead_hours=float(cycle.lead_hours),
        bbox=REGIONS[cycle.region],
    )
    # Refuse to publish a cycle on placeholder terrain. It happened: one
    # timed-out tile request dropped a Fani cycle onto flat terrain, and the
    # diff against the previous real cycle reported 159 assets standing down
    # -- a model change presented as a change in the storm.
    if result.summary.get("terrain_source") == "flat-placeholder":
        raise DegradedCycle("no real terrain available; advisories not published")
    # The diff is computed from exactly the payload the console will see,
    # then the file is written once, with it.
    current = json.loads(pipeline.payload_json(result))
    changes = diff_cycles(previous, current)
    path = pipeline.export(result, out_dir, extra={"changes": changes})
    return json.loads(path.read_text()), path


class DegradedCycle(RuntimeError):
    """A cycle that ran, but on inputs too degraded to publish."""


def log_event(event: dict[str, Any]) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(json.dumps(event) + "\n")


def watch(source: CycleSource, pause_seconds: float = 0.0) -> list[dict[str, Any]]:
    """Run every cycle the source yields, in order, carrying state forward."""
    previous: dict[str, Any] | None = None
    events: list[dict[str, Any]] = []
    for cycle in source.cycles():
        started = time.monotonic()
        try:
            payload, path = run_cycle(cycle, previous)
        # A cycle that fails in any way -- degraded inputs, a data source
        # down, a bug -- costs that cycle, not the rest of the storm. It is
        # recorded with its reason, and the last good cycle stays the
        # baseline so the next diff is against something real.
        except Exception as exc:  # noqa: BLE001 -- recorded and reported, not hidden
            reason = str(exc) if isinstance(exc, DegradedCycle) else f"{type(exc).__name__}: {exc}"
            event = {"at": datetime.now(UTC).isoformat(timespec="seconds"),
                     "storm": cycle.storm, "lead_hours": cycle.lead_hours,
                     "failed": reason}
            log_event(event)
            events.append(event)
            print(f"T-{cycle.lead_hours:>2}h  {cycle.storm:<8} FAILED: {reason}")
            continue
        event = {
            "at": datetime.now(UTC).isoformat(timespec="seconds"),
            "storm": cycle.storm,
            "lead_hours": cycle.lead_hours,
            "file": path.name,
            "advisories": len(payload["advisories"]),
            "changes": payload["changes"]["summary"],
            "seconds": round(time.monotonic() - started, 1),
        }
        log_event(event)
        events.append(event)
        print(f"T-{cycle.lead_hours:>2}h  {cycle.storm:<8} "
              f"{event['advisories']} advisories  {event['changes']}  "
              f"({event['seconds']}s)")
        previous = payload
        if pause_seconds:
            time.sleep(pause_seconds)
    return events


def main() -> None:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--replay", nargs=2, metavar=("STORM", "YEAR"))
    from exposure.osm import REGIONS

    # An unknown region used to fail every cycle with a KeyError; refuse it here.
    ap.add_argument("--region", default="andhra", choices=sorted(REGIONS))
    ap.add_argument("--leads", nargs="+", type=int, default=[72, 48, 24, 12])
    ap.add_argument("--live", action="store_true")
    args = ap.parse_args()

    import envfile
    envfile.load()

    from ingest.net import use_certifi_globally
    use_certifi_globally()

    if args.live:
        try:
            watch(LiveSource())
        except (RuntimeError, NotImplementedError) as exc:
            # Not a crash: live mode says what it needs and stops.
            raise SystemExit(f"live mode unavailable: {exc}") from None
    elif args.replay:
        storm, year = args.replay
        events = watch(ReplaySource(storm.upper(), int(year), args.region, tuple(args.leads)))
        failed = [e for e in events if "failed" in e]
        if failed:
            raise SystemExit(f"{len(failed)} of {len(events)} cycles failed; see {LOG}")
    else:
        ap.error("choose --replay STORM YEAR or --live")


if __name__ == "__main__":
    main()

"""HTTP API for the operator console.

The console is the product surface the brief asks for: municipal and disaster
management authorities looking at a map 48 hours before landfall. This serves
it, plus the JSON the pipeline produces.

The dispatch endpoint deliberately refuses to send anything that has not been
approved by a named operator, and stamps every alert as an exercise.

What every request passes through first is in api/guard.py; the run files in
api/run_store.py; the request and response models in api/models.py.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any, cast

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi import Path as PathParam
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from api import access, docs, guard, identity
from api.audit import AuditLog, AuditStore
from api.models import (
    Approval,
    Dispatcher,
    DispatchReceipt,
    Health,
    OperatorAction,
    RunListing,
    Withdrawal,
    named,
)
from api.run_store import RunFileError, find_advisory, load_run, readable_runs, run_status
from telemetry.ingest import (
    DuplicateObservation,
    RegistryError,
    TelemetryStore,
    UnknownNode,
    ValidationError,
    load_registry,
    registry_problem,
    utc_now,
)

LOG = logging.getLogger("bob.api")

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"

app = FastAPI(
    title="Project CYCLOPS: Bay of Bengal Cyclone Impact Forecaster",
    description="Asset-level cyclone impact and advisory drafting. Decision "
                "support only -- IMD is the statutory warning authority.",
    version="0.1.0",
    # Served by api/docs.py, under a content policy and not on a deployment
    # by default; the schema they read goes with them.
    docs_url=None, redoc_url=None, openapi_url=None,
)
guard.install(app)
app.include_router(docs.router)


#: Approvals and dispatch attempts, append-only on disk; and live telemetry
#: from field nodes, the local stand-in for Pub/Sub -> BigQuery. Both are
#: opened on first use, so importing the API writes nothing. Tests replace them.
_audit: AuditStore | None = None
_telemetry: TelemetryStore | None = None
_STORES_LOCK = threading.Lock()


def use_stores(audit: AuditStore, telemetry: TelemetryStore) -> None:
    """Point the API at particular stores -- for benchmarks and tools that
    must not touch the configured ones."""
    global _audit, _telemetry
    with _STORES_LOCK:
        _audit, _telemetry = audit, telemetry


#: What goes wrong when a store is unusable: a file unreadable, corrupt, in
#: a directory that cannot be created or on a full disk; BigQuery unreachable
#: or refusing (api/bigquery_audit.BigQueryError is an OSError).
STORAGE_ERRORS = (sqlite3.Error, OSError)


class StoreRefused(OSError):
    """A store whose setting cannot work. Answered as any unusable store is --
    approvals refused, the forecast still served -- and named in /api/health."""


@app.exception_handler(sqlite3.Error)
@app.exception_handler(OSError)
async def storage_unavailable(request: Request, exc: Exception) -> JSONResponse:
    """A store that cannot be used is a 503 saying nothing was recorded, not a
    500 -- and never a response that names the file."""
    LOG.error("storage unavailable on %s %s: %r", request.method, request.url.path, exc)
    return JSONResponse({"detail": "Storage is unavailable on this server; nothing was "
                                   "recorded. /api/health says which store."}, status_code=503)


def store_problems() -> list[str]:
    """Stores that cannot be opened and read, for /api/health."""
    problems: list[str] = []
    for name, opener in (("audit log", audit_log), ("telemetry store", telemetry_store)):
        try:
            store = opener()
            store.probe()
        except StoreRefused:
            pass     # its setting is reported on its own
        except STORAGE_ERRORS as exc:
            problems.append(f"the {name} cannot be used ({type(exc).__name__})")
        except HTTPException:
            pass     # a store refused by configuration is reported on its own
    return problems


#: Where the audit trail is kept: "sqlite" (a file; the default) or
#: "bigquery" (a table, durable on Cloud Run; see api/bigquery_audit.py).
AUDIT_STORES = ("sqlite", "bigquery")


def audit_store_problem() -> str | None:
    """A store setting that cannot work, for /api/health."""
    store = os.environ.get("BOB_AUDIT_STORE", "sqlite")
    if store not in AUDIT_STORES:
        return f"BOB_AUDIT_STORE is {store!r}; it must be one of {', '.join(AUDIT_STORES)}"
    if store == "bigquery" and len(os.environ.get("BOB_BQ_AUDIT_TABLE", "").split(".")) != 3:
        return "BOB_AUDIT_STORE is bigquery, so BOB_BQ_AUDIT_TABLE must name project.dataset.table"
    return None


def audit_log() -> AuditStore:
    """The audit trail, opened on first use; a 503 if its setting cannot work."""
    global _audit
    with _STORES_LOCK:
        if _audit is None:
            problem = audit_store_problem()
            if problem:
                raise StoreRefused(problem)
            if os.environ.get("BOB_AUDIT_STORE", "sqlite") == "bigquery":
                from api import bigquery_audit

                _audit = bigquery_audit.open_log(os.environ["BOB_BQ_AUDIT_TABLE"])
            else:
                _audit = AuditLog(Path(os.environ.get(
                    "BOB_AUDIT_DB", ROOT / "data" / "audit.sqlite3")))
        return _audit


def telemetry_store() -> TelemetryStore:
    """The telemetry store, or a 503 saying why there is none.

    A misconfigured node registry refuses telemetry outright rather than
    accepting every node: the registry exists to keep invented nodes out.
    """
    global _telemetry
    with _STORES_LOCK:
        if _telemetry is None:
            try:
                registry = load_registry(os.environ.get("BOB_NODE_REGISTRY"))
            except RegistryError as exc:
                raise HTTPException(503, f"Telemetry is refused: {exc}") from exc
            _telemetry = TelemetryStore(
                Path(os.environ.get("BOB_TELEMETRY_DB",
                                    ROOT / "data" / "telemetry" / "live.sqlite3")),
                registry=registry, clock=utc_now)
        return _telemetry

#: Storm names become file names; only plain names reach the filesystem.
Storm = PathParam(pattern=r"^[A-Za-z0-9]{1,32}$")

OPERATOR_ONLY = [Depends(access.require(access.OPERATOR))]
#: Reads that need the operator code but are not writes: no write budget.
OPERATOR_READ = [Depends(access.require(access.OPERATOR, counts_as_write=False))]
INGEST_ONLY = [Depends(access.require(access.INGEST))]


@app.exception_handler(RunFileError)
async def run_unavailable(request: Request, exc: Exception) -> JSONResponse:
    LOG.error("run file unusable on %s: %s", request.url.path, exc)
    return JSONResponse({"detail": f"This run cannot be served: {exc}. The other runs are "
                                   "unaffected; /api/health lists the file."}, status_code=503)


class AuthConfig(BaseModel):
    """What the page needs to offer Google sign-in; null when it is off."""

    firebase: dict[str, str] | None


@app.get("/api/auth-config")
def auth_config() -> AuthConfig:
    """Public by design: Firebase's web configuration is sent to every
    browser that signs in."""
    return AuthConfig(firebase=identity.web_config())


@app.get("/api/runs")
def list_runs() -> list[RunListing]:
    """Every replay available to the console."""
    return [RunListing(storm=storm, lead_hours=lead, file=path.name)
            for path, storm, lead in readable_runs()]


@app.get("/api/run/{storm}/{lead}")
def get_run(lead: int, storm: str = Storm) -> dict[str, Any]:
    """Full run payload: track, hazard layers, scored assets, advisories."""
    stored = load_run(storm, lead)
    # Approval state is added to copies; the cached run is never modified.
    # The forecast does not depend on the audit log: if the log cannot be
    # read, the run is served with approval state unknown (None), and says so.
    try:
        standing = audit_log().current_many([a["identifier"] for a in stored["advisories"]])
    except STORAGE_ERRORS as exc:
        LOG.error("audit log unreadable while serving %s/%s: %r", storm, lead, exc)
        return dict(stored, approvals_unavailable=(
                        "The approval record cannot be read on this server, so whether "
                        "these advisories are approved is unknown."),
                    advisories=[dict(adv, approved=None, approved_by=None, approved_at=None)
                                for adv in stored["advisories"]])
    advisories: list[dict[str, Any]] = []
    for adv in stored["advisories"]:
        state = standing.get(adv["identifier"])
        advisories.append(dict(adv, approved=bool(state),
                               approved_by=state["operator"] if state else None,
                               approved_at=state["at"] if state else None))
    return dict(stored, advisories=advisories)


@app.post("/api/advisory/{identifier}/approve", dependencies=OPERATOR_ONLY)
def approve(identifier: str, req: OperatorAction, request: Request) -> Approval:
    """Record a named operator's approval.

    The human gate. Nothing reaches a dispatch channel without passing
    through here, and the operator's name is attached to the decision.
    """
    advisory = find_advisory(identifier)
    # Signed in: the verified account. Otherwise the name the officer gave.
    officer = access.officer_of(request)
    operator = officer.label if officer else named(req)
    event = audit_log().record(identifier, "approve", operator, req.note,
                         advisory["recipient"], advisory["severity"])
    return Approval(identifier=identifier, approved=True, operator=operator, note=req.note,
                    at=str(event["at"]))


@app.post("/api/advisory/{identifier}/revoke", dependencies=OPERATOR_ONLY)
def revoke(identifier: str, req: OperatorAction, request: Request) -> Withdrawal:
    """Withdraw an approval. Named, like the approval it withdraws: an
    anonymous revocation would leave a gap in the record it exists to keep."""
    advisory = find_advisory(identifier)
    # Signed in: the verified account. Otherwise the name the officer gave.
    officer = access.officer_of(request)
    operator = officer.label if officer else named(req)
    # Withdrawing nothing is refused, not logged: a revocation row with no
    # approval before it would read as an approval that was never recorded.
    if audit_log().withdraw(identifier, operator, req.note, recipient=advisory["recipient"],
                            severity=advisory["severity"]) is None:
        raise HTTPException(409, "No standing approval to withdraw; it may already have been")
    return Withdrawal(identifier=identifier, approved=False, operator=operator)


@app.get("/api/advisory/{storm}/{lead}/{identifier}/cap.xml")
def cap_xml(lead: int, identifier: str, storm: str = Storm) -> Response:
    """The CAP 1.2 XML document, as SACHET would ingest it."""
    data = load_run(storm, lead)
    for adv in data["advisories"]:
        if adv["identifier"] == identifier:
            return Response(adv["cap_xml"], media_type="application/xml")
    raise HTTPException(404, f"No advisory {identifier} in this run")


@app.post("/api/advisory/{storm}/{lead}/{identifier}/dispatch", dependencies=OPERATOR_ONLY)
def dispatch(request: Request, lead: int, identifier: str, storm: str = Storm,
             req: Dispatcher | None = None) -> DispatchReceipt:
    """Hand an approved advisory to the delivery channel.

    Stops short of actually sending. Feeding SACHET is a privileged,
    irreversible act that belongs to an accountable authority, and this is a
    demonstration -- so the endpoint proves the gate works and returns the
    payload that WOULD be sent.
    """
    data = load_run(storm, lead)
    adv = next((a for a in data["advisories"] if a["identifier"] == identifier), None)
    if adv is None:
        raise HTTPException(404, f"No advisory {identifier} in this run")

    # The actor is whoever dispatches, if they say; the approver goes in the
    # note. Recording the approver as the actor misattributed the dispatch.
    officer = access.officer_of(request)
    actor = officer.label if officer else (req.operator if req and req.operator else None)
    # Checked and recorded in one step, so a withdrawal cannot land between.
    # Refusals are recorded too: an attempt to send something unapproved is
    # exactly what an audit trail exists to show.
    approval = audit_log().dispatch(identifier, actor, recipient=adv["recipient"],
                                    severity=adv["severity"])
    if approval is None:
        raise HTTPException(
            409, "Advisory is not approved. A named operator must approve it first."
        )

    return DispatchReceipt(
        dispatched=False,
        reason="Exercise mode. Real dispatch requires an authorised SACHET "
               "gateway credential and IMD concurrence.",
        would_send_to=adv["recipient"],
        channels=["SACHET CAP gateway", "SMS", "cell broadcast"],
        languages=adv["languages"],
        approved_by=approval["operator"],
        dispatched_by=actor,
        cap_status="Exercise",
        payload_bytes=len(adv["cap_xml"]),
    )


@app.get("/api/audit", dependencies=OPERATOR_READ)
def audit(identifier: str | None = None) -> list[dict[str, Any]]:
    """The approval and dispatch history, newest first when unfiltered."""
    return audit_log().history(identifier)


@app.post("/api/telemetry", dependencies=INGEST_ONLY)
def ingest_telemetry(body: dict[str, Any]) -> dict[str, Any]:
    """One node observation: validated, quality-checked, stored.

    Returns the QC verdict. A flagged reading is still stored -- it is the
    evidence for that node's maintenance ticket -- but is not fusable.
    """
    try:
        return telemetry_store().ingest(body)
    except ValidationError as exc:
        raise HTTPException(422, f"Not a valid observation: {exc}") from exc
    except UnknownNode as exc:
        raise HTTPException(403, str(exc)) from exc
    except DuplicateObservation as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/api/telemetry/nodes", dependencies=OPERATOR_READ)
def telemetry_nodes() -> list[dict[str, Any]]:
    """Latest reading per node, with its flag history."""
    return telemetry_store().nodes()


@app.get("/api/telemetry/report/{storm}")
def telemetry_report(storm: str = Storm) -> dict[str, Any]:
    """The saved report from a simulated network run for a storm."""
    path = ROOT / "data" / "telemetry" / f"{storm.lower()}_report.json"
    if not path.exists():
        raise HTTPException(404, f"No network simulation for {storm}. "
                                 f"Run: python -m telemetry.simulate {storm.upper()} <year>")
    try:
        report: object = json.loads(path.read_text())
    except ValueError as exc:
        raise HTTPException(503, f"The network report for {storm} cannot be read "
                                 f"({type(exc).__name__}); regenerate it") from exc
    if not isinstance(report, dict):
        raise HTTPException(503, f"The network report for {storm} is not a report; regenerate it")
    return cast(dict[str, Any], report)


@app.get("/api/health")
def health() -> Health:
    """Liveness, plus whether writes are protected -- so an open deployment
    is visible rather than discovered."""
    audit_path = os.environ.get("BOB_AUDIT_DB", str(ROOT / "data" / "audit.sqlite3"))
    in_file = os.environ.get("BOB_AUDIT_STORE", "sqlite") != "bigquery"
    # Configuration that will make a route fail, reported here rather than
    # found by the first gateway to post.
    problems = [p for p in (registry_problem(os.environ.get("BOB_NODE_REGISTRY")),
                            access.code_problem(access.OPERATOR),
                            access.code_problem(access.INGEST),
                            *identity.problems(),
                            audit_store_problem()) if p]
    readable, run_problems = run_status()          # one pass over the run files
    problems += access.write_problems() + access.SETTING_PROBLEMS
    problems += store_problems() + run_problems
    # Whether approvals survive a restart, not where they are kept: the path
    # is nobody's business but the operator's.
    return Health(ok=not problems, problems=problems, runs=len(readable),
                  writes={"operator": access.mode(access.OPERATOR),
                          "telemetry": access.mode(access.INGEST)},
                  # On Cloud Run, /tmp is memory: approvals kept in a file there
                  # vanish when the instance does. Said here so it is known, not
                  # discovered. In BigQuery they outlive it.
                  audit_log={"ephemeral": in_file and access.managed_platform()
                                          and audit_path.startswith(CLOUD_RUN_MEMORY_DIR),
                             "bigquery": not in_file})


#: Cloud Run's only writable directory, which is memory: a file there goes
#: with the instance. Named here to recognise a path under it, not to use it.
CLOUD_RUN_MEMORY_DIR = "/tmp"  # noqa: S108 - compared against, never written to


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(WEB / "index.html")


if WEB.exists():
    app.mount("/static", StaticFiles(directory=WEB), name="static")

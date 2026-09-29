"""The approval and dispatch audit trail, kept in BigQuery.

The SQLite log (api/audit.py) lives on the machine that runs the server. On
Cloud Run that is /tmp, which is memory: every approval went with the
instance. This keeps the same append-only trail in a BigQuery table, within
BigQuery's free tier -- no billing account is needed:

- Each event is appended by a batch load job. Load jobs are free in every
  tier, including the sandbox, which refuses DML and streaming inserts. One
  takes a few seconds; an approval is a deliberate act, and it is reported as
  recorded only once BigQuery has it.
- The trail is read once, when the server starts, with tabledata.list, which
  is free and runs no query. After that, standing approvals are answered from
  memory, and each new event joins it only after BigQuery has accepted it.
- Checking for an approval and recording a dispatch or a withdrawal is one
  step under this process's lock, as in the SQLite log. That holds because
  there is one writer: the deploy command caps Cloud Run at one instance.
- In the sandbox a table expires at most 60 days ahead, and no expiry can be
  set further out. The server moves it forward when it starts and at most
  once a day after that. A deployment that does not run for 60 days loses the
  table; with billing enabled, scripts/bigquery_setup.py removes the expiry.

Selected with BOB_AUDIT_STORE=bigquery and BOB_BQ_AUDIT_TABLE=project.dataset.table.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, cast

from common.errors import reraise_bugs

LOG = logging.getLogger("bob.audit")

API = "https://bigquery.googleapis.com/bigquery/v2"
UPLOAD = "https://bigquery.googleapis.com/upload/bigquery/v2"
SCOPE = "https://www.googleapis.com/auth/bigquery"

ACTIONS = ("approve", "revoke", "dispatch_allowed", "dispatch_refused")

#: The table's columns. `seq` orders the trail, as the SQLite log's id does;
#: `event_id` names each event, and its load job, uniquely.
SCHEMA: list[dict[str, str]] = [
    {"name": "seq", "type": "INTEGER", "mode": "REQUIRED",
     "description": "Order of the event in the trail, from 1"},
    {"name": "recorded_at", "type": "TIMESTAMP", "mode": "REQUIRED"},
    {"name": "identifier", "type": "STRING", "mode": "REQUIRED",
     "description": "The advisory's identifier, content fingerprint included"},
    {"name": "action", "type": "STRING", "mode": "REQUIRED",
     "description": "approve, revoke, dispatch_allowed or dispatch_refused"},
    {"name": "operator", "type": "STRING", "mode": "NULLABLE"},
    {"name": "note", "type": "STRING", "mode": "NULLABLE"},
    {"name": "recipient", "type": "STRING", "mode": "NULLABLE"},
    {"name": "severity", "type": "STRING", "mode": "NULLABLE"},
    {"name": "event_id", "type": "STRING", "mode": "REQUIRED"},
]

#: How long one call, and one load job, may take before the write is refused.
TIMEOUT_S = 30.0
JOB_DEADLINE_S = 90.0
#: The sandbox refuses an expiry 60 or more days ahead.
EXPIRY_AHEAD = timedelta(days=59)
#: Move the expiry forward once fewer than this many days remain.
EXPIRY_REFRESH_BELOW = timedelta(days=50)


class BigQueryError(OSError):
    """BigQuery could not be reached, or refused. An OSError, so the API
    answers it as it does any unusable store: a 503 saying nothing was
    recorded, and /api/health naming the store."""


class Response(Protocol):
    status_code: int
    content: bytes

    def json(self) -> Any: ...


class Session(Protocol):
    """What this needs of an authorised HTTP session (google-auth's
    AuthorizedSession, or a stand-in in the tests)."""

    def request(self, method: str, url: str, **kwargs: Any) -> Response: ...


class Table:
    """One BigQuery table, over the REST API."""

    def __init__(self, table_id: str, session: Session,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        parts = table_id.split(".")
        if len(parts) != 3 or not all(parts):
            raise ValueError(f"expected project.dataset.table, not {table_id!r}")
        self.project, self.dataset, self.table = parts
        self.session = session
        self._sleep = sleep
        self.location: str | None = None
        self._base = f"{API}/projects/{self.project}/datasets/{self.dataset}/tables"

    def _call(self, what: str, method: str, url: str, ok: tuple[int, ...] = (200,),
              **kwargs: Any) -> tuple[int, dict[str, Any]]:
        try:
            r = self.session.request(method, url, timeout=TIMEOUT_S, **kwargs)
            body: object = r.json() if r.content else {}
        except Exception as exc:  # noqa: BLE001 - transport, auth and decode failures
            reraise_bugs(exc)
            raise BigQueryError(
                f"BigQuery unreachable while {what} ({type(exc).__name__})") from exc
        reply = cast(dict[str, Any], body) if isinstance(body, dict) else {}
        if r.status_code not in ok:
            error = cast(dict[str, Any], reply.get("error") or {})
            raise BigQueryError(f"BigQuery refused {what}: {r.status_code} "
                                f"{error.get('status', '')} {str(error.get('message', ''))[:200]}")
        return r.status_code, reply

    def get(self) -> dict[str, Any] | None:
        """The table's metadata, or None if it does not exist."""
        status, info = self._call("reading the table", "GET", f"{self._base}/{self.table}",
                                  ok=(200, 404))
        if status == 404:
            return None
        self.location = info.get("location") or self.location
        return info

    def create(self, description: str = "") -> dict[str, Any]:
        _, info = self._call("creating the table", "POST", self._base, json={
            "tableReference": {"projectId": self.project, "datasetId": self.dataset,
                               "tableId": self.table},
            "schema": {"fields": SCHEMA}, "description": description})
        self.location = info.get("location") or self.location
        return info

    def ensure_dataset(self, location: str, description: str) -> bool:
        """Create the table's dataset if it does not exist; True if created."""
        datasets = f"{API}/projects/{self.project}/datasets"
        status, _ = self._call("reading the dataset", "GET", f"{datasets}/{self.dataset}",
                               ok=(200, 404))
        if status == 200:
            return False
        self._call("creating the dataset", "POST", datasets, json={
            "datasetReference": {"projectId": self.project, "datasetId": self.dataset},
            "location": location, "description": description})
        return True

    def clear_expiry(self) -> None:
        """Remove the table's expiry. BigQuery allows it only with billing."""
        self._call("removing the table's expiry", "PATCH", f"{self._base}/{self.table}",
                   json={"expirationTime": None})

    def delete(self) -> None:
        self._call("deleting the table", "DELETE", f"{self._base}/{self.table}", ok=(200, 204, 404))

    def rows(self) -> list[dict[str, Any]]:
        """Every row, by column name. tabledata.list is free and runs no query."""
        names = [f["name"] for f in SCHEMA]
        out: list[dict[str, Any]] = []
        token: str | None = None
        while True:
            # Timestamps as whole microseconds: exact, where the default
            # float in scientific notation is not.
            params = {"maxResults": "10000", "formatOptions.useInt64Timestamp": "true",
                      **({"pageToken": token} if token else {})}
            _, page = self._call("reading the trail", "GET", f"{self._base}/{self.table}/data",
                                 params=params)
            for row in cast(list[dict[str, Any]], page.get("rows") or []):
                cells = cast(list[dict[str, Any]], row["f"])
                out.append({n: c.get("v") for n, c in zip(names, cells, strict=True)})
            token = page.get("pageToken")
            if not token:
                return out

    def append(self, rows: list[dict[str, Any]], job_id: str) -> None:
        """Append rows with a load job and wait until BigQuery has them.

        The job's id is chosen here, so a submission that is repeated after a
        dropped connection finds the first job rather than adding the rows twice.
        """
        meta = {"jobReference": {"projectId": self.project, "jobId": job_id,
                                 **({"location": self.location} if self.location else {})},
                "configuration": {"load": {
                    "destinationTable": {"projectId": self.project, "datasetId": self.dataset,
                                         "tableId": self.table},
                    "sourceFormat": "NEWLINE_DELIMITED_JSON", "writeDisposition": "WRITE_APPEND",
                    "createDisposition": "CREATE_NEVER"}}}
        ndjson = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
        boundary = f"bob-{uuid.uuid4().hex}"
        body = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"
                f"{json.dumps(meta)}\r\n--{boundary}\r\n"
                f"Content-Type: application/octet-stream\r\n\r\n{ndjson}\r\n--{boundary}--\r\n")
        url = f"{UPLOAD}/projects/{self.project}/jobs"
        upload: dict[str, Any] = {
            "params": {"uploadType": "multipart"}, "data": body.encode(),
            "headers": {"Content-Type": f"multipart/related; boundary={boundary}"}}
        try:
            _, job = self._call("appending to the trail", "POST", url, **upload)
        except BigQueryError:
            # Sent once more with the same job id: if the first arrived, this
            # is refused as a duplicate and the first job is followed instead.
            status, job = self._call("appending to the trail", "POST", url, ok=(200, 409),
                                     **upload)
            if status == 409:
                job = {}
        self._wait(job_id, job)

    def _wait(self, job_id: str, job: dict[str, Any]) -> None:
        deadline = time.monotonic() + JOB_DEADLINE_S
        params = {"location": self.location} if self.location else {}
        while cast(dict[str, Any], job.get("status") or {}).get("state") != "DONE":
            if time.monotonic() > deadline:
                raise BigQueryError(f"BigQuery did not finish job {job_id} in time; "
                                    "the event may yet be recorded")
            self._sleep(0.5)
            _, job = self._call("waiting for the append", "GET",
                                f"{API}/projects/{self.project}/jobs/{job_id}", params=params)
        failed = cast(dict[str, Any], job["status"]).get("errorResult")
        if failed:
            message = str(cast(dict[str, Any], failed).get("message", ""))[:200]
            raise BigQueryError(f"BigQuery refused the append: {message}")

    def keep_alive(self, now: datetime) -> datetime | None:
        """Move a sandbox expiry forward; return when the table now expires."""
        info = self.get()
        if info is None:
            raise BigQueryError("the audit table no longer exists; it may have expired")
        expires = info.get("expirationTime")
        if expires is None:
            return None                     # no expiry: billing is enabled
        when = datetime.fromtimestamp(int(expires) / 1000, UTC)
        if when - now < EXPIRY_REFRESH_BELOW:
            when = now + EXPIRY_AHEAD
            self._call("moving the table's expiry", "PATCH", f"{self._base}/{self.table}",
                       json={"expirationTime": str(int(when.timestamp() * 1000))})
            LOG.info("audit table expiry moved to %s", when.isoformat(timespec="minutes"))
        return when


def _event(row: dict[str, Any]) -> dict[str, Any]:
    """A table row as the SQLite log returns an event."""
    at = datetime.fromtimestamp(int(row["recorded_at"]) / 1_000_000, UTC).isoformat(
        timespec="seconds")
    return {"id": int(row["seq"]), "at": at, "identifier": row["identifier"],
            "action": row["action"], "operator": row["operator"], "note": row["note"],
            "recipient": row["recipient"], "severity": row["severity"]}


class BigQueryAuditLog:
    """The audit trail in BigQuery, with the SQLite log's interface and rules:
    append-only, and approval state derived from the trail itself."""

    def __init__(self, table: Table, clock: Callable[[], datetime] = lambda: datetime.now(UTC)
                 ) -> None:
        self._table = table
        self._clock = clock
        self._lock = threading.RLock()
        self._events: list[dict[str, Any]] = []
        self._by_id: dict[str, list[dict[str, Any]]] = {}
        self._expiry_checked: datetime | None = None
        self.expires: datetime | None = None
        if table.get() is None:
            table.create("Bay of Bengal cyclone forecaster: every approval, withdrawal and "
                         "dispatch attempt, append-only")
        for event in sorted((_event(r) for r in table.rows()), key=lambda e: e["id"]):
            self._remember(event)
        self._keep_alive()

    def _remember(self, event: dict[str, Any]) -> None:
        self._events.append(event)
        self._by_id.setdefault(event["identifier"], []).append(event)

    def _keep_alive(self) -> None:
        now = self._clock()
        if self._expiry_checked and now - self._expiry_checked < timedelta(days=1):
            return
        self.expires = self._table.keep_alive(now)
        self._expiry_checked = now

    def record(self, identifier: str, action: str, operator: str | None = None,
               note: str = "", recipient: str = "", severity: str = "") -> dict[str, Any]:
        if action not in ACTIONS:
            raise ValueError(f"not an audit action: {action!r}")
        with self._lock:
            now = self._clock()
            event_id = uuid.uuid4().hex
            seq = self._events[-1]["id"] + 1 if self._events else 1
            self._table.append([{
                "seq": seq, "recorded_at": now.isoformat(timespec="seconds"),
                "identifier": identifier, "action": action, "operator": operator,
                "note": note, "recipient": recipient, "severity": severity,
                "event_id": event_id}], job_id=f"bob_audit_{event_id}")
            at = now.replace(microsecond=0).isoformat()
            self._remember({"id": seq, "at": at, "identifier": identifier, "action": action,
                            "operator": operator, "note": note, "recipient": recipient,
                            "severity": severity})
            try:
                self._keep_alive()
            except BigQueryError as exc:
                # The event is recorded; the expiry is retried on the next write.
                LOG.error("audit table expiry not moved: %s", exc)
        return {"at": at, "identifier": identifier, "action": action, "operator": operator}

    def withdraw(self, identifier: str, operator: str, note: str = "",
                 recipient: str = "", severity: str = "") -> dict[str, Any] | None:
        """Record a revocation if an approval stands, else record nothing."""
        with self._lock:
            if self.current(identifier) is None:
                return None
            return self.record(identifier, "revoke", operator, note, recipient, severity)

    def dispatch(self, identifier: str, actor: str | None, recipient: str = "",
                 severity: str = "") -> dict[str, Any] | None:
        """Check for a standing approval and record the attempt, as one step."""
        with self._lock:
            approval = self.current(identifier)
            if approval is None:
                self.record(identifier, "dispatch_refused", actor,
                            recipient=recipient, severity=severity)
            else:
                self.record(identifier, "dispatch_allowed", actor,
                            f"approved by {approval['operator']}",
                            recipient=recipient, severity=severity)
            return approval

    def probe(self) -> None:
        """Raise if the table cannot be reached, or is gone."""
        if self._table.get() is None:
            raise BigQueryError("the audit table no longer exists; it may have expired")

    def current(self, identifier: str) -> dict[str, Any] | None:
        with self._lock:
            decisions = [e for e in self._by_id.get(identifier, [])
                         if e["action"] in ("approve", "revoke")]
        if not decisions or decisions[-1]["action"] == "revoke":
            return None
        last = decisions[-1]
        return {"operator": last["operator"], "note": last["note"], "at": last["at"]}

    def current_many(self, identifiers: list[str]) -> dict[str, dict[str, Any]]:
        standing = {i: self.current(i) for i in identifiers}
        return {i: s for i, s in standing.items() if s is not None}

    def history(self, identifier: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            if identifier:
                return [dict(e) for e in self._by_id.get(identifier, [])]
            return [dict(e) for e in reversed(self._events[-200:])]


def credentials() -> Any:
    """Google credentials for BigQuery.

    On Cloud Run, the service's own identity (Application Default
    Credentials). On a developer's machine without those, the Earth Engine
    sign-in, when it carries the cloud-platform scope.
    """
    import importlib

    from google.auth.exceptions import DefaultCredentialsError

    # google-auth leaves its credential types unannotated: Any, said once here.
    google_auth: Any = importlib.import_module("google.auth")
    try:
        return google_auth.default(scopes=[SCOPE])[0]
    except DefaultCredentialsError:
        pass
    try:
        # A developer's machine only: the serving image has no Earth Engine.
        ee_data: Any = importlib.import_module("ee.data")
        return ee_data.get_persistent_credentials()
    except Exception as exc:  # noqa: BLE001 - not installed, or not signed in
        reraise_bugs(exc)
        raise BigQueryError("no Google credentials for BigQuery: run on Cloud Run with a "
                            "service account, or sign in with `earthengine authenticate`") from exc


def authorised_session() -> Session:
    """An HTTP session that signs its requests with `credentials()`."""
    from google.auth.transport.requests import AuthorizedSession

    return cast(Session, AuthorizedSession(credentials()))


def open_log(table_id: str) -> BigQueryAuditLog:
    """The audit trail in `table_id` (project.dataset.table), read and ready."""
    return BigQueryAuditLog(Table(table_id, authorised_session()))

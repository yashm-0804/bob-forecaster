"""The audit trail kept in BigQuery (api/bigquery_audit.py).

The same rules as the SQLite log, checked against both: a stand-in for
BigQuery's REST API serves the unit tests, and one opt-in test runs against
the real service (BOB_NETWORK_TESTS=1, BOB_BQ_TEST_DATASET=project.dataset)."""

import json
import os
import re
import threading
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from api import bigquery_audit as bq
from api.audit import AuditLog


class FakeResponse:
    def __init__(self, status, body=None):
        self.status_code = status
        self.content = json.dumps(body).encode() if body is not None else b""
        self._body = body

    def json(self):
        return self._body


class FakeBigQuery:
    """BigQuery's REST API for one project, as far as the audit log uses it:
    tables, multipart load jobs, jobs.get and tabledata.list, with its value
    encoding (every cell a string; TIMESTAMP as seconds since the epoch)."""

    def __init__(self, page_size=3, sandbox=True):
        self.tables = {}          # (dataset, table) -> {"rows": [...], "meta": {...}}
        self.datasets = {}        # dataset -> location
        self.jobs = {}
        self.page_size = page_size
        self.sandbox = sandbox
        self.fail_next_load = None    # an errorResult message for the next load job
        self.running_polls = 0        # jobs.get answers RUNNING this many times first
        self.calls = []
        self.lock = threading.Lock()

    def request(self, method, url, params=None, json=None, data=None, headers=None, timeout=None,
                **other):
        with self.lock:
            return self._handle(method, url, params or {}, json, data)

    def _handle(self, method, url, params, body, data):
        u = urlsplit(url)
        params = {**params, **{k: v[0] for k, v in parse_qs(u.query).items()}}
        self.calls.append((method, u.path))
        d = re.fullmatch(r"/bigquery/v2/projects/[^/]+/datasets(?:/([^/]+))?", u.path)
        if d:
            if method == "POST":
                self.datasets[body["datasetReference"]["datasetId"]] = body["location"]
                return FakeResponse(200, body)
            if d[1] in self.datasets:
                return FakeResponse(200, {"location": self.datasets[d[1]]})
            return FakeResponse(404, {"error": {"status": "NOT_FOUND", "message": "Not found"}})
        m = re.fullmatch(r"/bigquery/v2/projects/[^/]+/datasets/([^/]+)/tables(?:/([^/]+))?(/data)?",
                         u.path)
        if m:
            key = (m[1], m[2])
            if method == "POST":
                key = (m[1], body["tableReference"]["tableId"])
                expires = datetime.now(UTC) + timedelta(days=60) if self.sandbox else None
                self.tables[key] = {"rows": [], "meta": {
                    "location": "asia-south1", "schema": body["schema"],
                    "expirationTime": str(int(expires.timestamp() * 1000)) if expires else None}}
                return FakeResponse(200, self._meta(key))
            if key not in self.tables:
                return FakeResponse(404, {"error": {"status": "NOT_FOUND", "message": "Not found"}})
            if method == "GET" and m[3]:
                assert params.get("formatOptions.useInt64Timestamp") == "true", "exact timestamps"
                rows = self.tables[key]["rows"]
                start = int(params.get("pageToken", 0))
                page = rows[start:start + self.page_size]
                out = {"totalRows": str(len(rows)), "rows": page}
                if start + self.page_size < len(rows):
                    out["pageToken"] = str(start + self.page_size)
                return FakeResponse(200, out)
            if method == "GET":
                return FakeResponse(200, self._meta(key))
            if method == "PATCH":
                wanted = body["expirationTime"]
                if self.sandbox and (wanted is None or int(wanted) / 1000 - datetime.now(UTC).timestamp()
                                     >= 60 * 86400):
                    return FakeResponse(403, {"error": {"status": "PERMISSION_DENIED", "message":
                        "Table expiration time must be less than 60 days while in sandbox mode."}})
                self.tables[key]["meta"]["expirationTime"] = wanted
                return FakeResponse(200, self._meta(key))
            if method == "DELETE":
                del self.tables[key]
                return FakeResponse(204)
        if u.path.startswith("/upload/bigquery/v2/projects/") and method == "POST":
            return self._load(data)
        m = re.fullmatch(r"/bigquery/v2/projects/[^/]+/jobs/([^/]+)", u.path)
        if m and method == "GET":
            job = self.jobs[m[1]]
            if self.running_polls:
                self.running_polls -= 1
                return FakeResponse(200, {**job, "status": {"state": "RUNNING"}})
            return FakeResponse(200, job)
        return FakeResponse(400, {"error": {"status": "INVALID", "message": f"unexpected {method} {url}"}})

    def _meta(self, key):
        meta = dict(self.tables[key]["meta"])
        if meta["expirationTime"] is None:
            del meta["expirationTime"]
        return {**meta, "tableReference": {"datasetId": key[0], "tableId": key[1]}}

    def _load(self, data):
        text = data.decode()
        boundary = text.split("\r\n", 1)[0]
        parts = [p for p in text.split(boundary) if p.strip() and p.strip() != "--"]
        meta = json.loads(parts[0].split("\r\n\r\n", 1)[1])
        ndjson = parts[1].split("\r\n\r\n", 1)[1]
        job_id = meta["jobReference"]["jobId"]
        if job_id in self.jobs:
            return FakeResponse(409, {"error": {"status": "ALREADY_EXISTS", "message": "duplicate"}})
        dest = meta["configuration"]["load"]["destinationTable"]
        table = self.tables[(dest["datasetId"], dest["tableId"])]
        if self.fail_next_load:
            self.jobs[job_id] = {"status": {"state": "DONE", "errorResult": {"message": self.fail_next_load}}}
            self.fail_next_load = None
            return FakeResponse(200, self.jobs[job_id])
        names = [f["name"] for f in table["meta"]["schema"]["fields"]]
        for line in ndjson.strip().splitlines():
            row = json.loads(line)
            micros = int(datetime.fromisoformat(row["recorded_at"]).timestamp() * 1_000_000)
            cells = {**row, "recorded_at": str(micros), "seq": str(row["seq"])}
            table["rows"].append({"f": [{"v": cells.get(n)} for n in names]})
        self.jobs[job_id] = {"status": {"state": "DONE"}}
        if self.running_polls:
            return FakeResponse(200, {"status": {"state": "RUNNING"}})
        return FakeResponse(200, self.jobs[job_id])


TABLE = "proj.bob_forecaster.audit_events"


@pytest.fixture
def backend():
    return FakeBigQuery()


def bigquery_log(backend):
    return bq.BigQueryAuditLog(bq.Table(TABLE, backend, sleep=lambda s: None))


@pytest.fixture(params=["sqlite", "bigquery"])
def log(request, tmp_path, backend):
    return AuditLog(tmp_path / "audit.sqlite3") if request.param == "sqlite" else bigquery_log(backend)


# --- the same rules, both stores ------------------------------------------------

def test_an_approval_stands_until_it_is_withdrawn(log):
    assert log.current("A") is None
    log.record("A", "approve", "K. Ramesh", "checked", "Health", "red")
    assert log.current("A")["operator"] == "K. Ramesh"
    assert log.withdraw("A", "S. Das")["action"] == "revoke"
    assert log.current("A") is None
    assert log.withdraw("A", "S. Das") is None, "withdrawing nothing records nothing"
    assert [e["action"] for e in log.history("A")] == ["approve", "revoke"]


def test_dispatch_is_recorded_whether_allowed_or_refused(log):
    assert log.dispatch("A", "P. Rao") is None
    log.record("A", "approve", "K. Ramesh")
    assert log.dispatch("A", "P. Rao")["operator"] == "K. Ramesh"
    events = log.history("A")
    assert [e["action"] for e in events] == ["dispatch_refused", "approve", "dispatch_allowed"]
    assert events[-1]["note"] == "approved by K. Ramesh" and events[-1]["operator"] == "P. Rao"
    assert [e["id"] for e in events] == sorted(e["id"] for e in events)


def test_standing_approvals_many_at_once_and_newest_history_first(log):
    log.record("A", "approve", "K. Ramesh")
    log.record("B", "approve", "K. Ramesh")
    log.record("B", "revoke", "S. Das")
    assert set(log.current_many(["A", "B", "C"])) == {"A"}
    assert [e["identifier"] for e in log.history()][:3] == ["B", "B", "A"]
    assert set(log.history()[0]) == {"id", "at", "identifier", "action", "operator",
                                     "note", "recipient", "severity"}


def test_a_dispatch_and_a_withdrawal_at_once_never_dispatch_after_the_withdrawal(log):
    for trial in range(10):
        ident = f"R{trial}"
        log.record(ident, "approve", "K. Ramesh")
        barrier = threading.Barrier(2)
        threads = [
            threading.Thread(target=lambda b=barrier, i=ident: (b.wait(), log.dispatch(i, "P. Rao"))),
            threading.Thread(target=lambda b=barrier, i=ident: (b.wait(), log.withdraw(i, "S. Das")))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        actions = [e["action"] for e in log.history(ident)]
        assert actions in (["approve", "dispatch_allowed", "revoke"],
                           ["approve", "revoke", "dispatch_refused"]), actions


# --- BigQuery only ----------------------------------------------------------------

def test_the_trail_survives_a_restart(backend):
    first = bigquery_log(backend)
    first.record("A", "approve", "K. Ramesh", "checked", "Health", "red")
    for i in range(4):                               # more than one page of rows
        first.record(f"X{i}", "dispatch_refused", "P. Rao")
    restarted = bigquery_log(backend)
    assert restarted.current("A") == first.current("A")
    assert restarted.history() == first.history()
    assert any(p.endswith("/data") for _, p in backend.calls), "read with tabledata.list"
    restarted.record("A", "revoke", "S. Das")
    assert restarted.history("A")[-1]["id"] == 6, "numbering carries on"


def test_nothing_is_recorded_when_bigquery_refuses_the_write(backend):
    log = bigquery_log(backend)
    backend.fail_next_load = "Quota exceeded: table modifications per day"
    with pytest.raises(bq.BigQueryError, match="Quota exceeded"):
        log.record("A", "approve", "K. Ramesh")
    assert log.current("A") is None and log.history("A") == []
    assert bigquery_log(backend).history() == []


def test_an_append_waits_until_bigquery_has_it(backend):
    log = bigquery_log(backend)
    backend.running_polls = 3
    log.record("A", "approve", "K. Ramesh")
    assert backend.running_polls == 0 and log.current("A") is not None


def test_a_resubmitted_append_follows_the_first_job_instead_of_adding_twice(backend):
    table = bq.Table(TABLE, backend, sleep=lambda s: None)
    table.create()
    row = {"seq": 1, "recorded_at": "2026-09-29T00:00:00+00:00", "identifier": "A",
           "action": "approve", "operator": "K. Ramesh", "note": "", "recipient": "",
           "severity": "", "event_id": "e1"}
    table.append([row], job_id="job-1")
    real = backend.request
    dropped = {"n": 0}

    def drop_first_reply(method, url, **kw):        # the job arrives; its reply does not
        reply = real(method, url, **kw)
        if "/upload/" in url and dropped["n"] == 0:
            dropped["n"] += 1
            raise ConnectionError("connection reset")
        return reply

    backend.request = drop_first_reply
    table.append([{**row, "seq": 2, "event_id": "e2"}], job_id="job-2")
    assert [r["seq"] for r in table.rows()] == ["1", "2"], "the second row once, not twice"


def test_the_sandbox_expiry_is_moved_forward_and_billing_leaves_none(backend):
    now = datetime.now(UTC)
    log = bigquery_log(backend)
    assert log.expires and log.expires - now > timedelta(days=58)
    meta = backend.tables[("bob_forecaster", "audit_events")]["meta"]
    meta["expirationTime"] = str(int((now + timedelta(days=10)).timestamp() * 1000))
    moved = bq.BigQueryAuditLog(bq.Table(TABLE, backend), clock=lambda: now)
    assert moved.expires == now + bq.EXPIRY_AHEAD, "within the sandbox's 60 days"
    billed = FakeBigQuery(sandbox=False)
    assert bigquery_log(billed).expires is None


def test_a_table_that_has_gone_is_reported_not_recreated_silently(backend):
    log = bigquery_log(backend)
    del backend.tables[("bob_forecaster", "audit_events")]
    with pytest.raises(bq.BigQueryError, match="no longer exists"):
        log.probe()


def test_an_unreachable_bigquery_is_a_storage_error(backend):
    def down(*a, **k):
        raise ConnectionError("network unreachable")

    backend.request = down
    with pytest.raises(OSError, match="unreachable"):
        bigquery_log(backend)


def test_only_audit_actions_are_recorded(backend):
    with pytest.raises(ValueError, match="not an audit action"):
        bigquery_log(backend).record("A", "delete_everything", "X. Y")


def test_setup_makes_the_dataset_once_and_only_billing_lifts_the_expiry(backend):
    table = bq.Table(TABLE, backend)
    assert table.ensure_dataset("asia-south1", "audit trail") is True
    assert table.ensure_dataset("asia-south1", "audit trail") is False, "left as it is"
    assert backend.datasets == {"bob_forecaster": "asia-south1"}
    table.create()
    with pytest.raises(bq.BigQueryError, match="less than 60 days"):
        table.clear_expiry()                     # the sandbox refuses, and says why
    billed = bq.Table(TABLE, FakeBigQuery(sandbox=False))
    billed.create()
    billed.clear_expiry()
    assert billed.keep_alive(datetime.now(UTC)) is None


def test_without_credentials_the_error_says_how_to_get_them(monkeypatch):
    """No service account and no Earth Engine sign-in: a storage error naming
    both ways to fix it, not a stack trace from inside google-auth."""
    import importlib

    from google.auth.exceptions import DefaultCredentialsError

    class NoDefault:
        @staticmethod
        def default(scopes=None):
            raise DefaultCredentialsError("no credentials found")

    real = importlib.import_module

    def modules(name, *a):
        if name == "google.auth":
            return NoDefault
        if name == "ee.data":
            raise ImportError("No module named 'ee'")
        return real(name, *a)

    monkeypatch.setattr(importlib, "import_module", modules)
    with pytest.raises(OSError, match="service account.*earthengine authenticate"):
        bq.credentials()


# --- through the API ------------------------------------------------------------------

def test_the_api_approves_and_dispatches_through_bigquery(monkeypatch, backend):
    import api.main as main

    monkeypatch.setenv("BOB_AUDIT_STORE", "bigquery")
    monkeypatch.setenv("BOB_BQ_AUDIT_TABLE", TABLE)
    monkeypatch.setattr(main, "_audit", None)
    monkeypatch.setattr(bq, "open_log", lambda table_id: bigquery_log(backend))
    client = TestClient(main.app, base_url="http://localhost")
    ident = client.get("/api/run/montha/48").json()["advisories"][0]["identifier"]
    assert client.post(f"/api/advisory/{ident}/approve", json={"operator": "K. Ramesh"}).status_code == 200
    assert client.post(f"/api/advisory/montha/48/{ident}/dispatch").status_code == 200
    rows = backend.tables[("bob_forecaster", "audit_events")]["rows"]
    assert len(rows) == 2, "both events are in the table"
    health = client.get("/api/health").json()
    assert health["audit_log"] == {"ephemeral": False, "bigquery": True}
    backend.fail_next_load = "backend error"
    r = client.post(f"/api/advisory/{ident}/revoke", json={"operator": "S. Das"})
    assert r.status_code == 503 and "nothing was recorded" in r.json()["detail"]
    served = client.get("/api/run/montha/48").json()["advisories"][0]
    assert served["approved"] is True, "the refused withdrawal changed nothing"


@pytest.mark.parametrize("store, table, problem", [
    ("files", "", "must be one of sqlite, bigquery"),
    ("bigquery", "", "must name project.dataset.table"),
    ("bigquery", "only.two", "must name project.dataset.table"),
])
def test_a_store_setting_that_cannot_work_is_reported_and_refuses_writes(monkeypatch, store, table, problem):
    import api.main as main

    monkeypatch.setenv("BOB_AUDIT_STORE", store)
    monkeypatch.setenv("BOB_BQ_AUDIT_TABLE", table)
    monkeypatch.setattr(main, "_audit", None)
    client = TestClient(main.app, base_url="http://localhost")
    health = client.get("/api/health").json()
    assert health["ok"] is False and any(problem in p for p in health["problems"])
    assert len(health["problems"]) == 1, "said once"
    run = client.get("/api/run/montha/48").json()
    assert "approvals_unavailable" in run, "the forecast is still served"
    ident = run["advisories"][0]["identifier"]
    r = client.post(f"/api/advisory/{ident}/approve", json={"operator": "K. Ramesh"})
    assert r.status_code == 503 and "nothing was recorded" in r.json()["detail"]


# --- the real service -------------------------------------------------------------------

@pytest.mark.network
def test_the_trail_in_real_bigquery_survives_a_restart():
    """Against BigQuery itself, in a table made for the test and deleted after."""
    dataset = os.environ.get("BOB_BQ_TEST_DATASET")
    if not dataset:
        pytest.skip("set BOB_BQ_TEST_DATASET=project.dataset to run against BigQuery")
    session = bq.authorised_session()
    table = bq.Table(f"{dataset}.audit_test_{uuid.uuid4().hex[:12]}", session)
    try:
        log = bq.BigQueryAuditLog(table)
        log.record("LIVE-A", "approve", "K. Ramesh", "live test", "Health", "red")
        allowed = log.dispatch("LIVE-A", "P. Rao")
        assert allowed is not None and allowed["operator"] == "K. Ramesh"
        withdrawn = log.withdraw("LIVE-A", "S. Das")
        assert withdrawn is not None and withdrawn["action"] == "revoke"
        assert log.dispatch("LIVE-A", "P. Rao") is None
        restarted = bq.BigQueryAuditLog(bq.Table(f"{table.project}.{table.dataset}.{table.table}",
                                                 session))
        assert restarted.history("LIVE-A") == log.history("LIVE-A")
        assert [e["action"] for e in restarted.history("LIVE-A")] == [
            "approve", "dispatch_allowed", "revoke", "dispatch_refused"]
        restarted.probe()
    finally:
        table.delete()

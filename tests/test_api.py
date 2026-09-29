"""The HTTP API, and above all the approval gate and its audit trail.

Until this file the gate was only ever exercised by hand with curl.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api.main as main
from api import guard, run_store
from api.audit import AuditLog

RUNS = Path(__file__).resolve().parent.parent / "data" / "runs"


@pytest.fixture
def client(tmp_path, monkeypatch):
    # The replays are committed; their absence is a broken checkout, not a
    # reason to skip the approval-gate tests.
    assert (RUNS / "montha_48h.json").exists(), "data/runs/montha_48h.json is missing"
    monkeypatch.setattr(main, "_audit", AuditLog(tmp_path / "audit.sqlite3"))
    return TestClient(main.app, base_url="http://localhost")


@pytest.fixture
def advisory_id():
    return json.loads((RUNS / "montha_48h.json").read_text())["advisories"][0]["identifier"]


def dispatch(client, ident):
    return client.post(f"/api/advisory/montha/48/{ident}/dispatch")


def test_dispatch_is_refused_until_a_named_operator_approves(client, advisory_id):
    assert dispatch(client, advisory_id).status_code == 409
    r = client.post(f"/api/advisory/{advisory_id}/approve", json={"operator": "K. Ramesh, DDMA"})
    assert r.status_code == 200
    ok = dispatch(client, advisory_id)
    assert ok.status_code == 200
    body = ok.json()
    assert body["dispatched"] is False, "exercise mode never actually sends"
    assert body["cap_status"] == "Exercise"
    assert body["approved_by"] == "K. Ramesh, DDMA"


def test_invalid_approvals_are_rejected(client, advisory_id):
    assert client.post("/api/advisory/FAKE/approve", json={"operator": "Someone"}).status_code == 404
    assert client.post(f"/api/advisory/{advisory_id}/approve", json={"operator": "  "}).status_code == 400
    assert client.post(f"/api/advisory/{advisory_id}/approve", json={"operator": "K"}).status_code == 400


def test_revoking_closes_the_gate_again(client, advisory_id):
    client.post(f"/api/advisory/{advisory_id}/approve", json={"operator": "K. Ramesh"})
    r = client.post(f"/api/advisory/{advisory_id}/revoke", json={"operator": "S. Das, SEOC"})
    assert r.status_code == 200
    assert dispatch(client, advisory_id).status_code == 409


def test_approval_survives_a_restart(tmp_path, advisory_id):
    """Regression: approvals lived in a dict and vanished on restart."""
    db = tmp_path / "audit.sqlite3"
    AuditLog(db).record(advisory_id, "approve", "K. Ramesh")
    state = AuditLog(db).current(advisory_id)
    assert state is not None and state["operator"] == "K. Ramesh"


def test_refused_attempts_are_on_the_record(client, advisory_id):
    """An attempt to send something unapproved is what an audit trail is for."""
    dispatch(client, advisory_id)
    actions = [e["action"] for e in client.get(f"/api/audit?identifier={advisory_id}").json()]
    assert actions == ["dispatch_refused"]


def test_the_log_is_append_only(client, advisory_id):
    for op in ("A. One", "B. Two"):
        client.post(f"/api/advisory/{advisory_id}/approve", json={"operator": op})
    client.post(f"/api/advisory/{advisory_id}/revoke", json={"operator": "C. Three"})
    history = client.get(f"/api/audit?identifier={advisory_id}").json()
    assert [e["action"] for e in history] == ["approve", "approve", "revoke"]
    assert [e["operator"] for e in history] == ["A. One", "B. Two", "C. Three"]


def test_run_payload_reports_standing_approval(client, advisory_id):
    client.post(f"/api/advisory/{advisory_id}/approve", json={"operator": "K. Ramesh"})
    run = client.get("/api/run/montha/48").json()
    adv = next(a for a in run["advisories"] if a["identifier"] == advisory_id)
    assert adv["approved"] and adv["approved_by"] == "K. Ramesh"


def test_unknown_run_explains_how_to_make_one(client):
    r = client.get("/api/run/nosuch/48")
    assert r.status_code == 404 and "pipeline.export" in r.json()["detail"]


# --- who may change state --------------------------------------------------

def test_a_revocation_must_be_named_too(client, advisory_id):
    """An anonymous revocation left a gap in the record it exists to keep."""
    client.post(f"/api/advisory/{advisory_id}/approve", json={"operator": "K. Ramesh"})
    assert client.post(f"/api/advisory/{advisory_id}/revoke").status_code == 422
    assert client.post(f"/api/advisory/{advisory_id}/revoke",
                       json={"operator": " "}).status_code == 400
    assert dispatch(client, advisory_id).status_code == 200, "the approval still stands"


def test_withdrawing_nothing_is_refused_and_not_recorded(client, advisory_id):
    """Found in review: a revoke with no approval standing returned 200 and
    wrote a revocation row."""
    url = f"/api/advisory/{advisory_id}/revoke"
    assert client.post(url, json={"operator": "S. Das"}).status_code == 409
    assert main.audit_log().history(advisory_id) == []
    client.post(f"/api/advisory/{advisory_id}/approve", json={"operator": "K. Ramesh"})
    assert client.post(url, json={"operator": "S. Das"}).status_code == 200
    again = client.post(url, json={"operator": "P. Rao"})
    assert again.status_code == 409 and "already" in again.json()["detail"]
    assert [e["action"] for e in main.audit_log().history(advisory_id)] == ["approve", "revoke"]


def test_two_officers_withdrawing_at_once_leave_one_revocation(tmp_path):
    import threading

    log = AuditLog(tmp_path / "a.sqlite3")
    log.record("A", "approve", "K. Ramesh")
    results = []
    threads = [threading.Thread(target=lambda n=n: results.append(log.withdraw("A", f"Officer {n}")))
               for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(r is not None for r in results) == 1
    assert [e["action"] for e in log.history("A")] == ["approve", "revoke"]


def test_a_dispatch_and_a_withdrawal_at_once_never_record_a_dispatch_after_the_withdrawal(tmp_path):
    """Found in review: dispatch checked the approval, then recorded, with no
    lock between, so a withdrawal could land in the gap and the log show a
    dispatch allowed after its approval was gone. Now the order in the log
    always agrees with the outcome."""
    import threading

    for trial in range(30):
        log = AuditLog(tmp_path / f"race{trial}.sqlite3")
        log.record("A", "approve", "K. Ramesh")
        barrier = threading.Barrier(2)
        results = {}

        def dispatch(log=log, barrier=barrier, results=results):
            barrier.wait()
            results["dispatch"] = log.dispatch("A", "S. Das")

        def withdraw(log=log, barrier=barrier, results=results):
            barrier.wait()
            results["withdraw"] = log.withdraw("A", "P. Rao")

        threads = [threading.Thread(target=dispatch), threading.Thread(target=withdraw)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        actions = [e["action"] for e in log.history("A")]
        assert results["withdraw"] is not None, "the approval stood, so the withdrawal records"
        if results["dispatch"] is None:
            assert actions == ["approve", "revoke", "dispatch_refused"]
        else:
            assert actions == ["approve", "dispatch_allowed", "revoke"]


def minimal_run(ident):
    """The least a run file must hold to be served."""
    return {"summary": {}, "grid": {}, "layers": {}, "track": [], "assets": [],
            "advisories": [{"identifier": ident, "recipient": "Health Department",
                            "severity": "red", "languages": ["en-IN"], "cap_xml": "<alert/>"}]}


@pytest.mark.parametrize("broken", ['{"advisories": [', "", '[1, 2]', '{"summary": {}}',
                                     json.dumps(dict(minimal_run("X"), advisories=[{"identifier": 3}]))])
def test_a_broken_run_file_costs_that_run_not_every_approval(tmp_path, monkeypatch, broken):
    """Found in review: one truncated file named like a run made every
    approval and withdrawal, on every run, a 500, while health said ok."""
    import shutil

    runs = tmp_path / "runs"
    runs.mkdir()
    shutil.copy(RUNS / "montha_48h.json", runs / "montha_48h.json")
    (runs / "fani_48h.json").write_text(broken)
    monkeypatch.setattr(run_store, "RUNS", runs)
    monkeypatch.setattr(main, "_audit", AuditLog(tmp_path / "audit.sqlite3"))
    client = TestClient(main.app, base_url="http://localhost", raise_server_exceptions=False)
    ident = client.get("/api/run/montha/48").json()["advisories"][0]["identifier"]
    assert client.post(f"/api/advisory/{ident}/approve", json={"operator": "K. Ramesh"}).status_code == 200
    assert client.post(f"/api/advisory/montha/48/{ident}/dispatch").status_code == 200
    assert [r["storm"] for r in client.get("/api/runs").json()] == ["montha"], "not offered"
    r = client.get("/api/run/fani/48")
    assert r.status_code == 503 and "fani_48h.json" in r.json()["detail"]
    health = client.get("/api/health").json()
    assert health["ok"] is False and health["runs"] == 1
    assert any(p.startswith("run file fani_48h.json") for p in health["problems"])
    assert str(tmp_path) not in str(health)


def test_the_advisory_index_follows_the_run_files(tmp_path, monkeypatch):
    """Approvals look advisories up in an index rebuilt only when a run file
    changes; a new or rewritten run must be seen at once."""
    import os

    runs = tmp_path / "runs"
    runs.mkdir()
    monkeypatch.setattr(run_store, "RUNS", runs)
    write = lambda name, ident: (runs / name).write_text(json.dumps(minimal_run(ident)))
    write("montha_48h.json", "A-1")
    assert set(run_store.advisory_index()) == {"A-1"}
    write("fani_48h.json", "B-1")
    assert set(run_store.advisory_index()) == {"A-1", "B-1"}
    write("montha_48h.json", "A-2")
    os.utime(runs / "montha_48h.json", ns=(1, 10**18))       # a different mtime, surely
    assert set(run_store.advisory_index()) == {"A-2", "B-1"}
    (runs / "fani_48h.json").unlink()
    assert set(run_store.advisory_index()) == {"A-2"}


@pytest.mark.parametrize("path", ["/api/advisory/X/approve", "/api/telemetry",
                                  "/api/advisory/montha/48/X/dispatch"])
def test_a_body_nested_thousands_deep_is_refused_not_a_500(client, path):
    """Found in review: '['*5000 + ']'*5000, well under the size limit,
    overflowed the recursion of the JSON machinery and gave a 500."""
    r = client.post(path, content="[" * 5000 + "]" * 5000,
                    headers={"Content-Type": "application/json"})
    assert r.status_code == 400 and "nested" in r.json()["detail"]
    deep = '{"a":' * 40 + "1" + "}" * 40
    assert client.post(path, content=deep, headers={"Content-Type": "application/json"}).status_code == 400


def test_brackets_inside_strings_are_not_nesting():
    assert guard.nesting_depth(b'{"note": "[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[["}') == 1
    assert guard.nesting_depth(b'{"note": "a \\" [ \\\" [", "x": [1, [2]]}') == 3
    assert guard.nesting_depth(b"") == 0


def test_a_damaged_network_report_is_a_503_not_a_500(tmp_path, monkeypatch, client):
    reports = tmp_path / "data" / "telemetry"
    reports.mkdir(parents=True)
    (reports / "montha_report.json").write_text('{"nodes": ')
    (reports / "fani_report.json").write_text("[1, 2]")
    monkeypatch.setattr(main, "ROOT", tmp_path)
    for storm in ("montha", "fani"):
        r = client.get(f"/api/telemetry/report/{storm}")
        assert r.status_code == 503 and "regenerate" in r.json()["detail"]


def test_the_vendored_map_library_is_served_as_javascript(client):
    """Module scripts are refused by browsers unless served as JavaScript."""
    for path in ("/static/map-loader.mjs", "/static/vendor/maplibre-gl/maplibre-gl.mjs",
                 "/static/vendor/maplibre-gl/maplibre-gl-shared.mjs",
                 "/static/vendor/maplibre-gl/maplibre-gl-worker.mjs"):
        r = client.get(path)
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/javascript"), path
    assert client.get("/static/vendor/maplibre-gl/maplibre-gl.css").status_code == 200


def test_the_vendored_files_are_the_ones_the_manifest_names():
    import hashlib

    folder = Path(__file__).resolve().parent.parent / "web" / "vendor" / "maplibre-gl"
    manifest = json.loads((folder / "VENDOR.json").read_text())
    assert manifest["version"] == "6.11.2", "6.4.1 or later fixes GHSA-jrc7-96c5-q579"
    on_disk = {f.name for f in folder.iterdir() if f.name != "VENDOR.json"}
    assert on_disk == set(manifest["files"])
    for name, digest in manifest["files"].items():
        assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == digest, name


def test_every_get_route_answers_head_with_no_body(client):
    """Found in review: HEAD / and then HEAD /api/run/... were 405s, which
    uptime checks read as down."""
    for path in ("/", "/api/health", "/api/runs", "/api/run/montha/48", "/static/app.js"):
        get, head = client.get(path), client.head(path)
        assert head.status_code == get.status_code == 200, path
        assert head.content == b"" and head.headers["content-type"] == get.headers["content-type"]
    assert client.head("/api/run/nosuch/48").status_code == 404
    assert client.post("/api/runs").status_code == 405, "only GET routes answer HEAD"


def test_health_is_not_ok_while_writes_are_refused_for_want_of_a_code(client, monkeypatch):
    """Found in review: health said ok while the image refused every write."""
    monkeypatch.setenv("BOB_REQUIRE_TOKENS", "1")
    health = client.get("/api/health").json()
    assert health["ok"] is False and health["writes"]["operator"] == "disabled"
    assert any("BOB_OPERATOR_TOKEN" in p for p in health["problems"])
    monkeypatch.setenv("BOB_OPERATOR_TOKEN", "o" * 20)
    monkeypatch.setenv("BOB_INGEST_TOKEN", "i" * 20)
    assert client.get("/api/health").json()["ok"] is True


def test_an_unusable_code_is_logged_once_not_on_every_request(client, monkeypatch, caplog):
    """Found in review: every protected request and health check logged it."""
    monkeypatch.setenv("BOB_OPERATOR_TOKEN", "short-code")
    with caplog.at_level("ERROR", logger="bob.access"):
        for _ in range(3):
            client.get("/api/health")
            client.post("/api/advisory/X/approve", json={"operator": "K. Ramesh"})
    logged = [r for r in caplog.records if "access code unusable" in r.getMessage()]
    assert len(logged) == 1 and "shorter than 16" in logged[0].getMessage()
    assert client.get("/api/health").json()["ok"] is False, "still reported, every time"


def test_a_budget_setting_that_is_not_a_number_is_reported_not_fatal(monkeypatch):
    """Found in review: BOB_OPERATOR_WRITES_PER_MIN=abc stopped the server starting."""
    from api import access

    monkeypatch.setattr(access, "SETTING_PROBLEMS", [])
    monkeypatch.setenv("BOB_OPERATOR_WRITES_PER_MIN", "abc")
    assert access._per_minute("BOB_OPERATOR_WRITES_PER_MIN", 30) == 30
    monkeypatch.setenv("BOB_OPERATOR_WRITES_PER_MIN", "0")
    assert access._per_minute("BOB_OPERATOR_WRITES_PER_MIN", 30) == 30
    monkeypatch.setenv("BOB_OPERATOR_WRITES_PER_MIN", "45")
    assert access._per_minute("BOB_OPERATOR_WRITES_PER_MIN", 30) == 45
    assert len(access.SETTING_PROBLEMS) == 2
    client = TestClient(main.app, base_url="http://localhost")
    assert "not a positive whole number" in " ".join(client.get("/api/health").json()["problems"])


def test_a_bad_budget_setting_does_not_stop_the_server_starting(tmp_path):
    import subprocess
    import sys

    env = {"PATH": "/usr/bin:/bin", "BOB_OPERATOR_WRITES_PER_MIN": "abc",
           "BOB_AUDIT_DB": str(tmp_path / "a.sqlite3")}
    r = subprocess.run([sys.executable, "-c", "import api.main; print('started')"],
                       cwd=Path(__file__).resolve().parent.parent, env=env,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "started" in r.stdout, r.stderr


def test_operator_input_is_bounded(client, advisory_id):
    url = f"/api/advisory/{advisory_id}/approve"
    assert client.post(url, json={"operator": "A" * 200_000}).status_code == 413  # body limit
    assert client.post(url, json={"operator": "A" * 121}).status_code == 422      # field limit
    assert client.post(url, json={"operator": "K. Ramesh", "note": "n" * 501}).status_code == 422
    assert client.post(url, json={"operator": "K.\x00Ramesh"}).status_code == 422
    for hidden in ("\u202e", "\u200b", "\x7f", "\x85", "\u2028"):   # bidi, zero-width, DEL, C1, LS
        assert client.post(url, json={"operator": f"K. Ram{hidden}esh"}).status_code == 422
    assert client.post(url, json={"operator": "కె. రమేష్"}).status_code == 200, "Telugu names are fine"
    assert client.post(url, json={"operator": "  K. Ramesh  "}).json()["operator"] == "K. Ramesh"


def test_with_a_token_configured_writes_need_it(client, advisory_id, monkeypatch):
    monkeypatch.setenv("BOB_OPERATOR_TOKEN", "s3cret-code-for-tests")
    url = f"/api/advisory/{advisory_id}/approve"
    body = {"operator": "K. Ramesh"}
    assert client.post(url, json=body).status_code == 401
    assert client.post(url, json=body, headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.post(url, json=body, headers={"Authorization": "s3cret-code-for-tests"}).status_code == 401
    ok = client.post(url, json=body, headers={"Authorization": "Bearer s3cret-code-for-tests"})
    assert ok.status_code == 200
    assert dispatch(client, advisory_id).status_code == 401
    assert client.get("/api/audit").status_code == 401
    # Reading the console needs no token.
    assert client.get("/api/run/montha/48").status_code == 200


def test_telemetry_has_its_own_token(client, monkeypatch):
    monkeypatch.setenv("BOB_INGEST_TOKEN", "gateway-key-for-tests")
    monkeypatch.setenv("BOB_OPERATOR_TOKEN", "officer-key-for-tests")
    r = client.post("/api/telemetry", json={}, headers={"Authorization": "Bearer officer-key-for-tests"})
    assert r.status_code == 401, "an officer's code is not a gateway's"


def test_a_cloud_deployment_without_a_token_refuses_writes(client, advisory_id, monkeypatch):
    """Forgetting the token on a public deployment must fail closed."""
    monkeypatch.setenv("K_SERVICE", "bob-forecaster")
    r = client.post(f"/api/advisory/{advisory_id}/approve", json={"operator": "K. Ramesh"})
    assert r.status_code == 503
    assert client.post("/api/telemetry", json={}).status_code == 503
    health = client.get("/api/health").json()
    assert health["writes"] == {"operator": "disabled", "telemetry": "disabled"}
    monkeypatch.setenv("BOB_AUDIT_DB", "/tmp/audit.sqlite3")
    assert client.get("/api/health").json()["audit_log"]["ephemeral"] is True


def test_health_says_when_writes_are_open(client):
    assert client.get("/api/health").json()["writes"] == {"operator": "open",
                                                          "telemetry": "open"}


def test_storm_names_that_are_not_plain_are_refused(client):
    assert client.get("/api/run/mon.tha/48").status_code == 422
    assert client.get("/api/telemetry/report/a-b").status_code == 422


def test_responses_carry_security_headers(client):
    r = client.get("/api/health")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    page = client.get("/")
    csp = page.headers["Content-Security-Policy"]
    assert client.get("/static/index.html").headers["Content-Security-Policy"] == csp
    docs = client.get("/docs").headers["Content-Security-Policy"]
    assert docs != csp and "frame-ancestors 'none'" in docs
    assert "unsafe-inline" not in docs.split("script-src")[1].split(";")[0]
    assert "'sha256-" in docs, "the docs page's inline script is allowed by hash"
    assert "Strict-Transport-Security" not in r.headers, "not on a laptop's plain HTTP"
    assert "frame-ancestors 'none'" in csp and "object-src 'none'" in csp
    assert "script-src 'self';" in csp, "no third-party script at all: MapLibre is vendored"
    assert "cdnjs" not in csp and "worker-src 'self' blob:" in csp
    connect = csp.split("connect-src")[1].split(";")[0]
    assert "data:" in connect, "MapLibre 6 fetches the hazard images"
    assert " https: " not in connect + " " and "cartocdn.com" in connect, "the basemap's hosts only"
    assert " https:;" not in csp and not csp.endswith(" https:")
    assert "unsafe-inline" not in csp.split("script-src")[1].split(";")[0]


def test_oversized_writes_are_refused_before_they_are_read(client, advisory_id):
    big = {"operator": "K. Ramesh", "note": "x" * (guard.MAX_BODY_BYTES + 1)}
    r = client.post(f"/api/advisory/{advisory_id}/approve", json=big)
    assert r.status_code == 413
    assert main.audit_log().history(advisory_id) == []


def test_a_changed_run_file_is_read_again(tmp_path, monkeypatch):
    runs = tmp_path / "runs"; runs.mkdir()
    src = json.loads((RUNS / "montha_48h.json").read_text())
    path = runs / "montha_48h.json"
    path.write_text(json.dumps(src))
    monkeypatch.setattr(run_store, "RUNS", runs)
    monkeypatch.setattr(run_store, "_RUN_CACHE", {})
    monkeypatch.setattr(main, "_audit", AuditLog(tmp_path / "audit.sqlite3"))
    c = TestClient(main.app, base_url="http://localhost")
    assert c.get("/api/run/montha/48").json()["summary"]["storm"] == src["summary"]["storm"]
    src["summary"]["storm"] = "Changed"
    path.write_text(json.dumps(src))
    import os
    os.utime(path, ns=(path.stat().st_atime_ns, path.stat().st_mtime_ns + 1_000_000))
    assert c.get("/api/run/montha/48").json()["summary"]["storm"] == "Changed"


def test_serving_a_run_never_writes_approval_state_into_the_cache(client, advisory_id):
    client.post(f"/api/advisory/{advisory_id}/approve", json={"operator": "K. Ramesh"})
    client.get("/api/run/montha/48")
    cached = run_store.load_run("montha", 48)
    adv = next(a for a in cached["advisories"] if a["identifier"] == advisory_id)
    assert "approved_by" not in adv
    client.post(f"/api/advisory/{advisory_id}/revoke", json={"operator": "S. Das"})
    served = client.get("/api/run/montha/48").json()
    assert next(a for a in served["advisories"]
                if a["identifier"] == advisory_id)["approved"] is False


# --- the endpoints the console and SACHET read -------------------------------

def test_the_run_list_is_what_the_console_first_asks_for(client):
    runs = client.get("/api/runs").json()
    assert {"storm": "montha", "lead_hours": 48, "file": "montha_48h.json"} in runs
    assert all(set(r) == {"storm", "lead_hours", "file"} for r in runs)


def test_a_stray_file_among_the_runs_is_ignored_everywhere(tmp_path, monkeypatch):
    """Found in review: a non-run JSON file made every approval return 500."""
    runs = tmp_path / "runs"; runs.mkdir()
    (runs / "montha_48h.json").write_text((RUNS / "montha_48h.json").read_text())
    (runs / "notes.json").write_text("[1, 2, 3]")
    (runs / "montha_48h.backup.json").write_text("not json at all")
    monkeypatch.setattr(run_store, "RUNS", runs)
    monkeypatch.setattr(run_store, "_RUN_CACHE", {})
    client = TestClient(main.app, base_url="http://localhost", raise_server_exceptions=False)
    assert client.get("/api/runs").json() == [
        {"storm": "montha", "lead_hours": 48, "file": "montha_48h.json"}]
    assert client.get("/api/health").json()["runs"] == 1
    ident = client.get("/api/run/montha/48").json()["advisories"][0]["identifier"]
    assert client.post(f"/api/advisory/{ident}/approve", json={"operator": "K. Ramesh"}).status_code == 200
    assert client.post("/api/advisory/NOPE/revoke", json={"operator": "K. Ramesh"}).status_code == 404


def test_cap_xml_is_served_as_xml_and_is_an_exercise(client, advisory_id):
    r = client.get(f"/api/advisory/montha/48/{advisory_id}/cap.xml")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/xml")
    assert "<status>Exercise</status>" in r.text
    assert client.get("/api/advisory/montha/48/NOPE/cap.xml").status_code == 404


def test_dispatch_for_an_advisory_not_in_that_run_is_404(client, advisory_id):
    client.post(f"/api/advisory/{advisory_id}/approve", json={"operator": "K. Ramesh"})
    assert client.post(f"/api/advisory/fani/48/{advisory_id}/dispatch").status_code == 404


def test_the_network_report_is_served_and_a_missing_one_explains_itself(client):
    r = client.get("/api/telemetry/report/montha")
    assert r.status_code == 200 and "faults_caught" in r.json()
    missing = client.get("/api/telemetry/report/nosuch")
    assert missing.status_code == 404 and "telemetry.simulate" in missing.json()["detail"]


def test_a_dispatch_is_recorded_against_who_dispatched_not_who_approved(client, advisory_id):
    """Found in review: the dispatch event carried the approver's name."""
    client.post(f"/api/advisory/{advisory_id}/approve", json={"operator": "K. Ramesh"})
    dispatch(client, advisory_id)
    r = client.post(f"/api/advisory/montha/48/{advisory_id}/dispatch", json={"operator": "S. Das"})
    assert r.json()["dispatched_by"] == "S. Das" and r.json()["approved_by"] == "K. Ramesh"
    events = [e for e in client.get(f"/api/audit?identifier={advisory_id}").json()
              if e["action"] == "dispatch_allowed"]
    assert [e["operator"] for e in events] == [None, "S. Das"]
    assert all(e["note"] == "approved by K. Ramesh" for e in events)


@pytest.mark.parametrize("breakage", ["corrupt", "cannot be created"])
def test_an_unusable_audit_log_costs_approvals_not_the_forecast(tmp_path, monkeypatch, breakage):
    """Found in review: with the audit database corrupt or unreachable, GET
    /api/run was a 500 and health said ok. The forecast does not depend on
    the approval record, so it is served with approval state unknown; writes
    are refused with 503 saying nothing was recorded; health names the store."""
    if breakage == "corrupt":
        bad = tmp_path / "audit.sqlite3"
        bad.write_bytes(b"not a database" * 100)
    else:
        # A file where its directory should be: no one can create it, root
        # included (a read-only directory would not stop root).
        blocker = tmp_path / "blocker"
        blocker.write_text("a file, not a directory")
        bad = blocker / "sub" / "audit.sqlite3"
    monkeypatch.setenv("BOB_AUDIT_DB", str(bad))
    monkeypatch.setattr(main, "_audit", None)
    client = TestClient(main.app, base_url="http://localhost", raise_server_exceptions=False)
    run = client.get("/api/run/montha/48")
    assert run.status_code == 200
    body = run.json()
    assert "cannot be read" in body["approvals_unavailable"]
    assert all(a["approved"] is None for a in body["advisories"])
    ident = body["advisories"][0]["identifier"]
    for r in (client.post(f"/api/advisory/{ident}/approve", json={"operator": "K. Ramesh"}),
              client.post(f"/api/advisory/montha/48/{ident}/dispatch")):
        assert r.status_code == 503 and "nothing was recorded" in r.json()["detail"]
        assert str(bad) not in r.text
    health = client.get("/api/health").json()
    assert health["ok"] is False and health["problems"][0].startswith("the audit log cannot be used")
    assert str(tmp_path) not in str(health)


def test_health_does_not_disclose_where_data_is_kept(client):
    assert "path" not in client.get("/api/health").json()["audit_log"]


def test_node_locations_need_the_operator_code_when_one_is_set(client, monkeypatch):
    assert client.get("/api/telemetry/nodes").status_code == 200
    monkeypatch.setenv("BOB_OPERATOR_TOKEN", "operator-code-for-tests")
    assert client.get("/api/telemetry/nodes").status_code == 401


def test_standing_approvals_are_read_in_one_query_and_agree_with_one_by_one(tmp_path):
    log = AuditLog(tmp_path / "a.sqlite3")
    log.record("A", "approve", "K. Ramesh")
    log.record("B", "approve", "S. Das")
    log.record("B", "revoke", "S. Das")
    log.record("C", "dispatch_refused")
    many = log.current_many(["A", "B", "C", "D"])
    assert set(many) == {"A"}
    assert many["A"] == log.current("A")
    assert log.current("B") is None and log.current_many([]) == {}


def test_a_rebound_domain_is_refused_before_it_can_pass_the_origin_check(client, advisory_id):
    """Found in review: a page on a domain pointed at 127.0.0.1 sends Host and
    Origin that agree -- both the attacker's -- and approved an advisory."""
    evil = {"Host": "rebind.evil.example:8077", "Origin": "http://rebind.evil.example:8077"}
    r = client.post(f"/api/advisory/{advisory_id}/approve", headers=evil,
                    json={"operator": "K. Ramesh"})
    assert r.status_code == 400
    assert main.audit_log().history(advisory_id) == []
    assert client.get("/api/runs", headers={"Host": "rebind.evil.example"}).status_code == 400
    assert r.headers["X-Content-Type-Options"] == "nosniff", "refusals carry the headers too"


@pytest.mark.parametrize("host, allowed", [
    ("localhost", True), ("localhost:8077", True), ("127.0.0.1:8077", True), ("[::1]:8077", True),
    ("LOCALHOST", True), ("", False), ("evil.example", False), ("localhost.evil.example", False),
    ("127.0.0.1.nip.io", False), ("bob-abc.a.run.app", False),
])
def test_by_default_only_this_machines_names_are_answered(host, allowed):
    assert guard.host_allowed(host, guard.allowed_hosts()) is allowed


def test_on_cloud_run_the_service_domain_is_answered_and_https_is_insisted_on(client, monkeypatch):
    monkeypatch.setenv("K_SERVICE", "bob")
    assert guard.host_allowed("bob-abc-el.a.run.app", guard.allowed_hosts())
    assert not guard.host_allowed("run.app.evil.example", guard.allowed_hosts())
    assert not guard.host_allowed("evilrun.app", guard.allowed_hosts())
    r = client.get("/api/health", headers={"Host": "bob-abc-el.a.run.app"})
    assert r.status_code == 200
    assert r.headers["Strict-Transport-Security"] == "max-age=31536000"


def test_allowed_hosts_can_be_configured(monkeypatch):
    monkeypatch.setenv("BOB_ALLOWED_HOSTS", "forecaster.example.org, *.osdma.example")
    assert guard.host_allowed("forecaster.example.org:443", guard.allowed_hosts())
    assert guard.host_allowed("console.osdma.example", guard.allowed_hosts())
    assert not guard.host_allowed("localhost", guard.allowed_hosts()), "configured replaces the default"
    monkeypatch.setenv("BOB_ALLOWED_HOSTS", "*")
    assert guard.host_allowed("anything.example", guard.allowed_hosts())


def test_api_docs_are_off_on_a_deployment_unless_asked_for(client, monkeypatch):
    """They load their UI from a CDN without a pinned version."""
    assert client.get("/docs").status_code == 200
    assert client.get("/redoc").status_code == 200
    assert client.get("/openapi.json").json()["info"]["title"] == main.app.title
    monkeypatch.setenv("K_SERVICE", "bob")
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
    assert client.get("/openapi.json").status_code == 404, "found in review: the schema stayed public"
    monkeypatch.setenv("BOB_API_DOCS", "1")
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_large_responses_are_compressed(client):
    with client.stream("GET", "/api/run/montha/48", headers={"Accept-Encoding": "gzip"}) as r:
        assert r.status_code == 200 and r.headers["Content-Encoding"] == "gzip"
        sent = sum(len(chunk) for chunk in r.iter_raw())
    plain = client.get("/api/run/montha/48", headers={"Accept-Encoding": "identity"})
    assert "Content-Encoding" not in plain.headers
    assert sent < len(plain.content) / 3, (sent, len(plain.content))
    assert plain.json()["advisories"]


def test_the_same_site_in_other_letter_case_is_the_same_site(client, advisory_id):
    """Found in review: Host LOCALHOST with Origin localhost was refused."""
    url = f"/api/advisory/montha/48/{advisory_id}/dispatch"
    r = client.post(url, headers={"Host": "LOCALHOST:8791", "Origin": "http://localhost:8791"})
    assert r.status_code == 409, "the normal answer (not approved), not a cross-site 403"
    r = client.post(url, headers={"Host": "localhost:8791", "Origin": "http://evil.example"})
    assert r.status_code == 403


def test_a_write_another_website_sends_is_refused(client, advisory_id):
    """Found in review: a bodiless cross-site POST could write dispatch rows."""
    url = f"/api/advisory/montha/48/{advisory_id}/dispatch"
    assert client.post(url, headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.post(url, headers={"Origin": "null"}).status_code == 403
    assert main.audit_log().history(advisory_id) == [], "nothing was recorded"
    same = client.post(url, headers={"Origin": "http://localhost"})
    assert same.status_code == 409, "the console's own origin gets the normal answer"
    assert client.post(url).status_code == 409, "no Origin: not a browser, not refused"


def test_the_console_is_revalidated_so_an_update_is_seen(client):
    """Found in use: after an update the browser kept the old page, so the
    sign-in button did not appear until a hard reload."""
    assert client.get("/").headers["Cache-Control"] == "no-cache"
    for path in ("/static/app.js", "/static/auth-loader.mjs", "/static/vendor/firebase/firebase-auth.js"):
        r = client.get(path)
        assert r.headers["Cache-Control"] == "no-cache", path
        again = client.get(path, headers={"If-None-Match": r.headers["ETag"]})
        assert again.status_code == 304, "an unchanged script is not sent again"
    assert "Cache-Control" not in client.get("/api/health").headers

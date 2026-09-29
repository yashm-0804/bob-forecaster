"""The write budget: a brake on floods, with the time to wait."""

import pytest
from fastapi.testclient import TestClient

from api.ratelimit import RateLimiter


def test_requests_within_the_budget_pass_and_the_next_waits():
    now = [0.0]
    limiter = RateLimiter(3, clock=lambda: now[0])
    assert [limiter.retry_after("a") for _ in range(3)] == [None, None, None]
    assert limiter.retry_after("a") == 61
    assert limiter.retry_after("b") is None, "clients have separate budgets"
    now[0] = 30.0
    assert limiter.retry_after("a") == 31
    now[0] = 60.5
    assert limiter.retry_after("a") is None, "the window slides"


def test_idle_clients_are_forgotten_so_memory_stays_bounded():
    limiter = RateLimiter(1, clock=lambda: 0.0, max_clients=100)
    for i in range(1000):
        limiter.retry_after(f"client-{i}")
    assert len(limiter._hits) == 100


def _client(monkeypatch, operator_budget=30, failures=20):
    import api.main as main
    from api import access

    monkeypatch.setitem(access.BUDGETS, access.OPERATOR, RateLimiter(operator_budget))
    monkeypatch.setattr(access, "FAILED_ATTEMPTS", RateLimiter(failures))
    return TestClient(main.app, base_url="http://localhost")


def test_the_api_answers_429_with_retry_after(monkeypatch):
    client = _client(monkeypatch, operator_budget=2)
    codes = [client.post("/api/advisory/NOPE/approve", json={"operator": "K. Ramesh"}).status_code
             for _ in range(3)]
    assert codes == [404, 404, 429]
    r = client.post("/api/advisory/NOPE/approve", json={"operator": "K. Ramesh"})
    assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0
    assert client.get("/api/health").status_code == 200, "reads are not limited"


def test_traffic_without_the_code_cannot_lock_out_a_code_holder(monkeypatch):
    """Found in review: the limit was counted before the access check, so
    thirty anonymous requests from a shared address blocked every approval.

    What this limit is, and is not: it bounds how many wrong attempts an
    address gets answered, not the odds of a guess, because the right code
    always gets through (behind Cloud Run's proxy every caller shares one
    address, so refusing the right code would let anyone lock officers
    out). Guessing is defeated by the code's length; see the next test."""
    monkeypatch.setenv("BOB_OPERATOR_TOKEN", "real-code-for-the-tests")
    client = _client(monkeypatch, operator_budget=30, failures=5)
    anonymous = [client.post("/api/advisory/NOPE/approve", json={"operator": "X Y Z"}).status_code
                 for _ in range(40)]
    assert anonymous.count(401) == 5 and anonymous.count(429) == 35, "wrong attempts are limited"
    ok = client.post("/api/advisory/NOPE/approve", json={"operator": "K. Ramesh"},
                     headers={"Authorization": "Bearer real-code-for-the-tests"})
    assert ok.status_code == 404, "the code holder gets through (to a 404 for a fake id)"


@pytest.mark.parametrize("code, why", [
    ("Zq7", "shorter than 16"), ("e2e-code", "shorter than 16"), ("fifteen-chars-x", "shorter than 16"),
    ("pässwörd-länger-als-16", "outside ASCII"),
])
def test_an_unusable_code_refuses_everything_and_says_so(monkeypatch, caplog, code, why):
    """Found in review: with a short code, 936 fast guesses found it, since
    the limit on wrong guesses never blocks the right one; and a code with
    characters outside ASCII could never match, as headers arrive as latin-1.
    Either is now a misconfiguration: refused outright, reported by health,
    and explained in the server log -- publicly only named, not described."""
    monkeypatch.setenv("BOB_OPERATOR_TOKEN", code)
    client = _client(monkeypatch)
    for auth in ({}, {"Authorization": b"Bearer " + code.encode()}):   # the code's own bytes
        r = client.post("/api/advisory/NOPE/approve", json={"operator": "K. Ramesh"}, headers=auth)
        assert r.status_code == 503 and "BOB_OPERATOR_TOKEN is misconfigured" in r.json()["detail"]
        assert why not in r.text
    audit = client.get("/api/audit", headers={"Authorization": b"Bearer " + code.encode()})
    assert audit.status_code == 503, "reads the code protects are refused too"
    health = client.get("/api/health").json()
    assert health["writes"]["operator"] == "disabled" and health["ok"] is False
    assert any("BOB_OPERATOR_TOKEN is misconfigured" in p for p in health["problems"])
    assert code not in str(health) and why not in str(health)
    assert why in caplog.text, "the log says what is wrong"
    assert code not in caplog.text, "and never the code"


def test_the_shortest_accepted_code_works(monkeypatch):
    code = "x" * 16
    monkeypatch.setenv("BOB_OPERATOR_TOKEN", code)
    client = _client(monkeypatch)
    r = client.post("/api/advisory/NOPE/approve", json={"operator": "K. Ramesh"},
                    headers={"Authorization": f"Bearer {code}"})
    assert r.status_code == 404
    assert client.get("/api/health").json()["writes"]["operator"] == "token"


def test_reading_the_audit_log_does_not_spend_the_write_budget(monkeypatch):
    """Found in review: thirty reads of /api/audit in a minute blocked the
    officer's next approval for sixty seconds."""
    code = "operator-code-for-the-tests"
    monkeypatch.setenv("BOB_OPERATOR_TOKEN", code)
    client = _client(monkeypatch, operator_budget=3)
    auth = {"Authorization": f"Bearer {code}"}
    for _ in range(40):
        assert client.get("/api/audit", headers=auth).status_code == 200
        assert client.get("/api/telemetry/nodes", headers=auth).status_code == 200
    r = client.post("/api/advisory/NOPE/approve", json={"operator": "K. Ramesh"}, headers=auth)
    assert r.status_code == 404, "the approval is answered, not refused for the reads"
    assert client.get("/api/audit").status_code == 401, "reads still need the code"


def test_the_container_image_refuses_writes_without_codes_anywhere(monkeypatch):
    """Found in review: outside Cloud Run the image, listening on every
    interface, was open for writes when started without codes. It sets
    BOB_REQUIRE_TOKENS=1; a checkout on a laptop does not."""
    monkeypatch.setenv("BOB_REQUIRE_TOKENS", "1")
    client = _client(monkeypatch)
    assert client.post("/api/advisory/NOPE/approve", json={"operator": "K. Ramesh"}).status_code == 503
    assert client.post("/api/telemetry", json={}).status_code == 503
    assert client.get("/api/health").json()["writes"] == {"operator": "disabled",
                                                          "telemetry": "disabled"}


def test_the_image_sets_the_rule():
    from pathlib import Path

    dockerfile = (Path(__file__).resolve().parent.parent / "Dockerfile").read_text()
    assert "BOB_REQUIRE_TOKENS=1" in dockerfile


def test_a_code_holder_still_has_a_budget(monkeypatch):
    monkeypatch.setenv("BOB_OPERATOR_TOKEN", "real-code-for-the-tests")
    client = _client(monkeypatch, operator_budget=3)
    auth = {"Authorization": "Bearer real-code-for-the-tests"}
    codes = [client.post("/api/advisory/NOPE/revoke", json={"operator": "K. Ramesh"},
                         headers=auth).status_code for _ in range(4)]
    assert codes == [404, 404, 404, 429]

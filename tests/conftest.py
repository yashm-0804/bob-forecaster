"""Keep the suite offline and machine-independent.

A signed-in laptop and a fresh CI runner must see the same results, so Earth
Engine is switched off and any Gemini key cleared for every test. Tests that exercise the satellite code
feed it recorded arrays instead.
"""

import os

import pytest


def pytest_collection_modifyitems(config, items):
    """Tests marked `network` probe live services (AWS, Overpass). They are
    opt-in, so the default suite cannot fail because a third party is slow."""
    if os.environ.get("BOB_NETWORK_TESTS") == "1":
        return
    skip = pytest.mark.skip(reason="live-service test; set BOB_NETWORK_TESTS=1 to run")
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch, tmp_path):
    from ingest import earthengine

    monkeypatch.setenv("EARTHENGINE_OFF", "1")
    # No real Gemini calls either: drafting tests pass a fake generator.
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY_2"):
        monkeypatch.setenv(name, "placeholder")
        monkeypatch.delenv(name)
    # Access control starts in local mode: no tokens, not on Cloud Run.
    for name in ("BOB_OPERATOR_TOKEN", "BOB_INGEST_TOKEN", "K_SERVICE", "EE_PROJECT",
                 "BOB_NODE_REGISTRY", "BOB_ALLOWED_HOSTS", "BOB_API_DOCS", "BOB_REQUIRE_TOKENS"):
        monkeypatch.setenv(name, "placeholder")
        monkeypatch.delenv(name)
    monkeypatch.setitem(earthengine._state, "ready", False)
    # The API's stores open lazily; each test gets its own, never data/.
    import api.main

    monkeypatch.setenv("BOB_AUDIT_DB", str(tmp_path / "audit.sqlite3"))
    # The file store, whatever the developer's .env chose: tests never reach BigQuery
    # unless they say so.
    for name in ("BOB_AUDIT_STORE", "BOB_BQ_AUDIT_TABLE", "BOB_FIREBASE_PROJECT", "BOB_OPERATORS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("BOB_TELEMETRY_DB", str(tmp_path / "telemetry.sqlite3"))
    monkeypatch.setattr(api.main, "_audit", None)
    monkeypatch.setattr(api.main, "_telemetry", None)
    # Every test starts with a full write budget; the limit itself is
    # tested in test_ratelimit.py.
    from api import access
    from api.ratelimit import RateLimiter

    monkeypatch.setitem(access.BUDGETS, access.OPERATOR, RateLimiter(30))
    monkeypatch.setitem(access.BUDGETS, access.INGEST, RateLimiter(1200))
    monkeypatch.setattr(access, "FAILED_ATTEMPTS", RateLimiter(20))
    # A code problem is logged once per process; each test is its own.
    monkeypatch.setattr(access, "_LOGGED", set())

"""Officers sign in with Google (api/identity.py): approvals are recorded
against a verified account, and only officers on BOB_OPERATORS may act.

Tokens here are made as Firebase makes them -- RS256, signed by a key whose
certificate the server looks up by key id -- with a key made for the test."""

import time
from datetime import UTC, datetime, timedelta

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi.testclient import TestClient
from google.auth import crypt, jwt

import api.main as main
from api import identity
from api.audit import AuditLog

PROJECT = "bob-test-project"


def _key_and_cert():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "securetoken.test")])
    now = datetime.now(UTC)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(1)
            .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=1))
            .sign(key, hashes.SHA256()))
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode()
    return pem, cert.public_bytes(serialization.Encoding.PEM).decode()


KEY, CERT = _key_and_cert()
OTHER_KEY, _ = _key_and_cert()


def token(email="k.ramesh@osdma.example", name="K. Ramesh", key=KEY, kid="k1", **claims):
    now = int(time.time())
    payload = {"iss": f"https://securetoken.google.com/{PROJECT}", "aud": PROJECT,
               "sub": "uid-1", "user_id": "uid-1", "auth_time": now - 60, "iat": now - 60,
               "exp": now + 3600, "email": email, "email_verified": True, "name": name,
               "firebase": {"sign_in_provider": "google.com",
                            "identities": {"email": [email]}}}
    payload.update(claims)
    return jwt.encode(crypt.RSASigner.from_string(key, kid), payload).decode()


@pytest.fixture
def signin(monkeypatch, tmp_path):
    monkeypatch.setenv("BOB_FIREBASE_PROJECT", PROJECT)
    monkeypatch.setenv("BOB_FIREBASE_API_KEY", "AIza-test-web-key")
    monkeypatch.setenv("BOB_FIREBASE_APP_ID", "1:1:web:test")
    monkeypatch.setenv("BOB_OPERATORS", "k.ramesh@osdma.example, @seoc.example")
    monkeypatch.setattr(identity, "CERTS", identity._Certs(lambda: ({"k1": CERT}, 3600)))
    monkeypatch.setattr(main, "_audit", AuditLog(tmp_path / "audit.sqlite3"))
    client = TestClient(main.app, base_url="http://localhost")
    ident = client.get("/api/run/montha/48").json()["advisories"][0]["identifier"]
    return client, ident


def auth(tok):
    return {"Authorization": f"Bearer {tok}"}


def test_an_approval_is_recorded_against_the_signed_in_account_not_a_typed_name(signin):
    client, ident = signin
    r = client.post(f"/api/advisory/{ident}/approve", headers=auth(token()),
                    json={"operator": "Someone Else Entirely"})
    assert r.status_code == 200 and r.json()["operator"] == "K. Ramesh <k.ramesh@osdma.example>"
    r = client.post(f"/api/advisory/montha/48/{ident}/dispatch",
                    headers=auth(token("p.rao@seoc.example", "P. Rao")))
    assert r.status_code == 200
    assert r.json()["dispatched_by"] == "P. Rao <p.rao@seoc.example>", "a whole domain on the list"
    history = client.get(f"/api/audit?identifier={ident}", headers=auth(token())).json()
    assert [(e["action"], e["operator"]) for e in history] == [
        ("approve", "K. Ramesh <k.ramesh@osdma.example>"),
        ("dispatch_allowed", "P. Rao <p.rao@seoc.example>")]


@pytest.mark.parametrize("why, tok", [
    ("no sign-in", None),
    ("the shared code is not a sign-in", "operator-code-0123456789abcdef"),
    ("another Firebase project", token(aud="someone-elses-project")),
    ("another issuer", token(iss="https://accounts.example/other")),
    ("expired", token(iat=int(time.time()) - 7200, exp=int(time.time()) - 3600)),
    ("email not verified", token(email_verified=False)),
    ("not a Google sign-in", token(firebase={"sign_in_provider": "password"})),
    ("signed with another key", token(key=OTHER_KEY)),
    ("a key id Google does not have", token(kid="unknown")),
])
def test_anything_but_a_valid_google_sign_in_is_refused_and_nothing_recorded(signin, why, tok):
    client, ident = signin
    r = client.post(f"/api/advisory/{ident}/approve", headers=auth(tok) if tok else {},
                    json={"operator": "K. Ramesh"})
    assert r.status_code == 401, why
    assert "Sign in" in r.json()["detail"]
    assert main.audit_log().history(ident) == []


def test_a_valid_account_that_is_not_an_officer_is_refused(signin):
    client, ident = signin
    r = client.post(f"/api/advisory/{ident}/approve", headers=auth(token("stranger@gmail.com")),
                    json={"operator": "Stranger"})
    assert r.status_code == 403 and "stranger@gmail.com is not on" in r.json()["detail"]
    assert main.audit_log().history(ident) == []
    assert identity.on_the_list("K.RAMESH@osdma.example"), "addresses compare without case"
    assert not identity.on_the_list("x@notseoc.example"), "a domain entry matches that domain only"


def test_without_a_list_of_officers_no_one_may_act_and_health_says_so(signin, monkeypatch):
    client, ident = signin
    monkeypatch.setenv("BOB_OPERATORS", "")
    r = client.post(f"/api/advisory/{ident}/approve", headers=auth(token()), json={"operator": "x"})
    assert r.status_code == 503 and "BOB_OPERATORS is empty" in r.json()["detail"]
    health = client.get("/api/health").json()
    assert health["ok"] is False and health["writes"]["operator"] == "disabled"
    monkeypatch.setenv("BOB_OPERATORS", "k.ramesh@osdma.example")
    assert client.get("/api/health").json()["writes"]["operator"] == "signin"


def test_the_page_is_told_how_to_sign_in_and_its_policy_allows_only_that(signin, monkeypatch):
    client, _ = signin
    config = client.get("/api/auth-config").json()["firebase"]
    assert config == {"apiKey": "AIza-test-web-key", "authDomain": f"{PROJECT}.firebaseapp.com",
                      "projectId": PROJECT, "appId": "1:1:web:test"}
    csp = client.get("/").headers["Content-Security-Policy"]
    script_src = csp.split("script-src ")[1].split(";")[0]
    assert script_src == "'self' https://apis.google.com"
    assert f"frame-src 'self' https://{PROJECT}.firebaseapp.com https://apis.google.com" in csp
    monkeypatch.delenv("BOB_FIREBASE_PROJECT")
    assert client.get("/api/auth-config").json() == {"firebase": None}
    assert "apis.google.com" not in client.get("/").headers["Content-Security-Policy"]


def test_repeated_bad_sign_ins_are_slowed_like_wrong_codes(signin):
    client, ident = signin
    codes = [client.post(f"/api/advisory/{ident}/approve", headers=auth(token(key=OTHER_KEY)),
                         json={"operator": "x"}).status_code for _ in range(25)]
    assert codes.count(401) == 20 and codes[-1] == 429
    ok = client.post(f"/api/advisory/{ident}/approve", headers=auth(token()), json={"operator": "x"})
    assert ok.status_code == 200, "a valid sign-in is never locked out"


def test_when_googles_keys_cannot_be_fetched_nothing_is_recorded(signin, monkeypatch):
    client, ident = signin

    def unreachable():
        raise OSError("network unreachable")

    monkeypatch.setattr(identity, "CERTS", identity._Certs(unreachable))
    r = client.post(f"/api/advisory/{ident}/approve", headers=auth(token()), json={"operator": "x"})
    assert r.status_code == 503 and "Nothing was recorded" in r.json()["detail"]
    assert main.audit_log().history(ident) == []


def test_googles_keys_are_fetched_once_while_they_are_fresh(signin, monkeypatch):
    client, ident = signin
    fetches = []
    monkeypatch.setattr(identity, "CERTS",
                        identity._Certs(lambda: (fetches.append(1) or {"k1": CERT}, 3600)))
    for _ in range(3):
        client.get("/api/audit", headers=auth(token()))
    assert len(fetches) == 1

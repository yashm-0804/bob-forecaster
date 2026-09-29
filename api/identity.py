"""Officers sign in with Google (Firebase Authentication), so an approval is
recorded against a verified account, not a name anyone could type.

With BOB_FIREBASE_PROJECT set, operator actions -- approve, withdraw,
dispatch, reading the audit log -- need `Authorization: Bearer <ID token>`
from a Firebase sign-in, instead of the shared operator code:

  - the token must be signed by Google for this Firebase project, unexpired,
    issued through Google sign-in, with a verified email;
  - the email must be on BOB_OPERATORS: comma-separated addresses, or
    "@example.org" for a whole domain. Without that list no one may act:
    otherwise any Google account in the world could approve.

The page gets what it needs to start the sign-in from /api/auth-config: the
web app's configuration, which Firebase designs to be public.

Telemetry gateways are machines, and keep their ingest code (api/access.py).
"""

from __future__ import annotations

import os
import re
import threading
import time
from collections.abc import Callable
from typing import Any, NamedTuple, cast

from fastapi import HTTPException
from google.auth import exceptions as auth_exceptions
from google.auth import jwt

#: Google's public keys for Firebase ID tokens, by key id.
CERTS_URL = "https://www.googleapis.com/robot/v1/metadata/x509/securetoken@system.gserviceaccount.com"
#: Clock difference tolerated between this server and Google's, seconds.
CLOCK_SKEW_S = 30


class Officer(NamedTuple):
    email: str
    name: str

    @property
    def label(self) -> str:
        """How the audit trail names them: their name and the verified address."""
        return f"{self.name} <{self.email}>" if self.name else self.email


def project() -> str:
    return os.environ.get("BOB_FIREBASE_PROJECT", "").strip()


def enabled() -> bool:
    return bool(project())


def allowed() -> list[str]:
    return [a.strip().lower() for a in os.environ.get("BOB_OPERATORS", "").split(",") if a.strip()]


def web_config() -> dict[str, str] | None:
    """The Firebase web app's configuration for the page, or None."""
    if not enabled():
        return None
    return {"apiKey": os.environ.get("BOB_FIREBASE_API_KEY", ""),
            "authDomain": auth_domain(),
            "projectId": project(),
            "appId": os.environ.get("BOB_FIREBASE_APP_ID", "")}


def auth_domain() -> str:
    return os.environ.get("BOB_FIREBASE_AUTH_DOMAIN", "") or f"{project()}.firebaseapp.com"


def problems() -> list[str]:
    """Sign-in settings that cannot work, for /api/health."""
    if not enabled():
        return []
    out = [f"sign-in is on but {name} is not set" for name in
           ("BOB_FIREBASE_API_KEY", "BOB_FIREBASE_APP_ID") if not os.environ.get(name)]
    if not allowed():
        out.append("sign-in is on but BOB_OPERATORS is empty, so no one may approve")
    return out


def on_the_list(email: str) -> bool:
    email = email.lower()
    return any(email == a or (a.startswith("@") and email.endswith(a)) for a in allowed())


class _Certs:
    """Google's signing certificates, fetched when needed and kept for as long
    as Google's Cache-Control allows."""

    def __init__(self, fetch: Callable[[], tuple[dict[str, str], int]]) -> None:
        self._fetch = fetch
        self._lock = threading.Lock()
        self._certs: dict[str, str] = {}
        self._until = 0.0

    def get(self) -> dict[str, str]:
        with self._lock:
            if time.monotonic() >= self._until:
                self._certs, max_age = self._fetch()
                self._until = time.monotonic() + max_age
            return self._certs


def _fetch_certs() -> tuple[dict[str, str], int]:
    import requests

    r = requests.get(CERTS_URL, timeout=10)
    r.raise_for_status()
    age = re.search(r"max-age=(\d+)", r.headers.get("Cache-Control", ""))
    return cast(dict[str, str], r.json()), int(age[1]) if age else 3600


CERTS = _Certs(_fetch_certs)


def verify(token: str) -> Officer:
    """The officer a Firebase ID token proves, or a 401/403 saying why not."""
    try:
        certs = CERTS.get()
    except Exception as exc:  # noqa: BLE001 - network or decode failure fetching the keys
        from common.errors import reraise_bugs

        reraise_bugs(exc)
        raise HTTPException(503, "Sign-in cannot be checked right now: Google's keys "
                                 "could not be fetched. Nothing was recorded.") from exc
    try:
        claims = cast(dict[str, Any], jwt.decode(  # pyright: ignore[reportUnknownMemberType]
            token, certs=certs, audience=project(), clock_skew_in_seconds=CLOCK_SKEW_S))
    except (ValueError, auth_exceptions.GoogleAuthError) as exc:
        raise HTTPException(401, "Sign in again: this sign-in is not valid here "
                                 f"({type(exc).__name__})",
                            headers={"WWW-Authenticate": "Bearer"}) from exc
    firebase = cast(dict[str, Any], claims.get("firebase") or {})
    email = str(claims.get("email") or "")
    if (claims.get("iss") != f"https://securetoken.google.com/{project()}"
            or not claims.get("sub") or firebase.get("sign_in_provider") != "google.com"
            or claims.get("email_verified") is not True or not email):
        raise HTTPException(401, "Sign in again with a verified Google account",
                            headers={"WWW-Authenticate": "Bearer"})
    if not on_the_list(email):
        raise HTTPException(403, f"{email} is not on this console's list of officers "
                                 "(BOB_OPERATORS). Ask the administrator to add it.")
    return Officer(email=email, name=str(claims.get("name") or ""))

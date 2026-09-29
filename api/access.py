"""Who may change state: approve, revoke, dispatch, and write telemetry.

Two shared bearer tokens, one per kind of caller, read from the environment:

  BOB_OPERATOR_TOKEN  officers in the console: approve, revoke, dispatch, audit
  BOB_INGEST_TOKEN    field gateways: telemetry writes

Rules, in order:

  - Token configured but shorter than MIN_CODE_LENGTH: refused with 503, as
    if unset. What makes a code unguessable is its length, not the rate
    limit below: a request with the right code is never blocked (so no one
    can lock officers out by guessing wrong), which means a limit on wrong
    guesses slows nothing. A 16-character code from DEPLOY.md's generator
    has 96 bits; the 32-character one it makes has 192.
  - Token configured: the request must carry `Authorization: Bearer <token>`,
    compared in constant time. Anything else is 401.
  - No token, where writes must be protected -- on a managed platform (Cloud
    Run sets K_SERVICE) or in the container image (it sets
    BOB_REQUIRE_TOKENS=1): the write is refused with 503. A deployment that
    forgot its token fails closed instead of letting any visitor approve an
    advisory.
  - No token, anywhere else: open. This is a laptop running a replay from a
    checkout, and the health check says so.

A token proves the caller holds the access code, not who they are. With
sign-in configured (BOB_FIREBASE_PROJECT; see api/identity.py), operator
actions need a Google sign-in from an officer on BOB_OPERATORS instead, and
are recorded against that verified account. Without it, the named operator
on an approval is self-declared and recorded as such.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from collections.abc import Callable

from fastapi import Header, HTTPException, Request

from api import identity
from api.ratelimit import RateLimiter

OPERATOR = "BOB_OPERATOR_TOKEN"
INGEST = "BOB_INGEST_TOKEN"

#: Shortest access code accepted. See the module docstring for why length,
#: not the rate limit, is what resists guessing.
MIN_CODE_LENGTH = 16

#: Write budgets, per minute. Counted only for writes that have passed the
#: access check -- per code when codes are set, per client address when open --
#: so traffic without a valid code can never use up a code holder's budget,
#: and reads never count. Wrong codes have their own budget per address. It
#: bounds the load of wrong attempts, not the odds of guessing: a request with
#: the right code is always let through.
#: Budget settings that could not be read, for /api/health. A typo in one
#: used to stop the server starting; now it runs on the default and says so.
SETTING_PROBLEMS: list[str] = []


def _per_minute(name: str, default: int) -> int:
    """A budget from the environment: a positive whole number, else the default."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    if raw.isdigit() and int(raw) > 0:
        return int(raw)
    SETTING_PROBLEMS.append(f"{name} is not a positive whole number; using {default}")
    return default


BUDGETS: dict[str, RateLimiter] = {
    OPERATOR: RateLimiter(_per_minute("BOB_OPERATOR_WRITES_PER_MIN", 30)),
    INGEST: RateLimiter(_per_minute("BOB_TELEMETRY_WRITES_PER_MIN", 1200)),
}
FAILED_ATTEMPTS = RateLimiter(_per_minute("BOB_FAILED_AUTH_PER_MIN", 20))


def _too_many(wait: int) -> HTTPException:
    return HTTPException(429, f"Too many requests; retry in {wait} s",
                         headers={"Retry-After": str(wait)})


def managed_platform() -> bool:
    return bool(os.environ.get("K_SERVICE"))


def tokens_required() -> bool:
    """Whether writes without a configured code are refused rather than open:
    on Cloud Run, and wherever the container image runs."""
    return managed_platform() or os.environ.get("BOB_REQUIRE_TOKENS") == "1"


LOG = logging.getLogger("bob.access")


def _code_detail(env_name: str) -> str | None:
    """Exactly what is wrong with a configured code, for the server log."""
    code = os.environ.get(env_name, "")
    if not code:
        return None
    if len(code) < MIN_CODE_LENGTH:
        return (f"{env_name} is shorter than {MIN_CODE_LENGTH} characters, too short to "
                "resist guessing; DEPLOY.md shows how to make one")
    if not code.isascii():
        # HTTP headers arrive decoded as latin-1, so such a code never matches.
        return f"{env_name} has characters outside ASCII, which no request can send"
    return None


#: Code problems already written to the log. Every protected request and
#: health check asks; the log says each problem once, not once a request.
_LOGGED: set[str] = set()


def code_problem(env_name: str) -> str | None:
    """That a configured code cannot be used, or None. Public: it names the
    setting, not what is wrong with it; the log says that."""
    detail = _code_detail(env_name)
    if detail is None:
        return None
    if detail not in _LOGGED:
        _LOGGED.add(detail)
        LOG.error("access code unusable: %s", detail)
    return f"{env_name} is misconfigured, so what it protects is refused; the server log says why"


def write_problems() -> list[str]:
    """Writes that are refused for want of a setting, for /api/health: a
    deployment that cannot take approvals is not healthy, even if it serves."""
    return [f"writes needing {name} are refused: it is not set"
            for name in (OPERATOR, INGEST) if not os.environ.get(name) and tokens_required()
            and not (name == OPERATOR and identity.enabled())]


def mode(env_name: str) -> str:
    """'signin', 'token', 'disabled' or 'open' -- reported by the health check."""
    if env_name == OPERATOR and identity.enabled():
        return "disabled" if identity.problems() else "signin"
    if os.environ.get(env_name):
        return "disabled" if code_problem(env_name) else "token"
    return "disabled" if tokens_required() else "open"


def require(env_name: str, counts_as_write: bool = True) -> Callable[..., None]:
    """A FastAPI dependency enforcing the rules above for one token.

    `counts_as_write=False` for reads that need the code (the audit log, node
    positions): they are checked the same way but spend no write budget, so
    an officer reading the log cannot block their own approvals.
    """

    def check(request: Request, authorization: str | None = Header(default=None)) -> None:
        client = request.client.host if request.client else "unknown"
        if env_name == OPERATOR and identity.enabled():
            officer = _signed_in(authorization, client)
            request.state.officer = officer
            budget_key = "officer:" + officer.email
        else:
            budget_key = _code_holder(env_name, authorization, client)
        if counts_as_write and (wait := BUDGETS[env_name].retry_after(budget_key)) is not None:
            raise _too_many(wait)

    return check


def _signed_in(authorization: str | None, client: str) -> identity.Officer:
    """The signed-in officer, or the reason there is none. Failed sign-ins
    spend the same per-address budget as wrong codes."""
    problem = next(iter(identity.problems()), None)
    if problem:
        raise HTTPException(503, f"Refused: {problem}")
    scheme, _, token = (authorization or "").partition(" ")
    try:
        if scheme.lower() != "bearer" or not token.strip():
            raise HTTPException(401, "Sign in with Google to do this",
                                headers={"WWW-Authenticate": "Bearer"})
        return identity.verify(token.strip())
    except HTTPException as exc:
        if exc.status_code == 401 and (wait := FAILED_ATTEMPTS.retry_after(client)) is not None:
            raise _too_many(wait) from exc
        raise


def officer_of(request: Request) -> identity.Officer | None:
    """Who signed in for this request, if sign-in is in use."""
    found: object = getattr(request.state, "officer", None)
    return found if isinstance(found, identity.Officer) else None


def _code_holder(env_name: str, authorization: str | None, client: str) -> str:
    """Check the access code (or its absence) by the rules above; return the
    key the write budget is counted under."""
    expected = os.environ.get(env_name, "")
    problem = code_problem(env_name)
    if problem:
        raise HTTPException(503, f"Refused: {problem}")
    if not expected:
        if tokens_required():
            raise HTTPException(
                503, f"Writes are disabled on this deployment: {env_name} is not set")
        return f"open:{client}"
    scheme, _, supplied = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(
            supplied.strip().encode(), expected.encode()):
        wait = FAILED_ATTEMPTS.retry_after(client)
        if wait is not None:
            raise _too_many(wait)
        raise HTTPException(401, "A valid access code is required for this action",
                            headers={"WWW-Authenticate": "Bearer"})
    return "code:" + hashlib.sha256(expected.encode()).hexdigest()[:16]

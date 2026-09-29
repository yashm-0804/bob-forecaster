"""One place that knows how to start Earth Engine, and whether it can.

Earth Engine needs two things: a Cloud project registered for Earth Engine,
and credentials on this machine from `earthengine authenticate`. The project
comes from EE_PROJECT (usually set in .env); there is no default, so a run
never bills a project it was not told to use. The credentials are personal
and never live in the repository.

Every caller asks `availability()` first and gets a reason in plain words when
the answer is no, so a missing sign-in shows up as a sentence in the console
rather than a stack trace. Setting EARTHENGINE_OFF keeps a run offline even
on a signed-in machine -- the test suite does this, so it never depends on
the network or on whose laptop it runs on.
"""

from __future__ import annotations

import os

from common.errors import reraise_bugs

_state: dict[str, object] = {"ready": False, "reason": "not yet initialised"}


def project() -> str | None:
    """The Cloud project to bill Earth Engine to. Deliberately no default:
    a run on someone else's machine must name its own project."""
    return os.environ.get("EE_PROJECT") or None


def initialise(project_id: str | None = None) -> bool:
    """Start Earth Engine once. Returns whether it is usable."""
    if _state["ready"]:
        return True
    if os.environ.get("EARTHENGINE_OFF"):
        # Tests and offline replays: never touch the network, and say why.
        _state["reason"] = "Earth Engine switched off for this run (EARTHENGINE_OFF is set)"
        return False
    chosen = project_id or project()
    if not chosen:
        _state["reason"] = "no Earth Engine project set (put EE_PROJECT in .env)"
        return False
    try:
        import ee
    except ImportError:
        _state["reason"] = "earthengine-api is not installed"
        return False
    try:
        ee.Initialize(project=chosen)
        # Initialize can succeed lazily; one tiny server call proves access.
        ee.Number(1).getInfo()
    except Exception as exc:  # noqa: BLE001 - every failure becomes a reason
        reraise_bugs(exc)          # a bug is not a failed source
        text = str(exc)
        if "authenticate" in text.lower() or "credentials" in text.lower():
            _state["reason"] = ("this machine is not signed in to Earth Engine "
                                "(run: earthengine authenticate)")
        elif "not registered" in text.lower() or "permission" in text.lower():
            _state["reason"] = ("the Earth Engine project (EE_PROJECT) is not registered "
                                "or not permitted")
        else:
            _state["reason"] = f"Earth Engine unavailable: {text[:160]}"
        return False
    _state["ready"] = True
    # The project id stays out of the reason: reasons are exported into the
    # published run files, and the id is the owner's business.
    _state["reason"] = "signed in to Earth Engine"
    return True


def availability() -> tuple[bool, str]:
    ok = initialise()
    return ok, str(_state["reason"])

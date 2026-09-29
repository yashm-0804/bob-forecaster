"""What the API accepts and returns, as typed models, so the schema at
/openapi.json says what each route really sends."""

from __future__ import annotations

import unicodedata

from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator


class OperatorAction(BaseModel):
    """Who is acting, and why. Bounded, so the audit log cannot be stuffed."""

    operator: str = Field(max_length=120)
    note: str = Field(default="", max_length=500)

    @field_validator("operator", "note")
    @classmethod
    def _printable(cls, value: str) -> str:
        value = value.strip()
        # Control and format characters (Cc, Cf -- including the bidi
        # overrides that can make a name read differently from how it is
        # stored) and line or paragraph separators have no place in a name.
        if any(unicodedata.category(c) in ("Cc", "Cf", "Zl", "Zp") for c in value):
            raise ValueError("control or invisible formatting characters are not allowed")
        return value


class Dispatcher(OperatorAction):
    """Who is dispatching. Optional: the approval is the accountable act,
    but a name given here is recorded against the dispatch itself."""

    operator: str = Field(default="", max_length=120)


class RunListing(BaseModel):
    """One replay the console can open."""

    storm: str
    lead_hours: int
    file: str


class Approval(BaseModel):
    identifier: str
    approved: bool
    operator: str
    note: str = ""
    at: str


class Withdrawal(BaseModel):
    identifier: str
    approved: bool
    operator: str


class DispatchReceipt(BaseModel):
    """What would be sent, and on whose approval. Nothing is sent."""

    dispatched: bool
    reason: str
    would_send_to: str
    channels: list[str]
    languages: list[str]
    approved_by: str
    dispatched_by: str | None
    cap_status: str
    payload_bytes: int


class Health(BaseModel):
    ok: bool
    problems: list[str]
    runs: int
    writes: dict[str, str]
    audit_log: dict[str, bool]


def named(req: OperatorAction) -> str:
    """The accountable operator's name, or a 400 saying what is missing."""
    if not req.operator:
        raise HTTPException(400, "An approval must name the operator accountable for it")
    if len(req.operator) < 3:
        raise HTTPException(400, "Name the accountable operator in full, not an initial")
    return req.operator

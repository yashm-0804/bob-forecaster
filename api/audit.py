"""Approval state and its audit trail, persisted.

Approvals used to live in a dict and vanished on restart -- awkward in a demo,
unacceptable in the thing an approval is for, which is accountability. Every
action is now appended to SQLite and never updated or deleted: an approval,
a revocation, and every dispatch attempt, including the ones that were
refused. Whether an advisory is currently approved is derived from that log,
so the history cannot disagree with the state.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from common.sqlite import connect

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "audit.sqlite3"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    at          TEXT NOT NULL,
    identifier  TEXT NOT NULL,
    action      TEXT NOT NULL CHECK (action IN
                ('approve', 'revoke', 'dispatch_allowed', 'dispatch_refused')),
    operator    TEXT,
    note        TEXT,
    recipient   TEXT,
    severity    TEXT
);
CREATE INDEX IF NOT EXISTS events_by_id ON events (identifier, id);
"""


class AuditStore(Protocol):
    """What the API needs of an audit trail: this SQLite log, or the BigQuery
    one (api/bigquery_audit.py). Both are append-only, and derive approval
    state from the trail."""

    def record(self, identifier: str, action: str, operator: str | None = None,
               note: str = "", recipient: str = "", severity: str = "") -> dict[str, Any]: ...

    def withdraw(self, identifier: str, operator: str, note: str = "",
                 recipient: str = "", severity: str = "") -> dict[str, Any] | None: ...

    def dispatch(self, identifier: str, actor: str | None, recipient: str = "",
                 severity: str = "") -> dict[str, Any] | None: ...

    def probe(self) -> None: ...

    def current(self, identifier: str) -> dict[str, Any] | None: ...

    def current_many(self, identifiers: list[str]) -> dict[str, dict[str, Any]]: ...

    def history(self, identifier: str | None = None) -> list[dict[str, Any]]: ...


class AuditLog:
    def __init__(self, path: Path = DEFAULT_DB) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Re-entrant: `dispatch` and `withdraw` check and record as one step,
        # and `record` takes the same lock.
        self._lock = threading.RLock()
        with self._connect() as db:
            db.executescript(_SCHEMA)

    def _connect(self) -> AbstractContextManager[sqlite3.Connection]:
        return connect(self.path)

    def record(self, identifier: str, action: str, operator: str | None = None,
               note: str = "", recipient: str = "", severity: str = "") -> dict[str, Any]:
        at = datetime.now(UTC).isoformat(timespec="seconds")
        with self._lock, self._connect() as db:
            db.execute(
                "INSERT INTO events (at, identifier, action, operator, note, recipient, severity)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (at, identifier, action, operator, note, recipient, severity),
            )
        return {"at": at, "identifier": identifier, "action": action, "operator": operator}

    def withdraw(self, identifier: str, operator: str, note: str = "",
                 recipient: str = "", severity: str = "") -> dict[str, Any] | None:
        """Record a revocation if an approval stands, else record nothing and
        return None. One step under the lock, so two officers withdrawing at
        once leave one revocation, not a revocation of nothing."""
        with self._lock:
            if self.current(identifier) is None:
                return None
            at = datetime.now(UTC).isoformat(timespec="seconds")
            with self._connect() as db:
                db.execute(
                    "INSERT INTO events (at, identifier, action, operator, note, recipient,"
                    " severity) VALUES (?, ?, 'revoke', ?, ?, ?, ?)",
                    (at, identifier, operator, note, recipient, severity),
                )
        return {"at": at, "identifier": identifier, "action": "revoke", "operator": operator}

    def dispatch(self, identifier: str, actor: str | None, recipient: str = "",
                 severity: str = "") -> dict[str, Any] | None:
        """Check for a standing approval and record the dispatch attempt as one
        step under the lock: allowed (naming the approver) if one stands, else
        refused. Returns the approval, or None if there was none.

        Checking and recording separately let a revocation land between them,
        and a dispatch be recorded against an approval already withdrawn.
        """
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
        """Raise if the log cannot be read (see /api/health)."""
        with self._connect() as db:
            db.execute("SELECT 1 FROM events LIMIT 1").fetchall()

    def current(self, identifier: str) -> dict[str, Any] | None:
        """The standing approval, or None: the latest approve/revoke decides."""
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM events WHERE identifier = ? AND action IN ('approve','revoke')"
                " ORDER BY id DESC LIMIT 1", (identifier,),
            ).fetchone()
        if row is None or row["action"] == "revoke":
            return None
        return {"operator": row["operator"], "note": row["note"], "at": row["at"]}

    def current_many(self, identifiers: list[str]) -> dict[str, dict[str, Any]]:
        """Standing approvals for many advisories in one query: serving a run
        used to open one connection per advisory."""
        if not identifiers:
            return {}
        # The identifiers travel as one JSON parameter, so the SQL text is
        # fixed: nothing is ever formatted into it, however many there are.
        with self._connect() as db:
            rows = db.execute(
                "SELECT e.* FROM events e JOIN (SELECT identifier, MAX(id) AS last FROM events"
                " WHERE action IN ('approve','revoke')"
                " AND identifier IN (SELECT value FROM json_each(?))"
                " GROUP BY identifier) m ON e.id = m.last",
                (json.dumps(identifiers),),
            ).fetchall()
        return {r["identifier"]: {"operator": r["operator"], "note": r["note"], "at": r["at"]}
                for r in rows if r["action"] == "approve"}

    def history(self, identifier: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as db:
            if identifier:
                rows = db.execute("SELECT * FROM events WHERE identifier = ? ORDER BY id",
                                  (identifier,)).fetchall()
            else:
                rows = db.execute("SELECT * FROM events ORDER BY id DESC LIMIT 200").fetchall()
        return [dict(r) for r in rows]

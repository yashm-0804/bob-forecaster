"""One way to open SQLite: commit or roll back, then always close.

`with sqlite3.connect(...) as db` only ends the transaction; the connection
stays open until garbage collection. Both stores open one per request, so
that leaked a connection per request.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def connect(path: Path) -> Generator[sqlite3.Connection]:
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    try:
        with db:
            yield db
    finally:
        db.close()

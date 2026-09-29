"""A small sliding-window rate limit for write endpoints.

In memory, per process: on Cloud Run the deploy command caps the service at
one instance, so this is one window for the whole service. It is a brake on
a runaway gateway or a scripted flood of approvals, not a defence against a
determined attacker; that belongs in front of the service (Cloud Armor).
api/access.py applies it only after the access check, keyed by code, so
requests without a valid code cannot spend a code holder's budget.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict, deque
from collections.abc import Callable


class RateLimiter:
    def __init__(self, per_minute: int, clock: Callable[[], float] = time.monotonic,
                 max_clients: int = 10_000) -> None:
        self.per_minute = per_minute
        self.clock = clock
        self.max_clients = max_clients
        self._hits: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = threading.Lock()

    def retry_after(self, client: str) -> int | None:
        """None if this request may proceed (and counts it); otherwise the
        whole seconds until it would be allowed."""
        now = self.clock()
        with self._lock:
            hits = self._hits.pop(client, deque())
            while hits and now - hits[0] >= 60.0:
                hits.popleft()
            self._hits[client] = hits          # most recently seen goes last
            while len(self._hits) > self.max_clients:
                self._hits.popitem(last=False)  # forget the longest-idle client
            if len(hits) >= self.per_minute:
                return max(1, int(60.0 - (now - hits[0])) + 1)
            hits.append(now)
            return None

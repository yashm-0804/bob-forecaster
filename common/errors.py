"""Telling a failed data source from a bug.

Every external source here degrades with a reason instead of stopping a
forecast cycle: a missing satellite pass, an archive that is down, a model
that is overloaded. Catching broadly for that also catches the code's own
mistakes, and would turn a bug into a line of provenance that reads like a
data-source failure. These exceptions only ever mean a bug, so the handlers
let them through (`reraise_bugs`), and tests and replays fail loudly on them.
"""

from __future__ import annotations

#: Exceptions no network, archive or model failure raises here. ImportError is
#: not among them: a missing optional dependency is an environment's state,
#: and each source reports it as its reason.
BUGS: tuple[type[BaseException], ...] = (
    TypeError, AttributeError, NameError, AssertionError, NotImplementedError, RecursionError,
)


def reraise_bugs(exc: BaseException) -> None:
    """Raise `exc` again if it is a bug rather than a failed source."""
    if isinstance(exc, BUGS):
        raise exc

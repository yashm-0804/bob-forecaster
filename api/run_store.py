"""The exported runs the console serves: finding them, reading and checking
them once per change, and looking advisories up across all of them.

One bad file costs that run, never the others: it raises `RunFileError`,
which the API turns into a 503 naming the file, and /api/health lists it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, cast

from fastapi import HTTPException

RUNS = Path(__file__).resolve().parent.parent / "data" / "runs"

_RUN_NAME = re.compile(r"(?P<storm>[a-z0-9]+)_(?P<lead>\d+)h\.json")

#: Parsed run files, keyed by path and invalidated when the file changes. An
#: approval looks its advisory up across every run; re-reading and parsing
#: every file (about 2 MB of JSON) on each click was the slowest thing the
#: API did.
_RUN_CACHE: dict[Path, tuple[int, dict[str, Any]]] = {}

#: What every run must have, and of what kind, for the console and the
#: approval routes to work on it.
_RUN_SHAPE: dict[str, type] = {"summary": dict, "grid": dict, "layers": dict,
                               "track": list, "assets": list, "advisories": list}
_ADVISORY_SHAPE: dict[str, type] = {"identifier": str, "recipient": str, "severity": str,
                                    "languages": list, "cap_xml": str}

RunEntry = tuple[Path, str, int]


class RunFileError(Exception):
    """A run file that cannot be served: unreadable, not JSON, or not shaped
    like a run. One bad file costs that run, never the others."""


def run_files() -> list[RunEntry]:
    """(path, storm, lead) for every run the exporter wrote, sorted.

    The one place run files are found. Anything else in the folder -- a
    backup, a note -- is not a run and is never listed, read or counted; a
    stray file once made every approval return 500.
    """
    if not RUNS.exists():
        return []
    found: list[RunEntry] = []
    for path in sorted(RUNS.glob("*.json")):
        m = _RUN_NAME.fullmatch(path.name)
        if m:
            found.append((path, m["storm"], int(m["lead"])))
    return found


def shape_problem(data: object) -> str | None:
    """What is missing from a run, or None if it is shaped like one."""
    if not isinstance(data, dict):
        return "is not a JSON object"
    run = cast(dict[str, object], data)
    wrong = [k for k, kind in _RUN_SHAPE.items() if not isinstance(run.get(k), kind)]
    if wrong:
        return f"has no valid {', '.join(wrong)}"
    for adv in cast(list[object], run["advisories"]):
        fields = cast(dict[str, object], adv) if isinstance(adv, dict) else {}
        bad = [k for k, kind in _ADVISORY_SHAPE.items() if not isinstance(fields.get(k), kind)]
        if bad:
            return f"has an advisory without a valid {', '.join(bad)}"
    return None


def read_run(path: Path) -> dict[str, Any]:
    """A run, parsed and checked once per change to its file."""
    try:
        stamp = path.stat().st_mtime_ns
        hit = _RUN_CACHE.get(path)
        if hit is None or hit[0] != stamp:
            data: object = json.loads(path.read_text())
            problem = shape_problem(data)
            if problem:
                raise RunFileError(f"{path.name} {problem}")
            hit = (stamp, cast(dict[str, Any], data))
            _RUN_CACHE[path] = hit
    except (OSError, ValueError) as exc:
        raise RunFileError(f"{path.name} cannot be read ({type(exc).__name__})") from exc
    return hit[1]


def run_status() -> tuple[list[RunEntry], list[str]]:
    """The run files that can be served, and a reason for each that cannot."""
    readable: list[RunEntry] = []
    problems: list[str] = []
    for entry in run_files():
        try:
            read_run(entry[0])
        except RunFileError as exc:
            problems.append(f"run file {exc}")
        else:
            readable.append(entry)
    return readable, problems


def readable_runs() -> list[RunEntry]:
    """The run files that can be served; `run_status` says why others cannot."""
    return run_status()[0]


def load_run(storm: str, lead: int) -> dict[str, Any]:
    """A run as stored. Shared and cached: callers must not modify it."""
    path = RUNS / f"{storm.lower()}_{lead}h.json"
    if not path.exists():
        raise HTTPException(
            404,
            f"No run for {storm} at {lead}h lead. "
            f"Generate it with: python -c \"import pipeline; "
            f"pipeline.export(pipeline.run('{storm.upper()}', lead_hours={lead}))\"",
        )
    return read_run(path)


_advisories_by_id: tuple[tuple[tuple[Path, int], ...], dict[str, dict[str, Any]]] = ((), {})


def advisory_index() -> dict[str, dict[str, Any]]:
    """Every exported advisory by identifier, rebuilt only when a run file is
    added, removed or rewritten. An approval used to scan every run."""
    global _advisories_by_id
    files = readable_runs()
    stamp = tuple((path, path.stat().st_mtime_ns) for path, _, _ in files)
    if stamp != _advisories_by_id[0]:
        index: dict[str, dict[str, Any]] = {}
        for path, _, _ in files:
            for adv in cast(list[dict[str, Any]], read_run(path).get("advisories", [])):
                index[str(adv["identifier"])] = adv
        _advisories_by_id = (stamp, index)
    return _advisories_by_id[1]


def find_advisory(identifier: str) -> dict[str, Any]:
    """Locate an advisory across every exported run.

    Approval must be anchored to a real advisory. Accepting an arbitrary
    string created an approval record for something that did not exist, which
    would then satisfy the dispatch gate -- a hole in the one subsystem whose
    entire job is to be rigorous.
    """
    adv = advisory_index().get(identifier)
    if adv is None:
        raise HTTPException(404, f"No advisory {identifier} in any exported run")
    return adv

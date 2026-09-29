"""Read local secrets from `.env`, for the command-line entry points only.

`.env` is git-ignored and holds keys such as GEMINI_API_KEY. Only the agent
and run.sh load it; library code reads the environment and nothing else, so
the test suite (which clears these keys) never picks up a real credential.
A variable already set in the shell wins over the file.
"""

from __future__ import annotations

import os
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parent / ".env"


def load(path: Path = ENV_FILE) -> list[str]:
    """Set any unset variables from the file. Returns the names it set."""
    if not path.exists():
        return []
    loaded: list[str] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name, value = name.strip(), value.strip().strip("'\"")
        if name and name not in os.environ:
            os.environ[name] = value
            loaded.append(name)
    return loaded

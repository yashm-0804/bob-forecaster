"""Audit the JavaScript libraries this project ships, as pip-audit does the
Python ones.

    python scripts/js_audit.py              # exit 1 on any finding

The console loads no script from anywhere but its own server: MapLibre is
vendored in web/vendor, and the browser tests' axe-core in tests/e2e/vendor.
Each vendored library has a VENDOR.json naming its npm package, version,
source tarball with npm's integrity hash, and a sha256 for every file. This
checks, for each:

  - every file on disk is listed and matches its hash, so a copy cannot be
    edited or swapped without the manifest saying so;
  - its version has no advisory in the OSV database (npm ecosystem);

and that the console page loads no script or stylesheet from another origin.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ingest.net import https_open, https_request  # noqa: E402

OSV = "https://api.osv.dev/v1/query"
VENDORED = (ROOT / "web" / "vendor", ROOT / "tests" / "e2e" / "vendor")
PAGE = ROOT / "web" / "index.html"
#: A script or stylesheet taken from another origin.
_REMOTE = re.compile(r"<(?:script|link)\b[^>]*\b(?:src|href)=[\"']https?://[^>]*>", re.IGNORECASE)


def manifests() -> list[Path]:
    return sorted(p for folder in VENDORED if folder.exists() for p in folder.glob("*/VENDOR.json"))


def file_problems(manifest_path: Path) -> list[str]:
    """Files that are unlisted, missing, or not the ones the manifest names."""
    manifest: dict[str, Any] = json.loads(manifest_path.read_text())
    folder = manifest_path.parent
    listed: dict[str, str] = manifest["files"]
    on_disk = {p.name for p in folder.iterdir() if p.name not in ("VENDOR.json", "README.md")}
    where = folder.relative_to(ROOT)
    problems = [f"{where}/{name}: not in VENDOR.json" for name in sorted(on_disk - set(listed))]
    problems += [f"{where}/{name}: listed but missing" for name in sorted(set(listed) - on_disk)]
    for name in sorted(set(listed) & on_disk):
        if hashlib.sha256((folder / name).read_bytes()).hexdigest() != listed[name]:
            problems.append(f"{where}/{name}: does not match its sha256 in VENDOR.json")
    return problems


def known_vulnerabilities(name: str, version: str) -> list[str]:
    """OSV advisories for this npm package at this version."""
    body = json.dumps({"package": {"name": name, "ecosystem": "npm"}, "version": version})
    req = https_request(OSV, data=body.encode(), headers={"Content-Type": "application/json"})
    with https_open(req, timeout=30) as resp:
        reply: dict[str, Any] = json.loads(resp.read().decode())
    return [str(v.get("id")) for v in reply.get("vulns", [])]


def remote_assets(html: str) -> list[str]:
    """Scripts and stylesheets the page would load from another origin."""
    return [tag[:100] for tag in _REMOTE.findall(html)]


def main() -> int:
    problems = [f"web/index.html loads from another origin: {tag}"
                for tag in remote_assets(PAGE.read_text())]
    audited: list[str] = []
    for path in manifests():
        manifest: dict[str, Any] = json.loads(path.read_text())
        name, version = str(manifest["name"]), str(manifest["version"])
        audited.append(f"{name} {version}")
        problems += file_problems(path)
        problems += [f"{name} {version}: {vuln}" for vuln in known_vulnerabilities(name, version)]
    if problems:
        print(f"js audit: {len(problems)} finding(s)")
        for problem in problems:
            print(f"  {problem}")
        return 1
    print(f"js audit: no known vulnerabilities, files as vendored: {', '.join(audited)};"
          " the console loads nothing from another origin")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Look for credentials in the repository: every tracked file, and every
change in every commit of its history.

    python scripts/secret_scan.py            # exit 1 if anything is found

What it looks for:

  - known credential formats: Google API keys (the older AIza form and the
    newer AQ. form Gemini keys use), AWS access keys, private-key blocks,
    GitHub and Slack tokens, a service-account key file;
  - the actual values in the local .env, if there is one -- the surest check
    that the key this project runs with has never been committed. A setting
    named as a credential (KEY, TOKEN, SECRET, PASSWORD ...) found anywhere
    fails the scan; any other long value, such as a cloud project id, is an
    identifier rather than a credential, and is listed as a note: whether it
    should be scrubbed from history is the owner's call, not this script's;
  - that .env is ignored by git, by the Docker build and by gcloud's upload,
    and that no commit has ever contained it.

A finding names the file (and commit) and the kind of secret, never the
value. Test code that builds fake credentials at run time is not a finding:
the scanner matches literal text only.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Credential formats, by name. Each is specific enough that a match in this
#: repository would be a real secret, not a false alarm on prose.
PATTERNS: dict[str, re.Pattern[str]] = {
    "Google API key": re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"),
    "Google API key (AQ. form, as Gemini issues)": re.compile(r"\bAQ\.[0-9A-Za-z_\-]{40,}"),
    "AWS access key id": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "private key block": re.compile(
        r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----"),
    "GitHub token": re.compile(r"\bgh[pousr]_[0-9A-Za-z]{36,}\b"),
    "Slack token": re.compile(r"\bxox[abprs]-[0-9A-Za-z-]{10,}\b"),
    "service-account key file": re.compile(r'"type"\s*:\s*"service_account"'),
}

#: .env values shorter than this are settings, not secrets (EARTHENGINE_OFF=1).
MIN_SECRET_LENGTH = 16
#: .env settings whose values are credentials, by name.
SECRET_NAME = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|PRIVATE", re.IGNORECASE)


def env_values(path: Path) -> dict[str, str]:
    """The .env settings long enough to be secrets, by name."""
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        name, sep, value = line.partition("=")
        value = value.strip().strip("'\"")
        if sep and not name.strip().startswith("#") and len(value) >= MIN_SECRET_LENGTH:
            values[name.strip()] = value
    return values


def findings_in(text: str, where: str, own: dict[str, str]) -> list[str]:
    """What in this text looks like a secret, described without its value."""
    found: list[str] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for kind, pattern in PATTERNS.items():
            if pattern.search(line):
                found.append(f"{where}:{lineno}: {kind}")
        for name, value in own.items():
            if value in line:
                found.append(f"{where}:{lineno}: the value of {name} from .env")
    return found


def git(*args: str) -> str:
    """Run git in the repository. Its full path, fixed arguments, no shell."""
    exe = shutil.which("git")
    if exe is None:
        raise RuntimeError("git is needed to scan the history")
    return subprocess.run([exe, *args], cwd=ROOT, capture_output=True, text=True,  # noqa: S603 - fixed argv
                          check=True).stdout


def scan_tree(own: dict[str, str]) -> list[str]:
    """Every tracked file as it is now."""
    found: list[str] = []
    for name in git("ls-files", "-z").split("\0"):
        path = ROOT / name
        if not name or not path.is_file():
            continue
        try:
            text = path.read_text()
        except (UnicodeDecodeError, OSError):
            continue            # binary: no credential format here is binary
        found += findings_in(text, name, own)
    return found


def scan_history(own: dict[str, str]) -> list[str]:
    """Every line any commit ever added, in every branch."""
    found: list[str] = []
    commit, path = "", ""
    for line in git("log", "--all", "-p", "--no-color", "--unified=0",
                    "--format=commit %H").splitlines():
        if line.startswith("commit "):
            commit = line.split()[1][:10]
        elif line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else line[4:]
        elif line.startswith("+") and not line.startswith("+++"):
            found += findings_in(line[1:], f"{commit}:{path}", own)
    return found


def env_file_is_kept_out() -> list[str]:
    """.env must be ignored everywhere it could leave this machine from, and
    must never have been committed."""
    problems: list[str] = []
    for ignore in (".gitignore", ".dockerignore", ".gcloudignore"):
        lines = {line.strip() for line in (ROOT / ignore).read_text().splitlines()}
        if ".env" not in lines:
            problems.append(f"{ignore} does not exclude .env")
    if git("log", "--all", "--format=%H", "--", ".env").strip():
        problems.append(".env appears in the git history")
    if ".env" in git("ls-files").split("\n"):
        problems.append(".env is tracked")
    return problems


def split_env(values: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    """(credentials, identifiers) among the .env values, by setting name."""
    secrets = {k: v for k, v in values.items() if SECRET_NAME.search(k)}
    return secrets, {k: v for k, v in values.items() if k not in secrets}


def _identifier_notes(identifiers: dict[str, str]) -> list[str]:
    """Where identifiers from .env appear: each file once, marked as in the
    current files or only in history."""
    notes: set[str] = set()
    for finding in scan_tree(identifiers):          # "path:line: what"
        where, _, what = finding.partition(": ")
        notes.add(f"{where.rsplit(':', 1)[0]} (current files): {what}")
    for finding in scan_history(identifiers):       # "commit:path:line: what"
        where, _, what = finding.partition(": ")
        notes.add(f"{where.rsplit(':', 1)[0].split(':', 1)[1]} (history): {what}")
    return sorted(notes)


def history_problem() -> str | None:
    """Why the history cannot be scanned in full, or None. An export has no
    history, and a shallow clone -- actions/checkout's default -- has one
    commit of it; either would pass a scan that looked at almost nothing."""
    exe = shutil.which("git")
    if exe is None:
        return "git is not installed"
    inside = subprocess.run([exe, "rev-parse", "--is-inside-work-tree"], cwd=ROOT,  # noqa: S603 - fixed argv
                            capture_output=True, text=True, check=False)
    if inside.returncode != 0:
        return "this is not a git checkout (an export?), so there is no history to scan"
    if git("rev-parse", "--is-shallow-repository").strip() == "true":
        return "the clone is shallow; fetch the full history (git fetch --unshallow) to scan it"
    return None


def main() -> int:
    blocked = history_problem()
    if blocked:
        print(f"secret scan: cannot run: {blocked}")
        return 1
    secrets, identifiers = split_env(env_values(ROOT / ".env"))
    problems = env_file_is_kept_out() + scan_tree(secrets) + scan_history(secrets)
    commits = len(git("rev-list", "--all").split())
    files = len([n for n in git("ls-files").split("\n") if n])
    notes = _identifier_notes(identifiers)
    if notes:
        print("secret scan: note -- identifiers from .env (not credentials) appear in:")
        for note in notes:
            print(f"  {note}")
    if problems:
        print(f"secret scan: {len(problems)} finding(s)")
        for problem in sorted(set(problems)):
            print(f"  {problem}")
        return 1
    print(f"secret scan: no credentials in {files} tracked files or {commits} commits"
          f" ({len(PATTERNS)} formats; {len(secrets)} credential value(s) from .env checked)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

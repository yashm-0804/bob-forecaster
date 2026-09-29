"""The secret scan finds credentials in files and in history, and never
prints them. Every fake credential here is assembled at run time, so this
file contains none for the scan of this repository to find."""

import importlib.util
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "secret_scan.py"
_spec = importlib.util.spec_from_file_location("secret_scan", SCRIPT)
assert _spec and _spec.loader
scan = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scan)

# Fakes of each format, built so no literal credential sits in this file.
FAKES = {
    "Google API key": "AI" + "za" + "Sy" + "x" * 33,
    "Google API key (AQ. form, as Gemini issues)": "AQ" + "." + "Ab8" + "y" * 45,
    "AWS access key id": "AK" + "IA" + "Z" * 16,
    "private key block": "-----BEGIN " + "RSA PRIVATE KEY-----",
    "GitHub token": "gh" + "p_" + "a" * 36,
    "Slack token": "xo" + "xb-" + "1" * 12,
    "service-account key file": '"ty' + 'pe": "service' + '_account"',
}


@pytest.mark.parametrize("kind", sorted(FAKES))
def test_each_credential_format_is_found_and_not_printed(kind):
    found = scan.findings_in(f"config = '{FAKES[kind]}'\n", "app/settings.py", {})
    assert found == [f"app/settings.py:1: {kind}"]
    assert FAKES[kind] not in " ".join(found)


def test_prose_and_code_about_keys_are_not_findings():
    text = ("Set GEMINI_API_KEY in .env; the key looks like AIza... or AQ.\n"
            "pattern = re.compile(r'AIza[0-9A-Za-z]{35}')\n"
            "BOB_OPERATOR_TOKEN=operator-code-for-tests\n")
    assert scan.findings_in(text, "README.md", {}) == []


def test_the_local_env_values_are_looked_for_and_short_settings_are_not(tmp_path):
    env = tmp_path / ".env"
    secret = "k" * 20 + "9" * 12
    env.write_text(f"# local secrets\nGEMINI_API_KEY='{secret}'\nEARTHENGINE_OFF=1\n"
                   "EE_PROJECT=my-project-name-12345\n")
    own = scan.env_values(env)
    assert set(own) == {"GEMINI_API_KEY", "EE_PROJECT"}, "a 1 is a setting, not a secret"
    found = scan.findings_in(f"x = {secret}\n", "notes.txt", own)
    assert found == ["notes.txt:1: the value of GEMINI_API_KEY from .env"]
    assert scan.env_values(tmp_path / "missing") == {}


def test_credentials_and_identifiers_in_env_are_told_apart():
    secrets, identifiers = scan.split_env({"GEMINI_API_KEY": "k" * 30, "BOB_OPERATOR_TOKEN": "t" * 30,
                                           "EE_PROJECT": "my-project-12345678"})
    assert set(secrets) == {"GEMINI_API_KEY", "BOB_OPERATOR_TOKEN"}
    assert set(identifiers) == {"EE_PROJECT"}


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                   env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.org",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.org",
                        "HOME": str(repo), "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"})


def test_an_identifier_in_history_is_a_note_and_a_key_is_a_failure(tmp_path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    for ignore in (".gitignore", ".dockerignore", ".gcloudignore"):
        (repo / ignore).write_text(".env\n")
    project, key = "my-cloud-project-4242", "q" * 24 + "7" * 16
    (repo / ".env").write_text(f"EE_PROJECT={project}\nGEMINI_API_KEY={key}\n")
    (repo / "run.json").write_text(f'{{"project": "{project}"}}\n')
    _git(repo, "add", ".gitignore", ".dockerignore", ".gcloudignore", "run.json")
    _git(repo, "commit", "-q", "-m", "a run that names the project")
    monkeypatch.setattr(scan, "ROOT", repo)
    assert scan.main() == 0, "an identifier is a note, not a failure"
    out = capsys.readouterr().out
    assert "run.json (current files): the value of EE_PROJECT from .env" in out
    assert "run.json (history): the value of EE_PROJECT from .env" in out
    assert project not in out and key not in out
    (repo / "notes.txt").write_text(f"key {key}\n")
    _git(repo, "add", "notes.txt")
    _git(repo, "commit", "-q", "-m", "a key")
    assert scan.main() == 1
    assert key not in capsys.readouterr().out


def test_a_secret_committed_then_deleted_is_still_found_in_history(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    for ignore in (".gitignore", ".dockerignore", ".gcloudignore"):
        (repo / ignore).write_text(".env\n")
    (repo / "settings.py").write_text(f"KEY = '{FAKES['Google API key']}'\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "oops")
    (repo / "settings.py").write_text("KEY = os.environ['KEY']\n")
    _git(repo, "commit", "-q", "-am", "move the key to the environment")
    monkeypatch.setattr(scan, "ROOT", repo)

    assert scan.scan_tree({}) == [], "the file is clean now"
    history = scan.scan_history({})
    assert len(history) == 1 and history[0].endswith(":settings.py:1: Google API key")
    assert scan.env_file_is_kept_out() == []
    assert scan.main() == 1


def test_an_env_file_that_is_committed_or_not_ignored_is_a_finding(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / ".gitignore").write_text("*.pyc\n")
    (repo / ".dockerignore").write_text(".env\n")
    (repo / ".gcloudignore").write_text(".env\n")
    (repo / ".env").write_text("EARTHENGINE_OFF=1\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "everything")
    monkeypatch.setattr(scan, "ROOT", repo)
    problems = scan.env_file_is_kept_out()
    assert scan.main() == 1
    assert ".gitignore does not exclude .env" in problems
    assert ".env appears in the git history" in problems and ".env is tracked" in problems


def test_an_export_or_a_shallow_clone_is_refused_not_passed(tmp_path, monkeypatch, capsys):
    """Found in rehearsal: in a git export the scan crashed; and CI's default
    checkout is one commit deep, where a history scan would look at nothing."""
    export = tmp_path / "export"
    export.mkdir()
    monkeypatch.setattr(scan, "ROOT", export)
    assert scan.main() == 1
    assert "not a git checkout" in capsys.readouterr().out

    origin = tmp_path / "origin"
    origin.mkdir()
    _git(origin, "init", "-q")
    for n in range(3):
        (origin / "f.txt").write_text(str(n))
        _git(origin, "add", ".")
        _git(origin, "commit", "-q", "-m", f"c{n}")
    shallow = tmp_path / "shallow"
    subprocess.run(["git", "clone", "-q", "--depth", "1", f"file://{origin}", str(shallow)],
                   check=True, capture_output=True)
    monkeypatch.setattr(scan, "ROOT", shallow)
    assert scan.main() == 1
    assert "shallow" in capsys.readouterr().out

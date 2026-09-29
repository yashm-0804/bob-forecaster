"""The JavaScript library audit: vendored files must match their manifest,
known advisories fail it, and the page may load nothing from elsewhere."""

import hashlib
import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "js_audit.py"
_spec = importlib.util.spec_from_file_location("js_audit", SCRIPT)
assert _spec and _spec.loader
audit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(audit)


def _vendor(tmp_path, files):
    folder = tmp_path / "vendor" / "lib"
    folder.mkdir(parents=True)
    for name, text in files.items():
        (folder / name).write_text(text)
    manifest = {"name": "lib", "version": "1.0.0", "files": {
        name: hashlib.sha256(text.encode()).hexdigest() for name, text in files.items()}}
    (folder / "VENDOR.json").write_text(json.dumps(manifest))
    return folder


def test_the_shipped_libraries_match_their_manifests():
    paths = audit.manifests()
    assert {json.loads(p.read_text())["name"] for p in paths} == {"maplibre-gl", "axe-core", "firebase"}
    for path in paths:
        assert audit.file_problems(path) == [], path


def test_an_edited_extra_or_missing_file_is_a_finding(tmp_path, monkeypatch):
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    folder = _vendor(tmp_path, {"lib.mjs": "export const x = 1;", "LICENSE": "BSD"})
    assert audit.file_problems(folder / "VENDOR.json") == []
    (folder / "lib.mjs").write_text("export const x = 2; fetch('https://evil.example')")
    (folder / "extra.js").write_text("")
    (folder / "LICENSE").unlink()
    problems = " ".join(audit.file_problems(folder / "VENDOR.json"))
    assert "lib.mjs: does not match its sha256" in problems
    assert "extra.js: not in VENDOR.json" in problems and "LICENSE: listed but missing" in problems


def test_a_known_advisory_fails_the_audit_and_none_passes(monkeypatch, capsys):
    """The MapLibre version the console used to load (4.7.1) has
    GHSA-jrc7-96c5-q579; the audit found it, which is why it is vendored at
    6.11.2 now."""
    monkeypatch.setattr(audit, "known_vulnerabilities",
                        lambda name, version: ["GHSA-jrc7-96c5-q579"] if name == "maplibre-gl" else [])
    assert audit.main() == 1
    assert "maplibre-gl 6.11.2: GHSA-jrc7-96c5-q579" in capsys.readouterr().out
    monkeypatch.setattr(audit, "known_vulnerabilities", lambda name, version: [])
    assert audit.main() == 0


def test_the_query_names_the_npm_package_and_version(monkeypatch):
    sent = {}

    class Reply:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b'{"vulns": [{"id": "GHSA-x"}]}'

    def fake_open(req, timeout):
        sent.update(url=req.full_url, body=json.loads(req.data))
        return Reply()

    monkeypatch.setattr(audit, "https_open", fake_open)
    assert audit.known_vulnerabilities("maplibre-gl", "4.7.1") == ["GHSA-x"]
    assert sent["url"] == "https://api.osv.dev/v1/query"
    assert sent["body"] == {"package": {"name": "maplibre-gl", "ecosystem": "npm"}, "version": "4.7.1"}


def test_a_script_from_another_origin_is_a_finding():
    assert audit.remote_assets('<script src="/static/app.js"></script>') == []
    page = ('<link rel="stylesheet" href="https://cdn.example/x.css">'
            '<script type="module" src="http://cdn.example/x.mjs"></script>')
    assert len(audit.remote_assets(page)) == 2
    assert audit.remote_assets(audit.PAGE.read_text()) == [], "the console loads nothing from elsewhere"

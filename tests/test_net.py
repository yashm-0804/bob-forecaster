"""TLS setup, in one place; and every download goes through `ingest.net`,
only over HTTPS."""

import os
import ssl
import urllib.request

import pytest

from ingest import net


def test_the_context_verifies_certificates():
    ctx = net.tls_context()
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname
    assert ctx.cert_store_stats()["x509_ca"] > 0, "a CA bundle was loaded"


def test_the_global_default_respects_an_existing_setting(monkeypatch):
    monkeypatch.setenv("SSL_CERT_FILE", "/already/chosen.pem")
    monkeypatch.setattr(ssl, "_create_default_https_context", ssl._create_default_https_context)
    net.use_certifi_globally()
    assert os.environ["SSL_CERT_FILE"] == "/already/chosen.pem"


@pytest.mark.parametrize("url", ["http://overpass-api.de/api/interpreter", "file:///etc/passwd",
                                 "ftp://example.org/x", "data:text/plain,hi", "/etc/passwd"])
def test_anything_but_https_is_refused_before_a_request_is_made(monkeypatch, url):
    """urllib would open file: and ftp: URLs as readily as https: ones; a
    URL built wrong must fail, not read a local file."""
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: pytest.fail("opened"))
    with pytest.raises(ValueError, match="only https"):
        net.https_request(url)
    with pytest.raises(ValueError, match="only https"):
        net.https_open(url, timeout=5)


def test_https_is_opened_with_the_trusted_context_and_the_timeout(monkeypatch):
    seen = {}

    def urlopen(request, timeout, context):
        seen.update(url=request.full_url if hasattr(request, "full_url") else request,
                    timeout=timeout, context=context)
        return "response"

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    req = net.https_request("https://example.org/data.csv", headers={"User-Agent": "t"},
                            method="HEAD")
    assert req.get_method() == "HEAD" and req.get_header("User-agent") == "t"
    assert net.https_open(req, timeout=7) == "response"
    assert seen["url"] == "https://example.org/data.csv" and seen["timeout"] == 7
    assert isinstance(seen["context"], ssl.SSLContext)
    assert seen["context"].verify_mode == ssl.CERT_REQUIRED, "certificates are checked"

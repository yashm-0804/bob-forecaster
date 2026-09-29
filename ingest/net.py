"""TLS for every outbound request, in one place.

python.org builds of Python on macOS ship without root certificates, so an
HTTPS request fails until something points at a CA bundle. Our own fetchers
pass `tls_context()` explicitly. Third-party code that opens its own
connections -- imdtrack downloading the IMD best track -- cannot be handed a
context, so `use_certifi_globally()` sets the process default; only command
entry points and that one caller use it.
"""

from __future__ import annotations

import os
import ssl
import urllib.parse
import urllib.request
from typing import Any


def tls_context() -> ssl.SSLContext:
    """A context trusting certifi's roots when installed, the system's if not."""
    try:
        import certifi
    except ImportError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


def https_request(url: str, data: bytes | None = None, headers: dict[str, str] | None = None,
                  method: str | None = None) -> urllib.request.Request:
    """A request for an HTTPS URL; any other scheme is refused here, before
    anything is built (see `https_open`)."""
    if urllib.parse.urlsplit(url).scheme != "https":
        raise ValueError(f"only https URLs are fetched, not {url!r}")
    return urllib.request.Request(url, data=data, headers=headers or {},  # noqa: S310 - checked above
                                  method=method)


def https_open(request: str | urllib.request.Request, timeout: float) -> Any:
    """Open an HTTPS URL, trusting `tls_context()`. The one place data comes
    in from the network.

    Anything but https is refused: urllib would also open file: and ftp: URLs,
    and no source here is either -- a URL built wrong must fail, not read a
    local file. Returns urllib's response, which the stdlib types as Any.
    """
    url = request if isinstance(request, str) else request.full_url
    if urllib.parse.urlsplit(url).scheme != "https":
        raise ValueError(f"only https URLs are fetched, not {url!r}")
    return urllib.request.urlopen(request, timeout=timeout,  # noqa: S310 - scheme checked above
                                  context=tls_context())


def use_certifi_globally() -> None:
    """Make certifi's roots the process default, for libraries we cannot
    hand a context to. Leaves an existing SSL_CERT_FILE alone."""
    try:
        import certifi
    except ImportError:
        return
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    # The stdlib's documented hook for the default HTTPS context is a private
    # name; there is no public one to set.
    ssl._create_default_https_context = ssl.create_default_context  # pyright: ignore[reportPrivateUsage]

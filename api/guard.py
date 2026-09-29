"""What every request passes through before a route sees it: the host and
origin checks, the body limits, HEAD as GET, and the headers every response
carries -- the console's content policy among them.

`install(app)` registers them. Each registration wraps the ones before it, so
the order below is the order they run in reverse: compression outermost, then
the response headers, the body limits, HEAD, the host check, and the origin
check nearest the routes.
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, Response

from api import access

#: Where the basemap's style, tiles, glyphs and sprites come from (CARTO), and
#: nothing else: the page talks to this server and the basemap only.
BASEMAP_HOSTS = "https://basemaps.cartocdn.com https://*.basemaps.cartocdn.com"

#: The console page's content policy. No inline script at all: the console's
#: code is /static/app.js and its buttons are wired by one delegated listener,
#: so an injected <script> or onerror= will not run even if escaping ever
#: fails. Scripts come only from this server -- MapLibre included, vendored
#: in web/vendor -- the page cannot be framed (no clickjacking the Approve button),
#: and plugins and <base> rewrites are off. Inline *styles* stay allowed: the
#: panels are styled with style attributes. Tiles, glyphs and sprites come
#: from the basemap's hosts, which are named rather than allowing any https.
CONSOLE_CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",
    f"img-src 'self' data: blob: {BASEMAP_HOSTS}",
    # data: because MapLibre 6 fetches image sources, and the hazard layers
    # are images the console draws itself; reading inline data sends nothing.
    f"connect-src 'self' data: {BASEMAP_HOSTS}",
    # MapLibre starts its tile workers from its own module file, or from a
    # blob: URL where module workers are not supported.
    "worker-src 'self' blob:",
    "child-src blob:",
    "font-src 'self' data:",
    "object-src 'none'",
    "base-uri 'none'",
    "frame-ancestors 'none'",
])

#: Largest request body accepted, bytes. A telemetry message is under 1 KB
#: and an approval a few hundred bytes; nothing legitimate comes close.
MAX_BODY_BYTES = 64 * 1024

#: Deepest JSON nesting accepted. A telemetry message is two levels deep.
MAX_JSON_DEPTH = 32

Next = Callable[[Request], Awaitable[Response]]


async def same_origin_writes(request: Request, call_next: Next) -> Response:
    """Refuse writes that another website makes a visitor's browser send.

    Browsers put an Origin header on every cross-site POST. On a laptop in
    open mode, without this, any page the officer visited could post a
    dispatch to the console on localhost. Clients that are not browsers --
    gateways, curl -- send no Origin and are unaffected.
    """
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        origin = request.headers.get("origin")
        # Host names are case-insensitive; LOCALHOST and localhost are one site.
        host = request.headers.get("host", "").lower()
        if origin is not None and urlsplit(origin).netloc.lower() != host:
            return JSONResponse({"detail": "Cross-site writes are refused"}, status_code=403)
    return await call_next(request)


def allowed_hosts() -> list[str]:
    """The host names this server answers to.

    BOB_ALLOWED_HOSTS, comma-separated, with "*.example.org" for a domain's
    subdomains. Unset: this machine's own names, plus Cloud Run's service
    domain when running there.
    """
    configured = os.environ.get("BOB_ALLOWED_HOSTS", "")
    if configured.strip():
        return [h.strip().lower() for h in configured.split(",") if h.strip()]
    own = ["localhost", "127.0.0.1", "[::1]"]
    return own + ["*.run.app"] if access.managed_platform() else own


def host_allowed(host_header: str, allowed: list[str]) -> bool:
    """Whether a Host header (name, optional port) is one of `allowed`."""
    host = host_header.strip().lower()
    host = host[:host.find("]") + 1] if host.startswith("[") else host.split(":", 1)[0]
    return bool(host) and any(
        pattern == "*" or host == pattern
        or (pattern.startswith("*.") and host.endswith(pattern[1:]))
        for pattern in allowed)


async def trusted_hosts(request: Request, call_next: Next) -> Response:
    """Answer only to this server's own names.

    The same-origin check compares Origin with Host, and a page on a domain
    the attacker points at 127.0.0.1 (DNS rebinding) makes the two agree:
    Host and Origin are both the attacker's name. Refusing unknown Host names
    first is what makes that comparison mean anything.
    """
    if not host_allowed(request.headers.get("host", ""), allowed_hosts()):
        return JSONResponse({"detail": "Unknown host; see BOB_ALLOWED_HOSTS"}, status_code=400)
    return await call_next(request)


async def head_as_get(request: Request, call_next: Next) -> Response:
    """HEAD is GET without the body, for every route that answers GET: uptime
    checks and caches ask with HEAD, and a 405 reads to them as down."""
    if request.method != "HEAD":
        return await call_next(request)
    request.scope["method"] = "GET"
    response = await call_next(request)
    headers = {k: v for k, v in response.headers.items() if k.lower() != "content-length"}
    return Response(status_code=response.status_code, headers=headers)


async def limit_body(request: Request, call_next: Next) -> Response:
    """Refuse oversized writes before they are read into memory."""
    if request.method in ("POST", "PUT", "PATCH"):
        length = request.headers.get("content-length")
        if length is None:
            if request.headers.get("transfer-encoding"):
                return JSONResponse({"detail": "Send a Content-Length"}, status_code=411)
        elif not length.isdigit() or int(length) > MAX_BODY_BYTES:
            return JSONResponse({"detail": f"Request body over {MAX_BODY_BYTES} bytes"},
                                status_code=413)
        # A small body can still be nested thousands deep, which overflows
        # the recursion of the JSON machinery downstream (a 500). Nothing this
        # API accepts is nested more than a few levels.
        if nesting_depth(await request.body()) > MAX_JSON_DEPTH:
            return JSONResponse({"detail": f"Request body nested more than {MAX_JSON_DEPTH} "
                                           "levels deep"}, status_code=400)
    return await call_next(request)


def nesting_depth(body: bytes) -> int:
    """How deep brackets nest in a JSON body, ignoring those inside strings.
    One pass over at most MAX_BODY_BYTES; no parsing, so no recursion."""
    depth = deepest = 0
    in_string = escaped = False
    for byte in body:
        if in_string:
            if escaped:
                escaped = False
            elif byte == 0x5C:          # backslash
                escaped = True
            elif byte == 0x22:          # quote
                in_string = False
        elif byte == 0x22:
            in_string = True
        elif byte in (0x5B, 0x7B):      # [ {
            depth += 1
            deepest = max(deepest, depth)
        elif byte in (0x5D, 0x7D):      # ] }
            depth -= 1
    return deepest


def console_csp() -> str:
    """CONSOLE_CSP, plus what Google sign-in needs when it is configured: its
    helper script and the sign-in frame (apis.google.com, the project's auth
    domain) and the token services. Nothing else from another origin."""
    from api import identity

    if not identity.enabled():
        return CONSOLE_CSP
    google = "https://identitytoolkit.googleapis.com https://securetoken.googleapis.com"
    extra = {"script-src": "https://apis.google.com",
             "connect-src": google + " https://www.googleapis.com",
             "frame-src": f"'self' https://{identity.auth_domain()} https://apis.google.com"}
    parts = [p + (" " + extra.pop(p.split(" ")[0]) if p.split(" ")[0] in extra else "")
             for p in CONSOLE_CSP.split("; ")]
    return "; ".join(parts + [f"{k} {v}" for k, v in extra.items()])


async def security_headers(request: Request, call_next: Next) -> Response:
    """Headers every response carries, whatever produced it."""
    response = await call_next(request)
    # The console is reachable at / and /static/index.html; both get the
    # policy. The API documentation pages set their own (see api/docs.py).
    html = response.headers.get("content-type", "").startswith("text/html")
    if html:
        response.headers.setdefault("Content-Security-Policy", console_csp())
    # The console's page and scripts are checked with the server on every
    # load (an unchanged file costs a 304): without this a browser kept an
    # old copy after an update, and the new sign-in button never appeared.
    path = request.url.path
    if path == "/" or path.startswith("/static/"):
        response.headers.setdefault("Cache-Control", "no-cache")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Frame-Options", "DENY")
    if access.managed_platform():
        # Cloud Run serves only HTTPS; say so, so a browser never tries HTTP.
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    return response


def install(app: FastAPI) -> None:
    """Register every check on `app`, innermost first."""
    for check in (same_origin_writes, trusted_hosts, head_as_get, limit_body, security_headers):
        app.middleware("http")(check)
    # Compress what is worth compressing: a run file is ~260 KB of JSON, sent
    # in 33 KB at level 5 for 1.4 ms. Level 9 saves 2 KB more and costs 6 ms.
    app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=5)

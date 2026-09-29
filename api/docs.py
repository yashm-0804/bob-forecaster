"""The API's own documentation pages: Swagger UI, ReDoc and the schema they
read. On by default on a laptop; off on a deployment unless BOB_API_DOCS=1,
because their UI is loaded from a CDN, unpinned."""

from __future__ import annotations

import base64
import hashlib
import os
import re

from fastapi import APIRouter, HTTPException, Request
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse

from api import access

router = APIRouter(include_in_schema=False)


def docs_enabled() -> bool:
    """The API docs load their UI from a CDN, unpinned; on a deployment they
    are off unless BOB_API_DOCS=1 asks for them."""
    return not access.managed_platform() or os.environ.get("BOB_API_DOCS") == "1"


def _docs_page(page: HTMLResponse, extra: str) -> HTMLResponse:
    """A docs page with a policy of its own: its inline script is allowed by
    hash, not by 'unsafe-inline', so nothing injected into it would run."""
    body = bytes(page.body).decode()
    hashes = " ".join(
        "'sha256-" + base64.b64encode(hashlib.sha256(script.encode()).digest()).decode() + "'"
        for script in re.findall(r"<script>(.*?)</script>", body, flags=re.DOTALL))
    policy = "; ".join([
        "default-src 'none'",
        f"script-src https://cdn.jsdelivr.net {hashes}".strip(),
        "connect-src 'self'",
        "img-src 'self' data: https://fastapi.tiangolo.com https://cdn.redoc.ly",
        extra,
        "base-uri 'none'", "object-src 'none'", "frame-ancestors 'none'",
    ])
    page.headers["Content-Security-Policy"] = policy
    return page


def _refuse_unless_enabled() -> None:
    if not docs_enabled():
        raise HTTPException(404, "Not Found")


@router.get("/openapi.json")
def openapi_schema(request: Request) -> JSONResponse:
    """The API schema, where the docs are on (see `docs_enabled`)."""
    _refuse_unless_enabled()
    return JSONResponse(request.app.openapi())


@router.get("/docs")
def swagger_docs(request: Request) -> HTMLResponse:
    _refuse_unless_enabled()
    return _docs_page(get_swagger_ui_html(openapi_url="/openapi.json", title=request.app.title),
                      "style-src https://cdn.jsdelivr.net")


@router.get("/redoc")
def redoc_docs(request: Request) -> HTMLResponse:
    _refuse_unless_enabled()
    return _docs_page(get_redoc_html(openapi_url="/openapi.json", title=request.app.title),
                      "style-src 'unsafe-inline' https://fonts.googleapis.com; "
                      "font-src https://fonts.gstatic.com; worker-src blob:")

"""Capability-protected localhost application for recovery inspection."""

from __future__ import annotations

import secrets
from importlib import resources
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from agent_ledger.recovery.catalog import (
    RecoveryCatalog,
    SessionSourceChangedError,
    UnknownCandidateError,
)
from agent_ledger.recovery.git_state import (
    RecoveryGitError,
    UnsafeRecoveryPathError,
)
from agent_ledger.recovery.package import (
    ConcurrentRepositoryDriftError,
    assemble_recovery_package,
    receipt_status,
)
from agent_ledger.recovery.prompt import render_recovery_prompt
from agent_ledger.recovery.receipts import ReceiptIntegrityError, ReceiptStore

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from agent_ledger.recovery.models import RecoveryBrief

TOKEN_HEADER = "X-Agent-Ledger-Token"
TOKEN_COOKIE = "agent_ledger_capability"
STATIC_MEDIA_TYPES = {
    "app.css": "text/css; charset=utf-8",
    "app.js": "text/javascript; charset=utf-8",
    "favicon.svg": "image/svg+xml",
}


def _security_headers(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "connect-src 'self'; img-src 'self'; object-src 'none'; "
        "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    )
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=(), payment=()"
    )


def _asset_text(name: str) -> str:
    return (
        resources.files("agent_ledger.api.static")
        .joinpath(name)
        .read_text(encoding="utf-8")
    )


def create_app(
    *,
    capability_token: str,
    brief: RecoveryBrief | None = None,
    prompt: str | None = None,
    catalog: RecoveryCatalog | None = None,
    receipt_store: ReceiptStore | None = None,
    allowed_hosts: frozenset[str] | None = None,
    allowed_origins: frozenset[str] | None = None,
    port: int = 8680,
) -> FastAPI:
    """Create a read-only recovery console bound to one capability token.

    Args:
        brief: Optional immutable recovery data for single-session compatibility.
        prompt: Safe prompt paired with ``brief`` in compatibility mode.
        catalog: Optional repository-bound session catalog for Inbox mode.
        receipt_store: Optional private store enabling read-only receipt/package routes.
        capability_token: Unguessable token required for every resource.
        allowed_hosts: Optional exact Host allowlist, primarily for tests.
        allowed_origins: Optional exact Origin allowlist, primarily for tests.
        port: Localhost port used to derive default allowlists.

    Returns:
        Configured FastAPI application with no CORS support.
    """

    if (brief is None) == (catalog is None):
        raise ValueError("configure exactly one recovery source")
    if brief is not None and prompt is None:
        raise ValueError("compatibility mode requires a prompt")

    hosts = allowed_hosts or frozenset({f"127.0.0.1:{port}", f"localhost:{port}"})
    origins = allowed_origins or frozenset(
        {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}
    )
    app = FastAPI(
        title="Agent Ledger Recovery Console",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.middleware("http")
    async def guard_request(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        host = request.headers.get("host", "")
        if host not in hosts:
            denied = JSONResponse({"detail": "invalid host"}, status_code=400)
            _security_headers(denied)
            return denied
        origin = request.headers.get("origin")
        if origin is not None and origin not in origins:
            denied = JSONResponse({"detail": "invalid origin"}, status_code=403)
            _security_headers(denied)
            return denied
        supplied = (
            request.query_params.get("token")
            or request.headers.get(TOKEN_HEADER)
            or request.cookies.get(TOKEN_COOKIE)
        )
        if supplied is None or not secrets.compare_digest(supplied, capability_token):
            denied = JSONResponse({"detail": "capability required"}, status_code=401)
            _security_headers(denied)
            return denied
        response = await call_next(request)
        _security_headers(response)
        return response

    @app.get("/", response_class=HTMLResponse)
    async def console(request: Request) -> Response:
        html = _asset_text("index.html").replace(
            "__CAPABILITY_TOKEN__", capability_token
        )
        response = HTMLResponse(html)
        if request.query_params.get("token") is not None:
            response.set_cookie(
                TOKEN_COOKIE,
                capability_token,
                httponly=True,
                samesite="strict",
                secure=False,
                max_age=3600,
            )
        return response

    @app.get("/static/{asset_name}")
    async def static_asset(asset_name: str) -> Response:
        media_type = STATIC_MEDIA_TYPES.get(asset_name)
        if media_type is None:
            return JSONResponse({"detail": "not found"}, status_code=404)
        return Response(_asset_text(asset_name), media_type=media_type)

    if catalog is None:
        assert brief is not None
        assert prompt is not None

        @app.get("/api/recovery")
        async def recovery() -> Response:
            return JSONResponse(brief.model_dump(mode="json"))

        @app.get("/api/prompt")
        async def recovery_prompt() -> Response:
            return JSONResponse({"prompt": prompt})
    else:

        @app.get("/api/sessions")
        async def sessions() -> Response:
            return JSONResponse(catalog.public.model_dump(mode="json"))

        def selected_recovery(candidate_id: str) -> RecoveryBrief | Response:
            try:
                return catalog.recover(candidate_id)
            except UnknownCandidateError:
                return JSONResponse({"detail": "session not found"}, status_code=404)
            except SessionSourceChangedError:
                return JSONResponse(
                    {"detail": "session source changed; restart discovery"},
                    status_code=409,
                )
            except (RecoveryGitError, UnsafeRecoveryPathError):
                return JSONResponse(
                    {"detail": "session evidence could not be reconciled safely"},
                    status_code=422,
                )

        @app.get("/api/sessions/{candidate_id}/recovery")
        async def catalog_recovery(candidate_id: str) -> Response:
            selected = selected_recovery(candidate_id)
            if isinstance(selected, Response):
                return selected
            return JSONResponse(selected.model_dump(mode="json"))

        @app.get("/api/sessions/{candidate_id}/prompt")
        async def catalog_prompt(candidate_id: str) -> Response:
            selected = selected_recovery(candidate_id)
            if isinstance(selected, Response):
                return selected
            return JSONResponse({"prompt": render_recovery_prompt(selected)})

        if receipt_store is not None:

            @app.get("/api/sessions/{candidate_id}/receipt")
            async def catalog_receipt(candidate_id: str) -> Response:
                selected = selected_recovery(candidate_id)
                if isinstance(selected, Response):
                    return selected
                try:
                    status = receipt_status(
                        catalog=catalog,
                        candidate_id=candidate_id,
                        store=receipt_store,
                    )
                except ReceiptIntegrityError:
                    return JSONResponse(
                        {"detail": "stored receipt failed integrity validation"},
                        status_code=409,
                    )
                return JSONResponse(status.model_dump(mode="json"))

            @app.get("/api/sessions/{candidate_id}/package")
            async def catalog_package(candidate_id: str) -> Response:
                selected = selected_recovery(candidate_id)
                if isinstance(selected, Response):
                    return selected
                try:
                    package = assemble_recovery_package(
                        catalog=catalog,
                        candidate_id=candidate_id,
                        store=receipt_store,
                    )
                except (ConcurrentRepositoryDriftError, ReceiptIntegrityError):
                    return JSONResponse(
                        {"detail": "recovery package changed during assembly"},
                        status_code=409,
                    )
                return Response(
                    package.model_dump_json(indent=2),
                    media_type="application/json",
                    headers={
                        "Content-Disposition": (
                            f'attachment; filename="recovery-{candidate_id}.json"'
                        )
                    },
                )

    return app

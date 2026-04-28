"""Bearer token + IP allowlist guard.

`/health` is exempt; everything else under `/v1/...` requires both checks.
On failure: 401 for bad/missing bearer, 403 for IP outside allowlist.
"""

from __future__ import annotations

import hmac
import logging
from typing import Optional

from fastapi import Request

from .settings import RelaySettings


log = logging.getLogger(__name__)


def _client_ip(request: Request) -> Optional[str]:
    if request.client is None:
        return None
    return request.client.host


def _strip_bearer(header_value: str) -> Optional[str]:
    if not header_value:
        return None
    parts = header_value.split(None, 1)
    if len(parts) != 2:
        return None
    scheme, token = parts
    if scheme.lower() != "bearer":
        return None
    token = token.strip()
    return token or None


def install_auth(app, settings: RelaySettings) -> None:
    """Install a single middleware that enforces IP + bearer for non-/health.

    The middleware is installed on the app object so route modules don't have
    to repeat the dependency on every endpoint.
    """

    @app.middleware("http")
    async def auth_mw(request: Request, call_next):
        path = request.url.path
        # Allowlist health regardless of how it's mounted.
        if path == "/health":
            return await call_next(request)

        # IP allowlist
        ip = _client_ip(request)
        if not ip or not settings.is_ip_allowed(ip):
            log.warning("auth: IP %s outside allowlist", ip)
            return _json_error(403, "forbidden_ip", f"client IP not allowed: {ip}")

        # Bearer
        header = request.headers.get("authorization") or ""
        token = _strip_bearer(header)
        expected = settings.bearer_token
        if not token or not expected or not hmac.compare_digest(token, expected):
            log.warning("auth: bearer rejected from %s on %s", ip, path)
            return _json_error(401, "unauthorized", "missing or invalid bearer token")

        return await call_next(request)


def _json_error(http_status: int, code: str, message: str):
    from starlette.responses import JSONResponse

    return JSONResponse(
        status_code=http_status,
        content={"error": code, "message": message},
    )

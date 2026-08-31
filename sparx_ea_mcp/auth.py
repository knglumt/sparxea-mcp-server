"""
Minimal bearer-token authentication for the HTTP (remote) transport.

This is intentionally simple - a single static shared secret checked with
a constant-time comparison - rather than a full OAuth 2.1 authorization
server. That's a deliberate, documented trade-off (see README.md): Claude's
custom connectors explicitly support plain bearer tokens ("If your
server's documentation shows Authorization: Bearer YOUR_TOKEN, enter
Bearer followed by your token"), so this is enough for a personal or
small-team deployment. If you need per-user accounts, token expiry, or
revocation, implement MCPServer's `token_verifier`/OAuth support instead
of this middleware.
"""

from __future__ import annotations

import hmac

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class BearerTokenMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, token: str):
        super().__init__(app)
        self._token = token

    async def dispatch(self, request: Request, call_next):
        header = request.headers.get("authorization", "")
        expected = f"Bearer {self._token}"
        if not hmac.compare_digest(header, expected):
            return JSONResponse(
                {"error": "unauthorized"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        return await call_next(request)

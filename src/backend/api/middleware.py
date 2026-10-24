from __future__ import annotations

import time
from urllib.parse import urlsplit

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from ..domain.errors import AppError
from ..domain.tokens import verify_token

PUBLIC = {"/api/v1/health", "/api/v1/session/exchange"}


class LocalSecurity(BaseHTTPMiddleware):
    def __init__(self, app, origin: str, secret: str):
        super().__init__(app)
        self.origin, self.secret = origin.rstrip("/"), secret
        self.host = urlsplit(self.origin).netloc

    async def dispatch(self, request, call_next):
        if request.headers.get("host") != self.host:
            return JSONResponse({"error": "Недопустимый Host"}, status_code=403)
        origin = request.headers.get("origin")
        if origin and origin != self.origin:
            return JSONResponse({"error": "Недопустимый Origin"}, status_code=403)
        if request.url.path.startswith("/api/") and request.url.path not in PUBLIC:
            try:
                request.state.user_id = verify_token(
                    self.secret,
                    request.cookies.get("mosprom_session", ""),
                    "session",
                    int(time.time()),
                )
            except AppError as exc:
                return JSONResponse({"error": exc.message, "code": exc.code}, status_code=401)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data: blob:; style-src 'self'; script-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
        )
        return response

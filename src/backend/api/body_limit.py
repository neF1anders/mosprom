from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from ..domain.errors import AppError


class RequestBodyLimit:
    def __init__(self, app: ASGIApp, max_bytes: int = 257 * 1024 * 1024):
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        length = headers.get(b"content-length")
        if length and (not length.isdigit() or int(length) > self.max_bytes):
            await JSONResponse(
                {"error": "Запрос превышает допустимый размер", "code": "request_too_large"},
                status_code=413,
            )(scope, receive, send)
            return
        size = 0

        async def bounded_receive():
            nonlocal size
            message = await receive()
            size += len(message.get("body", b""))
            if size > self.max_bytes:
                raise AppError("Запрос превышает допустимый размер", "request_too_large", 413)
            return message

        await self.app(scope, bounded_receive, send)

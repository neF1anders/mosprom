import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.backend.api.body_limit import RequestBodyLimit
from src.backend.domain.errors import AppError

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "case", ["empty", "exact", "overflow", "chunked", "false_header", "declared_overflow"]
)
async def test_T01_request_bytes_bounded_before_parsing(case):
    app = FastAPI()
    app.add_middleware(RequestBodyLimit, max_bytes=16)

    @app.exception_handler(AppError)
    async def error(request, exc):
        return JSONResponse({"code": exc.code}, status_code=exc.status)

    @app.post("/upload")
    async def upload(request: Request):
        return {"bytes": len(await request.body())}

    async def chunks():
        for _ in range(3):
            yield b"1234567"

    headers = {}
    content = b"" if case == "empty" else b"a" * (17 if case == "overflow" else 16)
    if case in {"chunked", "false_header"}:
        content = chunks()
    if case == "false_header":
        headers["Content-Length"] = "0"
    if case == "declared_overflow":
        headers["Content-Length"] = "1000000000"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/upload", content=content, headers=headers)
    assert response.status_code == (200 if case in {"empty", "exact"} else 413)

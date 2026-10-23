"""Explicit test receiver. Replaces stage two only in integration tests."""

import hashlib
import json

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI()
received: dict[str, str] = {}


@app.post("/cards")
async def card(request: Request):
    key = request.headers.get("idempotency-key", "")
    value = await request.json()
    digest = hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
    if not key:
        return JSONResponse({"error": "idempotency key required"}, status_code=400)
    if key in received and received[key] != digest:
        return JSONResponse({"error": "key payload conflict"}, status_code=409)
    duplicate = key in received
    received[key] = digest
    return {"accepted": True, "duplicate": duplicate}

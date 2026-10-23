from __future__ import annotations

import base64
import hashlib
import hmac
import json
from uuid import uuid4

from .errors import AppError


def sign_token(secret: str, kind: str, expires: int) -> str:
    payload = base64.urlsafe_b64encode(
        json.dumps({"kind": kind, "expires": expires, "nonce": str(uuid4())}).encode()
    ).decode()
    signature = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return payload + "." + signature


def verify_token(secret: str, token: str, kind: str, timestamp: int) -> None:
    try:
        payload, signature = token.split(".")
        expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        valid = (
            hmac.compare_digest(signature, expected)
            and data["kind"] == kind
            and data["expires"] > timestamp
        )
    except (ValueError, KeyError, TypeError):
        valid = False
    if not valid:
        raise AppError("Откройте приложение по ссылке запуска", "unauthorized", 401)

"""Stable hashes for idempotency receipts, cache keys and short ids."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def fingerprint(payload: Any) -> str:
    """Key order never changes the hash, whichever store the payload came from."""
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()


def digest(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:12]

import base64
import hashlib
import hmac
import json

import pytest

from src.backend.domain.tokens import verify_token

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("nonce", ["a", "ab", "abc", "abcd", "abcde"])
def test_unpadded_browser_tokens(nonce):
    secret = "test-secret"
    payload = (
        base64.urlsafe_b64encode(
            json.dumps({"kind": "launch", "expires": 2000, "nonce": nonce}).encode()
        )
        .decode()
        .rstrip("=")
    )
    signature = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    verify_token(secret, payload + "." + signature, "launch", 1000)

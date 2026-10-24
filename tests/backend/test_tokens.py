import base64
import hashlib
import hmac
import json

import pytest

from src.backend.domain.errors import AppError
from src.backend.domain.tokens import sign_token, verify_token

pytestmark = pytest.mark.unit
SECRET = "test-secret"


def signed(data: dict) -> str:
    payload = base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")
    return payload + "." + hmac.new(SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()


@pytest.mark.parametrize("nonce", ["a", "ab", "abc", "abcd", "abcde"])
def test_unpadded_browser_tokens_carry_the_plugin_user(nonce):
    token = signed({"kind": "launch", "expires": 2000, "nonce": nonce, "user_id": "user-7"})
    assert verify_token(SECRET, token, "launch", 1000) == "user-7"


@pytest.mark.parametrize(
    "data",
    [
        {"kind": "launch", "expires": 2000, "nonce": "n"},
        {"kind": "launch", "expires": 2000, "nonce": "n", "user_id": ""},
        {"kind": "launch", "expires": 2000, "nonce": "n", "user_id": "../etc"},
        {"kind": "session", "expires": 2000, "nonce": "n", "user_id": "u"},
        {"kind": "launch", "expires": 10, "nonce": "n", "user_id": "u"},
    ],
)
def test_rejected_tokens(data):
    with pytest.raises(AppError):
        verify_token(SECRET, signed(data), "launch", 1000)


def test_forged_signature_rejected():
    token = sign_token(SECRET, "launch", 2000, "alice")
    payload, _ = token.split(".")
    with pytest.raises(AppError):
        verify_token(SECRET, payload + "." + "0" * 64, "launch", 1000)

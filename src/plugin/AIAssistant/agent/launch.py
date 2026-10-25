import base64
import hashlib
import hmac
import json
import os
import time
import uuid

from . import settings

CONFIG_NAME = "mosprom.json"
LINK_SECONDS = 600


def config_path():
    return os.path.join(settings.data_dir(), CONFIG_NAME)


def app_url(sidecar=None):
    """Ссылка для входа в приложение."""
    if sidecar is not None and sidecar.running():
        origin, secret, user_id = sidecar.origin(), sidecar.secret, sidecar.user_id
    else:
        try:
            with open(config_path(), encoding="utf-8") as stream:
                config = json.load(stream)
            origin, secret = config["origin"], config["secret"]
        except (OSError, ValueError, KeyError, TypeError):
            return None
        user_id = config.get("user_id") or "local"
    claims = {
        "kind": "launch",
        "expires": int(time.time()) + LINK_SECONDS,
        "nonce": str(uuid.uuid4()),
        "user_id": user_id,
    }
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode("utf-8")).decode("ascii")
    signature = hmac.new(
        secret.encode("utf-8"), payload.encode("ascii"), hashlib.sha256
    ).hexdigest()
    return origin.rstrip("/") + "/#launch=" + payload + "." + signature

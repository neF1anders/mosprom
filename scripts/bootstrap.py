"""Standard-library bootstrap: creates .env and prints a one-time launch link for a user.

The STE Slicer plugin builds the same link with the same secret to open the chat.
Usage: python3 scripts/bootstrap.py [user_id]
"""

import base64
import hashlib
import hmac
import json
import os
import secrets
import sys
import time
from pathlib import Path
from uuid import uuid4

path = Path(".env")
if not path.exists() and not os.environ.get("SESSION_SECRET"):
    template = Path(".env.example").read_text()
    path.write_text(
        template.replace("SESSION_SECRET=\n", "SESSION_SECRET=" + secrets.token_urlsafe(48) + "\n")
    )
    path.chmod(0o600)
values = {}
if path.exists():
    for line in path.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
secret = os.environ.get("SESSION_SECRET", values.get("SESSION_SECRET", ""))
if len(secret) < 32:
    raise SystemExit("Set SESSION_SECRET to at least 32 characters")
origin = os.environ.get("APP_ORIGIN", values.get("APP_ORIGIN", "http://localhost:8000"))
user_id = sys.argv[1] if len(sys.argv) > 1 else "local"
payload = base64.urlsafe_b64encode(
    json.dumps(
        {
            "kind": "launch",
            "expires": int(time.time()) + 600,
            "nonce": str(uuid4()),
            "user_id": user_id,
        }
    ).encode()
).decode()
signature = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
print(origin + "/#launch=" + payload + "." + signature)

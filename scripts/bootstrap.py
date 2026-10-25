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
    template = Path(".env.example").read_text(encoding="utf-8")
    path.write_text(
        template.replace(
            "SESSION_SECRET=\n", "SESSION_SECRET=" + secrets.token_urlsafe(48) + "\n"
        ).replace("SLICER_HOST_FOLDER=\n", ""),
        encoding="utf-8",
    )
    path.chmod(0o600)
if path.exists() and "SLICER_HOST_FOLDER=" not in (current := path.read_text(encoding="utf-8")):
    # server.json в Documents
    folder = Path.home() / "Documents" / "STE_AIAssistant"
    # перенос строки обязателен
    separator = "\n" if current and not current.endswith("\n") else ""
    with path.open("a", encoding="utf-8") as stream:
        stream.write(f"{separator}SLICER_HOST_FOLDER={folder}\n")
values = {}
if path.exists():
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
secret = os.environ.get("SESSION_SECRET", values.get("SESSION_SECRET", ""))
if len(secret) < 32:
    raise SystemExit("Set SESSION_SECRET to at least 32 characters")
origin = os.environ.get("APP_ORIGIN", values.get("APP_ORIGIN", "http://localhost:8000"))
user_id = sys.argv[1] if len(sys.argv) > 1 else "local"
plugin_folder = Path(
    os.environ.get("SLICER_HOST_FOLDER")
    or values.get("SLICER_HOST_FOLDER")
    or Path.home() / "Documents" / "STE_AIAssistant"
)
try:
    plugin_folder.mkdir(parents=True, exist_ok=True)
    config = plugin_folder / "mosprom.json"
    config.write_text(
        json.dumps({"origin": origin, "secret": secret, "user_id": user_id}), encoding="utf-8"
    )
    config.chmod(0o600)
except OSError as exc:
    print(f"The plugin config was not written to {plugin_folder}: {exc}", file=sys.stderr)
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

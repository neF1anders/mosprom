"""Local HTTP server: serves the chat page, a small JSON API for it and the MCP endpoint."""
import base64
import binascii
import json
import os
import threading
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from urllib.parse import parse_qs, urlparse

from UM.Logger import Logger

from . import mcp, settings, tools
from .runner import Chat
from .scenarios import SCENARIOS

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8",
                 ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml"}
MAX_BODY = 40 * 1024 * 1024
UPLOAD_KINDS = (".stl", ".obj", ".3mf", ".png", ".jpg", ".jpeg")


class _Server(ThreadingMixIn, HTTPServer):
    daemon_threads = True


class AssistantServer(object):
    def __init__(self):
        self.token = binascii.hexlify(os.urandom(16)).decode("ascii")
        self.chat = Chat()
        self._httpd = None

    def start(self):
        """Bind, write server.json, then serve. A failure leaves nothing running, so the caller may try again."""
        httpd = _Server(("127.0.0.1", 0), _make_handler(self))
        self._httpd = httpd
        try:
            info = {"port": self.port(), "token": self.token, "pid": os.getpid()}
            with open(os.path.join(settings.data_dir(), "server.json"), "w", encoding="utf-8") as stream:
                json.dump(info, stream)
        except Exception:
            self._httpd = None
            httpd.server_close()
            raise
        thread = threading.Thread(target=httpd.serve_forever)
        thread.daemon = True
        thread.start()

    def port(self):
        return self._httpd.server_address[1]

    def url(self):
        return "http://127.0.0.1:%d/?t=%s" % (self.port(), self.token)


def _config_view():
    config = settings.load()
    return {"base_url": config["base_url"], "model": config["model"], "has_key": bool(config["api_key"])}


class _Handler(BaseHTTPRequestHandler):
    """One request; owner is the AssistantServer, set by _make_handler."""
    owner = None
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        Logger.log("d", "AI Assistant http: " + fmt, *args)

    # ---------- helpers
    def _send(self, status, body, content_type="application/json; charset=utf-8"):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _host_ok(self):
        host = self.headers.get("Host", "")
        return host in ("127.0.0.1:%d" % self.owner.port(), "localhost:%d" % self.owner.port())

    def _token_ok(self):
        query = parse_qs(urlparse(self.path).query)
        supplied = self.headers.get("X-Token") or query.get("t", [""])[0]
        bearer = self.headers.get("Authorization", "")
        if bearer.startswith("Bearer "):
            supplied = bearer[7:]
        return supplied == self.owner.token

    def _json_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise ValueError("The request is too large")
        return json.loads(self.rfile.read(length).decode("utf-8") or "{}")

    # ---------- routing
    def do_GET(self):
        if not self._host_ok():
            return self._send(403, {"error": "bad host"})
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/") or parsed.path == "/download":
            if not self._token_ok():
                return self._send(401, {"error": "bad token"})
            return self._guarded(self._api_get, parsed)
        return self._static(parsed.path)

    def do_POST(self):
        if not self._host_ok():
            return self._send(403, {"error": "bad host"})
        if not self._token_ok():
            return self._send(401, {"error": "bad token"})
        parsed = urlparse(self.path)
        if parsed.path == "/mcp":
            return self._guarded(self._mcp, parsed)
        return self._guarded(self._api_post, parsed)

    def _guarded(self, handler, parsed):
        try:
            handler(parsed)
        except ValueError as error:
            self._send(400, {"error": str(error)})
        except Exception as error:
            Logger.logException("w", "AI Assistant request failed")
            self._send(500, {"error": str(error)})

    def _static(self, path):
        name = "index.html" if path in ("/", "") else path.lstrip("/")
        full = os.path.normpath(os.path.join(WEB_DIR, name))
        if not full.startswith(WEB_DIR) or not os.path.isfile(full):
            return self._send(404, {"error": "not found"})
        with open(full, "rb") as stream:
            body = stream.read()
        self._send(200, body, CONTENT_TYPES.get(os.path.splitext(full)[1], "application/octet-stream"))

    # ---------- API for the chat page
    def _api_get(self, parsed):
        if parsed.path == "/api/config":
            return self._send(200, _config_view())
        if parsed.path == "/api/scenarios":
            return self._send(200, [{"title": s["title"], "prompt": s["prompt"]} for s in SCENARIOS])
        if parsed.path == "/api/state":
            return self._send(200, self._state())
        if parsed.path == "/api/events":
            after = int(parse_qs(parsed.query).get("after", ["0"])[0])
            return self._send(200, self.owner.chat.events_since(after))
        if parsed.path == "/download":
            return self._download(parse_qs(parsed.query).get("path", [""])[0])
        self._send(404, {"error": "not found"})

    def _state(self):
        state = tools.state()
        state["changes"] = list(tools.SESSION.changes)
        return state

    def _download(self, path):
        root = os.path.realpath(settings.data_dir("results"))
        full = os.path.realpath(path)
        if not full.startswith(root + os.sep) or not os.path.isfile(full):
            return self._send(404, {"error": "not found"})
        with open(full, "rb") as stream:
            self._send(200, stream.read(), "application/octet-stream")

    def _api_post(self, parsed):
        body = self._json_body()
        if parsed.path == "/api/config":
            if body.get("forget_session"):
                settings.forget_session()
            settings.save(body.get("base_url"), body.get("api_key"), body.get("model"), body.get("persist", True))
            return self._send(200, _config_view())
        if parsed.path == "/api/upload":
            return self._send(200, self._upload(body))
        if parsed.path == "/api/chat":
            text = (body.get("text") or "").strip()
            if not text:
                raise ValueError("The message is empty")
            try:
                self.owner.chat.send(text, body.get("uploads") or [], int(body.get("scenario", -1)))
            except RuntimeError as error:
                raise ValueError(str(error))
            return self._send(200, {"ok": True})
        if parsed.path == "/api/reset":
            self.owner.chat.reset()
            return self._send(200, {"ok": True})
        self._send(404, {"error": "not found"})

    def _upload(self, body):
        name = os.path.basename(body.get("name") or "")
        if os.path.splitext(name)[1].lower() not in UPLOAD_KINDS:
            raise ValueError("Supported files: STL, OBJ, 3MF, PNG, JPG")
        try:
            data = base64.b64decode(body.get("data") or "")
        except (ValueError, TypeError):
            raise ValueError("The file is not valid base64")
        upload_id = uuid.uuid4().hex[:12]
        path = os.path.join(settings.data_dir("uploads"), upload_id + "_" + name)
        with open(path, "wb") as stream:
            stream.write(data)
        kind = self.owner.chat.add_upload(upload_id, name, path)
        return {"id": upload_id, "name": name, "kind": kind, "path": path}

    # ---------- MCP
    def _mcp(self, parsed):
        try:
            request = self._json_body()
        except ValueError:
            return self._send(200, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
        if isinstance(request, list):
            responses = [r for r in (mcp.handle(item) for item in request) if r is not None]
            return self._send(200, responses) if responses else self._send(202, b"", "text/plain")
        response = mcp.handle(request)
        if response is None:
            return self._send(202, b"", "text/plain")
        self._send(200, response)


def _make_handler(owner):
    return type("Handler", (_Handler,), {"owner": owner})

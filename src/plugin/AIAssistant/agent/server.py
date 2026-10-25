import binascii
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

from UM.Logger import Logger

from . import mcp, settings

MAX_BODY = 40 * 1024 * 1024


class _Server(ThreadingMixIn, HTTPServer):
    daemon_threads = True


class AssistantServer(object):
    def __init__(self):
        self.token = binascii.hexlify(os.urandom(16)).decode("ascii")
        self._httpd = None

    def start(self):
        """Привязывает порт и запускает сервер."""
        httpd = _Server(("127.0.0.1", 0), _make_handler(self))
        self._httpd = httpd
        try:
            info = {"port": self.port(), "token": self.token, "pid": os.getpid()}
            with open(
                os.path.join(settings.data_dir(), "server.json"), "w", encoding="utf-8"
            ) as stream:
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


class _Handler(BaseHTTPRequestHandler):
    """Один запрос к серверу."""

    owner = None
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        Logger.log("d", "AI Assistant http: " + fmt, *args)

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
        supplied = self.headers.get("X-Token") or ""
        bearer = self.headers.get("Authorization", "")
        if bearer.startswith("Bearer "):
            supplied = bearer[7:]
        return supplied == self.owner.token

    def do_GET(self):
        self._send(404, {"error": "not found"})

    def do_POST(self):
        if not self._host_ok():
            return self._send(403, {"error": "bad host"})
        if not self._token_ok():
            return self._send(401, {"error": "bad token"})
        if self.path.split("?", 1)[0] != "/mcp":
            return self._send(404, {"error": "not found"})
        try:
            self._mcp()
        except Exception as error:
            Logger.logException("w", "AI Assistant request failed")
            self._send(500, {"error": str(error)})

    def _mcp(self):
        length = int(self.headers.get("Content-Length") or 0)
        try:
            if length > MAX_BODY:
                raise ValueError("The request is too large")
            request = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except ValueError:
            return self._send(
                200,
                {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}},
            )
        if isinstance(request, list):
            responses = [r for r in (mcp.handle(item) for item in request) if r is not None]
            return self._send(200, responses) if responses else self._send(202, b"", "text/plain")
        response = mcp.handle(request)
        if response is None:
            return self._send(202, b"", "text/plain")
        self._send(200, response)


def _make_handler(owner):
    return type("Handler", (_Handler,), {"owner": owner})

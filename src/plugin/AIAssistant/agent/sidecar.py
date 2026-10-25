"""The StereotechAI backend as a child process of the slicer, on the Python 3.11 shipped in runtime/.

The slicer embeds Python 3.5, so the app cannot run inside it. The portable build puts a Python 3.11
and the app next to the plugin; this module starts it on a free port and stops it with the slicer.
"""
import atexit
import base64
import os
import socket
import subprocess
import sys
import time
import urllib.request

from . import settings

PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNTIME_DIR = os.path.join(PLUGIN_DIR, "runtime")
START_SECONDS = 60
CREATE_NO_WINDOW = 0x08000000


def python_path():
    name = "python.exe" if sys.platform == "win32" else "python3"
    return os.path.join(RUNTIME_DIR, "python", name)


def available():
    """True in the portable build; a run from the sources has no runtime/ and uses mosprom.json."""
    return os.path.isfile(python_path()) and os.path.isdir(os.path.join(RUNTIME_DIR, "app"))


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class Sidecar(object):
    def __init__(self):
        self.port = None
        self.secret = None
        self.user_id = "local"
        self._process = None
        self._log = None
        atexit.register(self.stop)

    def origin(self):
        return "http://127.0.0.1:%d" % self.port

    def running(self):
        return self._process is not None and self._process.poll() is None

    def log_path(self):
        return os.path.join(RUNTIME_DIR, "data", "logs", "backend.log")

    def start(self):
        """Start the backend and wait until it answers; raises RuntimeError with the reason."""
        if self.running():
            return
        if not available():
            raise RuntimeError("runtime/ is missing next to the plugin")
        self.port = _free_port()
        self.secret = base64.urlsafe_b64encode(os.urandom(48)).decode("ascii")
        os.makedirs(os.path.dirname(self.log_path()), exist_ok=True)
        self._log = open(self.log_path(), "ab")
        config = settings.load()
        env = dict(os.environ)
        env.update({
            "DATA_DIR": os.path.join(RUNTIME_DIR, "data"),
            "APP_ORIGIN": self.origin(),
            "SESSION_SECRET": self.secret,
            "QWEN_API_KEY": config.get("api_key") or "",
            "QWEN_BASE_URL": config.get("base_url") or settings.DEFAULT_BASE_URL,
            "QWEN_MODEL": config.get("model") or settings.DEFAULT_MODEL,
            "SLICER_FOLDER": settings.data_dir(),
            "SLICER_HOST": "127.0.0.1",
            "PARENT_PID": str(os.getpid()),
            "PYTHONUTF8": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
        })
        for name in ("PYTHONPATH", "PYTHONHOME"):
            env.pop(name, None)
        command = [python_path(), "-m", "uvicorn", "src.backend.api.app:create_app", "--factory",
                   "--host", "127.0.0.1", "--port", str(self.port), "--loop", "asyncio"]
        flags = CREATE_NO_WINDOW if sys.platform == "win32" else 0
        self._process = subprocess.Popen(
            command, cwd=os.path.join(RUNTIME_DIR, "app"), env=env, stdin=subprocess.DEVNULL,
            stdout=self._log, stderr=subprocess.STDOUT, creationflags=flags)
        self._wait_ready()

    def _wait_ready(self):
        url = self.origin() + "/api/v1/health"
        deadline = time.time() + START_SECONDS
        while time.time() < deadline:
            if self._process.poll() is not None:
                self.stop()
                raise RuntimeError("the backend exited, see %s" % self.log_path())
            try:
                request = urllib.request.Request(url, headers={"Host": "127.0.0.1:%d" % self.port})
                with urllib.request.urlopen(request, timeout=2) as response:
                    if response.status == 200:
                        return
            except (OSError, ValueError):
                pass
            time.sleep(0.5)
        self.stop()
        raise RuntimeError("the backend did not answer in %d s, see %s" % (START_SECONDS, self.log_path()))

    def stop(self):
        process, self._process = self._process, None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        if self._log is not None:
            self._log.close()
            self._log = None

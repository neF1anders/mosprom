import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from contextlib import ExitStack
from pathlib import Path

SECRET = "test-only-session-secret-never-use-for-real-data"
STACK = Path("artifacts/e2e")
START_SECONDS = 60
CHECKS = [
    [sys.executable, "scripts/make_fixtures.py"],
    [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "--cov=src",
        "--cov-report=term-missing",
        "--cov-fail-under=80",
    ],
    ["ruff", "check", "."],
    ["mypy", "src/backend"],
    ["npm", "--prefix", "src/web", "run", "test:unit"],
]


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def answers(host: str, path: str) -> bool:
    request = urllib.request.Request(f"http://{host}{path}", headers={"Host": host})
    try:
        with urllib.request.urlopen(request, timeout=2):
            return True
    except OSError:
        return False


def wait(ready, process: subprocess.Popen, name: str) -> None:
    deadline = time.monotonic() + START_SECONDS
    while not ready():
        if process.poll() is not None:
            raise SystemExit(f"{name} exited, see {STACK}")
        if time.monotonic() > deadline:
            raise SystemExit(f"{name} did not start in {START_SECONDS} s, see {STACK}")
        time.sleep(0.5)


def start(stack: ExitStack, name: str, command: list[str], env: dict[str, str]):
    log = stack.enter_context((STACK / f"{name}.log").open("wb"))
    process = subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT)

    def stop():
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()

    stack.callback(stop)
    return process


def e2e(stack: ExitStack) -> dict[str, str]:
    """Стек для сквозных проверок."""
    if os.environ.get("E2E_BASE_URL"):
        return os.environ.copy()
    data, slicer = STACK / "data", STACK / "slicer"
    for folder in (data, slicer):
        shutil.rmtree(folder, ignore_errors=True)
        folder.mkdir(parents=True)
    model, app = f"127.0.0.1:{free_port()}", f"127.0.0.1:{free_port()}"
    env = dict(
        os.environ,
        DATA_DIR=str(data),
        DATABASE_URL="",
        SESSION_SECRET=SECRET,
        QWEN_API_KEY="test-only",
        QWEN_BASE_URL=f"http://{model}/v1",
        APP_ORIGIN=f"http://{app}",
        SLICER_FOLDER=str(slicer),
        SLICER_HOST_FOLDER="",
        SLICER_HOST="127.0.0.1",
    )
    uvicorn = [sys.executable, "-m", "uvicorn", "--host", "127.0.0.1"]
    provider = start(
        stack, "model", [*uvicorn, "--port", model.split(":")[1], "tests.model_server:app"], env
    )
    plugin = start(
        stack,
        "slicer",
        [sys.executable, "scripts/fake_ste_slicer.py", "--folder", str(slicer)],
        env,
    )
    api = start(
        stack,
        "api",
        [*uvicorn, "--port", app.split(":")[1], "--factory", "src.backend.api.app:create_app"],
        env,
    )
    wait(lambda: answers(model, "/docs"), provider, "The provider")
    wait(lambda: (slicer / "server.json").exists(), plugin, "The slicer stand-in")
    wait(lambda: answers(app, "/api/v1/health"), api, "The app")
    return dict(os.environ, E2E_BASE_URL=f"http://{app}", E2E_SESSION_SECRET=SECRET)


for command in CHECKS:
    result = subprocess.run(command, env=os.environ.copy(), check=False)
    if result.returncode:
        sys.exit(result.returncode)
with ExitStack() as stack:
    result = subprocess.run(["npm", "--prefix", "src/web", "run", "test:e2e"], env=e2e(stack))
sys.exit(result.returncode)

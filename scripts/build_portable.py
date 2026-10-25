"""Builds dist/AIAssistant-portable.zip: the plugin with its own Python 3.11 and the app.

The zip unpacks into STE Slicer's plugins folder; the plugin starts the bundled backend itself
(src/plugin/AIAssistant/agent/sidecar.py). Runs on Mac and Windows, needs network unless the
embeddable Python is cached and --offline is given (wheels are then taken from --wheels).

Usage: python3 scripts/build_portable.py [--skip-web] [--skip-download] [--offline] [--dry-run]
"""

import argparse
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON_VERSION = "3.11.9"
EMBED_URL = "https://www.python.org/ftp/python/{v}/python-{v}-embed-amd64.zip".format(v=PYTHON_VERSION)
CACHE = ROOT / "build" / "cache"
STAGE = ROOT / "build" / "portable"
PLUGIN = ROOT / "src" / "plugin" / "AIAssistant"
OUTPUT = ROOT / "dist" / "AIAssistant-portable.zip"
APP_ITEMS = [("src/backend", "src/backend"), ("src/mesh_analysis.py", "src/mesh_analysis.py"),
             ("knowledge", "knowledge"), ("src/web/dist", "src/web/dist")]
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store", ".env", "*.db", "model.json")
APP = "AIAssistant/runtime/app/"
# What the app reads at runtime besides its code: prompts, tuning tables, knowledge, the chat.
REQUIRED = [
    "AIAssistant/plugin.json",
    "AIAssistant/agent/sidecar.py",
    "AIAssistant/runtime/python/python.exe",
    "AIAssistant/runtime/python/Lib/site-packages/aiosqlite/__init__.py",
    APP + "src/backend/api/app.py",
    APP + "src/backend/startup.py",
    APP + "src/backend/agents/prompts/assistant.md",
    APP + "src/backend/tuning/free_keys.json",
    APP + "src/backend/tuning/rules.json",
    APP + "src/mesh_analysis.py",
    APP + "knowledge/catalog.json",
    APP + "knowledge/requirement_keys.json",
    APP + "knowledge/ste_5.2.4/definitions/fdmprinter.def.json",
    APP + "src/web/dist/index.html",
]
# Settings, keys and data of the build machine never ship; neither does the Docker setup.
PRIVATE = re.compile(
    r"(^|/)(\.env[^/]*|[^/]*compose[^/]*\.ya?ml|Dockerfile|model\.json|[^/]*\.db)$"
)


def run(command, **kwargs):
    print("+", " ".join(str(part) for part in command))
    subprocess.run([str(part) for part in command], check=True, **kwargs)


def embeddable_python(skip_download):
    archive = CACHE / Path(EMBED_URL).name
    if not archive.exists():
        if skip_download:
            raise SystemExit("Embeddable Python is not cached: {}".format(archive))
        CACHE.mkdir(parents=True, exist_ok=True)
        print("downloading", EMBED_URL)
        partial = archive.with_suffix(".part")
        urllib.request.urlretrieve(EMBED_URL, str(partial))
        partial.replace(archive)
    return archive


def enable_site(python_dir):
    """Turn on site-packages and put the app folder on sys.path (the embeddable build ignores PYTHONPATH)."""
    pth = next(python_dir.glob("python*._pth"))
    lines = [line for line in pth.read_text(encoding="utf-8").splitlines() if line.strip()]
    lines = [re.sub(r"^#\s*import site", "import site", line) for line in lines]
    for extra in ("Lib/site-packages", "../app"):
        if extra not in lines:
            lines.insert(len(lines) - 1 if "import site" in lines else len(lines), extra)
    pth.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_web():
    web = ROOT / "src" / "web"
    run(["npm", "ci"], cwd=web)
    run(["npm", "run", "build"], cwd=web)


def check_plugin_syntax():
    """The slicer runs the plugin on Python 3.5; vermin flags newer syntax and modules."""
    result = subprocess.run([sys.executable, "-m", "vermin", "--version"], capture_output=True)
    command = ["vermin", "--no-tips", "--target=3.5-", "--violations", str(PLUGIN)]
    if result.returncode != 0 and shutil.which("vermin") is None:
        print("vermin is not installed, the Python 3.5 check of the plugin is skipped")
        return
    run(command)


def install_packages(python_dir, args):
    requirements = ROOT / "requirements.portable.txt"
    target = python_dir / "Lib" / "site-packages"
    if shutil.which("uv"):
        pip = ["uv", "pip", "install", "--python-platform", "x86_64-pc-windows-msvc",
               "--python-version", "3.11", "--only-binary", ":all:", "--target", target,
               "-r", requirements]
    else:
        pip = [sys.executable, "-m", "pip", "install", "--no-compile", "--only-binary=:all:",
               "--platform", "win_amd64", "--python-version", "3.11", "--implementation", "cp",
               "--target", target, "-r", requirements]
    if args.offline:
        pip += ["--no-index", "--find-links", args.wheels]
    run(pip)


def copy_app(app):
    for source, target in APP_ITEMS:
        origin = ROOT / source
        destination = app / target
        destination.parent.mkdir(parents=True, exist_ok=True)
        if origin.is_dir():
            shutil.copytree(origin, destination, ignore=IGNORE)
        else:
            shutil.copy2(origin, destination)


def check_zip():
    """The archive must hold what the app reads at runtime and nothing private of this machine."""
    with zipfile.ZipFile(OUTPUT) as bundle:
        broken = bundle.testzip()
        names = set(bundle.namelist())
    if broken:
        raise SystemExit("Broken entry in the zip: {}".format(broken))
    missing = [name for name in REQUIRED if name not in names]
    if missing:
        raise SystemExit("Missing in the zip: {}".format(", ".join(missing)))
    private = sorted(name for name in names if PRIVATE.search(name))
    if private:
        raise SystemExit("Private files in the zip: {}".format(", ".join(private)))


def build(args):
    if args.dry_run:
        print("embeddable python:", EMBED_URL)
        print("pip target:", STAGE / "AIAssistant/runtime/python/Lib/site-packages")
        print("app items:", ", ".join(source for source, _ in APP_ITEMS))
        print("output:", OUTPUT)
        return
    check_plugin_syntax()
    if not args.skip_web:
        build_web()
    if not (ROOT / "src/web/dist").is_dir():
        raise SystemExit("src/web/dist is missing: build the web app or drop --skip-web")
    archive = embeddable_python(args.skip_download)
    shutil.rmtree(STAGE, ignore_errors=True)
    package = STAGE / "AIAssistant"
    shutil.copytree(PLUGIN, package, ignore=IGNORE)
    runtime = package / "runtime"
    python_dir = runtime / "python"
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(python_dir)
    enable_site(python_dir)
    install_packages(python_dir, args)
    copy_app(runtime / "app")
    (runtime / "data").mkdir()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.unlink(missing_ok=True)
    with zipfile.ZipFile(OUTPUT, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for path in sorted(STAGE.rglob("*")):
            bundle.write(path, path.relative_to(STAGE).as_posix())
    check_zip()
    print("{} {:.0f} MB".format(OUTPUT, OUTPUT.stat().st_size / 1e6))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--skip-web", action="store_true", help="use the existing src/web/dist")
    parser.add_argument("--skip-download", action="store_true", help="fail unless the embeddable Python is cached")
    parser.add_argument("--offline", action="store_true", help="install wheels only from --wheels")
    parser.add_argument("--wheels", default=str(ROOT / "build" / "wheels"), help="folder of wheels for --offline")
    parser.add_argument("--dry-run", action="store_true", help="print the plan and build nothing")
    build(parser.parse_args())

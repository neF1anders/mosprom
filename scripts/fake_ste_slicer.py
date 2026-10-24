"""Stand-in for STE Slicer with the AI Assistant plugin, for a Mac or a test without the slicer.

It answers the plugin's MCP calls the way ``src/plugin/AIAssistant/agent`` does: the same port and token in ``server.json``, the same Host and token
checks and the tools slicing uses. Nothing is sliced: the G-code is a few layers around the
model's footprint with the layer height and temperatures that were set, and the project is a
3MF with a note that it is a stand-in.

    uv run python scripts/fake_ste_slicer.py [--folder ~/Documents/STE_AIAssistant]
"""

from __future__ import annotations

import argparse
import json
import math
import os
import secrets
import struct
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

# Layer heights of the quality profiles in the issued build (quality_type -> mm).
LAYER_HEIGHTS = {
    "high": 0.06,
    "normal": 0.1,
    "fast": 0.15,
    "draft": 0.2,
    "verydraft": 0.3,
    "coarse": 0.4,
    "extra coarse": 0.6,
}
# The classic bed of the Hybrid 530 V5.2.4 in machine coordinates, its centre as the plate's.
BED = (351.0, 300.3, 300.0)
CENTRE = (175.5, 150.15)
TOOLS = [
    "get_state",
    "list_models",
    "delete_model",
    "set_printer",
    "set_print_mode",
    "set_quality_profile",
    "set_material",
    "set_setting",
    "load_model",
    "rotate_model",
    "scale_model",
    "move_model",
    "slice_model",
    "export_gcode",
    "save_project",
]


class ToolError(Exception):
    pass


class FakeSlicer:
    def __init__(
        self,
        folder: Path,
        reset_tool: bool = False,
        fail_on: str | None = None,
        bind: str = "127.0.0.1",
    ):
        self.folder, self.token, self.bind = folder, secrets.token_hex(16), bind
        self.tools = TOOLS + (["reset_settings"] if reset_tool else [])
        self.fail_on = fail_on
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.headers: list[dict[str, str]] = []
        self.printer: str | None = None
        self.mode, self.quality, self.material = "classic", "fast", "generic_pla_175"
        self.settings: dict[str, Any] = {}
        self.models: list[dict[str, Any]] = []
        self.sliced = False
        self._server: ThreadingHTTPServer | None = None

    # -------------------------------------------------------------- server

    def start(self) -> int:
        self._server = ThreadingHTTPServer((self.bind, 0), _handler(self))
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        # A worker in another container writes the models here under its own user.
        exchange = self.folder / "mosprom"
        exchange.mkdir(parents=True, exist_ok=True)
        exchange.chmod(0o777)
        info = {"port": self.port, "token": self.token, "pid": os.getpid()}
        (self.folder / "server.json").write_text(json.dumps(info), encoding="utf-8")
        return self.port

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        (self.folder / "server.json").unlink(missing_ok=True)

    @property
    def port(self) -> int:
        assert self._server is not None
        return self._server.server_address[1]

    def handle(self, request: dict[str, Any]) -> dict[str, Any]:
        method, params = request.get("method"), request.get("params") or {}
        reply: dict[str, Any] = {"jsonrpc": "2.0", "id": request.get("id")}
        if method == "tools/list":
            reply["result"] = {"tools": [{"name": name} for name in self.tools]}
        elif method == "tools/call":
            reply["result"] = self.call(params.get("name"), params.get("arguments") or {})
        else:
            reply["error"] = {"code": -32601, "message": f"Method not found: {method}"}
        return reply

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((name, arguments))
        try:
            if name not in self.tools:
                raise ToolError(f"Unknown tool: {name}")
            if name == self.fail_on:
                raise ToolError(f"{name} failed on purpose")
            result = getattr(self, "tool_" + name)(**arguments)
        except ToolError as error:
            return {"content": [{"type": "text", "text": str(error)}], "isError": True}
        text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
        return {"content": [{"type": "text", "text": text}], "isError": False}

    # -------------------------------------------------------------- tools

    def tool_get_state(self) -> dict[str, Any]:
        return {"printer": self.printer, "print_mode": self.mode, "quality": self.quality}

    def tool_list_models(self) -> list[dict[str, Any]]:
        return [{"index": i, "name": m["name"]} for i, m in enumerate(self.models)]

    def tool_delete_model(self, model_index: int = 0) -> str:
        model = self._model(model_index)
        self.models.remove(model)
        self.sliced = False
        return "removed %s" % model["name"]

    def tool_reset_settings(self) -> str:
        self.settings.clear()
        return "user settings cleared"

    def tool_set_printer(self, definition_id: str = "hte530v5.2.4") -> str:
        self.printer = definition_id
        return "active printer: %s" % definition_id

    def tool_set_print_mode(self, mode: str, reason: str = "") -> str:
        old, self.mode = self.mode, mode
        return "printing_mode: %s -> %s" % (old, mode)

    def tool_set_quality_profile(self, quality_type: str, reason: str = "") -> str:
        if quality_type not in LAYER_HEIGHTS:
            raise ToolError("Unknown quality type: %s" % quality_type)
        old, self.quality = self.quality, quality_type
        return "quality: %s -> %s" % (old, quality_type)

    def tool_set_material(self, material_id: str, reason: str = "") -> str:
        old, self.material = self.material, material_id
        return "material: %s -> %s" % (old, material_id)

    def tool_set_setting(self, key: str, value: Any, reason: str = "") -> str:
        if key.startswith("machine_") or key == "printing_mode":
            raise ToolError("%s cannot be changed here" % key)
        old = self.settings.get(key)
        self.settings[key] = value
        return "%s: %s -> %s" % (key, old, value)

    def tool_load_model(self, path: str) -> list[dict[str, Any]]:
        if not os.path.isfile(path):
            raise ToolError("File not found: %s" % path)
        size = _stl_size(Path(path))
        name = os.path.basename(path)
        self.models.append({"name": name, "size": size, "scale": 1.0, "offset": (0.0, 0.0)})
        return self.tool_list_models()

    def tool_rotate_model(self, axis: str, degrees: float, reason: str = "", model_index: int = 0):
        model = self._model(model_index)
        x, depth, height = model["size"]
        if axis in ("x", "z") and round(degrees / 90) % 2:
            # A quarter turn about a horizontal axis swaps the height with a side.
            model["size"] = (height, depth, x) if axis == "z" else (x, height, depth)
        return "rotated %s by %s degrees" % (model["name"], degrees)

    def tool_scale_model(self, factor: float, reason: str = "", model_index: int = 0) -> str:
        self._model(model_index)["scale"] *= float(factor)
        return "scaled by %s" % factor

    def tool_move_model(self, x: float, z: float, model_index: int = 0) -> str:
        self._model(model_index)["offset"] = (float(x), float(z))
        return "moved to x=%s z=%s" % (x, z)

    def tool_slice_model(self) -> dict[str, Any]:
        if not self.models:
            raise ToolError("There are no models on the build plate. Use load_model first.")
        self.sliced = True
        layers = self._layers()
        return {
            "print_time_seconds": 600 * len(layers),
            "print_time": "",
            "material_grams": round(0.4 * len(layers), 2),
            "material_meters": round(0.13 * len(layers), 2),
        }

    def tool_export_gcode(self, path: str | None = None) -> dict[str, Any]:
        if not self.sliced:
            raise ToolError("There is no G-code. Run slice_model first.")
        target = Path(path or self.folder / "results" / "result.gcode")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self._gcode(), encoding="utf-8")
        return {"path": str(target), "bytes": target.stat().st_size}

    def tool_save_project(self, path: str | None = None) -> dict[str, Any]:
        target = Path(path or self.folder / "results" / "project.3mf")
        target.parent.mkdir(parents=True, exist_ok=True)
        state = {
            "stand_in": "fake_ste_slicer.py, not STE Slicer",
            "printer": self.printer,
            "printing_mode": self.mode,
            "quality_type": self.quality,
            "material": self.material,
            "settings": self.settings,
            "models": self.models,
        }
        with zipfile.ZipFile(target, "w") as archive:
            archive.writestr("SteSlicer/stand_in.json", json.dumps(state, ensure_ascii=False))
        return {"path": str(target), "bytes": target.stat().st_size}

    # -------------------------------------------------------------- helpers

    def _model(self, index: int) -> dict[str, Any]:
        if not 0 <= index < len(self.models):
            raise ToolError("model_index must be between 0 and %d" % (len(self.models) - 1))
        return self.models[index]

    def _layer_height(self) -> float:
        return float(self.settings.get("layer_height", LAYER_HEIGHTS[self.quality]))

    def _layers(self) -> list[float]:
        height = max(m["size"][2] * m["scale"] for m in self.models)
        step = self._layer_height()
        # A handful of layers is enough for the check; the count follows the height.
        count = max(1, min(50, math.ceil(height / step)))
        return [round(step * (i + 1), 3) for i in range(count)]

    def _gcode(self) -> str:
        nozzle = int(self.settings.get("material_print_temperature", 200))
        bed = int(self.settings.get("material_bed_temperature", 60))
        layers = self._layers()
        lines = [
            ";FLAVOR:Marlin",
            ";TIME:%d" % (600 * len(layers)),
            ";Filament used: %.4fm" % (0.13 * len(layers)),
            ";Layer height: %g" % self._layer_height(),
            ";Generated with fake_ste_slicer.py",
        ]
        if self.mode == "classic":
            lines += ["M140 S%d" % bed, "M190 S%d" % bed]
        lines += ["M104 S%d" % nozzle, "M109 S%d" % nozzle, "G92 E0", ";LAYER_COUNT:%d" % len(layers)]
        extrusion = 0.0
        support = self.settings.get("support_enable") is True
        for number, z in enumerate(layers):
            lines += [";LAYER:%d" % number, ";TYPE:WALL-OUTER"]
            for model in self.models:
                for x, y in _square(model):
                    extrusion += 0.05
                    lines.append("G1 X%.3f Y%.3f Z%.3f E%.5f" % (x, y, z, extrusion))
            if support:
                lines += [";TYPE:SUPPORT", "G1 X%.3f Y%.3f E%.5f" % (CENTRE[0], CENTRE[1], extrusion)]
        lines += ["M104 S0", "M140 S0", ";End of Gcode"]
        return "\n".join(lines) + "\n"


def _square(model: dict[str, Any]) -> list[tuple[float, float]]:
    """The model's footprint in machine coordinates: the scene's z is minus the machine's Y."""
    width, depth = model["size"][0] * model["scale"], model["size"][1] * model["scale"]
    x0 = CENTRE[0] + model["offset"][0]
    y0 = CENTRE[1] - model["offset"][1]
    return [
        (x0 - width / 2, y0 - depth / 2),
        (x0 + width / 2, y0 - depth / 2),
        (x0 + width / 2, y0 + depth / 2),
        (x0 - width / 2, y0 + depth / 2),
    ]


def _stl_size(path: Path) -> tuple[float, float, float]:
    """Size of an STL along x, y and z, binary or ASCII."""
    data = path.read_bytes()
    points: list[tuple[float, ...]] = []
    count = struct.unpack_from("<I", data, 80)[0] if len(data) >= 84 else 0
    if len(data) == 84 + 50 * count:
        for index in range(count):
            offset = 84 + 50 * index + 12
            points += [struct.unpack_from("<3f", data, offset + 12 * v) for v in range(3)]
    else:
        for line in data.decode("utf-8", "replace").splitlines():
            parts = line.split()
            if parts[:1] == ["vertex"]:
                points.append(tuple(float(p) for p in parts[1:4]))
    if not points:
        raise ToolError("The model did not appear on the build plate")
    return tuple(max(p[a] for p in points) - min(p[a] for p in points) for a in range(3))  # type: ignore[return-value]


def _handler(slicer: FakeSlicer) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:
            pass

        def _send(self, status: int, body: dict[str, Any]) -> None:
            data = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self) -> None:
            slicer.headers.append(dict(self.headers))
            port = slicer.port
            if self.headers.get("Host") not in ("127.0.0.1:%d" % port, "localhost:%d" % port):
                return self._send(403, {"error": "bad host"})
            if self.headers.get("Authorization") != "Bearer %s" % slicer.token:
                return self._send(401, {"error": "bad token"})
            if self.path != "/mcp":
                return self._send(404, {"error": "not found"})
            length = int(self.headers.get("Content-Length") or 0)
            self._send(200, slicer.handle(json.loads(self.rfile.read(length) or b"{}")))

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    default = Path.home() / "Documents" / "STE_AIAssistant"
    parser.add_argument("--folder", type=Path, default=default, help="folder of server.json")
    parser.add_argument("--reset-tool", action="store_true", help="offer reset_settings too")
    parser.add_argument("--bind", default="127.0.0.1", help="0.0.0.0 to serve other containers")
    args = parser.parse_args()
    slicer = FakeSlicer(args.folder.expanduser(), reset_tool=args.reset_tool, bind=args.bind)
    port = slicer.start()
    print(f"Stand-in STE Slicer on {args.bind}:{port}, server.json in {slicer.folder}", flush=True)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        slicer.stop()


if __name__ == "__main__":
    main()

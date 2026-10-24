"""Tools the LLM can call. Every method runs on the Qt main thread (see LLMChat._onToolRequested)."""
import json
import math
import os
import time

from PyQt5.QtCore import QUrl

from UM.Application import Application
from UM.Logger import Logger
from UM.Math.Quaternion import Quaternion
from UM.Math.Vector import Vector
from UM.Operations.RotateOperation import RotateOperation
from UM.Scene.Iterator.DepthFirstIterator import DepthFirstIterator
from UM.Settings.ContainerRegistry import ContainerRegistry
from UM.Backend.Backend import BackendState

# key: (type, min, max, options)
SETTINGS = {
    "layer_height": ("float", 0.05, 0.4, None),
    "wall_line_count": ("int", 1, 10, None),
    "top_layers": ("int", 0, 30, None),
    "bottom_layers": ("int", 0, 30, None),
    "infill_sparse_density": ("float", 0, 100, None),
    "infill_pattern": ("enum", None, None, ["grid", "lines", "triangles", "trihexagon", "cubic", "cubicsubdiv", "tetrahedral", "concentric", "zigzag", "cross", "gyroid"]),
    "support_enable": ("bool", None, None, None),
    "support_type": ("enum", None, None, ["buildplate", "everywhere"]),
    "support_angle": ("float", 0, 80, None),
    "support_infill_rate": ("float", 0, 100, None),
    "adhesion_type": ("enum", None, None, ["skirt", "brim", "raft", "none"]),
    "material_print_temperature": ("float", 150, 320, None),
    "material_bed_temperature": ("float", 0, 120, None),
    "speed_print": ("float", 10, 150, None),
    "cool_fan_enabled": ("bool", None, None, None),
    "retraction_enable": ("bool", None, None, None),
    "retraction_amount": ("float", 0, 10, None),
    "material_flow": ("float", 50, 150, None),
}

PRINT_MODES = {
    "classic": "3D (planar printing)",
    "cylindrical": "5D spiral",
    "cylindrical_full": "5D",
    "discrete": "5D discrete (alpha)",
    "spherical": "5D spherical (alpha)",
    "spherical_full": "5D spherical full (alpha)",
}

TOOL_SPECS = [
    {"name": "get_state", "description": "Current printer, print mode, material, quality, key settings, build volume and models on the build plate (name, size in mm). Call this first.", "parameters": {"type": "object", "properties": {}}},
    {"name": "list_materials", "description": "Materials available for the active printer: id, brand, type, color. Use to pick a material and its color.", "parameters": {"type": "object", "properties": {"type": {"type": "string", "description": "Filter by material type, e.g. PLA, PETG, ABS, TPU"}, "limit": {"type": "integer"}}}},
    {"name": "set_material", "description": "Select the material by id from list_materials.", "parameters": {"type": "object", "properties": {"material_id": {"type": "string"}, "reason": {"type": "string"}}, "required": ["material_id", "reason"]}},
    {"name": "set_print_mode", "description": "Choose 3D planar printing ('classic') or a 5D mode. 5D modes: cylindrical_full, cylindrical, discrete, spherical, spherical_full.", "parameters": {"type": "object", "properties": {"mode": {"type": "string", "enum": list(PRINT_MODES)}, "reason": {"type": "string"}}, "required": ["mode", "reason"]}},
    {"name": "set_setting", "description": "Change one print setting. Allowed keys: " + ", ".join(SETTINGS) + ". Values outside safe ranges are clamped.", "parameters": {"type": "object", "properties": {"key": {"type": "string", "enum": list(SETTINGS)}, "value": {"type": ["number", "string", "boolean"]}, "reason": {"type": "string", "description": "Why, in the user's language, one sentence"}}, "required": ["key", "value", "reason"]}},
    {"name": "load_model", "description": "Load an STL/3MF/OBJ file from a local path onto the build plate.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "rotate_model", "description": "Rotate a model for better orientation. The scene is Y-up: rotate about x or z to lay a part on another face, about y to turn it on the plate.", "parameters": {"type": "object", "properties": {"axis": {"type": "string", "enum": ["x", "y", "z"]}, "degrees": {"type": "number"}, "model_index": {"type": "integer"}, "reason": {"type": "string"}}, "required": ["axis", "degrees", "reason"]}},
    {"name": "arrange_models", "description": "Arrange all models on the build plate.", "parameters": {"type": "object", "properties": {}}},
    {"name": "slice_and_export", "description": "Slice the scene and save the G-code. Takes up to a few minutes.", "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "Output .gcode path, optional"}}}},
    {"name": "save_project", "description": "Save the current scene with all settings as a .3mf project.", "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "Output .3mf path, optional"}}}},
]


def _app():
    return Application.getInstance()


def _out_dir():
    d = os.path.join(os.path.expanduser("~"), "Documents", "STE_LLMChat")
    os.makedirs(d, exist_ok=True)
    return d


class SlicerTools:
    def __init__(self):
        self.changes = []
        self.slice_state = None
        self._hooked_backend = None
        self._retries = 0
        self._last_start = 0.0

    # ---------- helpers ----------
    def _stack(self):
        return _app().getGlobalContainerStack()

    def _models(self):
        nodes = []
        for node in DepthFirstIterator(_app().getController().getScene().getRoot()):
            if node.getMeshData() and node.callDecoration("isSliceable") and not node.callDecoration("isGroup"):
                nodes.append(node)
        return nodes

    def _get_value(self, key):
        gs = self._stack()
        if gs.getProperty(key, "settable_per_extruder") and gs.extruders:
            return list(gs.extruders.values())[0].getProperty(key, "value")
        return gs.getProperty(key, "value")

    @staticmethod
    def _coerce(key, value):
        kind, lo, hi, options = SETTINGS[key]
        if kind == "bool":
            if isinstance(value, str):
                return value.strip().lower() in ("1", "true", "yes", "да")
            return bool(value)
        if kind == "enum":
            if value not in options:
                raise ValueError("%s must be one of %s" % (key, options))
            return value
        number = float(value)
        number = max(lo, min(hi, number))
        return int(round(number)) if kind == "int" else number

    def changes_html(self):
        if not self.changes:
            return ""
        rows = ["<b>%s</b>: %s &rarr; <b>%s</b><br><i>%s</i>" % c for c in self.changes]
        return "<br><br>".join(rows)

    # ---------- tools ----------
    def tool_get_state(self):
        gs = self._stack()
        mm = _app().getMachineManager()
        state = {
            "printer": gs.getName() if gs else None,
            "print_mode": gs.getProperty("printing_mode", "value") if gs else None,
            "material_id": mm.activeMaterialId,
            "quality": mm.activeQualityType,
            "build_volume_mm": [gs.getProperty(k, "value") for k in ("machine_width", "machine_depth", "machine_height")],
            "settings": {k: self._get_value(k) for k in SETTINGS},
            "models": [],
        }
        for i, node in enumerate(self._models()):
            box = node.getBoundingBox()
            state["models"].append({"index": i, "name": node.getName(), "size_mm_xyz": [round(box.width, 1), round(box.depth, 1), round(box.height, 1)]})
        return json.dumps(state, ensure_ascii=False, default=str)

    def tool_list_materials(self, type=None, limit=25):
        gs = self._stack()
        manager = _app().getMaterialManager()
        extruder = list(gs.extruders.values())[0]
        available = manager.getAvailableMaterialsForMachineExtruder(gs, extruder) or {}
        rows = []
        registry = ContainerRegistry.getInstance()
        for root_id in available:
            found = registry.findContainersMetadata(id=root_id)
            meta = found[0] if found else {}
            mat_type = meta.get("material", "")
            if type and type.lower() != str(mat_type).lower():
                continue
            rows.append({"id": root_id, "brand": meta.get("brand"), "type": mat_type, "color": meta.get("color_name")})
        rows.sort(key=lambda r: (str(r["type"]), str(r["brand"]), str(r["color"])))
        return json.dumps(rows[:int(limit)], ensure_ascii=False)

    def tool_set_material(self, material_id, reason=""):
        old = _app().getMachineManager().activeMaterialId
        _app().getMachineManager().setMaterialById("0", material_id)
        new = _app().getMachineManager().activeMaterialId
        self.changes.append(("material", old, new, reason))
        return "material: %s -> %s" % (old, new)

    def tool_set_print_mode(self, mode, reason=""):
        if mode not in PRINT_MODES:
            return "ERROR: unknown mode, use one of %s" % list(PRINT_MODES)
        gs = self._stack()
        old = gs.getProperty("printing_mode", "value")
        gs.userChanges.setProperty("printing_mode", "value", mode)
        self.changes.append(("print mode", PRINT_MODES.get(old, old), PRINT_MODES[mode], reason))
        return "printing_mode: %s -> %s" % (old, mode)

    def tool_set_setting(self, key, value, reason=""):
        if key not in SETTINGS:
            return "ERROR: key not allowed, use one of %s" % list(SETTINGS)
        gs = self._stack()
        if gs.getProperty(key, "value") is None and not gs.getSettingDefinition(key):
            return "ERROR: setting %s does not exist for this printer" % key
        new = self._coerce(key, value)
        old = self._get_value(key)
        if gs.getProperty(key, "settable_per_extruder") and gs.extruders:
            for extruder in gs.extruders.values():
                extruder.userChanges.setProperty(key, "value", new)
        else:
            gs.userChanges.setProperty(key, "value", new)
        self.changes.append((key, old, new, reason))
        return "%s: %s -> %s" % (key, old, new)

    def tool_load_model(self, path):
        if not os.path.isfile(path):
            return "ERROR: file not found: %s" % path
        _app().readLocalFile(QUrl.fromLocalFile(path))
        return "loading started, call get_state in a moment to see the model size"

    def tool_rotate_model(self, axis, degrees, model_index=0, reason=""):
        models = self._models()
        if not models:
            return "ERROR: no models on the build plate"
        node = models[int(model_index)]
        unit = {"x": Vector.Unit_X, "y": Vector.Unit_Y, "z": Vector.Unit_Z}[axis]
        RotateOperation(node, Quaternion.fromAngleAxis(math.radians(float(degrees)), unit)).push()
        self.changes.append(("rotation %s" % axis, "0", "%s deg" % degrees, reason))
        return "rotated %s by %s degrees" % (node.getName(), degrees)

    def tool_arrange_models(self):
        _app().arrangeAll()
        return "models arranged"

    def start_slice(self):
        if not self._models():
            return "ERROR: no models on the build plate"
        backend = _app().getBackend()
        if self._hooked_backend is not None:
            try:
                self._hooked_backend.backendStateChange.disconnect(self._on_backend_state)
            except Exception:
                pass
        self.slice_state = None
        backend.backendStateChange.connect(self._on_backend_state)
        self._hooked_backend = backend
        self._retries = 0
        self._last_start = time.time()
        backend.forceSlice()
        return "slicing started"

    def poll_slice(self):
        """Slicing is aborted whenever the scene changes (rotate, arrange, model load), so restart it when it fell back to NotStarted."""
        done = self.finished_state_text()
        if done:
            return done
        if self.slice_state == BackendState.NotStarted and time.time() - self._last_start > 4 and self._retries < 5:
            self._retries += 1
            self._last_start = time.time()
            self._hooked_backend.forceSlice()
            return "restarted"
        return "waiting"

    def _on_backend_state(self, state):
        Logger.log("i", "LLMChat backend state: %s", state)
        self.slice_state = state

    def tool_export_gcode(self, path=None):
        scene = _app().getController().getScene()
        lines = getattr(scene, "gcode_dict", {}).get(0)
        if not lines:
            return "ERROR: no G-code, slicing did not finish"
        path = path or os.path.join(_out_dir(), "result.gcode")
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("".join(lines))
        return "G-code saved: %s (%d chunks)" % (path, len(lines))

    def tool_save_project(self, path=None):
        path = path or os.path.join(_out_dir(), "project.3mf")
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        writer = _app().getWorkspaceFileHandler().getWriter("3MFWriter")
        if writer is None:
            return "ERROR: 3MF workspace writer not found"
        with open(path, "wb") as f:
            writer.write(f, [_app().getController().getScene().getRoot()])
        return "project saved: %s" % path

    def finished_state_text(self):
        if self.slice_state == BackendState.Error:
            return "error"
        gcode = getattr(_app().getController().getScene(), "gcode_dict", {}).get(0)
        if self.slice_state == BackendState.Done and gcode:
            return "done"
        return None

"""MCP tools over the STE Slicer API. Handlers run on the Qt main thread unless registered with on_main=False."""
import json
import math
import os
import time

from PyQt5.QtCore import QUrl

from UM.Application import Application
from UM.Backend.Backend import BackendState
from UM.Logger import Logger
from UM.Math.Quaternion import Quaternion
from UM.Math.Vector import Vector
from UM.Operations.RemoveSceneNodeOperation import RemoveSceneNodeOperation
from UM.Operations.RotateOperation import RotateOperation
from UM.Operations.ScaleOperation import ScaleOperation
from UM.Operations.TranslateOperation import TranslateOperation
from UM.Scene.Iterator.DepthFirstIterator import DepthFirstIterator
from UM.Settings.ContainerRegistry import ContainerRegistry

from . import settings
from .mainthread import run_on_main

DEFAULT_PRINTER = "hte530v5.2.4"  # Stereotech Hybrid 530 V5.2.4

PRINT_MODES = {
    "classic": "3D",
    "cylindrical": "5D Spiral",
    "cylindrical_full": "5D",
}

KEY_SETTINGS = [
    "layer_height", "wall_line_count", "top_layers", "bottom_layers", "infill_sparse_density",
    "infill_pattern", "support_enable", "support_type", "adhesion_type", "material_print_temperature",
    "material_bed_temperature", "speed_print", "cool_fan_enabled", "retraction_enable",
]

# Where a face has to lie on the plate: name -> (axis, degrees) that brings that face down (scene is Y-up)
ORIENTATIONS = {
    "keep": (None, 0),
    "flip": ("x", 180),
    "side_px": ("z", -90),
    "side_nx": ("z", 90),
    "side_pz": ("x", 90),
    "side_nz": ("x", -90),
}
DOWN_VECTORS = {
    "keep": (0, -1, 0),
    "flip": (0, 1, 0),
    "side_px": (1, 0, 0),
    "side_nx": (-1, 0, 0),
    "side_pz": (0, 0, 1),
    "side_nz": (0, 0, -1),
}


class ToolError(Exception):
    expected = True  # a normal failure the model can read, not worth a stack trace in the log


class Tool(object):
    def __init__(self, name, description, properties, required, handler, on_main):
        self.name = name
        self.description = description
        self.properties = properties
        self.required = required
        self.handler = handler
        self.on_main = on_main

    def spec(self):
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": {"type": "object", "properties": self.properties, "required": self.required},
        }


TOOLS = {}


def tool(description, properties=None, required=None, on_main=True):
    def decorator(func):
        TOOLS[func.__name__] = Tool(func.__name__, description, properties or {}, required or [], func, on_main)
        return func
    return decorator


def P(kind, description, **extra):
    schema = {"type": kind, "description": description}
    schema.update(extra)
    return schema


class Session(object):
    """What happened in this chat: the list of changes shown to the user and the slicing state."""

    def __init__(self):
        self.changes = []
        self.slice_state = None
        self.slice_progress = 0.0
        self.backend = None
        self.restarts = 0
        self.last_start = 0.0

    def record(self, name, old, new, reason):
        self.changes.append({"name": name, "old": old, "new": new, "reason": reason})


SESSION = Session()


def _app():
    return Application.getInstance()


def _stack():
    stack = _app().getGlobalContainerStack()
    if stack is None:
        raise ToolError("No printer is active. Call set_printer first.")
    return stack


def _value(key):
    stack = _stack()
    try:
        if stack.getProperty(key, "settable_per_extruder") and stack.extruders:
            return list(stack.extruders.values())[0].getProperty(key, "value")
        return stack.getProperty(key, "value")
    except Exception:
        return None


def _models():
    nodes = []
    for node in DepthFirstIterator(_app().getController().getScene().getRoot()):
        if node.getMeshData() and node.callDecoration("isSliceable") and not node.callDecoration("isGroup"):
            nodes.append(node)
    return nodes


def _model(index):
    models = _models()
    if not models:
        raise ToolError("There are no models on the build plate. Use load_model first.")
    if index < 0 or index >= len(models):
        raise ToolError("model_index must be between 0 and %d" % (len(models) - 1))
    return models[index]


def _model_row(index, node):
    box = node.getBoundingBox()
    position = node.getWorldPosition()
    return {
        "index": index,
        "name": node.getName(),
        "size_mm": {"x": round(box.width, 2), "y_depth": round(box.depth, 2), "z_height": round(box.height, 2)},
        "position_mm": {"x": round(position.x, 2), "z": round(position.z, 2)},
    }


# ---------------------------------------------------------------- printer, profiles, materials

@tool("Printer, print mode, material, quality, build volume, key settings and the models on the build plate. Call this first.")
def get_state():
    stack = _stack()
    manager = _app().getMachineManager()
    mode = stack.getProperty("printing_mode", "value")
    return {
        "printer": stack.getName(),
        "printer_definition": stack.definition.getId(),
        "print_mode": mode,
        "print_mode_name": PRINT_MODES.get(mode, mode),
        "material_id": manager.activeMaterialId,
        "quality": manager.activeQualityType,
        "build_volume_mm": [stack.getProperty(k, "value") for k in ("machine_width", "machine_depth", "machine_height")],
        "settings": dict((key, _value(key)) for key in KEY_SETTINGS),
        "models": [_model_row(i, node) for i, node in enumerate(_models())],
    }


@tool("Printers known to the slicer.")
def list_printers():
    active = _app().getGlobalContainerStack()
    rows = []
    for stack in ContainerRegistry.getInstance().findContainerStacks(type="machine"):
        rows.append({"id": stack.getId(), "name": stack.getName(), "definition": stack.definition.getId(),
                     "active": stack is active})
    return rows


@tool("Select the active printer by definition id; it is added if missing. The test printer Stereotech Hybrid 530 V5.2.4 is 'hte530v5.2.4'.",
      {"definition_id": P("string", "Printer definition id", default=DEFAULT_PRINTER)})
def set_printer(definition_id=DEFAULT_PRINTER):
    registry = ContainerRegistry.getInstance()
    manager = _app().getMachineManager()
    for stack in registry.findContainerStacks(type="machine"):
        if stack.definition.getId() == definition_id:
            manager.setActiveMachine(stack.getId())
            return "active printer: %s" % stack.getName()
    definitions = registry.findDefinitionContainersMetadata(id=definition_id)
    if not definitions:
        raise ToolError("Unknown printer definition: %s" % definition_id)
    manager.addMachine(definitions[0].get("name", definition_id), definition_id)
    return "printer added and selected: %s" % _stack().getName()


@tool("Materials available for the active printer: id, brand, type, color. Use it to choose a material and its color.",
      {"type": P("string", "Filter by material type, e.g. PLA, PETG, ABS, TPU"), "limit": P("integer", "Maximum rows", default=25)})
def list_materials(type=None, limit=25):
    stack = _stack()
    extruder = list(stack.extruders.values())[0]
    available = _app().getMaterialManager().getAvailableMaterialsForMachineExtruder(stack, extruder) or {}
    registry = ContainerRegistry.getInstance()
    rows = []
    for root_id in available:
        found = registry.findContainersMetadata(id=root_id)
        meta = found[0] if found else {}
        material_type = meta.get("material", "")
        if type and type.lower() != str(material_type).lower():
            continue
        rows.append({"id": root_id, "brand": meta.get("brand"), "type": material_type, "color": meta.get("color_name")})
    rows.sort(key=lambda r: (str(r["type"]), str(r["brand"]), str(r["color"])))
    return rows[:int(limit)]


@tool("Select the material by id from list_materials.",
      {"material_id": P("string", "Material id"), "reason": P("string", "Why this material, one sentence")},
      ["material_id", "reason"])
def set_material(material_id, reason=""):
    manager = _app().getMachineManager()
    old = manager.activeMaterialId
    manager.setMaterialById("0", material_id)
    new = manager.activeMaterialId
    SESSION.record("material", old, new, reason)
    return "material: %s -> %s" % (old, new)


@tool("Quality profiles of the active printer and material.")
def list_quality_profiles():
    stack = _stack()
    active = _app().getMachineManager().activeQualityType
    rows = []
    for quality_type, group in _app().getQualityManager().getQualityGroups(stack).items():
        rows.append({"quality_type": quality_type, "name": group.name, "available": group.is_available,
                     "active": quality_type == active})
    return rows


@tool("Select a quality profile by quality_type from list_quality_profiles.",
      {"quality_type": P("string", "Quality type"), "reason": P("string", "Why this profile, one sentence")},
      ["quality_type", "reason"])
def set_quality_profile(quality_type, reason=""):
    manager = _app().getMachineManager()
    old = manager.activeQualityType
    manager.setQualityGroupByQualityType(quality_type)
    new = manager.activeQualityType
    SESSION.record("quality profile", old, new, reason)
    return "quality: %s -> %s" % (old, new)


@tool("Save the current settings changes as a new custom profile.",
      {"name": P("string", "Profile name")}, ["name"])
def save_profile(name):
    _app().getQualityManager().createQualityChanges(name)
    return "profile saved: %s" % name


@tool("Choose 3D planar printing ('classic') or a 5D mode ('cylindrical' is 5D Spiral, 'cylindrical_full' is 5D). Only these three modes are allowed.",
      {"mode": P("string", "Print mode", enum=list(PRINT_MODES)), "reason": P("string", "Why this mode, one sentence")},
      ["mode", "reason"])
def set_print_mode(mode, reason=""):
    if mode not in PRINT_MODES:
        raise ToolError("mode must be one of %s" % sorted(PRINT_MODES))
    stack = _stack()
    old = stack.getProperty("printing_mode", "value")
    stack.userChanges.setProperty("printing_mode", "value", mode)
    SESSION.record("print mode", PRINT_MODES.get(old, old), PRINT_MODES[mode], reason)
    return "printing_mode: %s -> %s" % (old, mode)


# ---------------------------------------------------------------- settings

@tool("Find slicer settings by key or label (there are about 640). Returns key, label, type and current value.",
      {"query": P("string", "Part of the key or the label"), "limit": P("integer", "Maximum rows", default=15)}, ["query"])
def search_settings(query, limit=15):
    needle = query.lower()
    rows = []
    for definition in _stack().definition.findDefinitions():
        if definition.type == "category":
            continue
        if needle in definition.key.lower() or needle in str(definition.label).lower():
            rows.append({"key": definition.key, "label": str(definition.label), "type": definition.type,
                         "unit": getattr(definition, "unit", ""), "value": _value(definition.key)})
        if len(rows) >= int(limit):
            break
    return rows


@tool("Read one setting (global or extruder level).", {"key": P("string", "Setting key")}, ["key"])
def get_setting(key):
    definition = _stack().getSettingDefinition(key)
    if definition is None:
        raise ToolError("Unknown setting: %s. Use search_settings." % key)
    return {"key": key, "label": str(definition.label), "type": definition.type, "value": _value(key)}


def _coerce(definition, value):
    kind = definition.type
    if kind == "bool":
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)
    if kind == "enum":
        if value not in definition.options:
            raise ToolError("%s must be one of %s" % (definition.key, sorted(definition.options)))
        return value
    if kind in ("float", "int"):
        number = float(value)
        stack = _stack()
        low = stack.getProperty(definition.key, "minimum_value")
        high = stack.getProperty(definition.key, "maximum_value")
        if isinstance(low, (int, float)):
            number = max(number, low)
        if isinstance(high, (int, float)):
            number = min(number, high)
        return int(round(number)) if kind == "int" else number
    if kind == "str":
        return str(value)
    raise ToolError("Settings of type %s cannot be changed with this tool" % kind)


@tool("Change one print setting (global or extruder level). Values outside the allowed range are clamped. Printer (machine_*) settings and the print mode are not available here.",
      {"key": P("string", "Setting key from search_settings"), "value": P(["number", "string", "boolean"], "New value"),
       "reason": P("string", "Why, one sentence in the user's language")}, ["key", "value", "reason"])
def set_setting(key, value, reason=""):
    if key.startswith("machine_") or key == "printing_mode":
        raise ToolError("%s cannot be changed here" % key)
    stack = _stack()
    definition = stack.getSettingDefinition(key)
    if definition is None:
        raise ToolError("Unknown setting: %s. Use search_settings." % key)
    new = _coerce(definition, value)
    old = _value(key)
    if stack.getProperty(key, "settable_per_extruder") and stack.extruders:
        for extruder in stack.extruders.values():
            extruder.userChanges.setProperty(key, "value", new)
    else:
        stack.userChanges.setProperty(key, "value", new)
    SESSION.record(key, old, new, reason)
    return "%s: %s -> %s" % (key, old, new)


# ---------------------------------------------------------------- models

def _wait_for_models(count, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        if len(run_on_main(_models)) >= count:
            return True
        time.sleep(0.5)
    return False


@tool("Load an STL, OBJ or 3MF file from a local path onto the build plate.",
      {"path": P("string", "Absolute path to the model file")}, ["path"], on_main=False)
def load_model(path):
    if not os.path.isfile(path):
        raise ToolError("File not found: %s" % path)
    before = len(run_on_main(_models))
    run_on_main(lambda: _app().readLocalFile(QUrl.fromLocalFile(path)))
    if not _wait_for_models(before + 1):
        raise ToolError("The model did not appear on the build plate")
    time.sleep(1)
    return run_on_main(lambda: [_model_row(i, n) for i, n in enumerate(_models())])


SUMMARY_FIELDS = ["machineName", "machineType", "variantType", "qualityName", "qualityType", "numUserSettings",
                  "numSettingsOverridenByQualityChanges", "materialLabels", "activeMode", "machineConflict",
                  "qualityChangesConflict", "materialConflict"]


@tool("Open a .3mf file the way the user does: a slicer project (model plus printer, material and settings) is opened as a project and the data of the slicer's Summary dialog is returned; anything else is loaded as a model only. Reports which way it opened.",
      {"path": P("string", "Absolute path to the .3mf file")}, ["path"], on_main=False)
def open_project(path):
    if not os.path.isfile(path):
        raise ToolError("File not found: %s" % path)
    run_on_main(_stop_slicing)
    handler = run_on_main(lambda: _app().getWorkspaceFileHandler())
    reader = run_on_main(lambda: handler.getReaderForFile(path))
    summary = None
    if reader is not None:
        run_on_main(lambda: handler._readLocalFile(QUrl.fromLocalFile(path)))
        dialog = reader._dialog  # the slicer's own "Open Project / Summary" dialog; the reader blocks on it
        end = time.time() + 20
        while time.time() < end and not dialog._visible:
            time.sleep(0.2)
        if dialog._visible:
            summary = dict((name, getattr(dialog, name)) for name in SUMMARY_FIELDS)
            run_on_main(dialog.onOkButtonClicked)  # the user's "Open" button
    opened_as = "project" if summary is not None else "model_only"
    if summary is None:
        run_on_main(lambda: (_app().deleteAll(), _app().readLocalFile(QUrl.fromLocalFile(path), skip_project_file_check=True)))
    if not _wait_for_models(1, timeout=60):
        raise ToolError("Nothing was loaded from %s (opened_as=%s). The slicer could not read it; see stderr.log." % (path, opened_as))
    time.sleep(1)
    state = run_on_main(get_state)
    return {"opened_as": opened_as, "summary": summary, "printer": state["printer"], "print_mode": state["print_mode"],
            "material_id": state["material_id"], "quality": state["quality"], "settings": state["settings"],
            "models": state["models"]}


@tool("Remove a printer from the slicer by its id from list_printers. The active printer cannot be removed.",
      {"printer_id": P("string", "Printer id")}, ["printer_id"])
def remove_printer(printer_id):
    active = _app().getGlobalContainerStack()
    if active is not None and active.getId() == printer_id:
        raise ToolError("The active printer cannot be removed. Select another printer first.")
    _app().getMachineManager().removeMachine(printer_id)
    return "printer removed: %s" % printer_id


@tool("Models on the build plate: index, name, size and position in mm.")
def list_models():
    return [_model_row(i, node) for i, node in enumerate(_models())]


@tool("Move a model on the plate: x and z are millimetres from the plate center.",
      {"model_index": P("integer", "Index from list_models", default=0), "x": P("number", "X in mm"), "z": P("number", "Z in mm")},
      ["x", "z"])
def move_model(x, z, model_index=0):
    node = _model(model_index)
    TranslateOperation(node, Vector(float(x), node.getWorldPosition().y, float(z)), set_position=True).push()
    return "moved to x=%s z=%s" % (x, z)


@tool("Rotate a model. The scene is Y-up: rotate about x or z to lay a part on another face, about y to turn it on the plate.",
      {"model_index": P("integer", "Index from list_models", default=0), "axis": P("string", "Rotation axis", enum=["x", "y", "z"]),
       "degrees": P("number", "Angle in degrees"), "reason": P("string", "Why, one sentence")}, ["axis", "degrees", "reason"])
def rotate_model(axis, degrees, reason="", model_index=0):
    node = _model(model_index)
    unit = {"x": Vector.Unit_X, "y": Vector.Unit_Y, "z": Vector.Unit_Z}[axis]
    RotateOperation(node, Quaternion.fromAngleAxis(math.radians(float(degrees)), unit)).push()
    SESSION.record("rotation %s" % axis, "0", "%s deg" % degrees, reason)
    return "rotated %s by %s degrees" % (node.getName(), degrees)


@tool("Scale a model uniformly by a factor (1.0 keeps the size).",
      {"model_index": P("integer", "Index from list_models", default=0), "factor": P("number", "Scale factor"),
       "reason": P("string", "Why, one sentence")}, ["factor", "reason"])
def scale_model(factor, reason="", model_index=0):
    node = _model(model_index)
    factor = float(factor)
    if factor <= 0.01:
        raise ToolError("factor must be greater than 0.01")
    current = node.getScale()
    ScaleOperation(node, Vector(current.x * factor, current.y * factor, current.z * factor), set_scale=True).push()
    SESSION.record("scale", "1.0", str(factor), reason)
    return "scaled %s by %s" % (node.getName(), factor)


@tool("Remove a model from the build plate.", {"model_index": P("integer", "Index from list_models", default=0)})
def delete_model(model_index=0):
    node = _model(model_index)
    name = node.getName()
    _stop_slicing()
    RemoveSceneNodeOperation(node).push()
    return "removed %s" % name


@tool("Arrange all models on the build plate.")
def arrange_models():
    _app().arrangeAll()
    return "models arranged"


def _triangles(node):
    mesh = node.getMeshDataTransformed()
    vertices = mesh.getVertices()
    indices = mesh.getIndices()
    return vertices[indices] if indices is not None else vertices.reshape(-1, 3, 3)


def _orientation_rows(node):
    import numpy
    triangles = _triangles(node).astype(numpy.float64)
    cross = numpy.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    areas = numpy.linalg.norm(cross, axis=1) / 2.0
    normals = cross / numpy.maximum(2.0 * areas, 1e-12)[:, None]
    total = float(areas.sum())
    rows = []
    for name, down in DOWN_VECTORS.items():
        down = numpy.array(down, dtype=numpy.float64)
        heights = triangles.dot(-down)
        base = heights.min()
        height = float(heights.max() - base)
        face_min = heights.min(axis=1) - base
        face_max = heights.max(axis=1) - base
        facing_down = normals.dot(down)
        contact = float(areas[(facing_down > 0.98) & (face_max < 0.3)].sum())
        overhang = float(areas[(facing_down > math.cos(math.radians(45))) & (face_min >= 0.3)].sum())
        projected = float(0.5 * (areas * numpy.abs(normals.dot(-down))).sum())
        axes = [a for a in range(3) if abs(down[a]) < 0.5]
        spans = [float(triangles[:, :, a].max() - triangles[:, :, a].min()) for a in axes]
        extent = max(max(spans), height, 1e-6)
        r_support = overhang / total if total else 0.0
        r_base = min(1.0, contact / projected) if projected else 0.0
        r_slender = height / max(min(spans), 1e-6)
        r_height = height / extent
        score = 0.58 * r_support + 0.16 * min(1.0, r_slender / 10.0) + 0.12 * (1.0 - r_base) + 0.14 * r_height
        rows.append({"orientation": name, "height_mm": round(height, 2), "contact_area_mm2": round(contact, 1),
                     "overhang_area_mm2": round(overhang, 1), "support_share": round(r_support, 3),
                     "score": round(score, 3)})
    rows.sort(key=lambda r: r["score"])
    return rows


@tool("Compare the six face-down orientations of a model by overhang area, plate contact and height (lower score is better, heuristic after Du et al. 2026).",
      {"model_index": P("integer", "Index from list_models", default=0)})
def analyze_orientation(model_index=0):
    return _orientation_rows(_model(model_index))


@tool("Rotate a model so that the chosen face lies on the plate. Use 'best' for the lowest score from analyze_orientation.",
      {"model_index": P("integer", "Index from list_models", default=0),
       "orientation": P("string", "Orientation name or 'best'", enum=["best"] + sorted(ORIENTATIONS)),
       "reason": P("string", "Why, one sentence")}, ["orientation", "reason"])
def orient_model(orientation, reason="", model_index=0):
    node = _model(model_index)
    if orientation == "best":
        orientation = _orientation_rows(node)[0]["orientation"]
    if orientation not in ORIENTATIONS:
        raise ToolError("orientation must be 'best' or one of %s" % sorted(ORIENTATIONS))
    axis, degrees = ORIENTATIONS[orientation]
    if axis is not None:
        unit = {"x": Vector.Unit_X, "z": Vector.Unit_Z}[axis]
        RotateOperation(node, Quaternion.fromAngleAxis(math.radians(degrees), unit)).push()
    SESSION.record("orientation", "current", orientation, reason)
    return "orientation: %s" % orientation


# ---------------------------------------------------------------- slicing

def _stop_slicing():
    """Clearing the scene while the engine still delivers G-code crashes the slicer (KeyError in CuraEngineBackend), so stop it first."""
    _app().getBackend().stopSlicing()
    SESSION.slice_state = None


def _on_backend_state(state):
    SESSION.slice_state = state


def _on_progress(progress):
    SESSION.slice_progress = float(progress)


def _hook_backend():
    """Follow the state of the active slicing backend; it changes with the print mode."""
    backend = _app().getBackend()
    if backend is not SESSION.backend:
        if SESSION.backend is not None:
            try:
                SESSION.backend.backendStateChange.disconnect(_on_backend_state)
                SESSION.backend.processingProgress.disconnect(_on_progress)
            except Exception:
                pass
        SESSION.backend = backend
        backend.backendStateChange.connect(_on_backend_state)
        backend.processingProgress.connect(_on_progress)
    return backend


def _start_slice():
    if not _models():
        raise ToolError("There are no models on the build plate. Use load_model first.")
    backend = _hook_backend()
    SESSION.restarts = 0
    SESSION.last_start = time.time()
    if SESSION.slice_state != BackendState.Processing:
        # restarting the engine while the slicer's own automatic slicing is running crashes the slicer
        SESSION.slice_state = None
        SESSION.slice_progress = 0.0
        backend.forceSlice()
    return "slicing started"


def _gcode():
    return getattr(_app().getController().getScene(), "gcode_dict", {}).get(0)


def _poll_slice():
    """Slicing is aborted whenever the scene changes, so it is restarted when it falls back to NotStarted."""
    if SESSION.slice_state == BackendState.Error:
        return "error"
    if SESSION.slice_state == BackendState.Done and _gcode():
        return "done"
    if SESSION.slice_state == BackendState.NotStarted and time.time() - SESSION.last_start > 4 and SESSION.restarts < 5:
        SESSION.restarts += 1
        SESSION.last_start = time.time()
        SESSION.backend.forceSlice()
        return "restarted"
    return "waiting"


def _print_info():
    info = _app().getPrintInformation()
    duration = info.currentPrintTime
    seconds = int(duration.days) * 86400 + int(duration.hours) * 3600 + int(duration.minutes) * 60 + int(duration.seconds)
    weights = [float(w) for w in info.materialWeights]
    lengths = [float(l) for l in info.materialLengths]
    return {"print_time_seconds": seconds, "print_time": duration.getDisplayString(),
            "material_grams": round(sum(weights), 2), "material_meters": round(sum(lengths), 2)}


@tool("Current slicing state, progress (0..1) and, once finished, print time and material use.")
def get_slicing_status():
    names = {BackendState.NotStarted: "not_started", BackendState.Processing: "processing",
             BackendState.Done: "done", BackendState.Error: "error", BackendState.Disabled: "disabled"}
    status = {"state": names.get(SESSION.slice_state, "not_started"), "progress": round(SESSION.slice_progress, 3)}
    if SESSION.slice_state == BackendState.Done:
        status.update(_print_info())
    return status


@tool("Slice the scene with the current settings and wait for the result. Returns print time and material use. Takes up to a few minutes; 5D modes need an activated STE Slicer license.",
      on_main=False)
def slice_model():
    run_on_main(_start_slice)
    begin = time.time()
    while time.time() - begin < 300:
        state = run_on_main(_poll_slice)
        if state == "done":
            time.sleep(1.5)
            return run_on_main(get_slicing_status)
        if state == "error":
            raise ToolError("Slicing failed. Check the model, the printer profile and the STE Slicer license.")
        if SESSION.slice_state is None and time.time() - begin > 25:
            raise ToolError("Slicing did not start. In 5D modes check the STE Slicer license window.")
        time.sleep(1)
    raise ToolError("Slicing timed out")


def _result_path(name, path):
    if path:
        directory = os.path.dirname(path) or "."
        os.makedirs(directory, exist_ok=True)
        return path
    models = _models()
    base = os.path.splitext(models[0].getName())[0] if models else "result"
    return os.path.join(settings.data_dir("results", base), name)


@tool("Save the G-code of the last slicing. The default path is Documents/STE_AIAssistant/results/<model>/result.gcode.",
      {"path": P("string", "Output .gcode path (optional)")})
def export_gcode(path=None):
    lines = _gcode()
    if not lines:
        raise ToolError("There is no G-code. Run slice_model first.")
    path = _result_path("result.gcode", path)
    with open(path, "w", encoding="utf-8") as stream:
        stream.write("".join(lines))
    return {"path": path, "bytes": os.path.getsize(path)}


@tool("Save the scene with all settings as a .3mf project. The default path is Documents/STE_AIAssistant/results/<model>/project.3mf.",
      {"path": P("string", "Output .3mf path (optional)")}, on_main=False)
def save_project(path=None):
    path = run_on_main(lambda: _result_path("project.3mf", path))
    # the 3MF workspace writer hops to the Qt thread by itself, so it must not be called from it
    writer = run_on_main(lambda: _app().getWorkspaceFileHandler().getWriter("3MFWriter"))
    if writer is None:
        raise ToolError("3MF workspace writer not found")
    root = run_on_main(lambda: _app().getController().getScene().getRoot())
    with open(path, "wb") as stream:
        writer.write(stream, [root])
    return {"path": path, "bytes": os.path.getsize(path)}


def call(name, arguments):
    """Run a tool and return its JSON-serialisable result; raises ToolError for expected failures."""
    if name not in TOOLS:
        raise ToolError("Unknown tool: %s" % name)
    entry = TOOLS[name]
    arguments = arguments or {}
    try:
        if entry.on_main:
            result = run_on_main(lambda: (_hook_backend(), entry.handler(**arguments))[1])
        else:
            result = entry.handler(**arguments)
    except TypeError as error:
        raise ToolError("Bad arguments for %s: %s" % (name, error))
    Logger.log("d", "AI Assistant tool %s(%s)", name, json.dumps(arguments, ensure_ascii=False))
    return result

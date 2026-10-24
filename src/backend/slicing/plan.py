"""The plugin calls that apply a parameter set, slice it and save the G-code and the project.

Ported from ``tools/slicing/apply_parameter_set.py`` (FedorSolodkin), whose order of calls,
axes and offsets were checked on STE Slicer 7.10.12 under Windows on 24.10.2026. The plan
starts from an empty plate; the slicer's own settings left by an earlier run are reset by the
caller when the plugin can do it.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping

from ..domain.parameters import ParameterSet, PlacedModel
from ..domain.slicing import SlicerCall, Unsupported

# Below these the angle or the difference of scale factors is rounding, not a request.
ANGLE_EPSILON = 1e-6
SCALE_EPSILON = 1e-9


def build_plan(
    parameter_set: ParameterSet, models: Mapping[str, str], gcode: str, project: str
) -> tuple[list[SlicerCall], list[Unsupported]]:
    """``models`` maps an attachment id to its file as the slicer sees it; ``gcode`` and
    ``project`` are where the slicer saves the result."""
    calls = [
        SlicerCall(
            step="set_printer", tool="set_printer", args={"definition_id": parameter_set.printer}
        ),
        SlicerCall(
            step="set_print_mode",
            tool="set_print_mode",
            args={
                "mode": parameter_set.printing_mode.value,
                "reason": parameter_set.printing_mode.why,
            },
        ),
        SlicerCall(
            step="set_quality_profile",
            tool="set_quality_profile",
            args={
                "quality_type": parameter_set.quality.quality_type,
                "reason": parameter_set.quality.why,
            },
        ),
    ]
    unsupported = []
    for position, material in parameter_set.materials.items():
        step = f"set_material[{position}]"
        if position != "0":
            unsupported.append(
                Unsupported(step=step, reason="плагин меняет материал только у экструдера 0")
            )
            continue
        calls.append(
            SlicerCall(
                step=step,
                tool="set_material",
                args={"material_id": material.id, "reason": material.why},
            )
        )
    for key, setting in parameter_set.settings.items():
        step = f"set_setting[{key}]"
        if key == "printing_mode" or key.startswith("machine_"):
            unsupported.append(
                Unsupported(step=step, reason=f"{key} не меняется через set_setting")
            )
            continue
        # List settings are strings in the slicer, as "[0, 90]".
        value = json.dumps(setting.value) if isinstance(setting.value, list) else setting.value
        calls.append(
            SlicerCall(
                step=step,
                tool="set_setting",
                args={"key": key, "value": value, "reason": setting.why},
            )
        )
    for index, model in enumerate(parameter_set.models):
        if model.attachment_id not in models:
            raise KeyError(model.attachment_id)
        calls.extend(_placement(index, model, models[model.attachment_id], unsupported))
    calls += [
        SlicerCall(step="slice_model", tool="slice_model", args={}),
        SlicerCall(step="export_gcode", tool="export_gcode", args={"path": gcode}),
        SlicerCall(step="save_project", tool="save_project", args={"path": project}),
    ]
    return calls, unsupported


def _placement(
    index: int, model: PlacedModel, path: str, unsupported: list[Unsupported]
) -> list[SlicerCall]:
    calls = [SlicerCall(step=f"load_model[{index}]", tool="load_model", args={"path": path})]
    for axis, degrees in euler_steps(model.transform.rotation):
        scene_axis, scene_degrees = scene_rotation(axis, degrees)
        calls.append(
            SlicerCall(
                step=f"rotate_model[{index},{scene_axis}]",
                tool="rotate_model",
                args={
                    "axis": scene_axis,
                    "degrees": scene_degrees,
                    "reason": model.why,
                    "model_index": index,
                },
            )
        )
    x, y, z = model.transform.scale
    if abs(x - y) < SCALE_EPSILON and abs(y - z) < SCALE_EPSILON:
        if abs(x - 1.0) >= SCALE_EPSILON:
            calls.append(
                SlicerCall(
                    step=f"scale_model[{index}]",
                    tool="scale_model",
                    args={"factor": x, "reason": model.why, "model_index": index},
                )
            )
    else:
        reason = f"плагин масштабирует только равномерно, запрошено [{x}, {y}, {z}]"
        unsupported.append(Unsupported(step=f"scale_model[{index}]", reason=reason))
    # The set's Y is the machine's Y, which is minus Z of the slicer's scene; the height
    # follows from the plate.
    offset_x, offset_y = model.transform.position[0], model.transform.position[1]
    calls.append(
        SlicerCall(
            step=f"move_model[{index}]",
            tool="move_model",
            args={"x": offset_x, "z": -offset_y, "model_index": index},
        )
    )
    return calls


def euler_steps(rotation: list[list[float]]) -> list[tuple[str, float]]:
    """``rotation`` as turns about x, then y, then z of the set: R = Rz(c)·Ry(b)·Rx(a)."""
    sin_b = -rotation[2][0]
    if abs(sin_b) >= 1.0 - 1e-9:
        # Gimbal lock at b = ±90°: only a + c or a - c is defined, so c is taken as zero.
        b = math.copysign(math.pi / 2, sin_b)
        sign = 1 if sin_b > 0 else -1
        a, c = math.atan2(sign * rotation[0][1], rotation[1][1]), 0.0
    else:
        b = math.asin(sin_b)
        cos_b = math.cos(b)
        a = math.atan2(rotation[2][1] / cos_b, rotation[2][2] / cos_b)
        c = math.atan2(rotation[1][0] / cos_b, rotation[0][0] / cos_b)
    turns = [("x", math.degrees(a)), ("y", math.degrees(b)), ("z", math.degrees(c))]
    return [(axis, degrees) for axis, degrees in turns if abs(degrees) >= ANGLE_EPSILON]


def scene_rotation(axis: str, degrees: float) -> tuple[str, float]:
    """An axis of the set (Z up, as the STL and the plate) as the axis of the scene (Y up).

    The scene takes a point of the STL as (x, z, -y): x stays x, Z of the set is y of the
    scene and Y of the set is z of the scene with the opposite sign.
    """
    if axis == "x":
        return "x", degrees
    if axis == "y":
        return "z", -degrees
    return "y", degrees

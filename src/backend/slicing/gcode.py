"""What the G-code of a slicing shows, checked against the parameter set it was sliced from.

Ported from ``tools/slicing/check_gcode.py`` (FedorSolodkin), checked on two G-code files of
STE Slicer 7.10.12 for the Hybrid 530 V5.2.4. The file is read line by line: a 15 MB G-code
takes about two seconds and is never held in memory.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Literal

from ..domain.catalog import Catalog, ModeValues
from ..domain.parameters import Exclusion, Feedback, FeedbackWarning, ParameterSet
from ..domain.slicing import GcodeCheck, GcodeFinding

# A move this far past the bed is still rounding of the slicer, not a model off the bed.
COORD_TOLERANCE = 0.5
FIVE_D = ("cylindrical", "cylindrical_full")
_AXIS = {axis: re.compile(axis + r"([-\d.]+)") for axis in "XYZE"}
_TEMPERATURE = re.compile(r"S(\d+)")


@dataclass
class Bounds:
    low: float | None = None
    high: float | None = None

    def add(self, value: float) -> None:
        self.low = value if self.low is None else min(self.low, value)
        self.high = value if self.high is None else max(self.high, value)


@dataclass
class GcodeFacts:
    lines: int = 0
    header: dict[str, str] = field(default_factory=dict)
    layer_count: int | None = None
    layers: int = 0
    types: Counter[str] = field(default_factory=Counter)
    nozzle: list[int] = field(default_factory=list)
    bed: list[int] = field(default_factory=list)
    bounds: dict[str, Bounds] = field(default_factory=lambda: {a: Bounds() for a in "XYZ"})
    max_extrusion: float | None = None
    ended: bool = False
    settings: dict[str, str] = field(default_factory=dict)
    settings_error: str | None = None


_HEADER = {
    ";PRINTING_MODE:": "printing_mode",
    ";Layer height:": "layer_height",
    ";TIME:": "time",
    ";Filament used:": "filament",
}


def read_gcode(lines: Iterable[str]) -> GcodeFacts:
    facts = GcodeFacts()
    serialized: list[str] = []
    for number, raw in enumerate(lines, 1):
        facts.lines = number
        line = raw.strip()
        if line.startswith(";SETTING_3 "):
            # A piece of the settings may end in a space that belongs to a value.
            serialized.append(raw.rstrip("\r\n").lstrip()[len(";SETTING_3 ") :])
        elif line.startswith(";"):
            _comment(facts, line)
        elif line.startswith(("M104 ", "M109 ", "M140 ", "M190 ")):
            found = _TEMPERATURE.search(line)
            if found and int(found.group(1)) > 0:
                target = facts.nozzle if line[:4] in ("M104", "M109") else facts.bed
                target.append(int(found.group(1)))
        elif line.startswith(("G0 ", "G1 ")):
            _move(facts, line)
    if serialized:
        _settings(facts, "".join(serialized))
    return facts


def _comment(facts: GcodeFacts, line: str) -> None:
    for prefix, name in _HEADER.items():
        if line.startswith(prefix):
            facts.header[name] = line[len(prefix) :].strip().strip("[]")
            return
    if line.startswith(";LAYER_COUNT:"):
        facts.layer_count = int(line.split(":", 1)[1])
    elif line.startswith(";LAYER:"):
        facts.layers += 1
    elif line.startswith(";TYPE:"):
        facts.types[line.split(":", 1)[1]] += 1
    elif line.startswith(";End of Gcode"):
        facts.ended = True


def _move(facts: GcodeFacts, line: str) -> None:
    for axis in "XYZ":
        found = _AXIS[axis].search(line)
        if found:
            facts.bounds[axis].add(float(found.group(1)))
    extrusion = _AXIS["E"].search(line)
    if extrusion:
        value = float(extrusion.group(1))
        if facts.max_extrusion is None or value > facts.max_extrusion:
            facts.max_extrusion = value


def _settings(facts: GcodeFacts, text: str) -> None:
    """The changed settings the slicer serialized at the end of the file, as INI sections."""
    try:
        data = json.loads(text)
        profiles = [data.get("global_quality", ""), *data.get("extruder_quality", [])]
    except (ValueError, AttributeError, TypeError) as exc:
        facts.settings_error = str(exc)
        return
    for profile in profiles:
        inside = False
        for row in re.split(r"\\n|\n", profile):
            row = row.strip()
            if row.startswith("["):
                inside = row == "[values]"
            elif inside and "=" in row:
                key, value = row.split("=", 1)
                facts.settings[key.strip()] = value.strip()


def check_gcode(
    facts: GcodeFacts, parameter_set: ParameterSet, catalog: Catalog, iteration: int
) -> GcodeCheck:
    findings: list[GcodeFinding] = []

    def add(kind: str, level: str, message: str, key: str | None = None) -> None:
        findings.append(
            GcodeFinding.model_validate(
                {
                    "id": f"G{len(findings) + 1}",
                    "kind": kind,
                    "level": level,
                    "message": message,
                    "key": key,
                }
            )
        )

    mode = parameter_set.printing_mode.value
    settings = {key: setting.value for key, setting in parameter_set.settings.items()}
    _file(facts, add)
    written_mode = facts.header.get("printing_mode")
    if written_mode is None:
        # Plugins before the export through the slicer's G-code writer saved no such header.
        add("apply", "info", "в G-code нет строки ;PRINTING_MODE, режим не проверен")
    elif written_mode != mode:
        add("apply", "error", f"режим в G-code {written_mode}, ожидался {mode}", "printing_mode")
    _layer_height(facts, parameter_set, catalog, add)
    _temperatures(facts, catalog.values(mode, settings), settings, mode, add)
    _written_settings(facts, settings, add)
    if mode == "classic":
        _bed(facts, catalog, add)
    else:
        add("content", "info", "габариты в 5D по G-code не проверяются")
    supports = facts.types["SUPPORT"] + facts.types["SUPPORT-INTERFACE"]
    if settings.get("support_enable") is False and supports:
        add("apply", "error", "поддержки выключены, но в G-code они есть", "support_enable")
    _summary(facts, add)
    return _verdict(findings, parameter_set, iteration)


def _file(facts: GcodeFacts, add) -> None:
    if facts.lines < 3:
        add("file", "error", "файл G-code пустой")
    if not facts.layers:
        add("file", "error", "в G-code нет слоёв")
    if not facts.ended:
        add("file", "error", "G-code оборван: нет строки ;End of Gcode")
    # The last layer is not always marked, and a turned model gave 762 layers for 765 on
    # Windows, so a gap is a warning: a cut file is caught by the missing end above.
    declared = facts.layer_count
    if declared is not None and facts.layers not in (declared, declared - 1):
        add("file", "warning", f"заявлено слоёв {declared}, найдено {facts.layers}")
    if facts.max_extrusion is None or facts.max_extrusion <= 0:
        add("file", "error", "в G-code нет экструзии")


def _layer_height(facts: GcodeFacts, parameter_set: ParameterSet, catalog: Catalog, add) -> None:
    written = _number(facts.header.get("layer_height"))
    if written is None:
        return
    expected = _number(_expected_layer_height(parameter_set, catalog))
    if expected is not None and abs(written - expected) > 1e-6:
        add("apply", "error", f"высота слоя {written} мм, ожидалась {expected} мм", "layer_height")


def _expected_layer_height(parameter_set: ParameterSet, catalog: Catalog) -> Any:
    if "layer_height" in parameter_set.settings:
        return parameter_set.settings["layer_height"].value
    quality = catalog.qualities.get(parameter_set.quality.quality_type)
    if quality is not None and "layer_height" in quality.values:
        return quality.values["layer_height"]
    return catalog.values(parameter_set.printing_mode.value).get("layer_height")


def _temperatures(
    facts: GcodeFacts, values: ModeValues, settings: dict[str, Any], mode: str, add
) -> None:
    """Every heating command sets a temperature the set asks for: the print's or the first
    layer's, which follows the print by the build's formula unless the set gives its own."""
    nozzle = settings.get("material_print_temperature")
    if nozzle is not None:
        layer = values.get("material_print_temperature_layer_0")
        _heated(facts.nozzle, {nozzle, layer}, "сопла", nozzle, "material_print_temperature", add)
    bed = settings.get("material_bed_temperature")
    if bed is not None and mode == "classic":
        layer = values.get("material_bed_temperature_layer_0")
        _heated(facts.bed, {bed, layer}, "стола", bed, "material_bed_temperature", add)
    if mode in FIVE_D and facts.bed:
        add(
            "apply",
            "warning",
            "в 5D стол не греется, а в G-code есть его нагрев",
            "material_bed_temperature",
        )


def _heated(found: list[int], asked: set[Any], what: str, expected: Any, key: str, add) -> None:
    other = sorted(set(found) - asked)
    if other:
        message = (
            f"температура {what} в G-code {', '.join(map(str, other))} °C, ожидалась {expected} °C"
        )
        add("apply", "error", message, key)


def _written_settings(facts: GcodeFacts, settings: dict[str, Any], add) -> None:
    if facts.settings_error:
        add("apply", "info", f"блок ;SETTING_3 не прочитан: {facts.settings_error}")
    unchecked = []
    for key, value in settings.items():
        if key not in facts.settings:
            unchecked.append(key)
        elif not _same(value, facts.settings[key]):
            message = f"{key} в G-code {facts.settings[key]}, ожидалось {value}"
            add("apply", "error", message, key)
    if unchecked:
        add("apply", "info", "по G-code не проверить: " + ", ".join(unchecked))


def _same(value: Any, written: str) -> bool:
    if isinstance(value, bool):
        return written.lower() == str(value).lower()
    if isinstance(value, int | float):
        number = _number(written)
        return number is not None and abs(number - value) <= 1e-9
    return written == (json.dumps(value) if isinstance(value, list) else str(value))


def _bed(facts: GcodeFacts, catalog: Catalog, add) -> None:
    """Moves in machine coordinates of the classic bed, its corner at zero."""
    values = catalog.values("classic")
    sizes = {"X": "machine_width", "Y": "machine_depth", "Z": "machine_height"}
    for axis, key in sizes.items():
        size, bounds = float(values.get(key)), facts.bounds[axis]
        if bounds.low is None or bounds.high is None:
            continue
        if bounds.low < -COORD_TOLERANCE or bounds.high > size + COORD_TOLERANCE:
            message = (
                f"модель выходит за стол по {axis}: [{bounds.low:.1f}, {bounds.high:.1f}] "
                f"при области [0, {size:g}]"
            )
            add("content", "error", message)


def _summary(facts: GcodeFacts, add) -> None:
    seconds = _number(facts.header.get("time"))
    if seconds is not None:
        hours, minutes = divmod(int(seconds) // 60, 60)
        add("apply", "info", f"время печати {hours} ч {minutes} мин")
    if facts.header.get("filament"):
        add("apply", "info", f"расход {facts.header['filament']}")
    add("apply", "info", f"слоёв {facts.layer_count or facts.layers}")


def _verdict(
    findings: list[GcodeFinding], parameter_set: ParameterSet, iteration: int
) -> GcodeCheck:
    errors = [finding for finding in findings if finding.level == "error"]
    exclude, warnings = [], []
    for finding in errors:
        if finding.kind == "content":
            candidates = [model.orientation_candidate for model in parameter_set.models[:1]]
            exclude += [
                Exclusion(type="orientation", candidate=candidate, reason=finding.message)
                for candidate in candidates
            ]
    for finding in findings:
        if finding.level == "warning":
            warnings.append(FeedbackWarning(key=finding.key or "gcode", reason=finding.message))
    result: Literal["ok", "needs_changes", "apply_failed"]
    if any(finding.kind == "content" for finding in errors):
        result = "needs_changes"
    else:
        result = "apply_failed" if errors else "ok"
    feedback = Feedback(
        iteration=iteration,
        result="needs_changes" if result == "needs_changes" else "ok",
        exclude=exclude,
        warnings=warnings,
    )
    return GcodeCheck(result=result, findings=findings, feedback=feedback)


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

"""Reader of STE Slicer material files (*.fdm_material) joined with general-knowledge traits."""

import os
import xml.etree.ElementTree as ElementTree
from typing import Any  # noqa: F401  (used in type comments)

from tuning.errors import TuningError
from tuning.serialization import load_json_file

_NAMESPACE = {"m": "http://www.ultimaker.com/material"}
_SUFFIX = ".xml.fdm_material"
_TRAITS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "traits.json")
_DIAMETER_TOLERANCE_MM = 1e-6


class Material(object):
    def __init__(self, material_id, label, description, density, diameter, settings, traits):
        # type: (str, str, str, float, float, dict, dict) -> None
        self.id = material_id
        self.label = label
        self.description = description
        self.density = density
        self.diameter = diameter
        self.print_temperature = settings.get("print temperature")
        self.bed_temperature = settings.get("heated bed temperature")
        self.speed = settings.get("speed print")
        self.cooling_pct = settings.get("print cooling")
        self.traits = traits


def load_traits():
    # type: () -> dict
    return load_json_file(_TRAITS_PATH)


def _number(text):
    return float(text) if text not in (None, "") else None


def read_materials(directory, filament_mm):
    # type: (str, float) -> dict
    """Return {material_id: Material} for the material files whose filament fits the extruder.

    The slicer hides materials of another filament diameter (2.85 mm generics on a 1.75 mm extruder), so a
    lookup by name such as "PLA" must not land on them.
    """
    traits = load_traits()["materials"]
    materials = {}
    for filename in sorted(os.listdir(directory)):
        if not filename.endswith(_SUFFIX):
            continue
        root = ElementTree.parse(os.path.join(directory, filename)).getroot()
        material_id = filename[: -len(_SUFFIX)]
        name = root.find("m:metadata/m:name", _NAMESPACE)
        if name is None:
            raise TuningError("%s has no metadata/name" % filename)
        label = name.findtext("m:label", namespaces=_NAMESPACE) or name.findtext("m:material", namespaces=_NAMESPACE)
        settings = {
            item.get("key"): _number(item.text)
            for item in root.findall("m:settings/m:setting", _NAMESPACE)
            if item.get("key") in ("print temperature", "heated bed temperature", "speed print", "print cooling")
        }
        diameter = _number(root.findtext("m:properties/m:diameter", namespaces=_NAMESPACE))
        if diameter is None or abs(diameter - filament_mm) > _DIAMETER_TOLERANCE_MM:
            continue
        materials[material_id] = Material(
            material_id,
            label or material_id,
            " ".join((root.findtext("m:metadata/m:description", namespaces=_NAMESPACE) or "").split()),
            _number(root.findtext("m:properties/m:density", namespaces=_NAMESPACE)),
            diameter,
            settings,
            traits.get(material_id, {}),
        )
    return materials


def find_material(materials, name):
    # type: (dict, str) -> Any
    """Look a material up by file id or label, case-insensitively."""
    wanted = name.strip().lower()
    for material in materials.values():
        if wanted in (material.id.lower(), material.label.lower()):
            return material
    return None

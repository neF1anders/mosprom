"""Reader of STE Slicer material files (*.fdm_material) joined with general-knowledge traits."""

import os
import xml.etree.ElementTree as ElementTree
from typing import Any  # noqa: F401  (used in type comments)

from tuning.errors import TuningError
from tuning.serialization import load_json_file

_NAMESPACE = {"m": "http://www.ultimaker.com/material"}
_SUFFIX = ".xml.fdm_material"
_TRAITS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "traits.json")
DEFAULT_SPEED_MM_S = 50.0


class Material(object):
    def __init__(self, material_id, label, description, density, settings, traits):
        # type: (str, str, str, float, dict, dict) -> None
        self.id = material_id
        self.label = label
        self.description = description
        self.density = density
        self.print_temperature = settings.get("print temperature")
        self.bed_temperature = settings.get("heated bed temperature")
        self.speed = settings.get("speed print")
        self.cooling_pct = settings.get("print cooling")
        self.traits = traits

    def context(self):
        # type: () -> dict
        """Numbers used by search-space references; speed falls back to a documented default."""
        return {
            "print_temperature": self.print_temperature,
            "bed_temperature": self.bed_temperature,
            "speed": self.speed if self.speed is not None else DEFAULT_SPEED_MM_S,
        }


def load_traits():
    # type: () -> dict
    return load_json_file(_TRAITS_PATH)


def _number(text):
    return float(text) if text not in (None, "") else None


def read_materials(directory):
    # type: (str) -> dict
    """Return {material_id: Material} for every material file in the directory."""
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
        materials[material_id] = Material(
            material_id,
            label or material_id,
            " ".join((root.findtext("m:metadata/m:description", namespaces=_NAMESPACE) or "").split()),
            _number(root.findtext("m:properties/m:density", namespaces=_NAMESPACE)),
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

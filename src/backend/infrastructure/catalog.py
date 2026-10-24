"""Reads the issued STE Slicer build from disk into a ``Catalog``, once per process."""

from __future__ import annotations

import configparser
import hashlib
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any
from xml.etree import ElementTree

from ..domain.catalog import Catalog, MaterialProfile, QualityProfile

_MATERIAL = {"m": "http://www.ultimaker.com/material"}
_MATERIAL_SUFFIX = ".xml.fdm_material"
_MATERIAL_SETTINGS = {
    "print temperature": "print_temperature",
    "heated bed temperature": "bed_temperature",
    "speed print": "speed",
    "print cooling": "cooling_percent",
}


def load_catalog(root: Path, printer: str) -> Catalog:
    definitions = root / "definitions"
    chain = _chain(definitions, printer)
    settings: dict[str, dict[str, Any]] = {}
    _flatten(_json(definitions / "fdmprinter.def.json")["settings"], settings)
    return Catalog(
        printer=printer,
        digest=_digest(root),
        settings=MappingProxyType(settings),
        printer_overrides=MappingProxyType(_printer_overrides(chain)),
        extruder_overrides=MappingProxyType(_extruder_overrides(root / "extruders", chain)),
        qualities=MappingProxyType(_qualities(root / "quality")),
        materials=MappingProxyType(_materials(root / "materials")),
    )


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _digest(root: Path) -> str:
    """Identifies the build a result was computed from."""
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _chain(definitions: Path, printer: str) -> list[dict[str, Any]]:
    """The printer's definition and its ancestors, most specific first."""
    chain: list[dict[str, Any]] = []
    name: str | None = printer
    while name and all(d.get("id") != name for d in chain):
        definition = _json(definitions / f"{name}.def.json")
        chain.append({**definition, "id": name})
        name = definition.get("inherits")
    return chain


def _flatten(node: dict[str, Any], out: dict[str, dict[str, Any]]) -> None:
    """Settings without their category nesting; children follow their parents."""
    for key, value in node.items():
        if value.get("type") != "category":
            out[key] = {k: v for k, v in value.items() if k != "children"}
        _flatten(value.get("children", {}), out)


def _printer_overrides(chain: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    overrides: dict[str, dict[str, Any]] = {}
    for definition in reversed(chain):
        for key, value in definition.get("overrides", {}).items():
            overrides[key] = value if isinstance(value, dict) else {"default_value": value}
    return overrides


def _extruder_overrides(extruders: Path, chain: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    trains: dict[str, str] = next(
        (d["metadata"]["machine_extruder_trains"] for d in chain if _trains(d)),
        {},
    )
    found = {}
    for position, extruder in sorted(trains.items(), key=lambda item: int(item[0])):
        overrides = _json(extruders / f"{extruder}.def.json").get("overrides", {})
        found[position] = {key: _default(value) for key, value in overrides.items()}
    return found


def _trains(definition: dict[str, Any]) -> bool:
    return bool(definition.get("metadata", {}).get("machine_extruder_trains"))


def _default(value: Any) -> Any:
    return value.get("default_value") if isinstance(value, dict) else value


def _qualities(folder: Path) -> dict[str, QualityProfile]:
    qualities = {}
    for path in sorted(folder.glob("*.inst.cfg")):
        config = configparser.ConfigParser(interpolation=None, strict=False)
        config.read(path, encoding="utf-8")
        quality_type = config.get("metadata", "quality_type")
        values = dict(config["values"]) if config.has_section("values") else {}
        qualities[quality_type] = QualityProfile(
            quality_type, config.get("general", "name"), MappingProxyType(values)
        )
    return qualities


def _materials(folder: Path) -> dict[str, MaterialProfile]:
    return {
        path.name.removesuffix(_MATERIAL_SUFFIX): _material(path)
        for path in sorted(folder.glob(f"*{_MATERIAL_SUFFIX}"))
    }


def _material(path: Path) -> MaterialProfile:
    root = ElementTree.parse(path).getroot()
    material_id = path.name.removesuffix(_MATERIAL_SUFFIX)
    found = root.find("m:metadata/m:name", _MATERIAL)
    name = found if found is not None else ElementTree.Element("name")
    label = name.findtext("m:label", namespaces=_MATERIAL)
    settings = {
        _MATERIAL_SETTINGS[item.get("key", "")]: _number(item.text)
        for item in root.findall("m:settings/m:setting", _MATERIAL)
        if item.get("key") in _MATERIAL_SETTINGS
    }
    description = root.findtext("m:metadata/m:description", default="", namespaces=_MATERIAL)
    return MaterialProfile(
        id=material_id,
        brand=name.findtext("m:brand", default="", namespaces=_MATERIAL),
        label=label or name.findtext("m:material", namespaces=_MATERIAL) or material_id,
        description=" ".join(description.split()),
        density=_number(root.findtext("m:properties/m:density", namespaces=_MATERIAL)),
        diameter=_number(root.findtext("m:properties/m:diameter", namespaces=_MATERIAL)),
        print_temperature=settings.get("print_temperature"),
        bed_temperature=settings.get("bed_temperature"),
        speed=settings.get("speed"),
        cooling_percent=settings.get("cooling_percent"),
    )


def _number(text: str | None) -> float | None:
    return float(text) if text not in (None, "") else None

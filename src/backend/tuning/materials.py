from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ..domain.catalog import Catalog, MaterialProfile
from ..domain.errors import AppError
from ..domain.models import Value

_DIAMETER_TOLERANCE_MM = 1e-6
# слова названия материала
_WORD = re.compile(r"[a-z0-9]+")
Level = Literal["low", "medium", "high"]
Grade = Literal["good", "fair", "poor"]


class MaterialTraits(Value):
    """Общие свойства полимера без паспорта."""

    tg_c: int | float | None = None
    hdt_c: int | float | None = None
    service_max_c: int | float | None = None
    modulus_mpa: int | float | None = None
    tensile_mpa: int | float | None = None
    elongation_pct: int | float | None = None
    water_24h_pct: int | float | None = None
    hygroscopic: Level | None = None
    uv: Grade | None = None
    flexible: bool | None = None
    stiffness: Level | None = None
    friction: Level | None = None
    abrasion: Grade | None = None
    warp: Level | None = None
    abrasive_filler: bool = False
    chemical_good: list[str] = []
    chemical_poor: list[str] = []
    cost: Level | None = None
    infill_min_pct: float | None = None


class TextFlags(Value):
    uv_good: list[str]
    uv_bad: list[str]
    food_safe: list[str]


class TraitBook(Value):
    verified: bool
    note: str
    materials: dict[str, MaterialTraits]
    chemical_stems: dict[str, list[str]]
    text_flags: TextFlags


TRAITS = TraitBook.model_validate_json(
    Path(__file__).with_name("traits.json").read_text(encoding="utf-8")
)


@dataclass(frozen=True)
class Candidate:
    """Печатаемый материал из каталога."""

    id: str
    label: str
    description: str
    density: float | None
    print_temperature: float
    speed: float | None
    cooling_percent: float | None
    traits: MaterialTraits


@dataclass(frozen=True)
class Printable:
    candidates: Mapping[str, Candidate]
    # материалы без температуры
    without_temperature: Mapping[str, MaterialProfile]

    @property
    def warnings(self) -> list[str]:
        return [
            f"material {material_id} has no print temperature in the catalog, skipped"
            for material_id in self.without_temperature
        ]

    def find(self, name: str, allowed: Mapping[str, Candidate]) -> Candidate | None:
        """Материал по файлу или названию."""
        wanted = name.strip().lower()
        found = next(
            (
                material
                for material in allowed.values()
                if wanted in (material.id.lower(), material.label.lower())
            ),
            None,
        )
        unprintable = [
            material
            for material in self.without_temperature.values()
            if wanted in (material.id.lower(), material.label.lower())
        ]
        if found is None and unprintable:
            raise AppError(
                f"У материала {unprintable[0].label} в каталоге нет температуры печати, "
                "выберите другой материал",
                "material_without_temperature",
            )
        return found


def mentioned(text: str, allowed: Mapping[str, Candidate]) -> Candidate | None:
    """Материал, названный в тексте."""
    words = _WORD.findall(text.lower())
    found: list[tuple[int, int, str, Candidate]] = []
    for material in allowed.values():
        label = _WORD.findall(material.label.lower())
        at = _position(words, label)
        if label and at is not None:
            found.append((-len(label), at, material.id, material))
    return min(found, key=lambda item: item[:3])[3] if found else None


def _position(words: list[str], label: list[str]) -> int | None:
    """Позиция слов названия в тексте."""
    for start in range(len(words) - len(label) + 1):
        if words[start : start + len(label)] == label:
            return start
    return None


def printable_materials(catalog: Catalog, filament: float) -> Printable:
    candidates, without_temperature = {}, {}
    for material in catalog.materials.values():
        if material.diameter is None or abs(material.diameter - filament) > _DIAMETER_TOLERANCE_MM:
            continue
        if material.print_temperature is None:
            without_temperature[material.id] = material
            continue
        candidates[material.id] = Candidate(
            id=material.id,
            label=material.label,
            description=material.description,
            density=material.density,
            print_temperature=material.print_temperature,
            speed=material.speed,
            cooling_percent=material.cooling_percent,
            traits=TRAITS.materials.get(material.id, MaterialTraits()),
        )
    return Printable(candidates, without_temperature)

"""Materials of the catalog that fit the extruder, joined with general-knowledge traits.

The slicer hides materials of another filament diameter (2.85 mm generics on a 1.75 mm
extruder), so a lookup by name such as "PLA" must not land on them. A material file without
a print temperature cannot be printed from and is skipped with a warning.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ..domain.catalog import Catalog, MaterialProfile
from ..domain.errors import AppError
from ..domain.models import Value

_DIAMETER_TOLERANCE_MM = 1e-6
Level = Literal["low", "medium", "high"]
Grade = Literal["good", "fair", "poor"]


class MaterialTraits(Value):
    """General polymer knowledge, not verified against datasheets; absent means unknown."""

    tg_c: int | float | None = None
    service_max_c: int | float | None = None
    hygroscopic: Level | None = None
    uv: Grade | None = None
    flexible: bool | None = None
    stiffness: Level | None = None
    friction: Level | None = None
    abrasion: Grade | None = None
    warp: Level | None = None


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
    """A printable material of the catalog."""

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
    # Materials of the extruder's filament that have no print temperature in their file.
    without_temperature: Mapping[str, MaterialProfile]

    @property
    def warnings(self) -> list[str]:
        return [
            f"material {material_id} has no print temperature in the catalog, skipped"
            for material_id in self.without_temperature
        ]

    def find(self, name: str, allowed: Mapping[str, Candidate]) -> Candidate | None:
        """A material of ``allowed`` by file id or label, case-insensitively.

        Naming a material whose file has no print temperature is an error the user must see.
        """
        wanted = name.strip().lower()
        found = next(
            (m for m in allowed.values() if wanted in (m.id.lower(), m.label.lower())), None
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

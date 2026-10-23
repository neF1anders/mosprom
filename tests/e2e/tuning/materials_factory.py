"""Minimal synthetic material files in the STE Slicer .fdm_material format."""

import os

_TEMPLATE = """<?xml version='1.0' encoding='utf-8'?>
<fdmmaterial version="1.3" xmlns="http://www.ultimaker.com/material">
  <metadata>
    <name><brand>Test</brand><material>{label}</material><color></color><label>{label}</label></name>
    <description>{description}</description>
  </metadata>
  <properties><diameter>1.75</diameter><density>{density}</density></properties>
  <settings>
    <setting key="print temperature">{nozzle}</setting>
    <setting key="heated bed temperature">{bed}</setting>
    <setting key="print cooling">{cooling}</setting>
    <setting key="speed print">{speed}</setting>
  </settings>
</fdmmaterial>
"""

# id: label, density, nozzle, bed, cooling, speed, description
_MATERIALS = {
    "enduse_abs": ("Enduse ABS", 1.05, 250, 100, 0, 50, "Универсальный ABS. Не стоек к атмосферным воздействиям."),
    "enduse_pa6": (
        "Enduse PA6",
        1.05,
        260,
        100,
        0,
        40,
        "Полиамид-6, стойкость к щелочам, маслам и бензину, износостойкий.",
    ),
    "enduse_pc": ("Enduse PC", 1.2, 280, 100, 0, 40, "Поликарбонат, термостойкий."),
    "sealant_tpu": ("Sealant TPU", 1.15, 220, 60, 20, 40, "Гибкий термополиуретан, стойкость к маслам."),
}


def write_materials(directory):
    os.makedirs(str(directory))
    for material_id, (label, density, nozzle, bed, cooling, speed, description) in _MATERIALS.items():
        path = os.path.join(str(directory), material_id + ".xml.fdm_material")
        with open(path, "w", encoding="utf-8") as stream:
            stream.write(
                _TEMPLATE.format(
                    label=label,
                    density=density,
                    nozzle=nozzle,
                    bed=bed,
                    cooling=cooling,
                    speed=speed,
                    description=description,
                )
            )
    return str(directory)

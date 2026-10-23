"""Offline import from the organizer's STE Slicer sources. No network access."""

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from xml.etree import ElementTree

parser = argparse.ArgumentParser()
parser.add_argument("slicer", type=Path)
parser.add_argument("--examples", type=Path)
args = parser.parse_args()
output = Path("knowledge/sources")
output.mkdir(parents=True, exist_ok=True)
records = []
ns = {"m": "http://www.ultimaker.com/material"}
for path in sorted((args.slicer / "resources/materials").glob("*.xml.fdm_material")):
    xml = ElementTree.parse(path)
    brand = xml.findtext("m:metadata/m:name/m:brand", namespaces=ns)
    if brand != "Stereotech":
        continue
    label = xml.findtext("m:metadata/m:name/m:label", namespaces=ns) or path.stem
    density = xml.findtext("m:properties/m:density", namespaces=ns)
    if density is None:
        continue
    shutil.copyfile(path, output / path.name)
    material_id = path.name.removesuffix(".xml.fdm_material")
    description = xml.findtext("m:metadata/m:description", default="", namespaces=ns)
    records.append(
        {
            "id": material_id + ".density",
            "material_id": material_id,
            "aliases": [label, brand + " " + label],
            "property": "density",
            "value": density,
            "unit": "g/cm3",
            "conditions": "Настройка профиля STE Slicer; метод и температура измерения не указаны",
            "method": "Значение properties/density в профиле; единица подтверждена MaterialsView.qml:220",
            "text": f"{label} плотность density {density} г/см³. {description}",
            "source": f"knowledge/sources/{path.name} SHA256 {hashlib.sha256(path.read_bytes()).hexdigest()}",
            "version": "kb001-v1",
            "scope": "grade",
        }
    )
profile = args.slicer / "resources/definitions/hte530v5.2.4.def.json"
shutil.copyfile(profile, output / profile.name)
records.append(
    {
        "id": "printer.hybrid530",
        "property": "profile",
        "value": "hte530v5.2.4",
        "text": "Stereotech Hybrid 530 V5.2.4 основной тестовый профиль. Рабочие области зависят от режима печати и унаследованных настроек, не выводить их из одного файла.",
        "source": "knowledge/sources/" + profile.name,
        "scope": "printer",
    }
)
records.append(
    {
        "id": "rule.kb001",
        "property": "coverage",
        "value": "KB-001",
        "text": "Начальное покрытие ограничено семью примерами, профилями материалов STE Slicer и Hybrid 530 V5.2.4. Свойства семейства не подтверждают свойства марки. Отсутствие сведений не доказывает непригодность. Веб поиск отключён.",
        "source": "docs/STAGE1_DESIGN.md",
        "scope": "rule",
    }
)
if args.examples:
    from docx import Document

    for index, path in enumerate(sorted(args.examples.rglob("*.docx")), 1):
        document = Document(path)
        paragraphs = [p.text for p in document.paragraphs if p.text.strip()]
        paragraphs.extend(
            " | ".join(cell.text for cell in row.cells)
            for table in document.tables
            for row in table.rows
        )
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        text = "\n\n".join(paragraphs)
        relative = f"knowledge/sources/example-{index}.md"
        Path(relative).write_text(
            f"# {path.parent.name}\n\nИсточник: {path.name}\n\nSHA-256: {digest}\n\nЭто требования конкретного примера, а не свойства материала.\n\n{text}\n"
        )
        records.append(
            {
                "id": f"example.{index}",
                "property": "example_requirements",
                "value": path.parent.name,
                "text": text,
                "source": relative + " SHA256 " + digest,
                "scope": "example",
                "conditions": "Требования только к исходной детали; не переносить на другие задачи",
                "method": "Текст исходного DOCX",
                "version": "kb001-v1",
            }
        )
else:
    existing = Path("knowledge/catalog.json")
    if existing.exists():
        records.extend(
            item for item in json.loads(existing.read_text()) if item.get("scope") == "example"
        )
Path("knowledge/catalog.json").write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n")
print(f"{len(records)} verified profile/rule records")

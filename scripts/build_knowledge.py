import hashlib
import json
from pathlib import Path
from xml.etree import ElementTree

build = Path("knowledge/ste_5.2.4")
records = []
ns = {"m": "http://www.ultimaker.com/material"}
for path in sorted((build / "materials").glob("*.xml.fdm_material")):
    xml = ElementTree.parse(path)
    brand = xml.findtext("m:metadata/m:name/m:brand", namespaces=ns)
    if brand != "Stereotech":
        continue
    label = xml.findtext("m:metadata/m:name/m:label", namespaces=ns) or path.stem
    density = xml.findtext("m:properties/m:density", namespaces=ns)
    if density is None:
        continue
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
            "source": f"{path} SHA256 {hashlib.sha256(path.read_bytes()).hexdigest()}",
            "version": "kb001-v1",
            "scope": "grade",
        }
    )
profile = build / "definitions/hte530v5.2.4.def.json"
records.append(
    {
        "id": "printer.hybrid530",
        "property": "profile",
        "value": "hte530v5.2.4",
        "text": "Stereotech Hybrid 530 V5.2.4 основной тестовый профиль. Рабочие области зависят от режима печати и унаследованных настроек, не выводить их из одного файла.",
        "source": str(profile),
        "scope": "printer",
    }
)
records.append(
    {
        "id": "rule.kb001",
        "property": "coverage",
        "value": "KB-001",
        "text": "Покрытие базы ограничено профилями материалов STE Slicer и профилем Hybrid 530 V5.2.4. Свойства семейства не подтверждают свойства марки. Отсутствие сведений не доказывает непригодность. Веб поиск отключён.",
        "source": "docs/STAGE1_DESIGN.md",
        "scope": "rule",
    }
)
Path("knowledge/catalog.json").write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n")
print(f"{len(records)} verified profile/rule records")

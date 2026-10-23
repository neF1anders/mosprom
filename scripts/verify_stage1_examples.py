"""Golden facts transcribed from the seven DOCX inputs, independently of model output."""

import json
import re
import sys
from pathlib import Path

root = Path(sys.argv[1] if len(sys.argv) > 1 else "artifacts/stage1-acceptance")
# Each item is a group of expressions that must occur in the same interpreted requirement.
expected = {
    1: [
        ["25", "номиналь|nominal"],
        ["75", "пик|peak|стопор"],
        ["85.*98"],
        ["10.*70"],
        ["85.*90", "tg|стеклован"],
    ],
    2: [["18", "кг"], ["20.*2"], ["45.*5"], ["70", "ipa|изопроп"], ["0[.,]1"], ["esd|антистат"]],
    3: [["42"], ["30", "мм"], ["1000"], ["герметич"], ["mos2|молибден"], ["бенз"]],
    4: [["15", "колич|batch|шт"], ["видим", "сло"], ["поддерж"], ["15.*60"], ["желте|уф"]],
    5: [
        ["75.*85", "постоян"],
        ["9[.,]5.*10[.,]5"],
        ["4500"],
        ["50", "мпа"],
        ["1[.,]2", "плотност|density"],
        ["130", "вика|vicat"],
    ],
    6: [["2950"], ["60.*65"], ["озон"], ["1[.,]25"], ["оскол"]],
    7: [
        ["160", "кратк"],
        ["15.*35"],
        ["18", "момент|torque"],
        ["0[.,]15"],
        ["pom|полиацет"],
        ["10.*11|ph 11"],
    ],
}
results = []
for number, checks in expected.items():
    state = json.loads((root / f"{number}.json").read_text())
    card = state["job"].get("card") or {}
    requirements = card.get("requirements", [])
    texts = [
        " ".join(
            str(r.get(k) or "") for k in ["key", "label", "value", "unit", "conditions"]
        ).lower()
        for r in requirements
    ]
    matched = [
        any(all(re.search(pattern, text) for pattern in group) for text in texts)
        for group in checks
    ]
    special = True
    if number == 2:
        radial = [r for r in requirements if re.search("radial|радиаль", str(r).lower())]
        special = any("кг" in (r.get("unit") or r["value"]) for r in radial)
    if number == 6:
        special = (
            "multiple_shells" in card.get("geometry", {}).get("defects", [])
            and not card["geometry"]["physical_volume_confirmed"]
        )
    if number == 7:
        hot = [t for t in texts if "160" in t]
        special = all("кратк" in t for t in hot)
    result = {
        "example": number,
        "checks": len(checks),
        "matched": sum(matched),
        "special": special,
        "passed": all(matched) and special and state["job"]["status"] == "waiting_user",
    }
    results.append(result)
    print(json.dumps(result, ensure_ascii=False))
(root / "semantic-verification.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))
raise SystemExit(0 if all(r["passed"] for r in results) else 1)

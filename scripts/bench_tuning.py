"""Measure parameter selection offline, without stage one and the slicer.

Two sets, both kept outside the repository (``.scratch/bench`` by default):

- ``native``: 41 SeeMeCNC projects of the validation branch (``fedor/validation-ste``). The STL
  is the project's model, the card is what stage one gives for the customer text: material
  PLA, the quality wish as a code. The selection is compared with the settings the human chose
  in the same project. The human is one opinion, not the truth.
- ``seven``: the seven parts of the case. The card holds the dictionary codes written by hand
  from the task documents; the mode is compared with the organisers' folder labels, the other
  fields with the ranges of the Stereotech wiki (materials, three reference 3MF projects).

Usage:
  uv run python scripts/bench_tuning.py [--bench .scratch/bench] [--cards current|coded]
      [--out result.json]

``--cards current`` writes only the codes stage one emits today; ``coded`` adds the quality
code ``print_quality`` of the dictionary; ``stage1`` takes the seven cards stage one really
wrote in the eval run (``tests/fixtures/tuning/eval-N``, free keys, no ``part_class``) with a
fresh STL report, so the selection is measured on what the pipeline hands over.
"""

import argparse
import hashlib
import json
import statistics
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.backend.domain.models import Requirement, StlAnalysis, TaskCard
from src.backend.domain.parameters import ParameterSet
from src.backend.infrastructure.catalog import load_catalog, load_requirement_keys
from src.backend.tuning.printer import load_printer
from src.backend.tuning.select import select_parameters
from src.mesh_analysis import analyze_stl

CATALOG = load_catalog(Path("knowledge/ste_5.2.4"), "hte530v5.2.4")
KEYS = load_requirement_keys(Path("knowledge/requirement_keys.json"))
PRINTER = load_printer(CATALOG)

# Quality wish of the native texts -> what stage one writes as codes.
WISHES = {
    "обычное качество": {"print_quality": "standard"},
    "быстро, внешний вид не важен": {"priority": "speed", "print_quality": "draft"},
    "высокое качество поверхности, время не важно": {"print_quality": "fine"},
}
# Codes stage one already has in the dictionary; ``print_quality`` is new.
CURRENT_CODES = {"priority", "material", "load_bearing", "part_class", "printing_mode"}


def report_for(stl: Path, cache: Path) -> dict[str, Any]:
    cache.mkdir(parents=True, exist_ok=True)
    stored = cache / f"{stl.stem}.json"
    if stored.exists():
        return json.loads(stored.read_text())
    report = analyze_stl(stl, units="mm")
    stored.write_text(json.dumps(report))
    return report


def requirement(key: str, value: str, unit: str | None = None, hard: bool = True) -> Requirement:
    return Requirement(
        key=key,
        label=key,
        value=value,
        unit=unit,
        mandatory=hard,
        provenance="user",
        verified=True,
    )


def card(job_id: str, report: dict[str, Any], requirements: list[Requirement]) -> TaskCard:
    sha = report.get("file", {}).get("sha256") or hashlib.sha256(job_id.encode()).hexdigest()
    return TaskCard(
        job_id=job_id,
        revision=1,
        requirements=requirements,
        stl_analysis=StlAnalysis(attachment_id=f"att-{job_id}", sha256=sha, report=report),
        readiness="ready",
        allowed_actions=["select_parameters"],
    )


def effective(found: ParameterSet) -> dict[str, Any]:
    """Values the slicer prints with: chosen settings over the quality profile and the build."""
    mode = PRINTER.modes[found.printing_mode.value]
    quality = mode.qualities[found.quality.quality_type]
    chosen = {key: setting.value for key, setting in found.settings.items()}
    value = lambda key: mode.value(key, quality, chosen)  # noqa: E731
    return {
        "mode": found.printing_mode.value,
        "quality": found.quality.quality_type,
        "layer": round(float(value("layer_height")), 3),
        "walls": int(value("wall_line_count")),
        "infill": float(value("infill_sparse_density")),
        "support": bool(value("support_enable")),
        "adhesion": value("adhesion_type"),
        "speed": float(value("speed_print")),
        "material": found.materials["0"].id,
        "status": found.status,
        "pose": found.models[0].orientation_candidate,
        "sent": sorted(found.settings),
        "warnings": [w for w in found.warnings if "is not used" in w],
    }


def native_cases(bench: Path, coded: bool) -> list[dict[str, Any]]:
    cases = json.loads((bench / "eval_cases_41.json").read_text())["cases"]
    texts = {
        line["id"]: line
        for line in map(json.loads, (bench / "texts.jsonl").read_text().splitlines())
    }
    results = []
    for case in cases:
        meta = texts[case["id"]]
        human = case["reference"]
        if not human["layer_height"]:
            continue
        report = report_for(bench / "native" / f"{case['id']}.stl", bench / "reports")
        codes = WISHES[meta["priority"]]
        requirements = [requirement("material", "PLA")] if "pla" in meta["material"].lower() else []
        for key, value in codes.items():
            if coded or key in CURRENT_CODES:
                requirements.append(requirement(key, value))
        found = select_parameters(card(f"native-{case['id']}", report, requirements), CATALOG, KEYS)
        results.append(
            {
                "id": case["id"],
                "wish": meta["priority"],
                "size": meta["size"],
                "volume_cm3": round((report["geometry"].get("volume") or 0) / 1000, 1),
                "got": effective(found),
                "human": {
                    "layer": float(human["layer_height"]),
                    "infill": float(human["infill"]),
                    "support": human["support"] == "True",
                    "adhesion": human["adhesion"],
                    "walls": int(human["walls"]) if human["walls"] else None,
                },
            }
        )
    return results


# Labels of the organisers' folders (mode) and ranges of the Stereotech wiki: material
# datasheets, the "print parameter" memo and the three reference projects (see docs/tuning).
SEVEN = {
    "1_gear": {
        "stl": "1. Шестерня - 3D/Шестерня.stl",
        "part_class": "gear",
        "modes": ["classic"],
        "layer": (0.1, 0.2),
        "walls": (3, 6),
        "infill": (25, 100),
        "adhesion": ["skirt", "brim"],
        "materials": [
            "fiberpart_tpu_c5",
            "enduse_pa6",
            "fiberpart_pa12_g12",
            "sealant_tpu",
            "sealant_tpu_A95",
            "enduse_tpu_d70",
            "fiberpart_pc_g20",
            "fiberpart_abspa_g8",
        ],
    },
    "2_conveyor_wheel": {
        "stl": "2. Колесо конвейерной линии - 5D/Колесо.STL",
        "part_class": "wheel_roller",
        "modes": ["cylindrical_full", "cylindrical"],
        "layer": (0.1, 0.2),
        "walls": (3, 5),
        "infill": (25, 100),
        "adhesion": ["raft", "none"],
        "materials": [
            "sealant_tpu_A95",
            "enduse_tpu_d70",
            "fiberpart_tpu_c5",
            "enduse_pa6",
            "fiberpart_pa12_g12",
        ],
    },
    "3_cv_boot": {
        "stl": "3. Пыльник Шруса - 3D/Пыльник шруса.STL",
        "part_class": "cover_boot_seal",
        "modes": ["classic"],
        "layer": (0.1, 0.2),
        "walls": (3, 6),
        "infill": (35, 100),
        "adhesion": ["skirt", "brim"],
        "materials": ["sealant_tpu", "sealant_tpu_A95", "sealant_tpv80", "sealant_tpu93"],
    },
    "4_figurine": {
        "stl": "4. Фигурка/Декоративная фигурка.stl",
        "part_class": "decorative",
        "modes": ["classic"],
        "layer": (0.1, 0.15),
        "walls": (2, 4),
        "infill": (10, 25),
        "adhesion": ["skirt", "brim"],
        "materials": [
            "proto_pla",
            "generic_pla_175",
            "enduse_petg",
            "generic_petg_175",
            "enduse_sbs",
            "fiberpart_abs_g4",
        ],
    },
    "5_pump_impeller": {
        "stl": "5. Рабочее колесо насоса Wilo - 5D/Рабочее_колесо насоса Wilo IPL 80140-42. 2063106.STL",
        "part_class": "impeller_fan",
        # The label "5D" is the build's name of cylindrical_full; Stereotech prints its own
        # Wilo impeller in cylindrical (5D Spiral), so both count.
        "modes": ["cylindrical_full", "cylindrical"],
        "layer": (0.15, 0.2),
        "walls": (3, 5),
        "infill": (25, 100),
        "adhesion": ["none", "raft"],
        "materials": ["fiberpart_pp_g30", "fiberpart_pc_g20", "enduse_pa6", "enduse_pp"],
    },
    "6_fan_impeller": {
        "stl": "6. Крыльчатка охлаждения электродвигателя - 3D/Крыльчатка охлаждения электродвигателя.STL",
        "part_class": "impeller_fan",
        "modes": ["classic"],
        "layer": (0.15, 0.2),
        "walls": (3, 5),
        "infill": (25, 100),
        "adhesion": ["skirt", "brim"],
        "materials": [
            "fiberpart_pp_g30",
            "enduse_pa6",
            "enduse_pp",
            "fiberpart_abspa_g8",
            "fiberpart_pc_g20",
        ],
    },
    "7_cam_shaft": {
        "stl": "7. Ось вращения передающих звёзд формовщика коробов Krones - 5D/Ось вращения передающих звёзд.STL",
        "part_class": "shaft",
        "modes": ["cylindrical_full", "cylindrical"],
        "layer": (0.1, 0.2),
        "walls": (4, 6),
        "infill": (35, 100),
        "adhesion": ["raft", "none"],
        "materials": ["fiberpart_pa12_g12", "enduse_pa6", "fiberpart_pp_g30"],
    },
}
_UNITS = {
    "tg_min_c": "°C",
    "service_temp_max_c": "°C",
    "dimensional_tol_mm": "mm",
    "density_max_g_cm3": "g/cm3",
}


def seven_requirements(old: dict[str, Any], part_class: str) -> list[Requirement]:
    """The hand-written cards of ``.scratch/cases`` in today's dictionary codes."""
    found = [
        requirement("part_class", part_class),
        requirement("load_bearing", old["part"]["load"]),
    ]
    found.append(requirement("priority", ", ".join(old["preferences"]["priority"])))
    for item in old["requirements"]:
        value = item["value"]
        if isinstance(value, bool):
            text = "да" if value else "нет"
        elif isinstance(value, list):
            text = ", ".join(value)
        else:
            text = str(value)
        found.append(requirement(item["key"], text, _UNITS.get(item["key"]), item["hard"]))
    return found


EVAL_CARDS = Path("tests/fixtures/tuning")


def stage1_card(number: int, report: dict[str, Any]) -> TaskCard:
    """The card of the eval run with the STL report of today's analysis."""
    found = TaskCard.model_validate_json(
        (EVAL_CARDS / f"eval-{number}" / "card.json").read_text(encoding="utf-8")
    )
    analysis = StlAnalysis(
        attachment_id=found.stl_analysis.attachment_id if found.stl_analysis else "att",
        sha256=report["file"]["sha256"],
        report=report,
    )
    return found.model_copy(update={"stl_analysis": analysis})


def seven_cases(
    bench: Path, parts: Path, cases: Path, from_stage1: bool = False
) -> list[dict[str, Any]]:
    results = []
    for number, (name, golden) in enumerate(SEVEN.items(), start=1):
        report = report_for(parts / golden["stl"], bench / "reports")
        if from_stage1:
            task = stage1_card(number, report)
        else:
            old = json.loads((cases / f"{name}.json").read_text())
            task = card(name, report, seven_requirements(old, golden["part_class"]))
        found = select_parameters(task, CATALOG, KEYS)
        got = effective(found)
        score = {
            "mode": got["mode"] in golden["modes"],
            "mode_exact": got["mode"] == golden["modes"][0],
            "layer": golden["layer"][0] - 1e-9 <= got["layer"] <= golden["layer"][1] + 1e-9,
            "walls": golden["walls"][0] <= got["walls"] <= golden["walls"][1],
            "infill": golden["infill"][0] <= got["infill"] <= golden["infill"][1],
            "adhesion": got["adhesion"] in golden["adhesion"],
            "material": got["material"] in golden["materials"],
        }
        rev = report.get("revolution") or {}
        results.append(
            {
                "id": name,
                "got": got,
                "score": score,
                "base_diameter": getattr(
                    found.settings.get("cylindrical_mode_base_diameter"), "value", None
                ),
                "why_mode": found.printing_mode.why,
                "revolution": {
                    key: rev.get(key)
                    for key in (
                        "is_revolution",
                        "symmetry_score",
                        "round_fraction",
                        "outer_diameter_mm",
                        "length_along_axis_mm",
                        "bore",
                    )
                },
                "overhang": (report.get("overhangs") or {}).get("area_fraction"),
            }
        )
    return results


def summary(native: list[dict[str, Any]], seven: list[dict[str, Any]]) -> dict[str, Any]:
    def share(items: list[bool]) -> str:
        return f"{sum(items)}/{len(items)}"

    layer_ratio = [case["got"]["layer"] / case["human"]["layer"] for case in native]
    return {
        "native": {
            "layer_equal": share(
                [abs(c["got"]["layer"] - min(c["human"]["layer"], 0.3)) < 0.026 for c in native]
            ),
            "layer_finer_than_human": share(
                [c["got"]["layer"] < c["human"]["layer"] - 0.026 for c in native]
            ),
            "layer_ratio_median": round(statistics.median(layer_ratio), 2),
            "infill_within_5": share(
                [abs(c["got"]["infill"] - c["human"]["infill"]) <= 5 for c in native]
            ),
            "infill_abs_error_median": statistics.median(
                abs(c["got"]["infill"] - c["human"]["infill"]) for c in native
            ),
            "support_equal": share([c["got"]["support"] == c["human"]["support"] for c in native]),
            "adhesion_equal": share(
                [c["got"]["adhesion"] == c["human"]["adhesion"] for c in native]
            ),
            "walls_equal": share(
                [c["got"]["walls"] == c["human"]["walls"] for c in native if c["human"]["walls"]]
            ),
            "material_pla": share(["pla" in c["got"]["material"] for c in native]),
            "unused_requirement_warnings": sum(len(c["got"]["warnings"]) for c in native),
        },
        "seven": {key: share([c["score"][key] for c in seven]) for key in seven[0]["score"]},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bench", type=Path, default=Path(".scratch/bench"))
    parser.add_argument("--parts", type=Path, default=Path(".scratch/parts"))
    parser.add_argument("--cases", type=Path, default=Path(".scratch/cases"))
    parser.add_argument("--cards", choices=["current", "coded", "stage1"], default="coded")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--table", action="store_true")
    args = parser.parse_args()
    native = native_cases(args.bench, args.cards == "coded")
    seven = seven_cases(args.bench, args.parts, args.cases, args.cards == "stage1")
    result = {
        "cards": args.cards,
        "summary": summary(native, seven),
        "native": native,
        "seven": seven,
    }
    if args.out:
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=1))
    if args.table:
        for case in native:
            g, h = case["got"], case["human"]
            print(
                f"{case['id']} {case['wish'][:8]:8} V={case['volume_cm3']:>7} "
                f"L {g['layer']}/{h['layer']} I {g['infill']:g}/{h['infill']:g} "
                f"S {int(g['support'])}/{int(h['support'])} A {g['adhesion']}/{h['adhesion']} "
                f"W {g['walls']}/{h['walls']} v{g['speed']:g} {g['pose']} {g['material']}"
            )
        for case in seven:
            g = case["got"]
            bad = [key for key, ok in case["score"].items() if not ok]
            print(
                f"{case['id']:17} {g['mode']:16} {g['pose']} L{g['layer']} W{g['walls']} I{g['infill']:g} "
                f"S{int(g['support'])} {g['adhesion']:5} {g['material']:20} miss={bad} "
                f"ovh={case['overhang']} rev={json.dumps(case['revolution'], ensure_ascii=False)[:160]}"
            )
    print(json.dumps(result["summary"], ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

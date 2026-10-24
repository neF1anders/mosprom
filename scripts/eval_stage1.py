"""Run stage one on the organizer examples with the real model and score it against reference facts.

Usage:
  uv run --locked python scripts/eval_stage1.py "~/Downloads/Примеры деталей" [--only 1 3] [--full]

The stand-in user sends the files, declines to add details if the gate asks, and answers the
checker with the suggested option or «Не знаю». With --full the job goes on through parameter
selection, its check, slicing in the stand-in STE Slicer and the G-code check.

Needs QWEN_API_KEY and a migrated database in EVAL_DATABASE_URL (default mosprom_eval on 55432).
Results go to artifacts/eval/<time>/: one job per example and summary.json.
"""

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.backend.config import Settings
from src.backend.container import Container
from src.backend.domain.models import Job, Status
from src.backend.domain.requirement_keys import RequirementKeys
from src.backend.domain.rules import UNKNOWN_ANSWER

REFERENCE = json.loads(Path("tests/eval/reference.json").read_text())
DEFAULT_DATABASE = "postgresql+psycopg://mosprom:mosprom_local@127.0.0.1:55432/mosprom_eval"
DECLINE = "Подробностей нет, сделайте как считаете нужным"
SLICER_START_SECONDS = 30
# A code's unit is written the Latin way; the reference facts look for the Russian one too.
ALIASES = {"mpa": "мпа", "mm": "мм", "g/cm3": "г/см3", "rpm": "об/мин"}


def texts(card: dict, codes: RequirementKeys) -> list[str]:
    """What a fact is looked for in: the requirement, and the code's own name if it has one."""
    fields = ["key", "label", "value", "unit", "conditions"]
    found = []
    for requirement in card.get("requirements", []):
        entry = codes.get(requirement.get("key", ""))
        unit = str(requirement.get("unit") or "").lower()
        words = [str(requirement.get(f) or "") for f in fields]
        words += [entry.title if entry else "", ALIASES.get(unit, "")]
        found.append(" ".join(words).lower())
    return found


def score(number: str, card: dict, codes: RequirementKeys) -> dict:
    """Facts found, rules kept, and how many requirements use a code parameter selection reads."""
    reference, found = REFERENCE[number], texts(card, codes)
    requirements = card.get("requirements", [])
    coded = sum(codes.get(r.get("key", "")) is not None for r in requirements)
    matched = [
        any(all(re.search(p, t) for p in group) for t in found) for group in reference["must"]
    ]
    rules = [
        all(re.search(rule["then"], t) for t in found if re.search(rule["if"], t))
        for rule in reference.get("each", [])
    ]
    defects = set((card.get("geometry") or {}).get("defects", []))
    rules += [defect in defects for defect in reference.get("defects", [])]
    return {
        "facts": len(matched),
        "matched": sum(matched),
        "missed": [g for g, ok in zip(reference["must"], matched) if not ok],
        "rules_passed": all(rules),
        "codes": f"{coded}/{len(requirements)}",
    }


async def upload(container: Container, user: str, job_id: str, path: Path) -> None:
    async def chunks():
        yield path.read_bytes()

    await container.uploads.upload(user, job_id, str(uuid4()), path.name, chunks())


async def run_example(container: Container, folder: Path, full: bool) -> dict:
    user = "eval"
    job = await container.jobs.create(user, str(uuid4()), folder.name)
    for path in sorted(folder.iterdir()):
        if path.suffix.lower() in {".docx", ".stl", ".jpg", ".png", ".pdf"}:
            await upload(container, user, job["id"], path)
    # Files wait for an explicit send, as in the chat.
    await container.control.run(user, job["id"], str(uuid4()), "retry")
    started = time.perf_counter()
    state = await stage(container, job["id"])
    gate_asked = await asked_for_details(container, job["id"])
    if gate_asked:
        await container.messages.send(user, job["id"], str(uuid4()), DECLINE)
        state = await stage(container, job["id"])
    questions = [q for q in (state.card.questions if state.card else []) if q.answer is None]
    if state.status == Status.WAITING and questions:
        answers = {q.id: q.suggested or UNKNOWN_ANSWER for q in questions}
        await container.answers.answer(user, job["id"], str(uuid4()), state.revision, answers)
        state = await stage(container, job["id"])
    understood = time.perf_counter()
    if full and state.status == Status.QUEUED:
        await container.pipeline.run(job["id"], state.revision)
        async with container.uow() as uow:
            state = await uow.jobs.get(job["id"])
    async with container.uow() as uow:
        usage = await uow.traces.usage(job["id"])
        selected = await uow.stage_results.latest(job["id"], state.work_revision, "parameters")
    return {
        "job": state.model_dump(mode="json"),
        "gate_asked": gate_asked,
        "asked": [{"title": q.title, "answer": q.suggested or UNKNOWN_ANSWER} for q in questions],
        "parameters": selected,
        "stage1_seconds": round(understood - started, 1),
        "seconds": round(time.perf_counter() - started, 1),
        "calls": usage[0],
        "tokens": usage[1],
    }


async def asked_for_details(container: Container, job_id: str) -> bool:
    async with container.uow() as uow:
        messages = await uow.messages.list(job_id, None, 5)
    last = next((m for m in reversed(messages) if m["role"] == "assistant"), None)
    return last is not None and last.get("kind") == "gate"


def pipeline_row(result: dict) -> dict:
    """What the later stages chose and how the slicing and its check went."""
    job, chosen = result["job"], result["parameters"] or {}
    summary, sliced = job.get("parameters") or {}, job.get("result") or {}
    settings = {key: s.get("value") for key, s in chosen.get("settings", {}).items()}
    return {
        "material": summary.get("material"),
        "mode": summary.get("printing_mode"),
        "quality": summary.get("quality_type"),
        "supports": settings.get("support_enable"),
        "base_diameter": settings.get("cylindrical_mode_base_diameter"),
        "unsatisfied": summary.get("unsatisfied"),
        "check": summary.get("check"),
        "sliced": sliced.get("sliced"),
        "gcode_check": sliced.get("gcode_check"),
        "slicing": sliced.get("message"),
    }


async def stage(container: Container, job_id: str) -> Job:
    async with container.uow() as uow:
        job = await uow.jobs.get(job_id)
    await container.stage1.run(job_id, job.revision)
    async with container.uow() as uow:
        return await uow.jobs.get(job_id)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("examples", type=Path)
    parser.add_argument("--only", nargs="*", default=[])
    parser.add_argument("--full", action="store_true", help="go on to slicing in the stand-in")
    args = parser.parse_args()
    database = os.environ.get("EVAL_DATABASE_URL", DEFAULT_DATABASE)
    env = dict(os.environ, DATABASE_URL=database)
    subprocess.run(["alembic", "upgrade", "head"], env=env, check=True)
    subprocess.run([sys.executable, "scripts/import_knowledge.py"], env=env, check=True)
    folder = Path(tempfile.mkdtemp(prefix="eval-slicer-"))
    slicer = None
    if args.full:
        # The stand-in serves the same MCP tools as the plugin, so the real adapter runs.
        slicer = subprocess.Popen(
            [sys.executable, "scripts/fake_ste_slicer.py", "--folder", str(folder)]
        )
        deadline = time.monotonic() + SLICER_START_SECONDS
        while not (folder / "server.json").exists():
            if slicer.poll() is not None or time.monotonic() > deadline:
                slicer.kill()
                raise SystemExit("The slicer stand-in did not start")
            await asyncio.sleep(0.2)
    container = Container(Settings(database_url=database, slicer_folder=folder))
    output = Path("artifacts/eval") / datetime.now().strftime("%Y%m%d-%H%M%S")
    output.mkdir(parents=True)
    summary = []
    try:
        for example in sorted(args.examples.expanduser().iterdir()):
            number = example.name.split(".", 1)[0]
            if (
                not example.is_dir()
                or number not in REFERENCE
                or (args.only and number not in args.only)
            ):
                continue
            result = await run_example(container, example, args.full)
            (output / f"{number}.json").write_text(json.dumps(result, ensure_ascii=False, indent=1))
            card = result["job"].get("card") or {}
            part = next((r for r in card.get("requirements", []) if r["key"] == "part_class"), {})
            row = {
                "example": number,
                "status": result["job"]["status"],
                "error": result["job"]["error"],
                **score(number, card, container.requirement_keys),
                "part_class": part.get("value"),
                "requirements": len(card.get("requirements", [])),
                "gate_asked": result["gate_asked"],
                "questions": len(result["asked"]),
                "stage1_seconds": result["stage1_seconds"],
                "seconds": result["seconds"],
                "calls": result["calls"],
                "tokens": result["tokens"],
            }
            if args.full:
                row.update(pipeline_row(result))
            summary.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
    finally:
        await container.close()
        if slicer is not None:
            slicer.terminate()
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    print("Saved", output)


if __name__ == "__main__":
    asyncio.run(main())

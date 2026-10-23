"""Run stage one on the organizer examples with the real model and score it against reference facts.

Usage:
  uv run --locked python scripts/eval_stage1.py "~/Downloads/Примеры деталей" [--only 1 3] [--units mm]

Needs QWEN_API_KEY and a migrated database in EVAL_DATABASE_URL (default mosprom_eval on 55432).
Results go to artifacts/eval/<time>/: one card per example and summary.json.
"""

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import text

from src.backend.config import Settings
from src.backend.container import Container
from src.backend.domain.models import Job

REFERENCE = json.loads(Path("tests/eval/reference.json").read_text())
DEFAULT_DATABASE = "postgresql+psycopg://mosprom:mosprom_local@127.0.0.1:55432/mosprom_eval"


def texts(card: dict) -> list[str]:
    fields = ["key", "label", "value", "unit", "conditions"]
    return [
        " ".join(str(r.get(f) or "") for f in fields).lower() for r in card.get("requirements", [])
    ]


def score(number: str, card: dict) -> dict:
    reference, found = REFERENCE[number], texts(card)
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
    }


async def upload(container: Container, user: str, job_id: str, path: Path) -> None:
    async def chunks():
        yield path.read_bytes()

    await container.uploads.upload(user, job_id, str(uuid4()), path.name, chunks())


async def run_example(container: Container, folder: Path, units: str) -> dict:
    user = "eval"
    job = await container.jobs.create(user, str(uuid4()), folder.name)
    for path in sorted(folder.iterdir()):
        if path.suffix.lower() in {".docx", ".stl", ".jpg", ".png", ".pdf"}:
            await upload(container, user, job["id"], path)
    # Files wait for an explicit send, as in the chat.
    await container.control.run(user, job["id"], str(uuid4()), "retry")
    started = time.perf_counter()
    state = await stage(container, job["id"])
    if any(q.id == "units" and q.answer is None for q in state.card.questions):
        await container.answers.answer(
            user, job["id"], str(uuid4()), state.revision, {"units": units}
        )
        state = await stage(container, job["id"])
    async with container.engine.connect() as connection:
        usage = (
            await connection.execute(
                text(
                    "SELECT count(*), coalesce(sum((response->'usage'->>'total_tokens')::int), 0) "
                    "FROM agent_calls WHERE job_id = :job"
                ),
                {"job": job["id"]},
            )
        ).one()
    return {
        "job": state.model_dump(mode="json"),
        "seconds": round(time.perf_counter() - started, 1),
        "calls": usage[0],
        "tokens": usage[1],
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
    parser.add_argument("--units", default="mm")
    args = parser.parse_args()
    database = os.environ.get("EVAL_DATABASE_URL", DEFAULT_DATABASE)
    env = dict(os.environ, DATABASE_URL=database)
    subprocess.run(["alembic", "upgrade", "head"], env=env, check=True)
    subprocess.run([sys.executable, "scripts/import_knowledge.py"], env=env, check=True)
    container = Container(Settings(database_url=database))
    output = Path("artifacts/eval") / datetime.now().strftime("%Y%m%d-%H%M%S")
    output.mkdir(parents=True)
    summary = []
    try:
        for folder in sorted(args.examples.expanduser().iterdir()):
            number = folder.name.split(".", 1)[0]
            if (
                not folder.is_dir()
                or number not in REFERENCE
                or (args.only and number not in args.only)
            ):
                continue
            result = await run_example(container, folder, args.units)
            (output / f"{number}.json").write_text(json.dumps(result, ensure_ascii=False, indent=1))
            card = result["job"].get("card") or {}
            verdict = card.get("verdict") or {}
            row = {
                "example": number,
                "status": result["job"]["status"],
                "error": result["job"]["error"],
                **score(number, card),
                "requirements": len(card.get("requirements", [])),
                "questions": sum(q.get("answer") is None for q in card.get("questions", [])),
                "judge": verdict.get("score"),
                "seconds": result["seconds"],
                "calls": result["calls"],
                "tokens": result["tokens"],
            }
            summary.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
    finally:
        await container.close()
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    print("Saved", output)


if __name__ == "__main__":
    asyncio.run(main())

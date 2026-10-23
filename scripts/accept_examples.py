"""Opt-in live API acceptance on the seven organizer examples; never modifies inputs."""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from uuid import uuid4

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.backend.config import Settings
from src.backend.domain.tokens import sign_token


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--timeout", type=int, default=1800)
    args = parser.parse_args()
    settings = Settings()
    output = Path("artifacts/stage1-acceptance")
    output.mkdir(parents=True, exist_ok=True)
    summaries = []
    async with httpx.AsyncClient(base_url=settings.app_origin, timeout=180) as client:
        auth = await client.post(
            "/api/v1/session/exchange",
            json={"token": sign_token(settings.session_secret, "launch", int(time.time()) + 60)},
        )
        auth.raise_for_status()
        for folder in sorted(p for p in args.directory.iterdir() if p.is_dir()):
            if not list(folder.glob("*.stl")) and not list(folder.glob("*.STL")):
                continue
            response = await client.post(
                "/api/v1/jobs", json={"request_id": str(uuid4()), "title": folder.name}
            )
            response.raise_for_status()
            job = response.json()
            for file in sorted(folder.iterdir()):
                if file.suffix.lower() not in {".stl", ".docx", ".jpg", ".jpeg", ".png", ".pdf"}:
                    continue
                with file.open("rb") as stream:
                    response = await client.post(
                        f"/api/v1/jobs/{job['id']}/attachments",
                        data={"request_id": str(uuid4())},
                        files={"file": (file.name, stream)},
                    )
                response.raise_for_status()
            await client.post(
                f"/api/v1/jobs/{job['id']}/messages",
                json={
                    "request_id": str(uuid4()),
                    "text": "Разбери приложенные ТЗ и STL. Сохрани все требования с условиями и источниками. Не назначай масштаб STL без подтверждения.",
                },
            )
            started = time.monotonic()
            while time.monotonic() - started < args.timeout:
                state = (await client.get(f"/api/v1/jobs/{job['id']}")).json()
                if state["job"]["status"] in {"waiting_user", "completed", "failed"}:
                    break
                await asyncio.sleep(2)
            (output / (folder.name.split(".")[0] + ".json")).write_text(
                json.dumps(state, ensure_ascii=False, indent=2)
            )
            card = state["job"].get("card") or {}
            item = {
                "example": folder.name,
                "job_id": job["id"],
                "status": state["job"]["status"],
                "requirements": len(card.get("requirements", [])),
                "error": state["job"].get("error"),
                "seconds": round(time.monotonic() - started, 2),
            }
            summaries.append(item)
            print(json.dumps(item, ensure_ascii=False), flush=True)
        (output / "summary.json").write_text(json.dumps(summaries, ensure_ascii=False, indent=2))


asyncio.run(main())

"""Deterministic OpenAI-compatible provider for integration/E2E only."""

import asyncio
import json

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI()


@app.post("/v1/chat/completions")
async def complete(request: Request):
    payload = await request.json()
    text = payload["messages"][1]["content"]
    if isinstance(text, list):
        text = next(item["text"] for item in text if item["type"] == "text")
    context = json.loads(text)
    sources = context.get("sources", {})
    images = payload["messages"][1]["content"]
    actual_images = (
        sum(part.get("type") == "image_url" for part in images) if isinstance(images, list) else 0
    )
    if actual_images != sum(bool(source.get("image")) for source in sources.values()):
        return JSONResponse({"error": "missing page image"}, status_code=400)
    combined = "\n".join(s["text"] for s in sources.values())
    if "TEST_PROVIDER_401" in combined:
        return JSONResponse({"error": "synthetic authorization failure"}, status_code=401)
    if "TEST_PROVIDER_INVALID_JSON" in combined:
        return {"choices": [{"message": {"role": "assistant", "content": "invalid"}}]}
    if "TEST_DELAY" in combined:
        await asyncio.sleep(2)
    requirements = source_requirements(sources) + visual_requirements(sources)
    questions = []
    if "TEST_QUESTIONS" in combined:
        questions = [
            {
                "id": f"question.{i}",
                "title": f"Уточнение {i}",
                "reason": "Требуется для параметров",
                "options": ["Да", "Нет"],
                "answer": context.get("answers", {}).get(f"question.{i}"),
            }
            for i in range(1, 6)
        ]
    conflicts = []
    if "TEST_UNIT_ALIAS" in combined:
        questions.append(
            {"id": "model_units", "title": "В каких единицах задан STL?", "reason": "Нужен масштаб"}
        )
    if "TEST_CONFLICT" in combined:
        conflicts = [
            {
                "id": "test-size",
                "title": "Размер детали",
                "options": ["80 мм", "100 мм"],
                "resolution": context.get("resolutions", {}).get("test-size"),
            }
        ]
    card = {
        "purpose": combined[:150] or "Деталь",
        "requirements": requirements,
        "questions": questions,
        "conflicts": conflicts,
    }
    if "TEST_TOOL" in combined and not any(m["role"] == "tool" for m in payload["messages"]):
        call = {
            "id": "tool-1",
            "type": "function",
            "function": {
                "name": "search_knowledge",
                "arguments": json.dumps(
                    {"query": "плотность", "material_id": "proto_pla", "property": "density"}
                ),
            },
        }
        return {
            "choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [call]}}]
        }
    return {
        "choices": [
            {"message": {"role": "assistant", "content": json.dumps(card, ensure_ascii=False)}}
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 100},
    }


def source_requirements(sources):
    requirements = []
    for source_id, source in sources.items():
        for i, line in enumerate(source["text"].splitlines()):
            if not line.strip():
                continue
            requirements.append(
                {
                    "key": f"Требование {source_id} {i + 1}",
                    "value": line,
                    "conditions": "",
                    "sources": [
                        {"source_id": source_id, "quote": line, "page": source.get("page")}
                    ],
                }
            )
    return requirements


def visual_requirements(sources):
    # Controlled provider reads known synthetic fixtures, never a production fallback.
    return [
        {
            "key": f"{source_id}.{kind}",
            "value": value,
            "unit": "Nm",
            "sources": [{"source_id": source_id, "page": source["page"], "quote": quote}],
        }
        for source_id, source in sources.items()
        if source.get("image")
        for kind, value, quote in [
            ("nominal", "25", "Nominal 25 Nm"),
            ("peak", "75", "Peak 75 Nm"),
        ]
    ]

"""Deterministic OpenAI-compatible provider for browser E2E only; answers per agent header."""

import asyncio
import json
import re

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI()
SOURCE = re.compile(r'<source id="([^"]+)"[^>]*>\n?(.*?)\n?</source>', re.S)
VISUAL = [
    ("torque_nominal", "25", "Nominal torque 25 Nm"),
    ("torque_peak", "75", "Peak torque 75 Nm"),
]


@app.post("/v1/chat/completions")
async def complete(request: Request):
    payload = await request.json()
    agent = request.headers.get("X-Mosprom-Agent", "")
    content = payload["messages"][1]["content"]
    text = content if isinstance(content, str) else content[0]["text"]
    if "TEST_PROVIDER_401" in text:
        return JSONResponse({"error": "synthetic authorization failure"}, status_code=401)
    if "TEST_DELAY" in text:
        await asyncio.sleep(2)
    if "TEST_PROVIDER_INVALID_JSON" in text:
        return message("invalid")
    called = any(m["role"] == "tool" for m in payload["messages"])
    if agent == "interpreter" and "TEST_TOOL" in text and not called:
        arguments = {"value": "1", "from_unit": "inch", "to_unit": "mm"}
        tool = {
            "id": "t1",
            "type": "function",
            "function": {"name": "convert_units", "arguments": json.dumps(arguments)},
        }
        return {
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {"role": "assistant", "content": None, "tool_calls": [tool]},
                }
            ]
        }
    answer = ANSWERS.get(agent, lambda text, content: {})(text, content)
    return message(json.dumps(answer, ensure_ascii=False))


def message(content: str) -> dict:
    return {
        "choices": [
            {"finish_reason": "stop", "message": {"role": "assistant", "content": content}}
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 100, "total_tokens": 200},
    }


def sources(text: str) -> dict[str, str]:
    data = text.split("<draft>")[0]
    return {key: body for key, body in SOURCE.findall(data)}


def interpret(text: str, content) -> dict:
    found = sources(text)
    images = (
        [
            p["text"].split()[2].rstrip(",")
            for p in content[1:]
            if p["type"] == "text" and p["text"].startswith("Изображение источника")
        ]
        if isinstance(content, list)
        else []
    )
    requirements = [
        {
            "key": f"line_{source}_{index}",
            "label": line[:40],
            "value": line,
            "sources": [{"source_id": source, "quote": line}],
        }
        for source, body in found.items()
        if not source.startswith("a:")
        for index, line in enumerate(body.splitlines())
        if re.search(r"\d", line) and "TEST_" not in line
    ]
    requirements += [
        {
            "key": key,
            "label": key,
            "value": value,
            "unit": "Nm",
            "sources": [{"source_id": source, "quote": quote}],
        }
        for source in images
        if not found.get(source, "").strip()
        for key, value, quote in VISUAL
    ]
    if "TEST_CONFLICT" in text:
        requirements += [
            {
                "key": "length",
                "label": "Длина детали",
                "value": value,
                "unit": "мм",
                "sources": [{"source_id": source, "quote": f"Длина {value} мм"}],
            }
            for source, value in [
                (s, v) for s, body in found.items() for v in re.findall(r"Длина (\d+) мм", body)
            ]
        ]
    questions = []
    if "TEST_QUESTIONS" in text:
        questions = [
            {
                "title": f"Уточнение {i}",
                "impact": "Влияет на подбор параметров",
                "options": ["Да", "Нет"],
            }
            for i in (1, 2)
        ]
    purpose = next(
        (body.strip()[:150] for source, body in found.items() if source.startswith("m")), "Деталь"
    )
    return {"purpose": purpose, "requirements": requirements, "questions": questions}


def second_reading(text: str, content) -> dict:
    items = json.loads(text.split("<items>")[1].split("</items>")[0])
    values = {key: value for key, value, _ in VISUAL}
    return {
        "readings": [
            {
                "key": i["key"],
                "value": values.get(i["key"], ""),
                "unit": "Nm",
                "legible": i["key"] in values,
            }
            for i in items
        ]
    }


def discrepancies(text: str, content) -> dict:
    if "TEST_STL_MISMATCH" not in text:
        return {"discrepancies": []}
    return {
        "discrepancies": [
            {
                "kind": "tz_vs_stl",
                "requirement_key": "length",
                "title": "Длина в ТЗ 100 мм, в модели 30 мм",
                "impact": "Влияет на масштаб и подбор параметров",
                "options": ["Верно ТЗ", "Верна модель STL"],
            }
        ]
    }


def judge(text: str, content) -> dict:
    if "TEST_JUDGE_LOW" in text:
        return {
            "score": 0.3,
            "remarks": [{"severity": "major", "text": "Потеряно условие пикового момента"}],
        }
    return {"score": 0.9, "remarks": []}


def triage(text: str, content) -> dict:
    """Every field is found in the first source line, so no early questions get in the way."""
    if "TEST_TRIAGE" in text:
        return {"fields": [], "questions": []}
    fields = json.loads(text.split("<fields>")[1].split("</fields>")[0])
    line = next(
        (
            (source, row.strip())
            for source, body in sources(text).items()
            for row in body.splitlines()
            if row.strip()
        ),
        None,
    )
    if line is None:
        return {"fields": [], "questions": []}
    return {
        "fields": [
            {"field": f["field"], "value": line[1], "source_id": line[0], "quote": line[1]}
            for f in fields
        ],
        "questions": [],
    }


def reading(text: str, content) -> dict:
    return {"requirements": [], "questions": [], "unknowns": []}


ANSWERS = {
    "triage": triage,
    "interpreter": interpret,
    # An empty patch keeps the interpreter's draft and its questions.
    "consolidator": lambda text, content: {},
    "analyst_loads": reading,
    "analyst_environment": reading,
    "analyst_geometry": reading,
    "analyst_production": reading,
    "second_reading": second_reading,
    "discrepancies": discrepancies,
    "judge": judge,
}

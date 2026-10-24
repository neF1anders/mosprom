"""Deterministic OpenAI-compatible provider for browser E2E only; answers per agent header.

Markers anywhere in the chat or in a document steer it. TEST_PROVIDER_401 and
TEST_PROVIDER_INVALID_JSON break the provider, TEST_DELAY slows every call down. In the
latest message TEST_OFFTOPIC and TEST_GATE_ASK keep the assistant talking instead of starting
the work, TEST_STEER_APPLY makes it update the project. TEST_TOOL makes the interpreter call a tool first. TEST_QUESTIONS, TEST_CONFLICT and
TEST_STL_MISMATCH make the checker ask in its first turn.
"""

import asyncio
import json
import re
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.backend.agents.assistant import template

app = FastAPI()
SOURCE = re.compile(r'<source id="([^"]+)"[^>]*>\n?(.*?)\n?</source>', re.S)
KEYS = re.compile(r"<requirement_keys>\n(.*?)\n</requirement_keys>", re.S)
VISUAL = [
    ("torque_nominal", "25", "Nominal torque 25 Nm"),
    ("torque_peak", "75", "Peak torque 75 Nm"),
]
# A line naming one of these becomes a requirement code instead of a free requirement.
CODES = [
    ("service_temp_max_c", "°C", re.compile(r"[Тт]емпература\s+(.*\d)\s*°?\s*[CС]?\s*$")),
    ("quantity", None, re.compile(r"[Кк]оличество\s+(\d+)")),
    ("dimensional_tol_mm", "mm", re.compile(r"[Дд]опуск\D*?(\d+(?:[.,]\d+)?)\s*мм")),
]
OFF_TOPIC = "Я помогаю только с подготовкой задания на печать"
STEER_SUMMARY = "Учитываю правку и пересчитываю то, что от неё зависит"
STEER_REPLY = "Задание от этого не меняется, продолжаю работу"
NO_MODEL = "Приложите модель STL, и я подберу параметры печати"

ANALYSIS = "Так решила программа подбора по требованиям карточки"
GATE_ASK = "Расскажите подробнее о детали, для чего она нужна, какие у неё нагрузки и температура"
UNKNOWN = "Не знаю"
REASONING = "Читаю источники и ищу числа.\n\nСверяю каждое значение с цитатой."


@app.post("/v1/chat/completions")
async def complete(request: Request):
    payload = await request.json()
    agent = request.headers.get("X-Mosprom-Agent", "")
    messages = payload["messages"]
    everything = "\n".join(text(m) for m in messages if m["role"] != "system")
    if "TEST_PROVIDER_401" in everything:
        return JSONResponse({"error": "synthetic authorization failure"}, status_code=401)
    if "TEST_DELAY" in everything:
        await asyncio.sleep(2)
    if agent == "assistant":
        return assistant(payload)
    if agent == "report":
        # The report the code would write without a model, from the same facts.
        facts = json.loads(text(messages[-1]).split("<facts>", 1)[1].split("</facts>", 1)[0])
        return message(template(facts))
    if agent == "analyst":
        return message(ANALYSIS)
    # The assistant replies in plain text, so a broken answer reaches the first JSON agent.
    if "TEST_PROVIDER_INVALID_JSON" in everything:
        return message("invalid")
    # An agent that thinks answers with its reasoning, which the chat shows as it works.
    reasoning = REASONING if payload.get("enable_thinking") else ""
    called = any(m["role"] == "tool" for m in messages)
    if agent == "interpreter" and "TEST_TOOL" in everything and not called:
        arguments = {"value": "1", "from_unit": "inch", "to_unit": "mm"}
        return tool_call("convert_units", arguments, reasoning)
    answer = ANSWERS.get(agent, lambda messages: {})(messages)
    return message(json.dumps(answer, ensure_ascii=False), reasoning)


def text(item: dict[str, Any]) -> str:
    content = item.get("content") or ""
    if isinstance(content, str):
        return content
    return "\n".join(p.get("text", "") for p in content if p.get("type") == "text")


def message(content: str, reasoning: str = "") -> dict:
    return reply({"role": "assistant", "content": content}, "stop", reasoning)


def tool_call(name: str, arguments: dict[str, Any], reasoning: str = "") -> dict:
    call = {
        "id": "t1",
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }
    body = {"role": "assistant", "content": None, "tool_calls": [call]}
    return reply(body, "tool_calls", reasoning)


def reply(body: dict[str, Any], finish: str, reasoning: str = "") -> dict:
    """A provider that ignores stream answers with one body, its reasoning included."""
    return {
        "choices": [{"finish_reason": finish, "message": {**body, "reasoning_content": reasoning}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 100, "total_tokens": 200},
    }


def assistant(payload: dict[str, Any]) -> dict:
    """New files with a model start a project and a marked message updates it; small talk is
    answered, and so is the turn after a refused call."""
    messages = payload["messages"]
    users = [m for m in messages if m["role"] == "user"]
    latest = text(users[-1]) if users else ""
    if messages[-1]["role"] == "tool" or not payload.get("tools"):
        return message(NO_MODEL)
    if "TEST_STEER_APPLY" in latest:
        return tool_call("update_project", {"summary": STEER_SUMMARY})
    if "TEST_GATE_ASK" in latest:
        return message(GATE_ASK)
    if "TEST_OFFTOPIC" in latest:
        return message(OFF_TOPIC)
    if '"работа": "идёт' in latest:
        return message(STEER_REPLY)
    if "(модель STL)" in latest:
        return tool_call("start_project", {"title": "Деталь", "notes": ""})
    # With a project, whatever else the user writes about it changes it.
    if '"текущий проект": {' in latest:
        return tool_call("update_project", {"summary": STEER_SUMMARY})
    return message(NO_MODEL)


def interpret(messages: list[dict[str, Any]]) -> dict:
    """Every line with a number is a requirement; a line naming a code fills that code."""
    content = next(m["content"] for m in messages if m["role"] == "user")
    data = text({"content": content})
    found = dict(SOURCE.findall(data))
    codes: dict[str, Any] = {key: None for key in dictionary(data)}
    coded: set[str] = set()
    # Documents first, so that a later chat message overrides the value they give.
    for source, body in sorted(found.items(), key=lambda item: item[0].startswith("m")):
        for line in body.splitlines():
            for code, unit, pattern in CODES:
                match = pattern.search(line)
                if match and code in codes:
                    codes[code] = {
                        "value": match.group(1),
                        "unit": unit,
                        "source_id": source,
                        "quote": line,
                        "conditions": "",
                        "mandatory": True,
                        "inferred": False,
                    }
                    coded.add(line)
    requirements = [
        {
            "key": f"line_{source}_{index}",
            "label": line[:40],
            "value": line,
            "sources": [{"source_id": source, "quote": line}],
        }
        for source, body in found.items()
        for index, line in enumerate(body.splitlines())
        if re.search(r"\d", line) and "TEST_" not in line and line not in coded
    ]
    images = [
        p["text"].split()[2].rstrip(",")
        for p in (content[1:] if isinstance(content, list) else [])
        if p["type"] == "text" and p["text"].startswith("Изображение источника")
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
    # Small talk the gate answered does not describe the part.
    purpose = next(
        (
            body.strip()[:150]
            for source, body in found.items()
            if source.startswith("m") and "TEST_OFFTOPIC" not in body
        ),
        "Деталь",
    )
    return {"purpose": purpose, "requirements": requirements, "codes": codes}


def dictionary(data: str) -> list[str]:
    block = KEYS.search(data)
    return [json.loads(line)["key"] for line in block.group(1).splitlines()] if block else []


def check(messages: list[dict[str, Any]]) -> dict:
    """The first turn asks what the markers call for; the answer turn asks nothing again."""
    turns = [m for m in messages if m["role"] != "system"]
    if len(turns) > 1:
        return answered(text(turns[-1]))
    data = text(turns[0])
    questions = []
    if "TEST_QUESTIONS" in data:
        questions += [
            {
                "title": f"Уточнение {i}",
                "impact": "Влияет на подбор параметров",
                "options": ["Да", "Нет"],
                "kind": "clarify",
            }
            for i in (1, 2)
        ]
    if "TEST_CONFLICT" in data:
        lengths = dict.fromkeys(re.findall(r"Длина (\d+) мм", data))
        questions.append(
            {
                "title": "Источники расходятся, Длина детали",
                "impact": "Влияет на масштаб и подбор параметров",
                "options": [f"{value} мм" for value in lengths],
                "kind": "sources",
                "requirement_key": "length",
            }
        )
    if "TEST_STL_MISMATCH" in data:
        questions.append(
            {
                "title": "Длина в ТЗ 100 мм, в модели 30 мм",
                "impact": "Влияет на масштаб и подбор параметров",
                "options": ["Верно ТЗ", "Верна модель STL"],
                "kind": "tz_vs_stl",
                "requirement_key": "length",
            }
        )
    return {"questions": questions} if questions else {}


def answered(turn: str) -> dict:
    """An answer the user does not know becomes an assumption, as the prompt asks."""
    answers = turn.split("<answers>")[-1].split("</answers>")[0]
    unknown = [
        body.removesuffix(UNKNOWN).strip()
        for source, body in SOURCE.findall(answers)
        if source.startswith("a:") and body.endswith(UNKNOWN)
    ]
    return {
        "assumptions": [
            {"text": f"{title}, принято без ответа", "basis": "Пользователь не знает ответа"}
            for title in unknown
        ],
        "questions": [],
    }


ANSWERS = {"interpreter": interpret, "checker": check}

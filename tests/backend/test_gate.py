"""The gate's prompt, dialog and text rules, without a model."""

import pytest

from src.backend.agents.context import collect
from src.backend.agents.gate import NO_TEXT, clean, gate_messages, split_tool, started
from src.backend.agents.runner import prompt
from src.backend.domain.models import Attachment

from .fakes import call

pytestmark = pytest.mark.unit
WHEN = "2026-10-24T10:00:00+00:00"


def test_the_tool_block_of_the_prompt_becomes_the_tool_description():
    system, tool = split_tool(prompt("gate"))
    assert "<tool_start_pipeline>" not in system and "Ты ассистент" in system
    assert tool["function"]["name"] == "start_pipeline"
    assert tool["function"]["description"].startswith("Запускает разбор задания")


def test_a_send_of_files_alone_still_ends_with_the_users_turn():
    document = Attachment(
        job_id="j",
        filename="ТЗ.docx",
        kind="docx",
        sha256="0" * 64,
        size=1,
        status="completed",
        fragments=[{"page": 1, "text": "Шестерня привода " * 1000}],
    )
    messages = [
        {"id": "u1", "role": "user", "kind": "chat", "text": "Привет", "created_at": WHEN},
        {
            "id": "a1",
            "role": "assistant",
            "kind": "chat",
            "text": "Здравствуйте",
            "created_at": WHEN,
        },
    ]
    dialog = gate_messages("система", messages, collect(messages, [document], {}, None), "a.stl")
    assert [m["role"] for m in dialog] == ["system", "user", "assistant", "user"]
    last = dialog[-1]["content"]
    assert '"stl": "a.stl"' in last and '"документы": "приложены"' in last
    assert last.endswith(f"<messages>\n{NO_TEXT}\n</messages>")
    assert len(last) < 7000


def test_only_the_start_tool_starts():
    assert started([call("start_pipeline", {})])
    assert not started([call("view_page", {})]) and not started([])


@pytest.mark.parametrize(
    "text,expected",
    [
        ("## Готово.", "Готово"),
        ("Приложите STL — и начнём", "Приложите STL, и начнём"),
        ("Уточните:\n- нагрузку", "Уточните\n- нагрузку"),
        ("Например: вода", "Например, вода"),
        ("В 10:30 всё готово", "В 10:30 всё готово"),
        ("Деталь 齿轮 готова", "Деталь  готова"),
    ],
)
def test_the_reply_follows_the_chat_text_rules(text, expected):
    assert clean(text) == expected

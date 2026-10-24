"""Helpers of the agents in the chat: tools from the prompt and the chat text rules."""

import pytest

from src.backend.agents.chat import called, chat_text, clean, split_tool
from src.backend.agents.runner import prompt

from .fakes import call

pytestmark = pytest.mark.unit


def test_the_tool_blocks_of_the_prompt_become_tool_descriptions():
    system, tool = split_tool(prompt("assistant"), "start_project", {"type": "object"})
    assert "<tool_start_project>" not in system and "<tool_update_project>" in system
    assert tool["function"]["name"] == "start_project"
    assert tool["function"]["description"].startswith("Начинает новый проект")
    assert tool["function"]["parameters"] == {"type": "object"}


def test_only_the_named_tool_counts_as_called():
    assert called([call("start_project", {"title": "Колесо"})], "start_project") == {
        "title": "Колесо"
    }
    assert called([call("project_log", {})], "start_project") is None


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
def test_plain_text_follows_the_chat_text_rules(text, expected):
    assert clean(text) == expected


def test_markdown_keeps_its_marks_but_not_dashes_and_colons():
    text = "### Итог\n- **PETG** — держит 70 градусов\nМатериал: PETG."
    assert chat_text(text) == "### Итог\n- **PETG**, держит 70 градусов\nМатериал, PETG"

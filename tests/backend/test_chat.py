import pytest

from src.backend.agents.chat import called, chat_text, split_tool
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
        ("Приложите STL — и начнём", "Приложите STL, и начнём"),
        ("Уточните:\n- нагрузку", "Уточните\n- нагрузку"),
        ("Например: вода", "Например, вода"),
        ("В 10:30 всё готово", "В 10:30 всё готово"),
        ("Принтер Hybrid 530: печать", "Принтер Hybrid 530, печать"),
        ("Вот анекдот:\n— Почему колесо?\n— Потому что", "Вот анекдот\nПочему колесо?\nПотому что"),
        ("Анекдот: — Почему?", "Анекдот, Почему?"),
        ("Перекись 3–6% и спирт", "Перекись 3-6% и спирт"),
        ("Деталь 齿轮 готова", "Деталь  готова"),
    ],
)
def test_the_chat_text_follows_its_rules(text, expected):
    assert chat_text(text) == expected


def test_markdown_keeps_its_marks_but_not_dashes_and_colons():
    text = "### Итог\n- **PETG** — держит 70 градусов\nМатериал: PETG."
    assert chat_text(text) == "### Итог\n- **PETG**, держит 70 градусов\nМатериал, PETG"

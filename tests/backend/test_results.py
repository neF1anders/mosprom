import io

import pytest
from PIL import Image

from src.backend.domain.results import RESULTS, folder_name
from src.backend.infrastructure.results import LocalResultFolders
from src.backend.services.transcript import BUBBLE, PAD, PAGE, WIDTH, _font, entries, render, wrap

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("part", "name"),
    [
        ("Шестерня", "Шестерня"),
        ("Ось вращения: звёзды/Krones?", "Ось вращения звёзды Krones"),
        ("  Колесо  конвейера.  ", "Колесо конвейера"),
        ("CON", "Деталь"),
        ("lpt1.stl", "Деталь"),
        ("...", "Деталь"),
        ("Я" * 80, "Я" * 60),
    ],
)
def test_a_part_name_becomes_a_folder_name_any_system_takes(part, name):
    assert folder_name(part) == name


async def test_a_name_taken_by_an_earlier_project_gets_a_number(tmp_path):
    folders = LocalResultFolders(tmp_path, "")
    first = await folders.reserve("Шестерня")
    await folders.write(first, "result.gcode", b"G1")
    second = await folders.reserve("Шестерня")
    third = await folders.reserve("Шестерня")
    assert [first.path.name, second.path.name, third.path.name] == [
        "Шестерня",
        "Шестерня (2)",
        "Шестерня (3)",
    ]
    assert first.shown == str(tmp_path / RESULTS / "Шестерня")
    # прежние файлы остаются
    assert (first.path / "result.gcode").read_bytes() == b"G1"


async def test_the_folder_is_shown_as_the_slicers_machine_sees_it(tmp_path):
    folders = LocalResultFolders(tmp_path, r"C:\Users\u\Documents\STE_AIAssistant")
    folder = await folders.reserve("Крыльчатка")
    assert folder.shown == r"C:\Users\u\Documents\STE_AIAssistant\Результаты\Крыльчатка"
    assert folder.path == tmp_path / RESULTS / "Крыльчатка"


async def test_only_an_unused_folder_is_discarded(tmp_path):
    folders = LocalResultFolders(tmp_path, "")
    empty, used = await folders.reserve("A"), await folders.reserve("B")
    await folders.write(used, "report.md", b"text")
    await folders.discard(empty)
    await folders.discard(used)
    assert not empty.path.exists() and (used.path / "report.md").exists()


def test_the_chat_shows_who_said_what_and_the_files_sent():
    messages = [
        {"role": "user", "kind": "chat", "text": "Нужна шестерня", "attachment_ids": ["a"]},
        {"role": "assistant", "kind": "gate", "text": "Какая **нагрузка**?"},
        {"role": "user", "kind": "answers", "text": "Нагрузка, средняя"},
        {"role": "assistant", "kind": "report", "text": "### Результат\n- Печать 5 мин"},
        {"role": "assistant", "kind": "chat", "text": "  "},
    ]
    shown = entries(messages, {"a": "Шестерня.stl"})
    assert [(e.role, e.label) for e in shown] == [
        ("user", "Вы"),
        ("assistant", "Ассистент"),
        ("user", "Ответы на вопросы"),
        ("assistant", "Итоговый отчёт"),
    ]
    assert shown[0].lines[-1] == ("Файлы Шестерня.stl", False)
    assert shown[1].lines == [("Какая нагрузка?", False)]
    assert shown[3].lines == [("Результат", True), ("• Печать 5 мин", False)]


def test_a_long_chat_goes_on_to_the_next_picture():
    text = "\n".join(f"Строка {n} длинного ответа ассистента" for n in range(200))
    messages = [{"role": "assistant", "kind": "chat", "text": text}] * 3
    pages = render("Шестерня", entries(messages, {}), "25.10.2026 05:00")
    assert len(pages) > 1
    for page in pages:
        with Image.open(io.BytesIO(page)) as picture:
            assert picture.format == "PNG" and picture.width == WIDTH
            assert picture.height <= PAGE


def test_a_word_longer_than_a_line_breaks_inside():
    path = "C:\\Users\\u\\Documents\\STE_AIAssistant\\Результаты\\" + "Ось" * 40
    font = _font(False, 22)
    lines = wrap(f"Проект лежит в папке {path}", font, BUBBLE - 2 * PAD)
    assert len(lines) > 1 and "".join(lines).replace(" ", "") in f"Проектлежитвпапке{path}"
    assert all(font.getlength(line) <= BUBBLE - 2 * PAD for line in lines)


def test_a_long_report_fills_the_picture_before_going_on():
    """Длинный отчёт заполняет картинку."""
    report = "\n".join(f"Строка {n} итогового отчёта" for n in range(120))
    messages = [
        {"role": "user", "kind": "chat", "text": "Деталь 6"},
        {"role": "assistant", "kind": "report", "text": report},
    ]
    pages = render("Крыльчатка", entries(messages, {}), "25.10.2026 05:00")
    heights = [Image.open(io.BytesIO(page)).height for page in pages]
    assert len(pages) == 2 and heights[0] > PAGE - 200, heights

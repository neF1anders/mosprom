from datetime import timedelta

import pytest

from src.backend.agents.assistant import (
    ASK,
    FALLBACK,
    INVESTIGATE,
    LOG,
    REPLY,
    START,
    UPDATE,
    Assistant,
    Situation,
    assistant_messages,
    template,
)
from src.backend.agents.journal import _quality
from src.backend.agents.runner import AgentRunner
from src.backend.agents.tools import ToolBox
from src.backend.domain.models import (
    Attachment,
    Job,
    ParametersSummary,
    Project,
    Question,
    QueuedMessage,
    Status,
    TaskCard,
    now,
)
from src.backend.services.steering import CLAIM_TIMEOUT, busy, claimable

from .fakes import FakeUow, ScriptedModel, call, reply

pytestmark = pytest.mark.unit
WHEN = "2026-10-25T10:00:00+00:00"


class Store:
    async def event(self, *args, **kwargs):
        return None


class Journal:
    def __init__(self):
        self.read = 0

    async def facts(self, job):
        self.read += 1
        return {"purpose": "Колесо конвейера", "parameters": {"materials": [{"id": "PETG"}]}}

    async def reasoning(self, job):
        return "<checker step=1>\nPETG holds 70 degrees\n"


class Sources:
    async def parse(self, attachments, ctx):
        return None


def assistant(**script) -> tuple[Assistant, ScriptedModel]:
    model = ScriptedModel(script)
    agent = Assistant(AgentRunner(model, ToolBox(None), FakeUow()), FakeUow(), None)
    agent.store, agent.journal, agent.sources = Store(), Journal(), Sources()  # type: ignore[assignment]
    return agent, model


def file(name: str, kind: str, **fields) -> Attachment:
    return Attachment(job_id="j", filename=name, kind=kind, sha256="0" * 64, size=1, **fields)


def situation(job: Job | None = None, files=(), new=(), text="Привет") -> Situation:
    job = job or Job(user_id="u")
    messages = [{"id": "m1", "seq": 1, "role": "user", "kind": "chat", "text": text}]
    return Situation(job, messages, list(files), list(files), list(new))


async def said(text, turn):
    said.texts.append(text)


said.texts = []


async def test_the_assistant_reasons_and_may_reply_by_its_tool():
    """Рассуждает и отвечает инструментом."""
    answer = reply("", tool_calls=[call(REPLY, {"text": "Привет — чем помочь?"})])
    agent, model = assistant(assistant=[answer])
    decision = await agent.decide(situation(), said)
    assert decision.action == "reply" and decision.text == "Привет, чем помочь?"
    request = model.requests["assistant"][0]
    names = {t["function"]["name"] for t in request["tools"]}
    assert names == {REPLY, ASK, START, UPDATE, LOG, INVESTIGATE}
    assert (request["thinking"], request["budget"]) == (True, 2000)


async def test_a_reply_in_plain_text_is_taken_as_well():
    agent, _ = assistant(assistant=[reply("Привет — чем помочь?")])
    decision = await agent.decide(situation(), said)
    assert decision.action == "reply" and decision.text == "Привет, чем помочь?"


async def test_a_new_project_starts_with_its_title_and_notes():
    start = call(START, {"title": "Колесо", "notes": "Работает на улице"})
    agent, _ = assistant(assistant=[reply("Начинаю", tool_calls=[start])])
    decision = await agent.decide(situation(files=[file("Колесо.STL", "stl")]), said)
    assert (decision.action, decision.title, decision.notes) == (
        "start",
        "Колесо",
        "Работает на улице",
    )


async def test_a_start_without_a_model_comes_back_to_the_agent_as_a_refusal():
    agent, model = assistant(
        assistant=[
            reply("", tool_calls=[call(START, {"title": "Колесо"})]),
            reply("Приложите модель STL"),
        ]
    )
    decision = await agent.decide(situation(files=[file("ТЗ.docx", "docx")]), said)
    assert decision.action == "reply" and decision.text == "Приложите модель STL"
    answer = model.requests["assistant"][1]["messages"][-1]
    assert answer["role"] == "tool" and "нет модели STL" in answer["content"]


async def test_no_new_project_while_the_work_runs():
    job = Job(user_id="u", status=Status.RUNNING, projects=[Project(number=1, title="Вал")])
    agent, model = assistant(
        assistant=[
            reply("", tool_calls=[call(START, {"title": "Колесо"})]),
            reply("Сначала закончу вал"),
        ]
    )
    decision = await agent.decide(situation(job, files=[file("Колесо.STL", "stl")]), said)
    assert decision.action == "reply"
    assert "идёт работа" in model.requests["assistant"][1]["messages"][-1]["content"]


async def test_an_update_needs_a_project():
    agent, _ = assistant(
        assistant=[reply("", tool_calls=[call(UPDATE, {"summary": "x"})]), reply("Сначала модель")]
    )
    assert (await agent.decide(situation(), said)).action == "reply"
    job = Job(user_id="u", revision=1, projects=[Project(number=1, title="Вал")])
    summary = "Температуру поменял на 80 градусов: пересчитываю материал."
    agent, _ = assistant(assistant=[reply("", tool_calls=[call(UPDATE, {"summary": summary})])])
    decision = await agent.decide(situation(job), said)
    assert decision.action == "update" and decision.text == ""
    assert decision.summary == "Температуру поменял на 80 градусов, пересчитываю материал"


async def test_an_investigation_says_so_first_and_answers_from_the_analyst():
    said.texts = []
    agent, model = assistant(
        assistant=[
            reply(
                "",
                tool_calls=[
                    call(
                        INVESTIGATE,
                        {"question": "Почему PETG", "say": "Сейчас посмотрю, как я это решал"},
                    )
                ],
            ),
            reply("Потому что PETG держит 70 градусов"),
        ],
        analyst=[reply("Я выбрал PETG, он держит 70 градусов")],
    )
    decision = await agent.decide(situation(text="Почему PETG?"), said)
    assert said.texts == ["Сейчас посмотрю, как я это решал"]
    assert decision.text == "Потому что PETG держит 70 градусов"
    analyst = model.requests["analyst"][0]
    assert (
        analyst["thinking"] is True and "PETG holds 70 degrees" in analyst["messages"][1]["content"]
    )
    assert "Я выбрал PETG" in model.requests["assistant"][1]["messages"][-1]["content"]


async def test_the_journal_is_read_by_its_tool():
    agent, model = assistant(
        assistant=[reply("", tool_calls=[call(LOG, {})]), reply("Материал PETG")]
    )
    decision = await agent.decide(situation(text="Какой материал?"), said)
    assert decision.text == "Материал PETG" and agent.journal.read == 1
    assert "Колесо конвейера" in model.requests["assistant"][1]["messages"][-1]["content"]


async def test_the_last_step_offers_only_the_reply_and_an_empty_answer_falls_back():
    looping = reply("", tool_calls=[call(LOG, {})])
    agent, model = assistant(assistant=[looping, looping, looping, reply("")])
    decision = await agent.decide(situation(), said)
    assert decision.text == FALLBACK
    assert [t["function"]["name"] for t in model.requests["assistant"][-1]["tools"]] == [REPLY]


def test_the_state_tells_the_work_the_open_questions_and_the_new_files():
    job = Job(user_id="u", status=Status.WAITING, projects=[Project(number=1, title="Вал")])
    job.card = TaskCard(
        job_id=job.id,
        revision=1,
        purpose="Вал редуктора",
        questions=[Question(id="q", kind="clarify", title="Какая температура")],
    )
    document = file("ТЗ колеса.docx", "docx", fragments=[{"page": 1, "text": "Колесо " * 2000}])
    messages = assistant_messages("система", situation(job, files=[document], text="Вот ещё"))
    last = messages[-1]["content"]
    assert '"работа": "не идёт"' in last and '"вопросы без ответа": ["Какая температура"]' in last
    assert '"ТЗ колеса.docx (документ)"' in last and last.endswith("Вот ещё")
    assert len(last) < 7500


def test_messages_typed_during_the_work_close_the_dialog():
    job = Job(user_id="u", status=Status.RUNNING, stage="slicing")
    messages = assistant_messages("система", situation(job, new=["Какая погода"]))
    assert [m["role"] for m in messages] == ["system", "user"]
    assert '"работа": "идёт, этап нарезка"' in messages[-1]["content"]
    assert messages[-1]["content"].endswith("Привет\n\nКакая погода")


def test_the_template_reports_the_facts_without_the_model():
    text = template(
        {
            "outcome": "ready",
            "requirements": ["Момент 25 Нм (из документа)"],
            "waived_questions": [{"question": "Нужна ли балансировка", "reason": "Колесо лёгкое"}],
            "parameters": {"mode": "3D", "quality": "Fine", "materials": [{"id": "PETG"}]},
            "slicing": {
                "message": "G-code сохранён",
                "print_time_seconds": 3900,
                "folder": "C:\\p",
            },
        }
    )
    assert text.startswith("Проект готов")
    assert "### Вопросы, которые я не стал задавать\n- Нужна ли балансировка Колесо лёгкое" in text
    assert "Режим 3D, профиль Fine, материал PETG" in text and "Печать 1 ч 5 мин" in text
    assert "Проект лежит в папке C:\\p" in text


def test_a_claim_is_taken_once_until_its_delivery_dies():
    at = now()
    waiting = QueuedMessage(job_id="j", text="x")
    held = waiting.model_copy(update={"status": "delivering", "claim": "c", "claimed_at": at})
    dead = held.model_copy(update={"claimed_at": at - CLAIM_TIMEOUT - timedelta(seconds=1)})
    assert claimable(waiting, False, at) and not busy(waiting, at)
    assert busy(held, at) and not claimable(held, True, at)
    assert claimable(dead, False, at) and not busy(dead, at)


def test_twice_failed_messages_go_only_when_sent_by_hand():
    failed = QueuedMessage(job_id="j", text="x", attempts=2)
    assert not claimable(failed, False, now()) and claimable(failed, True, now())
    assert claimable(failed.model_copy(update={"attempts": 1}), False, now())


async def test_a_new_project_while_questions_wait_needs_the_users_consent():
    job = Job(
        user_id="u", revision=1, status=Status.WAITING, projects=[Project(number=1, title="Вал")]
    )
    job.card = TaskCard(job_id=job.id, revision=1)
    files = [file("Колесо.STL", "stl")]
    hasty = reply("", tool_calls=[call(START, {"title": "Колесо"})])
    agent, model = assistant(assistant=[hasty, reply("Отложить вал и начать колесо?")])
    assert (await agent.decide(situation(job, files=files), said)).action == "reply"
    assert "ждёт ответов" in model.requests["assistant"][1]["messages"][-1]["content"]
    agreed = reply("", tool_calls=[call(START, {"title": "Колесо", "drop_current": True})])
    agent, _ = assistant(assistant=[agreed])
    assert (await agent.decide(situation(job, files=files), said)).action == "start"
    state = assistant_messages("система", situation(job))[-1]["content"]
    assert "как принять ответ" not in state


def test_the_template_says_when_no_parameters_fit():
    facts = {"outcome": "parameters_attention", "parameters": {"status": "infeasible"}}
    assert template(facts).startswith("Подобрать параметры под все требования не получилось")
    assert template({"outcome": "parameters_attention"}).startswith(
        "Параметры подобраны, но требуют внимания"
    )


async def test_details_are_asked_once_and_the_next_turn_starts():
    """Детали спрашиваются один раз."""
    files = [file("Колесо.STL", "stl")]
    ask = reply("", tool_calls=[call(ASK, {"text": "Расскажите — для чего деталь?"})])
    agent, _ = assistant(assistant=[ask])
    decision = await agent.decide(situation(files=files), said)
    assert (decision.action, decision.text) == ("ask", "Расскажите, для чего деталь?")
    earlier = [
        {"id": "m1", "seq": 1, "role": "user", "kind": "chat", "text": "Деталь"},
        {"id": "a1", "seq": 2, "role": "assistant", "kind": "gate", "text": "Расскажите"},
        {"id": "m2", "seq": 3, "role": "user", "kind": "chat", "text": "Не знаю"},
    ]
    again = Situation(Job(user_id="u"), earlier, files, files)
    start = reply("", tool_calls=[call(START, {"title": "Колесо"})])
    agent, model = assistant(assistant=[ask, start])
    decision = await agent.decide(again, said)
    assert decision.action == "start"
    assert "уже спрашивал" in model.requests["assistant"][1]["messages"][-1]["content"]


async def test_a_text_reply_while_questions_wait_is_checked_once():
    """Текстовый ответ проверяется один раз."""
    job = Job(
        user_id="u", revision=1, status=Status.WAITING, projects=[Project(number=1, title="Вал")]
    )
    job.card = TaskCard(
        job_id=job.id, revision=1, questions=[Question(id="q", kind="clarify", title="Среда")]
    )
    update = reply("", tool_calls=[call(UPDATE, {"summary": "Учитываю ответ"})])
    agent, model = assistant(assistant=[reply("Принято"), update])
    decision = await agent.decide(situation(job, text="Масло"), said)
    assert decision.action == "update"
    assert model.requests["assistant"][1]["messages"][-1]["content"].startswith(
        "Ты ответил текстом"
    )
    # ответ на вопрос
    agent, model = assistant(assistant=[reply("Стоит дорого"), reply("Стоит дорого")])
    decision = await agent.decide(situation(job, text="Сколько стоит принтер?"), said)
    assert (decision.action, len(model.requests["assistant"])) == ("reply", 2)


async def test_a_decision_keeps_its_turn():
    agent, _ = assistant(assistant=[reply("Привет")])
    decision = await agent.decide(situation(), said)
    assert decision.turn


async def test_a_model_and_a_task_start_and_the_checker_asks_later():
    """Модель и задача запускают работу."""
    files = [file("Шестерня.stl", "stl"), file("ТЗ.txt", "txt")]
    ask = reply("", tool_calls=[call(ASK, {"text": "Какая температура верна?"})])
    start = reply("", tool_calls=[call(START, {"title": "Шестерня"})])
    agent, model = assistant(assistant=[ask, start])
    assert (await agent.decide(situation(files=files), said)).action == "start"
    assert "найдёт проверяющий" in model.requests["assistant"][1]["messages"][-1]["content"]
    agent, model = assistant(assistant=[reply("Какая температура верна?"), start])
    assert (await agent.decide(situation(files=files), said)).action == "start"
    # держит слово
    wait = reply("Хорошо, жду")
    agent, model = assistant(assistant=[wait, wait])
    decision = await agent.decide(situation(files=files, text="Пока не запускай"), said)
    assert (decision.action, len(model.requests["assistant"])) == ("reply", 2)


def test_the_report_names_the_profile_as_the_slicer_menu_does():
    """Отчёт называет профиль как слайсер."""
    summary = ParametersSummary(
        iteration=1,
        printing_mode="3D",
        quality_type="Fine",
        material="PLA",
        changed_settings=0,
        unsatisfied=0,
        status="proposed",
    )
    assert _quality("normal", Job(user_id="u", parameters=summary)) == "Fine (normal)"
    assert _quality("normal", Job(user_id="u")) == "normal"

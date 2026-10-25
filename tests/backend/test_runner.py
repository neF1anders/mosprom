import asyncio
import time

import pytest

from src.backend.agents.events import BUFFER, CallEvents, Clock, Narration, ThoughtStream, preview
from src.backend.agents.runner import AgentRunner, AgentSpec, parse_output
from src.backend.agents.schemas import Draft, Output
from src.backend.agents.tools import ToolBox
from src.backend.domain.errors import AppError

from .fakes import FakeUow, ScriptedModel, call, context, reply

pytestmark = pytest.mark.unit
SPEC = AgentSpec("interpreter", "Разбор ТЗ", Draft, ("convert_units",), max_steps=3)


class Scored(Output):
    score: float


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def runner(script, clock: Clock = time.monotonic) -> tuple[AgentRunner, ScriptedModel, FakeUow]:
    model, uow = ScriptedModel(script), FakeUow()
    return AgentRunner(model, ToolBox(None), uow, clock=clock), model, uow


def kinds(ctx) -> list[tuple[str, str]]:
    return [(type, status) for type, _, status, _ in ctx.recorded]


def thoughts(clock: FakeClock) -> tuple[ThoughtStream, list[tuple[int, str]]]:
    sent: list[tuple[int, str]] = []

    async def event(type, message, status="running", **data):
        sent.append((data["attempt"], data["text"]))

    return ThoughtStream(event, "checker", "Проверка", "r:checker:1", clock), sent


def test_json_repair_and_per_item_validation():
    text = """```json
    {"purpose": "Шестерня", "requirements": [
      {"key": "t", "value": 25, "unit": "Н·м", "sources": []},
      {"label": "без ключа и значения"},
      {"key": "m", "value": "PA12", "extra": "ignored"}
    ], "unknowns": ["срок службы", {"bad": 1}],}
    """
    draft, dropped = parse_output(text, Draft)
    assert draft.purpose == "Шестерня"
    assert [(r.key, r.value) for r in draft.requirements] == [("t", "25"), ("m", "PA12")]
    assert draft.unknowns == ["срок службы"]
    assert len(dropped) == 2


@pytest.mark.parametrize("text", ["", "[1, 2]", "просто текст"])
def test_non_object_answer_is_a_technical_error(text):
    with pytest.raises(AppError) as error:
        parse_output(text, Draft)
    assert error.value.code == "model_output"


def test_missing_required_scalar_is_an_error():
    with pytest.raises(AppError):
        parse_output('{"remarks": []}', Scored)


async def test_tool_loop_repeated_calls_and_tracing():
    agent, model, uow = runner(
        {
            "interpreter": [
                reply(
                    tool_calls=[
                        call("convert_units", {"value": "1", "from_unit": "inch", "to_unit": "mm"})
                    ]
                ),
                reply(
                    tool_calls=[
                        call(
                            "convert_units",
                            {"value": "1", "from_unit": "inch", "to_unit": "mm"},
                            "c2",
                        )
                    ]
                ),
                reply({"purpose": "Деталь"}),
            ]
        }
    )
    ctx = context()
    result = await agent.run(SPEC, [{"type": "text", "text": "данные"}], ctx)
    assert result.purpose == "Деталь"
    tool_messages = [m for m in model.requests["interpreter"][2]["messages"] if m["role"] == "tool"]
    assert [m["content"] for m in tool_messages] == ['{"value": "25.4", "unit": "mm"}'] * 2
    assert sum(e[0] == "tool.called" for e in ctx.recorded) == 1
    assert [c.step for c in uow.traces.calls] == [1, 2, 3]
    assert uow.traces.calls[0].tools[0]["result"] == {"value": "25.4", "unit": "mm"}


async def test_last_step_has_no_tools_and_a_closing_instruction():
    endless = reply(
        tool_calls=[call("convert_units", {"value": "x", "from_unit": "mm", "to_unit": "m"})]
    )
    agent, model, _ = runner({"interpreter": [endless, endless, reply({"purpose": "Итог"})]})
    result = await agent.run(SPEC, [], context())
    assert result.purpose == "Итог"
    last = model.requests["interpreter"][2]
    assert (
        last["tools"] == [] and "Инструменты больше недоступны" in last["messages"][-1]["content"]
    )


async def test_tool_outside_the_agent_list_is_refused():
    agent, model, _ = runner(
        {"interpreter": [reply(tool_calls=[call("view_page", {"source_id": "f1p1"})]), reply({})]}
    )
    await agent.run(SPEC, [], context())
    tool = next(m for m in model.requests["interpreter"][1]["messages"] if m["role"] == "tool")
    assert "недоступен" in tool["content"]


async def test_truncated_answer_is_an_error_not_a_partial_card():
    agent, _, uow = runner({"interpreter": [reply('{"purpose": "обо', finish_reason="length")]})
    with pytest.raises(AppError) as error:
        await agent.run(SPEC, [], context())
    assert error.value.code == "model_truncated"
    assert len(uow.traces.calls) == 1


async def test_images_are_traced_as_references():
    agent, _, uow = runner({"interpreter": [reply({})]})
    ctx = context()
    ctx.images["data:image/png;base64,AAAA"] = "page-1.png"
    content = [{"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}]
    await agent.run(SPEC, content, ctx)
    stored = uow.traces.calls[0].request["messages"][1]["content"][0]
    assert stored == {"type": "image_url", "artifact": "page-1.png"}


async def test_same_input_reuses_the_result_and_new_input_asks_again():
    agent, model, _ = runner(
        {"interpreter": [reply({"purpose": "Первый"}), reply({"purpose": "Второй"})]}
    )
    text = [{"type": "text", "text": "ТЗ"}]
    assert (await agent.run(SPEC, text, context())).purpose == "Первый"
    assert (await agent.run(SPEC, text, context())).purpose == "Первый"
    assert len(model.requests["interpreter"]) == 1
    other = [{"type": "text", "text": "ТЗ с ответом"}]
    assert (await agent.run(SPEC, other, context())).purpose == "Второй"
    budgeted = AgentSpec("interpreter", "Разбор ТЗ", Draft, ("convert_units",), budget=100)
    await agent.run(budgeted, text, context())
    assert len(model.requests["interpreter"]) == 3
    assert model.requests["interpreter"][2]["budget"] == 100


async def test_a_reply_that_lost_items_is_not_reused():
    """Повреждённый ответ не переиспользуется."""
    damaged = reply({"purpose": "Деталь", "requirements": [{"label": "без значения"}]})
    whole = reply({"purpose": "Деталь", "requirements": [{"key": "t", "value": "25"}]})
    agent, model, uow = runner({"interpreter": [damaged, whole]})
    text = [{"type": "text", "text": "ТЗ"}]
    assert (await agent.run(SPEC, text, context())).requirements == []
    assert [r.key for r in (await agent.run(SPEC, text, context())).requirements] == ["t"]
    assert len(model.requests["interpreter"]) == 2
    assert [r.key for r in (await agent.run(SPEC, text, context())).requirements] == ["t"]
    assert len(model.requests["interpreter"]) == 2
    hit = uow.traces.calls[-1]
    assert hit.cached and hit.step == 0 and hit.response is None
    assert hit.request["cache_key"].startswith("agent:")


async def test_each_step_traces_only_the_messages_it_added():
    converted = call("convert_units", {"value": "1", "from_unit": "inch", "to_unit": "mm"})
    agent, _, uow = runner(
        {"interpreter": [reply(tool_calls=[converted]), reply({"purpose": "Деталь"})]}
    )
    await agent.run(SPEC, [{"type": "text", "text": "данные"}], context())
    first, second = (c.request for c in uow.traces.calls)
    assert first["offset"] == 0 and [m["role"] for m in first["messages"]] == ["system", "user"]
    assert second["offset"] == 2
    assert [m["role"] for m in second["messages"]] == ["assistant", "tool"]


async def test_a_later_turn_is_reused_only_for_the_same_history():
    agent, model, _ = runner(
        {"interpreter": [reply({"purpose": "Ответ"}), reply({"purpose": "Другой"})]}
    )
    dialog = [
        {"role": "user", "content": [{"type": "text", "text": "ТЗ"}]},
        {"role": "assistant", "content": '{"purpose": "Деталь"}'},
        {"role": "user", "content": "Ответы"},
    ]
    assert (await agent.converse(SPEC, dialog, context())).purpose == "Ответ"
    assert (await agent.converse(SPEC, dialog, context())).purpose == "Ответ"
    sent = model.requests["interpreter"][0]["messages"]
    assert [m["role"] for m in sent] == ["system", "user", "assistant", "user"]
    changed = [*dialog[:2], {"role": "user", "content": "Другие ответы"}]
    assert (await agent.converse(SPEC, changed, context())).purpose == "Другой"
    assert len(model.requests["interpreter"]) == 2


async def test_talk_offers_the_tools_but_does_not_run_them():
    tool = {"type": "function", "function": {"name": "start_pipeline", "parameters": {}}}
    agent, model, uow = runner({"gate": [reply("", tool_calls=[call("start_pipeline", {})])]})
    spec = AgentSpec("gate", "Ассистент", Output, max_steps=1, thinking=False)
    messages = [
        {"role": "system", "content": "Ты ассистент"},
        {"role": "user", "content": "Привет"},
    ]
    ctx = context()
    answer = await agent.talk(spec, messages, [tool], ctx)
    assert answer.tool_calls[0]["function"]["name"] == "start_pipeline"
    assert model.requests["gate"][0]["tools"] == [tool]
    assert model.requests["gate"][0]["thinking"] is False
    assert len(uow.traces.calls) == 1 and uow.cache.values == {}
    assert [(e[0], e[3]["call"]) for e in ctx.recorded] == [
        ("agent.started", "r:gate:1"),
        ("agent.thinking", "r:gate:1"),
        ("agent.finished", "r:gate:1"),
    ]


def test_a_null_in_an_optional_field_keeps_the_item():
    """Null в поле сохраняет пункт."""
    text = """{"requirements": [
      {"key": "duty", "label": null, "value": "24/7", "unit": null, "conditions": null,
       "sources": [{"source_id": "f1p1", "page": null, "quote": "режим 24/7"}]},
      {"key": "brittle", "value": null}
    ]}"""
    draft, dropped = parse_output(text, Draft)
    [duty] = draft.requirements
    assert (duty.key, duty.label, duty.conditions, duty.unit) == ("duty", "", "", None)
    assert duty.sources[0].quote == "режим 24/7"
    # обязательное поле ломает
    assert dropped == ["requirements[1]: Input should be a valid string"]


async def test_a_call_shows_its_start_reasoning_and_end():
    clock = FakeClock()

    async def slow(messages):
        clock.now = 2.5
        return reply({"purpose": "Деталь"}, reasoning="Читаю ТЗ")

    agent, _, _ = runner({"interpreter": [slow]}, clock)
    ctx = context()
    await agent.run(SPEC, [], ctx)
    call_id = "r:interpreter:1"
    assert ctx.recorded == [
        (
            "agent.started",
            "Разбор ТЗ, работает",
            "running",
            {"agent": "interpreter", "title": "Разбор ТЗ", "call": call_id},
        ),
        (
            "agent.thinking",
            "Разбор ТЗ, рассуждает",
            "running",
            {"agent": "interpreter", "call": call_id, "attempt": 1, "text": "Читаю ТЗ"},
        ),
        (
            "agent.finished",
            "Разбор ТЗ, готово",
            "completed",
            {
                "agent": "interpreter",
                "title": "Разбор ТЗ",
                "call": call_id,
                "duration_ms": 2500,
                "cached": False,
            },
        ),
    ]


async def test_a_reused_result_starts_and_finishes_at_once():
    agent, _, _ = runner({"interpreter": [reply({"purpose": "Деталь"})]}, FakeClock())
    text = [{"type": "text", "text": "ТЗ"}]
    await agent.run(SPEC, text, context())
    ctx = context()
    await agent.run(SPEC, text, ctx)
    assert [(e[0], e[1], e[2]) for e in ctx.recorded] == [
        ("agent.started", "Разбор ТЗ, работает", "running"),
        ("agent.finished", "Разбор ТЗ, ответ из кеша", "completed"),
    ]
    assert ctx.recorded[-1][3] == {
        "agent": "interpreter",
        "title": "Разбор ТЗ",
        "call": "r:interpreter:0",
        "duration_ms": 0,
        "cached": True,
    }


@pytest.mark.parametrize(
    "answer",
    [
        AppError("Модель не отвечает", "model_unavailable", 503),
        reply('{"purpose": "обо', finish_reason="length"),
    ],
)
async def test_a_failed_call_finishes_as_failed(answer):
    agent, _, _ = runner({"interpreter": [answer]})
    ctx = context()
    with pytest.raises(AppError):
        await agent.run(SPEC, [], ctx)
    assert ctx.recorded[0][0] == "agent.started"
    assert ctx.recorded[-1][:3] == ("agent.finished", "Разбор ТЗ, ошибка", "failed")


async def test_a_cancelled_call_sends_nothing_after_its_start():
    def stopped(messages):
        raise asyncio.CancelledError

    agent, _, _ = runner({"interpreter": [stopped]})
    ctx = context()
    with pytest.raises(asyncio.CancelledError):
        await agent.run(SPEC, [], ctx)
    assert kinds(ctx) == [("agent.started", "running")]


async def test_tools_run_inside_their_step_and_finish_with_a_preview():
    good = call("convert_units", {"value": "1", "from_unit": "inch", "to_unit": "mm"})
    bad = call("convert_units", {"value": "x", "from_unit": "mm", "to_unit": "m"}, "c2")
    agent, _, _ = runner(
        {"interpreter": [reply(tool_calls=[good, bad]), reply({"purpose": "Деталь"})]},
        FakeClock(),
    )
    ctx = context()
    await agent.run(SPEC, [], ctx)
    assert kinds(ctx) == [
        ("agent.started", "running"),
        ("agent.thinking", "running"),
        ("tool.called", "running"),
        ("tool.finished", "completed"),
        ("tool.called", "running"),
        ("tool.finished", "warning"),
        ("agent.finished", "completed"),
        ("agent.started", "running"),
        ("agent.thinking", "running"),
        ("agent.finished", "completed"),
    ]
    converted, refused = [e for e in ctx.recorded if e[0] == "tool.finished"]
    assert converted[1] == "Разбор ТЗ, переводит единицы, готово"
    assert converted[3] == {
        "agent": "interpreter",
        "tool": "convert_units",
        "call": "r:interpreter:1",
        "duration_ms": 0,
        "result_preview": '{"value": "25.4", "unit": "mm"}',
    }
    assert refused[1] == "Разбор ТЗ, переводит единицы, ошибка"
    assert refused[3]["result_preview"].startswith('{"error": ')


def test_a_tool_preview_leaves_out_images_and_stays_short():
    shown = preview({"status": "приложено " * 40, "images": [{"type": "image_url"}]})
    assert len(shown) == 200 and "images" not in shown
    assert shown.startswith('{"status": "приложено приложено')


async def test_reasoning_goes_out_after_a_pause_a_paragraph_or_a_full_buffer():
    clock = FakeClock()
    stream, sent = thoughts(clock)
    pieces = [(0.2, "a"), (0.4, "b"), (1.0, "c"), (1.3, "x\n\ny"), (1.6, "z"), (1.7, "w" * BUFFER)]
    for at, text in pieces:
        clock.now = at
        await stream(text, 1)
    # абзац до конца
    assert [text for _, text in sent] == ["abc", "x\n\n", "yz" + "w" * BUFFER]
    await stream("конец", 1)
    assert len(sent) == 3
    await stream.close()
    await stream.close()
    assert sent[3:] == [(1, "конец")]


async def test_a_new_attempt_drops_the_unsent_reasoning():
    clock = FakeClock()
    stream, sent = thoughts(clock)
    await stream("прежняя попытка", 1)
    await stream("новая", 2)
    await stream.close()
    assert sent == [(2, "новая")]


async def test_events_that_fail_never_stop_the_run():
    async def broken(*args, **data):
        raise RuntimeError("database is down")

    agent, _, _ = runner({"interpreter": [reply({"purpose": "Деталь"}, reasoning="Читаю")]})
    ctx = context()
    ctx.event = broken
    assert (await agent.run(SPEC, [], ctx)).purpose == "Деталь"
    clock = FakeClock()
    stream, _ = thoughts(clock)
    clock.now = 5
    await stream(None, 1)  # type: ignore[arg-type]
    assert stream.buffer == ""


async def test_a_stop_is_never_swallowed_by_the_reasoning():
    async def stopped(*args, **data):
        raise asyncio.CancelledError

    stream = ThoughtStream(stopped, "checker", "Проверка", "r:checker:1", FakeClock())
    with pytest.raises(asyncio.CancelledError):
        await stream("w" * BUFFER, 1)


def narration(narrate) -> tuple[Narration, list[tuple[int, str]]]:
    said: list[tuple[int, str]] = []

    async def event(type, message, status="running", **data):
        said.append((data["attempt"], data["text"]))

    return Narration(event, "checker", "r:checker:1", "Проверка", narrate, 0.01, 0.01), said


async def test_the_narrator_says_what_the_agent_does_while_it_reasons():
    heard: list[tuple[str, str]] = []

    async def narrate(title: str, reasoning: str, previous: str) -> str:
        heard.append((reasoning, previous))
        return f"Сверяю {len(heard)}"

    talk, said = narration(narrate)
    talk.feed("Checking the torque. ", 1)
    await asyncio.sleep(0.03)
    talk.feed("Now the temperature.", 1)
    await asyncio.sleep(0.03)
    talk.stop()
    assert said[:2] == [(1, "Сверяю 1"), (1, "Сверяю 2")]
    assert heard[0] == ("Checking the torque. ", "")
    assert heard[1] == ("Checking the torque. Now the temperature.", "Сверяю 1")


async def test_the_narrator_keeps_quiet_without_news_and_skips_a_failure():
    calls = 0

    async def narrate(title: str, reasoning: str, previous: str) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise AppError("Модель не отвечает", "model_unavailable", 503)
        return "Разбираю ТЗ"

    talk, said = narration(narrate)
    talk.feed("Reading the spec", 1)
    await asyncio.sleep(0.05)
    # второго вызова нет
    assert calls == 1 and said == []
    talk.feed(" further", 2)
    await asyncio.sleep(0.03)
    talk.stop()
    assert said[0] == (2, "Разбираю ТЗ")


async def test_a_cancelled_call_stops_its_narrator():
    async def narrate(title: str, reasoning: str, previous: str) -> str:
        return "Разбираю ТЗ"

    async def event(type, message, status="running", **data):
        pass

    ctx = context()
    ctx.event = event
    events = CallEvents(SPEC, ctx, 1, FakeClock(), narrate=narrate)
    with pytest.raises(asyncio.CancelledError):
        async with events:
            await events.thoughts("Reading", 1)
            raise asyncio.CancelledError
    await asyncio.sleep(0)
    assert events.narration is not None and events.narration.task is not None
    assert events.narration.task.cancelled() or events.narration.task.done()

import pytest

from src.backend.agents.runner import AgentRunner, AgentSpec, parse_output
from src.backend.agents.schemas import Draft, Output
from src.backend.agents.tools import ToolBox
from src.backend.domain.errors import AppError

from .fakes import FakeUow, ScriptedModel, call, context, reply

pytestmark = pytest.mark.unit
SPEC = AgentSpec("interpreter", "Разбор ТЗ", Draft, ("convert_units",), max_steps=3)


class Scored(Output):
    score: float


def runner(script) -> tuple[AgentRunner, ScriptedModel, FakeUow]:
    model, uow = ScriptedModel(script), FakeUow()
    return AgentRunner(model, ToolBox(None), uow), model, uow


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
    """Regression: a damaged reply was cached and every retry got the same empty draft."""
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
    answer = await agent.talk(spec, messages, [tool], context())
    assert answer.tool_calls[0]["function"]["name"] == "start_pipeline"
    assert model.requests["gate"][0]["tools"] == [tool]
    assert model.requests["gate"][0]["thinking"] is False
    assert len(uow.traces.calls) == 1 and uow.cache.values == {}

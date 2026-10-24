"""The agent «Корректировка» and the rules of a claim, without a database."""

from datetime import timedelta

import pytest

from src.backend.agents.runner import AgentRunner, prompt
from src.backend.agents.steer import APPLIED, APPLY, REPLY, Steer, steer_messages
from src.backend.agents.tools import ToolBox
from src.backend.domain.models import Job, QueuedMessage, Requirement, TaskCard, now
from src.backend.services.steering import CLAIM_TIMEOUT, busy, claimable

from .fakes import FakeUow, ScriptedModel, call, reply

pytestmark = pytest.mark.unit


class Store:
    """The job is current, whatever the agent asks."""

    async def check(self, job_id, revision):
        return None

    async def event(self, *args, **kwargs):
        return None


def agent(*replies) -> tuple[Steer, ScriptedModel]:
    model = ScriptedModel({"steer": list(replies)})
    steer = Steer(AgentRunner(model, ToolBox(None), FakeUow()), FakeUow())
    steer.store = Store()  # type: ignore[assignment]
    return steer, model


def job(**card) -> Job:
    job = Job(user_id="u", revision=3, stage="slicing")
    job.card = TaskCard(job_id=job.id, revision=3, **card)
    return job


def test_the_tool_block_of_the_prompt_becomes_the_correction_tool():
    steer, _ = agent(reply("Привет"))
    assert "<tool_apply_correction>" not in steer.system and "«Корректировка»" in steer.system
    function = steer.tool["function"]
    assert function["name"] == APPLY
    assert function["description"].startswith("Применяет правку")
    assert function["parameters"]["required"] == ["summary"]
    assert "Длину участка A поменял со 100 на 90 мм" in prompt("steer")


def test_the_agent_sees_the_stage_the_purpose_and_twenty_requirements():
    requirements = [
        Requirement(key=f"r{i}", label=f"Длина участка {i}", value=str(i), unit="мм")
        for i in range(25)
    ]
    messages = steer_messages(
        "система", job(purpose="Корпус насоса", requirements=requirements), ["Первое", "Второе"]
    )
    assert [m["role"] for m in messages] == ["system", "user"]
    content = messages[1]["content"]
    assert '"этап": "нарезка"' in content and '"назначение": "Корпус насоса"' in content
    assert "Длина участка 19 19 мм" in content and "Длина участка 20" not in content
    assert content.endswith("<messages>\nПервое\n\nВторое\n</messages>")


async def test_only_the_call_makes_a_correction():
    summary = "Длину участка A поменял со 100 на 90 мм: пересчитываю то, что от неё зависит."
    steer, model = agent(reply("Хорошо", tool_calls=[call(APPLY, {"summary": summary})]))
    decision = await steer.decide(job(), ["Длина участка A 90 мм"])
    assert decision.correction
    assert (
        decision.text
        == "Длину участка A поменял со 100 на 90 мм, пересчитываю то, что от неё зависит"
    )
    request = model.requests["steer"][0]
    assert request["tools"] == [steer.tool] and request["thinking"] is False


@pytest.mark.parametrize(
    ("answer", "correction", "text"),
    [
        (
            reply("Погоду не знаю — работаю над деталью."),
            False,
            "Погоду не знаю, работаю над деталью",
        ),
        (reply(""), False, REPLY),
        (reply("", tool_calls=[call(APPLY, {})]), True, APPLIED),
        (reply("", tool_calls=[call("start_pipeline", {})]), False, REPLY),
    ],
)
async def test_a_reply_follows_the_chat_rules_and_falls_back_when_empty(answer, correction, text):
    steer, _ = agent(answer)
    decision = await steer.decide(job(), ["Какая погода"])
    assert (decision.correction, decision.text) == (correction, text)


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

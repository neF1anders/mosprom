import asyncio
import json
from uuid import uuid4

import pytest

from src.backend.domain.errors import AppError
from src.backend.domain.models import Attachment, Job, Knowledge
from src.backend.infrastructure.files import LocalFiles


@pytest.mark.unit
@pytest.mark.parametrize("key", ["../secret", "/etc/passwd", "..", "name.exe", "a/b.png"])
async def test_T01_storage_rejects_unsafe_identifiers(tmp_path, key):
    with pytest.raises(AppError):
        await LocalFiles(tmp_path).read(key)


@pytest.mark.integration
@pytest.mark.parametrize("case", ["alias", "unknown", "family", "conditions", "conflict"])
async def test_T06_knowledge_never_substitutes_unproven_properties(pg, case):
    records = [
        Knowledge(
            id="grade1",
            material_id="grade1",
            aliases=["Alias"],
            property="density",
            value="1.2",
            unit="g/cm3",
            conditions="20C",
            text="Плотность материала",
            source="fixture:approved",
            scope="grade",
        )
    ]
    if case == "family":
        records[0] = records[0].model_copy(update={"scope": "family"})
    if case == "conflict":
        records.append(records[0].model_copy(update={"id": "grade2", "value": "1.3"}))
    async with pg.uow() as uow:
        for record in records:
            await uow.knowledge.put(record)
        await uow.commit()
    result = await pg.knowledge.search(
        "плотность",
        "missing" if case == "unknown" else "Alias",
        "density",
        "80C" if case == "conditions" else "",
    )
    expected = {
        "alias": "found",
        "unknown": "not_found",
        "family": "ambiguous",
        "conditions": "ambiguous",
        "conflict": "ambiguous",
    }
    assert result["status"] == expected[case]


@pytest.mark.integration
@pytest.mark.parametrize("case", ["unknown", "invalid", "foreign", "scale", "inactive"])
async def test_T09_tool_validation(pg, case):
    job = Job(active_stl="owned")
    attachment = Attachment(
        id="owned",
        job_id=job.id,
        filename="x.stl",
        kind="stl",
        sha256="hash",
        size=1,
        active=case != "inactive",
    )
    name = "shell" if case == "unknown" else "analyze_stl"
    args = (
        "broken"
        if case == "invalid"
        else json.dumps(
            {
                "attachment_id": "foreign" if case == "foreign" else "owned",
                "units": "mm" if case == "scale" else "unknown",
            }
        )
    )
    with pytest.raises(AppError):
        await pg.pipeline.extraction.tools.call(name, args, job, [attachment])


@pytest.mark.integration
@pytest.mark.parametrize(
    "case", ["expired", "new_owner", "stale_finish", "stale_heartbeat", "two_claims"]
)
async def test_T12_lease_recovery_fences_old_worker(pg, case):
    job = await pg.jobs.create(str(uuid4()), "Lease")
    await pg.messages.send(job["id"], str(uuid4()), "Text")
    async with pg.uow() as uow:
        first = await uow.queue.claim("first", lease_seconds=-1)
        await uow.commit()
    async with pg.uow() as uow:
        second = await uow.queue.claim("second")
        assert second and first and second.id == first.id and second.attempts == 2
        await uow.commit()
    if case == "expired":
        assert second.attempts == 2
        return
    if case == "two_claims":

        async def claim():
            async with pg.uow() as uow:
                result = await uow.queue.claim(str(uuid4()))
                await uow.commit()
                return result

        assert await asyncio.gather(claim(), claim()) == [None, None]
        return
    async with pg.uow() as uow:
        if case == "stale_finish":
            await uow.queue.finish(first)
            assert await uow.queue.heartbeat(second)
        elif case == "stale_heartbeat":
            assert not await uow.queue.heartbeat(first)
        else:
            assert await uow.queue.heartbeat(second)
            assert second.owner != first.owner
        await uow.commit()

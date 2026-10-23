from uuid import uuid4

import pytest

from src.backend.domain.models import TaskCard

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("revision", [0, 1, 2, 5, 10])
async def test_T13_stale_card_is_never_exported(pg, http, revision):
    created = await pg.jobs.create(str(uuid4()), "Export")
    async with pg.uow() as uow:
        job = await uow.jobs.get(created["id"], lock=True)
        job.revision = revision + 1
        job.card = TaskCard(revision=revision)
        await uow.jobs.save(job)
        await uow.commit()
    response = await http.get(f"/api/v1/jobs/{job.id}/card")
    assert response.status_code == 409

from uuid import uuid4

import pytest

pytestmark=pytest.mark.integration


async def test_invalid_attachment_can_be_replaced_without_permanent_block(pg):
    created=await pg.jobs.create(str(uuid4()),'Replacement')
    async def chunks():yield b'broken'
    item=await pg.uploads.upload(created['id'],str(uuid4()),'bad.pdf',chunks())
    await pg.uploads.detach(created['id'],str(uuid4()),item['id'])
    assert not (await pg.jobs.snapshot(created['id']))['attachments']

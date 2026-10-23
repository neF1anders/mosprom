import base64
import io
import json
from pathlib import Path
from uuid import uuid4

import pytest
from PIL import Image

from src.backend.domain.models import DOCUMENT_VERSION
from tests.backend.test_full_card import settle
from tests.model_server import visual_requirements

pytestmark = pytest.mark.integration


class VisionProvider:
    def __init__(self):
        self.pages = set()

    async def complete(self, messages, tools):
        content = messages[1]["content"]
        assert isinstance(content, list)
        context = json.loads(content[0]["text"])
        images = [part["image_url"]["url"] for part in content if part["type"] == "image_url"]
        sources = context["sources"]
        assert len(images) == sum(bool(source.get("image")) for source in sources.values())
        for data in images:
            with Image.open(io.BytesIO(base64.b64decode(data.split(",", 1)[1]))) as image:
                image.verify()
        self.pages.update(source["page"] for source in sources.values() if source.get("image"))
        return {
            "content": json.dumps(
                {"purpose": "Шестерня", "requirements": visual_requirements(sources)}
            )
        }


async def prepare(pg, name):
    model = VisionProvider()
    pg.pipeline.extraction.model = model
    job = await pg.jobs.create(str(uuid4()), "PDF vision")

    async def chunks():
        yield Path("tests/fixtures", name).read_bytes()

    attachment = await pg.uploads.upload(job["id"], str(uuid4()), name, chunks())
    return job["id"], attachment, model


@pytest.mark.parametrize(
    "name,pages", [("text.pdf", 1), ("scan.pdf", 1), ("mixed.pdf", 2), ("photo.png", 1)]
)
async def test_vision_pages_reach_model_and_keep_viewable_evidence(pg, http, name, pages):
    job_id, attachment, model = await prepare(pg, name)
    job = await settle(pg)
    assert job["card"]["schema_version"] == "1.2"
    assert model.pages == set(range(1, pages + 1))
    assert len(job["card"]["requirements"]) == 2 * pages
    for requirement in job["card"]["requirements"]:
        assert requirement["verified"]
        source = requirement["sources"][0]
        assert source["source_id"].startswith(attachment["id"] + ":")
        assert source["page"] in model.pages
        assert source["artifact_id"]
        image = await http.get(f"/api/v1/jobs/{job_id}/artifacts/{source['artifact_id']}")
        assert image.status_code == 200
    if name in {"scan.pdf", "photo.png"}:
        assert all(r["sources"][0]["method"] == "vision" for r in job["card"]["requirements"])


async def test_legacy_ocr_fragments_rebuilt_once_without_ocr(pg):
    job_id, attachment, _ = await prepare(pg, "scan.pdf")
    await settle(pg)
    original_inspect = pg.files.inspect
    calls = []

    async def observe(key, kind):
        calls.append(key)
        return await original_inspect(key, kind)

    pg.files.inspect = observe
    async with pg.uow() as uow:
        stored = next(a for a in await uow.jobs.attachments(job_id) if a.id == attachment["id"])
        stored.parser_version = "documents-v1-ocr"
        stored.fragments[0].update(method="ocr", text="Old OCR 999")
        await uow.jobs.attachment(stored)
        await uow.commit()
    await pg.control.run(job_id, str(uuid4()), "retry")
    await settle(pg)
    async with pg.uow() as uow:
        current = next(a for a in await uow.jobs.attachments(job_id) if a.id == attachment["id"])
        assert current.parser_version == DOCUMENT_VERSION
        assert current.fragments[0]["method"] == "vision"
        assert current.fragments[0]["text"] == ""
    await pg.control.run(job_id, str(uuid4()), "retry")
    await settle(pg)
    assert calls == [attachment["id"]]

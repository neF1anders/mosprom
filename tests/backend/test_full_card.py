import copy
import hashlib
import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from src.backend.infrastructure.handoff import HttpHandoff
from tests.backend.test_pipeline import ModelDouble, run_work

pytestmark = pytest.mark.integration


class FullAnalyzer:
    def __init__(self, files):
        self.files = files
        self.calls = []
        self.reports = {}
        self.partial = False

    async def analyze(self, key, units, cache_key):
        self.calls.append((key, units))
        scale = {"unknown": 1, "mm": 1, "cm": 10, "m": 1000, "inch": 25.4}[units]
        report = {
            "schema_version": "analyzer-fixture-1",
            "status": "partial" if self.partial else "checks_passed",
            "file": {
                "path": key,
                "triangles": 12,
                "sha256": hashlib.sha256(await self.files.read(key)).hexdigest(),
            },
            "software": {"analyzer": "test", "versions": ["a", "b"]},
            "geometry": {"extents": [10 * scale, 20 * scale, 30 * scale], "volume": None},
            "topology": {"component_count": 1, "components": [{"faces": [1, 2, 3]}]},
            "validation": {"defects": []},
            "sections": [{"z": 0.5, "paths": [[[1, 2, 3], [4, 5, None]]]}],
            "normal_chords": {"samples": [{"origin": [1, 2, 3], "length": None}]},
            "units": {
                "input_unit": units,
                "coordinate_unit": "unknown" if units == "unknown" else "mm",
            },
            "warnings": ["Физический объём не подтверждён"],
            "partial_errors": {"rays": {"code": "timeout", "completed": 2}} if self.partial else {},
            "future_field": {
                "must_survive": [None, False, 0, [1.25, {"nested": "STL-only-marker"}]]
            },
        }
        self.reports[(key, units)] = copy.deepcopy(report)
        return report


class ObservedModel(ModelDouble):
    def __init__(self):
        super().__init__()
        self.requests = []

    async def complete(self, messages, tools):
        self.requests.append(copy.deepcopy(messages))
        return await super().complete(messages, tools)


async def settle(pg):
    for _ in range(10):
        result = await run_work(pg)
        if result["status"] != "queued":
            return result
    pytest.fail("Queue did not settle")


async def upload(pg, job_id, name="box.stl"):
    async def chunks():
        yield Path("tests/fixtures", name).read_bytes()

    return await pg.uploads.upload(job_id, str(uuid4()), name, chunks())


async def prepare(pg):
    analyzer = FullAnalyzer(pg.files)
    model = ObservedModel()
    pg.files.analyze = analyzer.analyze
    pg.pipeline.extraction.model = model
    captured = []

    async def receiver(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"accepted": True})

    pg.pipeline.handoff = HttpHandoff(
        "http://receiver/cards", transport=httpx.MockTransport(receiver)
    )
    job = await pg.jobs.create(str(uuid4()), "Full card")
    attachment = await upload(pg, job["id"])
    await pg.messages.send(job["id"], str(uuid4()), "Корпус подшипника")
    return job["id"], attachment, analyzer, model, captured


async def test_full_report_is_identical_in_storage_export_and_one_handoff(pg, http):
    job_id, attachment, analyzer, model, captured = await prepare(pg)
    first = await settle(pg)
    await pg.answers.answer(job_id, str(uuid4()), first["revision"], {"geometry.units": "mm"})
    final = await settle(pg)
    exported = (await http.get(f"/api/v1/jobs/{job_id}/card")).json()
    expected = {
        "attachment_id": attachment["id"],
        "sha256": attachment["sha256"],
        "report": analyzer.reports[(attachment["id"], "mm")],
    }
    assert final["card"]["stl_analysis"] == expected
    assert exported == final["card"] == captured[-1]["card"]
    assert captured[-1]["idempotency_key"] == f"{job_id}:{final['revision']}"
    assert exported["schema_version"] == "1.2"
    assert exported["requirements"] and exported["requirements"][0]["sources"]
    assert exported["answers"]["geometry.units"] == "mm"
    assert "STL-only-marker" not in json.dumps(model.requests)
    assert all("stl_analysis" not in request[0]["content"] for request in model.requests)
    from sqlalchemy import select

    from src.backend.infrastructure.tables import cards

    async with pg.engine.connect() as connection:
        stored_version = await connection.scalar(
            select(cards.c.payload).where(
                cards.c.job_id == job_id, cards.c.revision == final["revision"]
            )
        )
    assert stored_version["card"] == exported


@pytest.mark.parametrize(
    "block", ["sections", "normal_chords", "validation", "software", "future_field"]
)
async def test_full_report_preserves_nested_arrays_and_unknown_fields(pg, block):
    job_id, attachment, analyzer, _, _ = await prepare(pg)
    result = await settle(pg)
    report = result["card"]["stl_analysis"]["report"]
    assert report[block] == analyzer.reports[(attachment["id"], "unknown")][block]
    assert report["geometry"]["volume"] is None


async def test_partial_report_preserves_errors_and_missing_values(pg):
    job_id, attachment, analyzer, _, _ = await prepare(pg)
    analyzer.partial = True
    result = await settle(pg)
    report = result["card"]["stl_analysis"]["report"]
    assert report == analyzer.reports[(attachment["id"], "unknown")]
    assert report["partial_errors"]["rays"] == {"code": "timeout", "completed": 2}
    assert report["normal_chords"]["samples"][0]["length"] is None


async def test_replacement_and_new_units_never_reuse_old_report(pg):
    job_id, first, analyzer, _, _ = await prepare(pg)
    initial = await settle(pg)
    await pg.answers.answer(job_id, str(uuid4()), initial["revision"], {"geometry.units": "mm"})
    old = await settle(pg)
    replacement = await upload(pg, job_id, "open.stl")
    pending = await settle(pg)
    assert pending["card"]["stl_analysis"]["attachment_id"] == replacement["id"]
    assert pending["card"]["stl_analysis"]["sha256"] != first["sha256"]
    await pg.answers.answer(job_id, str(uuid4()), pending["revision"], {"geometry.units": "cm"})
    changed = await settle(pg)
    assert changed["card"]["stl_analysis"]["report"] == analyzer.reports[(replacement["id"], "cm")]
    assert changed["card"]["stl_analysis"]["report"]["units"]["input_unit"] == "cm"
    assert changed["card"]["geometry"]["extents"] == [100, 200, 300]
    assert changed["card"]["revision"] > old["card"]["revision"]
    assert len(analyzer.calls) == 4


async def test_text_edit_reuses_complete_report_with_new_card_revision(pg):
    job_id, _, analyzer, _, _ = await prepare(pg)
    old = await settle(pg)
    await pg.messages.send(job_id, str(uuid4()), "Количество 15")
    new = await settle(pg)
    assert new["card"]["stl_analysis"] == old["card"]["stl_analysis"]
    assert new["card"]["revision"] > old["card"]["revision"]
    assert len(analyzer.calls) == 1


async def test_shared_content_cache_binds_report_to_new_active_attachment(pg):
    job_id, first, analyzer, _, _ = await prepare(pg)
    old = await settle(pg)
    second_job = await pg.jobs.create(str(uuid4()), "Same bytes, another job")
    second = await upload(pg, second_job["id"])
    await pg.messages.send(second_job["id"], str(uuid4()), "Корпус подшипника")
    new = await settle(pg)
    assert first["sha256"] == second["sha256"]
    assert first["id"] != second["id"]
    assert new["card"]["stl_analysis"]["attachment_id"] == second["id"]
    assert new["card"]["stl_analysis"]["report"] == old["card"]["stl_analysis"]["report"]
    assert new["card"]["stl_analysis"]["report"]["file"]["path"] == first["id"]
    assert len(analyzer.calls) == 1


async def test_replacement_during_model_call_cannot_deliver_old_report(pg):
    job_id, old_attachment, analyzer, model, captured = await prepare(pg)
    replacement = []

    async def replace():
        replacement.append(await upload(pg, job_id, "open.stl"))

    model.callback = replace
    result = await settle(pg)
    assert result["card"]["stl_analysis"]["attachment_id"] == replacement[0]["id"]
    assert result["card"]["stl_analysis"]["attachment_id"] != old_attachment["id"]
    assert not captured  # replacement units are unconfirmed, so no stage-two delivery


async def test_units_change_during_model_call_cannot_deliver_old_report(pg):
    job_id, attachment, analyzer, model, captured = await prepare(pg)
    initial = await settle(pg)
    await pg.answers.answer(job_id, str(uuid4()), initial["revision"], {"geometry.units": "mm"})

    async def change_units():
        current = await pg.jobs.snapshot(job_id)
        await pg.answers.answer(
            job_id, str(uuid4()), current["job"]["revision"], {"geometry.units": "cm"}
        )

    model.callback = change_units
    current = await settle(pg)
    assert current["card"]["stl_analysis"]["report"] == analyzer.reports[(attachment["id"], "cm")]
    assert len(captured) == 1
    assert captured[0]["card"] == current["card"]


async def test_no_active_stl_has_explicit_null_analysis(pg):
    pg.pipeline.extraction.model = ModelDouble()
    job = await pg.jobs.create(str(uuid4()), "No STL")
    await pg.messages.send(job["id"], str(uuid4()), "Корпус")
    current = await settle(pg)
    assert current["card"]["stl_analysis"] is None
    assert "select_parameters" in current["card"]["blocked_actions"]


async def test_unavailable_analyzer_never_fabricates_report(pg):
    from src.backend.domain.errors import AppError

    job_id, _, _, _, captured = await prepare(pg)

    async def unavailable(*args):
        raise AppError("Авария процесса", "analyzer_crashed", 503)

    pg.files.analyze = unavailable
    current = await settle(pg)
    assert current["card"]["stl_analysis"] is None
    assert current["card"]["geometry"]["extents"] == []
    assert current["card"]["geometry"]["limitations"] == ["Авария процесса"]
    assert not captured


@pytest.mark.unit
@pytest.mark.parametrize("mutation", ["hash", "units", "file_type", "units_type", "missing"])
def test_binding_rejects_unrelated_measurement(mutation):
    from src.backend.domain.errors import AppError
    from src.backend.domain.models import Attachment
    from src.backend.domain.task_cards import bind_analysis

    attachment = Attachment(job_id="job", filename="box.stl", kind="stl", sha256="a" * 64, size=1)
    report = {"file": {"sha256": attachment.sha256}, "units": {"input_unit": "mm"}}
    changes = {
        "hash": {"file": {"sha256": "b" * 64}},
        "units": {"units": {"input_unit": "cm"}},
        "file_type": {"file": []},
        "units_type": {"units": None},
        "missing": {"file": {}},
    }
    report.update(changes[mutation])
    with pytest.raises(AppError, match="STL"):
        bind_analysis(attachment, "mm", report)


@pytest.mark.unit
@pytest.mark.parametrize("field", ["stl_analysis", "answers", "resolutions"])
def test_model_contract_rejects_server_owned_fields(field):
    from pydantic import ValidationError

    from src.backend.domain.models import InterpretationCard

    with pytest.raises(ValidationError, match="Extra inputs"):
        InterpretationCard.model_validate({"purpose": "Корпус", field: {}})

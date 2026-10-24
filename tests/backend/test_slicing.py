"""Slicing and the G-code check without STE Slicer: the plan of plugin calls, the check of a
written G-code and the MCP adapter against the stand-in of the plugin."""

import json
import math
import zipfile
from pathlib import Path

import pytest

from scripts.fake_ste_slicer import FakeSlicer
from src.backend.domain.parameters import ParameterSet
from src.backend.infrastructure.catalog import load_catalog
from src.backend.infrastructure.files import LocalFiles
from src.backend.infrastructure.slicer import McpSlicer, SlicerSettings, gcode_facts
from src.backend.slicing import build_plan, check_gcode, read_gcode
from src.backend.slicing.plan import euler_steps, scene_rotation

pytestmark = pytest.mark.unit
CATALOG = load_catalog(Path("knowledge/ste_5.2.4"), "hte530v5.2.4")
REASON = {"why": "профиль по умолчанию", "source": "default"}
BOX = Path("tests/fixtures/box.stl")


def parameter_set(**changes) -> ParameterSet:
    data = {
        "card_ref": {"job_id": "j", "revision": 1},
        "iteration": 1,
        "printer": "hte530v5.2.4",
        "printing_mode": {"value": "classic", **REASON},
        "quality": {"quality_type": "draft", **REASON},
        "materials": {"0": {"id": "enduse_petg", **REASON}},
        "settings": {
            "infill_sparse_density": {"value": 40, **REASON},
            "support_enable": {"value": False, **REASON},
        },
        "models": [
            {
                "id": "m1",
                "attachment_id": "att",
                "extruder": 0,
                "orientation_candidate": "o1",
                "transform": {
                    "rotation": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
                    "position": [-9.5, 0.0, 15.0],
                    "scale": [1, 1, 1],
                },
                **REASON,
            }
        ],
        "status": "proposed",
    }
    data.update(changes)
    return ParameterSet.model_validate(data)


def model(**transform) -> dict:
    placed = parameter_set().models[0].model_dump()
    placed["transform"].update(transform)
    return placed


def tools(calls) -> list[str]:
    return [call.tool for call in calls]


# -------------------------------------------------------------------- plan


def test_the_plan_applies_the_set_in_the_order_checked_on_windows():
    calls, unsupported = build_plan(parameter_set(), {"att": "/m/att.stl"}, "/r.gcode", "/p.3mf")
    assert tools(calls) == [
        "set_printer",
        "set_print_mode",
        "set_quality_profile",
        "set_material",
        "set_setting",
        "set_setting",
        "load_model",
        "move_model",
        "slice_model",
        "export_gcode",
        "save_project",
    ]
    assert calls[0].args == {"definition_id": "hte530v5.2.4"}
    assert calls[6].args == {"path": "/m/att.stl"}
    # The set's Y is the machine's Y, which is minus z of the scene.
    assert calls[7].args == {"x": -9.5, "z": -0.0, "model_index": 0}
    assert calls[-2].args == {"path": "/r.gcode"} and calls[-1].args == {"path": "/p.3mf"}
    assert unsupported == []


def test_axes_of_the_set_become_axes_of_the_y_up_scene():
    cos, sin = math.cos(math.radians(45)), math.sin(math.radians(45))

    def scene(rotation):
        return [(a, round(d, 6)) for a, d in (scene_rotation(*s) for s in euler_steps(rotation))]

    assert scene([[1, 0, 0], [0, 0, -1], [0, 1, 0]]) == [("x", 90.0)]
    # A turn about Z of the set turns the part on the plate: y of the scene.
    assert scene([[0, -1, 0], [1, 0, 0], [0, 0, 1]]) == [("y", 90.0)]
    # Y of the set is z of the scene with the opposite sign.
    assert scene([[cos, 0, sin], [0, 1, 0], [-sin, 0, cos]]) == [("z", -45.0)]


def test_a_gimbal_lock_rotation_is_still_the_same_rotation():
    rotation = [[0, 0, 1], [0, 1, 0], [-1, 0, 0]]
    steps = euler_steps(rotation)
    assert [axis for axis, _ in steps] == ["y"] and abs(steps[0][1] - 90) < 1e-9


def test_what_the_plugin_cannot_do_is_reported_not_sent():
    changes = {
        "materials": {"0": {"id": "enduse_petg", **REASON}, "1": {"id": "generic_pva", **REASON}},
        "settings": {"machine_width": {"value": 400, **REASON}},
        "models": [model(scale=[1, 2, 1])],
    }
    calls, unsupported = build_plan(parameter_set(**changes), {"att": "a.stl"}, "g", "p")
    assert {u.step for u in unsupported} == {
        "set_material[1]",
        "set_setting[machine_width]",
        "scale_model[0]",
    }
    assert "scale_model" not in tools(calls) and tools(calls).count("set_material") == 1


def test_a_list_setting_goes_to_the_slicer_as_its_string():
    changes = {"settings": {"infill_angles": {"value": [0, 90], **REASON}}}
    calls, _ = build_plan(parameter_set(**changes), {"att": "a.stl"}, "g", "p")
    assert next(c for c in calls if c.tool == "set_setting").args["value"] == "[0, 90]"


def test_a_model_without_its_file_stops_the_plan():
    with pytest.raises(KeyError):
        build_plan(parameter_set(), {}, "g", "p")


# -------------------------------------------------------------------- G-code


def gcode(layer=0.2, nozzle=230, bed=70, xs=(160.0, 190.0), layers=3, end=True, extra=()):
    lines = [";FLAVOR:Marlin", ";TIME:3720", ";Filament used: 1.5m", f";Layer height: {layer}"]
    lines += [f"M140 S{bed}", f"M190 S{bed}", f"M104 S{nozzle}", f"M109 S{nozzle}"]
    lines += [f";LAYER_COUNT:{layers}"]
    for number in range(layers):
        lines += [f";LAYER:{number}", ";TYPE:WALL-OUTER"]
        lines += [f"G1 X{x} Y150 Z{layer * (number + 1):.2f} E{number + 1}" for x in xs]
    lines += list(extra)
    if end:
        lines.append(";End of Gcode")
    return [line + "\n" for line in lines]


def checked(lines, pset=None):
    return check_gcode(read_gcode(lines), pset or parameter_set(), CATALOG, 1)


def test_a_good_gcode_passes_with_its_estimate():
    result = checked(gcode())
    assert result.result == "ok" and result.feedback.result == "ok"
    messages = [f.message for f in result.findings]
    assert "время печати 1 ч 2 мин" in messages and "слоёв 3" in messages


def test_a_cut_gcode_is_a_broken_file():
    result = checked(gcode(end=False))
    assert result.result == "apply_failed"
    assert [f.kind for f in result.findings if f.level == "error"] == ["file"]


def test_a_layer_height_other_than_the_profile_is_an_apply_error():
    result = checked(gcode(layer=0.1))
    errors = [f for f in result.findings if f.level == "error"]
    assert result.result == "apply_failed" and [e.key for e in errors] == ["layer_height"]
    assert result.feedback.result == "ok", "applying is not stage two's fault"


def test_a_requested_temperature_has_to_appear_in_the_gcode():
    pset = parameter_set(settings={"material_print_temperature": {"value": 240, **REASON}})
    assert checked(gcode(nozzle=230), pset).result == "apply_failed"
    first_layer = gcode(nozzle=240, extra=["M104 S235"])
    assert checked(first_layer, pset).result == "ok"


def test_a_model_off_the_bed_goes_back_to_selection_without_its_orientation():
    result = checked(gcode(xs=(330.0, 360.0)))
    assert result.result == "needs_changes" and result.feedback.result == "needs_changes"
    assert [(e.type, e.candidate) for e in result.feedback.exclude] == [("orientation", "o1")]


def test_supports_the_set_turned_off_are_an_apply_error():
    result = checked(gcode(extra=[";TYPE:SUPPORT", "G1 X170 Y150 E9"]))
    assert result.result == "apply_failed"
    assert any(f.key == "support_enable" for f in result.findings if f.level == "error")


def test_a_heated_bed_in_5d_is_a_warning():
    pset = parameter_set(printing_mode={"value": "cylindrical", **REASON})
    result = checked(gcode(), pset)
    assert result.result == "ok"
    assert [w.key for w in result.feedback.warnings] == ["material_bed_temperature"]


def test_written_settings_are_compared_with_the_set():
    payload = {
        "global_quality": "[general]\\nversion = 4\\n[values]\\ninfill_sparse_density = 25\\n"
    }
    result = checked(gcode(extra=[";SETTING_3 " + json.dumps(payload)]))
    errors = [f for f in result.findings if f.level == "error"]
    assert [e.key for e in errors] == ["infill_sparse_density"]


# -------------------------------------------------------------------- adapter


@pytest.fixture
def plugin(tmp_path):
    fake = FakeSlicer(tmp_path / "STE_AIAssistant")
    fake.start()
    yield fake
    fake.stop()


def adapter(tmp_path, folder: Path, host_folder: str = "") -> tuple[McpSlicer, LocalFiles]:
    files = LocalFiles(tmp_path / "files")
    files.path("att").write_bytes(BOX.read_bytes())
    return McpSlicer(files, SlicerSettings(folder, host_folder, "127.0.0.1")), files


async def test_the_adapter_slices_and_keeps_the_gcode_and_the_project(tmp_path, plugin):
    slicer, files = adapter(tmp_path, plugin.folder)
    report = await slicer.slice("job-r1-i1", parameter_set(), {"att": "att"})
    assert report.status == "sliced", report
    assert (report.gcode, report.project) == ("job-r1-i1.gcode", "job-r1-i1.3mf")
    assert report.folder == str(plugin.folder / "mosprom" / "job-r1-i1")
    assert report.print_time_seconds and report.material_meters
    # The plugin checks the Host header, which in Docker is not its own address.
    assert {h["Host"] for h in plugin.headers} == {f"127.0.0.1:{plugin.port}"}
    loaded = next(args for name, args in plugin.calls if name == "load_model")
    assert loaded["path"].endswith("mosprom/job-r1-i1/att.stl")
    result = check_gcode(gcode_facts(files, report.gcode), parameter_set(), CATALOG, 1)
    assert result.result == "ok", result.findings
    with zipfile.ZipFile(files.path(report.project)) as archive:
        assert archive.namelist() == ["SteSlicer/stand_in.json"]
    assert report.warnings, "the plugin has no reset, so earlier settings may remain"


async def test_the_scene_is_cleared_and_settings_reset_before_each_run(tmp_path):
    fake = FakeSlicer(tmp_path / "STE_AIAssistant", reset_tool=True)
    fake.start()
    try:
        slicer, _ = adapter(tmp_path, fake.folder)
        await slicer.slice("a", parameter_set(), {"att": "att"})
        await slicer.slice("b", parameter_set(), {"att": "att"})
        assert len(fake.models) == 1
        assert [name for name, _ in fake.calls].count("reset_settings") == 2
    finally:
        fake.stop()


async def test_a_value_the_slicer_wrote_differently_is_reported(tmp_path, plugin):
    original = plugin.tool_set_setting

    def clamping(key, value, reason=""):
        original(key, value, reason)
        return f"{key}: 20 -> 30" if key == "infill_sparse_density" else f"{key}: x -> {value}"

    plugin.tool_set_setting = clamping
    slicer, _ = adapter(tmp_path, plugin.folder)
    report = await slicer.slice("r", parameter_set(), {"att": "att"})
    assert [(c.key, c.requested, c.written) for c in report.clamped] == [
        ("infill_sparse_density", 40, 30)
    ]


async def test_a_failed_call_stops_the_run_with_a_plain_message(tmp_path):
    fake = FakeSlicer(tmp_path / "STE_AIAssistant", fail_on="slice_model")
    fake.start()
    try:
        slicer, _ = adapter(tmp_path, fake.folder)
        report = await slicer.slice("r", parameter_set(), {"att": "att"})
    finally:
        fake.stop()
    assert (report.status, report.message) == ("failed", "Слайсер не нарезал модель")
    assert report.steps[-1].error == "slice_model failed on purpose" and report.gcode is None


async def test_no_running_slicer_is_reported_as_unavailable(tmp_path):
    slicer, _ = adapter(tmp_path, tmp_path / "nothing")
    report = await slicer.slice("r", parameter_set(), {"att": "att"})
    assert (report.status, report.message) == (
        "unavailable",
        "STE Slicer с плагином AI Assistant не запущен",
    )


async def test_a_stale_server_file_is_reported_as_unavailable(tmp_path, plugin):
    port = plugin.port
    plugin._server.shutdown()
    plugin._server.server_close()
    (plugin.folder / "server.json").write_text(json.dumps({"port": port, "token": "t"}))
    slicer, _ = adapter(tmp_path, plugin.folder)
    report = await slicer.slice("r", parameter_set(), {"att": "att"})
    assert (report.status, report.message) == ("unavailable", "STE Slicer не отвечает")
    plugin._server = None


async def test_paths_go_to_the_slicer_as_it_sees_the_shared_folder(tmp_path, plugin):
    host = r"C:\Users\fedor\Documents\STE_AIAssistant"
    slicer, _ = adapter(tmp_path, plugin.folder, host)
    report = await slicer.slice("r", parameter_set(), {"att": "att"})
    # The stand-in cannot open a Windows path, which is what the plan sent.
    loaded = next(args for name, args in plugin.calls if name == "load_model")
    assert loaded["path"] == host + r"\mosprom\r\att.stl"
    assert report.status == "failed" and report.message == "Слайсер не загрузил модель"

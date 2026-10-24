"""STE Slicer through the MCP server of its AI Assistant plugin (branch ``feat/ste-plugin``).

The plugin listens on 127.0.0.1 with a port and a token it writes to
``Documents/STE_AIAssistant/server.json`` and reads and writes files by paths of its own
machine. The worker shares that folder with it: models go to and results come from
``mosprom/<run>`` inside it. In Docker the folder is mounted and ``host_dir`` is the same
folder as the slicer sees it.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
from dataclasses import dataclass
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath
from typing import Any

import httpx

from ..domain.parameters import ParameterSet
from ..domain.slicing import CallOutcome, Clamped, SlicerCall, SliceReport
from ..slicing import GcodeFacts, build_plan, read_gcode
from .files import LocalFiles

logger = logging.getLogger(__name__)
EXCHANGE = "mosprom"
# Slicing waits up to 300 s inside the plugin; any other call answers within seconds.
SLICE_SECONDS = 330
CALL_SECONDS = 60
RESET_TOOL = "reset_settings"
OVERRUN = "Слайсер не ответил вовремя"
# What the chat says when a call fails; the plugin's own error stays in the report.
FAILED = {
    "list_models": "Слайсер не очистил стол",
    "load_model": "Слайсер не загрузил модель",
    "rotate_model": "Слайсер не повернул модель",
    "scale_model": "Слайсер не масштабировал модель",
    "move_model": "Слайсер не поставил модель на место",
    "slice_model": "Слайсер не нарезал модель",
    "export_gcode": "Слайсер не сохранил G-code",
    "save_project": "Слайсер не сохранил проект",
}


@dataclass(frozen=True)
class SlicerSettings:
    folder: Path
    host_folder: str
    host: str
    # How long a run may hold the slicer; waiting for another job's run is not counted.
    run_seconds: float


class SlicerUnavailable(Exception):
    pass


class CallFailed(Exception):
    pass


class McpSlicer:
    def __init__(self, files: LocalFiles, settings: SlicerSettings):
        self.files, self.settings = files, settings
        # One slicer, one scene: runs of different jobs wait for each other.
        self._lock = asyncio.Lock()
        # Runs a caller stopped waiting for, kept until the plugin is done with them.
        self._runs: set[asyncio.Task[None]] = set()

    async def slice(
        self, run: str, parameter_set: ParameterSet, models: dict[str, str]
    ) -> SliceReport:
        """The caller waits until the run ends, overruns ``run_seconds`` once it holds the
        slicer, or is cancelled by a stop or an edit. The run itself keeps the slicer until
        the call the plugin is busy with returns, so the next run never meets a busy plugin."""
        answer: asyncio.Future[SliceReport] = asyncio.get_running_loop().create_future()
        stop = asyncio.Event()
        task = asyncio.create_task(self._exclusive(run, parameter_set, models, answer, stop))
        self._runs.add(task)
        task.add_done_callback(self._runs.discard)
        try:
            return await asyncio.shield(answer)
        finally:
            stop.set()
            answer.cancel()

    async def _exclusive(
        self,
        run: str,
        parameter_set: ParameterSet,
        models: dict[str, str],
        answer: asyncio.Future[SliceReport],
        stop: asyncio.Event,
    ) -> None:
        async with self._lock:
            if stop.is_set():
                return
            session = asyncio.create_task(self._session(run, parameter_set, models, stop))
            done, _ = await asyncio.wait({session}, timeout=self.settings.run_seconds)
            if not done:
                stop.set()
                _settle(answer, SliceReport(status="failed", message=OVERRUN))
            try:
                _settle(answer, await session)
            except Exception as exc:
                if answer.done():
                    logger.exception("Slicer run %s failed after its caller left", run)
                else:
                    answer.set_exception(exc)

    async def _session(
        self, run: str, parameter_set: ParameterSet, models: dict[str, str], stop: asyncio.Event
    ) -> SliceReport:
        try:
            port, token = await asyncio.to_thread(self._server)
        except SlicerUnavailable as exc:
            return SliceReport(status="unavailable", message=str(exc))
        folder = self.settings.folder / EXCHANGE / run
        try:
            await asyncio.to_thread(self._place_models, folder, models)
        except OSError as exc:
            logger.warning("Models of %s did not reach %s: %r", run, folder, exc)
            return SliceReport(status="failed", message="Не удалось передать модель слайсеру")
        async with self._client(port, token) as client:
            try:
                return await self._run(client, run, folder, parameter_set, models, stop)
            except SlicerUnavailable as exc:
                return SliceReport(status="unavailable", message=str(exc))

    async def call(self, name: str, arguments: dict[str, Any]) -> Any:
        """One tool of the plugin outside a run, for a check by hand."""
        port, token = await asyncio.to_thread(self._server)
        async with self._lock, self._client(port, token) as client:
            return await self._tool(client, name, arguments)

    def _client(self, port: int, token: str) -> httpx.AsyncClient:
        # The plugin checks the Host header, which in Docker is not its own address.
        headers = {"Authorization": f"Bearer {token}", "Host": f"127.0.0.1:{port}"}
        return httpx.AsyncClient(base_url=f"http://{self.settings.host}:{port}", headers=headers)

    def _server(self) -> tuple[int, str]:
        path = self.settings.folder / "server.json"
        try:
            server = json.loads(path.read_text(encoding="utf-8"))
            return int(server["port"]), str(server["token"])
        except FileNotFoundError:
            raise SlicerUnavailable("STE Slicer с плагином AI Assistant не запущен") from None
        except (OSError, ValueError, KeyError, TypeError) as exc:
            logger.warning("server.json of the plugin is unreadable: %s", exc)
            raise SlicerUnavailable("Не удалось подключиться к STE Slicer") from None

    def _place_models(self, folder: Path, models: dict[str, str]) -> None:
        """The slicer picks the reader by the extension, which stored files lack."""
        folder.mkdir(parents=True, exist_ok=True)
        for attachment_id, key in models.items():
            shutil.copyfile(self.files.path(key), folder / f"{attachment_id}.stl")

    async def _run(
        self,
        client: httpx.AsyncClient,
        run: str,
        folder: Path,
        parameter_set: ParameterSet,
        models: dict[str, str],
        stop: asyncio.Event,
    ) -> SliceReport:
        try:
            tools = {tool["name"] for tool in (await _rpc(client, "tools/list", {}))["tools"]}
        except httpx.TransportError as exc:
            logger.warning("STE Slicer at %s does not answer: %r", client.base_url, exc)
            raise SlicerUnavailable("STE Slicer не отвечает") from None
        except (CallFailed, KeyError, TypeError) as exc:
            logger.warning("The plugin did not list its tools: %r", exc)
            raise SlicerUnavailable("Плагин AI Assistant не отвечает") from None
        host_models = {a: self._host(run, f"{a}.stl") for a in models}
        try:
            calls, unsupported = build_plan(
                parameter_set,
                host_models,
                self._host(run, "result.gcode"),
                self._host(run, "project.3mf"),
            )
        except KeyError:
            message = "В наборе модель, которой нет среди файлов задания"
            return SliceReport(status="failed", message=message)
        report = SliceReport(
            status="sliced",
            message="",
            unsupported=unsupported,
            folder=self._host(run),
        )
        prelude = [SlicerCall(step="clear_scene", tool="list_models", args={})]
        if RESET_TOOL in tools:
            prelude.append(SlicerCall(step="reset_settings", tool=RESET_TOOL, args={}))
        else:
            report.warnings.append(
                "плагин не сбрасывает настройки: изменённые прошлыми нарезками ключи, "
                "которых нет в наборе, остались в слайсере"
            )
        for call in [*prelude, *calls]:
            if stop.is_set():
                report.status, report.message = "failed", OVERRUN
                return report
            try:
                result = await self._call(client, call)
            except (CallFailed, httpx.TransportError) as exc:
                error = str(exc) or type(exc).__name__
                report.steps.append(
                    CallOutcome(step=call.step, tool=call.tool, ok=False, error=error)
                )
                report.status = "failed"
                report.message = FAILED.get(call.tool, "Слайсер не применил параметры")
                logger.warning("Slicer step %s of %s failed: %s", call.step, run, error)
                return report
            report.steps.append(CallOutcome(step=call.step, tool=call.tool, ok=True))
            _note(report, call, result)
        try:
            report.gcode, report.project = await asyncio.to_thread(self._keep, run, folder)
        except OSError as exc:
            logger.warning("The results of %s are not in %s: %r", run, folder, exc)
            report.status, report.message = (
                "failed",
                "Не удалось забрать G-code и проект у слайсера",
            )
            return report
        report.message = "G-code и проект сохранены"
        return report

    async def _call(self, client: httpx.AsyncClient, call: SlicerCall) -> Any:
        if call.step == "clear_scene":
            # Models of an earlier run would be sliced along with this one.
            for _ in await self._tool(client, "list_models", {}):
                await self._tool(client, "delete_model", {"model_index": 0})
            return None
        timeout = SLICE_SECONDS if call.tool == "slice_model" else CALL_SECONDS
        return await self._tool(client, call.tool, call.args, timeout)

    async def _tool(
        self,
        client: httpx.AsyncClient,
        name: str,
        arguments: dict[str, Any],
        timeout: float = CALL_SECONDS,
    ) -> Any:
        result = await _rpc(client, "tools/call", {"name": name, "arguments": arguments}, timeout)
        content = result.get("content") or []
        text = content[0].get("text", "") if content else ""
        if result.get("isError"):
            raise CallFailed(text)
        if text.lstrip().startswith(("{", "[")):
            try:
                return json.loads(text)
            except ValueError:
                pass
        return text

    def _keep(self, run: str, folder: Path) -> tuple[str, str]:
        """Copies the chat serves; the originals stay where the slicer saved them."""
        kept = []
        for name, key in (("result.gcode", f"{run}.gcode"), ("project.3mf", f"{run}.3mf")):
            shutil.copyfile(folder / name, self.files.path(key))
            kept.append(key)
        return kept[0], kept[1]

    def _host(self, *parts: str) -> str:
        """A path inside the shared folder as the slicer sees it."""
        if not self.settings.host_folder:
            return str(self.settings.folder.joinpath(EXCHANGE, *parts))
        windows = re.match(r"^[A-Za-z]:|^\\\\", self.settings.host_folder)
        base: PurePath = (PureWindowsPath if windows else PurePosixPath)(self.settings.host_folder)
        return str(base.joinpath(EXCHANGE, *parts))


async def _rpc(
    client: httpx.AsyncClient, method: str, params: dict[str, Any], timeout: float = CALL_SECONDS
) -> dict[str, Any]:
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    response = await client.post("/mcp", json=body, timeout=timeout)
    if response.status_code != 200:
        raise CallFailed(f"HTTP {response.status_code}")
    try:
        reply = response.json()
    except ValueError:
        raise CallFailed("ответ плагина не JSON") from None
    if not isinstance(reply, dict):
        raise CallFailed("ответ плагина не объект JSON-RPC")
    if "error" in reply:
        error = reply["error"]
        raise CallFailed(str(error.get("message") if isinstance(error, dict) else error))
    if not isinstance(reply.get("result"), dict):
        raise CallFailed("в ответе плагина нет результата")
    return reply["result"]


def _settle(answer: asyncio.Future[SliceReport], report: SliceReport) -> None:
    if not answer.done():
        answer.set_result(report)


def _note(report: SliceReport, call: SlicerCall, result: Any) -> None:
    """What a call's answer says about the run: a clamped value or the slicer's estimate."""
    if call.tool == "slice_model" and isinstance(result, dict):
        report.print_time_seconds = result.get("print_time_seconds")
        report.material_grams = result.get("material_grams")
        report.material_meters = result.get("material_meters")
    if call.tool != "set_setting" or not isinstance(result, str) or " -> " not in result:
        return
    written = _typed(result.rsplit(" -> ", 1)[1].strip(), call.args["value"])
    if written != call.args["value"]:
        report.clamped.append(
            Clamped(key=call.args["key"], requested=call.args["value"], written=written)
        )


def _typed(text: str, requested: Any) -> Any:
    """The written value in the type of the requested one, as the plugin prints it."""
    if isinstance(requested, bool):
        return text.lower() in ("true", "1")
    if isinstance(requested, int | float):
        try:
            number = float(text)
        except ValueError:
            return text
        return int(number) if isinstance(requested, int) and number.is_integer() else number
    return text


def gcode_facts(files: LocalFiles, key: str) -> GcodeFacts:
    with files.path(key).open(encoding="utf-8", errors="replace") as stream:
        return read_gcode(stream)

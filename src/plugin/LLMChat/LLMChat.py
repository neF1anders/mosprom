import html
import json
import os
import re
import threading
import time
import urllib.request

from PyQt5.QtCore import QObject, QTimer, QUrl, pyqtSignal, pyqtSlot

from UM.Application import Application
from UM.Extension import Extension
from UM.Logger import Logger
from UM.PluginRegistry import PluginRegistry

from .scenarios import BASE_PROMPT, SCENARIOS
from .tools import SlicerTools, TOOL_SPECS

MAX_STEPS = 14
DEFAULT_URL = "https://api.timeweb.ai/v1"
DEFAULT_MODEL = "dashscope/qwen3.8-flash"


def _to_html(text):
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    text = html.escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    return text.replace("\n", "<br>")


class LLMChat(Extension, QObject):
    replyReceived = pyqtSignal(str, arguments=["answer"])
    errorReceived = pyqtSignal(str, arguments=["message"])
    statusReceived = pyqtSignal(str, arguments=["text"])
    changesUpdated = pyqtSignal(str, arguments=["html"])
    toolRequested = pyqtSignal(str, str)

    def __init__(self, parent=None):
        QObject.__init__(self, parent)
        Extension.__init__(self)
        self._view = None
        self._tools = SlicerTools()
        self._history = []
        self._scenario = 0
        self._attached = None
        self._busy = False
        self._tool_event = threading.Event()
        self._tool_result = ""
        self.toolRequested.connect(self._onToolRequested)
        prefs = Application.getInstance().getPreferences()
        prefs.addPreference("llm_chat/base_url", DEFAULT_URL)
        prefs.addPreference("llm_chat/api_key", "")
        prefs.addPreference("llm_chat/model", DEFAULT_MODEL)
        self.setMenuName("AI")
        self.addMenuItem("Open chat", self.showChat)
        self.addMenuItem("Self-test (no LLM)", self.selfTest)
        if os.environ.get("LLMCHAT_OPEN"):
            QTimer.singleShot(20000, self.showChat)
        if os.environ.get("LLMCHAT_SELFTEST"):
            QTimer.singleShot(25000, self.selfTest)

    # ---------- window ----------
    def showChat(self):
        if self._view is None:
            path = os.path.join(PluginRegistry.getInstance().getPluginPath(self.getPluginId()), "LLMChat.qml")
            self._view = Application.getInstance().createQmlComponent(path, {"manager": self})
        if self._view is not None:
            self._view.show()

    @pyqtSlot(str, str, str)
    def saveSettings(self, base_url, api_key, model):
        prefs = Application.getInstance().getPreferences()
        prefs.setValue("llm_chat/base_url", base_url.strip())
        if api_key.strip():
            prefs.setValue("llm_chat/api_key", api_key.strip())
        prefs.setValue("llm_chat/model", model.strip())

    @pyqtSlot(result=str)
    def getBaseUrl(self):
        return Application.getInstance().getPreferences().getValue("llm_chat/base_url")

    @pyqtSlot(result=str)
    def getModel(self):
        return Application.getInstance().getPreferences().getValue("llm_chat/model")

    @pyqtSlot(result=bool)
    def hasKey(self):
        return bool(Application.getInstance().getPreferences().getValue("llm_chat/api_key"))

    @pyqtSlot(result="QVariantList")
    def scenarioTitles(self):
        return [s["title"] for s in SCENARIOS]

    @pyqtSlot(int, result=str)
    def selectScenario(self, index):
        self._scenario = index
        return SCENARIOS[index]["prompt"]

    @pyqtSlot(str)
    def attachFile(self, url):
        path = QUrl(url).toLocalFile() or url
        self._attached = path
        self._tools.tool_load_model(path)
        self.statusReceived.emit("Файл прикреплён и загружается: " + os.path.basename(path))

    @pyqtSlot()
    def resetChat(self):
        self._history = []
        self._tools.changes = []
        self.changesUpdated.emit("")

    # ---------- chat ----------
    @pyqtSlot(str)
    def send(self, text):
        if self._busy:
            self.errorReceived.emit("Подожди ответа.")
            return
        if self._attached:
            text += "\n[Прикреплён файл модели: %s, он уже загружен на стол]" % self._attached
            self._attached = None
        self._history.append({"role": "user", "content": text})
        self._tools.changes = []
        self.changesUpdated.emit("")
        self._busy = True
        threading.Thread(target=self._chat_loop, daemon=True).start()

    def _config(self):
        prefs = Application.getInstance().getPreferences()
        return prefs.getValue("llm_chat/base_url").rstrip("/"), prefs.getValue("llm_chat/api_key"), prefs.getValue("llm_chat/model")

    def _post(self, messages):
        base, key, model = self._config()
        if not key:
            raise RuntimeError("Нет API-ключа: впиши его в поле API key и нажми Save.")
        body = {"model": model, "messages": messages,
                "tools": [{"type": "function", "function": spec} for spec in TOOL_SPECS]}
        req = urllib.request.Request(
            base + "/chat/completions", data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + key})
        with urllib.request.urlopen(req, timeout=180) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _chat_loop(self):
        try:
            system = BASE_PROMPT + "\nСценарий: " + SCENARIOS[self._scenario]["focus"]
            for _ in range(MAX_STEPS):
                data = self._post([{"role": "system", "content": system}] + self._history)
                msg = data["choices"][0]["message"]
                calls = msg.get("tool_calls") or []
                entry = {"role": "assistant", "content": msg.get("content") or ""}
                if calls:
                    entry["tool_calls"] = calls
                self._history.append(entry)
                if not calls:
                    self.replyReceived.emit(_to_html(entry["content"]))
                    return
                for call in calls:
                    name = call["function"]["name"]
                    try:
                        args = json.loads(call["function"].get("arguments") or "{}")
                    except ValueError:
                        args = {}
                    self.statusReceived.emit("Инструмент: %s" % name)
                    result = self._run_tool(name, args)
                    self.changesUpdated.emit(self._tools.changes_html())
                    self._history.append({"role": "tool", "tool_call_id": call["id"], "content": result})
            self.errorReceived.emit("Слишком много шагов, остановился.")
        except Exception as e:
            Logger.log("e", "LLM chat failed: %s", e)
            self.errorReceived.emit(str(e))
        finally:
            self._busy = False

    # ---------- tools (worker side) ----------
    def _dispatch(self, name, args):
        self._tool_event.clear()
        self.toolRequested.emit(name, json.dumps(args))
        if not self._tool_event.wait(90):
            return "ERROR: tool timeout"
        return self._tool_result

    def _run_tool(self, name, args):
        if name == "save_project":
            # the 3MF workspace writer hops to the Qt thread itself and would deadlock if called from it
            try:
                return str(self._tools.tool_save_project(**args))
            except Exception as e:
                return "ERROR: %s" % e
        if name == "slice_and_export":
            started = self._dispatch("start_slice", {})
            if started.startswith("ERROR"):
                return started
            return self._wait_slice(args.get("path"))
        return self._dispatch(name, args)

    def _wait_slice(self, path):
        begin = time.time()
        while time.time() - begin < 300:
            state = self._dispatch("poll_slice", {})
            if state == "done":
                return self._dispatch("export_gcode", {"path": path} if path else {})
            if state == "error":
                return "ERROR: slicing failed (check the model, the printer and the STE Slicer license)"
            if self._tools.slice_state is None and time.time() - begin > 25:
                return "ERROR: slicing did not start (check the license activation window of STE Slicer)"
            time.sleep(2)
        return "ERROR: slicing timeout"

    # ---------- tools (main thread side) ----------
    @pyqtSlot(str, str)
    def _onToolRequested(self, name, args_json):
        try:
            method = getattr(self._tools, "tool_" + name, None) or getattr(self._tools, name)
            result = method(**json.loads(args_json))
        except Exception as e:
            Logger.logException("e", "Tool %s failed", name)
            result = "ERROR: %s" % e
        self._tool_result = str(result)
        self._tool_event.set()

    # ---------- self-test without LLM ----------
    def selfTest(self):
        log = lambda title, value: Logger.log("i", "LLMChat selftest %s: %s", title, value)
        t = self._tools
        steps = [("get_state", lambda: t.tool_get_state()),
                 ("set_setting", lambda: t.tool_set_setting("layer_height", 0.2, "test")),
                 ("set_print_mode", lambda: t.tool_set_print_mode("classic", "test")),
                 ("list_materials", lambda: t.tool_list_materials(limit=5))]
        cube = os.path.join(PluginRegistry.getInstance().getPluginPath(self.getPluginId()), "selftest_cube.stl")
        if os.path.isfile(cube):
            steps.append(("load_model", lambda: t.tool_load_model(cube)))
        for title, fn in steps:
            try:
                log(title, fn())
            except Exception as e:
                Logger.logException("e", "selftest %s failed", title)
        QTimer.singleShot(5000, self._selfTestStage2)

    def _selfTestStage2(self):
        log = lambda title, value: Logger.log("i", "LLMChat selftest %s: %s", title, value)
        t = self._tools
        for title, fn in [("get_state", lambda: t.tool_get_state()),
                          ("arrange_models", lambda: t.tool_arrange_models()),
                          ("rotate_model", lambda: t.tool_rotate_model("x", 90, 0, "test")),
                          ("start_slice", lambda: t.start_slice())]:
            try:
                log(title, fn())
            except Exception:
                Logger.logException("e", "selftest %s failed", title)
        self._selftest_wait = 0
        QTimer.singleShot(3000, self._selfTestStage3)

    def _selfTestStage3(self):
        t = self._tools
        self._selftest_wait += 3
        state = t.poll_slice()
        if state in ("waiting", "restarted") and self._selftest_wait < 150:
            QTimer.singleShot(3000, self._selfTestStage3)
            return
        Logger.log("i", "LLMChat selftest slice state: %s", state)
        if state == "done":
            try:
                Logger.log("i", "LLMChat selftest export_gcode: %s", t.tool_export_gcode())
            except Exception:
                Logger.logException("e", "selftest export_gcode failed")
            threading.Thread(target=self._selfTestSave, daemon=True).start()

    def _selfTestSave(self):
        try:
            Logger.log("i", "LLMChat selftest save_project: %s", self._tools.tool_save_project())
        except Exception:
            Logger.logException("e", "selftest save_project failed")

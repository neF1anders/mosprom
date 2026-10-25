import base64
import json
import os
import re
import threading

from UM.Logger import Logger

from . import llm, mcp, settings, tools
from .scenarios import BASE_PROMPT, SCENARIOS

MAX_STEPS = 16
RESULT_LIMIT = 4000
MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


def _clean(text):
    return re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()


class Chat(object):
    def __init__(self):
        self._lock = threading.Lock()
        self._events = []
        self._history = []
        self._uploads = {}
        self._busy = False

    # опрос событий
    def add_event(self, kind, **data):
        with self._lock:
            data.update({"id": len(self._events), "type": kind})
            self._events.append(data)

    def events_since(self, after):
        with self._lock:
            return {"events": self._events[after:], "next": len(self._events), "busy": self._busy}

    # загрузка файлов
    def add_upload(self, upload_id, name, path):
        extension = os.path.splitext(name)[1].lower()
        kind = "image" if extension in MIME else "model"
        self._uploads[upload_id] = {"name": name, "path": path, "kind": kind}
        return kind

    def reset(self):
        with self._lock:
            self._events = []
            self._history = []
            self._uploads = {}
        tools.SESSION.changes = []

    # цикл диалога
    def send(self, text, upload_ids, scenario):
        with self._lock:
            if self._busy:
                raise RuntimeError("Wait for the answer to the previous message")
            self._busy = True
        try:
            self._start(text, upload_ids, scenario)
        except Exception:
            # поток не стартовал
            with self._lock:
                self._busy = False
            raise

    def _start(self, text, upload_ids, scenario):
        notes = []
        images = []
        for upload_id in upload_ids:
            upload = self._uploads.get(upload_id)
            if upload is None:
                continue
            if upload["kind"] == "model":
                notes.append(
                    "[Прикреплена модель: %s. Загрузи её через load_model.]" % upload["path"]
                )
            else:
                images.append(upload)
        content = text + ("\n" + "\n".join(notes) if notes else "")
        if images:
            parts = [{"type": "text", "text": content}]
            for image in images:
                try:
                    with open(image["path"], "rb") as stream:
                        encoded = base64.b64encode(stream.read()).decode("ascii")
                except (IOError, OSError) as error:
                    raise ValueError(
                        "The attached file %s cannot be read: %s" % (image["name"], error)
                    )
                mime = MIME[os.path.splitext(image["name"])[1].lower()]
                parts.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:%s;base64,%s" % (mime, encoded)},
                    }
                )
            content = parts
        self._history.append({"role": "user", "content": content})
        self.add_event(
            "user",
            text=text,
            attachments=[
                {"name": self._uploads[i]["name"], "kind": self._uploads[i]["kind"]}
                for i in upload_ids
                if i in self._uploads
            ],
        )
        tools.SESSION.changes = []
        thread = threading.Thread(target=self._loop, args=(scenario,))
        thread.daemon = True
        thread.start()

    def _loop(self, scenario):
        try:
            config = settings.load()
            focus = SCENARIOS[scenario]["focus"] if 0 <= scenario < len(SCENARIOS) else ""
            system = BASE_PROMPT + ("\nСценарий: " + focus if focus else "")
            specs = mcp.list_tools()
            for _ in range(MAX_STEPS):
                message = llm.chat(
                    config["base_url"],
                    config["api_key"],
                    config["model"],
                    [{"role": "system", "content": system}] + self._history,
                    specs,
                )
                calls = message.get("tool_calls") or []
                entry = {"role": "assistant", "content": message.get("content") or ""}
                if calls:
                    entry["tool_calls"] = calls
                self._history.append(entry)
                if not calls:
                    self.add_event("assistant", text=_clean(entry["content"]))
                    return
                if entry["content"]:
                    self.add_event("assistant", text=_clean(entry["content"]))
                for call in calls:
                    self._run_call(call)
            self.add_event("error", text="Слишком много шагов, остановился.")
        except Exception as error:
            Logger.log("w", "AI Assistant chat failed: %s", error)
            self.add_event("error", text=str(error))
        finally:
            with self._lock:
                self._busy = False
            self.add_event("done")

    def _run_call(self, call):
        name = call["function"]["name"]
        try:
            arguments = json.loads(call["function"].get("arguments") or "{}")
        except ValueError:
            arguments = {}
        self.add_event("tool_call", name=name, arguments=arguments)
        result = mcp.call_tool(name, arguments)
        text = result["content"][0]["text"]
        self.add_event("tool_result", name=name, ok=not result["isError"], text=text[:1500])
        self.add_event("changes", changes=list(tools.SESSION.changes))
        self._history.append(
            {"role": "tool", "tool_call_id": call.get("id", name), "content": text[:RESULT_LIMIT]}
        )

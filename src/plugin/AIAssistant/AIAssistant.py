import os
import webbrowser

from UM.Application import Application
from UM.Extension import Extension
from UM.Logger import Logger

from .agent import settings
from .agent.server import AssistantServer


class AIAssistant(Extension):
    def __init__(self):
        super().__init__()
        app = Application.getInstance()
        prefs = app.getPreferences()
        prefs.addPreference(settings.PREF_BASE_URL, settings.DEFAULT_BASE_URL)
        prefs.addPreference(settings.PREF_API_KEY, "")
        prefs.addPreference(settings.PREF_MODEL, settings.DEFAULT_MODEL)
        self._server = None
        self.setMenuName("AI Assistant")
        self.addMenuItem("Open chat", self.showChat)
        if os.environ.get("AIASSISTANT_AUTOSTART"):
            app.engineCreatedSignal.connect(self._ensureServer)

    def _ensureServer(self):
        if self._server is None:
            self._server = AssistantServer()
            self._server.start()
            Logger.log("i", "AI Assistant listening on %s", self._server.url())
        return self._server

    def showChat(self):
        webbrowser.open(self._ensureServer().url())

import webbrowser

from UM.Application import Application
from UM.Extension import Extension
from UM.Logger import Logger
from UM.Message import Message

from .agent import launch, settings
from .agent.server import AssistantServer

NO_CONFIG = ("Приложение StereotechAI ещё не настроено. В папке проекта запустите "
             "python scripts\\bootstrap.py и docker compose up -d, затем откройте пункт меню снова")
NO_SERVER = ("Сервер плагина не запустился, поэтому слайсер не сможет нарезать модели из приложения. "
             "Подробности в журнале STE Slicer. Откройте пункт меню снова, чтобы попробовать ещё раз")


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
        self.addMenuItem("Открыть StereotechAI", self.showApp)
        self.addMenuItem("Чат плагина", self.showChat)
        # The app slices through the MCP server, so it runs whenever the slicer is open.
        app.engineCreatedSignal.connect(self._ensureServer)

    def _ensureServer(self):
        """The running server, or None when it could not start; the next call tries again."""
        if self._server is None:
            server = AssistantServer()
            try:
                server.start()
            except Exception:
                Logger.logException("e", "AI Assistant server did not start")
                return None
            self._server = server
            Logger.log("i", "AI Assistant listening on %s", server.url())
        return self._server

    def showApp(self):
        if self._ensureServer() is None:
            Message(text=NO_SERVER, title="AI Assistant").show()
        url = launch.app_url()
        if url is None:
            Logger.log("w", "AI Assistant has no %s, the app link cannot be built", launch.CONFIG_NAME)
            Message(text=NO_CONFIG, title="AI Assistant").show()
            return
        webbrowser.open(url)

    def showChat(self):
        server = self._ensureServer()
        if server is None:
            Message(text=NO_SERVER, title="AI Assistant").show()
            return
        webbrowser.open(server.url())

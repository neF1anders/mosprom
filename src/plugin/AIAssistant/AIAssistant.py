import webbrowser

from UM.Application import Application
from UM.Extension import Extension
from UM.Logger import Logger
from UM.Message import Message

from .agent import launch, settings, sidecar
from .agent.server import AssistantServer

NO_CONFIG = (
    "Приложение StereotechAI ещё не настроено. В папке проекта запустите "
    "python scripts\\bootstrap.py и сервер приложения по инструкции из README, "
    "затем откройте пункт меню снова"
)
NO_BACKEND = "Приложение StereotechAI не запустилось ({}). Откройте пункт меню снова, чтобы попробовать ещё раз"
NO_SERVER = (
    "Сервер плагина не запустился, поэтому слайсер не сможет нарезать модели из приложения. "
    "Подробности в журнале STE Slicer. Откройте пункт меню снова, чтобы попробовать ещё раз"
)


class AIAssistant(Extension):
    def __init__(self):
        super().__init__()
        app = Application.getInstance()
        prefs = app.getPreferences()
        prefs.addPreference(settings.PREF_BASE_URL, settings.DEFAULT_BASE_URL)
        prefs.addPreference(settings.PREF_API_KEY, "")
        prefs.addPreference(settings.PREF_MODEL, settings.DEFAULT_MODEL)
        self._server = None
        self._sidecar = sidecar.Sidecar() if sidecar.available() else None
        self.setMenuName("AI Assistant")
        self.addMenuItem("Открыть StereotechAI", self.showApp)
        self.addMenuItem("Чат плагина", self.showChat)
        # сервер нужен всегда
        app.engineCreatedSignal.connect(self._ensureServer)

    def _ensureServer(self):
        """Запущенный сервер или None."""
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

    def _ensureBackend(self):
        """Запускает встроенный бэкенд переносной сборки."""
        if self._sidecar is None:
            return True
        try:
            self._sidecar.start()
        except Exception as error:
            Logger.logException("e", "AI Assistant backend did not start")
            Message(text=NO_BACKEND.format(error), title="AI Assistant").show()
            return False
        return True

    def showApp(self):
        if self._ensureServer() is None:
            Message(text=NO_SERVER, title="AI Assistant").show()
        if not self._ensureBackend():
            return
        url = launch.app_url(self._sidecar)
        if url is None:
            Logger.log(
                "w", "AI Assistant has no %s, the app link cannot be built", launch.CONFIG_NAME
            )
            Message(text=NO_CONFIG, title="AI Assistant").show()
            return
        webbrowser.open(url)

    def showChat(self):
        server = self._ensureServer()
        if server is None:
            Message(text=NO_SERVER, title="AI Assistant").show()
            return
        webbrowser.open(server.url())

import importlib
import importlib.util
import os
import sys
import threading
import types
import unittest
from unittest import mock

AGENT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "src", "plugin", "AIAssistant", "agent"
)


class Signal(object):
    def __init__(self):
        self._slots = []

    def connect(self, slot):
        self._slots.append(slot)

    def disconnect(self, slot):
        self._slots.remove(slot)

    def emit(self, *args):
        for slot in list(self._slots):
            slot(*args)


class BackendState(object):
    """Состояния бэкенда слайсера."""

    NotStarted = 1
    Processing = 2
    Done = 3
    Error = 4
    Disabled = 5


class Process(object):
    """Процесс движка нарезки."""

    def __init__(self):
        self.returncode = None

    def poll(self):
        return self.returncode

    def wait(self):
        return self.returncode

    def terminate(self):
        if self.returncode is None:
            self.returncode = 1


class EngineBackend(object):
    """Заглушка бэкенда с движком."""

    def __init__(self, scene, plugin_id="CuraEngineBackend"):
        self.scene = scene
        self.plugin_id = plugin_id
        self._current = False
        self._restart = False
        self._process = None
        self.backendQuit = Signal()
        self.backendStateChange = Signal()
        self.processingProgress = Signal()
        self.backendQuit.connect(self._onBackendQuit)
        self.engines = []
        self.sent_to = []

    def getPluginId(self):
        return self.plugin_id

    def setCurrent(self, current=True):
        self._current = current

    def _createSocket(self):
        # сокет запускает движок
        self._process = Process()
        self.engines.append(self._process)

    def _terminate(self):
        if self._process is not None:
            self._process.terminate()
            self._process = None

    def _onBackendQuit(self):
        if not self._current:
            return
        if not self._restart:
            if self._process:
                self._process = None

    def engine_exits(self):
        """Движок завершается после нарезки."""
        self._process.returncode = 0
        self.backendQuit.emit()

    def forceSlice(self):
        if self._process is None:
            self._createSocket()
        self.backendStateChange.emit(BackendState.Processing)
        engine = self._process
        self.sent_to.append(engine)
        if engine.poll() is None:
            # живой движок отвечает
            self.scene.gcode_dict = {0: [";gcode"]}
            self.backendStateChange.emit(BackendState.Done)
            self.engine_exits()
        # мёртвый молчит

    def run_for_5d(self):
        """Нарезка 5D этим движком."""
        self._terminate()
        self._createSocket()
        self.sent_to.append(self._process)
        self.engine_exits()


class CylindricalBackend(object):
    """Бэкенд 5D без движка."""

    def __init__(self):
        self.backendStateChange = Signal()
        self.processingProgress = Signal()

    def getPluginId(self):
        return "CylindricalBackend"

    def setCurrent(self, current=True):
        pass

    def forceSlice(self):
        self.backendStateChange.emit(BackendState.Processing)


class Duration(object):
    days = 0
    hours = 0
    minutes = 1
    seconds = 5

    def getDisplayString(self):
        return "00:01:05"


class App(object):
    """Приложение с текущим бэкендом."""

    def __init__(self):
        self.scene = types.SimpleNamespace(gcode_dict={})
        self.cura = EngineBackend(self.scene)
        self.cylindrical = CylindricalBackend()
        self.backend = None
        self.main = threading.current_thread()
        self.set_mode("classic")

    def set_mode(self, mode):
        """Смена режима и бэкенда."""
        new = self.cura if mode == "classic" else self.cylindrical
        if self.backend is not None:
            self.backend.setCurrent(False)
        self.backend = new
        new.setCurrent(True)

    def getBackend(self):
        return self.backend

    def getMainThread(self):
        return self.main

    def getMachineErrorChecker(self):
        return types.SimpleNamespace(needToWaitForResult=False)

    def getController(self):
        return types.SimpleNamespace(getScene=lambda: self.scene)

    def getPrintInformation(self):
        return types.SimpleNamespace(
            currentPrintTime=Duration(), materialWeights=[2.5], materialLengths=[0.8]
        )


class Application(object):
    instance = None

    @classmethod
    def getInstance(cls):
        return cls.instance


def _stubs():
    modules = {}

    def add(name, **names):
        module = types.ModuleType(name)
        module.__dict__.update(names)
        modules[name] = module

    for package in (
        "PyQt5",
        "UM",
        "UM.Backend",
        "UM.Math",
        "UM.Operations",
        "UM.Scene",
        "UM.Scene.Iterator",
        "UM.Settings",
    ):
        add(package)
    add("PyQt5.QtCore", QUrl=object)
    add("UM.Application", Application=Application)
    add("UM.Backend.Backend", BackendState=BackendState)
    add(
        "UM.Logger",
        Logger=types.SimpleNamespace(log=lambda *args: None, logException=lambda *args: None),
    )
    add("UM.Math.Quaternion", Quaternion=object)
    add("UM.Math.Vector", Vector=object)
    for operation in (
        "RemoveSceneNodeOperation",
        "RotateOperation",
        "ScaleOperation",
        "TranslateOperation",
    ):
        add("UM.Operations." + operation, **{operation: object})
    add("UM.Scene.Iterator.DepthFirstIterator", DepthFirstIterator=lambda root: iter(()))
    add("UM.Settings.ContainerRegistry", ContainerRegistry=object)
    return modules


def _load_tools():
    name = "aiassistant_agent_under_test"
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(AGENT, "__init__.py"), submodule_search_locations=[AGENT]
    )
    package = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, _stubs()):
        sys.modules[name] = package
        spec.loader.exec_module(package)
        return importlib.import_module(name + ".tools")


tools = _load_tools()


class EngineAfter5D(unittest.TestCase):
    def setUp(self):
        self.app = App()
        Application.instance = self.app
        tools.SESSION.__init__()
        patches = [
            mock.patch.object(tools, "_models", lambda: [object()]),
            mock.patch.object(tools.time, "sleep", lambda seconds: None),
            mock.patch.object(tools, "SLICE_SECONDS", 5),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def slice_5d(self):
        self.app.set_mode("cylindrical_full")
        tools._start_slice()
        self.app.cura.run_for_5d()
        self.app.cylindrical.backendStateChange.emit(BackendState.Done)

    def test_the_slicer_keeps_the_exited_engine_after_5d(self):
        """Сигнал теряется в 5D."""
        self.slice_5d()
        cura = self.app.cura
        engine = cura._process
        self.assertIsNotNone(engine)
        self.assertEqual(engine.poll(), 0)
        self.app.set_mode("classic")
        tools._hook_backend()
        cura.forceSlice()  # прежнее поведение
        self.assertIs(cura.sent_to[-1], engine)
        self.assertEqual(tools.SESSION.slice_state, BackendState.Processing)

    def test_3d_after_5d_slices_on_a_new_engine(self):
        self.slice_5d()
        exited = self.app.cura._process
        self.app.set_mode("classic")
        result = tools.slice_model()
        self.assertEqual(result["state"], "done")
        self.assertEqual(result["print_time_seconds"], 65)
        engine = self.app.cura.sent_to[-1]
        self.assertIsNot(engine, exited)
        self.assertEqual(len(self.app.cura.engines), 2)

    def test_3d_after_3d_and_5d_after_5d_are_left_alone(self):
        for _ in range(2):
            self.assertEqual(tools.slice_model()["state"], "done")
        self.assertEqual(len(self.app.cura.engines), 2)  # движок на нарезку
        self.slice_5d()
        self.slice_5d()
        self.assertEqual(len(self.app.cura.engines), 4)

    def test_5d_after_3d(self):
        self.assertEqual(tools.slice_model()["state"], "done")
        self.slice_5d()
        self.assertEqual(self.app.cura.sent_to[-1].poll(), 0)  # закрыт после 5D

    def test_a_backend_without_its_own_engine_is_not_touched(self):
        tools._release_ended_engine(self.app.cylindrical)
        cura = self.app.cura
        cura._createSocket()
        tools._release_ended_engine(cura)  # живой остаётся
        self.assertIsNone(cura._process.poll())

    def test_an_engine_the_slicer_does_not_let_go_fails_at_once(self):
        self.slice_5d()
        self.app.set_mode("classic")
        self.app.cura._restart = True  # процесс не отпущен
        with self.assertRaises(tools.ToolError) as caught:
            tools.slice_model()
        self.assertIn("Restart STE Slicer", str(caught.exception))
        self.assertEqual(len(self.app.cura.sent_to), 1)  # мёртвому не шлём

    def test_a_running_helper_process_is_not_waited_for(self):
        self.slice_5d()
        self.app.set_mode("classic")
        self.app.cura._glicer_process = Process()  # иначе ждёт CliParser
        with self.assertRaises(tools.ToolError):
            tools._start_slice()

    def test_slicing_with_an_exited_engine_fails_fast(self):
        """Пропавший движок даёт ошибку."""
        self.slice_5d()
        self.app.set_mode("classic")
        with mock.patch.object(tools, "_release_ended_engine", lambda backend: None):
            with self.assertRaises(tools.ToolError) as caught:
                tools.slice_model()
        self.assertIn("engine", str(caught.exception))

    def test_an_engine_whose_quit_arrives_is_not_lost(self):
        cura = self.app.cura
        tools._hook_backend()
        cura._createSocket()
        tools.SESSION.slice_state = BackendState.Processing
        cura._process.returncode = 0  # сигнал не доставлен
        self.assertEqual(tools._poll_slice(), "waiting")
        cura.backendQuit.emit()
        self.assertEqual(tools._poll_slice(), "waiting")
        self.assertEqual(tools.SESSION.engine_lost_polls, 0)


if __name__ == "__main__":
    unittest.main()

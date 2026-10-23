import threading

from UM.Application import Application
from UM.Logger import Logger


def run_on_main(func, timeout=60):
    """Run func on the Qt main thread and return its result.

    The slicer scene, settings and backend may only be touched from the main thread; the HTTP server
    works in other threads and hands the work over with Application.callLater.
    """
    app = Application.getInstance()
    if threading.current_thread() is app.getMainThread():
        return func()
    box = {}
    done = threading.Event()

    def call():
        try:
            box["result"] = func()
        except Exception as error:
            if not getattr(error, "expected", False):
                Logger.logException("w", "Tool call failed on the main thread")
            box["error"] = error
        finally:
            done.set()

    app.callLater(call)
    if not done.wait(timeout):
        raise RuntimeError("STE Slicer did not respond within %d s" % timeout)
    if "error" in box:
        raise box["error"]
    return box["result"]

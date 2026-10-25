import http.client
import json
import math
import os
import shutil
import socket
import struct
import tempfile
import time
import unittest

from tests.e2e.test_ai_assistant import ENABLED, SERVER_JSON

BOX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fixtures", "box.stl")
SLICE_SECONDS = float(os.environ.get("ENGINE_E2E_SLICE_SECONDS", "240"))
PRINTER = "hte530v5.2.4"
# середина стола
POSITION_X = {"classic": -9.5, "cylindrical_full": 0.0}


def ring_stl(outer=12.0, inner=5.0, height=10.0, segments=48):
    """Кольцо STL для 5D."""
    triangles = []
    for i in range(segments):
        a, b = 2 * math.pi * i / segments, 2 * math.pi * (i + 1) / segments
        o0, o1 = (
            (outer * math.cos(a), outer * math.sin(a)),
            (outer * math.cos(b), outer * math.sin(b)),
        )
        i0, i1 = (
            (inner * math.cos(a), inner * math.sin(a)),
            (inner * math.cos(b), inner * math.sin(b)),
        )
        for z, up in ((0.0, False), (height, True)):
            quad = [(o0[0], o0[1], z), (o1[0], o1[1], z), (i1[0], i1[1], z), (i0[0], i0[1], z)]
            if not up:
                quad.reverse()
            triangles += [(quad[0], quad[1], quad[2]), (quad[0], quad[2], quad[3])]
        for p0, p1, outward in ((o0, o1, True), (i0, i1, False)):
            quad = [
                (p0[0], p0[1], 0.0),
                (p1[0], p1[1], 0.0),
                (p1[0], p1[1], height),
                (p0[0], p0[1], height),
            ]
            if not outward:
                quad.reverse()
            triangles += [(quad[0], quad[1], quad[2]), (quad[0], quad[2], quad[3])]
    data = [b"ring".ljust(80, b" "), struct.pack("<I", len(triangles))]
    for triangle in triangles:
        data.append(struct.pack("<3f", 0.0, 0.0, 0.0))
        for point in triangle:
            data.append(struct.pack("<3f", *point))
        data.append(b"\0\0")
    return b"".join(data)


class Hung(Exception):
    pass


class Plugin(object):
    def __init__(self):
        with open(SERVER_JSON) as stream:
            info = json.load(stream)
        self.port = info["port"]
        self.token = info["token"]

    def tool(self, name, arguments=None, timeout=60):
        body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        }
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout)
        try:
            connection.request(
                "POST",
                "/mcp",
                json.dumps(body),
                {"Content-Type": "application/json", "X-Token": self.token},
            )
            raw = connection.getresponse().read()
        except socket.timeout:
            raise Hung("%s gave no answer in %d s" % (name, timeout))
        finally:
            connection.close()
        result = json.loads(raw.decode("utf-8"))["result"]
        text = result["content"][0]["text"]
        if result["isError"]:
            raise AssertionError("%s failed: %s" % (name, text))
        return text


@unittest.skipUnless(ENABLED, "needs AIASSISTANT_E2E=1 and a running STE Slicer with the plugin")
class EngineAfter5D(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plugin = Plugin()
        cls.directory = tempfile.mkdtemp()
        cls.ring = os.path.join(cls.directory, "ring.stl")
        with open(cls.ring, "wb") as stream:
            stream.write(ring_stl())

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.directory, ignore_errors=True)

    def slice(self, mode):
        """Нарезка как в конвейере."""
        plugin = self.plugin
        for _ in json.loads(plugin.tool("list_models")):
            plugin.tool("delete_model", {"model_index": 0})
        plugin.tool("set_printer", {"definition_id": PRINTER})
        plugin.tool("reset_settings")
        plugin.tool("set_print_mode", {"mode": mode, "reason": "e2e engine after 5D"})
        if mode == "cylindrical_full":
            plugin.tool(
                "set_setting",
                {
                    "key": "cylindrical_mode_base_diameter",
                    "value": 10,
                    "reason": "bore of the e2e ring",
                },
            )
        plugin.tool(
            "load_model",
            {"path": self.ring if mode == "cylindrical_full" else os.path.abspath(BOX)},
        )
        plugin.tool("move_model", {"x": POSITION_X[mode], "z": 0.0})
        began = time.time()
        try:
            status = json.loads(plugin.tool("slice_model", timeout=SLICE_SECONDS))
        except Hung as hung:
            self.fail("%s slicing hung: %s" % (mode, hung))
        path = os.path.join(self.directory, "%s-%d.gcode" % (mode, int(began)))
        gcode = json.loads(plugin.tool("export_gcode", {"path": path}))
        with open(path, encoding="utf-8", errors="replace") as stream:
            printing_mode = [line for line in stream if line.startswith(";PRINTING_MODE")]
        print(
            "%s: %s in %.0f s, %d bytes of G-code, %s"
            % (mode, status["state"], time.time() - began, gcode["bytes"], printing_mode[:1])
        )
        self.assertEqual(status["state"], "done")
        self.assertGreater(gcode["bytes"], 1000)
        return status

    def run_order(self, *modes):
        for mode in modes:
            self.slice(mode)

    def test_3d_5d_3d(self):
        self.run_order("classic", "cylindrical_full", "classic")

    def test_5d_5d(self):
        self.run_order("cylindrical_full", "cylindrical_full")

    def test_3d_3d(self):
        self.run_order("classic", "classic")


if __name__ == "__main__":
    unittest.main()

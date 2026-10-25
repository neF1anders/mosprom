import base64
import http.client
import json
import os
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

SERVER_JSON = os.path.join(os.path.expanduser("~"), "Documents", "STE_AIAssistant", "server.json")
ENABLED = os.environ.get("AIASSISTANT_E2E") == "1" and os.path.isfile(SERVER_JSON)
REQUIRED_TOOLS = {
    "get_state",
    "list_printers",
    "set_printer",
    "list_materials",
    "set_material",
    "list_quality_profiles",
    "set_quality_profile",
    "save_profile",
    "set_print_mode",
    "search_settings",
    "get_setting",
    "set_setting",
    "load_model",
    "list_models",
    "move_model",
    "rotate_model",
    "scale_model",
    "delete_model",
    "arrange_models",
    "analyze_orientation",
    "orient_model",
    "open_project",
    "remove_printer",
    "reset_settings",
    "slice_model",
    "get_slicing_status",
    "export_gcode",
    "save_project",
}
CUBE_FACES = [
    ((0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)),
    ((0, 0, 1), (0, 1, 1), (1, 1, 1), (1, 0, 1)),
    ((0, 0, 0), (0, 0, 1), (1, 0, 1), (1, 0, 0)),
    ((1, 0, 0), (1, 0, 1), (1, 1, 1), (1, 1, 0)),
    ((1, 1, 0), (1, 1, 1), (0, 1, 1), (0, 1, 0)),
    ((0, 1, 0), (0, 1, 1), (0, 0, 1), (0, 0, 0)),
]


def cube_stl(size=20):
    lines = ["solid cube"]
    for a, b, c, d in CUBE_FACES:
        for triangle in ((a, b, c), (a, c, d)):
            lines.append("facet normal 0 0 0\n outer loop")
            lines.extend(
                "  vertex %g %g %g" % (p[0] * size, p[1] * size, p[2] * size) for p in triangle
            )
            lines.append(" endloop\nendfacet")
    lines.append("endsolid cube")
    return "\n".join(lines).encode("ascii")


class Client(object):
    def __init__(self):
        with open(SERVER_JSON) as stream:
            info = json.load(stream)
        self.port = info["port"]
        self.token = info["token"]

    def request(self, method, path, body=None, headers=None, token=True):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=330)
        merged = {"Content-Type": "application/json"}
        if token:
            merged["X-Token"] = self.token
        merged.update(headers or {})
        connection.request(method, path, json.dumps(body) if body is not None else None, merged)
        response = connection.getresponse()
        raw = response.read()
        connection.close()
        return response.status, raw

    def json(self, method, path, body=None):
        status, raw = self.request(method, path, body)
        return status, json.loads(raw.decode("utf-8"))

    def mcp(self, method, params=None, request_id=1):
        status, data = self.json(
            "POST",
            "/mcp",
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}},
        )
        self_status = status
        assert self_status == 200, data
        return data

    def tool(self, name, arguments=None):
        result = self.mcp("tools/call", {"name": name, "arguments": arguments or {}})["result"]
        text = result["content"][0]["text"]
        return result["isError"], text


class FakeLLM(object):
    """Скриптовый сервер, совместимый с OpenAI."""

    def __init__(self, script):
        self.requests = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                outer.requests.append(json.loads(self.rfile.read(length).decode("utf-8")))
                reply = script[min(len(outer.requests), len(script)) - 1]
                body = json.dumps({"choices": [{"message": reply}]}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def url(self):
        return "http://127.0.0.1:%d/v1" % self.httpd.server_address[1]

    def close(self):
        self.httpd.shutdown()


def call(call_id, name, arguments):
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


@unittest.skipUnless(ENABLED, "needs AIASSISTANT_E2E=1 and a running STE Slicer with the plugin")
class AssistantE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = Client()

    def test_page_is_served_without_a_token(self):
        status, raw = self.client.request("GET", "/", token=False)
        self.assertEqual(status, 200)
        self.assertIn("AI помощник печати", raw.decode("utf-8"))

    def test_api_needs_the_token_and_a_local_host(self):
        self.assertEqual(self.client.request("GET", "/api/config", token=False)[0], 401)
        self.assertEqual(
            self.client.request("GET", "/api/config", headers={"Host": "evil.example"})[0], 403
        )

    def test_mcp_handshake_and_tool_list(self):
        init = self.client.mcp("initialize")["result"]
        self.assertEqual(init["serverInfo"]["name"], "ste-slicer-ai-assistant")
        names = {t["name"] for t in self.client.mcp("tools/list")["result"]["tools"]}
        self.assertTrue(REQUIRED_TOOLS <= names, REQUIRED_TOOLS - names)
        self.assertIn("error", self.client.mcp("no/such/method"))

    def test_settings_roundtrip_and_guards(self):
        self.assertFalse(self.client.tool("set_printer", {"definition_id": "hte530v5.2.4"})[0])
        self.assertFalse(
            self.client.tool("set_setting", {"key": "layer_height", "value": 0.2, "reason": "e2e"})[
                0
            ]
        )
        self.assertEqual(
            json.loads(self.client.tool("get_setting", {"key": "layer_height"})[1])["value"], 0.2
        )
        found = json.loads(
            self.client.tool("search_settings", {"query": "infill_sparse_density"})[1]
        )
        self.assertTrue(any(row["key"] == "infill_sparse_density" for row in found))
        self.assertTrue(
            self.client.tool("set_setting", {"key": "machine_width", "value": 1, "reason": "e2e"})[
                0
            ]
        )
        self.assertTrue(
            self.client.tool(
                "set_setting", {"key": "no_such_setting", "value": 1, "reason": "e2e"}
            )[0]
        )
        self.assertTrue(
            self.client.tool("set_print_mode", {"mode": "discrete", "reason": "e2e"})[0]
        )
        self.assertFalse(
            self.client.tool("set_print_mode", {"mode": "classic", "reason": "e2e"})[0]
        )
        self.assertEqual(json.loads(self.client.tool("get_state")[1])["print_mode"], "classic")

    def test_model_to_gcode_and_project(self):
        directory = tempfile.mkdtemp()
        stl = os.path.join(directory, "cube.stl")
        with open(stl, "wb") as stream:
            stream.write(cube_stl())
        self.client.tool("set_printer", {"definition_id": "hte530v5.2.4"})
        self.client.tool("set_print_mode", {"mode": "classic", "reason": "e2e"})
        for index in range(len(json.loads(self.client.tool("list_models")[1]))):
            self.client.tool("delete_model", {"model_index": 0})
        error, text = self.client.tool("load_model", {"path": stl})
        self.assertFalse(error, text)
        models = json.loads(self.client.tool("list_models")[1])
        self.assertEqual(len(models), 1)
        self.assertAlmostEqual(models[0]["size_mm"]["x"], 20, delta=0.5)
        rows = json.loads(self.client.tool("analyze_orientation")[1])
        self.assertEqual(len(rows), 6)
        self.assertFalse(
            self.client.tool("orient_model", {"orientation": "best", "reason": "e2e"})[0]
        )
        error, text = self.client.tool("slice_model")
        self.assertFalse(error, text)
        status = json.loads(text)
        self.assertEqual(status["state"], "done")
        self.assertGreater(status["print_time_seconds"], 0)
        gcode = json.loads(
            self.client.tool("export_gcode", {"path": os.path.join(directory, "result.gcode")})[1]
        )
        self.assertGreater(gcode["bytes"], 1000)
        project = json.loads(
            self.client.tool("save_project", {"path": os.path.join(directory, "project.3mf")})[1]
        )
        self.assertGreater(project["bytes"], 1000)
        error, text = self.client.tool("open_project", {"path": project["path"]})
        self.assertFalse(error, text)
        reopened = json.loads(text)
        self.assertEqual((reopened["opened_as"], len(reopened["models"])), ("project", 1))

    def test_chat_runs_tools_and_explains(self):
        fake = FakeLLM(
            [
                {"role": "assistant", "content": "", "tool_calls": [call("c1", "get_state", {})]},
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        call(
                            "c2",
                            "set_setting",
                            {
                                "key": "infill_sparse_density",
                                "value": 30,
                                "reason": "нагрузка на деталь",
                            },
                        )
                    ],
                },
                {"role": "assistant", "content": "Заполнение 30%: деталь под нагрузкой."},
            ]
        )
        try:
            status, _ = self.client.json(
                "POST",
                "/api/config",
                {"base_url": fake.url(), "api_key": "test-key", "model": "fake", "persist": False},
            )
            self.assertEqual(status, 200)
            self.client.json("POST", "/api/reset", {})
            picture = base64.b64encode(b"\x89PNG\r\n\x1a\n").decode("ascii")
            status, upload = self.client.json(
                "POST", "/api/upload", {"name": "part.png", "data": picture}
            )
            self.assertEqual((status, upload["kind"]), (200, "image"))
            status, _ = self.client.json(
                "POST",
                "/api/chat",
                {"text": "Кронштейн под нагрузку", "uploads": [upload["id"]], "scenario": 0},
            )
            self.assertEqual(status, 200)
            events, after = [], 0
            deadline = time.time() + 60
            while time.time() < deadline and not any(e["type"] == "done" for e in events):
                time.sleep(0.5)
                data = self.client.json("GET", "/api/events?after=%d" % after)[1]
                events.extend(data["events"])
                after = data["next"]
        finally:
            fake.close()
            self.client.json("POST", "/api/config", {"forget_session": True})
        kinds = [e["type"] for e in events]
        self.assertIn("done", kinds, events)
        self.assertEqual(
            [e["name"] for e in events if e["type"] == "tool_call"], ["get_state", "set_setting"]
        )
        self.assertTrue(all(e["ok"] for e in events if e["type"] == "tool_result"), events)
        change = [e for e in events if e["type"] == "changes"][-1]["changes"][0]
        self.assertEqual((change["name"], change["new"]), ("infill_sparse_density", 30))
        self.assertIn("30%", [e for e in events if e["type"] == "assistant"][-1]["text"])
        first = fake.requests[0]
        image_parts = [p for p in first["messages"][-1]["content"] if p["type"] == "image_url"]
        self.assertEqual(len(image_parts), 1)
        self.assertTrue(REQUIRED_TOOLS <= {t["function"]["name"] for t in first["tools"]})


if __name__ == "__main__":
    unittest.main()

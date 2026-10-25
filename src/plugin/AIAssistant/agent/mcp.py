import json

from UM.Logger import Logger

from . import tools

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "ste-slicer-ai-assistant", "version": "0.1.0"}


def list_tools():
    return [tools.TOOLS[name].spec() for name in sorted(tools.TOOLS)]


def call_tool(name, arguments):
    """Вызывает инструмент и возвращает результат."""
    try:
        result = tools.call(name, arguments)
        text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
        return {"content": [{"type": "text", "text": text}], "isError": False}
    except tools.ToolError as error:
        return {"content": [{"type": "text", "text": str(error)}], "isError": True}
    except Exception as error:
        Logger.logException("w", "Tool %s failed", name)
        return {
            "content": [{"type": "text", "text": "Internal error: %s" % error}],
            "isError": True,
        }


def _error(request_id, code, message):
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def handle(request):
    """Обрабатывает один JSON-RPC запрос."""
    if not isinstance(request, dict) or request.get("jsonrpc") != "2.0" or "method" not in request:
        return _error(
            request.get("id") if isinstance(request, dict) else None, -32600, "Invalid Request"
        )
    request_id = request.get("id")
    method = request["method"]
    params = request.get("params") or {}
    if "id" not in request:
        return None
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO,
            },
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": list_tools()}}
    if method == "tools/call":
        name = params.get("name")
        if name not in tools.TOOLS:
            return _error(request_id, -32602, "Unknown tool: %s" % name)
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": call_tool(name, params.get("arguments")),
        }
    return _error(request_id, -32601, "Method not found: %s" % method)

#!/usr/bin/env python3
"""Один вызов инструмента плагина через MCP: python mcp_call.py <инструмент> ['{"арг": 1}'] [--server-json путь]
Например: get_state, list_models, analyze_orientation, get_slicing_status."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from apply_parameter_set import McpClient, ApplyError


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    server = None
    if "--server-json" in argv:
        server = argv[argv.index("--server-json") + 1]
        args = [a for a in args if a != server]
    if not args:
        print(__doc__)
        return 2
    payload = json.loads(args[1]) if len(args) > 1 else {}
    try:
        result = McpClient(server).call(args[0], payload)
    except ApplyError as error:
        print("ОШИБКА:", error)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2) if not isinstance(result, str) else result)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

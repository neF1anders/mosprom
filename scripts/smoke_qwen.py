"""Opt-in provider checks using synthetic, non-confidential inputs."""

import asyncio
import base64
import io
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image, ImageDraw

from src.backend.agents.tools import ConvertArgs
from src.backend.config import Settings
from src.backend.infrastructure.qwen import QwenClient

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "convert_units",
            "description": "Точный перевод величины между единицами",
            "parameters": ConvertArgs.model_json_schema(),
        },
    }
]


async def main():
    settings = Settings()
    client = QwenClient(settings.qwen_base_url, settings.qwen_model, settings.qwen_api_key)
    image = Image.new("RGB", (256, 256), "white")
    ImageDraw.Draw(image).rectangle((50, 50, 200, 200), fill="red")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    cases = {
        "text": [{"role": "user", "content": "Ответь одним словом готов"}],
        "vision": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Какого цвета квадрат? Ответь одним словом."},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": "data:image/png;base64,"
                            + base64.b64encode(buffer.getvalue()).decode()
                        },
                    },
                ],
            }
        ],
        "tools": [
            {
                "role": "user",
                "content": "Обязательно вызови convert_units и переведи 2.5 inch в mm.",
            }
        ],
        "context_8000_estimate": [
            {
                "role": "user",
                "content": "Тестовые данные\n"
                + ("Свойство материала проверяется по источнику. " * 600)
                + "\nОтветь одним словом готов",
            }
        ],
    }
    output = {}
    for name, messages in cases.items():
        start = time.monotonic()
        try:
            reply = await asyncio.wait_for(
                client.complete(
                    messages, TOOLS if name == "tools" else [], agent="smoke", thinking=True
                ),
                120,
            )
            output[name] = {
                "ok": True,
                "seconds": round(time.monotonic() - start, 2),
                "content": reply.content,
                "tool_calls": reply.tool_calls,
                "finish_reason": reply.finish_reason,
                "reasoning": reply.reasoning[:300],
                "usage": reply.usage,
            }
        except Exception as exc:
            output[name] = {
                "ok": False,
                "seconds": round(time.monotonic() - start, 2),
                "error": type(exc).__name__,
            }
        print(name, output[name]["ok"], flush=True)
    await client.close()
    Path("artifacts/qwen-smoke.json").write_text(json.dumps(output, ensure_ascii=False, indent=2))


asyncio.run(main())

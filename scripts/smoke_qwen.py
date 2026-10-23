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

from src.backend.config import Settings
from src.backend.infrastructure.qwen import QwenClient
from src.backend.services.tools import TOOL_SCHEMAS


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
                "content": "Обязательно вызови search_knowledge с query плотность, material_id proto_pla, property density.",
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
            answer = await asyncio.wait_for(
                client.complete(messages, TOOL_SCHEMAS if name == "tools" else []), 45
            )
            output[name] = {
                "ok": True,
                "seconds": round(time.monotonic() - start, 2),
                "response": answer,
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

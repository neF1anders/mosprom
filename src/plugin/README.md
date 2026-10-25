# AI Assistant: плагин для STE Slicer

Плагин делает две вещи. Пункт меню «AI Assistant → Открыть StereotechAI» запускает приложение и открывает его чат в браузере. Сервер MCP поверх API слайсера даёт приложению инструменты: выбрать принтер, режим 3D/5D, профиль, материал и настройки, загрузить и сориентировать модель, нарезать её и сохранить G-code и проект `.3mf`.

Проверено на STE Slicer 7.10.12 (Windows). Код совместим с Python 3.5, на нём работает слайсер.

## Установка

Готовая сборка с приложением лежит в релизе репозитория, порядок установки описан в [README](../../README.md) и [PORTABLE.md](../../docs/PORTABLE.md).

1. Папка `AIAssistant` кладётся в `%APPDATA%\steslicer\7.10\plugins` (папку конфигурации открывает «Справка → Показать папку конфигурации»).
2. Сервер плагина стартует вместе со слайсером, слушает только `127.0.0.1` и пишет порт и токен в `Documents\STE_AIAssistant\server.json`.
3. «AI Assistant → Открыть StereotechAI» запускает приложение из `AIAssistant\runtime` и открывает его чат по одноразовой ссылке. Без встроенного приложения ссылку строит `Documents\STE_AIAssistant\mosprom.json`, его пишет `python scripts\bootstrap.py`.

Адрес API модели, имя модели и ключ вводятся в окне чата приложения при первом запуске и хранятся в `runtime\data\model.json`. В исходниках ключа нет.

## Инструменты

- **Принтер, профиль, материал:** `get_state`, `list_printers`, `set_printer` (по умолчанию Stereotech Hybrid 530 V5.2.4, `hte530v5.2.4`), `list_materials`, `set_material`, `list_quality_profiles`, `set_quality_profile`, `save_profile`, `reset_settings`.
- **Режим печати:** `set_print_mode`, только `classic` (3D), `cylindrical` (5D Spiral), `cylindrical_full` (5D).
- **Настройки (около 640):** `search_settings`, `get_setting`, `set_setting` (глобальные и уровня экструдера, значения вне диапазона подрезаются; `machine_*` недоступны).
- **Модели:** `load_model`, `open_project`, `list_models`, `move_model`, `rotate_model`, `scale_model`, `delete_model`, `arrange_models`, `analyze_orientation`, `orient_model`.
- **Слайсинг и результат:** `slice_model`, `get_slicing_status` (прогресс, время печати, расход материала), `export_gcode`, `save_project`.

## MCP

Эндпойнт `POST /mcp` (JSON-RPC 2.0): `initialize`, `tools/list`, `tools/call`. Нужны заголовки `Authorization: Bearer <токен>` и `Host: 127.0.0.1:<порт>`, порт и токен лежат в `Documents\STE_AIAssistant\server.json`.

## Ограничения

- 5D-слайсинг требует активированной лицензии STE Slicer (10 дней).
- Слайсер падает, если очищать сцену во время нарезки; инструменты перед этим останавливают слайсинг.
- Оценка времени и материала это оценка слайсера, а не измерение печати.
- Инструменты выполняются по одному. Если идёт нарезка, следующий вызов ждёт до 50 с и потом отвечает, что слайсер занят.
- `slice_model` укладывается в 900 с вместе с ожиданием проверки настроек слайсера. Перед каждым запуском нарезки плагин ждёт конца этой проверки, иначе слайсер падает с `KeyError: 0`.
- G-code сохраняется штатным писателем слайсера, со строкой `;PRINTING_MODE` и блоком `;SETTING_3`.

## Проверка (E2E)

Запустите слайсер, подождите появления `Documents\STE_AIAssistant\server.json` и выполните из корня репозитория:

```powershell
$env:AIASSISTANT_E2E = "1"
python -m unittest tests.e2e.test_ai_assistant -v
```

Без `AIASSISTANT_E2E=1` тесты пропускаются, в CI и в обычном `pytest` тоже. Они очищают стол и меняют настройки активного принтера, поэтому во время задачи приложения их не запускать.

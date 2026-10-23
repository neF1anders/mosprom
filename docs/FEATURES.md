# Реестр фич

Только реализованные возможности основного решения. Новую фичу и её E2E-проверку добавляем вместе; при удалении фичи удаляем строку.

| ID | Что умеет пользователь | E2E-проверка |
| --- | --- | --- |
| PLUGIN-CHAT | Открывает чат плагина в браузере из меню Extensions → AI Assistant; страница отдаётся локальным сервером, API закрыт токеном и проверкой Host | `tests/e2e/test_ai_assistant.py`: `test_page_is_served_without_a_token`, `test_api_needs_the_token_and_a_local_host` |
| PLUGIN-MCP | Подключает MCP-клиент к плагину (`initialize`, `tools/list`, `tools/call`) и видит инструменты слайсера | `test_mcp_handshake_and_tool_list` |
| PLUGIN-SETTINGS | Меняет принтер, режим печати 3D/5D и настройки слайсера через инструменты; недопустимые значения и режимы отклоняются | `test_settings_roundtrip_and_guards` |
| PLUGIN-SLICE | Загружает модель, анализирует и меняет ориентацию, нарезает, сохраняет G-code и проект `.3mf`, открывает проект обратно | `test_model_to_gcode_and_project` |
| PLUGIN-LLM-CHAT | Пишет задачу в чат (с картинкой), LLM вызывает инструменты, пользователь видит вызовы, список изменений и ответ | `test_chat_runs_tools_and_explains` |

Вики в `research/wiki/` — справочные материалы и в этот реестр не входит.

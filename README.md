# mosprom

Основное решение — ассистент-технолог для STE Slicer. Первый реализованный модуль — [анализатор STL](docs/STL_ANALYSIS.md), запускаемый отдельно на современном Python. Интеграция с плагином пока не реализована.

Локальный веб-чат первого этапа реализован в `src/backend` и `src/web`: агенты интерпретируют задание и собирают единую карточку для второго этапа. Запуск, агенты, гардрейлы и ограничения описаны в [руководстве реализации](docs/STAGE1_IMPLEMENTATION.md), контракт карточки 2.0 — в [TASK_CARD.md](docs/TASK_CARD.md).

```bash
python3 scripts/bootstrap.py
# Заполните QWEN_API_KEY в .env
docker compose up --build -d
python3 scripts/bootstrap.py <user_id>
```

Откройте ссылку из последней команды. В браузер передаётся только одноразовый токен локальной сессии; ключ Qwen остаётся на сервере.

```text
src/
  plugin/       Плагин STE Slicer и интеграция с приложением
  web/          Веб-интерфейс чата
  tuning/       Этап 2: подбор параметров печати (карточка этапа 1, правила, материалы, CLI `python -m tuning`)
tests/
  e2e/          Сквозные проверки пользовательских сценариев
docs/
  FEATURES.md   Краткий реестр реализованных фич и их E2E-проверок
research/
  wiki/         Вики Фёдора, материалы исследования и исходники сайта
CONTRIBUTING.md Правила работы с Git и кодом
AGENTS.md.example Шаблон инструкций для агентов
CLAUDE.md.example Шаблон локальных настроек участника
```

Сквозные проверки запускаются одной командой: `uv run pytest tests/e2e` (Python ≥ 3.8; линтеры `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`; код `src/tuning/` совместим с Python 3.5). Подбор из консоли по карточке этапа 1: `uv run python -m tuning select --input handoff.json [--feedback feedback.json] --materials-dir <resources/materials>`; выход — `stage2.parameter_set` v0.1 этапа 3. Проверка выходов проверкой этапа 3: `VALIDATION_DIR=<validation> STE_RESOURCES_DIR=<validation>/resources/ste_5.2.4 uv run pytest tests/e2e`; контракты и решения — в `docs/tuning/`.

Перед работой прочитайте [CONTRIBUTING.md](CONTRIBUTING.md). Реализованные возможности отслеживаем в [реестре фич](docs/FEATURES.md).

[Решения по первому этапу](docs/STAGE1_DESIGN.md) фиксируют согласованное поведение и ограничения проектирования, включая **KB-001: база знаний первой версии покрывает семь тестовых деталей, доступные материалы и основной профиль принтера**. При расширении набора задач это ограничение требуется пересмотреть.

Для работы с агентами создайте локальные файлы из шаблонов (если они уже есть, перенесите нужные изменения вручную):

```sh
cp -n AGENTS.md.example AGENTS.md
cp -n CLAUDE.md.example CLAUDE.md
```

[AGENTS.md.example](AGENTS.md.example) задаёт порядок работы агента, [CLAUDE.md.example](CLAUDE.md.example) — личное окружение участника. Заполните локальный `CLAUDE.md`. Оба локальных файла исключены из Git; общие правила разработки хранятся в `CONTRIBUTING.md`.

[Вики Фёдора](research/wiki/ABOUT.md) — справочные материалы и исследование, а не основное решение проекта.

[Текущая концепция команды](research/wiki/concept.html): роли, пять этапов обработки запроса и открытые вопросы.

Python-зависимости управляются через `uv`: `uv sync --locked`, затем `uv run --locked pytest`. Версии закреплены в `uv.lock`, рабочие зависимости и группа `dev` описаны в `pyproject.toml`. PDF рендерятся постранично и читаются мультимодальной моделью; отдельный OCR не используется.

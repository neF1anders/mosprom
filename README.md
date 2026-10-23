# mosprom

Основное решение — ассистент-технолог для STE Slicer. Код решения пока не добавлен.

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
```

Сквозные проверки запускаются одной командой: `uv run pytest tests/e2e` (Python ≥ 3.8; линтеры `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`; код `src/tuning/` совместим с Python 3.5). Подбор из консоли по карточке этапа 1: `uv run python -m tuning select --input handoff.json [--feedback feedback.json] --materials-dir <resources/materials>`; выход — `stage2.parameter_set` v0.1 этапа 3. Проверка выходов проверкой этапа 3: `VALIDATION_DIR=<validation> STE_RESOURCES_DIR=<validation>/resources/ste_5.2.4 uv run pytest tests/e2e`; контракты и решения — в `docs/tuning/`.

Перед работой прочитайте [CONTRIBUTING.md](CONTRIBUTING.md). Реализованные возможности отслеживаем в [реестре фич](docs/FEATURES.md).

Для работы с агентами создайте локальные файлы из шаблонов (если они уже есть, перенесите нужные изменения вручную):

```sh
```


[Вики Фёдора](research/wiki/ABOUT.md) — справочные материалы и исследование, а не основное решение проекта.

[Текущая концепция команды](research/wiki/concept.html): роли, пять этапов обработки запроса и открытые вопросы.

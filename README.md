# mosprom

Основное решение — ассистент-технолог для STE Slicer. Код решения пока не добавлен.

```text
src/
  plugin/       Плагин STE Slicer и интеграция с приложением
  web/          Веб-интерфейс чата
  tuning/       Этап 2: подбор параметров печати (геометрия STL, правила, материалы, CLI `python -m tuning`)
tests/
  e2e/          Сквозные проверки пользовательских сценариев
docs/
  FEATURES.md   Краткий реестр реализованных фич и их E2E-проверок
research/
  wiki/         Вики Фёдора, материалы исследования и исходники сайта
CONTRIBUTING.md Правила работы с Git и кодом
```

Сквозные проверки запускаются одной командой: `uv run pytest tests/e2e` (Python ≥ 3.8; линтеры `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`; код `src/tuning/` совместим с Python 3.5). Подбор из консоли: `uv run python -m tuning select --card card.json --stl part.stl --materials-dir <resources/materials>`; контракты и решения — в `docs/tuning/`.

Перед работой прочитайте [CONTRIBUTING.md](CONTRIBUTING.md). Реализованные возможности отслеживаем в [реестре фич](docs/FEATURES.md).

Для работы с агентами создайте локальные файлы из шаблонов (если они уже есть, перенесите нужные изменения вручную):

```sh
```


[Вики Фёдора](research/wiki/ABOUT.md) — справочные материалы и исследование, а не основное решение проекта.

[Текущая концепция команды](research/wiki/concept.html): роли, пять этапов обработки запроса и открытые вопросы.

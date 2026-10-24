# Эталоны подбора параметров

В каждой папке лежит карточка `TaskCard` 2.0 (`card.json`), для второго захода обратная связь этапа 3 (`feedback.json`) и выход исходного кода этапа 2 (`expected.json`). Выход записан до переноса кодом `src/tuning` из ветки `feat/parameters_tuning` (коммит `052fd62`) с каталогом материалов `knowledge/ste_5.2.4/materials`.

Исходный код читал карточку 1.1, поэтому перед запуском карточка переводилась в неё одноразовым скриптом вне репозитория:

- `schema_version` 1.1, `idempotency_key` из `job_id` и `revision`;
- допущения передавались строками `text`;
- ответы собирались из `questions[].answer` по `id` вопроса;
- `conflicts` пустой, в карточке 2.0 его нет.

Папки без префикса повторяют карточки тестов автора (`tests/e2e/tuning`). Папки `eval-1` … `eval-7` это карточки `job.card` прогона `artifacts/eval/20261024-034412`. В них изменено три поля, одинаково для обоих прогонов:

- `readiness` поставлен `ready`, у пяти карточек он был `blocked`;
- `blocked_actions` очищен;
- в `stl_analysis.report.file.path` локальный путь заменён на `artifacts/stage1/<attachment_id>`.

После переноса выход `select_parameters` совпадает с `expected.json` побайтово (`json.dumps(..., sort_keys=True)`), кроме оговорённых отличий:

- `version` 0.2 вместо 0.1;
- нет поля `idempotency_key`;
- `card_ref` берётся из `job_id` и `revision` карточки;
- `rotation` и `scale` модели записаны дробными числами, так их задаёт `ParameterSet` 0.2.

Проверяет это `tests/backend/tuning/test_golden.py`.

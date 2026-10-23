# Контракты этапа 2 (подбор параметров)

Этап 2 принимает карточку этапа 1 и (во втором заходе) обратную связь этапа 3, а отдаёт набор параметров в формате этапа 3. Весь JSON на выходе детерминирован: `json.dumps(..., sort_keys=True, ensure_ascii=False)`. Отказ: код 2 и `error: …` в CLI, `TuningError` в библиотеке.

```python
from tuning.select import select_parameters

parameter_set = select_parameters(handoff)  # заход 1
parameter_set = select_parameters(handoff, feedback=feedback)  # заход 2 (последний)
```
`config={"materials_dir": ...}` или переменная `STE_MATERIALS_DIR` — папка `resources/materials` слайсера. CLI: `uv run python -m tuning select --input handoff.json [--feedback feedback.json] --materials-dir DIR`. Состояния между вызовами нет: заход 2 пересчитывается из той же карточки и обратной связи.

## 1. Вход от этапа 1: карточка v1.1

`{idempotency_key, card}`; `card` — `TaskCard` 1.1 этапа 1. Адаптер `tuning.intake` переводит её во внутренние `task_card/0` и `geometry/0`.

| Поле карточки | Что делаем |
| --- | --- |
| `schema_version` | только `1.1`, иначе отказ |
| `readiness`, `blocked_actions.select_parameters` | `blocked` или непустой список причин → отказ с причинами; `preliminary` → работаем, оговорка первым допущением |
| `idempotency_key`, `revision`, `source_versions` | `card_ref = {job_id, revision}`: ключ `job_id:revision`; у карточки без ключа задание берётся из `source_versions`; нет ни того ни другого → отказ |
| `requirements[]` | `key` ищется в `intake/vocabulary.json`: известный код → наш ключ, значение-строка разбирается по типу (число с единицей, диапазон → строгая граница, да/нет, список). `id` = `key` (повтор → `key-2`), `hard` = `mandatory`; `source`: `user`/`document` → `user`, `measurement`/`knowledge` → `model`, `assumption` или `verified: false` → `assumption`. Неизвестный код или неразобранное значение: обязательное → в `assumptions` («не учтено подбором»), необязательное → в `warnings` |
| требования `quantity`, `load_bearing`, `material`, `printing_mode` | поля карточки: количество; нагрузка по фразам словаря; материал (только подтверждённый); режим `classic`/`cylindrical`/`cylindrical_full` |
| `answers.material_choice` | материал, если его нет в требованиях |
| `preferences[]`, `production_constraints[]` | приоритеты, запрет поддержек, нагрузка — по фразам словаря; каждый вывод записывается в `assumptions` |
| `assumptions[]`, неразрешённые `conflicts[]` | в `assumptions`; `unknowns[]` — в `warnings` |
| `stl_analysis` | `null` или нет `report` → отказ; `sha256` ≠ `report.file.sha256` → отказ; `attachment_id` → `models[].attachment_id` |
| `report.units.coordinate_unit` | `mm` — подтверждено; `unknown` — принимаем мм, допущение; иное → отказ |
| `report.geometry.bounds`, `volume`, `surface_area` | габариты (выбор режима, область печати, положение модели), факты для правил |
| `report.topology`, `report.validation.defects` | `needs_repair` (пока ни одно правило его не читает) |
| `report.normal_chords.minimum_sampled` | оценка тонкой стенки (пока ни одно правило её не читает) |

Нависаний, оси симметрии и диаметра отверстия в отчёте нет. Правила поддержек и 5D по нависаниям не срабатывают, а диаметр основания 5D остаётся значением по умолчанию. И то и другое пишется в `assumptions` (запрос к этапу 1 — `INTEGRATION.md`, раздел 2).

## 2. Выход: `stage2.parameter_set` v0.1

Формат задаёт этап 3: `validation/contracts/stage2_parameter_set.v0.1.md` в ветке `fedor/validation-ste`. Его же проверяет `validation/tools/check_parameter_set.py` по определениям выданной сборки 5.2.4. Что заполняем мы:

| Поле | Содержание |
| --- | --- |
| `contract`, `version` | `stage2.parameter_set`, `0.1` |
| `card_ref` | `{job_id, revision}` |
| `iteration` | `1` без обратной связи, `2` с ней |
| `printer` | `hte530v5.2.4` |
| `printing_mode` | `{value, why, source}` |
| `quality` | `{quality_type, why, source}`, один из профилей сборки: `high`, `normal`, `fast`, `draft`, `verydraft` (`coarse` и `extra coarse` толще 0,8 сопла) |
| `materials` | `{"0": {id, why, source}}`, только пруток 1,75 мм |
| `settings` | `{ключ слайсера: {value, why, source, unit?, scope?}}` — **только отличия** от профиля качества, файла материала и определения. Ключи — исходные (`layer_height`, `wall_thickness`, `top_bottom_thickness`, `support_enable`, `speed_print`), кроме обдува: у `cool_fan_enabled` ключи режима не связаны формулой, поэтому отправляется `cool_fan_enabled_classic` / `_cylindrical`. `scope: extruder:0` у настроек экструдера |
| `models` | `[{id, attachment_id, extruder: 0, transform: {rotation, position, scale}, why, source}]` |
| `assumptions` | `[{id: A1…, text, basis}]`; `source: assumption:<id>` ссылается на них |
| `applied_constraints` | только в заходе 2: `[{id, result: applied|not_applied, why}]` по каждому ограничению |

`source`: `requirement:<id>` (требование карточки; ответ — `requirement:answer.material_choice`), `rule:<ID>` (правило `rules/rules.json`), `constraint:<id>` (ограничение этапа 3), `assumption:<id>`, `default` (значение слайсера).

**Наши поля сверх контракта** (предложение этапу 3; проверка их не ругает):

| Поле | Зачем |
| --- | --- |
| `status` | `proposed` или `infeasible` (обязательные требования несовместимы, деталь не помещается); `infeasible` — не успех |
| `unsatisfied` | `[{requirement_id, why, conflicts_with?}]`: невыполненные требования, неприменённые ограничения, пары конфликтов |
| `warnings` | технические заметки: игнорированные поля, `unknowns` этапа 1, предупреждения отчёта STL |
| `idempotency_key` | ключ передачи этапа 1 |
| `materials[*].alternatives`, `materials[*].checks` | две альтернативы и проверка материала по каждому требованию (`ok`/`warn`/`fail`/`unknown`) |
| `models[*].orientation_candidate` | id кандидата ориентации (`o1`), на который ссылается `exclude` этапа 3 |

## 3. Вход захода 2: `stage3.feedback` v0.1

`{contract, version: "0.1", iteration: 1, result, constraints[{id, key, op, value, reason, severity}], exclude[], warnings[]}`. Обратная связь на заход 2 (`iteration: 2`) отклоняется: заходов не больше двух. `id` ограничения — буквы, цифры, `-`, `_`, `.`, иначе отказ (он попадает в `source: constraint:<id>`).

| Ключ ограничения | Как применяем |
| --- | --- |
| ось поиска (`layer_height`, `wall_thickness` / `wall_line_count`, `top_bottom_thickness`, `infill_sparse_density`, `material_print_temperature`, `speed_print`) | `min`/`max`/`eq` → жёсткая граница оси; правила сдвигают значение внутри неё. Если граница противоречит обязательному требованию → `infeasible` с парой. `ne`/`in` не поддержаны → `not_applied` |
| дискретная настройка (`support_enable`, `infill_pattern`, `adhesion_type`, `cool_fan_enabled*`, `retraction_enable`) | `eq` → значение; `ne` → запрет значения; `in` → выбор из списка |
| `printing_mode`, `quality_type`, `material` | `eq` / `ne` / `in` над выбором; если результат ограничению не соответствует (например, деталь не помещается в требуемый режим) → `not_applied` |
| любой другой ключ слайсера | `eq` → значение как есть, `in` → первое из списка, `min`/`max` → сама граница; `ne` → `not_applied` (значение выбрать не из чего) |
| `exclude` `orientation` | у нас один кандидат `o1`; если его исключили → `unsatisfied` |

Каждое неприменённое ограничение попадает и в `applied_constraints` (`not_applied` с причиной), и в `unsatisfied`.

## 4. Внутренние форматы

- `task_card/0` — карточка, которую ядро получает от адаптера: `status`, `inputs`, `part.load`, `requirements[{id, key, value, hard, source, basis}]`, `preferences{priority, supports_allowed, quantity, printing_mode}`, `material{name, requirement_id}`. Словарь ключей требований — в `intake/vocabulary.json`.
- `geometry/0` — `bbox_mm{min, max, size}`, `volume_mm3`, `surface_area_mm2`, `triangle_count`, `is_closed`, `normals_consistent`, `needs_repair`, `min_wall_estimate_mm`.

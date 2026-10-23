# Контракты этапа 2 (подбор параметров), черновик v0

Это предложение этапа 2 для этапов 1 и 3; оно реализовано в `src/tuning/contracts.py` как есть.
Правила чтения: неизвестные поля входа игнорируются с записью в `warnings`, падать нельзя.
Обязательны только `status` и `inputs`. Весь JSON на выходе детерминирован:
`json.dumps(..., sort_keys=True, ensure_ascii=False)`.

## Вход от этапа 1: единая карточка v1.1 (основной путь)

Этап 1 присылает `{idempotency_key, card}`; `card` — карточка `TaskCard` 1.1 (описание контракта — у этапа 1).
Адаптер `tuning.intake` переводит её во внутренние `task_card/0` и `geometry/0`, ядро подбора их и получает.
Что читаем и как:

| Поле карточки | Что делаем |
| --- | --- |
| `schema_version` | только `1.1`, иначе отказ |
| `readiness`, `blocked_actions.select_parameters` | `blocked` или непустой список причин → отказ с причинами; `preliminary` → работаем, оговорка первой строкой в `assumptions_used` |
| `requirements[]` | `key` ищется в `intake/vocabulary.json`: известный код → наш ключ; значение-строка разбирается по типу (число с единицей, диапазон → строгая граница, да/нет, список). `id` = `key` (повтор → `key#2`), `hard` = `mandatory`, `source`: `user`/`document` → `user`, `measurement`/`knowledge` → `model`, `assumption` или `verified: false` → `assumption`. Неизвестный код или неразобранное значение: обязательное → `assumptions_used` («не используется подбором»), необязательное → `warnings` |
| требования `quantity`, `load_bearing`, `material`, `printing_mode` | не требования к материалу, а поля карточки: количество, нагрузка (по фразам из словаря), материал (только подтверждённый, не `assumption`), подсказка режима (`classic`/`cylindrical`/`cylindrical_full`) |
| `answers.material_choice` | материал, если его нет в требованиях |
| `preferences[]` (строки) | приоритеты `strength`/`accuracy`/`speed`/`cost` и запрет поддержек — по фразам из словаря, порядок по первому упоминанию; каждый вывод записывается в `assumptions_used` |
| `production_constraints[]` | нагрузка, если её нет в требованиях |
| `assumptions[]`, неразрешённые `conflicts[]` | в `assumptions_used`; `unknowns[]` — в `warnings` |
| `stl_analysis` | `null` или нет `report` → отказ; `sha256` ≠ `report.file.sha256` → отказ |
| `report.units.coordinate_unit` | `mm` — подтверждено; `unknown` — координаты принимаются за мм, допущение в `assumptions_used`; иное → отказ |
| `report.geometry` | `bounds` → `bbox_mm`, `volume` (может быть `null` → факта нет), `surface_area` |
| `report.topology`, `report.validation.defects` | `is_closed`, `normals_consistent`, `volume_sign_negative`, `needs_repair` |
| `report.normal_chords.minimum_sampled` | `min_wall_estimate_mm` (оценка, не измерение) |
| `report.warnings`, `partial_errors` | в `warnings` |
| `idempotency_key` | копируется в `param_set` и `state`; вызов цикла с чужим ключом → отказ |

Остальные поля (`rules_version`, `knowledge_version`, `geometry` (сводка), `source_versions`, `questions`,
`allowed_actions`, `resolutions`, служебные поля отчёта) сейчас не читаются. Нависаний в отчёте нет: факт
`geometry.overhang_area_fraction` не задаётся, правила поддержек и 5D по нависаниям не срабатывают, это пишется
в `assumptions_used`. Отказ — код 2 и `error: …` в CLI, `TuningError` в библиотеке.

## task_card/0 (внутренний вход ядра; путь разработки `--card`)

| Поле | Тип | Смысл |
| --- | --- | --- |
| `schema` | str | `task_card/0` |
| `status` | str, обязательно | `ready` — можно подбирать; иное — подбор отказывается |
| `inputs` | object, обязательно | `text`, `files[{path, kind}]` |
| `part` | object | `name`, `function`, `load` (`static`/`cyclic`/`impact`/`none`), `environment` |
| `requirements` | list | `{id, kind, key, value, hard, source, basis}` |
| `preferences` | object | `priority` (порядок из `strength`/`accuracy`/`speed`/`cost`), `supports_allowed`, `quantity`, `printing_mode` (необязательная подсказка этапа 1: `classic`/`cylindrical`/`cylindrical_full`) |
| `material` | object | `name`, `candidates`, `source` |
| `assumptions` | list | `{text, basis, confidence}` |
| `missing` | list | `{what, critical}` |

`requirements.source`: `user` | `model` | `assumption`. Требование с `source: assumption`
не выдаётся как подтверждённый факт: попадает в `assumptions_used`.

### Словарь `requirements.key`

| key | значение | как используется |
| --- | --- | --- |
| `tg_min_c` | число, °C | фильтр материала (нужна оценка тепловой стойкости, см. DECISIONS) |
| `service_temp_max_c` | число, °C | то же |
| `hydrophobic` | bool | штраф гигроскопичных материалов; конфликт с жёсткостью выносится в `unsatisfied` |
| `uv_stable` | bool | предпочтение ASA/PC-подобных материалов (общие знания, не проверено) |
| `chemical_resistance` | список строк | сопоставление с описанием материала в каталоге |
| `flexible` | bool | эластомеры (TPU и т. п.) |
| `density_max_g_cm3` | число | жёсткий фильтр по плотности из каталога |
| `low_friction` | bool | предпочтение PA/POM-подобных |
| `abrasion_resistant` | bool | предпочтение PA/TPU |
| `dimensional_tol_mm` | число | точность: тонкий слой, режим, скорость |
| `no_visible_layers` | bool | тонкий слой, поверхность |
| `no_supports` | bool | запрет поддержек, влияет на ориентацию |
| `food_safe` | bool | помечается как «не проверено» (нет данных в каталоге) |
| `esd` | bool | помечается как «не проверено» |
| `high_stiffness` | bool | периметры, заполнение, материал |

Соответствие деталям из ТЗ (кратко): шестерня — `tg_min_c`, `hydrophobic`, `uv_stable`, `high_stiffness`,
`dimensional_tol_mm`; насос — `service_temp_max_c`, `density_max_g_cm3`, `dimensional_tol_mm`;
пыльник — `flexible`, `chemical_resistance`, `service_temp_max_c`; фигурка — `no_visible_layers`, `no_supports`, `uv_stable`.

## geometry/0 (из отчёта этапа 1 или, на пути разработки, из STL)

`bbox_mm` (min/max/size), `volume_mm3`, `surface_area_mm2`, `triangle_count`, `is_closed`
(каждое ребро ровно в двух треугольниках), `normals_consistent`, `needs_repair`,
`overhang_area_fraction` (площадь с наклоном нормали > 45° от вертикали, при текущей ориентации),
`min_wall_estimate_mm` (оценка, не измерение), `fits_build_volume` по режимам.

## param_set/0 (выход)

Поля: `schema`, `idempotency_key` (только при входе от этапа 1), `iteration`, `strategy`, `status`, `printing_mode`, `material`, `settings`,
`orientation`, `assumptions_used`, `unsatisfied`, `warnings`, `build_volume_mm` (область печати выбранного режима).
`unsatisfied[]`: `requirement_id`, `why`, необязательный `conflicts_with` (второй участник конфликта).
`material.checks[]` — проверка выбранного материала по каждому проверяемому требованию (`ok`/`warn`/`fail`/`unknown`).

- `status`: `proposed` · `final` · `exhausted` · `infeasible`. `exhausted` и `infeasible` — не успех.
- `printing_mode`/`material`/каждая запись `settings` обязаны иметь `source` и `reason`.
- `source`: `card` | `rule:<id>` | `search:itK` | `default:<профиль>` | `rank`.
- `settings[].target`: `global` или `extruder:<n>`; `t` ∈ [0, 1] — положение на оси «дёшево → прочно».
- `printing_mode.confidence` — для гипотез о 5D.

## verdict/0 (вход цикла, этап 3)

`ok`, необязательные `score`, `issues[{id, key, signal, severity?, requirement_id?, hard?, message}]`,
`vetoes[{key, value, message}]`. `signal`: `too_weak` | `too_costly` | `wrong_value` | `conflict`.
`score` и `severity` необязательны; стратегии без них деградируют до бисекции.

## Интерфейс

```python
select_from_handoff(payload, state=None, verdict=None, config=None) -> (param_set, new_state)  # tuning.intake
select_parameters(card, geometry, state=None, verdict=None, config=None) -> (param_set, new_state)  # ядро
```

Состояние — JSON-совместимый словарь, глобального состояния нет. CLI:
`uv run python -m tuning select --input handoff.json [--state s.json --verdict v.json] [--strategy m1] [--seed 1]`;
путь разработки и экспериментов: `--card card.json --stl part.stl` вместо `--input`.

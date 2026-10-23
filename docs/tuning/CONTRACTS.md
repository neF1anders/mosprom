# Контракты этапа 2 (подбор параметров), черновик v0

Это предложение этапа 2 для этапов 1 и 3; оно реализовано в `src/tuning/contracts.py` как есть.
Правила чтения: неизвестные поля входа игнорируются с записью в `warnings`, падать нельзя.
Обязательны только `status` и `inputs`. Весь JSON на выходе детерминирован:
`json.dumps(..., sort_keys=True, ensure_ascii=False)`.

## task_card/0 (вход, этап 1)

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

## geometry/0 (вычисляется из STL)

`bbox_mm` (min/max/size), `volume_mm3`, `surface_area_mm2`, `triangle_count`, `is_closed`
(каждое ребро ровно в двух треугольниках), `normals_consistent`, `needs_repair`,
`overhang_area_fraction` (площадь с наклоном нормали > 45° от вертикали, при текущей ориентации),
`min_wall_estimate_mm` (оценка, не измерение), `fits_build_volume` по режимам.

## param_set/0 (выход)

Поля: `schema`, `iteration`, `strategy`, `status`, `printing_mode`, `material`, `settings`,
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
select_parameters(card, geometry, state=None, verdict=None, config=None) -> (param_set, new_state)
```

Состояние — JSON-совместимый словарь, глобального состояния нет. CLI:
`uv run python -m tuning select --card card.json --stl part.stl [--state s.json --verdict v.json] [--strategy m1] [--seed 1]`.

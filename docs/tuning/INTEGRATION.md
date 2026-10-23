# Внедрение блока подбора параметров (этап 2) в пайплайн

Для команды: что этап 2 берёт у этапа 1, что отдаёт этапу 3 и адаптеру слайсера, как проходят два захода. Поля подробно — в [CONTRACTS.md](CONTRACTS.md), алгоритм по каждому параметру — в [METHODOLOGY.md](METHODOLOGY.md).

```
Этап 1: {idempotency_key, card v1.1 (требования + отчёт STL)}
   └─► ЭТАП 2 ── stage2.parameter_set (заход 1) ─► Этап 3 (проверка) ─► адаптер ─► слайсер
          ▲                                          │
          └──── stage3.feedback (ограничения) ◄──────┘   заход 2 — последний
```

## 1. Как вызывать

```python
from tuning.select import select_parameters

first = select_parameters(handoff, config={"materials_dir": materials})  # заход 1
second = select_parameters(handoff, feedback=feedback, config={"materials_dir": materials})  # заход 2
```

```sh
uv run python -m tuning select --input handoff.json [--feedback feedback.json] --materials-dir <resources/materials>
```

- `handoff` — тело POST этапа 1. Принимается и «голая» карточка из `GET /api/v1/jobs/{id}/card`: тогда задание берётся из `source_versions`. STL этапу 2 не нужен, геометрия приходит в `card.stl_analysis.report`.
- `materials_dir` (или `STE_MATERIALS_DIR`) — `resources/materials` **выданной сборки** слайсера. Значения в файлах материалов сборки 5.2.4 отличаются от GitHub (у PA6 скорость 50 мм/с, у PC 280 °C), поэтому каталог в репозиторий не копируется.
- Состояния нет: заход 2 = та же карточка + обратная связь этапа 3. Новая ревизия карточки — это новый заход 1.
- Модуль на Python 3.5 (только стандартная библиотека), работает внутри слайсера. Вывод детерминирован.
- Проверка выходов проверкой этапа 3: `VALIDATION_DIR=<validation> STE_RESOURCES_DIR=<validation>/resources/ste_5.2.4 uv run pytest tests/e2e` (без переменных эти тесты пропускаются). На наших E2E-случаях (3D, 5D Spiral, 5D, заход 2) проверка даёт 0 ошибок и 0 предупреждений.

## 2. Что нужно от этапа 1

Готовность: `readiness` — `ready` или `preliminary`, в `blocked_actions` нет `select_parameters`, есть `stl_analysis.report` того же STL. Иначе отказ с причинами.

**Чего не хватает, чтобы рассчитать все параметры** (по набору: 20 названий в 3D, 29 в 5D):

| Нужно для | Чего нет в карточке v1.1 | Просим |
|---|---|---|
| `support_enable/type/angle`, поворот модели | нависаний и площади опоры по направлениям | `overhang_by_direction`: для каждого из ±X/±Y/±Z как «вверх» — доля площади нависаний круче 45°, площадь контакта со столом, высота |
| режим 5D, `cylindrical_mode_base_diameter`, `non_printing_base_diameter`, плот 5D | оси вращательной симметрии и диаметра центрального отверстия | `rotation_axis` и `bore_diameter_mm` (по сечениям) |
| профиль качества, слой, скорость | допуска и поверхности числом | коды `dimensional_tol_mm`, `no_visible_layers` |
| периметры, кожа, заполнение, паттерн | нагрузки и жёсткости кодами (сейчас свободный текст) | `load_bearing` со значением `none`/`static`/`cyclic`/`impact`; `high_stiffness`, `flexible` |
| все размеры | подтверждённых единиц (`coordinate_unit: unknown`) | подтверждение мм до передачи |
| режим 3D/5D, если его задал пользователь | — | требование `printing_mode` (`classic`/`cylindrical`/`cylindrical_full`) — уже поддержано |
| партия → копии в `models` | смысла партии | ответ на вопрос `batch_models` |

**Коды требований, которые подбор понимает** (`src/tuning/intake/vocabulary.json`; новый код — новая строка словаря):

| Код | Значение и единица |
|---|---|
| `tg_min_c`, `service_temp_max_c` (и `service_temperature`) | число или диапазон, `°C`; из диапазона берётся верхняя граница |
| `density_max_g_cm3` (`г/см³`), `dimensional_tol_mm` (`мм`) | число; из диапазона берётся нижняя граница |
| `hydrophobic`, `uv_stable`, `flexible`, `low_friction`, `abrasion_resistant`, `high_stiffness`, `no_visible_layers`, `no_supports`, `food_safe`, `esd` | `да`/`нет` |
| `chemical_resistance` | список через запятую (`щёлочи, масла`) |
| `printing_mode`, `material`, `quantity`, `load_bearing` | режим, материал (id файла или название), число, нагрузка |

В примере v1.1 с нашим словарём совпадает только `service_temperature`. Остальное (`airtightness`, `surface_finish`, `purpose_item_type`) — свободный текст. Обязательное требование, которое подбор не понял, честно попадает в `assumptions` как «не учтено».

## 3. Что получает этап 3 и адаптер

`stage2.parameter_set` v0.1 этапа 3 (CONTRACTS.md, раздел 2):
- режим, профиль качества, материал;
- **только отличия** от профиля и материала;
- положение модели;
- допущения с id.

Пример для шестерни (3D, прочность, циклическая нагрузка, обязательная жёсткость):
- профиль `normal` (Fine 0,1 мм), материал `fiberpart_abs_g13`;
- `wall_thickness` 2,4 мм (6 периметров), `top_bottom_thickness` 1,2 мм, `infill_sparse_density` 40 %, `infill_pattern` gyroid;
- `material_print_temperature` 275 °C;
- `cool_fan_enabled_classic` = false (в файле материала обдув 0 %);
- модель в центре рабочей области стола, поворот «как загружено».

Сверх контракта мы отдаём `status`, `unsatisfied`, `warnings`, `idempotency_key`, альтернативы и проверки материала, `orientation_candidate`. Чат обязан показать пользователю `assumptions` и `unsatisfied`. `status: infeasible` — не успех.

## 4. Два захода

1. Заход 1 без обратной связи → `iteration: 1`.
2. Этап 3 проверяет набор и возвращает `stage3.feedback`: `result: ok` (заход 2 не нужен) или `needs_changes` с ограничениями.
3. Заход 2: карточка + обратная связь → `iteration: 2`, `applied_constraints`. Ограничения на наши оси становятся жёсткими границами. Ограничения на выбор (режим, профиль, материал) и на остальные ключи применяются напрямую. Неприменимые помечаются `not_applied` и попадают в `unsatisfied`.
4. Третьего захода нет: обратная связь на заход 2 отклоняется.

## 5. Открытые вопросы

**К этапу 3 (Фёдору):**
1. Наши поля сверх контракта (`status`, `unsatisfied`, `warnings`, `orientation_candidate`, `applied_constraints[{id, result, why}]`): принять в контракт 0.2 или переименовать?
2. Обдув в `cylindrical_full`. Внутренняя 3D-часть режется CuraEngine и по `StartSliceJob` читает `*_classic`, внешняя — `*_cylindrical`. Проверка предупреждает про ключ `_classic` в 5D, поэтому мы отправляем только `cool_fan_enabled_cylindrical`. Нужен ли и `_classic`?
3. Система координат `position` (принят центр стола) и как `rotation` соотносится с осями STL (у слайсера Y — вверх).
4. Нужно ли отправлять значения, совпадающие с профилем (например, `adhesion_type: brim` в примере), или только отличия?

**К команде:**
1. Кто выбирает материал: этап 1 (`material`/`answers.material_choice`) или мы по требованиям? Поддержаны оба, по умолчанию ранжируем сами.
2. Ключевые настройки жюри: совпадает ли их набор с `recommended.cfg` (48 ключей)?
3. Когда выбирать `cylindrical`, а когда `cylindrical_full`, и какой диаметр основания. По коду `cylindrical_full` режет модель цилиндром `cylindrical_mode_base_diameter`: внутри печать идёт в 3D, снаружи в 5D. В тестовых G-code Stereotech диаметр основания 10–20 мм и плот. Нужен эксперт организаторов.
4. Ориентация: сейчас модель стоит «как загружено» (у шестерни из примера толщина вдоль Y файла, то есть она встанет на ребро). Без нависаний от этапа 1 поворот не выбрать.

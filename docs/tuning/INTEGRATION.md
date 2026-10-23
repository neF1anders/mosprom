# Внедрение блока подбора параметров (этап 2) в пайплайн

Для команды: что этап 2 получает от этапа 1 и валидатора, что отдаёт этапам 4–5. Полные схемы — в [CONTRACTS.md](CONTRACTS.md); это краткая «инструкция по подключению». Контракт — предложение v0, его надо согласовать.

```
Этап 1 (карточка) ──► ЭТАП 2 (подбор) ◄──► Этап 3 (валидатор)
STL ────────────────►      │
                           └─ param_set ──► Этап 4 (слайсинг) ──► Этап 5 (сборка)
```

## 1. Как вызывать

Библиотека (внутри плагина) или CLI; состояния между вызовами не хранится:

```python
from tuning.select import select_parameters
param_set, state = select_parameters(card, geometry, state=None, verdict=None, config=cfg)   # первый подбор
param_set, state = select_parameters(card, geometry, state=state, verdict=verdict, config=cfg)  # после вердикта
```

```sh
uv run python -m tuning select --card card.json --stl part.stl --materials-dir <resources/materials> \
    [--state state.json --verdict verdict.json] [--strategy m5] [--max-iterations 3] [--seed 1] [--state-out state.json]
```

- `geometry` считает сам модуль: `tuning.geometry.extract_features(path_to_stl)` (CLI делает это сам). 28 МБ STL читается ≈ 3 с.
- `state` — JSON-словарь. **Его хранит вызывающая сторона** (оркестратор/чат) и возвращает при следующем вызове вместе с вердиктом. Карточка и STL при каждом вызове передаются заново и не должны меняться.
- `config`: `materials_dir` (или переменная `STE_MATERIALS_DIR`) — папка `resources/materials` слайсера; `strategy` (по умолчанию `m0`; для цикла рекомендуем `m5`, см. отчёт экспериментов); `max_iterations` = N, число проверок валидатора (по умолчанию 3); `seed`.
- Вывод детерминирован: `json.dumps(sort_keys=True, ensure_ascii=False)`. Ошибка входа: код 2 и строка `error: ...` в stderr (CLI) / `TuningError` (библиотека).
- Модуль на Python 3.5 (стандартная библиотека), запускается внутри слайсера.

## 2. Что нужно от этапа 1 (карточка `task_card/0`)

Обязательны только `status` (должен быть `"ready"`, иначе отказ) и `inputs`. Остальное необязательно, но чем полнее — тем точнее подбор. Неизвестные поля игнорируются с записью в `warnings`.

| Поле | Зачем нам | Если нет |
|---|---|---|
| файл STL (отдельно от карточки: путь передаёт оркестратор) | геометрия: габариты, нависания, тонкая стенка | подбор невозможен |
| `requirements[]` = `{id, key, value, hard, source, basis}` | материал, границы параметров, выбор режима | подбор по умолчанию |
| `preferences.priority` (порядок из `strength`/`accuracy`/`speed`/`cost`) | стартовая точка поиска | нейтральная середина |
| `preferences.supports_allowed` | допускаются ли поддержки (по умолчанию да) | да |
| `preferences.printing_mode` (`classic`/`cylindrical`/`cylindrical_full`) | подсказка режима; единственный надёжный способ выбрать 5D | `classic`, либо гипотеза правил |
| `preferences.quantity` | пока только записывается | 1 |
| `part.load` (`static`/`cyclic`/`impact`/`none`) | запас по периметрам, паттерн заполнения | — |
| `material.name` (id файла или название) / `material.candidates` | материал берём из карточки, иначе ранжируем каталог | ранжирование |

**Словарь `requirements.key`, который мы реально используем** (значения и единицы обязательны): `tg_min_c` (°C), `service_temp_max_c` (°C), `hydrophobic` (bool), `uv_stable` (bool), `chemical_resistance` (список: `acid`, `alkali`, `salts`, `oil`, `fuel`, `alcohol`, `ozone`, `solvents`, `water`), `flexible` (bool), `density_max_g_cm3`, `low_friction`, `abrasion_resistant`, `high_stiffness`, `food_safe`, `esd` (bool), `dimensional_tol_mm` (мм), `no_visible_layers`, `no_supports` (bool). Другие ключи не ломают работу, но не учитываются.

Просим от этапа 1 строго:
- `hard: true` только для того, что нарушать нельзя: такие требования становятся ограничениями, их конфликт даёт `infeasible`;
- `source`: `user` | `model` | `assumption`; допущения мы отдаём дальше в `assumptions_used`, а не как факт;
- числа и единицы, а не текст («Tg ≥ 85» → `tg_min_c: 85`); уникальные `id` (`R1`, `R2`…) — на них ссылаются вердикт и `unsatisfied`;
- сообщать, что не удалось выразить ключами (`missing`) — мы это не интерпретируем, но оно полезно чату.

Что мы **не** принимаем от этапа 1: значения настроек слайсера, ориентацию, G-code.

## 3. Что нужно от валидатора (`verdict/0`)

Вызывается после каждого `param_set` со статусом `proposed`. Минимум: `ok` (bool).

```json
{"schema": "verdict/0", "ok": false, "score": 0.62,
 "issues": [{"id": "V1", "key": "infill_sparse_density", "signal": "too_weak",
             "severity": 0.7, "requirement_id": "R2", "hard": true, "message": "…"}],
 "vetoes": [{"key": "support_enable_classic", "value": true, "message": "…"}]}
```

- `issues[].key` — **ключ настройки слайсера**, как в `param_set.settings[].key` (например `classic_layer_height`, `wall_line_count`, `top_layers`, `infill_sparse_density`, `material_print_temperature`, `speed_print`). Именно ключ определяет, какой параметр мы двигаем; вердикт без ключа мы не можем применить (такие замечания только попадают в `unsatisfied`).
- `signal`: `too_weak` (поднять прочность/качество), `too_costly` (дорого: время/материал), `wrong_value` (для дискретных), `conflict`.
- `severity` (0..1) и `score` (0..1, больше — лучше) необязательны; стратегии работают и без них (бисекция), но с ними чуть точнее.
- `vetoes` — запрет конкретного значения дискретной настройки (`support_enable_*`, `adhesion_type`, `infill_pattern`); мы переключимся на следующего кандидата.
- `requirement_id` и `message` нужны, чтобы при `exhausted`/`infeasible` показать пользователю причину.

**Из опыта экспериментов на заглушке** (подробно — [отчёт](experiments/2026-10-23-strategies-vs-stub.md)): цикл работает, только если замечания указывают на параметры, которые ещё можно менять. Не стоит одновременно ругаться на один параметр «слабо» и «дорого» и не стоит указывать на параметры, упёршиеся в жёсткие границы (слой 0.1 мм, температура окна материала, 2 периметра и т. п.); лучше сообщать несколько разных параметров.

## 4. Что отдаём (`param_set/0`)

| Поле | Содержание | Кто использует |
|---|---|---|
| `status` | `proposed` — отправить на проверку; `final` — все проверки пройдены; `exhausted` — лимит N исчерпан, лучший из набора, причины в `unsatisfied`; `infeasible` — жёсткие требования несовместимы, пара в `unsatisfied` | оркестратор, чат |
| `printing_mode` | `{value, source, reason, confidence}`; `classic` / `cylindrical` / `cylindrical_full`; 5D — гипотеза (`confidence` < 0.5) | этап 4 (настройка `printing_mode`) |
| `material` | `{value, source: card|rank, reason, alternatives[], checks[]}`; `value` = имя файла материала (`enduse_pa6`) | этап 4 (выбор материала), чат |
| `settings[]` | `{key, value, unit, target: global, t, source, rule_ids, reason}` — **ключи настроек STE Slicer для `hte530v5.2`**, зависят от режима (`classic_layer_height` / `cylindrical_layer_height`, `support_enable_classic` / `_cylindrical`; для `cylindrical_full` оба набора) | этап 4 пишет их в профиль/3MF; `reason` для чата |
| `unsatisfied[]` | `{requirement_id, why, conflicts_with?}` | чат (объяснение пользователю), валидатор |
| `assumptions_used[]` | допущения и непроверенные пункты («не проверено по каталогу») | чат: нельзя выдавать за подтверждённый факт |
| `build_volume_mm`, `orientation` | область печати режима; ориентация пока всегда `null` | этап 4 |
| `warnings[]` | игнорируемые поля, подмены (например, неизвестный материал) | логи |

Требует решения команды: **этап 4 должен подтвердить**, что принимает значения именно по этим ключам и что для `cylindrical_full` корректно задать оба набора; значения других настроек (скорости стенок, вентилятор по режимам и т. д.) выводятся слайсером по формулам из тех, что мы задаём.

## 5. Цикл и кто что делает

1. Оркестратор вызывает подбор (state=None) → `param_set` (`proposed`).
2. Передаёт его валидатору (и алгоритмические проверки), получает `verdict`.
3. `ok` → вызов с вердиктом даёт `final` с теми же настройками → на слайсинг (этап 4).
4. Не `ok` → вызов с `state` и `verdict` → новый `param_set` (`proposed`) → к валидатору. Всего не более N проверок.
5. После N-й неудачной проверки или при конфликте приходит `exhausted`/`infeasible` — **это не успех**: чат должен показать пользователю причины из `unsatisfied` и допущения.

Итоговый `final` не означает, что слайсинг пройдёт: этап 4 может вернуть свои предупреждения; пока контракта обратной связи от этапа 4 нет (см. открытые вопросы).

## 6. Открытые вопросы для команды

1. Кто выбирает материал: этап 1 (`material.name`) или мы по требованиям? Поддержаны оба, по умолчанию ранжируем сами.
2. N и кто правит параметры: сейчас N = 3, правим мы по замечаниям валидатора. Если валидатор сам правит значения — повторная проверка обязательна.
3. Нужны ли настройки по экструдерам (`target: extruder:n`)? Сейчас всегда `global`.
4. Точные ключи/значения, которые ждёт этап 4, и как он вернёт ошибки слайсинга в подбор.
5. Что физически означают `cylindrical` и `cylindrical_full` (нужен эксперт организаторов); до ответа выбор 5D — гипотеза, надёжный путь — `preferences.printing_mode` от этапа 1.
6. Откуда берётся папка материалов в плагине (`resources/materials` слайсера) и кто передаёт путь.
7. Ориентация модели пока не подбирается; по примерам похоже, что ось Z части STL не совпадает с осью печати.

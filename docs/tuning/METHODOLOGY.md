# Методология подбора параметров печати (этап 2)

Как `select_from_handoff` превращает карточку этапа 1 в набор настроек STE Slicer для принтера
**Stereotech Hybrid 530 V5.2** (`hte530v5.2`). Здесь описано, что вычисляется, из каких полей входа и по какому
правилу. Поля входа подробно разобраны в [CONTRACTS.md](CONTRACTS.md), допущения — в [DECISIONS.md](DECISIONS.md).

Метки происхождения знаний:
- **D** — определения и код STE-Slicer (клон `3c863ed`: `resources/definitions`, `resources/materials`, `plugins/*/StartSliceJob.py`);
- **S** — спецификация задачи;
- **G** — общая практика печати, на эталонах не проверена;
- **H** — наша гипотеза.

Эталонных наборов параметров нет, поэтому качество значений не измерено (раздел 7).

## 0. Конвейер

```
{idempotency_key, card v1.1}
  │ 1. приём: готовность → требования → геометрия из stl_analysis.report       (tuning/intake)
  │ 2. факты: плоский словарь req.* / reqhard.* / pref.* / part.load / geometry.*  (facts.py)
  │ 3. материал: из карточки или ранжирование каталога                          (material_choice.py, catalog/)
  │ 4. правила: стартовая точка t0 и допустимый интервал [lo, hi] по каждой оси   (rules/rules.json, planning.py)
  │ 5. режим печати: голосование правил с учётом области печати                 (select.py:_choose_mode)
  │ 6. значения: t → значение оси → ключи STE Slicer выбранного режима           (space/, select.py:_settings)
  │ 7. проверка жёстких правил и статус                                          (hard_rules.py, select.py)
  ▼
param_set/0  (+ state для цикла с валидатором, раздел 5)
```

**Ось t.** У каждого порядкового или непрерывного параметра есть нормированная ось `t ∈ [0, 1]`: 0 — дёшево, быстро,
хрупко; 1 — дорого, медленно, прочно (S 5.2, H1). Значение вычисляется так:
`v = квантование(v0 + t · (v1 − v0))` по шагу оси с обрезкой границами `[min(v0, v1), max(v0, v1)]`. Округление
банковское (Python `round`): 7.5 шага → 8, 6.5 → 6.

**Стартовая точка.** `t0 = 0.5`, затем правила, условие которых выполнено:
- `shift` сдвигает `t0`, сдвиги складываются;
- `bound` и `limit` сужают `[lo, hi]`; `limit` задаётся в единицах значения и переводится в `t`;
- в конце `t0` обрезается в `[lo, hi]`.

Если `lo > hi`, это конфликт правил: статус `infeasible`, пара правил и связанные требования записываются в `unsatisfied`.

**Что включает правила.** Из входа учитываются:
- `pref.priority_first` — **только первый** приоритет;
- `part.load`;
- `req.<key>` и `reqhard.<key>` — требование жёсткое, если хотя бы одно требование с этим ключом `mandatory`;
- `pref.supports_allowed`, `pref.printing_mode`;
- `geometry.*`.

## 1. Приём входа (`tuning/intake`)

| Шаг | Вход | Результат |
|---|---|---|
| Готовность | `schema_version`, `readiness`, `blocked_actions.select_parameters` | `1.1` и не `blocked`/не заблокировано, иначе отказ; `preliminary` → оговорка |
| Требования | `requirements[]{key, value, unit, mandatory, provenance, verified}` | по `intake/vocabulary.json`: код → наш ключ, строка → число/диапазон/да-нет/список; `mandatory` → жёсткое; `verified: false` → допущение |
| Поля карточки | требования `quantity`, `load_bearing`, `material`, `printing_mode`; `answers.material_choice`; `preferences[]`; `production_constraints[]` | количество; нагрузка `none/impact/cyclic/static`; материал; подсказка режима; приоритеты и запрет поддержек по фразам |
| Геометрия | `stl_analysis.report` | `bbox_mm`, `volume_mm3`, `surface_area_mm2`, `needs_repair`, `min_wall_estimate_mm`; единицы `unknown` → «мм» как допущение |

**Нет во входе:** доли нависаний, оси печати, ориентации. Поэтому факт `geometry.overhang_area_fraction` не задаётся,
и все правила с ним не срабатывают. Это допущение пишется в каждый ответ (запрос к этапу 1 — `INTEGRATION.md`, раздел 2).

## 2. Сводка: параметр → алгоритм

| Выход | Входные данные | Алгоритм (кратко) | Знание |
|---|---|---|---|
| `printing_mode` | требование `printing_mode`; габариты; (нависания + `no_supports`) | голосование: classic 1, подсказка карточки 10, гипотеза 5D 2; режим, где деталь не помещается, исключается | S, D (области), H (5D) |
| `material` | `material`/`answers.material_choice`; требования к материалу | назван и найден → берём и проверяем; иначе ранжирование пула каталога по требованиям | D (файлы), G (свойства) |
| `classic_layer_height` / `cylindrical_layer_height` | допуск, «без видимых слоёв», приоритет | ось 0.32 → 0.10 мм, шаг 0.01 | D (0.8·сопло), S, G |
| `wall_line_count` | приоритет, нагрузка, жёсткость, гибкость | ось 2 → 6, шаг 1 | S, G |
| `top_layers`, `bottom_layers` | приоритет, нагрузка; высота слоя | ось толщины кожи 0.8 → 2.0 мм, `ceil(толщина / слой)`, ≥ 3 | S, G |
| `infill_sparse_density` | приоритет, жёсткость, гибкость | ось 10 → 60 %, шаг 5 | G |
| `infill_pattern` | нагрузка, гибкость; плотность | gyroid при ударной или циклической нагрузке либо гибкости; иначе grid, при плотности > 25 % lines | G |
| `material_print_temperature` | материал; приоритет | ось T−10 → T+10 °C от значения файла материала, шаг 5, ≤ 285 | D, S |
| `speed_print` | материал; приоритет, допуск, гибкость | ось V → 0.5·V от скорости файла материала, шаг 5 | D (V), G |
| `support_enable_classic` / `_cylindrical` | нависания, `supports_allowed`, `no_supports` | `true`, если доля нависаний > 0.05 и поддержки разрешены; иначе `false` | S, G |
| `adhesion_type` | — | всегда `brim` (в `cylindrical` не выдаётся) | D |
| `material_bed_temperature` | материал | значение файла материала | D |
| `cool_fan_speed` | материал | значение файла материала | D |
| `build_volume_mm` | режим | 315 × 300.3 × (300 classic / 250 5D) | D |
| `orientation` | — | всегда `null` (не подбирается) | — |
| `status`, `unsatisfied`, `assumptions_used` | всё выше + вердикт | раздел 4 и 5 | S |

Ключи зависят от режима (`space/search_space.json`, по `StartSliceJob`, D):
- `classic` — `*_classic`;
- `cylindrical` — `*_cylindrical`;
- `cylindrical_full` — оба набора (H, `DECISIONS.md`).

Каждая запись `settings` несёт:
- `source`:
  - `rule:<id>` — последнее правило, сдвинувшее значение;
  - `default:<профиль>` — правила не сработали;
  - `default:material:<id>` — значение из файла материала;
  - `search:itK` — значение изменено циклом на итерации K;
- `reason` — тексты сработавших правил;
- `rule_ids` — все правила оси, включая ограничения.

## 3. Параметры по отдельности

Пример — шестерня из `stage1_example.json`:
- требования: Tg «85–90» °C, жёсткость, гидрофобность, температура эксплуатации до 70 °C, все обязательные;
- допуск 0.15 мм — допущение, не обязательное;
- нагрузка циклическая, приоритет «прочность, затем точность»;
- материал `fiberpart_abs_g13`: сопло 270 °C, стол 100 °C, скорость 50 мм/с, обдув 0.

### 3.1 `printing_mode`
- **Вход:** требование `printing_mode` (`classic`/`cylindrical`/`cylindrical_full`) → `pref.printing_mode`. Ещё используются габариты `bbox_mm.size` и, если появятся, нависания вместе с жёстким `no_supports`.
- **Алгоритм.** Каждое правило голосует весом:
  - `mode-default-classic` — 1, confidence 0.6;
  - `mode-card-hint` — 10, 0.9;
  - `mode-overhang` (нависания > 0.05 и жёсткий запрет поддержек → `cylindrical`) — 2, 0.35.

  Голос режима, в котором деталь не помещается, не считается. Сравнение «как загружено»: `[X, Y, Z] ≤ [315, 300.3, H]`, где `H = 300` для classic и 250 для 5D. Побеждает наибольшая сумма весов, при равенстве — первый по алфавиту. Не поместилась нигде → `classic` с confidence 0.1, `unsatisfied: GEOMETRY` и `infeasible`.
- **Знание:** classic по умолчанию (S 4.3). Области печати из `steprinter530_v5.2` (D). Правило 5D — гипотеза (H). По коду (`CuraEngineBackend/StartSliceJob.py`) `cylindrical_full` режет модель цилиндром диаметра `cylindrical_mode_base_diameter`: внутренняя часть печатается в 3D, внешняя в 5D. Когда выбирать какой режим, из кода не следует.
- **Шестерня:** подсказки нет, нависания неизвестны → `classic`, `rule:mode-default-classic`.

### 3.2 `material`
- **Вход:** требование `material` (только `verified` и не `assumption`) или `answers.material_choice`. Для проверки используются требования `tg_min_c`, `service_temp_max_c`, `hydrophobic`, `uv_stable`, `chemical_resistance`, `flexible`, `density_max_g_cm3`, `low_friction`, `abrasion_resistant`, `high_stiffness`, `food_safe`, `esd`.
- **Алгоритм.**
  1. **Материал назван** и найден в каталоге (по id файла или `label`, без учёта регистра). Берём его (`source: card`) и проверяем по каждому требованию. Провал жёсткого требования (`fail`) идёт в `unsatisfied`.
  2. **Не назван или не найден** (во втором случае с предупреждением). Ранжируем пул `enduse_*`, `fiberpart_*`, `sealant_*`:
     - статус требования: `ok` 1, `warn` 0.4, `unknown` 0.3, `fail` 0;
     - вес: жёсткое 3, мягкое 1;
     - оценка — взвешенное среднее;
     - порядок: меньше провалов жёстких требований → выше оценка → id.

     Лучший идёт в `value` (`source: rank`), два следующих — в `alternatives`.
  3. **Конфликты.** Жёсткое требование, которое не выполняет ни один материал, и пара жёстких, которую ни один материал не выполняет одновременно, дают `unsatisfied` и `infeasible`.
- **Проверки:**
  - пороги Tg и температуры эксплуатации — `traits.json`;
  - гидрофобность — по гигроскопичности: low ok, medium warn, high fail;
  - УФ — по тексту описания, затем по `traits`;
  - химстойкость — поиск основ слов в описании;
  - плотность — `<density>` файла материала;
  - `food_safe` и `esd` — всегда `unknown`, уходят в допущения.
- **Знание:** плотность, температуры, скорость и описание — из файлов материалов (D). Tg, гигроскопичность, УФ, жёсткость, трение и износ — общие знания (`catalog/traits.json`, `verified: false`, G).
- **Шестерня:** `fiberpart_abs_g13`, оценка 1.00. Альтернативы — `enduse_abs` и `enduse_pc`.

### 3.3 Высота слоя: `classic_layer_height` (classic, cylindrical_full), `cylindrical_layer_height` (cylindrical, cylindrical_full)
- **Вход:** `dimensional_tol_mm`, `no_visible_layers`, первый приоритет.
- **Ось:**
  - `v0 = 0.8 · сопло = 0.32` мм (сопло 0.4 — из `stereotech_v5_extruder_main`, D);
  - `v1 = 0.10` мм, шаг 0.01.
- **Правила:**
  - `limit` — `layer<=0.8*nozzle` (D: `maximum_value_warning` у `layer_height`) и `layer>=0.10` (S);
  - `shift` — `priority-speed` −0.25, `priority-accuracy` +0.25, `tolerance-soft-fine-layer` +0.2 (мягкий допуск), `no-visible-layers-soft` +0.3;
  - `bound` — `tolerance-hard-fine-layer` (жёсткий допуск ≤ 0.15 мм) → `t ≥ 0.7`, `no-visible-layers-hard` → `t ≥ 0.9`.
- **Шестерня:** t = 0.5 + 0.2 = 0.7 → 0.32 − 0.7 · 0.22 = 0.166 → **0.17 мм**, `rule:tolerance-soft-fine-layer`. Приоритет «точность» второй, поэтому не учитывается.

### 3.4 `wall_line_count`
- **Вход:** первый приоритет, `part.load`, `high_stiffness`, `flexible`.
- **Ось:** 2 → 6 периметров, шаг 1. В определении это формула от `wall_thickness`; явное значение её перекрывает (D).
- **Правила:**
  - `limit` — `walls>=2` (S);
  - `shift`:
    - `priority-strength` +0.2, `priority-speed` −0.15, `priority-cost` −0.1;
    - `load-walls-beat-infill` +0.15 (циклическая или ударная нагрузка);
    - `stiffness-soft` +0.15;
  - `bound`:
    - `stiffness-hard` → `t ≥ 0.5`;
    - `flexible-soft-structure` → `t ≤ 0.5`.
- **Шестерня:** 0.5 + 0.2 + 0.15 = 0.85, нижняя граница 0.5 → 2 + 0.85 · 4 = 5.4 → **5**, `rule:stiffness-hard`.

### 3.5 `top_layers`, `bottom_layers`
- **Вход:** первый приоритет, `part.load`, итоговая высота слоя.
- **Алгоритм.** Ищется не число слоёв, а толщина сплошной кожи по оси 0.8 → 2.0 мм с шагом 0.1. Затем `слоёв = ceil(round(толщина / слой, 4))`, но не меньше 3 (`top-bottom>=3`, S). Обе записи получают одно значение. Так же считает и формула определения `top_layers = ceil(top_thickness / layer_height)` (D), но мы задаём результат явно.
- **Правила `shift`:** `priority-strength` +0.15, `load-walls-beat-infill` +0.1.
- **Шестерня:** t = 0.75 → 0.8 + 0.75 · 1.2 = 1.7 мм; 1.7 / 0.17 = **10** слоёв сверху и снизу.

### 3.6 `infill_sparse_density`
- **Вход:** первый приоритет, `high_stiffness`, `flexible`.
- **Ось:** 10 → 60 %, шаг 5 (G).
- **Правила:**
  - `shift` — `priority-strength` +0.1, `priority-speed` −0.15, `priority-cost` −0.2, `stiffness-soft` +0.15;
  - `bound` — `stiffness-hard` → `t ≥ 0.4`, `flexible-soft-structure` → `t ≤ 0.5`.
- **Шестерня:** 0.5 + 0.1 = 0.6 → 10 + 0.6 · 50 = **40 %**.

### 3.7 `infill_pattern`
- **Вход:** `part.load`, `flexible`, итоговая плотность.
- **Алгоритм:**
  - `gyroid`, если нагрузка циклическая или ударная либо деталь гибкая (`infill-gyroid-isotropic`, G);
  - иначе `grid` по умолчанию профиля, а при плотности > 25 % — `lines` (G).

  Вето валидатора переключает на следующий кандидат: grid, lines, gyroid, triangles, cubic, concentric. Все они есть в `options` определения (D).
- **Шестерня:** **gyroid**.

### 3.8 `material_print_temperature`
- **Вход:** `print temperature` из файла выбранного материала (= `default_material_print_temperature`, D), первый приоритет.
- **Ось:** T − 10 → T + 10 °C, шаг 5.
- **Правила:**
  - `limit` — `temp-in-material-window` (окно ±10 °C: в файле одно значение, см. DECISIONS) и `temp<=machine-max` (285 °C, `maximum_value_warning`, D);
  - `shift` — `priority-strength` +0.1.
- **Шестерня:** 260 + 0.6 · 20 = 272 → **270 °C** (шаг 5).

### 3.9 `speed_print`
- **Вход:** `speed print` из файла материала (V; если нет — 50 мм/с), первый приоритет, допуск, гибкость.
- **Ось:** V → 0.5 · V, шаг 5. От `speed_print` формулами определения выводятся `speed_infill_classic`, `speed_wall_0_classic` и др., их `StartSliceJob` подставляет в classic и `cylindrical_full` (D).
- **Правила:**
  - `shift` — `priority-speed` −0.2, `priority-accuracy` +0.15;
  - `bound` — `tolerance-hard-fine-layer` → `t ≥ 0.4`, `flexible-soft-structure` → `t ≥ 0.5`.
- **Шестерня:** правила не сработали → t = 0.5 → 50 − 0.5 · 25 = 37.5 → **40 мм/с**, `default:hte530v5.2`.
- **Оговорка:** XML-ключ `speed print` в `XmlMaterialProfile` не сопоставлен ни с одной настройкой (D). В слайсере файл материала скорость не задаёт, мы берём её только как ориентир.

### 3.10 `support_enable_classic` / `support_enable_cylindrical`
- **Вход:** `geometry.overhang_area_fraction`, `pref.supports_allowed` (по фразам «без поддержек» в `preferences`), жёсткий `no_supports`.
- **Алгоритм:**
  - `true` (`supports-on-overhang`), если доля нависаний > 0.05 (S 4.2 «> 45° — поддержки»; порог 0.05 — G), поддержки разрешены и нет жёсткого запрета;
  - иначе `false` (по умолчанию профиля);
  - нависания есть, а жёсткий запрет стоит → `unsatisfied: no_supports`.

  `StartSliceJob` подставляет `support_enable = support_enable_classic` (D).
- **Сейчас:** нависаний во входе нет, поэтому всегда **false**, с допущением в ответе.

### 3.11 `adhesion_type`
- **Алгоритм:** всегда `brim` (`adhesion-brim`; это значение по умолчанию `fdmprinter`, D). В `cylindrical` ключ не выдаётся (печать на цилиндрическом основании). Вето переключает на skirt, raft, none.

### 3.12 `material_bed_temperature`, `cool_fan_speed`
- **Алгоритм:** значения `heated bed temperature` и `print cooling` из файла материала. Это те же значения, что слайсер берёт из материала сам (`default_material_bed_temperature`, `cool_fan_speed`, D). Не ищутся: влияние обдува немонотонно и зависит от материала (DECISIONS). `cool_fan_speed` через формулы даёт `cool_fan_speed_min/max_classic` (D).
- **Шестерня:** стол **100 °C**, обдув **0 %**.

### 3.13 `build_volume_mm`, `orientation`
- `build_volume_mm` — область выбранного режима из `profile.hte530v5.2.json` (D).
- `orientation` всегда `null`: ориентация не подбирается, модель берётся «как загружена».

## 4. Проверка и статус

`hard_rules.py` независимо от поиска проверяет:
- слой ≤ 0.8 · сопло;
- периметров ≥ 2;
- слоёв кожи ≥ 3;
- температура ≤ 285 и в окне материала;
- режим известен.

Статус:
- `infeasible` — конфликт материалов, правил или области печати;
- иначе `proposed`;
- после вердикта — раздел 5.

В `assumptions_used` попадают:
- оговорки приёма: preliminary, единицы, нависания, нераспознанные обязательные требования, выводы из свободного текста;
- допущения этапа 1;
- требования-допущения;
- непроверенные свойства материала.

## 5. Цикл с валидатором (`loop.py`, `strategies/`)

`issues[].key` по индексу ключей указывает ось. Сигнал `too_weak` сдвигает `t` вверх, `too_costly` — вниз. Шаг задаёт стратегия:
- **M1** — интервал и бисекция по каждой оси;
- **M2** — шаг по `severity` и росту `score`;
- **M3** — один скаляр для всех «силовых» осей;
- **M4** — три готовых кандидата;
- **M5** — M1, но ось, которую обвиняют в обе стороны или которая упёрлась в границу, не двигается.

Вето запрещают значение дискретной настройки. Валидатор вызывается не более N раз (по умолчанию 3):
- `ok` → `final`;
- бюджет исчерпан → `exhausted` с лучшей точкой и открытыми замечаниями;
- противоречивые замечания → `infeasible`.

Состояние держит вызывающая сторона. `idempotency_key` привязывает его к ревизии карточки. Результаты стратегий на заглушке валидатора — в `experiments/`.

## 6. Расхождения с устройством (проверено по клону; не исправлено)

| Что | Факт из STE-Slicer | Последствие |
|---|---|---|
| `material_bed_temperature` выдаётся и в 5D | `steprinter_v5`: `machine_heated_bed = printing_mode in ['classic']` | в 5D лишний ключ, слайсер его игнорирует |
| `target: global` у `material_print_temperature`, `cool_fan_speed` | `settable_per_extruder: true` | как этап 4 применит их к экструдеру, не согласовано (открытый вопрос 3) |
| нет `cylindrical_mode_base_diameter` | диаметр основания 5D (по умолчанию 6, минимум 4); по нему режется модель в `cylindrical`/`cylindrical_full` | в 5D остаётся 6 мм; нужен диаметр отверстия от этапа 1 |
| не выбирается профиль качества | у hte530v5.2 своих quality нет; общие `quality/*.inst.cfg`: слой 0.06/0.1/0.15/0.2/0.3 | слой 0.17 вне сетки профилей; жюри сравнивает «профиль» |
| `orientation = null` | жюри сравнивает ориентацию и расположение | нужны нависания по направлениям |

## 7. Что проверено, а что нет

**Проверено:**
- ключи есть в `fdmprinter.def.json`, формулы, через которые они влияют, прочитаны в `StartSliceJob` (D);
- вывод детерминирован;
- жёсткие правила не нарушаются (E2E);
- приём карточки v1.1 покрыт E2E (`test_stage1_input.py`).

**Не проверено:**
- что значения хороши: нет эталонов, настоящего слайсера и валидатора;
- диапазоны осей и сдвиги правил (G);
- свойства полимеров (G);
- выбор 5D (H);
- единицы при `unknown`;
- нависания и ориентация — данных нет;
- смысл свободного текста этапа 1 — читается по фразам словаря.

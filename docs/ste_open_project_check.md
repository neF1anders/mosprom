# Проверка файлов Фёдора в STE Slicer 7.10.12 (выданная сборка)

Принтер: Stereotech Hybrid 530 V5.2.4 (в сборке есть и V5.2, эксперт на чек-поинте назвал V5.2.4). Проверено 23.10.2026 на реальном слайсере, открытие через те же функции, что и меню File → Open.

## Таблица

| Папка | A (STL) | B (оригинал Cura) | C (конвертированный) |
|---|---|---|---|
| 1 Business Card Holder | открылся, 56.7 × 114.0 × 38.7 мм | не проект, открылась только модель (2 объекта: 56.7 и 14.9 мм по X), настройки не применились | отказ как проект, открылась только модель |
| 2 Artemis Single | открылся, 90.9 × 90.9 × 12.7 мм | не проект, только модель | отказ как проект, только модель |
| 3 Batarang | открылся, 197.0 × 81.5 × 8.0 мм | не проект, только модель (2 объекта: 197.0 и 160.2 мм) | отказ как проект, только модель |
| 4 BOSS Gear | открылся, 90.9 × 90.9 × 12.7 мм | не проект, только модель | отказ как проект, только модель |
| 5 BOSS500 PLA | открылся, 472.8 × 187.7 × 11.5 мм (шире стола 351 мм по X) | не проект, только модель (2 объекта: 472.8 и 384.6 мм) | исключение при чтении, только модель |

Окна «Open as project» для B не было: слайсер ищет в архиве папку `SteSlicer/`, а в B лежит только `Cura/`, поэтому считает файл обычным 3MF.

Для C окно не появилось, слайсер написал в лог (текст дословно):
- папки 1, 2, 3, 4: `Could unknown machine definition None in project file <путь>`. Слайсер нашёл папку `SteSlicer/`, но в ней нет определения принтера (`machine definition` = None), поэтому проект отклонён.
- папка 5: исключение при чтении: `ThreeMFWorkspaceReader.py, line 366, in preRead: quality_type = instance_container_info_dict[quality_container_id].parser["metadata"]["quality_type"]` (не нашёлся контейнер качества с нужным id).

Нарезку (Slice) файлов из папок 1-5 я не запускал, потому что B и C как проекты не открылись. Нарезка проверена на нашем кубе и на проекте ниже собранном самим слайсером.

## Самое ценное: настоящий проект нашего слайсера

Файл `project_hybrid530_PLA_Normal_0.2_infill30_support.3mf` (219 КБ): принтер Hybrid 530 V5.2.4, модель `A_model.stl` из папки 1, материал PLA generic, профиль **Normal**, слой 0.2, заполнение 30%, поддержки включены. Он открывается обратно как проект.

Окно Summary (данные диалога при открытии этого файла): имя и тип принтера Stereotech Hybrid 530 V5.2.4, тип сопла Nozzle, профиль Normal (`quality_type = fast`), материал PLA, режим «Custom», пользовательских настроек 5.

### Как устроен проект (что нужно воспроизвести при конвертации)

Корневая папка называется `SteSlicer/`. Внутри:

- `Stereotech Hybrid 530 V5.2.4.global.cfg`: описание принтера, секция `[containers]` с номерами `0 = ..._user`, `1 = empty_quality_changes`, `2 = fast`, `3 = empty_material`, `4 = empty_variant`, `5 = ..._settings`, `6 = hte530v5.2.4`.
- `Stereotech Hybrid 530 V5.2.4_user.inst.cfg`: пользовательские настройки уровня принтера: `layer_height = 0.2`, `printing_mode = classic`, `support_enable = True`.
- `stereotech_v5.2.4_extruder_main #2_user.inst.cfg` и `..._extruder_second #2_user.inst.cfg`: настройки уровня экструдера, здесь лежит `infill_sparse_density = 30.0` (в каждом из двух экструдеров).
- `stereotech_v5.2.4_extruder_main #2.extruder.cfg` (и `second`): экструдер; в `[containers]` указан материал `3 = generic_pla_175` и качество `2 = fast`.
- `fast.inst.cfg`: профиль качества (`name = Normal`, `quality_type = fast`, `definition = fdmprinter`).
- `generic_pla_175.xml.fdm_material`: материал.
- `hte530v5.2.4.def.json` (≈530 КБ), `stereotech_v5.2.4_extruder_main.def.json` и `..._second.def.json`: определения принтера и экструдеров внутри файла.
- `Stereotech Hybrid 530 V5.2.4_settings.inst.cfg`, `..._extruder_..._settings.inst.cfg`: контейнеры `definition_changes`.
- `preferences.cfg` (видимые настройки) и `version.ini` (`steslicer_version = 7.10.12`).
- Вне папки: `3D/3dmodel.model`, `[Content_Types].xml`, `_rels/.rels`.

### Важные детали для конвертации

1. Названия профилей в интерфейсе не совпадают с внутренними: «Normal» это `quality_type = fast`; `normal` показывается как «Fine»; `high` как «Extra Fine»; `draft` как «Draft»; `coarse` как «Coarse»; `verydraft` как «Extra Fast».
2. Настройки лежат в разных контейнерах: `layer_height`, `printing_mode`, `support_enable` в `user` принтера; `infill_sparse_density` и подобные в `user` каждого экструдера (в этой сборке два экструдера: main и second).
3. Определение принтера (`hte530v5.2.4.def.json`) и экструдеров обязательно должно лежать внутри архива. В конвертированных файлах Фёдора этого не хватает: слайсер пишет `machine definition None`.
4. Диапазоны допустимых значений уже собраны в `validation/docs/ste_allowed_values_hybrid530_v52.md` (Фёдор).

## Что добавлено в плагин

Инструмент `open_project` открывает любой `.3mf` как это делает пользователь и возвращает данные окна Summary. Им можно прогонять конвертацию автоматически: нужно только запущенное приложение и плагин.

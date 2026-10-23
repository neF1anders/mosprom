# Реестр фич

Только реализованные возможности основного решения. Новую фичу и её E2E-проверку добавляем вместе; при удалении фичи удаляем строку.

| ID | Что умеет пользователь | E2E-проверка |
| --- | --- | --- |
| F-TUNE-1 | Карточка этапа 1 → набор параметров `stage2.parameter_set` v0.1 для Hybrid 530 V5.2.4 в 3D: режим, профиль качества, материал под пруток 1,75 мм, только отличия от профиля и материала с `why`/`source`, положение модели (CLI `python -m tuning select --input`) | `tests/e2e/tuning/test_parameter_set_classic.py` |
| F-TUNE-2 | Режим 5D из карточки → `cylindrical`/`cylindrical_full` с ключами режима, без температуры стола, область печати 5D (эллипс, 231,1 мм); не помещается — остаётся 3D с объяснением | `tests/e2e/tuning/test_parameter_set_5d.py` |
| F-TUNE-3 | Обратная связь этапа 3 (`stage3.feedback`) → второй и последний заход: ограничения `eq/ne/min/max/in` применены или явно помечены неприменёнными в `applied_constraints` (`--feedback`) | `tests/e2e/tuning/test_feedback.py` |
| F-TUNE-4 | Несовместимые обязательные требования или ограничение против требования → `status: infeasible` с парой в `unsatisfied` | `tests/e2e/tuning/test_infeasible.py` |
| F-TUNE-5 | Та же карточка и обратная связь → побайтово тот же JSON | `tests/e2e/tuning/test_determinism.py` |
| F-TUNE-6 | Приём карточки этапа 1 v1.1: отказ для `blocked`, чужого STL, карточки без отчёта; `card_ref` из ключа задания; допущения входа — в `assumptions` | `tests/e2e/tuning/test_stage1_input.py` |

Вики в `research/wiki/` — справочные материалы и в этот реестр не входит.

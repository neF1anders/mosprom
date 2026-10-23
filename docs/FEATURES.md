# Реестр фич

Только реализованные возможности основного решения. Новую фичу и её E2E-проверку добавляем вместе; при удалении фичи удаляем строку.

| ID | Что умеет пользователь | E2E-проверка |
| --- | --- | --- |
| F-TUNE-1 | Карточка задачи + STL → набор настроек STE Slicer в режиме `classic` с источником и основанием у каждой записи (CLI `python -m tuning select`) | `tests/e2e/tuning/test_select_classic.py` |
| F-TUNE-2 | Карточка с 5D → ключи `*_cylindrical` и ограничения области печати 5D | `tests/e2e/tuning/test_select_5d.py` |
| F-TUNE-3 | Вердикт валидатора → следующая итерация; `ok` → `final`; лимит N исчерпан → `exhausted` с причинами, не `final` | `tests/e2e/tuning/test_validator_loop.py` |
| F-TUNE-4 | Несовместимые жёсткие требования → `infeasible` с парой требований | `tests/e2e/tuning/test_infeasible.py` |
| F-TUNE-5 | Тот же вход и сид → побайтово тот же JSON | `tests/e2e/tuning/test_determinism.py` |

Вики в `research/wiki/` — справочные материалы и в этот реестр не входит.

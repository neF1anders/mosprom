# Вики: ИИ-решения для FDM 3D/5D-печати

Oct 20, 2026 · @Fedor

## Обзор

Готовых компонентов для кейса много, а цельного решения «STL + фото + запрос → оптимальные параметры → G-код → парк принтеров» мы не нашли; ближайший цельный проект — Kiln. Вики собирает всё найденное по компонентам и по цельным сборкам, чтобы выбрать, что брать, а что писать самим.

Каждая статья построена одинаково: что это, как работает, что умеет, зрелость и лицензия, ограничения, источники. Оценки в сравнительной таблице (отдельный файл Google Sheets) — по шкале 0–5 по пяти критериям: покрытие кейса, зрелость, открытость и лицензия, интегрируемость в MCP-сервер, подтверждённость данных.

Ограничения исследования: основа — README, статьи и страницы проектов; код проектов мы не запускали. Данные, которые прочитаны только по пересказу страницы, помечены словом «по пересказу». Часть репозиториев GitHub из рабочей среды недоступна, поэтому для них опираемся на описания на других площадках.

## MCP-серверы управления принтерами и слайсерами

Готовые MCP-серверы уже умеют «дать ИИ руки»: запускать слайсер и командовать принтером. Решения о параметрах при этом принимает подключённая LLM, а не сам сервер (исключение — PrusaMCP с функцией рекомендации профиля).

| Проект | Что делает | Принтеры и слайсеры | Лицензия и зрелость |
| --- | --- | --- | --- |
| [mcp-3D-printer-server](https://mcpservers.org/ru/servers/DMontgomery40/mcp-3D-printer-server) | Инструменты: статус принтера, загрузка G-кода, старт и отмена печати, температура, `slice_stl`, `print_3mf`, простые правки STL (`scale_stl`, `lay_flat`). Перед стартом печати и нагревом требует подтверждения человека | OctoPrint, Klipper/Moonraker, Bambu Lab (больше всего проверен), PrusaLink, Duet, Repetier, Creality; PrusaSlicer, Slic3r, OrcaSlicer, CuraEngine, Bambu Studio | GPL-2.0, npm 1.2.12; тип принтера задаётся переменной, управление парком в описании не показано |
| [Cura MCP](https://cdn.jsdelivr.net/gh/AuraFriday/cura_mcp@main/README.md) | Плагин, через который ИИ управляет Cura: загрузка и поворот моделей, настройки, нарезка, пакетная нарезка, сравнение времени, оптимизация ориентации, база истории печати. Есть сценарии с подтверждением | Только Cura (5.11+); принтер-бэкенды в README не перечислены | Проприетарная; требует отдельный MCP-Link; всё локально |
| [PrusaMCP](https://glama.ai/mcp/servers/Noosbai/PrusaMCP) | 17 инструментов: анализ сетки, проверка пригодности к печати, `recommend_profile` (по намерению, соплу, материалу с обоснованием каждой настройки), нарезка, постобработка G-кода, загрузка, обратная связь | Только PrusaSlicer; PLA, PETG, ABS, ASA, TPU, Nylon, PC; OctoPrint и PrusaConnect | MIT, v1.0.0 (февраль 2026); в каталоге помечен как неактивный (по пересказу); логика рекомендаций не раскрыта |
| [Hermes-Skills (Flashforge)](https://www.fabbaloo.com/news/ai-agent-3d-printing-project-shows-automated-printer-control) | Навыки для агента Hermes: нарезка в OrcaSlicer, исправление проблем G-кода Flashforge, загрузка и запуск, учёт до 4 катушек; отдельный навык превращает наброски в OpenSCAD | Только Flashforge AD5X; один принтер, без очереди | Открытый, бесплатный, демо-проект (сентябрь 2026) |

**Как это устроено.** Сервер публикует инструменты с описанием, LLM выбирает нужный и передаёт аргументы. Вызов `slice_stl` запускает консольный слайсер в фоне, а вызовы `start_print` и `get_printer_status` — API принтера (OctoPrint, Moonraker и др.). Нарезает модель именно слайсер; разные слайсеры дают разный G-код из-за разных алгоритмов и профилей.

**Что брать.** `mcp-3D-printer-server` — база для связи с принтерами и слайсерами (но лицензия GPL: лучше запускать как отдельный сервис). PrusaMCP — пример того, как оформить рекомендацию профиля с объяснением. Cura MCP закрыт и привязан к рабочему столу — для серверной сборки не подходит.

**Ограничения.** Автоматический подбор настроек под цель в этих серверах, кроме PrusaMCP, не описан; по печати на нескольких принтерах одновременно данных нет.

## Подбор параметров печати

Это главное «белое пятно» рынка: есть три подхода (правила, одноразовый ответ LLM, цикл «слайсер оценивает — LLM корректирует»), но все готовые реализации привязаны к одному слайсеру, а фото как вход есть только у коммерческих сервисов.

| Решение | Как подбирает | Вход | Слайсер | Зрелость |
| --- | --- | --- | --- | --- |
| [LLMs as Tuning Experts (CMU, 2026)](https://arxiv.org/html/2603.22118v1) | Слайсер прогоняется в цикле, выдаёт оценку (время, стоимость пластика, штраф за качество) и диагностику; LLM выбирает одну проблему и предлагает правки; байесовская оптимизация настраивает ориентацию и 13 параметров | LLM видит только диагностику и список допустимых правок, не геометрию | Слайсер (какой именно, не уточнено), печать на Prusa i3 MK3S | Исследование; на 100 деталях Thingi10k лучшая конфигурация в 78% случаев против 15% «вероятных провалов» у чат-базовых моделей (по пересказу); код не найден |
| [slicer-copilot](https://github.com/pfrankov/slicer-copilot) | LLM по цели (баланс, прочность, качество, скорость, своя) предлагает правки настроек с пояснением причин; есть `--dry-run` | `.3mf` Bambu Studio, цель, заметки; в LLM уходит сводка и превью пластины | Только Bambu Studio | Apache-2.0, экспериментальный, 12 звёзд, 7 коммитов |
| [PrusaMCP `recommend_profile`](https://glama.ai/mcp/servers/Noosbai/PrusaMCP) | Рекомендация профиля по намерению, соплу, материалу и анализу сетки; с обоснованием, опирается на базу знаний и лимиты скорости материалов | STL/3MF, намерение, материал | Только PrusaSlicer | MIT, v1.0.0; эвристики не раскрыты |
| [SliceHub (MIT CSAIL)](https://hcie.csail.mit.edu/research/slicehub/slicehub.html) | Заранее оценивает время и расход материала при 16 профилях слоя × 16 масштабах; нарезает 10% и досчитывает полиномом; показывает компромиссы в Cura | STL, принтер, материал, границы времени/материала | Cura 3.6 plugin | Прототип; без LLM, без проверки успеха печати |
| [Cura MCP](https://cdn.jsdelivr.net/gh/AuraFriday/cura_mcp@main/README.md) | Нет встроенной логики подбора: LLM сама меняет настройки Cura; встроены ориентация и сравнение времени | Ввод пользователя | Cura | Проприетарный |

**Что отличает сильный подход.** Работа CMU не просит LLM «угадать» числа: проверяемый слайсер даёт объективную оценку, LLM объясняет направление поиска, а оптимизатор подбирает значения. Именно это лучший прототип архитектуры для нашего модуля подбора.

**Ограничения.** В CMU оценка «качества» — эвристика, физическая проверка качественная, только некоторые параметры тюнятся. Фото как вход для подбора есть только в коммерческих веб-сервисах ниже и сводится к диагностике уже дефектной печати.

**Дополнительные решения (в основном маркетинговые страницы, метод не раскрыт).**

| Решение | Что делает | Вход | Деньги и лицензия | Ограничения |
| --- | --- | --- | --- | --- |
| [Ask The Nozzle](https://askthenozzle.com/blog/ai-3d-printing-assistant-chat-what-actually-works-and-whats-just-hype/) | Комплект: Diagnose (зрение по фото дефекта + данные принтера и филамента → правки настроек), Pre-flight (правиловая проверка G-кода), чат на базе случаев, вывод `.ini`-патчей для PrusaSlicer и OrcaSlicer и собственный ATN Slicer (форк OrcaSlicer, AGPLv3) | Фото, описание проблемы, принтер, филамент | Кредиты, 30 бесплатных при регистрации | Статья — блог самого вендора; авторы признают нестабильную точность, перекос в сторону Cura/Ender 3 и слабость на новых случаях |
| [Slice Foundry](https://slicefoundry.com/) | Генератор «оптимизированных» профилей для Cura, Orca, Flash Studio, Prusa, Bambu; «Fix My Print» | Фото, описание, файл настроек | Цены и лицензия не указаны | Маркетинг, метод не раскрыт |
| [FabFlow AI FDM Slicer](https://www.fabflow.app/labs/ai-fdm-slicer) | Онлайн-нарезка с «автоматическими настройками» и оценкой времени и пластика | STL, 3MF, OBJ; профили Bambu Studio | Бесплатно | Не раскрыто, как выбираются параметры; только метаданные страницы |
| [sliceoptim](https://pypi.org/project/sliceoptim) | Байесовская оптимизация (гауссовский процесс) по оценкам качества от пользователя и оценкам времени; без LLM | Границы параметров, оценки | Apache-2.0, 0.1.2 (август 2021), бета, один автор | Работает через Slic3r (libslic3r), тесты только на Linux; есть предупреждение о физическом риске |

Страницы minimal3dp.com (OrcaSlicer Expert Assistant) и curaslicers.com запрещают автоматическое чтение, их методы не проверялись.

## Мониторинг и обнаружение дефектов

Здесь готовых решений больше всего: детекторы «спагетти» по камере есть у Obico, OctoEverywhere и SimplyPrint, встроенные системы — у Bambu и Creality, а исследователи CMU показали LLM-супервизора, который ещё и правит параметры на лету.

| Решение | Как работает | Железо и принтеры | Деньги и лицензия | Доказанность |
| --- | --- | --- | --- | --- |
| [Obico](https://www.obico.io/blog/ai-failure-detection-in-3d-printing/) | ML-модели на кадрах с камеры по интервалу, обучены на удачных и неудачных печатях; уведомление или пауза. Nozzle Ninja — камера на сопле, оценка первого слоя A–F | Klipper и OctoPrint (Creality K1, Sovol SV06/SV07, Elegoo Neptune 4, Qidi X и др.); камера, для самохостинга лучше GPU | Самохостинг бесплатно, Pro около $4/мес (по обзору 3dprinting.com); «открытый», лицензия в статье не названа | Цифры вендора: 89,8 млн часов мониторинга, 1 067 608 пойманных сбоев; точность не измерена |
| [LLM-3D Print (CMU)](https://arxiv.org/pdf/2408.14307) | После каждого слоя пауза, две камеры (сверху и спереди), LLM ищет дефекты и меняет скорость, поток, ретракты и температуру через API принтера; исходный G-код не меняется. Семь модулей (детектор, супервизор, планировщики, исполнители ReAct) | Klipper + Moonraker + Crowsnest + Mainsail, Ender 5 Plus и Ender 3, две камеры 1080p | GPT-4o и GPT-4.1 через API, LangChain/LangGraph; код не найден | В аннотации: экспертный уровень распознавания, раньше инженеров; числа по прочности — по пересказу; 15–45 с на слой; путает капли с паутинкой |
| Bambu Lab (встроенная) | Детекция «спагетти» по последним 10 кадрам, инспекция первого слоя Micro Lidar (X1-Carbon) | Только свои принтеры | В цене принтера | По обзору Obico; лучше работает с включённым светом камеры |
| Creality K1 Max (встроенная) | AI LiDAR и AI-камера | Только свои | В цене принтера | По обзору Obico |
| [OctoEverywhere Gadget / Nexus AI](https://www.obico.io/blog/ai-failure-detection-in-3d-printing/) | OctoEverywhere — безлимитный детект сбоев на бесплатном тарифе (до 3 принтеров); Nexus AI (Fiberpunk) — открытый плагин OctoPrint | OctoPrint, в том числе Bambu X1/P1/A1 у OctoEverywhere | Бесплатное до 3 принтеров; платные планы около $3,99–$9,99 в месяц | По обзору Obico и 3dprinting.com |
| [SimplyPrint](https://simplyprint.io/print-farms) | AI-детект сбоев и проверка очистки стола перед следующей печатью | Много брендов | Облако, бесплатно для 1 принтера | Только заявления вендора |
| [Kiln](https://github.com/codeofaxel/Kiln) | Снимки с камеры (`kiln snapshot`, `monitor_print`), «автоматическое восстановление после сбоев», возобновление с того же слоя; анализ изображений искусственным интеллектом в README не описан | Bambu, Moonraker, OctoPrint и др. | AGPL-3.0, часть функций в платных уровнях | README не показывает метрик |

**Главный вывод.** Для нашего проекта мониторинг лучше подключать (Obico с самохостингом или встроенные детекторы принтеров), а своё делать только слой LLM-реакции по идее CMU: детектор обнаружил → сервис решил, пауза или правка параметров.

**Ограничения.** Независимых тестов точности (ложные срабатывания, пропуски) у коммерческих решений не найдено; все цифры из блогов самих вендоров. В закрытых системах Bambu и Creality мало возможностей настройки.

## Управление парком принтеров и очередь

Единственный найденный продукт с автоматическим подбором принтера под задачу — SimplyPrint (облачный, платный, с REST API и MCP-сервером по заявлению вендора); открытые альтернативы либо управляют принтерами вручную, либо ограничены одним брендом.

| Решение | Что умеет | Принтеры | Деньги и открытость | Заметки |
| --- | --- | --- | --- | --- |
| [SimplyPrint](https://simplyprint.io/print-farms) | Общая очередь, запуск следующего задания одним кликом, AutoPrint, «умная маршрутизация» (задание попадает на принтер с нужным материалом, соплом и столом), права команды, техобслуживание, REST API + webhooks, Zapier/n8n, MCP-сервер, AI-детект сбоев | 130+ брендов, 610+ моделей (Bambu, Klipper, Prusa и др.) | Облако, бесплатно для 1 принтера, очередь на Pro и выше; цены не проверялись | Подбор работает на тегах, которые задаёт пользователь; маркетинговая страница самого вендора |
| [OctoFarm](https://www.pistack.xyz/posts/2026-06-06-self-hosted-3d-printer-farm-management-octofarm-obico-octoprint/) | Панель нескольких OctoPrint, ручное назначение заданий | OctoPrint (Marlin, Klipper, RepRapFirmware и др.) | Бесплатно, AGPL-3.0, самохостинг | Замедляется примерно свыше 12 принтеров; SimplyPrint пишет, что последний релиз был в 2022 году (слова конкурента) |
| [Obico Server](https://www.pistack.xyz/posts/2026-06-06-self-hosted-3d-printer-farm-management-octofarm-obico-octoprint/) | Детект сбоев плюс очередь; в таблице статьи названа «автоматической», без подробностей | OctoPrint, Klipper, Bambu | Бесплатно при самохостинге | Статья с партнёрскими ссылками; для GPU-режима нужна видеокарта |
| 3DPrinterOS, AstroPrint, Printago | Очереди, расписание, многопользовательский доступ (по 3dprinting.com); Printago, по данным SimplyPrint, — автоматизация заказов Etsy/Shopify | — | — | Подробно не читали; AstroPrint по словам SimplyPrint перезапускается у новых владельцев |
| Bambu Farm Manager, Bambuddy, Printerhive | Флот для Bambu: Farm Manager — бесплатный, только Windows и LAN; Bambuddy — открытый самохостинг; Printerhive — до 30 принтеров с калькулятором заказов | Bambu | Разное | Описания — словами SimplyPrint |
| Kiln | `kiln print *.gcode --queue`; парк — в платном уровне Business | OctoPrint, Moonraker, Bambu и др. | AGPL-3.0 + платные уровни | Выбор принтера по материалу в README не описан |
| Moonraker + Mainsail/Fluidd | API-сервер и веб-интерфейс для Klipper; нужны для управления по сети | Klipper | Бесплатно | Очереди по материалу нет, это только связь |

**Что означает «умный выбор».** В SimplyPrint принтер выбирается по правилам (материал, сопло, стол, размер и температуры), а не по данным LLM или анализу геометрии детали.

**Главный вывод.** Выбор принтера по правилам — задача на день работы: таблица принтеров (размер стола, сопло, загруженный материал, статус) и фильтр по этим полям. Реальная сложность — связь с разными API принтеров (OctoPrint, Moonraker, Bambu, PrusaLink), а не сам алгоритм распределения.

**Ограничения.** Большинство сравнений в источниках сделаны самим SimplyPrint, то есть стороной, заинтересованной в выводе. Данные форума Bambu Lab про управление несколькими принтерами устарели (2023–2024).

## Генерация 3D-моделей по тексту и фото

Есть два лагеря: меш-генераторы (быстрые, для фигурок, но без точных размеров) и «код → CAD» (LLM пишет OpenSCAD или CadQuery, точные размеры, но только простые детали). Для функциональных деталей подходит второй лагерь.

**Меш-генераторы (текст и фото → сетка)**

| Решение | Что умеет | Цена и лицензия | Заметки |
| --- | --- | --- | --- |
| [Meshy](https://www.meshy.ai/3d-printing) | Текст или фото → модель примерно за минуту; заявлены проверка герметичности и толщины стенок, авторемонт, разбиение крупных моделей, цвета для Bambu AMS; экспорт STL/3MF/OBJ; плагины для Bambu Studio, OrcaSlicer, Cura и др. | Бесплатные кредиты, платные планы (около $20/мес Pro по обзору); условия коммерческого использования в источниках противоречат друг другу | Маркетинг вендора; заявленные 97% проходят слайсер — цифра вендора |
| [Bambu MakerWorld × Meshy](https://filamentfeed.com/article/meshy-ai-text-to-3d-makerworld-june-2026) | Описать объект или загрузить фото в браузере, получить модель за 30–60 с, скачать STL/3MF или отправить на принтер Bambu | Доступ из браузера | Масштаб произвольный, плохо для сопряжённых и подвижных деталей |
| [Tripo, Rodin, Hunyuan3D, Sloyd, Luma Genie](https://3dprinting.com/software-guides/ai-3d-model-generators/) | Tripo: STL/3MF, около $12/мес при годовой оплате; Rodin: оплата за скачивание; Hunyuan3D — открытая, запускается локально на GPU; Sloyd — пресет для печати; Luma Genie — бесплатно, концепты | Цены приблизительные; бесплатные тарифы Meshy и Tripo — некоммерческие | Обзор отмечает: «почти ни одна не даёт модель без дочистки»: тонкие стенки, нет основания, масштаб произвольный |

**Код → CAD (LLM пишет скрипт модели)**

| Решение | Подход | Выход | Зрелость |
| --- | --- | --- | --- |
| [PrintPal CAD agent](https://printpal.io/resources/cad-agent-but-the-prompts-double) | Чат-агент пишет параметрический OpenSCAD (BOSL2, MCAD); заявлена проверка печатибельности | STL, 3MF, STEP | Промо-страница (2026-08-07), платный (кредиты); ограничения не названы |
| [text-2-cad](https://github.com/roberto-ceraolo/text-2-cad) | LLM пишет OpenSCAD, необязательно RAG по документации | OpenSCAD-код | 13 звёзд, 4 коммита; README: «наивная реализация», только простые формы |
| [DesignBench (разбор ZenML)](https://zenml.io/llmops-database/llm-powered-3d-model-generation-for-3d-printing) | Несколько LLM (GPT-4o, Claude Sonnet 3.5, Llama 3.1 70B) параллельно пишут OpenSCAD | STL | Прототип 2024; автор называет пространственное мышление LLM «очень плохим» |
| [Generative AI for CAD Automation (arXiv 2508.00843)](https://arxiv.org/html/2508.00843v1) | GPT-4 пишет скрипты FreeCAD, ошибки возвращаются в цикл исправления | FreeCAD-модели | 10 тестов; простые и средние детали получаются, сложные с множеством ограничений — нет |
| [CadQuery, OpenSCAD, Zoo ML-CAD](https://www.getleo.ai/blog/open-source-text-to-cad-tools-free) | CadQuery — BRep, экспорт STEP; OpenSCAD — CSG, STL; Zoo — прямое предсказание сетки, грубо по размерам | STEP, STL, сетка | Статья коммерческого вендора (Leo AI), выводы осторожно |
| [Canterbury-Press: руководство](https://github.com/cplanow/Canterbury-Press/blob/main/docs/research/ai-3d-printing-design-guide.md) | Обзор подходов и правил проектирования FDM (нависания 45°, минимальная стенка 0,8 мм, зазор 0,2 мм на сторону) | — | Личный репозиторий, 1 звёзда; автор пишет, что готового конвейера OpenSCAD → P1S нет |
| [Kiln](https://github.com/codeofaxel/Kiln) | Текст или набросок → генерация → проверка → нарезка → печать; провайдеры OpenSCAD и Meshy/Tripo/Stability/Gemini; фото только как рельеф на поверхности | STL, G-код | AGPL-3.0, без бенчмарков |

**Главный вывод.** Для нашего проекта генерация — необязательный бонус: условие кейса даёт готовую STL. Если делать, то функциональные детали — через CadQuery или OpenSCAD с автоматической проверкой сетки, а фотореалистичные фигурки — через внешний сервис (Meshy, Tripo, Hunyuan3D).

**Ограничения.** Ни один измеренный тест пригодности к печати не найден у меш-генераторов: цифры — вендорские. Для «код → CAD» сама проблема — слабое пространственное мышление LLM (в трёх источниках названо прямо). Статья с «69,3% точного совпадения» для Text-to-CadQuery упомянута в обзоре Canterbury, саму статью мы не читали.

## Анализ и починка STL

Для анализа геометрии и починки сетки есть зрелые библиотеки в открытом доступе; готового модуля «найти нависания, тонкие стенки, подбрать ориентацию» на базе этих библиотек нужно дописывать самим (частично это есть в PrusaMCP, Meshy, Cura MCP).

| Библиотека | Что умеет | Лицензия и версия | Ограничения |
| --- | --- | --- | --- |
| [trimesh](https://pypi.org/project/trimesh/) | Загрузка и анализ сеток: проверка `is_watertight`, объём и центр масс, разбиение на компоненты, срез плоскостью, простые исправления нормалей и небольших дыр, экспорт STL | MIT; 5.1.1; статус Beta | Ремонт только простых дефектов; булевы операции требуют Manifold3D или Blender |
| [pymeshfix](https://pypi.org/project/pymeshfix/) | Ремонт «битых» сеток в единую замкнутую поверхность (обёртка MeshFix): `clean_from_file`, `MeshFix(v, f).repair()`, заполнение маленьких границ | 0.18.1; лицензия: в метаданных AGPL-3.0, в README — GPLv3 с коммерческой лицензией; оба варианта «заразные» | Предполагает одно замкнутое тело; на CAD-сетках может дать грубый результат |
| [numpy-stl](https://pypi.org/project/numpy-stl/) | Чтение и запись STL (бинарный и ASCII), повороты, смещения, массовые свойства (объём, центр тяжести) | BSD-3-Clause; по данным PyPI JSON версия 4.1.1 (страница проекта читалась как 4.0.1) | Нет проверки герметичности и ремонта |
| [FullControl GCode](https://pypi.org/project/fullcontrol/) | Не слайсер и STL не читает: описываете траекторию в Python, получаете G-код | GPLv3; 0.1.2 (2025), один майнтейнер | Структура репозитория может меняться; подходит для произвольных траекторий, в том числе экспериментов с 5D |

**Главный вывод.** Связка trimesh + pymeshfix закрывает проверку и починку; нависания, тонкие стенки и ориентацию считает ваш код поверх них. **Внимание:** pymeshfix имеет копилефт-лицензию (AGPL/GPL), для коммерческого закрытого продукта нужна коммерческая лицензия или другой ремонтер; для хакатона это не проблема.

**Что дописывать самим.** Расчёт углов нависаний (через нормали граней в trimesh), поиск тонких стенок, оценку объёма поддержек и выбор ориентации перебором поворотов.

## Слайсеры (CLI) и API принтеров

Нарезать модель можно без окна слайсера, а отправить G-код — через HTTP API хоста; только точные флаги командной строки нужно сверять на установленной версии.

| Инструмент | Как работать без окна | Проверено |
| --- | --- | --- |
| [OrcaSlicer](https://www.orcaslicer.com/wiki/index.html) | AGPL-3.0; в вики есть раздел CLI (Mode, Actions, Transform, Misc); отправка заданий на Klipper, PrusaLink, OctoPrint | Флаги не читали |
| PrusaSlicer | Консольный режим известен, но официальная страница не открылась | Не проверено |
| [Moonraker](https://moonraker.readthedocs.io/en/latest/web_api/) | Moonraker не режет, принимает G-код: `POST /server/files/upload` (параметр `print=true` запускает печать), `POST /printer/print/start`, `/pause`, `/resume`, `/cancel`; очередь заданий — `/server/job_queue/*`; авторизация `X-Api-Key` или JWT | Старт и загрузка — дословно, очередь — из пересказа |
| [OctoPrint](https://docs.octoprint.org/en/main/api/) | `POST /api/files/local` — загрузка (`select`, `print`); `POST /api/job` с `{"command":"start"}`; `GET /api/job` — статус; нарезка через плагин слайсера (в документации «единственный поддерживаемый» — Cura); авторизация `X-Api-Key` | Дословно |
| Bambu Lab, PrusaLink, Duet | Есть собственные протоколы; поддерживаются через mcp-3D-printer-server и Kiln | Не читали |

## 5D и непланарная печать

Готового продукта «ИИ подбирает 5D-параметры» не найдено: есть энтузиастские слайсеры, исследовательские работы и один коммерческий принтер за сотни тысяч долларов.

| Решение | Алгоритм | Железо | Доступность | Ограничения |
| --- | --- | --- | --- | --- |
| [S4 Slicer](https://www.fabbaloo.com/news/implications-of-the-s4-slicer-nonplanar-3d-printing-for-everyone) | Модель деформируется до вида без нависаний, режется обычным способом, затем G-код «раздеформируется»; классическая геометрия, без ИИ | 4-осевой Core R-Theta (открытый проект автора) | Открытый код на GitHub | Обычный FFF-принтер без нового железа не подойдёт |
| [Open5x](https://all3dp.com/4/open-source-5-axis-prusa-upgrade/) | Непланарный алгоритм в Grasshopper | Prusa i3 + доп. моторы (оси X, Y, Z, V, U), Duet3D | Железо открыто; слайсер требует платный Rhino | Слайсер не открыт; авторы сами пишут о необходимости свободного 5-осевого слайсера |
| [Neural Slicer](https://arxiv.org/pdf/2404.15061) | Нейросети задают поле поворотов и масштаба, из него получаются кривые слои; оптимизируются отсутствие поддержек, прочность, столкновения; расчёт до 15 минут на RTX 4080 | 6-осевая рука ABB IRB 2600 + позиционер (8 степеней свободы) | Код на момент публикации не опубликован | Изотропный анализ прочности; глобальные столкновения решаются цёной потери кривизны |
| [Slic3r NonPlanar](https://github.com/DrEricEbert/Slic3r_NonPlanar_Slicing) | Экспериментальные непланарные слои (по тезису Ahlers 2018) | Обычный 3-осевой FDM (конфиги Ender 3 Pro, Ender 5) | AGPL-3.0, ветка `nonplanar`, 78 звёзд | В README: C++-версия «не умеет генерировать G-код» |
| [Hamburg nonplanar (Ahlers)](https://3dprintingindustry.com/news/smooth-operation-eliminates-fdm-stair-stepping-in-university-of-hamburg-study-160826/) | Верхние поверхности печатаются непланарно с проверкой столкновений головы | 3 оси, Ultimaker 2 | Открытый код (2019) | Прототип |
| [PrusaSlicer non-planar fork](https://www.3printr.com/slicer-version-for-non-planar-3d-printing-released-0370841/) | Функция непланарной нарезки в PrusaSlicer 2.6 (автор — пользователь EiNSTeiN); задаётся максимальный угол и высота | 3-осевой FDM, нужны обходы по просвету хотэнда | Windows-сборка, лицензия не указана | Некоторые модели ненадёжно нарезаются |
| [Uni-slice (ITU)](https://polen.itu.edu.tr/items/a42ffe7d-2bed-458a-8284-30359a23f8ab) | Модульный пайплайн в Grasshopper (плоская и кривая нарезка) | 3-осевой FDM | Скрипты опубликованы, лицензия не указана | Магистерская диссертация 2022, без силовых тестов |
| [FullControl GCode](https://pypi.org/project/fullcontrol/) | Ручное описание траекторий на Python | Разное | GPLv3 | Не слайсер, STL не читает |
| VSHAPER 5AX | Коммерческий 5-осевой FDM-принтер | — | Цена по посту 2022 года — около $300 000 | Данные из одного форумного поста |

**Главный вывод.** Полноценная 5D-печать требует специального железа и незрелого слайсера, поэтому для хакатона разумно реализовать только аналитический слой: расчёт нависаний, угла наклона, оценка экономии поддержек и предложение 5D-стратегии для принтеров, которые её умеют, с откатом на обычный 3D-режим.

**Ограничения.** Большинство проектов — учебные или хоббийные; «5D» часто на деле непланарная печать на трёх осях. Важно не путать понятия: непланарные слои могут делаться и без дополнительных осей.

## Цельные сборки и конкуренты

Ни одна из найденных сборок не закрывает кейс целиком; ближе всего — Kiln (цепочка «генерация → нарезка → печать → очередь»), но в открытой документации у него не описаны подбор слайсерных параметров под цель и анализ фото как входа.

| Сборка | STL | Фото | Подбор по цели | Нарезка | Печать | Парк | Мониторинг | Генерация | 5D |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| [Kiln](https://github.com/codeofaxel/Kiln) | да | только рельеф | частично (материалы) | да | да | частично (платно) | частично | да | нет |
| [mcp-3D-printer-server](https://mcpservers.org/ru/servers/DMontgomery40/mcp-3D-printer-server) | да | нет | нет | да | да | не показано | статус | нет | нет |
| [PrusaMCP](https://glama.ai/mcp/servers/Noosbai/PrusaMCP) | да | нет | да (профиль) | да | через OctoPrint/PrusaConnect | нет | нет | нет | нет |
| [Cura MCP](https://cdn.jsdelivr.net/gh/AuraFriday/cura_mcp@main/README.md) | да | нет | через LLM | да | нет | нет | нет | нет | нет |
| [Hermes-Skills](https://www.fabbaloo.com/news/ai-agent-3d-printing-project-shows-automated-printer-control) | да | нет | нет | да | да (один принтер) | нет | нет | набросок → OpenSCAD | нет |
| [slicer-copilot](https://github.com/pfrankov/slicer-copilot) | да (.3mf) | нет | да | нет | нет | нет | нет | нет | нет |
| [Ask The Nozzle](https://askthenozzle.com/blog/ai-3d-printing-assistant-chat-what-actually-works-and-whats-just-hype/) | неполно описано | да (диагностика дефекта) | да (правки профиля) | свой ATN Slicer | нет | нет | предпечатная проверка G-кода | нет | нет |
| [CMU: LLM Tuning Experts](https://arxiv.org/html/2603.22118v1) | да | нет | да (цикл с оптимизатором) | в цикле | контрольные печати | нет | нет | нет | нет |
| [CMU: LLM-3D Print](https://arxiv.org/pdf/2408.14307) | — | камеры для контроля | коррекция на лету | нет | да | нет | да | нет | нет |
| [SimplyPrint](https://simplyprint.io/print-farms) | — | нет | нет | нет | да | да (умная маршрутизация) | AI-детект | нет | нет |
| [Meshy](https://www.meshy.ai/3d-printing) | экспорт | вход для генерации | нет | плагины слайсеров | кнопка «на Bambu» | нет | нет | да | нет |

**Kiln подробнее.** Движок — [github.com/codeofaxel/Kiln](https://github.com/codeofaxel/Kiln), пакет `kiln3d` 1.4.1.1 на PyPI, AGPL-3.0, 56 звёзд и 2 841 коммит по данным README-страницы. Заявлено: MCP-сервер для изготовления по описанию или наброску; 51 профиль безопасности принтеров, проверка G-кода, сторожевой таймер нагревателя, журнал аудита, возобновление печати с того же слоя, 25 материалов и 45 профилей нити с «рекомендациями по намерению», настроенные профили для 60 моделей принтеров. В README есть внутренние противоречия («908» и «915» инструментов, 68 и 51 профиль), часть функций — в закрытом модуле и платных уровнях, а полная документация на отдельном сайте мы не читали.

**Что умеет Kiln без учёта нашего кейса.** Рельеф из фото и QR-кодов на поверхности модели (подставка с портретом собаки), текст и процедурные текстуры. Это декор, а не анализ фото для настройки печати.

**Критический вывод.** Наша ниша — связка «анализ STL и фото → подбор параметров с проверяемым циклом → парк». Подбор по цели есть у PrusaMCP, slicer-copilot, CMU; фото-диагностика — у Ask The Nozzle и Slice Foundry; парк — у SimplyPrint и частично Kiln. Но вместе в открытом виде этого нет.

## Пробелы рынка и выводы для нашего проекта

Инфраструктура (библиотеки геометрии, API принтеров, слайсеры в CLI, MCP SDK) готова и зрела, а слабее всего решён именно то, что требует кейс: средний итог в категории «Подбор параметров» — 2,31 из 5, ниже всех остальных категорий, включая 5D (2,40).

| Категория | Лучший компонент | Итог (0–5) | Средний по категории |
| --- | --- | --- | --- |
| Слайсеры и API принтеров | Moonraker API, OctoPrint REST API | 4,25 | 3,89 |
| Анализ и починка STL | trimesh | 4,25 | 3,60 |
| Каркас сервера | MCP SDK (Python) | 3,95 | 3,95 |
| Генерация моделей | CadQuery + LLM | 3,70 | 3,15 |
| Управление принтерами и слайсерами (MCP) | mcp-3D-printer-server | 3,60 | 3,04 |
| Управление парком | SimplyPrint | 3,45 | 2,65 |
| Мониторинг и дефекты | Obico | 3,40 | 2,70 |
| 5D и непланарная печать | S4 Slicer | 2,90 | 2,40 |
| Подбор параметров | CMU: LLM как эксперт по настройке | 2,75 | 2,31 |

Оценки — из таблицы «fdm\_components\_comparison.xlsx» (35 компонентов, пять критериев с пересчитываемыми весами). Они субъективны, и низкий итог может быть у полезной идеи: работа CMU получила 2,75 только из-за отсутствия кода, по смыслу она самая ценная.

**Что брать готовым.** MCP SDK для каркаса, trimesh для анализа STL, OrcaSlicer или PrusaSlicer в консольном режиме для нарезки, Moonraker и OctoPrint API для управления, Obico для мониторинга. mcp-3D-printer-server и Kiln полезны как образцы архитектуры, но у обоих копилефт-лицензии.

**Что писать самим.** Расчёт нависаний и тонких стенок; модуль подбора параметров по цели (правила плюс цикл «слайсер оценивает — LLM корректирует» по идее CMU); анализ фото мультимодальной LLM в требования к детали; выбор принтера из парка по размеру стола, материалу и соплу; проверку G-кода (границы стола, температуры, аномалии); 5D-рекомендацию как аналитику (угол наклона, экономия поддержек), а не как полный 5-осевой G-код.

**Риски лицензий.** Kiln (AGPL-3.0), mcp-3D-printer-server (GPL-2.0), pymeshfix (AGPL/GPL) и FullControl (GPLv3) обязывают открыть код при встраивании; для хакатона это обычно не проблема, для коммерческого продукта — да.

**Что ещё нужно проверить.** Полную документацию Kiln (kiln3d.com/docs): как выбираются параметры и есть ли анализ кадров; флаги консольного режима OrcaSlicer и PrusaSlicer на установленной версии; есть ли код у работ CMU; цены SimplyPrint и условия Meshy.

## Источники

Страницы, которые были открыты при сборе (данные на 20 октября 2026). Для некоторых часть текста была доступна только как пересказ страницы, поэтому точные числа из статей стоит сверять с оригиналом.

- [LLM-3D Print: Large Language Models To Monitor and Control 3D Printing](https://arxiv.org/pdf/2408.14307)
- [Programming Manufacturing Robots with Imperfect AI: LLMs as Tuning Experts for FDM Print Configuration Selection](https://arxiv.org/html/2603.22118v1)
- [CMU Researchers Use AI to Autonomously Manage 3D Printing Workflows on FFF Systems (Fabbaloo)](https://www.fabbaloo.com/news/cmu-researchers-use-ai-to-autonomously-manage-3d-printing-workflows-on-fff-systems)
- [Neural Slicer for Multi-Axis 3D Printing](https://arxiv.org/pdf/2404.15061)
- [Generative AI for CAD Automation (arXiv 2508.00843)](https://arxiv.org/html/2508.00843v1)
- [mcp-3D-printer-server](https://mcpservers.org/ru/servers/DMontgomery40/mcp-3D-printer-server)
- [Cura MCP](https://cdn.jsdelivr.net/gh/AuraFriday/cura_mcp@main/README.md)
- [PrusaMCP](https://glama.ai/mcp/servers/Noosbai/PrusaMCP)
- [Kiln](https://github.com/codeofaxel/Kiln)
- [slicer-copilot](https://github.com/pfrankov/slicer-copilot)
- [SliceHub](https://hcie.csail.mit.edu/research/slicehub/slicehub.html)
- [sliceoptim](https://pypi.org/project/sliceoptim)
- [Ask The Nozzle](https://askthenozzle.com/blog/ai-3d-printing-assistant-chat-what-actually-works-and-whats-just-hype/)
- [Slice Foundry](https://slicefoundry.com/)
- [FabFlow AI FDM Slicer](https://www.fabflow.app/labs/ai-fdm-slicer)
- [Obico: AI failure detection](https://www.obico.io/blog/ai-failure-detection-in-3d-printing/)
- [Obico: AI spaghetti detection](https://www.obico.io/blog/tags/ai-spaghetti-detection/)
- [SimplyPrint: print farms](https://simplyprint.io/print-farms)
- [SimplyPrint: print queue](https://simplyprint.io/features/print-queue)
- [SimplyPrint: alternatives](https://simplyprint.io/alternatives)
- [3dprinting.com: host software](https://3dprinting.com/software-guides/3d-printer-host-software/)
- [Self-hosted farm management: OctoFarm vs Obico vs OctoPrint](https://www.pistack.xyz/posts/2026-06-06-self-hosted-3d-printer-farm-management-octofarm-obico-octoprint/)
- [Bambu Lab forum: multiple printers](https://forum.bambulab.com/t/software-that-allows-multiple-users-to-control-multiple-printers/25432)
- [AI agent 3D printing project (Fabbaloo)](https://www.fabbaloo.com/news/ai-agent-3d-printing-project-shows-automated-printer-control)
- [Meshy: 3D printing](https://www.meshy.ai/3d-printing)
- [Meshy × MakerWorld (FilamentFeed)](https://filamentfeed.com/article/meshy-ai-text-to-3d-makerworld-june-2026)
- [Best AI 3D Model Generators for 3D Printing (3dprinting.com)](https://3dprinting.com/software-guides/ai-3d-model-generators/)
- [PrintPal CAD agent](https://printpal.io/resources/cad-agent-but-the-prompts-double)
- [text-2-cad](https://github.com/roberto-ceraolo/text-2-cad)
- [Open-source text-to-CAD tools (Leo AI)](https://www.getleo.ai/blog/open-source-text-to-cad-tools-free)
- [Canterbury-Press: AI 3D printing design guide](https://github.com/cplanow/Canterbury-Press/blob/main/docs/research/ai-3d-printing-design-guide.md)
- [DesignBench (ZenML)](https://zenml.io/llmops-database/llm-powered-3d-model-generation-for-3d-printing)
- [trimesh](https://pypi.org/project/trimesh/)
- [pymeshfix](https://pypi.org/project/pymeshfix/)
- [numpy-stl](https://pypi.org/project/numpy-stl/)
- [FullControl GCode](https://pypi.org/project/fullcontrol/)
- [OrcaSlicer wiki](https://www.orcaslicer.com/wiki/index.html)
- [Moonraker Web API](https://moonraker.readthedocs.io/en/latest/web_api/)
- [OctoPrint REST API](https://docs.octoprint.org/en/main/api/)
- [S4 Slicer (Fabbaloo)](https://www.fabbaloo.com/news/implications-of-the-s4-slicer-nonplanar-3d-printing-for-everyone)
- [Open5x (All3DP)](https://all3dp.com/4/open-source-5-axis-prusa-upgrade/)
- [Slic3r NonPlanar Slicing](https://github.com/DrEricEbert/Slic3r_NonPlanar_Slicing)
- [Non-planar PrusaSlicer fork (3Printr)](https://www.3printr.com/slicer-version-for-non-planar-3d-printing-released-0370841/)
- [Uni-slice (ITU)](https://polen.itu.edu.tr/items/a42ffe7d-2bed-458a-8284-30359a23f8ab)
- [Conformal slicing on a 5-axis printer (FOIL.zone)](https://foil.zone/t/3d-printing-our-propellers-using-conformal-slicing-on-a-5-axis-3d-printer/17085)
- [University of Hamburg nonplanar slicing (3DPI)](https://3dprintingindustry.com/news/smooth-operation-eliminates-fdm-stair-stepping-in-university-of-hamburg-study-160826/)

Не открылись для автоматического чтения: minimal3dp.com (OrcaSlicer Expert Assistant), curaslicers.com, официальная страница PrusaSlicer CLI на help.prusa3d.com, GitHub-репозитории PrusaMCP и slicer-copilot (из рабочей среды).

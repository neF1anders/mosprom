NEW4=[
("prusaslicer-tuner (bullitt186)","Подбор параметров",[4,2,5,4,3],"MIT (код), CC BY 4.0 (знания), 0 звёзд, обновлён 16.10.2026","Агент читает, сравнивает и (с согласия) правит профили PrusaSlicer; есть MCP-сервер и граф знаний о дефектах FDM, привязанный к ключам PrusaSlicer и параметрам Klipper. Ближе всего к подбору параметров по симптому.","https://github.com/bullitt186/prusaslicer-tuner"),
("bambu-print-optimizer (rvelozo)","Подбор параметров",[4,2,2,3,3],"AGPL-3.0, 0 звёзд, обновлён 18.10.2026","Цель вроде «быстрее и легче, но не менее 90% прочности»: инструмент пробует настройки по одной через Bambu Studio, показывает вклад каждой и рекомендует набор с причиной. Только Bambu Studio.","https://github.com/rvelozo/bambu-print-optimizer"),
("orca-slicer-ai-optimizer (agentbenzox)","Подбор параметров",[2,1,5,2,2],"MIT, 0 звёзд, обновлён 24.07.2026","Пост-обработка G-кода из Orca, Prusa, Bambu Studio: правки предлагает Ollama или Claude, жёсткие защитные пределы по температуре, столу и обдуву. Правит готовый G-код, а не профиль.","https://github.com/agentbenzox/orca-slicer-ai-optimizer"),
("3dprint-oracle (gregario)","Подбор параметров",[3,2,5,4,3],"MIT, 1 звезда, обновлён 02.05.2026","MCP со знаниями о материалах: 7000+ филаментов (из SpoolmanDB), восемь инструментов, в том числе recommend_material и diagnose_print_issue. Данные встроены, сеть и ключи не нужны. Параметры слайсера не подбирает.","https://github.com/gregario/3dprint-oracle"),
("KlipperLearn","Подбор параметров",[3,1,2,3,2],"GPL-3.0-or-later по README (GitHub лицензию не определил), 7 звёзд","Калибровочные печати, измерение камерой и датчиками, по одному ограниченному изменению за попытку; версия 0.6.0 с MCP-инструментами. В README сказано: проверено только на имитации принтера.","https://github.com/Agnuxo1/KlipperLearn"),
("VerSlicer (WayMakerSchool)","Подбор параметров",[3,1,5,2,2],"MIT, 0 звёзд, обновлён 01.10.2026","Форк OrcaSlicer с локальным помощником на Ollama: «сделай прочнее» превращается в действия на столе слайсера. Только macOS.","https://github.com/WayMakerSchool/2026_VerSlicer_Checkered"),
("IgniteFuse","Слайсеры и API принтеров",[2,1,5,2,2],"Apache-2.0, 0 звёзд, обновлён 26.05.2026","Слайсер в виде кода: процесс описывается в файле .fuse.js, из него получается предпросмотр и G-код. Бета, авторы просят проверять G-код вручную.","https://github.com/tokoshie3d/IgniteFuse"),
("hermes-orcaslicer (mazzanfar)","Управление принтерами и слайсерами (MCP)",[4,2,5,3,4],"MIT, 3 звезды, релиз 0.5.0, обновлён 19.10.2026","Плагин для агента Hermes поверх обычного OrcaSlicer: профили, правки с копией проекта, нарезка, проверка плиты и сопла до отправки, отправка и наблюдение (Bambu LAN, PrusaLink, Duet). Нарезка проверена на Windows, macOS, Linux; физические печати авторы не заявляют.","https://github.com/mazzanfar/hermes-orcaslicer"),
("printable-mcp (ExaltedTrou6)","Управление принтерами и слайсерами (MCP)",[4,1,5,4,3],"MIT, 1 звезда, обновлён 27.07.2026","Цикл: OpenSCAD → рендер → измерения → отчёт о печатаемости с уровнями серьёзности → ориентация → нарезка → отправка и старт. Нарезка возвращает время, расход и предупреждения слайсера.","https://github.com/ExaltedTrou6/printable-mcp"),
("cadloop (richardofortune)","Управление принтерами и слайсерами (MCP)",[3,1,5,4,3],"MIT, 1 звезда, обновлён 04.08.2026","Два MCP-сервера: OpenSCAD → компиляция → проверка, что деталь входит в стол → нарезка → G-код. Шаг проверки смысла детали оставлен пользователю.","https://github.com/richardofortune/cadloop"),
("printd (riverray121)","Управление принтерами и слайсерами (MCP)",[3,1,5,4,3],"MIT, 0 звёзд, обновлён 06.09.2026","Служба печати: файл или ссылка → нарезка вашими профилями → правила (кайма, размещение, границы движения) → картинка на согласование → старт → наблюдение по фото камеры. Наблюдатель сам ничего не останавливает.","https://github.com/riverray121/printd"),
("cad-to-print-mcp (Kayrim)","Управление принтерами и слайсерами (MCP)",[3,1,5,4,3],"MIT, 0 звёзд, обновлён 03.10.2026","FreeCAD → STL → пресеты Orca (копии, оригиналы не трогает) → G-код → загрузка и отдельный запуск на Moonraker. Каждый запуск пишет хэши входа, команду, настройки и журнал. Модель по тексту не строит, другие принтеры не поддерживает.","https://github.com/Kayrim/cad-to-print-mcp"),
("PrintMCP (SourceBox-LLC)","Управление принтерами и слайсерами (MCP)",[3,1,5,4,3],"Apache-2.0, 5 звёзд, обновлён 08.09.2026","MCP на три уровня: поиск и скачивание модели (Thingiverse), нарезка, печать. Рядом PrintPal (MIT, 2 звезды) как готовая оболочка для агента.","https://github.com/SourceBox-LLC/PrintMCP"),
("claude-orcaslicer-mcp (ShreddyKrueger75)","Управление принтерами и слайсерами (MCP)",[3,1,5,3,2],"MIT, 3 звезды, обновлён 05.09.2026","Нарезка Orca без окна, пресеты, разбор G-кода и управление Elegoo Centauri Carbon. Сведения из описания репозитория, README не читал.","https://github.com/ShreddyKrueger75/claude-orcaslicer-mcp"),
("printing-mcp (nicholas-papachriston)","Управление принтерами и слайсерами (MCP)",[3,1,5,3,2],"MIT, 1 звезда, обновлён 21.10.2026","Blender, нарезка OrcaSlicer, проверка сетки и G-кода, управление Elegoo по LAN. Сведения из описания репозитория, README не читал.","https://github.com/nicholas-papachriston/printing-mcp"),
("mcp-printable (AaronGoldsmith)","Управление принтерами и слайсерами (MCP)",[3,1,5,4,2],"MIT, 2 звезды, обновлён 05.07.2026","MCP для моделирования и проверки печатаемости FDM, не привязан к конкретному агенту. Сведения из описания репозитория, README не читал.","https://github.com/AaronGoldsmith/mcp-printable"),
("bambustudio-mcp (subhashdasyam)","Управление принтерами и слайсерами (MCP)",[3,1,2,3,3],"AGPL-3.0, 2 звезды, обновлён 21.10.2026","STL или 3MF на входе, настроенный 3MF на выходе: осмотр геометрии, правка копии проекта, сравнение нарезок в Bambu Studio. Принтером не управляет; в репозитории есть страница с подтверждениями.","https://github.com/subhashdasyam/bambustudio-mcp"),
("prusactl (trevin-lee)","Управление принтерами и слайсерами (MCP)",[2,1,5,3,2],"MIT, 1 звезда, обновлён 10.10.2026","MCP поверх PrusaLink и Prusa Connect и консольная настройка. Сведения из описания репозитория, README не читал.","https://github.com/trevin-lee/prusactl"),
("print3d (mfranzon)","Генерация моделей",[3,1,5,3,3],"MIT, 21 звезда, обновлён 21.10.2026","Идея, фото или объявление → скрипт Blender → проверка сетки → нарезка Bambu Studio → проект 3MF. Только Bambu X2D с соплом 0,4; печатает человек из Studio.","https://github.com/mfranzon/print3d"),
("local-ai-cad-agent (neuronaline)","Генерация моделей",[3,1,5,2,3],"MIT, 16 звёзд, обновлён 12.10.2026","Параметрические модели из чата на OpenSCAD, локально через Ollama или через облако; код запускается в песочнице. Авторы называют проект хобби и пишут, что он силён на простых и средних деталях.","https://github.com/neuronaline/local-ai-cad-agent"),
("phyx3d (arielmiki)","Анализ и починка STL",[3,2,5,4,3],"MIT, 5 звёзд, есть пакет npm, обновлён 25.09.2026","Проверка STL, 3MF и gcode.3mf на нависания, плавающие части, тонкие стенки, опрокидывание и слабые места; расчёт прочности. Веб-страница, консоль с JSON и MCP-сервер.","https://github.com/arielmiki/phyx3d"),
("MeshRight (Huzy85)","Анализ и починка STL",[2,1,2,3,2],"GPL-3.0, 1 звезда, версия 0.2.0 на PyPI","Починка сетки для печати в браузере, без выгрузки файлов. Замена Meshmixer для новичков.","https://github.com/Huzy85/MeshRight"),
("bambuddy (maziggy)","Управление парком",[3,4,2,3,4],"AGPL-3.0, 3,1 тыс. звёзд, обновлён 22.10.2026","Свой сервер для Bambu Lab без облака: от одного A1 до парка в 40 принтеров, очередь, архив, учёт AMS и Spoolman, Home Assistant, MQTT, Prometheus, уведомления. Только Bambu.","https://github.com/maziggy/bambuddy"),
("bambu-sentinel-mcp (selcukgk29)","Управление парком",[3,1,2,3,2],"Лицензия не указана, 0 звёзд, обновлён 16.10.2026","MCP для Bambu в режиме LAN: очередь с учётом филамента, наблюдение, учёт расхода и стоимости. Рассчитан на парк, собран на одном A1.","https://github.com/selcukgk29/bambu-sentinel-mcp"),
("printago-skill","Управление парком",[3,2,2,4,3],"MIT (навык), 3 звезды; условия сервиса Printago не проверены","Навык Claude Code: через консоль printago управляет принтерами, заданиями, заказами, деталями, материалами. Работает только с сервисом Printago.","https://github.com/printago/printago-skill"),
("runsodin","Управление парком",[3,1,2,3,2],"Лицензия не определена, 4 звезды, обновлён 22.10.2026","Свой сервер для парка: Bambu Lab, Klipper, Prusa, Elegoo, без облака.","https://github.com/HughKantsime/runsodin"),
("filaops","Управление парком",[2,3,2,2,3],"Лицензия не определена, 80 звёзд, обновлён 22.10.2026","Учётная система для печатной фермы: склад, производство, продажи, закупки. Принтерами не управляет.","https://github.com/BLB3DPrinting/filaops"),
("OctoPrint-PiNozCam (DrAlexLiu)","Мониторинг и дефекты",[2,3,2,3,3],"AGPL-3.0, 61 звезда, обновлён 10.10.2026","Плагин OctoPrint: модель находит брак на самом Raspberry Pi по камере у сопла.","https://github.com/DrAlexLiu/OctoPrint-PiNozCam"),
("argus-monitor (v3rac1ty)","Мониторинг и дефекты",[2,1,2,3,2],"GPL-3.0, 0 звёзд, обновлён 05.10.2026","Поиск брака для Klipper: YOLO по камере и акселерометр по CAN. README разделён на две части, и первая описывает систему, какой она должна стать, а не то, что уже работает.","https://github.com/v3rac1ty/argus-monitor"),
("vigia_3d (rexcacayo)","Мониторинг и дефекты",[2,1,2,3,2],"GPL-3.0, 0 звёзд, обновлён 10.10.2026","Наблюдатель на Claude: разбор брака, безопасные поправки по ходу печати и управление из Telegram. Сведения из описания репозитория, README не читал.","https://github.com/rexcacayo/vigia_3d"),
("octoprint_printsheriff (xeonqq)","Мониторинг и дефекты",[2,1,2,3,2],"AGPL-3.0, 0 звёзд, обновлён 08.10.2026","Плагин OctoPrint: определение брака на устройстве без облака, уведомления через ntfy.","https://github.com/xeonqq/octoprint_printsheriff"),
("duetPrintGuard (stuartofmt)","Мониторинг и дефекты",[2,1,2,3,2],"GPL-2.0, 0 звёзд, обновлён 15.10.2026","Поиск брака для принтеров на Duet3D.","https://github.com/stuartofmt/duetPrintGuard"),
("kpoc/FDM-gcodes (Hugging Face)","Проверка G-кода",[1,3,2,3,3],"Лицензия «other», более 7,9 тыс. загрузок","Набор G-кода из PrusaSlicer, размер от 100 тыс. до 1 млн строк, формат parquet. Для обучения и проверки моделей по G-коду.","https://huggingface.co/datasets/kpoc/FDM-gcodes"),
("pycentauri (bjan)","Слайсеры и API принтеров",[2,2,2,3,3],"Лицензия не определена, 23 звезды, обновлён 16.07.2026","Python-клиент, консоль и MCP для Elegoo Centauri Carbon.","https://github.com/bjan/pycentauri"),
]

EXTRA4={
1:[
("VerSlicer (HSU-LEE)","https://github.com/HSU-LEE/VerSlicer","Ещё один проект с именем VerSlicer, AGPL-3.0, 1 звезда; описания нет, связь с версией WayMakerSchool не проверена.",0),
("hermes-kobra-s1","https://github.com/PermissionWest9850/hermes-kobra-s1","Настройка Hermes для Anycubic Kobra S1 с FreeCAD, OrcaSlicer, Moonraker и KlipperMCP; MIT, 10 звёзд.",1),
("KAI: Klipper AI Agent","https://github.com/meltiseugen/KAI---Klipper-AI-Agent","Агент для принтера на Klipper; лицензии нет, 1 звезда, README не читал.",0),
("mcp-raker (lexfrei)","https://github.com/lexfrei/mcp-raker","MCP для Moonraker: статус и управление принтером на Klipper; BSD-3-Clause, обновлён 22.10.2026.",1),
("MCP-KLIPPER (LauOtero)","https://github.com/LauOtero/MCP-KLIPPER","MCP для Klipper; GPL-3.0, 0 звёзд, описания в репозитории нет.",0),
("OpenGalatea","https://github.com/GLechevalier/OpenGalatea","MCP: от поиска модели в сети до нарезки и печати на Prusa; MIT, 19 звёзд.",1),
("OctoEverywhere/mcp","https://github.com/OctoEverywhere/mcp","Открытый MCP: состояние принтера, снимки камеры, управление; Apache-2.0, 38 звёзд, последнее обновление 03.07.2025.",1),
("catesworks/bambu-cli-mcp","https://github.com/catesworks/bambu-cli-mcp","Деление сетки, шипы-соединители, экспорт проекта Bambu Studio как инструменты для модели; MIT, 2 звезды.",1),
("welingtonmatos/bambu-studio-mcp","https://github.com/welingtonmatos/bambu-studio-mcp","Нарезка, раскраска, проверка через консоль Bambu Studio, настройки по типу детали; MIT, 0 звёзд.",1),
("BambuX1-print-MCPtools","https://github.com/ry32767/BambuX1-print-MCPtools","Управление X1 Carbon по LAN без облака, нарезка Orca без окна и MCP; только стандартная библиотека, лицензии нет.",1),
("bambu-studio-profile-mcp (till-muellers)","https://github.com/till-muellers/bambu-studio-profile-mcp","MCP для профилей Bambu Studio; AGPL-3.0, описания нет.",0),
("qidi-studio-mcp (VladYankovenko)","https://github.com/VladYankovenko/qidi-studio-mcp","MCP для профилей QIDI Studio; лицензии нет.",0),
("creality-slicer-mcp (sairaph)","https://github.com/sairaph/creality-slicer-mcp","MCP для Creality Print 7.2 и 7.3: пресеты, проекты 3MF, нарезка для K2; MIT.",1),
("creality-k2-mcp (sairaph)","https://github.com/sairaph/creality-k2-mcp","Статус, файлы, камера и управление с защитными условиями для Creality K2; MIT.",1),
("creality-printer-monitor (catmargiela)","https://github.com/catmargiela/creality-printer-monitor","Локальная панель и MCP для Creality Hi, K1, K2: статус, камеры, загрузка, нарезка, история; MIT.",1),
("orca-slicer-mcp (dmikushin)","https://github.com/dmikushin/orca-slicer-mcp","Управляет OrcaSlicer без окна через DBus на Xvfb: импорт, нарезка, экспорт; лицензии нет, 4 звезды.",1),
("orca-mcp (jeff-roche)","https://github.com/jeff-roche/orca-mcp","Обёртка над консолью OrcaSlicer; MIT, 1 звезда.",1),
("freecad-bambu-mcp (hyun2xyz)","https://github.com/hyun2xyz/freecad-bambu-mcp","FreeCAD → Bambu Studio с возобновляемыми заданиями и предпечатной проверкой; печать по LAN названа экспериментальной; MIT.",1),
("centauri-mcp (blanders2)","https://github.com/blanders2/centauri-mcp","MCP для Elegoo Centauri Carbon (SDCP 3.0); MIT, 0 звёзд.",1),
("linkyard (Venither)","https://github.com/Venither/linkyard","Клиент PrusaLink с очередью печати и MCP-адаптером; MIT.",1),
("mcp-toolkit (sk7n4k3d)","https://github.com/sk7n4k3d/mcp-toolkit","Небольшие MCP-серверы: PrusaLink и цепочка OpenSCAD → STL → G-код; MIT.",1),
("hermes-3d-print (vladthecto)","https://github.com/vladthecto/hermes-3d-print","Навык Hermes: CadQuery, превью в Blender, нарезка Bambu Studio для A1 mini; лицензии нет.",1),
],
2:[
("Reverse3D-tool (rellytechgame)","https://github.com/rellytechgame/Reverse3D-tool","Фото, чертежи и сканы в измеренную модель и параметрический код OpenSCAD или CadQuery через MCP; Apache-2.0, 1 звезда.",1),
("Img2CAD (qq456cvb)","https://github.com/qq456cvb/Img2CAD","Код к методу «изображение в CAD»; MIT, 39 звёзд.",1),
("img2cad (PyPI)","https://pypi.org/project/img2cad/","Изображения и чертежи в CAD (STEP, GLB, STL, 3MF) с рабочим процессом агента; версия 0.17.0.",1),
("vibe-cading (fa-mc)","https://github.com/fa-mc/vibe-cading","Генераторы моделей на CadQuery для людей и агентов; AGPL-3.0, 8 звёзд.",1),
("Cadless","https://github.com/cadlesslab/Cadless","Описание детали словами в точное параметрическое тело на build123d, экспорт STEP и STL; MIT.",1),
("cadquery-agent (benisalla)","https://github.com/benisalla/cadquery-agent","Локальный агент: текст или картинка в проверенную деталь CadQuery, песочница, итерации; MIT.",1),
("eitri (SiddhuYen)","https://github.com/SiddhuYen/eitri","ИИ-агент CAD, который проверяет собственную работу; локальный, лицензия не определена.",1),
("cad-agent (Svetlana-DAO-LLC)","https://github.com/Svetlana-DAO-LLC/cad-agent","CAD-моделирование для 3D-печати на build123d и MCP; 53 звезды, лицензия не определена, последнее обновление 17.02.2026.",1),
("partsmith (JLay2026)","https://github.com/JLay2026/partsmith","Сервер параметрического CAD для агентов на build123d: REST и MCP, рендер, сечения, версии, проверки; MIT.",1),
("3dp-mcp-server (brs077)","https://github.com/brs077/3dp-mcp-server","MCP для моделирования печатаемых деталей на build123d под Bambu X1C; 14 звёзд, лицензия не определена.",1),
("RocketSmith (ppak10)","https://github.com/ppak10/RocketSmith","Агенты проектируют и собирают ракеты; для нашей задачи слишком далёк от общего случая; MIT.",1),
("Vibe_CADing (статья и код)","https://github.com/Masoudjafaripour/Vibe_CADing","Поиск и условная генерация CAD для конвейера text-to-CAD; MIT, 13 звёзд.",1),
("ToolCAD (arXiv 2604.07960)","https://arxiv.org/abs/2604.07960","Агент использует инструменты CAD-движка в тренажёре, обучение с подкреплением. Кода не искал.",1),
("Foundation Models for Automatic CAD Generation (arXiv 2607.05573)","https://arxiv.org/abs/2607.05573","Сравнение моделей на 97 инженерных задачах; своя система LLMForge с проверкой схемы и несколькими раундами уточнения.",1),
("CADmium (arXiv 2507.09792)","https://arxiv.org/abs/2507.09792","Дообучение кодовых моделей для CAD; набор из более чем 170 тыс. моделей.",1),
],
3:[
("MeshRight (PyPI)","https://pypi.org/project/meshright/","Проверка и починка сетки в браузере, версия 0.2.0; на GitHub GPL-3.0.",1),
("Bambu-Labs-Orcaslicer-Generator (hansonxyz)","https://github.com/hansonxyz/Bambu-Labs-Orcaslicer-Generator","Скрипт генерирует профили Orca по личным консервативным правилам автора и общим мнениям сообщества; 1 звезда.",1),
],
4:[
("Task-Driven 3D Printability Assistance (arXiv 2608.22128)","https://arxiv.org/abs/2608.22128","STL и описание задачи на обычном языке дают печатаемость, материал, параметры, советы по модели и риски. 96 физических печатей: печатаемость 75,0%, пригодность по задаче 88,9% среди напечатанных; точность выбора материала у Gemini 2.5 Flash-Lite выросла с 37,5% до 90,0%. Кода не нашёл.",1),
("LLM-ADAM (arXiv 2605.03328)","https://arxiv.org/abs/2605.03328","Три роли: одна модель вытаскивает параметры из G-кода, вторая читает документацию принтера и материала, третья судит по таблице отклонений. Корпус 200 G-кодов, пять классов; точность 87,5% против 59,5% у лучшей одиночной модели. Кода не нашёл.",1),
("3D printing Troubleshooting Guide dataset (Konkuk University)","https://github.com/bullitt186/prusaslicer-tuner/tree/main/knowledge","Набор Kang, Ahn, Kim по поиску причин брака, CC BY 4.0; указан как источник в README prusaslicer-tuner. Собственную страницу набора не открывал.",0),
("AdditiveLLM (arXiv 2501.17784)","https://arxiv.org/abs/2501.17784","Модели предсказывают режим брака по параметрам процесса, но для металла (keyholing, lack of fusion, balling); для FDM не подходит.",1),
("print-advisor-mcp (vandurmedries)","https://github.com/vandurmedries/print-advisor-mcp","Цена, время, материал и вместимость стола по размерам без загрузки файла и ключей; лицензии нет, 0 звёзд.",1),
],
5:[
("negative-support-mcp (spikeon)","https://github.com/spikeon/negative-support-mcp","MCP для API «negative-support»; описание в одну строку, содержимое не открывал.",0),
("bambu-studio-mcp (spikeon)","https://github.com/spikeon/bambu-studio-mcp","MCP для консоли bambu-studio; лицензии нет, 0 звёзд.",0),
],
6:[
("LLM4GCode (idealab-isu)","https://github.com/idealab-isu/LLM4GCode","Код к оценке языковых моделей на отладке, правке и понимании G-кода; лицензии нет, 5 звёзд, последнее обновление 2023 года.",1),
("gcode-tokenizer (ruslan-nesterov)","https://github.com/ruslan-nesterov/gcode-tokenizer","Свой токенизатор BPE для G-кода, чтобы команды занимали меньше контекста; MIT, 1 звезда.",1),
],
8:[
("awesome-octoprint (jcgoette)","https://github.com/jcgoette/awesome-octoprint","Список плагинов OctoPrint; MIT, не обновлялся с января 2022, годится только как карта старых плагинов.",1),
],
9:[
("klipper-print-failure-detection (CookiezRGood)","https://github.com/CookiezRGood/klipper-print-failure-detection","Локальная модель TensorFlow Lite находит спагетти, комки, трещины и коробление; 35 звёзд, лицензии нет.",1),
("forgetti (willuhmjs)","https://github.com/willuhmjs/forgetti","Альтернатива обычным системам обнаружения спагетти; MIT, 20 звёзд.",1),
("3d-print-failure-watchdog (ivanx519)","https://github.com/ivanx519/3d-print-failure-watchdog","Брак по остановке данных MQTT и по кадру через Gemini Vision, оповещение в Telegram; MIT, 0 звёзд.",1),
("printwatch (deniskostadinov1995)","https://github.com/deniskostadinov1995/printwatch","Обнаружитель Obico для Bambu P1S, управляется из Home Assistant; MIT, 0 звёзд.",1),
("Masamsa/3d-print-failure-detection (Hugging Face)","https://huggingface.co/datasets/Masamsa/3d-print-failure-detection","Набор снимков брака, около 94 загрузок; содержимое и лицензию не проверял.",0),
("bambu-timelapse-dataset (v2thegreat)","https://huggingface.co/datasets/v2thegreat/bambu-timelapse-dataset","Покадровые съёмки Bambu, около 154 загрузок; содержимое и лицензию не проверял.",0),
],
}

NEW4+=[
("bambu-studio-ai (heyixuan2)","Управление принтерами и слайсерами (MCP)",[4,3,5,4,3],"MIT, 233 звезды, обновлён 19.09.2026","Навык для агентов (Claude Code, Codex, Cursor, Gemini CLI и других): поиск модели в MakerWorld и Printables или построение в CAD, открытие в Bambu Studio, запуск печати и отчёты о ходе каждые 30 минут. Только Bambu Lab. В README указано, что навык отобран в официальную подборку Bambu Lab, это слова авторов.","https://github.com/heyixuan2/bambu-studio-ai"),
("Spoolman MCP (Disane87)","Управление парком",[2,2,5,4,3],"MIT, 17 звёзд, обновлён 15.08.2026","MCP для учёта катушек и филамента в Spoolman обычными словами.","https://github.com/Disane87/spoolman-mcp"),
("printshop-mcp (FireBall1725)","Управление парком",[3,1,2,4,3],"AGPL-3.0, 0 звёзд, обновлён 18.10.2026","MCP поверх Bambuddy и Spoolman: статус, пауза и остановка, пропуск объектов, сушка AMS, файлы и очередь, архив, обслуживание. Показывает, что Bambuddy можно подключить к агенту.","https://github.com/FireBall1725/printshop-mcp"),
("Mirdain Print Hub (hbaig2021)","Управление парком",[3,1,5,3,3],"MIT, 0 звёзд, версия 0.4.0, обновлён 09.10.2026","Свой сервер для печатной фермы: парк, очередь производства, файлы, материалы, телеметрия и управление с защитой; данные в SQLite, без аккаунта и облака. Авторы просят читать правила безопасности до подключения принтера.","https://github.com/hbaig2021/Mirdain_printer_manager"),
("moonraker-mcp (nixkor)","Управление принтерами и слайсерами (MCP)",[2,1,5,3,3],"MIT, 1 звезда, обновлён 30.06.2026","MCP для Klipper через Moonraker: статус, температуры, файлы, управление печатью, макросы. Работает как служба на Raspberry Pi рядом с Moonraker; в начале README большое предупреждение о безопасности.","https://github.com/nixkor/moonraker-mcp"),
("printagent (Eli-code1)","Генерация моделей",[3,1,5,3,3],"MIT, 0 звёзд, обновлён 22.09.2026","Набор навыков Claude Code: параметрическая модель на build123d, проверки печатаемости без участия модели, оценка прочности, упаковка для слайсера; есть режим для новичков.","https://github.com/Eli-code1/printagent"),
("CurviSlicer (mfx-inria)","5D и непланарная печать",[2,2,2,2,4],"AGPL-3.0, 259 звёзд, обновлён 28.03.2025","Исследовательский прототип: изогнутые слои на обычном трёхосевом принтере для лучшей поверхности и точности. Авторы просят не ждать готового к производству кода; исходная версия статьи использует коммерческий решатель Gurobi.","https://github.com/mfx-inria/curvislicer"),
("Radial Non-Planar Slicer (jyjblrd)","5D и непланарная печать",[2,2,2,3,3],"Лицензия не определена, 334 звезды, обновлён 08.06.2025","Непланарная нарезка простых деталей без поддержек; запускается в Google Colab. Сделан под полярный принтер автора, но должен подходить к любому.","https://github.com/jyjblrd/Radial_Non_Planar_Slicer"),
("5AxisSlicer (txf0101)","5D и непланарная печать",[2,2,5,2,3],"MIT, 11 звёзд, версия 2.9, обновлён 02.10.2026","Настольная программа для Windows: открывает STEP, строит траекторию для пятиосевой печати и выгружает NC или G-код для проверки. Документация в основном на китайском, есть английский README.","https://github.com/txf0101/5AxisSlicer"),
("MAGE slicer (gear2nd-droid)","5D и непланарная печать",[2,2,2,2,3],"Лицензия не определена, 18 звёзд, обновлён 17.09.2025","Слайсер для принтеров с четырьмя и более осями на поверхностях NURBS, считает нормали и расстояния между слоями; подходит и для непланарной печати на трёх осях.","https://github.com/gear2nd-droid/MageSlicer"),
]

EXTRA4.setdefault(10,[]).extend([
("EasyConical (DigitalGrin)","https://github.com/DigitalGrin/EasyConical","Программа для конического слайсинга, вида непланарной печати; GPL-3.0, 20 звёзд.",1),
("5axis-slicer (Ber-Sento)","https://github.com/Ber-Sento/5axis-slicer","Каркас для пятиосевой печати: нарезка, траектории, G-код под конкретную машину; MIT, 1 звезда.",1),
("Project-TotalControl (JamesTheGiblet)","https://github.com/JamesTheGiblet/Project-TotalControl","Из JSON с описанием путей делает G-код и сокращает холостые перемещения алгоритмами ближайшего соседа и 2-opt; часть заявленного ещё в разработке; лицензии нет, 1 звезда.",1),
])
EXTRA4.setdefault(7,[]).extend([
("KlipperMCP (mikehatch)","https://github.com/mikehatch/KlipperMCP","MCP для управления конфигами Klipper через Moonraker; лицензии нет, 7 звёзд.",1),
])
EXTRA4.setdefault(8,[]).extend([
("Print-OS (simongonzalezdc)","https://github.com/simongonzalezdc/Print-OS","Парк принтеров, очереди, учёт стоимости и рабочее место с ИИ-CAD; MIT, 0 звёзд; сведения из описания репозитория.",0),
])

NEW4+=[
("OrcaMCP (okets)","Управление принтерами и слайсерами (MCP)",[4,2,2,5,3],"AGPL-3.0, 2 звезды, обновлён 22.10.2026","Форк OrcaSlicer со встроенным MCP-сервером: по README 106 инструментов, делающих то же, что мышь: загрузка и разрезание моделей, настройка любой опции, нарезка, просмотр результата, отправка на принтер. Агент видит стол: рендерит его с любой камеры и читает картинку. Работает локально, облака нет.","https://github.com/okets/OrcaMCP"),
("PrusaSlicer-MCP (JorgeAlbareda)","Управление принтерами и слайсерами (MCP)",[3,1,2,4,3],"AGPL-3.0, 0 звёзд, обновлён 18.10.2026","Неофициальный MCP для PrusaSlicer: профили по имени, раскладка на столе, нарезка через консоль, проверка G-кода на соответствие запрошенной конфигурации, отправка на сетевой принтер. Первая версия работает только через консоль PrusaSlicer.","https://github.com/JorgeAlbareda/PrusaSlicer-MCP"),
("OrcaSlicer-MCP (Kherian)","Подбор параметров",[3,1,2,4,2],"Лицензии нет, 0 звёзд, обновлён 05.09.2026","По отчёту помощника: описываешь симптом текстом или фото, MCP находит связанные параметры OrcaSlicer, показывает значения до и после и применяет с автоматической копией. README на португальском; сам я его не читал.","https://github.com/Kherian/OrcaSlicer-MCP"),
("gcode-mcp (vitkuz573)","Проверка G-кода",[2,1,2,4,3],"Лицензии нет, 0 звёзд, обновлён 06.10.2026","MCP: восстанавливает 3D-модель из G-кода, осматривает срезы, сравнивает сетки. По отчёту помощника, работает с G-кодом Orca, Anycubic, Prusa, Cura.","https://github.com/vitkuz573/gcode-mcp"),
("bambuddy-mcp (MrMebelMan)","Управление парком",[3,1,2,4,3],"GPL-3.0, 5 звёзд, обновлён 22.10.2026","MCP-обёртка над Bambuddy: при запуске строит инструменты из OpenAPI запущенного Bambuddy (в README 430+ эндпоинтов), агенту отдаёт три мета-инструмента.","https://github.com/MrMebelMan/bambuddy-mcp"),
("bambu-mcp (griches)","Управление парком",[3,2,2,4,3],"Лицензии нет, 57 звёзд, обновлён 08.03.2026","MCP для парка Bambu: несколько принтеров, пуск, пауза, остановка, пропуск объектов, файлы, AMS, камера. Среди найденных Bambu-MCP самый заметный по звёздам.","https://github.com/griches/bambu-mcp"),
("bambu-mcp (synman)","Управление принтерами и слайсерами (MCP)",[2,2,2,4,3],"Лицензии нет, 5 звёзд, версия 0.9.0, обновлён 15.10.2026","Постоянная MQTT-сессия на каждый принтер Bambu по LAN, MCP-инструменты, REST и потоки камеры. Изменяющие инструменты требуют разрешения пользователя (user_permission=True).","https://github.com/synman/bambu-mcp"),
("bambu-mcp-server (gusjarendt-maker)","Анализ и починка STL",[3,1,5,3,3],"MIT, 0 звёзд, обновлён 09.03.2026","MCP «от битого STL до печати»: анализ сетки, починка через pymeshfix, масштаб и поворот, нарезка и управление принтером Bambu.","https://github.com/gusjarendt-maker/bambu-mcp-server"),
("bambu-ai (abe238)","Мониторинг и дефекты",[3,1,5,3,3],"Apache-2.0, 1 звезда, обновлён 26.05.2026","Консольная связка принтеров Bambu A1 и A1 mini с агентом (Claude Code, Cursor, Codex): статус, управление, уведомления, подсистема зрения: камера, vision-модель и автопауза при «спагетти». Только LAN.","https://github.com/abe238/bambu-ai"),
("Claude-коннектор SimplyPrint","Управление парком",[3,3,2,5,3],"Сервис закрытый; плагин simplyprint-claude-plugin и расширение для Gemini CLI под MIT","По странице SimplyPrint: коннектор запущен 11.07.2026, работает в claude.ai, Claude Desktop и Claude Code через OAuth, права на чтение или полные, перед отменой печати спрашивает.","https://simplyprint.io/integrations/claude.md"),
("Helio Additive Dragon","Подбор параметров",[3,3,1,1,2],"Проприетарно","Термосимуляция G-кода и платная оптимизация: переписывает G-код с ограничениями на скорость и поток; встроено в Bambu Studio в бета-режиме. Цифры вендора о росте прочности независимо не проверены; на форуме Bambu пользователи жалуются на цену и приватность. Сайт вендора я не открывал.","https://wiki.helioadditive.com/case-studies/dragon-vs-bambu-lab-pc"),
("Obico: чат-API для слайсера (Elegoo)","Подбор параметров",[3,2,1,2,4],"Закрытый партнёрский API","Документация API ИИ-чата на основе JusPrin: на входе история чата, текущие пресеты и объекты на столе; на выходе рекомендованный пресет с переопределениями и пояснениями по каждому (per_override_explanations) и действия агента (нарезка, ориентация, расстановка). Только один экструдер; вызов списывает кредиты Elegoo.","https://www.obico.io/docs/elegoo-apis/elegoo-obico-chat-messages-api/"),
("SKZ: снимки с камеры у сопла (Hugging Face)","Мониторинг и дефекты",[1,3,2,3,4],"Лицензия «cc» без версии, 1186 загрузок","Набор снимков в формате YOLO, девять классов: сопло, объект, линия очистки, спагетти, stringing, недоэкструзия, коробление, плохой первый слой, двойная печать. Данные центра SKZ; есть парный набор с камерой на всю платформу.","https://huggingface.co/datasets/DasKunststoffZentrumSKZ/Errors_Additive_Manufacturing_Nozzle_Cam"),
("Zero-To-CAD-1m (Hugging Face)","Генерация моделей",[1,3,5,3,4],"Apache-2.0, 12,3 тыс. загрузок, 136 лайков","Более миллиона синтетических примеров на CadQuery: текст или картинка в 3D, последовательности построения. Материал для обучения, не готовый инструмент.","https://huggingface.co/datasets/ADSKAILab/Zero-To-CAD-1m"),
]

EXTRA4.setdefault(1,[]).extend([
("Domain Adapted LLMs for Additive Manufacturing (arXiv 2603.22017)","https://arxiv.org/abs/2603.22017","Мультимодальные модели на Gemma 3, Qwen 3, Gemma 4, доадаптированные примерно на 50 млн токенов открытых статей по аддитивному производству. Код: ppak10/additive-manufacturing (5 звёзд, лицензию GitHub не определил).",1),
("additive-manufacturing (ppak10)","https://github.com/ppak10/additive-manufacturing","Python-пакет к статье 2603.22017; по описанию помощника, команда am mcp install ставит MCP-инструменты и агента для Claude Code. README сам не читал.",0),
])
EXTRA4.setdefault(2,[]).extend([
("SEG: Support-Effective Generation (arXiv 2511.16434)","https://arxiv.org/abs/2511.16434","Text-to-3D с оптимизацией по предпочтениям (Offset DPO), чтобы модель требовала меньше поддержек. Кода не нашли.",1),
("thingiverse-openscad (Hugging Face)","https://huggingface.co/datasets/redcathode/thingiverse-openscad","7378 пар «описание и код OpenSCAD» из Thingiverse; лицензия CC-BY-NC-SA-4.0, то есть только некоммерческое использование; 137 загрузок.",1),
("OpenSCAD-MCP-Server (jhacksman)","https://github.com/jhacksman/OpenSCAD-MCP-Server","Запрос в превью и 3D-файл через OpenSCAD; MIT, 208 звёзд, обновлён 07.09.2026.",1),
("openscad-mcp (RobertCoop)","https://github.com/RobertCoop/openscad-mcp","MCP для моделирования и рендера в OpenSCAD; MIT, 163 звезды, обновлён 10.09.2026.",1),
("build123d-mcp (pzfreo)","https://github.com/pzfreo/build123d-mcp","MCP для build123d, чтобы ИИ лучше строил CAD-модели; Apache-2.0, 125 звёзд, обновлён 15.10.2026.",1),
("AnkusDrive (gchen19)","https://github.com/gchen19/AnkusDrive","Консоль и MCP над FreeCAD: параметрический CAD, чертежи, расчёты; Apache-2.0, 13 звёзд.",1),
("RootControl/bambu-mcp","https://github.com/RootControl/bambu-mcp","Claude пишет OpenSCAD, смотрит превью и правит, на выходе 3MF для Bambu A1 mini; принтеру по сети ничего не отправляет. Лицензии нет, 0 звёзд.",1),
("stl-mcp (htilly)","https://github.com/htilly/stl-mcp","Самохостимый MCP для проектирования моделей под печать в миллиметрах с веб-просмотром; лицензии нет, 0 звёзд, описание в репозитории пустое.",0),
("Habr (Selectel): проверка нейросетей image-to-3D для печати","https://habr.com/ru/companies/selectel/articles/1031320/","Тест на одном объекте: у разных сервисов сетка то сохранила геометрию, то вышла с дырами; вывод автора: результат нейросети перед печатью надо проверять (замкнутость, стенки, нормали, пересечения). Сам не открывал.",0),
])
EXTRA4.setdefault(3,[]).extend([
("Support Fins (gittrahan)","https://github.com/gittrahan/support-fins","Ставит деталь на ребро и добавляет отламываемые «плавники» прямо в STL; всё в браузере; MIT, 824 звезды. Не ИИ-продукт, но идея ориентации полезна.",1),
])
EXTRA4.setdefault(4,[]).extend([
("A-RAM (arXiv 2609.19347)","https://arxiv.org/abs/2609.19347","Агент по намерению пользователя и файлу детали строит план печати: языковая модель формирует запрос, детерминированный планировщик перебирает варианты, инструменты считают нарезку, размещение и кинематику; проверка на роботизированной ячейке. Кода не нашли.",1),
("orcaslicer-mcp-optimizer (Nibbler1250)","https://github.com/Nibbler1250/orcaslicer-mcp-optimizer","По описанию репозитория: подбор настроек по обратной связи от результатов печати через консоль OrcaSlicer; лицензии нет, 1 звезда; README не открылся.",0),
("yennik16/3d-print-jobs-tabular (Hugging Face)","https://huggingface.co/datasets/yennik16/3d-print-jobs-tabular","30 деталей с Bambu X1C и X2D: расход, заполнение, слой, сопло, время печати; CC-BY-4.0, 90 загрузок. Мини-образец для оценки времени.",1),
("AdditiveLLM2-OA (Hugging Face)","https://huggingface.co/datasets/ppak10/AdditiveLLM2-OA","Открытые статьи по аддитивному производству (до февраля 2026) для доадаптации моделей; лицензия «other», 230 загрузок.",1),
("amba-pro/MCP-3d-printer (glama)","https://glama.ai/mcp/servers/amba-pro/MCP-3d-printer","Первая версия: разбор STL и 3MF, правила для стартовых настроек PLA, PETG, ABS, TPU; принтером не управляет. Репозиторий на GitHub не открылся (404), сведения со страницы glama.",0),
("Форум Bambu: фото брака в ChatGPT","https://forum.bambulab.com/t/fragmentation-and-stringing-issues/223218","Пользователь прогнал фото брака через ChatGPT и применил советы по порогам вентилятора для PETG; результат «идеальный» по его словам, не проверка. Показывает реальный сценарий «фото в параметры». Сам не открывал.",0),
("PrintFix.io","https://rutab.net/b/hardware/2025/07/01/novyy-ii-instrument-printfixio-obeschaet-pomoch-s-problemami-3d-pechati.html","Веб-инструмент: принтер, категория проблемы, фото, советы через 30 секунд, 3 бесплатных запроса в месяц; по обзору советы общие. Сайт не открывал, читал обзор.",0),
("3DSearch (Product Hunt)","https://www.producthunt.com/products/3dsearch-2/makers","По листингу: поиск моделей по 10+ площадкам и настройки слайсера под принтер и филамент; сам сайт не открывал.",0),
])
EXTRA4.setdefault(5,[]).extend([
("slicer-mcp (vitkuz573)","https://github.com/vitkuz573/slicer-mcp","Нарезка движком OrcaSlicer с профилями Anycubic Kobra S1; лицензии нет, 0 звёзд.",1),
("coqui-slicedd (carmelosantana)","https://github.com/carmelosantana/coqui-slicedd","Тулкит на PHP: нарезка через консоль OrcaSlicer, анализ и постобработка G-кода, история заданий. Репозиторий в архиве; лицензии нет.",1),
("@push.rocks/smartslicer (npm)","https://www.npmjs.com/package/@push.rocks/smartslicer","Нарезка в Node.js через консоль OrcaSlicer с системными профилями; MIT, версия 0.1.0 по отчёту помощника.",0),
("three-slicer (npm)","https://www.npmjs.com/package/three-slicer","Слайсер на базе OrcaSlicer для браузера и Node (WASM), AGPL-3.0-or-later; по отчёту помощника, версия 0.3.5.",0),
("Image2Gcode (arXiv 2511.20636)","https://arxiv.org/abs/2511.20636","Генерирует G-код прямо из картинки или чертежа без CAD и STL: диффузионный трансформер над последовательностями G-кода. Кода не нашли.",1),
("mecode (jminardi)","https://github.com/jminardi/mecode","Python-библиотека для прямой записи G-кода; MIT, 239 звёзд, последнее обновление 2023 года.",1),
("gcoordinator (tomohiron907)","https://github.com/tomohiron907/gcoordinator","Моделирование, предпросмотр и экспорт G-кода на Python; MIT, 20 звёзд.",1),
("Diterex/orcaslicer-mcp","https://github.com/Diterex/orcaslicer-mcp","Нарезка OrcaSlicer: время, расход, число слоёв, плюс инструменты для работы с кодом OrcaSlicer; MIT, 0 звёзд.",1),
("ai-slicer-mcp-server (VisualBoy)","https://github.com/VisualBoy/ai-slicer-mcp-server","Нарезка PrusaSlicer и управление OctoPrint; по README часть инструментов (анализ печатаемости, ориентация, выбор профиля) помечена как заглушки; лицензии нет, обновлён 10.06.2025.",1),
])
EXTRA4.setdefault(6,[]).extend([
("gcode-seer (npm)","https://www.npmjs.com/package/gcode-seer","Библиотека без зависимостей: анализ движения, экструзии, температур и ограничений принтера, профили Bambu и Prusa; MIT, версия 0.1.1 по отчёту помощника.",0),
("Extrudio","https://extrudio.site/","Рендерит деталь по G-коду, а не по STL; без ссылки на код; по статье Hackaday. Сайт не открывал.",0),
("r3lax/gcode (Hugging Face)","https://huggingface.co/datasets/r3lax/gcode","400 моделей с Printables и 740 файлов G-кода Prusa, 11 ГБ; лицензия не указана, 331 загрузка.",1),
("augmented-g-code (Hugging Face)","https://huggingface.co/datasets/jungter/augmented-g-code","Таблицы по 10–100 тыс. строк, MIT, 67 загрузок; описания в карточке нет, содержимое неясно.",0),
])
EXTRA4.setdefault(7,[]).extend([
("prusa-mcp (gioelemo)","https://github.com/gioelemo/prusa-mcp","MCP для принтеров Prusa через Prusa Connect с входом OAuth2 (PKCE); GPL-3.0, 2 звезды.",1),
("simplyprint-gemini-extension","https://github.com/SimplyPrint/simplyprint-gemini-extension","Официальное расширение Gemini CLI: очередь, принтеры, филамент; MIT, 1 звезда.",1),
("moonraker-mcp (simonerlic)","https://github.com/simonerlic/moonraker-mcp","Состояние, аварийная остановка, пауза, отмена, снимок вебкамеры, очередь заданий через Moonraker; лицензии нет, 3 звезды, обновлён 14.09.2025.",1),
("klipper-mcp (mmmaxwwwell)","https://github.com/mmmaxwwwell/klipper-mcp","MCP для Klipper; по README проект в разработке, цель: явный набор инструментов без произвольного G-кода; лицензии нет, 0 звёзд.",1),
("Ultimaker-S5-Interfacing (mjklopfer)","https://github.com/mjklopfer/Ultimaker-S5-Interfacing","Локальный MCP для UltiMaker S5 и Cura: плагин Cura и защищённые операции; MIT, 0 звёзд.",1),
("bambu-printer-mcp (ceweldy)","https://github.com/ceweldy/bambu-printer-mcp","Независимое продолжение DMontgomery40/bambu-printer-mcp: именованные профили принтеров, обезличенный статус парка; GPL-2.0, 0 звёзд.",1),
("bambu-mcp (Eyalm321)","https://github.com/Eyalm321/bambu-mcp","Bambu P2S, P1S, X1 в режиме LAN: нарезка, загрузка, печать, мониторинг; лицензии нет, 1 звезда.",1),
])
EXTRA4.setdefault(8,[]).extend([
("Printago: CLI и навык для Claude","https://printago.io/features/ai-agents","Консоль оборачивает REST-эндпоинты, вывод JSON; идёт с навыком Claude Code. Страницу читал помощник, сам не открывал.",0),
("Work orders merging (arXiv 2504.02509)","https://arxiv.org/abs/2504.02509","Языковая модель с памятью объединяет заказы на 3D-печать по устройствам. Кода не нашли.",1),
])
EXTRA4.setdefault(9,[]).extend([
("Obico AI Premium","https://www.obico.io/blog/next-gen-ai-failure-detection-general-release/","Новый детектор с 1 мая 2026: вендор заявляет на 63% меньше пропусков и на 56% меньше ложных срабатываний. Бесплатно 10 часов ИИ-детекции в месяц. Независимых проверок не видел; страницу читал помощник.",0),
("SimplyPrint AI Detection","https://simplyprint.io/features/ai-detection.md","По кадрам камеры ищет спагетти, коробление, комки; может ставить на паузу или отменять; 12 часов в месяц бесплатно, дальше платно. Код закрыт. Страницу читал помощник.",0),
("PrintGuard","https://circuitdigest.com/news/3d-print-failure-detection-using-ai-with-printguard","Открытый инструмент по статье: несколько камер, OctoPrint, уведомления со снимком, pip или Docker. Лицензию в статье не нашли, точности нет.",0),
("klipper-ai-vision (torcu)","https://github.com/torcu/klipper-ai-vision","Поиск брака через vision-модели Groq, проверка раз в 10 минут, уведомления в Telegram; MIT, 0 звёзд, обновлён 29.10.2025.",1),
("KlipperAI-OS (turer73)","https://github.com/turer73/KlipperAI-OS","Образ Linux для Klipper с детектором TFLite и автопаузой; AGPL-3.0, 0 звёзд; README на турецком.",1),
("uno-q-3d-print-watchdog (raspberry-tips)","https://github.com/raspberry-tips/uno-q-3d-print-watchdog","Локальный детектор на Arduino UNO Q: модель обучена только на удачных печатях, оповещение в Home Assistant, пауза через Moonraker; MIT, 1 звезда.",1),
("TheNoodleSnoop (stuomas)","https://github.com/stuomas/TheNoodleSnoop","Берёт нейросеть из obico-server без веб-сервера и интерфейса, результат шлёт по MQTT; AGPL-3.0, 8 звёзд, последнее обновление 11.02.2024.",1),
("3DPrintSaviour (Manicben)","https://github.com/Manicben/3DPrintSaviour","Поиск брака по кадрам Octolapse в связке с OctoPrint; 73 звезды, репозиторий в архиве, последнее изменение 06.04.2023.",1),
("bambu-mcp-server (Shockedrope)","https://github.com/Shockedrope/bambu-mcp-server","Наблюдение за Bambu P1P из Claude Desktop по MQTT: статус, пауза, остановка, скорость; лицензии нет, 8 звёзд, обновлён 04.11.2025.",1),
("Closed Loop Reference Optimization (arXiv 2512.16333)","https://arxiv.org/abs/2512.16333","Замкнутый контур экструзии: линейно-квадратичный регулятор с обратной связью по усилию; эксперименты на FFF-принтере. Кода не нашли.",1),
("Warpage detection in FDM (arXiv 2607.18515)","https://arxiv.org/abs/2607.18515","Автоматический выбор моделей и признаков для обнаружения коробления на наборах данных FDM; код по ссылке в статье: SalehML/Codes-for-ADP_XAI-Framework (0 звёзд, лицензии нет).",1),
("Errors_Additive_Manufacturing_Plattform_Cam (Hugging Face)","https://huggingface.co/datasets/DasKunststoffZentrumSKZ/Errors_Additive_Manufacturing_Plattform_Cam","Парный набор SKZ: камера на всю платформу, формат YOLO; лицензия «cc», 645 загрузок.",1),
])

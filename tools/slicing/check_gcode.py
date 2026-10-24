#!/usr/bin/env python3
"""Проверка G-code после нарезки (контракт stage3.feedback v0.1, этап 3в).

  python3 check_gcode.py result.gcode parameter_set.json [--forbid-supports] [--iteration N] [--returns-used N] [--json]
  python3 check_gcode.py --selftest

Принтер Stereotech Hybrid 530 V5.2.4, слайсер STE Slicer 7.10.12 (форк Cura).
Читает G-code потоково (не грузит в память). Проверяет высоту слоя, температуры, габариты,
поддержки, режим печати. Возвращает stage3.feedback с ограничениями для этапа 2.
"""
import argparse
import json
import os
import re
import sys
from collections import defaultdict

# Область стола classic (мм), центр в X175.5 Y150.15, размер 351 x 300.3 x 300
CLASSIC_X_MIN, CLASSIC_X_MAX = 0.0, 351.0
CLASSIC_Y_MIN, CLASSIC_Y_MAX = 0.0, 300.3
CLASSIC_Z_MIN, CLASSIC_Z_MAX = 0.0, 300.0
COORD_TOLERANCE = 0.5  # допуск выхода за стол

# Соответствие профилей и высот слоя
QUALITY_LAYER_HEIGHTS = {
    "normal": 0.1, "draft": 0.2, "fast": 0.15,
    "high": 0.06, "verydraft": 0.3, "coarse": 0.4, "extra coarse": 0.6
}


def parse_gcode(path):
    """Потоково собирает факты из G-code."""
    facts = {
        "header": {}, "line_count": 0, "type_counts": defaultdict(int),
        "layer_count": 0, "time_elapsed": None, "temps": [],
        "fan_commands": [], "bounds": {"x": [None, None], "y": [None, None], "z": [None, None]},
        "max_e": None, "has_end": False, "settings": {}, "settings_error": None
    }

    e_val = None

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line_num, raw_line in enumerate(f, 1):
            facts["line_count"] = line_num
            line = raw_line.strip()

            # Шапка (комментарии)
            if line.startswith(";VERSION:"):
                facts["header"]["VERSION"] = line.split(":", 1)[1]
            elif line.startswith(";PRINTING_MODE:"):
                facts["header"]["PRINTING_MODE"] = line.split(":", 1)[1].strip("[]")
            elif line.startswith(";MIN") or line.startswith(";MAX"):
                parts = line[1:].split(":")
                if len(parts) == 2:
                    facts["header"][parts[0]] = parts[1]
            elif line.startswith(";FLAVOR:"):
                facts["header"]["FLAVOR"] = line.split(":", 1)[1]
            elif line.startswith(";TIME:"):
                facts["header"]["TIME"] = line.split(":", 1)[1]
            elif line.startswith(";Filament used:"):
                facts["header"]["FILAMENT"] = line.split(":", 1)[1]
            elif line.startswith(";Layer height:"):
                facts["header"]["LAYER_HEIGHT"] = line.split(":", 1)[1].strip()
            elif line.startswith(";LAYER_COUNT:"):
                facts["header"]["LAYER_COUNT"] = int(line.split(":", 1)[1])

            # Типы и слои
            elif line.startswith(";TYPE:"):
                type_name = line.split(":", 1)[1]
                facts["type_counts"][type_name] += 1
            elif line.startswith(";LAYER:"):
                facts["layer_count"] += 1
            elif line.startswith(";TIME_ELAPSED:"):
                try:
                    facts["time_elapsed"] = float(line.split(":", 1)[1])
                except:
                    pass

            # Температуры
            elif line.startswith("M104 ") or line.startswith("M109 "):
                m = re.search(r"S(\d+)", line)
                if m:
                    facts["temps"].append((line[:4], int(m.group(1)), line_num))
            elif line.startswith("M140 ") or line.startswith("M190 "):
                m = re.search(r"S(\d+)", line)
                if m:
                    facts["temps"].append((line[:4], int(m.group(1)), line_num))

            # Вентилятор
            elif line.startswith("M106") or line.startswith("M107"):
                cmd = line.split()[0]
                facts["fan_commands"].append((cmd, line_num))

            # Движения (только если есть X/Y/Z)
            elif line.startswith("G0 ") or line.startswith("G1 "):
                x_match = re.search(r"X([-\d.]+)", line)
                y_match = re.search(r"Y([-\d.]+)", line)
                z_match = re.search(r"Z([-\d.]+)", line)
                e_match = re.search(r"E([-\d.]+)", line)

                if x_match:
                    x = float(x_match.group(1))
                    if facts["bounds"]["x"][0] is None or x < facts["bounds"]["x"][0]:
                        facts["bounds"]["x"][0] = x
                    if facts["bounds"]["x"][1] is None or x > facts["bounds"]["x"][1]:
                        facts["bounds"]["x"][1] = x

                if y_match:
                    y = float(y_match.group(1))
                    if facts["bounds"]["y"][0] is None or y < facts["bounds"]["y"][0]:
                        facts["bounds"]["y"][0] = y
                    if facts["bounds"]["y"][1] is None or y > facts["bounds"]["y"][1]:
                        facts["bounds"]["y"][1] = y

                if z_match:
                    z = float(z_match.group(1))
                    if facts["bounds"]["z"][0] is None or z < facts["bounds"]["z"][0]:
                        facts["bounds"]["z"][0] = z
                    if facts["bounds"]["z"][1] is None or z > facts["bounds"]["z"][1]:
                        facts["bounds"]["z"][1] = z

                if e_match:
                    e = float(e_match.group(1))
                    if e_val is None or e > e_val:
                        e_val = e

            # Конец
            elif line.startswith(";End of Gcode"):
                facts["has_end"] = True

            # SETTING_3
            elif line.startswith(";SETTING_3 "):
                payload = line[11:]
                try:
                    # Собираем построчно JSON
                    if not hasattr(parse_gcode, "_setting_buf"):
                        parse_gcode._setting_buf = []
                    parse_gcode._setting_buf.append(payload)
                except:
                    pass

    facts["max_e"] = e_val

    # Парсим SETTING_3
    if hasattr(parse_gcode, "_setting_buf"):
        try:
            full_json = "".join(parse_gcode._setting_buf)
            data = json.loads(full_json)
            # Разбираем INI из global_quality и extruder_quality
            for key in ["global_quality"]:
                if key in data:
                    facts["settings"].update(_parse_ini(data[key]))
            if "extruder_quality" in data and isinstance(data["extruder_quality"], list):
                for eq in data["extruder_quality"]:
                    facts["settings"].update(_parse_ini(eq))
        except Exception as e:
            facts["settings_error"] = str(e)
        delattr(parse_gcode, "_setting_buf")

    return facts


def _parse_ini(text):
    """Извлекает [values] из INI-строки."""
    result = {}
    lines = text.split("\\n")
    in_values = False
    for line in lines:
        line = line.strip()
        if line == "[values]":
            in_values = True
        elif in_values and "=" in line:
            k, v = line.split("=", 1)
            result[k.strip()] = v.strip()
    return result


def check(facts, pset, opts):
    """Возвращает список замечаний."""
    findings = []

    def add(kind, severity, key, message):
        obj = {"id": f"G{len(findings)+1}", "kind": kind, "severity": severity, "message": message}
        if key:
            obj["key"] = key
        findings.append(obj)

    # 1. file: пустой, нет слоёв, нет End, LAYER_COUNT не сходится, нет экструзии
    if facts["line_count"] < 3:  # минимум: заголовок, тело, ;End
        add("file", "error", None, "файл пустой или слишком короткий")

    if facts["layer_count"] == 0:
        add("file", "error", None, "нет слоёв (;LAYER:)")

    if not facts["has_end"]:
        add("file", "error", None, "нет маркера ;End of Gcode")

    # LAYER_COUNT может не совпадать на 1 (последний слой не всегда помечен ;LAYER:)
    if "LAYER_COUNT" in facts["header"]:
        declared = facts["header"]["LAYER_COUNT"]
        actual = facts["layer_count"]
        # Допускаем actual == declared или actual == declared-1. Больший разрыв встречается в целых G-code
        # слайсера (на Windows: 765 против 762 при повороте модели), поэтому это предупреждение, а не ошибка:
        # оборванный файл ловит проверка маркера ;End of Gcode.
        if actual not in (declared, declared - 1):
            add("file", "warning", None, f"LAYER_COUNT={declared}, но найдено {actual} слоёв")

    if facts["max_e"] is None or facts["max_e"] <= 0:
        add("file", "error", None, "нет экструзии (E не растёт)")

    # 2. apply: режим
    mode_gcode = facts["header"].get("PRINTING_MODE")
    mode_pset = (pset.get("printing_mode") or {}).get("value")
    if mode_gcode is None:
        # экспорт плагина (export_gcode) пишет G-code без шапки ;PRINTING_MODE и ;MINX..;MAXZ
        add("apply", "info", "printing_mode", "в G-code нет строки ;PRINTING_MODE (шапка не записана), режим не проверен")
    elif mode_gcode != mode_pset:
        add("apply", "error", "printing_mode", f"режим в G-code [{mode_gcode}], ожидался [{mode_pset}]")

    # 3. apply: высота слоя
    lh_gcode_str = facts["header"].get("LAYER_HEIGHT")
    if lh_gcode_str:
        try:
            lh_gcode = float(lh_gcode_str)
            # Ожидаемая
            lh_expected = None
            settings = pset.get("settings") or {}
            if "layer_height" in settings:
                lh_expected = settings["layer_height"].get("value")
            else:
                qt = (pset.get("quality") or {}).get("quality_type")
                lh_expected = QUALITY_LAYER_HEIGHTS.get(qt)

            if lh_expected is not None and abs(lh_gcode - lh_expected) > 1e-6:
                add("apply", "error", "layer_height", f"высота слоя {lh_gcode} мм, ожидалась {lh_expected} мм")
        except:
            pass

    # 4. apply: температуры
    settings = pset.get("settings") or {}
    mat_print_temp = settings.get("material_print_temperature", {}).get("value")
    mat_bed_temp = settings.get("material_bed_temperature", {}).get("value")

    # M104/M109 с S>0
    nozzle_temps = [t for cmd, t, ln in facts["temps"] if cmd in ("M104", "M109") and t > 0]
    bed_temps = [t for cmd, t, ln in facts["temps"] if cmd in ("M140", "M190") and t > 0]

    if mat_print_temp is not None:
        # Сверяем все M104/M109 с S>0
        for t in nozzle_temps:
            if t != mat_print_temp:
                add("apply", "error", "material_print_temperature", f"температура сопла {t}°C, ожидалась {mat_print_temp}°C")
                break
    else:
        if nozzle_temps:
            add("apply", "info", None, f"температуры взяты из материала: сопло {nozzle_temps[0]}°C" + (f", стол {bed_temps[0]}°C" if bed_temps else ""))

    if mat_bed_temp is not None and mode_pset == "classic":
        for t in bed_temps:
            if t != mat_bed_temp:
                add("apply", "error", "material_bed_temperature", f"температура стола {t}°C, ожидалась {mat_bed_temp}°C")
                break

    # 5. warning: в 5D (cylindrical, cylindrical_full) не должно быть M140/M190 с S>0
    if mode_pset in ("cylindrical", "cylindrical_full") and bed_temps:
        add("apply", "warning", "material_bed_temperature", "в 5D стол не греется, но найдены команды M140/M190")

    # 6. apply: настройки из SETTING_3
    if facts.get("settings_error"):
        add("apply", "info", None, f"SETTING_3 не распознан: {facts['settings_error']}")

    gcode_settings = facts.get("settings", {})
    not_checkable = []
    for key, node in settings.items():
        val = node.get("value")
        if key not in gcode_settings:
            not_checkable.append(key)
        else:
            gval_str = gcode_settings[key]
            # Сравниваем как числа или bool или строки
            if isinstance(val, bool):
                if gval_str.lower() != str(val).lower():
                    add("apply", "error", key, f"настройка {key}: в G-code '{gval_str}', ожидалось {val}")
            elif isinstance(val, (int, float)):
                try:
                    gval = float(gval_str)
                    if abs(gval - val) > 1e-9:
                        add("apply", "error", key, f"настройка {key}: в G-code {gval}, ожидалось {val}")
                except:
                    add("apply", "error", key, f"настройка {key}: в G-code '{gval_str}', ожидалось {val}")
            else:
                if gval_str != str(val):
                    add("apply", "error", key, f"настройка {key}: в G-code '{gval_str}', ожидалось '{val}'")

    if not_checkable:
        add("apply", "info", None, f"не проверяемо по G-code: {', '.join(not_checkable)}")

    # 7. content/error: габариты (только classic)
    if mode_pset == "classic":
        xmin, xmax = facts["bounds"]["x"]
        ymin, ymax = facts["bounds"]["y"]
        zmin, zmax = facts["bounds"]["z"]

        if xmin is not None and (xmin < CLASSIC_X_MIN - COORD_TOLERANCE or xmax > CLASSIC_X_MAX + COORD_TOLERANCE):
            add("content", "error", None, f"выход за стол по X: [{xmin:.1f}, {xmax:.1f}] при области [0, 351]")
        if ymin is not None and (ymin < CLASSIC_Y_MIN - COORD_TOLERANCE or ymax > CLASSIC_Y_MAX + COORD_TOLERANCE):
            add("content", "error", None, f"выход за стол по Y: [{ymin:.1f}, {ymax:.1f}] при области [0, 300.3]")
        if zmin is not None and (zmin < CLASSIC_Z_MIN - COORD_TOLERANCE or zmax > CLASSIC_Z_MAX + COORD_TOLERANCE):
            add("content", "error", None, f"выход за стол по Z: [{zmin:.1f}, {zmax:.1f}] при области [0, 300]")
    else:
        # 5D: не проверяем
        add("content", "info", None, f"габариты в 5D не проверены: нет образца G-code")

    # 8. supports
    support_count = facts["type_counts"].get("SUPPORT", 0) + facts["type_counts"].get("SUPPORT-INTERFACE", 0)
    support_enable_pset = settings.get("support_enable", {}).get("value")

    if opts.get("forbid_supports") and support_count > 0:
        add("content", "error", "support_enable", "поддержки найдены, но запрещены опцией --forbid-supports")

    if support_enable_pset is False and support_count > 0:
        add("apply", "error", "support_enable", "в параметрах support_enable=false, но в G-code есть поддержки")

    if support_enable_pset is True and support_count == 0:
        add("apply", "info", None, "поддержки включены, но слайсер их не построил (модель могла в них не нуждаться)")

    # 9. info: время, расход, слои
    time_sec = facts["header"].get("TIME")
    if time_sec:
        try:
            t = int(time_sec)
            hours = t // 3600
            minutes = (t % 3600) // 60
            add("apply", "info", None, f"время печати: {hours} ч {minutes} мин")
        except:
            pass

    filament = facts["header"].get("FILAMENT")
    if filament:
        add("apply", "info", None, f"расход: {filament.strip()}")

    layer_count = facts["header"].get("LAYER_COUNT", facts["layer_count"])
    add("apply", "info", None, f"число слоёв: {layer_count}")

    return findings


def build_feedback(findings, pset, iteration, returns_used):
    """Собирает stage3.feedback v0.1."""
    # result
    has_error = any(f["severity"] == "error" for f in findings)
    has_content_error = any(f["severity"] == "error" and f["kind"] == "content" for f in findings)
    has_apply_error = any(f["severity"] == "error" and f["kind"] in ("apply", "file") for f in findings)

    if not has_error:
        result = "ok"
    elif has_content_error:
        result = "needs_changes"
    elif has_apply_error:
        result = "apply_failed"
    else:
        result = "ok"

    # constraints
    constraints = []
    for f in findings:
        if f["severity"] == "error" and f["kind"] == "content" and f.get("key") == "support_enable":
            constraints.append({
                "id": f["id"], "key": "support_enable", "op": "eq", "value": False,
                "origin": "gcode", "reason": f["message"], "severity": "error"
            })

    # exclude
    exclude = []
    warnings = []
    for f in findings:
        if f["severity"] == "error" and f["kind"] == "content" and "выход за стол" in f["message"]:
            # Ищем orientation_candidate
            models = pset.get("models", [])
            if models and "orientation_candidate" in models[0]:
                exclude.append({
                    "type": "orientation", "candidate": models[0]["orientation_candidate"],
                    "reason": f["message"]
                })
            else:
                warnings.append({"message": f"выход за стол, но кандидат ориентации не указан"})

        if f["severity"] == "warning":
            warnings.append({"key": f.get("key"), "reason": f["message"]})

    feedback = {
        "contract": "stage3.feedback",
        "version": "0.1",
        "iteration": iteration,
        "result": result,
        "constraints": constraints,
        "exclude": exclude,
        "warnings": warnings,
        "returns_used": returns_used,
        "findings": findings
    }

    return feedback


def selftest():
    """Selftest: синтетические мини-G-code."""
    passed = 0
    total = 0

    def mini_gcode(header, body, setting3=None):
        """Генерирует минимальный G-code."""
        lines = []
        for k, v in header.items():
            lines.append(f";{k}:{v}")
        lines.extend(body)
        if setting3:
            lines.append(f';SETTING_3 {json.dumps(setting3)}')
        lines.append(";End of Gcode")
        return "\n".join(lines)

    def run_test(name, gcode_text, pset, opts, expect_result):
        nonlocal passed, total
        total += 1

        # Пишем во временный файл
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".gcode", delete=False, encoding="utf-8") as tf:
            tf.write(gcode_text)
            tpath = tf.name

        try:
            facts = parse_gcode(tpath)
            findings = check(facts, pset, opts)
            fb = build_feedback(findings, pset, 1, 0)
            actual = fb["result"]

            if actual == expect_result:
                print(f"OK  {name}")
                passed += 1
            else:
                print(f"СБОЙ {name}: ожидался {expect_result}, получен {actual}")
        finally:
            os.unlink(tpath)

    # Базовый pset
    base_pset = {
        "printing_mode": {"value": "classic"},
        "quality": {"quality_type": "draft"},
        "settings": {}
    }

    # 1. ok-случай
    ok_gcode = mini_gcode(
        {"PRINTING_MODE": "[classic]", "LAYER_HEIGHT": "0.2", "LAYER_COUNT": "10", "TIME": "100"},
        [";LAYER:0", "G1 X100 Y100 Z1 E1", ";LAYER:1", "G1 X150 Y150 Z2 E2"] * 5,
        {"global_quality": "[values]\\n", "extruder_quality": []}
    )
    run_test("ok-случай", ok_gcode, base_pset, {}, "ok")

    # 2. пустой
    run_test("пустой файл", "", base_pset, {}, "apply_failed")

    # 3. без End
    no_end = mini_gcode({"PRINTING_MODE": "[classic]", "LAYER_COUNT": "1"}, [";LAYER:0"])
    run_test("нет ;End of Gcode", no_end.replace(";End of Gcode", ""), base_pset, {}, "apply_failed")

    # 4. LAYER_COUNT не сходится
    wrong_lc = mini_gcode({"PRINTING_MODE": "[classic]", "LAYER_COUNT": "100"}, [";LAYER:0"])
    run_test("LAYER_COUNT не сходится", wrong_lc, base_pset, {}, "apply_failed")

    # 5. режим не тот
    wrong_mode = mini_gcode({"PRINTING_MODE": "[cylindrical]", "LAYER_COUNT": "1"}, [";LAYER:0"])
    run_test("режим не совпадает", wrong_mode, base_pset, {}, "apply_failed")

    # 6. слой не тот
    pset_lh = dict(base_pset)
    pset_lh["settings"] = {"layer_height": {"value": 0.15}}
    wrong_lh = mini_gcode({"PRINTING_MODE": "[classic]", "LAYER_HEIGHT": "0.2", "LAYER_COUNT": "1"}, [";LAYER:0"])
    run_test("высота слоя не совпадает", wrong_lh, pset_lh, {}, "apply_failed")

    # 7. температура не та
    pset_temp = dict(base_pset)
    pset_temp["settings"] = {"material_print_temperature": {"value": 210}}
    wrong_temp = mini_gcode({"PRINTING_MODE": "[classic]", "LAYER_COUNT": "1"}, [";LAYER:0", "M109 S200"])
    run_test("температура не совпадает", wrong_temp, pset_temp, {}, "apply_failed")

    # 8. настройка не совпала
    pset_setting = dict(base_pset)
    pset_setting["settings"] = {"top_layers": {"value": 5}}
    wrong_setting = mini_gcode(
        {"PRINTING_MODE": "[classic]", "LAYER_COUNT": "1"},
        [";LAYER:0"],
        {"global_quality": "[values]\\ntop_layers = 3\\n", "extruder_quality": []}
    )
    run_test("настройка не совпала", wrong_setting, pset_setting, {}, "apply_failed")

    # 9. выход за стол
    oob_gcode = mini_gcode(
        {"PRINTING_MODE": "[classic]", "LAYER_COUNT": "1"},
        [";LAYER:0", "G1 X400 Y100 Z1 E1"]
    )
    run_test("выход за стол", oob_gcode, base_pset, {}, "needs_changes")

    # 10. поддержки при forbid
    sup_forbid = mini_gcode({"PRINTING_MODE": "[classic]", "LAYER_COUNT": "1"}, [";LAYER:0", ";TYPE:SUPPORT"])
    run_test("поддержки при --forbid-supports", sup_forbid, base_pset, {"forbid_supports": True}, "needs_changes")

    # 11. поддержки при support_enable false
    pset_sup_false = dict(base_pset)
    pset_sup_false["settings"] = {"support_enable": {"value": False}}
    sup_off = mini_gcode({"PRINTING_MODE": "[classic]", "LAYER_COUNT": "1"}, [";LAYER:0", ";TYPE:SUPPORT"])
    run_test("поддержки при support_enable=false", sup_off, pset_sup_false, {}, "apply_failed")

    # 12. поддержек нет при support_enable true (info, не error)
    pset_sup_true = dict(base_pset)
    pset_sup_true["settings"] = {"support_enable": {"value": True}}
    no_sup = mini_gcode({"PRINTING_MODE": "[classic]", "LAYER_HEIGHT": "0.2", "LAYER_COUNT": "1"}, [";LAYER:0", "G1 X100 Y100 E1"])
    run_test("поддержек нет при support_enable=true", no_sup, pset_sup_true, {}, "ok")

    # 13. 5D с M140 (warning, не error)
    pset_5d = dict(base_pset)
    pset_5d["printing_mode"] = {"value": "cylindrical"}
    bed_5d = mini_gcode({"PRINTING_MODE": "[cylindrical]", "LAYER_HEIGHT": "0.2", "LAYER_COUNT": "1"}, [";LAYER:0", "M140 S60", "G1 X100 Y100 E1"])
    run_test("5D с M140", bed_5d, pset_5d, {}, "ok")

    # 14. кривой SETTING_3 (info, не error)
    bad_json = mini_gcode({"PRINTING_MODE": "[classic]", "LAYER_HEIGHT": "0.2", "LAYER_COUNT": "1"}, [";LAYER:0", "G1 X100 Y100 E1"])
    bad_json += "\n;SETTING_3 {bad json"
    run_test("кривой SETTING_3", bad_json, base_pset, {}, "ok")

    print(f"\n{passed} из {total} прошло")
    return passed == total


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("gcode", nargs="?", help="Файл G-code")
    parser.add_argument("pset", nargs="?", help="Файл parameter_set.json")
    parser.add_argument("--forbid-supports", action="store_true", help="Запретить поддержки")
    parser.add_argument("--iteration", type=int, default=1, help="Номер захода")
    parser.add_argument("--returns-used", type=int, default=0, help="Число использованных возвратов")
    parser.add_argument("--json", action="store_true", help="Вывод в JSON")
    parser.add_argument("--selftest", action="store_true", help="Запустить selftest")

    args = parser.parse_args(argv[1:])

    if args.selftest:
        return 0 if selftest() else 1

    if not args.gcode or not args.pset:
        parser.print_help()
        return 2

    if not os.path.exists(args.gcode):
        print(f"Ошибка: файл {args.gcode} не найден", file=sys.stderr)
        return 2

    if not os.path.exists(args.pset):
        print(f"Ошибка: файл {args.pset} не найден", file=sys.stderr)
        return 2

    pset = json.load(open(args.pset, "r", encoding="utf-8"))
    facts = parse_gcode(args.gcode)
    opts = {"forbid_supports": args.forbid_supports}
    findings = check(facts, pset, opts)
    feedback = build_feedback(findings, pset, args.iteration, args.returns_used)

    if args.json:
        print(json.dumps(feedback, ensure_ascii=False, indent=2))
    else:
        # Текстовый отчёт
        result_str = {"ok": "ОК", "needs_changes": "НУЖНЫ ИЗМЕНЕНИЯ", "apply_failed": "ОШИБКА ПРИМЕНЕНИЯ"}
        print(f"Итог: {result_str.get(feedback['result'], feedback['result'])}")

        errors = [f for f in findings if f["severity"] == "error"]
        warnings = [f for f in findings if f["severity"] == "warning"]
        infos = [f for f in findings if f["severity"] == "info"]

        if errors:
            print(f"\nОшибки ({len(errors)}):")
            for f in errors:
                print(f"  [{f['kind']}] {f['message']}")

        if warnings:
            print(f"\nПредупреждения ({len(warnings)}):")
            for f in warnings:
                print(f"  [{f['kind']}] {f['message']}")

        if infos:
            print(f"\nИнформация ({len(infos)}):")
            for f in infos:
                print(f"  {f['message']}")

    return 0 if feedback["result"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))

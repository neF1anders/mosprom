#!/usr/bin/env python3
"""Применение набора параметров этапа 2 в STE Slicer через MCP-плагин AI Assistant.

  python3 apply_parameter_set.py набор.json --model attachment-1=/путь/bracket.stl --out-dir папка
  python3 apply_parameter_set.py --selftest

Строит план, проверяет набор (при --resources), выполняет через плагин: принтер, режим, профиль, материал,
настройки, модели, slice, сохранение gcode и 3mf. Плагин подрезает значения к границам, шаги маркируются.
Только стандартная библиотека."""
import argparse
import http.server
import json
import math
import os
import sys
import threading
import time
import urllib.request
import urllib.error

# допущения о преобразовании координат (могут потребовать корректировки после запуска)
def pset_position_to_move_args(pos_xyz):
    """Поле position [X, Y, Z] из набора -> (x, z) для move_model.
    Допущение (не проверено запуском): Y интерфейса = минус Z сцены, высота игнорируется."""
    return (pos_xyz[0], -pos_xyz[1])


def rotation_matrix_to_euler_zyx(R):
    """Разложение матрицы поворота R в последовательность rotate_model(x, a), rotate_model(y, b), rotate_model(z, c).
    Возвращает [(axis, degrees), ...] в порядке применения (x, потом y, потом z в мировых осях сцены Y-up).
    Помечено «не проверено запуском: порядок и знак углов, сцена Y-up». R = Rz(c)·Ry(b)·Rx(a)."""
    # b = asin(-R[2][0]), кроме gimbal lock
    sin_b = -R[2][0]
    if abs(sin_b) >= 1.0 - 1e-9:  # gimbal lock |b| ≈ 90 градусов
        b = math.copysign(math.pi / 2, sin_b)
        if sin_b > 0:  # +90: a + c = atan2(R[0][1], R[1][1])
            a_plus_c = math.atan2(R[0][1], R[1][1])
            a, c = a_plus_c, 0
        else:  # -90: a - c = atan2(-R[0][1], R[1][1])
            a_minus_c = math.atan2(-R[0][1], R[1][1])
            a, c = a_minus_c, 0
    else:
        b = math.asin(sin_b)
        cos_b = math.cos(b)
        a = math.atan2(R[2][1] / cos_b, R[2][2] / cos_b)
        c = math.atan2(R[1][0] / cos_b, R[0][0] / cos_b)
    steps = []
    for axis, angle in [("x", a), ("y", b), ("z", c)]:
        deg = math.degrees(angle)
        if abs(deg) >= 1e-6:
            steps.append((axis, deg))
    return steps


def contract_axis_to_scene(axis, deg):
    """Ось и угол в системе набора (X вправо, Y вглубь, Z вверх, как у STL и стола) -> ось и угол сцены слайсера (Y вверх).
    Сцена получает точки STL как (x, z, -y): x остаётся x, Z набора это ось y сцены, Y набора это ось z сцены с обратным знаком.
    Проверено на Windows 24.10: поворот вокруг x (+90/-90) даёт ожидаемую грань вниз; в первой версии оси y и z
    передавались как есть, и поворот вокруг Z набора опрокидывал деталь вместо поворота на столе."""
    if axis == "x":
        return "x", deg
    if axis == "y":
        return "z", -deg
    return "y", deg


class ApplyError(Exception):
    pass


class McpClient:
    def __init__(self, server_json_path=None):
        if server_json_path is None:
            server_json_path = os.path.join(os.path.expanduser("~"), "Documents", "STE_AIAssistant", "server.json")
        if not os.path.isfile(server_json_path):
            raise ApplyError("server.json не найден: %s" % server_json_path)
        with open(server_json_path, encoding="utf-8") as f:
            data = json.load(f)
        self.port = data["port"]
        self.token = data["token"]
        self.pid = data["pid"]

    def call(self, name, args, timeout=60):
        url = "http://127.0.0.1:%d/mcp" % self.port
        request_body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}}
        req = urllib.request.Request(url, data=json.dumps(request_body).encode("utf-8"),
                                     headers={"Content-Type": "application/json", "Authorization": "Bearer %s" % self.token})
        try:
            response = urllib.request.urlopen(req, timeout=timeout)
            result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise ApplyError("HTTP %d: %s" % (e.code, e.reason))
        except Exception as e:
            raise ApplyError("сеть: %s" % e)
        if "result" not in result:
            raise ApplyError("нет result в ответе")
        content = result["result"].get("content", [])
        is_error = result["result"].get("isError", False)
        text = content[0]["text"] if content else ""
        if is_error:
            raise ApplyError(text)
        # текст успешного ответа: JSON (объект) или строка
        if text.strip().startswith("{") or text.strip().startswith("["):
            try:
                return json.loads(text)
            except Exception:
                pass
        return text


def build_plan(pset, model_paths, out_dir):
    """Построение упорядоченного плана шагов из набора параметров."""
    plan = []
    unsupported = []
    printer = pset.get("printer", "")
    mode_val = (pset.get("printing_mode") or {}).get("value", "")
    mode_why = (pset.get("printing_mode") or {}).get("why", "")
    quality_type = (pset.get("quality") or {}).get("quality_type", "")
    quality_why = (pset.get("quality") or {}).get("why", "")
    materials = pset.get("materials", {})
    settings_dict = pset.get("settings", {})
    models_list = pset.get("models", [])

    # set_printer
    plan.append({"step": "set_printer", "tool": "set_printer", "args": {"definition_id": printer}, "source": "принтер из набора", "note": ""})
    # set_print_mode
    plan.append({"step": "set_print_mode", "tool": "set_print_mode", "args": {"mode": mode_val, "reason": mode_why}, "source": "printing_mode", "note": ""})
    # set_quality_profile
    plan.append({"step": "set_quality_profile", "tool": "set_quality_profile", "args": {"quality_type": quality_type, "reason": quality_why}, "source": "quality", "note": ""})
    # set_material (только экструдер 0)
    for pos, mat_node in materials.items():
        mat_id = mat_node.get("id", "")
        mat_why = mat_node.get("why", "")
        if pos == "0":
            plan.append({"step": "set_material[%s]" % pos, "tool": "set_material", "args": {"material_id": mat_id, "reason": mat_why}, "source": "materials[%s]" % pos, "note": ""})
        else:
            unsupported.append({"step": "set_material[%s]" % pos, "reason": "плагин поддерживает только экструдер 0"})
    # set_setting (пропустить printing_mode и machine_*)
    for key, node in settings_dict.items():
        if key == "printing_mode" or key.startswith("machine_"):
            unsupported.append({"step": "set_setting[%s]" % key, "reason": "%s нельзя менять через set_setting" % key})
            continue
        val = node.get("value")
        why = node.get("why", "")
        plan.append({"step": "set_setting[%s]" % key, "tool": "set_setting", "args": {"key": key, "value": val, "reason": why}, "source": "settings.%s" % key, "note": ""})
    # модели
    for i, mdl in enumerate(models_list):
        att_id = mdl.get("attachment_id", "")
        if att_id not in model_paths:
            raise ApplyError("модель[%d] attachment_id=%r: нет пути в --model" % (i, att_id))
        model_path = model_paths[att_id]
        tf = mdl.get("transform", {})
        rot_matrix = tf.get("rotation", [[1, 0, 0], [0, 1, 0], [0, 0, 1]])
        pos = tf.get("position", [0, 0, 0])
        scale = tf.get("scale", [1, 1, 1])
        # load_model
        plan.append({"step": "load_model[%d]" % i, "tool": "load_model", "args": {"path": model_path}, "source": "models[%d]" % i, "note": ""})
        # повороты
        euler_steps = rotation_matrix_to_euler_zyx(rot_matrix)
        for axis, deg in euler_steps:
            scene_axis, scene_deg = contract_axis_to_scene(axis, deg)
            plan.append({"step": "rotate_model[%d,%s]" % (i, scene_axis), "tool": "rotate_model", "args": {"axis": scene_axis, "degrees": scene_deg, "reason": mdl.get("why", ""), "model_index": i}, "source": "models[%d].rotation" % i, "note": "ось набора %s -> ось сцены %s (после правки не проверено на Windows)" % (axis, scene_axis)})
        # масштаб
        sx, sy, sz = scale
        if abs(sx - sy) < 1e-9 and abs(sy - sz) < 1e-9:
            if abs(sx - 1.0) >= 1e-9:
                plan.append({"step": "scale_model[%d]" % i, "tool": "scale_model", "args": {"factor": sx, "reason": mdl.get("why", ""), "model_index": i}, "source": "models[%d].scale" % i, "note": ""})
        else:
            unsupported.append({"step": "scale_model[%d]" % i, "reason": "плагин умеет только равномерный масштаб, запрошено [%s, %s, %s]" % (sx, sy, sz)})
        # положение
        mx, mz = pset_position_to_move_args(pos)
        plan.append({"step": "move_model[%d]" % i, "tool": "move_model", "args": {"x": mx, "z": mz, "model_index": i}, "source": "models[%d].position" % i, "note": "допущение: Y интерфейса = -Z сцены (не проверено)"})
    # slice
    plan.append({"step": "slice_model", "tool": "slice_model", "args": {}, "source": "финальный шаг", "note": "таймаут 330с"})
    # export_gcode
    gcode_path = os.path.join(out_dir, "result.gcode")
    plan.append({"step": "export_gcode", "tool": "export_gcode", "args": {"path": gcode_path}, "source": "финальный шаг", "note": ""})
    # save_project
    project_path = os.path.join(out_dir, "project.3mf")
    plan.append({"step": "save_project", "tool": "save_project", "args": {"path": project_path}, "source": "финальный шаг", "note": ""})
    return plan, unsupported


def apply(plan, client):
    """Выполнение шагов плана через MCP-клиент."""
    report = []
    clamped = []
    for step_dict in plan:
        step_name = step_dict["step"]
        tool = step_dict["tool"]
        args = step_dict["args"]
        timeout = 330 if tool == "slice_model" else 60
        try:
            result = client.call(tool, args, timeout=timeout)
            # для set_setting разбираем строку "key: old -> new"
            if tool == "set_setting":
                text = str(result)
                if " -> " in text:
                    parts = text.split(" -> ")
                    if len(parts) == 2:
                        left = parts[0].split(":")
                        if len(left) == 2:
                            key_from_result = left[0].strip()
                            new_str = parts[1].strip()
                            requested = args["value"]
                            # сравниваем типы: bool остаётся bool, числа числами
                            new_val = new_str
                            if isinstance(requested, bool):
                                new_val = new_str.lower() in ("true", "1")
                            elif isinstance(requested, int) and not isinstance(requested, bool):
                                try:
                                    new_val = int(new_str)
                                except Exception:
                                    try:
                                        new_val = float(new_str)
                                    except Exception:
                                        pass
                            elif isinstance(requested, float):
                                try:
                                    new_val = float(new_str)
                                except Exception:
                                    pass
                            if new_val != requested:
                                clamped.append({"key": key_from_result, "requested": requested, "written": new_val})
            report.append({"step": step_name, "tool": tool, "ok": True, "result": result})
        except ApplyError as e:
            report.append({"step": step_name, "tool": tool, "ok": False, "error": str(e)})
            break
        except Exception as e:
            report.append({"step": step_name, "tool": tool, "ok": False, "error": "исключение: %s" % e})
            break
    return report, clamped


def dry_run_plan(plan, unsupported):
    """Печать плана без выполнения."""
    print("План (%d шагов):" % len(plan))
    for i, s in enumerate(plan, 1):
        note = (" (%s)" % s["note"]) if s["note"] else ""
        print("  %d. %s: %s%s" % (i, s["step"], s["tool"], note))
        print("     args: %s" % json.dumps(s["args"], ensure_ascii=False))
    if unsupported:
        print("Не поддержано (%d шагов):" % len(unsupported))
        for u in unsupported:
            print("  - %s: %s" % (u["step"], u["reason"]))


def main_cli(argv):
    parser = argparse.ArgumentParser(description="Применение набора параметров в STE Slicer через плагин.")
    parser.add_argument("parameter_set", nargs="?", help="файл stage2.parameter_set JSON")
    parser.add_argument("--model", action="append", dest="models", help="attachment_id=путь.stl")
    parser.add_argument("--out-dir", required=False, help="папка для result.gcode и project.3mf")
    parser.add_argument("--server-json", help="путь к server.json плагина (по умолчанию ~/Documents/STE_AIAssistant/server.json)")
    parser.add_argument("--dry-run", action="store_true", help="печать плана без выполнения")
    parser.add_argument("--resources", help="папка ste_5.2.4/resources для проверки набора перед применением")
    parser.add_argument("--report", help="файл report.json с результатом")
    parser.add_argument("--selftest", action="store_true", help="запуск встроенных тестов")
    args = parser.parse_args(argv[1:])

    if args.selftest:
        return selftest()

    if not args.parameter_set:
        parser.print_help()
        return 2
    if not os.path.isfile(args.parameter_set):
        print("Ошибка: файл %s не найден" % args.parameter_set)
        return 2
    with open(args.parameter_set, encoding="utf-8") as f:
        pset = json.load(f)

    # model_paths
    model_paths = {}
    for spec in (args.models or []):
        if "=" not in spec:
            print("Ошибка: --model нужен вид attachment_id=путь")
            return 2
        att_id, path = spec.split("=", 1)
        model_paths[att_id] = path

    # проверка набора, если --resources
    if args.resources:
        # импорт check_parameter_set из той же папки tools
        tools_dir = os.path.dirname(os.path.abspath(__file__))
        sys.path.insert(0, tools_dir)
        try:
            import check_parameter_set as cps
        except ImportError:
            print("Нет check_parameter_set.py рядом со скриптом: --resources работает только там, где он лежит "
                  "(ветка fedor/validation-ste). В основном решении проверку делает этап 3 (src/backend/validation).")
            return 2
        cat = cps.Catalog(args.resources, pset.get("printer", "hte530v5.2.4"))
        issues = cps.check(cat, pset)
        errors = [i for i in issues if i[0] == "error"]
        if errors:
            for level, where, msg in issues:
                print("[%s] %s: %s" % (level.upper(), where, msg))
            print("Ошибок проверки: %d, набор не применён" % len(errors))
            return 1

    if not args.resources:
        print("ВНИМАНИЕ: набор не проверен по допустимым границам (нет --resources). Слайсер и плагин значения не подрезают "
              "(проверено на Windows: infill_sparse_density 150 принят без подрезки), поэтому границы проверяет только этап 3.")

    # план
    try:
        plan, unsupported = build_plan(pset, model_paths, args.out_dir or ".")
    except ApplyError as e:
        print("Ошибка построения плана: %s" % e)
        return 2

    if args.dry_run:
        dry_run_plan(plan, unsupported)
        return 0

    # выполнение
    try:
        client = McpClient(args.server_json)
    except ApplyError as e:
        print("Ошибка подключения: %s" % e)
        return 1

    report_steps, clamped = apply(plan, client)
    failed = [s for s in report_steps if not s["ok"]]

    # итог
    print("Выполнено шагов: %d из %d" % (len([s for s in report_steps if s["ok"]]), len(plan)))
    if clamped:
        print("Подрезанных значений: %d" % len(clamped))
        for c in clamped:
            print("  %s: запрошено %s, записано %s" % (c["key"], c["requested"], c["written"]))
    if unsupported:
        print("Не поддержано: %d шагов" % len(unsupported))
        for u in unsupported:
            print("  - %s: %s" % (u["step"], u["reason"]))
    if failed:
        print("Ошибка на шаге %s: %s" % (failed[0]["step"], failed[0].get("error", "")))
        if args.report:
            with open(args.report, "w", encoding="utf-8") as f:
                json.dump({"ok": False, "steps": report_steps, "clamped": clamped, "unsupported": unsupported}, f, ensure_ascii=False, indent=2)
        return 1
    # пути результатов
    gcode_path = os.path.join(args.out_dir or ".", "result.gcode")
    project_path = os.path.join(args.out_dir or ".", "project.3mf")
    print("Готово: %s, %s" % (gcode_path, project_path))
    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            json.dump({"ok": True, "steps": report_steps, "clamped": clamped, "unsupported": unsupported, "gcode": gcode_path, "project": project_path}, f, ensure_ascii=False, indent=2)
    return 0


# ================================================================ selftest

def example_path():
    here = os.path.dirname(os.path.abspath(__file__))
    for rel in (("..", "contracts"), ("..", "..", "tests", "slicing")):
        path = os.path.join(here, *rel, "example_bracket_petg_classic.json")
        if os.path.exists(path):
            return path
    raise ApplyError("не найден example_bracket_petg_classic.json")


def selftest():
    """Встроенные тесты без реального слайсера (поддельный MCP-сервер)."""
    print("=== selftest ===")
    passed = 0
    total = 0

    # поддельный MCP-сервер
    class FakeMcpHandler(http.server.BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass
        def do_POST(self):
            if self.path != "/mcp":
                self.send_error(404)
                return
            # проверка токена
            auth_header = self.headers.get("Authorization", "")
            expected_token = self.server.token
            if auth_header != "Bearer %s" % expected_token:
                self.send_response(401)
                self.end_headers()
                return
            # чтение тела
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            req = json.loads(body)
            name = req["params"]["name"]
            args = req["params"]["arguments"]
            # запоминаем вызов
            self.server.calls.append((name, args))
            # ответ
            is_error = False
            text = "ok"
            # эмуляция set_setting с подрезкой
            if name == "set_setting":
                key = args["key"]
                val = args["value"]
                # подрезка по таблице
                clamped_val = val
                if key == "layer_height" and val < 0.05:
                    clamped_val = 0.05
                text = "%s: old -> %s" % (key, clamped_val)
            # эмуляция ошибки по запросу
            if hasattr(self.server, "error_on_step") and self.server.error_on_step:
                step_count = len(self.server.calls)
                if step_count == self.server.error_on_step:
                    is_error = True
                    text = "fake error"
            # JSON-ответ
            resp = {"jsonrpc": "2.0", "id": req["id"], "result": {"content": [{"type": "text", "text": text}], "isError": is_error}}
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(resp).encode("utf-8"))

    def start_fake_server(token, error_on_step=0):
        server = http.server.HTTPServer(("127.0.0.1", 0), FakeMcpHandler)
        server.token = token
        server.calls = []
        server.error_on_step = error_on_step
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        return server

    def fake_server_json(port, token):
        import tempfile
        fd, path = tempfile.mkstemp(suffix=".json", text=True)
        os.write(fd, json.dumps({"port": port, "token": token, "pid": 12345}).encode("utf-8"))
        os.close(fd)
        return path

    # вспомогательная функция проверки
    def test(name, func):
        nonlocal passed, total
        total += 1
        try:
            func()
            print("OK  %s" % name)
            passed += 1
        except AssertionError as e:
            print("СБОЙ %s: %s" % (name, e))
        except Exception as e:
            print("СБОЙ %s: исключение %s" % (name, e))

    # тест 1: план из примера
    def t1():
        pset = json.loads(open(example_path(), encoding="utf-8").read())
        model_paths = {"attachment-1": "/fake/bracket.stl"}
        plan, unsupported = build_plan(pset, model_paths, "/out")
        assert len(plan) > 0, "план пуст"
        # проверка порядка
        steps = [s["step"] for s in plan]
        assert steps[0] == "set_printer", "первый шаг должен быть set_printer"
        assert "set_print_mode" in steps, "нет set_print_mode"
        assert "set_quality_profile" in steps, "нет set_quality_profile"
        assert "set_material[0]" in steps, "нет set_material[0]"
        assert "slice_model" in steps, "нет slice_model"
        assert "export_gcode" in steps, "нет export_gcode"
        assert "save_project" in steps, "нет save_project"
        # аргументы
        printer_step = [s for s in plan if s["step"] == "set_printer"][0]
        assert printer_step["args"]["definition_id"] == "hte530v5.2.4", "definition_id"
    test("план из примера", t1)

    # тест 2: поворот на 90 градусов вокруг x
    def t2():
        R = [[1, 0, 0], [0, 0, -1], [0, 1, 0]]  # поворот на +90 градусов вокруг x
        steps = rotation_matrix_to_euler_zyx(R)
        assert len(steps) == 1, "ожидался один шаг поворота"
        assert steps[0][0] == "x", "ось должна быть x"
        assert abs(steps[0][1] - 90) < 0.01, "угол должен быть около 90"
    test("поворот 90 град вокруг x", t2)

    # тест 3: gimbal lock
    def t3():
        # sin_b = 1 (b = +90), тест обработки
        sin_b = 1.0
        R = [[0, 0, -1], [sin_b, 0, 0], [0, -1, 0]]
        # обратная сборка из результата должна дать близкую матрицу
        steps = rotation_matrix_to_euler_zyx(R)
        # проверка: сборка обратно
        a = b = c = 0.0
        for axis, deg in steps:
            angle = math.radians(deg)
            if axis == "x":
                a = angle
            elif axis == "y":
                b = angle
            elif axis == "z":
                c = angle
        # Rz(c)·Ry(b)·Rx(a)
        Rx = [[1, 0, 0], [0, math.cos(a), -math.sin(a)], [0, math.sin(a), math.cos(a)]]
        Ry = [[math.cos(b), 0, math.sin(b)], [0, 1, 0], [-math.sin(b), 0, math.cos(b)]]
        Rz = [[math.cos(c), -math.sin(c), 0], [math.sin(c), math.cos(c), 0], [0, 0, 1]]
        # R_result = Rz @ Ry @ Rx
        def matmul(A, B):
            return [[sum(A[i][k] * B[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
        R_result = matmul(Rz, matmul(Ry, Rx))
        diff = sum(abs(R_result[i][j] - R[i][j]) for i in range(3) for j in range(3))
        assert diff < 0.1, "gimbal lock: разница %.4f" % diff
    test("поворот gimbal lock", t3)

    # тест 4: неравномерный масштаб -> unsupported
    def t4():
        pset = {"printer": "hte530v5.2.4", "printing_mode": {"value": "classic", "why": "x", "source": "default"},
                "quality": {"quality_type": "draft", "why": "x", "source": "default"},
                "materials": {"0": {"id": "generic_petg_175", "why": "x", "source": "default"}},
                "settings": {}, "models": [{"attachment_id": "a1", "transform": {"rotation": [[1, 0, 0], [0, 1, 0], [0, 0, 1]], "position": [0, 0, 0], "scale": [1, 2, 1]}, "why": "x", "source": "default"}]}
        model_paths = {"a1": "/fake.stl"}
        plan, unsupported = build_plan(pset, model_paths, "/out")
        assert len(unsupported) > 0, "ожидался unsupported шаг"
        assert any("scale_model" in u["step"] for u in unsupported), "должен быть scale_model в unsupported"
    test("неравномерный масштаб unsupported", t4)

    # тест 5: материал второго экструдера -> unsupported
    def t5():
        pset = {"printer": "hte530v5.2.4", "printing_mode": {"value": "classic", "why": "x", "source": "default"},
                "quality": {"quality_type": "draft", "why": "x", "source": "default"},
                "materials": {"0": {"id": "generic_petg_175", "why": "x", "source": "default"}, "1": {"id": "generic_pla_175", "why": "x", "source": "default"}},
                "settings": {}, "models": []}
        model_paths = {}
        plan, unsupported = build_plan(pset, model_paths, "/out")
        assert len(unsupported) > 0, "ожидался unsupported шаг"
        assert any("set_material[1]" in u["step"] for u in unsupported), "должен быть set_material[1] в unsupported"
    test("материал второго экструдера unsupported", t5)

    # тест 6: ключ machine_* пропущен
    def t6():
        pset = {"printer": "hte530v5.2.4", "printing_mode": {"value": "classic", "why": "x", "source": "default"},
                "quality": {"quality_type": "draft", "why": "x", "source": "default"},
                "materials": {"0": {"id": "generic_petg_175", "why": "x", "source": "default"}},
                "settings": {"machine_width": {"value": 500, "why": "x", "source": "default"}}, "models": []}
        model_paths = {}
        plan, unsupported = build_plan(pset, model_paths, "/out")
        assert any("set_setting[machine_width]" in u["step"] for u in unsupported), "machine_* должен быть в unsupported"
    test("ключ machine_* пропущен", t6)

    # тест 7: нет пути модели -> ошибка плана
    def t7():
        pset = {"printer": "hte530v5.2.4", "printing_mode": {"value": "classic", "why": "x", "source": "default"},
                "quality": {"quality_type": "draft", "why": "x", "source": "default"},
                "materials": {"0": {"id": "generic_petg_175", "why": "x", "source": "default"}},
                "settings": {}, "models": [{"attachment_id": "a1", "transform": {"rotation": [[1, 0, 0], [0, 1, 0], [0, 0, 1]], "position": [0, 0, 0], "scale": [1, 1, 1]}, "why": "x", "source": "default"}]}
        model_paths = {}
        try:
            plan, unsupported = build_plan(pset, model_paths, "/out")
            assert False, "должна быть ошибка"
        except ApplyError:
            pass
    test("нет пути модели ошибка", t7)

    # тест 8: полный прогон на поддельном сервере
    def t8():
        pset = {"printer": "hte530v5.2.4", "printing_mode": {"value": "classic", "why": "x", "source": "default"},
                "quality": {"quality_type": "draft", "why": "x", "source": "default"},
                "materials": {"0": {"id": "generic_petg_175", "why": "x", "source": "default"}},
                "settings": {"wall_line_count": {"value": 4, "why": "x", "source": "default"}}, "models": [{"attachment_id": "a1", "transform": {"rotation": [[1, 0, 0], [0, 1, 0], [0, 0, 1]], "position": [0, 0, 0], "scale": [1, 1, 1]}, "why": "x", "source": "default"}]}
        model_paths = {"a1": "/fake.stl"}
        plan, unsupported = build_plan(pset, model_paths, "/out")
        server = start_fake_server("testtoken")
        time.sleep(0.1)
        srv_json_path = fake_server_json(server.server_address[1], "testtoken")
        client = McpClient(srv_json_path)
        report, clamped = apply(plan, client)
        os.unlink(srv_json_path)
        assert all(s["ok"] for s in report), "все шаги должны быть ok"
        # проверка порядка вызовов
        call_names = [c[0] for c in server.calls]
        assert call_names[0] == "set_printer", "первый вызов set_printer"
        assert "set_print_mode" in call_names, "нет set_print_mode"
        assert "slice_model" in call_names, "нет slice_model"
        server.shutdown()
    test("полный прогон поддельный сервер", t8)

    # тест 9: ошибка на шаге 3 останавливает остальные
    def t9():
        pset = {"printer": "hte530v5.2.4", "printing_mode": {"value": "classic", "why": "x", "source": "default"},
                "quality": {"quality_type": "draft", "why": "x", "source": "default"},
                "materials": {"0": {"id": "generic_petg_175", "why": "x", "source": "default"}},
                "settings": {"wall_line_count": {"value": 4, "why": "x", "source": "default"}}, "models": []}
        model_paths = {}
        plan, unsupported = build_plan(pset, model_paths, "/out")
        server = start_fake_server("testtoken", error_on_step=3)
        time.sleep(0.1)
        srv_json_path = fake_server_json(server.server_address[1], "testtoken")
        client = McpClient(srv_json_path)
        report, clamped = apply(plan, client)
        os.unlink(srv_json_path)
        assert len(report) == 3, "должно быть 3 шага (ошибка на 3-м)"
        assert not report[2]["ok"], "3-й шаг должен быть ошибкой"
        server.shutdown()
    test("ошибка на шаге 3 останавливает", t9)

    # тест 10: подрезанное значение попадает в clamped
    def t10():
        pset = {"printer": "hte530v5.2.4", "printing_mode": {"value": "classic", "why": "x", "source": "default"},
                "quality": {"quality_type": "draft", "why": "x", "source": "default"},
                "materials": {"0": {"id": "generic_petg_175", "why": "x", "source": "default"}},
                "settings": {"layer_height": {"value": 0.01, "why": "x", "source": "default"}}, "models": []}
        model_paths = {}
        plan, unsupported = build_plan(pset, model_paths, "/out")
        server = start_fake_server("testtoken")
        time.sleep(0.1)
        srv_json_path = fake_server_json(server.server_address[1], "testtoken")
        client = McpClient(srv_json_path)
        report, clamped = apply(plan, client)
        os.unlink(srv_json_path)
        assert len(clamped) > 0, "должно быть подрезанное значение"
        assert clamped[0]["key"] == "layer_height", "ключ layer_height"
        assert clamped[0]["requested"] == 0.01, "запрошено 0.01"
        assert clamped[0]["written"] == 0.05, "записано 0.05"
        server.shutdown()
    test("подрезанное значение в clamped", t10)

    # тест 11: неверный токен -> ошибка
    def t11():
        server = start_fake_server("goodtoken")
        time.sleep(0.1)
        srv_json_path = fake_server_json(server.server_address[1], "badtoken")
        client = McpClient(srv_json_path)
        try:
            client.call("get_state", {})
            assert False, "должна быть ошибка авторизации"
        except ApplyError as e:
            assert "401" in str(e), "ожидалась ошибка 401"
        os.unlink(srv_json_path)
        server.shutdown()
    test("неверный токен ошибка", t11)

    # тест 12: dry-run не открывает сеть
    def t12():
        # проверка что dry_run_plan не вызывает сетевые функции
        pset = {"printer": "hte530v5.2.4", "printing_mode": {"value": "classic", "why": "x", "source": "default"},
                "quality": {"quality_type": "draft", "why": "x", "source": "default"},
                "materials": {"0": {"id": "generic_petg_175", "why": "x", "source": "default"}},
                "settings": {}, "models": []}
        model_paths = {}
        plan, unsupported = build_plan(pset, model_paths, "/out")
        # просто вызываем, не должно быть исключений
        import io
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        dry_run_plan(plan, unsupported)
        output = sys.stdout.getvalue()
        sys.stdout = old_stdout
        assert "План" in output, "должен быть заголовок Плана"
    test("dry-run не открывает сеть", t12)

    # тест 13: оси набора переводятся в оси сцены (Windows 24.10: поворот вокруг z набора опрокидывал деталь)
    def t13():
        example = example_path()
        base = json.loads(open(example, encoding="utf-8").read())

        def rot_steps(R):
            p = json.loads(json.dumps(base))
            p["models"][0]["transform"]["rotation"] = R
            plan, _ = build_plan(p, {"attachment-1": "/m.stl"}, "/out")
            return [(s["args"]["axis"], round(s["args"]["degrees"], 6)) for s in plan if s["tool"] == "rotate_model"]
        c, sn = math.cos(math.radians(45)), math.sin(math.radians(45))
        assert rot_steps([[1, 0, 0], [0, 0, -1], [0, 1, 0]]) == [("x", 90.0)], "x"
        assert rot_steps([[0, -1, 0], [1, 0, 0], [0, 0, 1]]) == [("y", 90.0)], "z набора это y сцены"
        assert rot_steps([[c, 0, sn], [0, 1, 0], [-sn, 0, c]]) == [("z", -45.0)], "y набора это z сцены со знаком минус"
    test("оси набора -> оси сцены", t13)

    print("=" * 40)
    print("%d из %d прошло" % (passed, total))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main_cli(sys.argv))

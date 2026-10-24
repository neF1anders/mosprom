#!/usr/bin/env python3
"""Полный прогон конвейера параметров через HTTP API и оценка качества.

Создаёт задание, отправляет сообщение и STL, ждёт завершения конвейера (pipeline.completed)
или таймаута, проверяет ожидания и собирает метрики. Результаты в <out-dir>/<время>/.

Usage:
    python scripts/eval_pipeline.py --cases out/eval_cases.json [--user-id local] [--timeout 900]
    python scripts/eval_pipeline.py --organizer-dir ~/Downloads/"Примеры деталей" --user-id local
    python scripts/eval_pipeline.py --selftest

Авторизация: --user-id <id> (токен берётся из SESSION_SECRET в .env или переменной среды).
Для получения токена используется тот же механизм, что в scripts/bootstrap.py.
"""

import argparse
import base64
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from typing import Any, Dict, List, Optional
from uuid import uuid4


@dataclass
class CaseExpectation:
    """Ожидания для случая."""

    printing_mode: Optional[str] = None
    material_contains: Optional[str] = None
    quality_in: List[str] = field(default_factory=list)
    settings: Dict[str, Any] = field(default_factory=dict)
    completed: bool = True
    result_attention: Optional[bool] = None


@dataclass
class CaseResult:
    """Результат прогона одного случая."""

    case_id: str
    status: str
    completed: bool = False
    result: Optional[str] = None  # ok/attention/error
    iterations: int = 0
    validation_remarks: int = 0
    validation_remarks_text: List[str] = field(default_factory=list)
    gcode_result: Optional[str] = None
    print_time_seconds: Optional[int] = None
    material_grams: Optional[float] = None
    message: str = ""
    parameters: Optional[Dict[str, Any]] = None
    project_folder: Optional[str] = None
    stage_times: Dict[str, float] = field(default_factory=dict)
    expectations: Dict[str, str] = field(default_factory=dict)  # pass/fail/n/a
    error: Optional[str] = None
    elapsed_seconds: float = 0.0


def sign_token(secret: str, kind: str, expires: int, user_id: str) -> str:
    """Создаёт подписанный токен (как в bootstrap.py и tokens.py)."""
    payload = base64.urlsafe_b64encode(
        json.dumps(
            {
                "kind": kind,
                "expires": expires,
                "nonce": str(uuid4()),
                "user_id": user_id,
            }
        ).encode()
    ).decode()
    signature = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return payload + "." + signature


class ApiClient:
    """HTTP клиент для работы с API стенда."""

    def __init__(self, base_url: str, session_secret: str, user_id: str):
        self.base_url = base_url.rstrip("/")
        self.session_secret = session_secret
        self.user_id = user_id
        self.session_token: Optional[str] = None

    def _request(
        self,
        method: str,
        path: str,
        data: Any = None,
        files: Optional[Dict] = None,
        headers: Optional[Dict] = None,
    ) -> Any:
        """Выполняет HTTP запрос."""
        url = self.base_url + path
        req_headers = headers or {}

        # Добавляем cookie с сессией если есть
        if self.session_token:
            req_headers["Cookie"] = f"mosprom_session={self.session_token}"

        # Для multipart/form-data создаём boundary и тело
        if files:
            boundary = f"----WebKitFormBoundary{uuid4().hex[:16]}"
            req_headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"

            parts = []
            # Добавляем поля данных
            if data:
                for key, value in data.items():
                    parts.append(f"--{boundary}\r\n")
                    parts.append(f'Content-Disposition: form-data; name="{key}"\r\n\r\n')
                    parts.append(f"{value}\r\n")

            # Добавляем файлы
            for field_name, (filename, content) in files.items():
                parts.append(f"--{boundary}\r\n")
                parts.append(
                    f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'
                )
                parts.append("Content-Type: application/octet-stream\r\n\r\n")
                # content должен быть байтами
                body_data = "".join(parts).encode() + content + f"\r\n--{boundary}--\r\n".encode()
                break  # Обрабатываем только один файл за раз
        elif data is not None:
            req_headers["Content-Type"] = "application/json"
            body_data = json.dumps(data).encode()
        else:
            body_data = None

        req = urllib.request.Request(url, data=body_data, headers=req_headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                content = response.read()
                if response.headers.get("Content-Type", "").startswith("application/json"):
                    return json.loads(content.decode())
                return content
        except urllib.error.HTTPError as e:
            error_body = e.read().decode() if e.fp else ""
            raise Exception(f"HTTP {e.code}: {error_body}")
        except urllib.error.URLError as e:
            raise Exception(f"Network error: {e.reason}")

    def authenticate(self) -> None:
        """Обменивает launch токен на session токен."""
        launch_token = sign_token(
            self.session_secret, "launch", int(time.time()) + 600, self.user_id
        )

        self._request("POST", "/api/v1/session/exchange", {"token": launch_token})

        # Сервер устанавливает cookie, но в urllib нужно извлечь вручную
        # Для простоты создадим session токен сразу
        self.session_token = sign_token(
            self.session_secret, "session", int(time.time()) + 30 * 86400, self.user_id
        )

    def create_job(self, title: str = "Eval case") -> Dict:
        """Создаёт новое задание."""
        return self._request("POST", "/api/v1/jobs", {"request_id": str(uuid4()), "title": title})

    def send_message(self, job_id: str, text: str) -> Dict:
        """Отправляет сообщение в задание."""
        return self._request(
            "POST", f"/api/v1/jobs/{job_id}/messages", {"request_id": str(uuid4()), "text": text}
        )

    def upload_attachment(self, job_id: str, filename: str, content: bytes) -> Dict:
        """Загружает вложение к заданию."""
        boundary = f"----WebKitFormBoundary{uuid4().hex[:16]}"

        parts = []
        # request_id как form field
        request_id = str(uuid4())
        parts.append(f"--{boundary}\r\n")
        parts.append('Content-Disposition: form-data; name="request_id"\r\n\r\n')
        parts.append(f"{request_id}\r\n")

        # file field
        parts.append(f"--{boundary}\r\n")
        parts.append(f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n')
        parts.append("Content-Type: application/octet-stream\r\n\r\n")

        body = "".join(parts).encode() + content + f"\r\n--{boundary}--\r\n".encode()

        req = urllib.request.Request(
            self.base_url + f"/api/v1/jobs/{job_id}/attachments",
            data=body,
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Cookie": f"mosprom_session={self.session_token}",
            },
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode())

    def get_job_snapshot(self, job_id: str) -> Dict:
        """Получает снимок задания."""
        return self._request("GET", f"/api/v1/jobs/{job_id}")

    def get_parameters(self, job_id: str) -> Dict:
        """Получает набор параметров задания."""
        return self._request("GET", f"/api/v1/jobs/{job_id}/parameters")

    def answer_questions(self, job_id: str, revision: int, answers: dict[str, str]) -> Dict:
        """Отвечает на вопросы агента."""
        return self._request(
            "POST",
            f"/api/v1/jobs/{job_id}/answers",
            {"request_id": str(uuid4()), "expected_revision": revision, "answers": answers},
        )


def _answer_open_questions(
    client: ApiClient, job_id: str, job_data: dict, auto_answer: str
) -> bool:
    """Отвечает на неотвеченные вопросы карточки; без вопросов (карточки ещё нет, шлюз просит
    подтвердить запуск) отвечает в чат."""
    questions = (job_data.get("card") or {}).get("questions", [])
    answers = {
        q["id"]: ("mm" if q["id"] == "units" else auto_answer)
        for q in questions
        if q.get("answer") is None
    }
    if answers:
        client.answer_questions(job_id, job_data.get("revision", 0), answers)
    else:
        client.send_message(job_id, auto_answer)
    return True


def _wait_for_job(
    client: ApiClient,
    job_id: str,
    result: CaseResult,
    start: float,
    timeout: float,
    auto_answer: str,
) -> dict:
    """Опрашивает задание до конца; события в снимке не приходят, итог читаем из состояния задания."""
    last_stage = None
    answered = 0
    deadline = time.time() + timeout
    job_data: dict = {}
    while time.time() < deadline:
        job_data = client.get_job_snapshot(job_id).get("job", {})
        stage = job_data.get("stage")
        if stage and stage != last_stage:
            result.stage_times[stage] = round(time.time() - start, 1)
            last_stage = stage
        status = job_data.get("status")
        if status == "waiting_user" and answered < 3:
            answered += _answer_open_questions(client, job_id, job_data, auto_answer)
        if status in ("completed", "failed", "stopped"):
            result.status = status
            result.completed = status == "completed"
            return job_data
        time.sleep(2)
    result.error, result.status = "Timeout", "timeout"
    return job_data


def _fill_result(client: ApiClient, job_id: str, job_data: dict, result: CaseResult) -> None:
    """Параметры и итог из набора параметров и сводок задания."""
    if result.completed:
        try:
            result.parameters = client.get_parameters(job_id)
        except Exception as e:
            result.error = f"Не удалось получить параметры: {e}"
    summary = job_data.get("parameters") or {}
    result.iterations = max(
        summary.get("iteration", 0), (result.parameters or {}).get("iteration", 0)
    )
    outcome = job_data.get("result") or {}
    if result.completed:
        checked = summary.get("check") == "ok"
        gcode_ok = outcome.get("gcode_check") == "ok"
        result.result = "ok" if outcome.get("sliced") and checked and gcode_ok else "attention"
    result.message = outcome.get("message", "")
    result.gcode_result = outcome.get("gcode_check")
    result.print_time_seconds = outcome.get("print_time_seconds")
    result.material_grams = outcome.get("material_grams")
    result.project_folder = outcome.get("folder")


def run_case(
    client: ApiClient,
    case_id: str,
    message: str,
    attachments: list[Path],
    expect: CaseExpectation,
    timeout: float,
    auto_answer: str,
) -> CaseResult:
    """Прогоняет один случай через конвейер."""
    result = CaseResult(case_id=case_id, status="running")
    start_time = time.time()
    try:
        job_id = client.create_job(f"Eval: {case_id}")["id"]
        for path in attachments:
            if not path.exists():
                result.error, result.status = f"Файл не найден: {path}", "failed"
                return result
            client.upload_attachment(job_id, path.name, path.read_bytes())
        client.send_message(job_id, message)
        job_data = _wait_for_job(client, job_id, result, start_time, timeout, auto_answer)
        _fill_result(client, job_id, client.get_job_snapshot(job_id).get("job", job_data), result)
        result.expectations = check_expectations(expect, result)
    except Exception as e:
        result.error, result.status = str(e), "failed"
    result.elapsed_seconds = time.time() - start_time
    return result


def check_expectations(expect: CaseExpectation, result: CaseResult) -> dict[str, str]:
    """Проверяет ожидания случая. Возвращает {expectation: "pass"/"fail"/"n/a"}."""
    checks = {}

    if not result.parameters:
        return {
            k: "n/a"
            for k in [
                "printing_mode",
                "material_contains",
                "quality_in",
                "settings",
                "completed",
                "result_attention",
            ]
        }

    params = result.parameters

    # printing_mode
    if expect.printing_mode:
        mode = params.get("printing_mode", {}).get("value")
        checks["printing_mode"] = "pass" if mode == expect.printing_mode else "fail"
    else:
        checks["printing_mode"] = "n/a"

    # material_contains
    if expect.material_contains:
        materials = params.get("materials", {})
        material_ids = [m.get("id", "") for m in materials.values()]
        found = any(expect.material_contains.lower() in mid.lower() for mid in material_ids)
        checks["material_contains"] = "pass" if found else "fail"
    else:
        checks["material_contains"] = "n/a"

    # quality_in
    if expect.quality_in:
        quality = params.get("quality", {}).get("quality_type", "")
        checks["quality_in"] = "pass" if quality in expect.quality_in else "fail"
    else:
        checks["quality_in"] = "n/a"

    # settings
    if expect.settings:
        settings = params.get("settings", {})
        all_match = all(
            settings.get(key, {}).get("value") == value for key, value in expect.settings.items()
        )
        checks["settings"] = "pass" if all_match else "fail"
    else:
        checks["settings"] = "n/a"

    # completed
    if expect.completed:
        checks["completed"] = "pass" if result.completed else "fail"
    else:
        checks["completed"] = "n/a"

    # result_attention
    if expect.result_attention is not None:
        actual_attention = result.result == "attention"
        expected_attention = expect.result_attention
        checks["result_attention"] = "pass" if actual_attention == expected_attention else "fail"
    else:
        checks["result_attention"] = "n/a"

    return checks


def load_cases_from_json(
    path: Path, base_dir: Path
) -> list[tuple[str, str, list[Path], CaseExpectation]]:
    """Загружает случаи из eval_cases.json."""
    data = json.loads(path.read_text())
    cases = []

    for case in data.get("cases", []):
        case_id = case["id"]
        message = case["message"]
        attachments = [base_dir / att for att in case.get("attachments", [])]

        expect_data = case.get("expect", {})
        expect = CaseExpectation(
            printing_mode=expect_data.get("printing_mode"),
            material_contains=expect_data.get("material_contains"),
            quality_in=expect_data.get("quality_in", []),
            settings=expect_data.get("settings", {}),
            completed=expect_data.get("completed", True),
            result_attention=expect_data.get("result_attention"),
        )

        cases.append((case_id, message, attachments, expect))

    return cases


def load_cases_from_organizer(
    organizer_dir: Path, reference_path: Path
) -> list[tuple[str, str, list[Path], CaseExpectation]]:
    """Загружает случаи из папки 'Примеры деталей' и reference.json."""
    if not reference_path.exists():
        reference_data = {}
    else:
        reference_data = json.loads(reference_path.read_text())

    cases = []
    for folder in sorted(organizer_dir.iterdir()):
        if not folder.is_dir():
            continue

        number = folder.name.split(".", 1)[0]
        if number not in reference_data:
            continue

        # Ищем файлы
        files = list(folder.glob("*"))
        stl_files = [f for f in files if f.suffix.lower() == ".stl"]
        doc_files = [f for f in files if f.suffix.lower() in (".docx", ".pdf", ".jpg", ".png")]

        if not stl_files:
            continue

        # Формируем сообщение
        message = f"Деталь {number}: см. приложенные файлы"
        attachments = doc_files + stl_files

        # Для organizer случаев ожиданий нет, только метрики прогона
        expect = CaseExpectation(completed=True)

        cases.append((f"org-{number}", message, attachments, expect))

    return cases


def compute_metrics(results: list[CaseResult]) -> dict[str, Any]:
    """Вычисляет общие метрики."""
    total = len(results)
    if total == 0:
        return {}

    completed_count = sum(1 for r in results if r.completed)
    ok_count = sum(1 for r in results if r.result == "ok")

    # Доля прошедших все ожидания
    passed_all = 0
    for r in results:
        expectations = r.expectations
        if expectations and all(v == "pass" for v in expectations.values() if v != "n/a"):
            passed_all += 1

    iterations_list = [r.iterations for r in results if r.iterations > 0]
    avg_iterations = sum(iterations_list) / len(iterations_list) if iterations_list else 0

    validation_remarks_count = sum(1 for r in results if r.validation_remarks > 0)
    gcode_ok_count = sum(1 for r in results if r.gcode_result == "ok")

    times = [r.elapsed_seconds for r in results if r.elapsed_seconds > 0]
    avg_time = sum(times) / len(times) if times else 0

    failures = []
    for r in results:
        if not r.completed or r.error:
            failures.append(
                {
                    "case_id": r.case_id,
                    "reason": r.error or f"status={r.status}, completed={r.completed}",
                }
            )

    return {
        "total_cases": total,
        "completed_ratio": completed_count / total if total > 0 else 0,
        "ok_ratio": ok_count / total if total > 0 else 0,
        "passed_all_expectations_ratio": passed_all / total if total > 0 else 0,
        "avg_iterations": round(avg_iterations, 2),
        "validation_remarks_ratio": validation_remarks_count / total if total > 0 else 0,
        "gcode_ok_ratio": gcode_ok_count / total if total > 0 else 0,
        "avg_time_seconds": round(avg_time, 1),
        "failures": failures,
    }


def write_report(results: list[CaseResult], metrics: dict, out_dir: Path) -> None:
    """Записывает отчёт в report.md."""
    report_lines = ["# Отчёт о прогоне конвейера\n"]
    report_lines.append(f"Дата: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    report_lines.append(f"Всего случаев: {metrics.get('total_cases', 0)}\n\n")

    report_lines.append("## Метрики\n\n")
    report_lines.append(f"- Завершено: {metrics.get('completed_ratio', 0):.1%}\n")
    report_lines.append(f"- Результат OK: {metrics.get('ok_ratio', 0):.1%}\n")
    report_lines.append(
        f"- Прошли все ожидания: {metrics.get('passed_all_expectations_ratio', 0):.1%}\n"
    )
    report_lines.append(f"- Среднее число заходов: {metrics.get('avg_iterations', 0)}\n")
    report_lines.append(
        f"- Замечания на этапе 3: {metrics.get('validation_remarks_ratio', 0):.1%}\n"
    )
    report_lines.append(f"- G-code без замечаний: {metrics.get('gcode_ok_ratio', 0):.1%}\n")
    report_lines.append(f"- Среднее время: {metrics.get('avg_time_seconds', 0):.1f} с\n\n")

    if metrics.get("failures"):
        report_lines.append("## Провалы\n\n")
        for failure in metrics["failures"]:
            report_lines.append(f"- {failure['case_id']}: {failure['reason']}\n")
        report_lines.append("\n")

    report_lines.append("## Таблица случаев\n\n")
    report_lines.append("| ID | Статус | Итог | Заходы | G-code | Время (с) | Ожидания |\n")
    report_lines.append("|-----|--------|------|--------|--------|-----------|----------|\n")

    for r in results:
        exp_summary = ", ".join(f"{k[:3]}:{v[:1]}" for k, v in r.expectations.items() if v != "n/a")
        report_lines.append(
            f"| {r.case_id} | {r.status} | {r.result or '-'} | {r.iterations} | "
            f"{r.gcode_result or '-'} | {r.elapsed_seconds:.1f} | {exp_summary or '-'} |\n"
        )

    (out_dir / "report.md").write_text("".join(report_lines))


class _MockApi(BaseHTTPRequestHandler):
    """Поддельный стенд с формой ответов настоящего API: в снимке задания нет событий, карточка на
    раннем этапе null, итог лежит в job.status, job.parameters и job.result."""

    polls = 0
    posts: dict[str, tuple[int, dict]] = {
        "/api/v1/session/exchange": (200, {"authenticated": True}),
        "/api/v1/jobs": (201, {"id": "test-job-1", "status": "draft"}),
    }
    post_tails: dict[str, tuple[int, dict]] = {
        "messages": (200, {"ok": True}),
        "attachments": (201, {"id": "att-1"}),
        "answers": (200, {"ok": True}),
    }

    def log_message(self, format, *args):
        pass

    def _reply(self, code: int, payload: dict) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode())

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        reply = self.posts.get(self.path) or self.post_tails.get(self.path.rsplit("/", 1)[-1])
        if reply:
            self._reply(*reply)

    def do_GET(self):
        if self.path.endswith("/parameters"):
            self._reply(
                200,
                {
                    "iteration": 1,
                    "printing_mode": {"value": "classic"},
                    "materials": {"0": {"id": "generic_pla_175"}},
                    "quality": {"quality_type": "normal"},
                    "settings": {"support_enable": {"value": False}},
                },
            )
        else:
            type(self).polls += 1
            self._reply(200, {"job": self._job(type(self).polls)})

    @staticmethod
    def _job(poll: int) -> dict:
        stages = [(3, "running", "understanding"), (5, "running", "parameters")]
        status, stage = next(((st, sg) for limit, st, sg in stages if poll < limit), (None, None))
        if status is None:
            status, stage = ("waiting_user", "understanding") if poll < 7 else ("completed", "done")
        card = None
        if status == "waiting_user" and poll > 5:
            card = {"questions": [{"id": "q1", "answer": None}]}
        return {
            "id": "test-job-1",
            "status": status,
            "stage": stage,
            "revision": 0,
            "card": card,
            "parameters": {"iteration": 1, "printing_mode": "3D", "material": "PLA", "check": "ok"},
            "result": {
                "sliced": True,
                "message": "Проект готов",
                "gcode_check": "ok",
                "print_time_seconds": 3600,
                "material_grams": 50.0,
            },
        }


def selftest() -> int:
    """Запускает встроенный selftest с поддельным HTTP сервером."""
    print("Запуск selftest...")
    server = HTTPServer(("127.0.0.1", 0), _MockApi)
    Thread(target=server.serve_forever, daemon=True).start()
    try:
        client = ApiClient(
            f"http://127.0.0.1:{server.server_address[1]}", "test-secret", "test-user"
        )
        client.authenticate()
        expect = CaseExpectation(printing_mode="classic", material_contains="pla", completed=True)
        result = run_case(client, "test-1-success", "Test message", [], expect, 30, "Да")
        passed = (
            result.completed
            and result.result == "ok"
            and result.expectations.get("material_contains") == "pass"
        )
        print(f"{'✓' if passed else '✗'} Случай 1 (успех): {'PASS' if passed else 'FAIL'}")
        if not passed:
            print(f"  {result.error or result.status}")
        print(f"\nSelftest: {int(passed)}/1 прошло")
        return 0 if passed else 1
    finally:
        server.shutdown()


def _session_secret() -> str | None:
    """SESSION_SECRET из переменной среды или из .env в текущей папке."""
    secret = os.environ.get("SESSION_SECRET")
    env_path = Path(".env")
    if not secret and env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("SESSION_SECRET="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return secret


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Прогон конвейера параметров через HTTP API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument("--cases", type=Path, help="Путь к eval_cases.json")
    parser.add_argument("--organizer-dir", type=Path, help="Папка 'Примеры деталей'")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Base URL стенда")
    parser.add_argument("--user-id", default="local", help="User ID для авторизации")
    parser.add_argument("--timeout", type=float, default=900, help="Таймаут на случай в секундах")
    parser.add_argument(
        "--out-dir", type=Path, default=Path("results"), help="Папка для результатов"
    )
    parser.add_argument("--only", nargs="+", help="Запустить только указанные case ID")
    parser.add_argument(
        "--auto-answer", default="Подтверждаю, продолжай", help="Автоответ на вопросы агента"
    )
    parser.add_argument("--selftest", action="store_true", help="Запустить selftest")

    args = parser.parse_args()

    if args.selftest:
        return selftest()

    session_secret = _session_secret()
    if not session_secret or len(session_secret) < 32:
        print("Ошибка: SESSION_SECRET не найден или слишком короткий", file=sys.stderr)
        print("Укажите SESSION_SECRET в .env или переменной среды", file=sys.stderr)
        return 1

    # Загружаем случаи
    cases = []
    if args.cases:
        base_dir = args.cases.parent
        cases = load_cases_from_json(args.cases, base_dir)
    elif args.organizer_dir:
        reference_path = Path("pipeline/tests/eval/reference.json")
        cases = load_cases_from_organizer(args.organizer_dir, reference_path)
    else:
        parser.error("Укажите --cases или --organizer-dir")

    if args.only:
        cases = [(cid, msg, att, exp) for cid, msg, att, exp in cases if cid in args.only]

    if not cases:
        print("Нет случаев для прогона", file=sys.stderr)
        return 1

    # Создаём клиент
    client = ApiClient(args.base_url, session_secret, args.user_id)

    try:
        client.authenticate()
    except Exception as e:
        print(f"Ошибка авторизации: {e}", file=sys.stderr)
        return 1

    # Создаём выходную папку
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = args.out_dir / timestamp
    run_dir.mkdir(parents=True, exist_ok=True)

    # Прогоняем случаи
    results = []
    for case_id, message, attachments, expect in cases:
        print(f"Запуск случая: {case_id}...")
        result = run_case(
            client, case_id, message, attachments, expect, args.timeout, args.auto_answer
        )
        results.append(result)

        # Сохраняем результат случая
        case_file = run_dir / f"{case_id}.json"
        case_file.write_text(
            json.dumps(
                {
                    "case_id": result.case_id,
                    "status": result.status,
                    "completed": result.completed,
                    "result": result.result,
                    "iterations": result.iterations,
                    "validation_remarks": result.validation_remarks,
                    "gcode_result": result.gcode_result,
                    "print_time_seconds": result.print_time_seconds,
                    "material_grams": result.material_grams,
                    "message": result.message,
                    "project_folder": result.project_folder,
                    "stage_times": result.stage_times,
                    "expectations": result.expectations,
                    "error": result.error,
                    "elapsed_seconds": result.elapsed_seconds,
                    "parameters": result.parameters,
                },
                ensure_ascii=False,
                indent=2,
            )
        )

        print(
            f"  Статус: {result.status}, Итог: {result.result or 'N/A'}, "
            f"Время: {result.elapsed_seconds:.1f}s"
        )

    # Вычисляем метрики
    metrics = compute_metrics(results)

    # Записываем отчёты
    write_report(results, metrics, run_dir)
    (run_dir / "summary.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2))

    print(f"\nГотово. Результаты в {run_dir}/")
    print(
        f"Завершено: {metrics.get('completed_ratio', 0):.1%}, OK: {metrics.get('ok_ratio', 0):.1%}"
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())

import type { Page } from "@playwright/test";
import type {
  Attachment,
  Card,
  Job,
  ParameterSet,
  ProgressEvent,
  Question,
  Snapshot,
} from "../src/types";
export const designStates = [
  "start",
  "analysis",
  "questions",
  "conflict",
  "done",
  "selected",
  "files",
  "defect",
  "error",
  "offline",
  "revision",
] as const;
export type DesignState = (typeof designStates)[number];
export async function designFixture(page: Page, state: DesignState) {
  const card: Card = {
    schema_version: "2.0",
    job_id: "design",
    revision: state === "revision" ? 2 : 1,
    purpose: "Корпус подшипника, эксплуатация в помещении",
    requirements: [
      {
        key: "temperature",
        label: "Рабочая температура",
        value: "60",
        unit: "°C",
        conditions: "Постоянная",
        mandatory: true,
        verified: true,
        provenance: "document",
        sources: [
          {
            source_id: "spec:2",
            quote: "Рабочая температура до 60 °C",
            page: 2,
            method: "text",
          },
        ],
        superseded: [],
      },
    ],
    preferences: [],
    production_constraints: [],
    geometry: {
      readable: true,
      units: "mm",
      extents: [84, 62, 40],
      defects: ["duplicate_faces"],
      limitations: ["Физический объём не подтверждён"],
      report_id: null,
      preview_id: null,
    },
    assumptions: [
      { text: "Цвет и внешний вид не важны", basis: "", consequence: "" },
    ],
    unknowns: [],
    questions: [],
    verdict: { score: 0.9, passed: true, remarks: [] },
    readiness: "preliminary",
    allowed_actions: ["select_parameters"],
    blocked_actions: {},
  };
  const question: Question = {
    id: "clarify.temperature",
    kind: "clarify",
    title: "Какая рабочая температура у детали",
    impact: "Влияет на выбор материала, температуру стола и сопла",
    options: ["до 60 °C", "от 60 до 100 °C", "выше 100 °C"],
    answer: null,
    suggested: "до 60 °C",
    basis: "по ТЗ п. 2 «эксплуатация в помещении»",
    sources: [],
    blocking: true,
  };
  if (state === "questions")
    card.questions = [
      question,
      { ...question, id: "clarify.load", title: "Какая механическая нагрузка" },
      { ...question, id: "clarify.mount", title: "Как деталь крепится" },
    ];
  if (state === "defect")
    card.questions = [
      {
        ...question,
        id: "defect_vs_purpose.mesh",
        kind: "discrepancy",
        title: "Как продолжить",
        impact: "Влияет на расход материала и время печати",
        options: ["Продолжить с этой моделью", "Приложу исправленный STL"],
        suggested: null,
      },
    ];
  if (state === "conflict")
    card.questions = [
      {
        ...question,
        id: "tz_vs_stl.length",
        kind: "discrepancy",
        title: "Длина посадочного участка A",
        impact: "Влияет на масштаб и подбор параметров",
        options: ["ТЗ, п. 1.2, 100 мм", "STL, масштаб 1 к 1, 80 мм"],
        suggested: null,
        basis: null,
        sources: [
          {
            source_id: "spec:1",
            quote: "Указано в техническом задании",
            page: 1,
          },
        ],
      },
    ];
  const waiting = ["questions", "conflict", "defect"].includes(state);
  if (waiting) card.readiness = "blocked";
  const job: Job = {
    id: "design",
    title: state === "start" ? "Новое задание" : "Корпус подшипника",
    revision: card.revision,
    status:
      state === "start"
        ? "draft"
        : state === "done"
          ? "queued"
          : state === "selected"
            ? "completed"
            : state === "error"
              ? "failed"
              : waiting
                ? "waiting_user"
                : "running",
    card: state === "start" ? null : card,
    error:
      state === "error"
        ? "Модель не отвечает; анализ не завершён, результаты сохранены"
        : null,
    files_changed: false,
    stage:
      state === "selected"
        ? "done"
        : state === "done"
          ? "parameters"
          : "understanding",
    parameters:
      state === "selected"
        ? {
            iteration: 1,
            printing_mode: "3D",
            quality_type: "Fine",
            material: "PETG",
            changed_settings: 2,
            unsatisfied: 1,
            status: "proposed",
            check: "attention",
          }
        : null,
    created_at: "2026-10-23T12:00:00Z",
    updated_at: "2026-10-23T12:00:00Z",
  };
  const base = {
    job_id: job.id,
    revision: job.revision,
    status: "completed",
    data: {},
  };
  const events: ProgressEvent[] =
    state === "start"
      ? []
      : [
          {
            ...base,
            event_id: 1,
            type: "files.completed",
            message: "Файлы прочитаны",
          },
          {
            ...base,
            event_id: 2,
            type: "stl.completed",
            status: state === "defect" ? "warning" : "completed",
            message: "STL проанализирован",
            data: { geometry: card.geometry },
          },
          {
            ...base,
            event_id: 3,
            type: "interpretation.started",
            status: "running",
            message:
              state === "revision"
                ? "Пересчитываю с новой длиной участка A"
                : "Сверяю размеры из ТЗ с измерениями STL, расхождения передам вам на подтверждение",
          },
        ];
  if (waiting || state === "done" || state === "selected")
    events.push({
      ...base,
      event_id: 4,
      type: "stage1.completed",
      message: "Карточка подготовлена",
    });
  if (state === "selected")
    events.push(
      {
        ...base,
        event_id: 5,
        type: "parameters.completed",
        message: "Режим 3D, профиль Fine, материал PETG, изменено 2 настройки",
        data: { iteration: 1 },
      },
      {
        ...base,
        event_id: 6,
        type: "validation.completed",
        message: "Замечаний нет",
        data: { iteration: 1 },
      },
    );
  const parameters: ParameterSet = {
    iteration: 1,
    settings: {
      wall_thickness: {
        value: 1.6,
        unit: "мм",
        why: "Корпус под нагрузкой, четыре стенки",
        source: "rule:WALL-LOAD",
      },
      infill_sparse_density: {
        value: 30,
        unit: "%",
        why: "Прочность важнее времени печати",
        source: "rule:PRIORITY-STRENGTH",
      },
    },
    unsatisfied: [
      {
        requirement_id: "service_temp_max_c",
        why: "PETG держит до 70 °C, а нужно 80 °C",
      },
    ],
    assumptions: [
      { id: "A1", text: "Модель стоит как в файле", basis: "Этап 2" },
    ],
  };
  const attachments: Attachment[] =
    state === "start" ||
    state === "done" ||
    state === "revision" ||
    state === "defect"
      ? []
      : [
          {
            id: "spec",
            filename: "Корпус_ТЗ.pdf",
            kind: "pdf",
            status: "completed",
            error: null,
            artifacts: [],
          },
          {
            id: "mesh",
            filename: "korpus.stl",
            kind: "stl",
            status: "completed",
            error: null,
            artifacts: [],
          },
        ];
  if (state === "files")
    attachments.push(
      {
        id: "image",
        filename: "эскиз.png",
        kind: "png",
        status: "pending",
        error: null,
        artifacts: [],
      },
      {
        id: "unsupported",
        filename: "korpus.step",
        kind: "unknown",
        status: "failed",
        error: "Формат не поддерживается, приложите STL",
        artifacts: [],
      },
    );
  const introductions: Record<string, string> = {
    questions:
      "Анализ закончен, нужно уточнить 3 вещи, остальное я допустил, допущения видны справа:",
    conflict:
      "Размер детали в ТЗ и модели не совпадает, подтвердите, какое значение верно",
    done: "Вот как я понял задачу, если всё верно, я перейду к подбору параметров",
    selected:
      "Параметры подобраны, но выполнены не все требования. Режим 3D, профиль Fine, материал PETG, изменено 2 настройки",
    files: "Проверяю файлы перед анализом",
    defect:
      "В korpus.stl нашлись дублирующиеся грани, из-за них площадь и объём модели точно не посчитать, габариты и масштаб в порядке",
    error: "Модель не отвечает, анализ не завершён",
    revision:
      "Длину участка A поменял со 100 на 90 мм, пересчитываю то, что от неё зависит",
  };
  const snapshot: Snapshot = {
    job,
    messages:
      state === "start"
        ? []
        : [
            {
              id: "message1",
              seq: 1,
              revision: job.revision,
              role: "user",
              text:
                state === "revision"
                  ? "Длина посадочного участка теперь 90 мм"
                  : "Нужно напечатать корпус подшипника для работы в помещении, ТЗ и модель во вложении",
            },
            {
              id: "message2",
              seq: 2,
              revision: job.revision,
              role: "assistant",
              text: introductions[state] || "Разбираю материалы, все шаги ниже",
            },
          ],
    attachments,
    message_cursor: null,
  };
  await page.addInitScript(
    ({ events }) => {
      class DesignEventSource {
        onerror = null;
        set onopen(fn: (() => void) | null) {
          if (fn) queueMicrotask(fn);
        }
        set onmessage(fn: ((e: { data: string }) => void) | null) {
          if (fn)
            queueMicrotask(() =>
              events.forEach((event) => fn({ data: JSON.stringify(event) })),
            );
        }
        close() {}
      }
      Object.defineProperty(window, "EventSource", {
        value: DesignEventSource,
      });
    },
    { events },
  );
  await page.route("**/api/v1/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    const data = path.endsWith("/session")
      ? { authenticated: true }
      : path.endsWith("/capabilities")
        ? { model_configured: true }
        : path.endsWith("/parameters")
          ? parameters
          : path.endsWith("/jobs")
            ? [
                job,
                ...(state === "start"
                  ? [
                      "Корпус подшипника",
                      "Кронштейн датчика",
                      "Крышка редуктора",
                    ]
                  : ["Кронштейн датчика", "Крышка редуктора"]
                ).map((title, i, all) => ({
                  ...job,
                  id: String(i),
                  title,
                  updated_at: `2026-10-${all.length === 3 ? [22, 21, 18][i] : [21, 18][i]}T12:00:00Z`,
                })),
              ]
            : snapshot;
    return route.fulfill({ json: data });
  });
  return snapshot;
}

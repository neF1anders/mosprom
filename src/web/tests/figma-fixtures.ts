import type { Page } from "@playwright/test";
import type { Card, Job, ProgressEvent, Snapshot } from "../src/types";
export const designStates = [
  "start",
  "analysis",
  "questions",
  "conflict",
  "done",
  "files",
  "defect",
  "error",
  "offline",
  "revision",
] as const;
export type DesignState = (typeof designStates)[number];
export async function designFixture(page: Page, state: DesignState) {
  const card: Card = {
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
          { source_id: "spec", quote: "Рабочая температура до 60 °C", page: 2 },
        ],
      },
    ],
    preferences: [],
    geometry: {
      readable: true,
      units: "mm",
      extents: [84, 62, 40],
      defects: ["duplicate_faces"],
      limitations: ["Физический объём не подтверждён"],
      report_id: null,
    },
    assumptions: ["Цвет и внешний вид не важны"],
    unknowns: [],
    questions: [],
    conflicts: [],
    readiness: "preliminary",
    allowed_actions: [
      "interpret_requirements",
      "assess_materials",
      "select_parameters",
    ],
    blocked_actions: {},
  };
  const question = {
    id: "temperature",
    title: "Какая рабочая температура у детали?",
    reason: "Влияет на выбор материала, температуру стола и сопла",
    options: ["до 60 °C", "от 60 до 100 °C", "выше 100 °C"],
    answer: null,
    suggested: "до 60 °C",
    basis: "по ТЗ п. 2 «эксплуатация в помещении»",
    affected_actions: ["select_parameters"],
  };
  if (state === "questions")
    card.questions = [
      question,
      { ...question, id: "load", title: "Какая механическая нагрузка?" },
      { ...question, id: "material", title: "Какой материал доступен?" },
    ];
  if (state === "defect")
    card.questions = [
      {
        ...question,
        id: "defect",
        title: "Как продолжить?",
        reason: "Влияет на расход материала и время печати",
        options: ["Продолжить с этой моделью", "Приложу исправленный STL"],
        suggested: null,
      },
    ];
  if (state === "conflict")
    card.conflicts = [
      {
        id: "length",
        title: "Длина посадочного участка A",
        options: ["ТЗ, п. 1.2, 100 мм", "STL, масштаб 1 к 1, 80 мм"],
        sources: [
          {
            source_id: "spec",
            quote: "Указано в техническом задании",
            page: 1,
          },
          {
            source_id: "mesh",
            quote: "Измерено по модели, участок A",
            page: null,
          },
        ],
        resolved: false,
        resolution: null,
        affected_actions: ["select_parameters"],
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
    handoff: state === "done" ? "not_connected" : "not_ready",
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
            type: "document.completed",
            message: "Прочитано ТЗ",
          },
          {
            ...base,
            event_id: 2,
            type: "geometry.completed",
            message: "Проанализирован STL",
            data: { geometry: card.geometry },
          },
          {
            ...base,
            event_id: 3,
            type: "requirements.started",
            status: "running",
            message:
              state === "revision"
                ? "Пересчитываю с новой длиной участка A"
                : "Сверяю размеры из ТЗ с измерениями STL, расхождения передам вам на подтверждение",
          },
        ];
  if (waiting || state === "done")
    events.push({
      ...base,
      event_id: 4,
      type: "stage1.completed",
      message: "Карточка подготовлена",
    });
  const attachments =
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
        : path.endsWith("/jobs")
          ? [
              job,
              ...(state === "start" ? ["Корпус подшипника", "Кронштейн датчика", "Крышка редуктора"] : ["Кронштейн датчика", "Крышка редуктора"]).map((title, i, all) => ({
                ...job,
                id: String(i),
                title,
                updated_at: `2026-10-${all.length === 3 ? [22,21,18][i] : [21,18][i]}T12:00:00Z`,
              })),
            ]
          : snapshot;
    return route.fulfill({ json: data });
  });
  return snapshot;
}

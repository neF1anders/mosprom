import { defectLabels, modelSize, plural } from "./format";
import type { Card, Evidence, Geometry, Job, ProgressEvent } from "./types";
import { answered, isRunning, UNKNOWN_ANSWER } from "./types";

export type SectionState = "done" | "error" | "warn" | "run" | "wait";
export interface SectionItem {
  text: string;
  meta?: string;
  tag?: string;
  href?: string;
  // страница значения
  page?: string;
}
export interface Section {
  key: string;
  title: string;
  state: SectionState;
  summary: string;
  items: SectionItem[];
}
// слово у раздела
export const stateWords: Record<SectionState, string> = {
  done: "",
  error: "Ошибка",
  warn: "Внимание",
  run: "В работе",
  wait: "Ждёт",
};
// порядок заполнения полосы
const ORDER: SectionState[] = ["done", "error", "warn", "run", "wait"];
export function barOrder(sections: Section[]) {
  return sections
    .map((section) => section.state)
    .sort((a, b) => ORDER.indexOf(a) - ORDER.indexOf(b));
}
const methodLabels: Record<string, string> = {
  vision: "прочитано по изображению",
  user: "из ваших сообщений",
  knowledge: "из базы материалов",
};
function sourceLabel(source?: Evidence) {
  if (!source) return undefined;
  if (source.method && methodLabels[source.method])
    return methodLabels[source.method];
  return source.page ? `по ТЗ, страница ${source.page}` : "по ТЗ";
}
function lowerFirst(text: string) {
  return text.charAt(0).toLowerCase() + text.slice(1);
}
// состояние раздела
function emptyState(job: Job | undefined): SectionState {
  if (isRunning(job)) return "run";
  return job?.status === "failed" ? "error" : "wait";
}
function empty(job: Job | undefined, title: string, key: string): Section {
  return {
    key,
    title,
    state: emptyState(job),
    summary: isRunning(job) ? "Определяется" : "Нет данных",
    items: [],
  };
}
function purpose(job: Job | undefined, card: Card | null): Section {
  const title = "Назначение";
  if (!card?.purpose) return empty(job, title, "purpose");
  return {
    key: "purpose",
    title,
    state: "done",
    summary: card.purpose,
    items: [],
  };
}
function requirements(job: Job | undefined, card: Card | null): Section {
  const title = "Обязательные требования";
  const list = card?.requirements.filter((r) => r.mandatory) || [];
  if (!card || !list.length) return empty(job, title, "requirements");
  const count = list.length;
  const open = card.questions.filter((q) => !answered(q)).length;
  const named = `${count} ${plural(count, ["требование", "требования", "требований"])}`;
  const items = list.map((r) => {
    const page = r.sources.find((source) => source.artifact_id);
    return {
      text: `${r.label || r.key} ${r.value} ${r.unit || ""}`.trim(),
      meta: sourceLabel(r.sources[0]),
      tag: r.verified ? undefined : "уточнить",
      page:
        page && job
          ? `/api/v1/jobs/${job.id}/artifacts/${encodeURIComponent(page.artifact_id!)}`
          : undefined,
    };
  });
  // повторная проверка
  const rechecking =
    isRunning(job) &&
    job?.stage === "understanding" &&
    card.revision < (job?.revision ?? 0);
  if (open)
    return {
      key: "requirements",
      title,
      state: "warn",
      summary: `${named} · ${open} ${plural(open, ["ждёт", "ждут", "ждут"])} ответа`,
      items,
    };
  if (rechecking)
    return {
      key: "requirements",
      title,
      state: "run",
      summary: `Найдено ${count}, проверяются`,
      items,
    };
  return {
    key: "requirements",
    title,
    state: "done",
    summary: `${named} ${plural(count, ["подтверждено", "подтверждены", "подтверждены"])}`,
    items,
  };
}
function geometry(
  job: Job | undefined,
  card: Card | null,
  measured: Geometry | undefined,
): Section {
  const title = "Геометрия";
  const size = modelSize(measured);
  if (!measured || !size) return empty(job, title, "geometry");
  const defects = measured.defects.map((d) => defectLabels[d] || d);
  const items: SectionItem[] = [
    ...defects.map((text) => ({ text, tag: "дефект" })),
    ...(measured.limitations || []).map((text) => ({ text })),
  ];
  if (measured.report_id && job)
    items.push({
      text: "Отчёт анализа STL",
      href: `/api/v1/jobs/${job.id}/artifacts/${measured.report_id}.json`,
    });
  if (!defects.length)
    return { key: "geometry", title, state: "done", summary: size, items };
  // дефект закрыт
  const settled = !!card && card.questions.every(answered);
  return {
    key: "geometry",
    title,
    state: settled ? "done" : "warn",
    summary: `${size} · ${settled ? "дефект учтён" : defects.join(", ")}`,
    items,
  };
}
function assumptions(job: Job | undefined, card: Card | null): Section {
  const title = "Допущения и неизвестные";
  if (!card) return empty(job, title, "assumptions");
  const items: SectionItem[] = [
    ...card.assumptions.map((a) => ({
      text: a.text,
      meta: a.basis || undefined,
      tag: "допущение",
    })),
    ...card.unknowns.map((text) => ({ text, tag: "неизвестно" })),
    ...card.questions
      .filter((q) => q.answer === UNKNOWN_ANSWER)
      .map((q) => ({ text: q.title, tag: "не удалось уточнить" })),
  ];
  const count = card.assumptions.length;
  const unknown = card.unknowns.length;
  const named = `${count} ${plural(count, ["допущение", "допущения", "допущений"])}`;
  // что мешает продолжить
  const blockers = [
    ...new Set(
      Object.entries(card.blocked_actions || {})
        .filter(([action]) => action !== "prepare_gcode")
        .flatMap(([, reasons]) => reasons),
    ),
  ];
  if (blockers.length)
    return {
      key: "assumptions",
      title,
      state: "warn",
      summary: blockers.join(", "),
      items: [
        ...blockers.map((text) => ({ text, tag: "мешает продолжить" })),
        ...items,
      ],
    };
  if (unknown)
    return {
      key: "assumptions",
      title,
      state: "warn",
      summary: `${unknown} ${plural(unknown, ["неизвестное", "неизвестных", "неизвестных"])}${count ? `, ${named}` : ""}`,
      items,
    };
  const few = card.assumptions
    .map((a, index) => (index ? lowerFirst(a.text) : a.text))
    .join(", ");
  return {
    key: "assumptions",
    title,
    state: "done",
    summary:
      count > 2
        ? `${named}, блокирующих неизвестных нет`
        : few || "Допущений нет",
    items,
  };
}
// четыре раздела карточки
export function cardSections(job: Job | undefined, events: ProgressEvent[]) {
  const card = job?.card ?? null;
  const measured =
    events.reduce<Geometry | undefined>(
      (previous, event) =>
        event.type === "stl.completed" && event.data.geometry
          ? (event.data.geometry as Geometry)
          : previous,
      undefined,
    ) ||
    card?.geometry ||
    undefined;
  return [
    purpose(job, card),
    requirements(job, card),
    geometry(job, card, measured),
    assumptions(job, card),
  ];
}

import { useState, type ReactNode } from "react";
import type { Job, ProgressEvent } from "../types";
import { CardSummary } from "./CardSummary";
import styles from "../App.module.css";

type State = "wait" | "run" | "done" | "warn";
const labels = [
  "Подбор параметров",
  "Валидация",
  "Слайсинг",
  "Подготовка результата",
];
function TimelineRow({
  title,
  state,
  small = false,
  children,
  expanded = false,
}: {
  title: string;
  state: State;
  small?: boolean;
  children?: ReactNode;
  expanded?: boolean;
}) {
  const [open, setOpen] = useState(expanded);
  const icon = small ? `${state}-small` : state === "warn" ? "error" : state;
  return (
    <details
      className={`${styles.timelineRow} ${small ? styles.substep : ""}`}
      data-state={state}
      open={open}
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>
        <img
          className={styles.marker}
          src={`/figma/${icon}.svg`}
          alt={
            {
              wait: "Ожидает",
              run: "Выполняется",
              done: "Завершено",
              warn: "Требует внимания",
            }[state]
          }
        />
        <span>{title}</span>
        <img
          className={styles.chevron}
          src={`/figma/chevron-${open ? "up" : "down"}.svg`}
          alt=""
        />
      </summary>
      <div className={styles.stepContent}>
        {children || "Операция ещё не запускалась"}
      </div>
    </details>
  );
}
function latest(events: ProgressEvent[], prefix: string) {
  for (let index = events.length - 1; index >= 0; index--) {
    if (events[index].type.startsWith(prefix)) return events[index];
  }
}
function stateFor(events: ProgressEvent[], prefix: string): State {
  const event = latest(events, prefix);
  if (!event) return "wait";
  if (event.status === "failed" || event.type.endsWith("failed")) return "warn";
  return event.type.endsWith("completed") ? "done" : "run";
}
export function Progress({
  events,
  job,
  compact = false,
}: {
  events: ProgressEvent[];
  job?: Job;
  compact?: boolean;
}) {
  const operations = events.filter(
    (e) => !["job.created", "job.changed"].includes(e.type),
  );
  if (!operations.length || compact) return null;
  const finished = events.some((e) => e.type === "stage1.completed");
  const geometry = latest(events, "geometry.completed")?.data.geometry as
    { defects?: string[] } | undefined;
  const state: State =
    job?.status === "failed" ? "warn" : finished ? "done" : "run";
  const steps: { title: string; state: State; prefix: string }[] = [
    {
      title: "Прочитано ТЗ",
      state: stateFor(events, "document."),
      prefix: "document.",
    },
    {
      title: "Проанализирован STL",
      state: geometry?.defects?.length ? "warn" : stateFor(events, "geometry."),
      prefix: "geometry.",
    },
    {
      title: "Сверка ТЗ и геометрии",
      state: finished ? "done" : stateFor(events, "requirements."),
      prefix: "requirements.",
    },
    {
      title: "Проверяю, хватает ли данных",
      state: finished
        ? job?.card?.readiness === "blocked"
          ? "warn"
          : "done"
        : "wait",
      prefix: "stage1.",
    },
    {
      title: "Собираю карточку задания",
      state: finished ? "done" : "wait",
      prefix: "stage1.",
    },
  ];
  return (
    <section aria-label="Ход работы">
      {!compact && (
        <div className={styles.timeline}>
          <TimelineRow title="Интерпретация задания" state={state} expanded>
            {finished && job?.card ? (
              <>
                <p className={styles.checkCount}>5 проверок</p>
                <CardSummary card={job.card} />
              </>
            ) : (
              <div className={styles.substeps}>
                {steps.map((step) => (
                  <TimelineRow
                    key={step.title}
                    title={step.title}
                    state={step.state}
                    small
                    expanded={step.state === "run"}
                  >
                    {latest(events, step.prefix)?.message}
                  </TimelineRow>
                ))}
              </div>
            )}
          </TimelineRow>
          {labels.map((title) => (
            <TimelineRow key={title} title={title} state="wait">
              Следующий этап не подключён
            </TimelineRow>
          ))}
        </div>
      )}
    </section>
  );
}

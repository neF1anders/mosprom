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
const steps = [
  { title: "Файлы прочитаны", prefix: "files." },
  { title: "STL проанализирован", prefix: "stl." },
  { title: "Главные вопросы", prefix: "triage." },
  { title: "ТЗ разобрано по аспектам", prefix: "interpretation." },
  { title: "Сводка в карточку", prefix: "consolidation." },
  { title: "Поиск несоответствий", prefix: "discrepancies." },
  { title: "Итоговая оценка", prefix: "judge." },
];
function latest(events: ProgressEvent[], prefix: string) {
  for (let index = events.length - 1; index >= 0; index--) {
    if (events[index].type.startsWith(prefix)) return events[index];
  }
}
function stateFor(events: ProgressEvent[], prefix: string): State {
  const event = latest(events, prefix);
  if (!event) return "wait";
  if (["failed", "warning"].includes(event.status)) return "warn";
  return event.status === "completed" ? "done" : "run";
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
  const operations = events.filter((e) =>
    steps.some((step) => e.type.startsWith(step.prefix)),
  );
  if (!operations.length || compact) return null;
  const finished = events.some((e) => e.type === "stage1.completed");
  const state: State =
    job?.status === "failed" ? "warn" : finished ? "done" : "run";
  return (
    <section aria-label="Ход работы">
      <div className={styles.timeline}>
        <TimelineRow title="Интерпретация задания" state={state} expanded>
          {finished && job?.card ? (
            <CardSummary card={job.card} />
          ) : (
            <div className={styles.substeps}>
              {steps.map((step) => {
                const current = stateFor(events, step.prefix);
                return (
                  <TimelineRow
                    key={step.title}
                    title={step.title}
                    state={current}
                    small
                    expanded={current === "run"}
                  >
                    {latest(events, step.prefix)?.message}
                  </TimelineRow>
                );
              })}
            </div>
          )}
        </TimelineRow>
        {labels.map((title, index) => (
          <TimelineRow key={title} title={title} state="wait">
            {index === 0 && job?.next_stage === "queued"
              ? "Задание передано, ждёт подбора параметров"
              : "Этап ещё не начат"}
          </TimelineRow>
        ))}
      </div>
    </section>
  );
}

import { useState, type ReactNode } from "react";
import type { Job, ProgressEvent } from "../types";
import { isRunning } from "../types";
import { CardSummary } from "./CardSummary";
import { ParameterSummary } from "./ParameterSummary";
import { ResultSummary } from "./ResultSummary";
import styles from "../App.module.css";

type State = "wait" | "run" | "done" | "warn";
const icons: Record<State, string> = {
  wait: "wait",
  run: "run",
  done: "done",
  warn: "error",
};
// Stages after the interpretation; each one follows the events of its prefix.
const stages = [
  { title: "Подбор параметров", prefix: "parameters.", pass: "Заход" },
  { title: "Валидация", prefix: "validation.", pass: "Проверка" },
  { title: "Слайсинг", prefix: "slicing.", pass: "Нарезка" },
  { title: "Подготовка результата", prefix: "gcode.", pass: "Проверка G-code" },
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
  const icon = small ? `${state}-small` : icons[state];
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
// A stopped or failed run ends its open steps; without a job the events alone decide.
function halted(job?: Job): State | undefined {
  if (!job || isRunning(job)) return undefined;
  return job.status === "failed" ? "warn" : "wait";
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
    [...steps, ...stages].some((step) => e.type.startsWith(step.prefix)),
  );
  if (!operations.length || compact) return null;
  const finished = events.some((e) => e.type === "stage1.completed");
  const ended = halted(job);
  const state: State = finished ? "done" : ended || "run";
  return (
    <section aria-label="Ход работы">
      <div className={styles.timeline}>
        <TimelineRow title="Интерпретация задания" state={state} expanded>
          {finished && job?.card ? (
            <CardSummary card={job.card} />
          ) : (
            <div className={styles.substeps}>
              {steps.map((step) => {
                const found = stateFor(events, step.prefix);
                const current = found === "run" && ended ? ended : found;
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
        {stages.map((stage) => (
          <StageRow
            key={stage.title}
            {...stage}
            events={events}
            job={job}
            ended={ended}
          />
        ))}
      </div>
    </section>
  );
}

// A stage after the interpretation: one substep per pass, its result once the job is done.
function StageRow({
  title,
  prefix,
  pass,
  events,
  job,
  ended,
}: {
  title: string;
  prefix: string;
  pass: string;
  events: ProgressEvent[];
  job?: Job;
  ended?: State;
}) {
  const passes = events.filter((e) => e.type.startsWith(prefix));
  const found = stateFor(passes, prefix);
  const state = found === "run" && ended ? ended : found;
  if (!passes.length)
    return (
      <TimelineRow title={title} state="wait">
        {waitingText(prefix, job)}
      </TimelineRow>
    );
  // The first stage shows what was selected, the last one the project once it was made.
  const done = job?.stage === "done";
  const finished =
    done &&
    ((prefix === "parameters." && !!job?.parameters) ||
      (prefix === "gcode." && !!job?.result?.sliced));
  const summary = done && prefix === "parameters." ? job?.parameters : null;
  const unmet = !!summary?.unsatisfied || summary?.status === "infeasible";
  return (
    <TimelineRow
      // The result mounts anew so it opens even if the row had been folded as done.
      key={finished ? "result" : "progress"}
      title={title}
      state={unmet && state === "done" ? "warn" : state}
      expanded={state !== "done" || finished}
    >
      {finished && job ? (
        <StageSummary prefix={prefix} job={job} />
      ) : (
        <div className={styles.substeps}>
          {iterations(passes).map((iteration) => {
            const own = passes.filter((e) => e.data.iteration === iteration);
            const step = stateFor(own, prefix);
            return (
              <TimelineRow
                key={iteration}
                title={`${pass} ${iteration}`}
                state={step === "run" && ended ? ended : step}
                small
              >
                {latest(own, prefix + "completed")?.message}
              </TimelineRow>
            );
          })}
        </div>
      )}
    </TimelineRow>
  );
}
function StageSummary({ prefix, job }: { prefix: string; job: Job }) {
  if (prefix === "parameters.") return <ParameterSummary job={job} />;
  return <ResultSummary job={job} />;
}
function iterations(events: ProgressEvent[]) {
  return [...new Set(events.map((e) => Number(e.data.iteration)))];
}
function waitingText(prefix: string, job?: Job) {
  if (prefix === "parameters." && job?.stage === "parameters")
    return "Задание передано, ждёт подбора параметров";
  if (job?.stage !== "done") return "Этап ещё не начат";
  // Without a project there is no G-code to check.
  if (prefix === "gcode." && job.result && !job.result.sliced)
    return "Не проводилась, проект не создан";
  // An infeasible selection is not checked: nothing in it can be printed as it is.
  return "Не проводилась, параметры подобрать не удалось";
}

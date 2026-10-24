import type { ReactNode } from "react";
import { Audit } from "./Audit";
import { modelSize } from "../format";
import type { Card, Evidence, Geometry, Job, ProgressEvent } from "../types";
import { answered, isRunning, jobStatus, UNKNOWN_ANSWER } from "../types";
import styles from "../App.module.css";

const methodLabels: Record<string, string> = {
  vision: " · прочитано по изображению и подтверждено вторым чтением",
  user: " · из ваших сообщений",
  knowledge: " · из базы материалов",
};
function SourceQuote({ source, jobId }: { source: Evidence; jobId?: string }) {
  return (
    <blockquote>
      {source.quote}
      <small>
        {source.page ? `страница ${source.page}` : ""}
        {methodLabels[source.method || ""] || ""}
      </small>
      {source.artifact_id && (
        <a
          href={`/api/v1/jobs/${jobId}/artifacts/${encodeURIComponent(source.artifact_id)}`}
          target="_blank"
          rel="noreferrer"
        >
          Посмотреть страницу
        </a>
      )}
    </blockquote>
  );
}
const defectLabels: Record<string, string> = {
  boundary_edges: "Открытая поверхность",
  duplicate_faces: "Повторяющиеся грани",
  multiple_shells: "Несколько оболочек",
  nonmanifold_edges: "Немногообразные рёбра",
  inconsistent_winding: "Несогласованные нормали",
  topology_unchecked: "Топология не проверена",
};
// A section is empty without data, otherwise done unless something needs a look.
function presence(present: boolean, attention: boolean) {
  if (!present) return "empty";
  return attention ? "warn" : "done";
}
function readiness(card: Card | null | undefined, running: boolean) {
  if (running) return "warn";
  if (!card) return "empty";
  return card.readiness === "blocked" ? "error" : "done";
}
function Field({
  title,
  state = "empty",
  children,
}: {
  title: string;
  state?: string;
  children: ReactNode;
}) {
  return (
    <section>
      <h3>
        {title}
        <img
          alt=""
          src={`/figma/dot${state === "empty" ? "" : `-${state}`}.svg`}
          aria-hidden="true"
          className={styles.statusDot}
          data-state={state}
        />
      </h3>
      {children}
    </section>
  );
}
// Stages after the card: the chat says it was handed over until the pipeline ends.
const handedOver = new Set(["parameters", "validation", "slicing", "gcode"]);

export function TaskCard({
  job,
  onCollapse,
  events = [],
  collapsed = false,
}: {
  job?: Job;
  onCollapse: () => void;
  events?: ProgressEvent[];
  collapsed?: boolean;
}) {
  const card = job?.card;
  const geometry =
    events.reduce<Geometry | undefined>(
      (previous, event) =>
        event.type === "stl.completed"
          ? (event.data.geometry as Geometry)
          : previous,
      undefined,
    ) ||
    card?.geometry ||
    undefined;
  const running = isRunning(job);
  const requirements =
    card?.requirements.filter((requirement) => requirement.mandatory) || [];
  const size = modelSize(geometry);
  const unresolved = card?.questions.filter((q) => !answered(q)).length || 0;
  const defects = geometry?.defects.map((d) => defectLabels[d] || d) || [];
  const remarks =
    card?.verdict?.remarks.filter((r) => r.severity !== "minor") || [];
  const unknowns = card
    ? [
        ...card.assumptions.map((a) =>
          a.basis ? `${a.text}, основание ${a.basis}` : a.text,
        ),
        ...card.unknowns,
        ...remarks.map((r) => r.text),
      ]
    : [];
  const blockers = [
    ...new Set(
      Object.entries(card?.blocked_actions || {})
        .filter(([action]) => action !== "prepare_gcode")
        .flatMap(([, reasons]) => reasons),
    ),
  ];
  return (
    <aside
      className={styles.card}
      aria-label="Карточка задания"
      data-empty={!card}
      inert={collapsed}
    >
      <div className={styles.row}>
        <h2>Карточка задания</h2>
        <button
          className={styles.icon}
          aria-label="Свернуть карточку"
          onClick={onCollapse}
        >
          <img src="/figma/collapse-right.svg" alt="" />
        </button>
      </div>
      {card && card.revision !== job?.revision && (
        <p role="status">Обновляю карточку после ваших изменений</p>
      )}
      <Field title="Назначение" state={card?.purpose ? "done" : "empty"}>
        <p>{card?.purpose || "Нет данных"}</p>
      </Field>
      <Field
        title="Обязательные требования"
        state={presence(requirements.length > 0, unresolved > 0 || running)}
      >
        {requirements.length ? (
          <details className={styles.cardDisclosure}>
            <summary aria-label="Показать требования">
              {requirements.length} требований
              {unresolved ? ` · ${unresolved} ждут ответа` : " · проверены"}
            </summary>
            {requirements.map((r, i) => (
              <details key={i}>
                <summary>
                  {r.label || r.key} · {r.value} {r.unit}{" "}
                  {!r.verified && "· Нужно уточнить"}
                </summary>
                <p>{r.conditions || "Условия не указаны"}</p>
                {r.sources.map((source, j) => (
                  <SourceQuote key={j} source={source} jobId={job?.id} />
                ))}
                {r.superseded.map((old, j) => (
                  <p key={`old-${j}`} className={styles.muted}>
                    Было {old.value} {old.unit || ""},{" "}
                    {old.reason.toLowerCase()}
                  </p>
                ))}
              </details>
            ))}
          </details>
        ) : (
          <p>Нет данных</p>
        )}
      </Field>
      <Field title="Геометрия" state={presence(!!size, defects.length > 0)}>
        <p>
          {size || "Нет данных"}
          {defects.length ? ` · ${defects.join(", ")}` : ""}
        </p>
        {geometry?.report_id && (
          <details className={styles.geometryDetails}>
            <summary>Подробнее о геометрии</summary>
            {geometry.preview_id && (
              <img
                className={styles.preview}
                src={`/api/v1/jobs/${job?.id}/artifacts/${geometry.preview_id}`}
                alt="Три проекции STL"
              />
            )}
            {geometry.limitations?.map((text, i) => (
              <p key={i}>{text}</p>
            ))}
            <a
              href={`/api/v1/jobs/${job?.id}/artifacts/${geometry.report_id}.json`}
              download
            >
              Отчёт анализа STL
            </a>
          </details>
        )}
      </Field>
      <Field
        title="Допущения и неизвестные"
        state={presence(!!card, unknowns.length > 0)}
      >
        {unknowns.length ? (
          <details className={styles.cardDisclosure}>
            <summary>
              Допущений {card?.assumptions.length} · неизвестных{" "}
              {card?.unknowns.length}
            </summary>
            {unknowns.map((text, i) => (
              <p key={i}>{text}</p>
            ))}
          </details>
        ) : (
          <p>{card ? "Нет допущений и неизвестных" : "Нет данных"}</p>
        )}
        {card?.questions
          .filter((q) => q.answer === UNKNOWN_ANSWER)
          .map((q) => (
            <p key={q.id}>Не удалось уточнить · {q.title}</p>
          ))}
      </Field>
      <Field title="Готовность" state={readiness(card, running)}>
        {events.length ? (
          <details className={styles.cardDisclosure}>
            <summary
              aria-label="Показать журнал вызовов"
              title="Раскрыть журнал проверок"
            >
              <span role="status">{jobStatus(job)}</span>
            </summary>
            <Audit events={events} />
          </details>
        ) : (
          <p role="status">{jobStatus(job)}</p>
        )}
        {!!blockers.length && (
          <details className={styles.geometryDetails}>
            <summary>Что мешает продолжить</summary>
            {blockers.map((reason) => (
              <p key={reason}>{reason}</p>
            ))}
          </details>
        )}
        {job && handedOver.has(job.stage) && (
          <p>Карточка передана на подбор параметров</p>
        )}
      </Field>
      {/* The card stays available while later stages work on it. */}
      {card &&
        card.revision === job?.revision &&
        (!running || job.stage !== "understanding") && (
          <a href={`/api/v1/jobs/${job.id}/card`} download="task-card.json">
            Скачать карточку JSON
          </a>
        )}
      {job?.stage === "done" && job.parameters && (
        <a
          href={`/api/v1/jobs/${job.id}/parameters`}
          download="parameter-set.json"
        >
          Скачать параметры JSON
        </a>
      )}
      {job?.stage === "done" && job.result?.sliced && (
        <>
          <a
            href={`/api/v1/jobs/${job.id}/result/project`}
            download="project.3mf"
          >
            Скачать проект 3MF
          </a>
          <a
            href={`/api/v1/jobs/${job.id}/result/gcode`}
            download="result.gcode"
          >
            Скачать G-code
          </a>
        </>
      )}
    </aside>
  );
}

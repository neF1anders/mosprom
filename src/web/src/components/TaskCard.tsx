import type { ReactNode } from "react";
import { Audit } from "./Audit";
import type { Geometry, Job, ProgressEvent } from "../types";
import { statusLabel } from "../types";
import styles from "../App.module.css";

const defectLabels: Record<string, string> = {
  boundary_edges: "Открытая поверхность",
  duplicate_faces: "Повторяющиеся грани",
  multiple_shells: "Несколько оболочек",
  nonmanifold_edges: "Немногообразные рёбра",
  inconsistent_winding: "Несогласованные нормали",
  topology_unchecked: "Топология не проверена",
};
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
export function TaskCard({
  job,
  onCollapse,
  events = [],
  onEdit,
  onStop,
}: {
  job?: Job;
  onCollapse: () => void;
  events?: ProgressEvent[];
  onEdit?: () => void;
  onStop?: () => void;
}) {
  const card = job?.card;
  const geometry =
    events.reduce<Geometry | undefined>(
      (previous, event) =>
        event.type === "geometry.completed"
          ? (event.data.geometry as Geometry)
          : previous,
      undefined,
    ) || card?.geometry;
  const running =
    !!job && ["running", "queued", "stopping"].includes(job.status);
  const requirements =
    card?.requirements.filter((requirement) => requirement.mandatory) || [];
  const dimensions = geometry?.extents
    .map((x) => Number(x.toFixed(3)))
    .join(" × ");
  const unresolved =
    card?.questions.filter((q) => q.answer === null).length || 0;
  const defects = geometry?.defects.map((d) => defectLabels[d] || d) || [];
  const unknowns = card ? [...card.assumptions, ...card.unknowns] : [];
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
        state={
          requirements.length
            ? unresolved || running
              ? "warn"
              : "done"
            : "empty"
        }
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
                  <blockquote key={j}>
                    {source.quote}
                    <small>
                      {source.source_id}
                      {source.page ? ` · стр ${source.page}` : ""}
                      {source.method === "vision"
                        ? " · прочитано по изображению"
                        : ""}
                    </small>
                    {source.artifact_id && (
                      <a
                        href={`/api/v1/jobs/${job?.id}/artifacts/${encodeURIComponent(source.artifact_id)}`}
                        target="_blank"
                        rel="noreferrer"
                      >
                        Посмотреть страницу
                      </a>
                    )}
                  </blockquote>
                ))}
              </details>
            ))}
          </details>
        ) : (
          <p>Нет данных</p>
        )}
      </Field>
      <Field
        title="Геометрия"
        state={dimensions ? (defects.length ? "warn" : "done") : "empty"}
      >
        <p>
          {dimensions
            ? `${dimensions} ${geometry?.units === "unknown" ? "единицы не указаны" : "мм"}`
            : "Нет данных"}
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
        state={unknowns.length ? "warn" : card ? "done" : "empty"}
      >
        {unknowns.length ? (
          <details className={styles.cardDisclosure}>
            <summary>
              {card?.assumptions.length} допущений · {card?.unknowns.length}{" "}
              неизвестных
            </summary>
            {unknowns.map((text, i) => (
              <p key={i}>{text}</p>
            ))}
          </details>
        ) : (
          <p>{card ? "Нет допущений и неизвестных" : "Нет данных"}</p>
        )}
        {card?.questions
          .filter((q) => q.answer === "Не знаю")
          .map((q) => (
            <p key={q.id}>Не удалось уточнить · {q.title}</p>
          ))}
      </Field>
      <Field
        title="Готовность"
        state={
          running
            ? "warn"
            : card
              ? card.readiness === "blocked"
                ? "error"
                : "done"
              : job?.status === "running"
                ? "warn"
                : "empty"
        }
      >
        {events.length ? (
          <details className={styles.cardDisclosure}>
            <summary
              aria-label="Показать журнал вызовов"
              title="Раскрыть журнал проверок"
            >
              <span role="status">{statusLabel[job?.status || "draft"]}</span>
            </summary>
            <Audit events={events} />
          </details>
        ) : (
          <p role="status">{statusLabel[job?.status || "draft"]}</p>
        )}
        {!!blockers.length && (
          <details className={styles.geometryDetails}>
            <summary>Что мешает продолжить</summary>
            {blockers.map((reason) => (
              <p key={reason}>{reason}</p>
            ))}
          </details>
        )}
        {job?.handoff === "not_connected" && (
          <p>Карточка подготовлена, следующий этап не подключён</p>
        )}
      </Field>
      {card && !running && card.revision === job?.revision && (
        <a href={`/api/v1/jobs/${job?.id}/card`} download="task-card.json">
          Скачать карточку JSON
        </a>
      )}
      {job?.status === "completed" && (
        <div className={styles.actions}>
          <button onClick={onEdit}>Внести правки</button>
          <button onClick={onStop}>Остановить</button>
        </div>
      )}
    </aside>
  );
}

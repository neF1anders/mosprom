import { useState, type ReactNode } from "react";
import { barOrder, cardSections, stateWords, type Section } from "../card";
import type { Attachment, Job, ProgressEvent } from "../types";
import { AgentsPanel, type AgentRow } from "./AgentsPanel";
import { Icon } from "./Icon";
import { ProjectFiles } from "./ProjectFiles";
import styles from "../App.module.css";

const markers: Record<Section["state"], ReactNode> = {
  done: <Icon name="check" size={12} />,
  error: <Icon name="cross" size={12} />,
  warn: <Icon name="attention" size={12} />,
  run: <Icon name="spinner-20" size={20} className={styles.spin} />,
  wait: <Icon name="ring" size={20} />,
};
// раздел как шаг
function Step({ section }: { section: Section }) {
  const [open, setOpen] = useState(false);
  const word = stateWords[section.state];
  return (
    <li className={styles.step} data-state={section.state}>
      <span className={styles.stepMarker}>{markers[section.state]}</span>
      <div>
        <button
          className={styles.stepTitle}
          aria-expanded={section.items.length ? open : undefined}
          disabled={!section.items.length}
          onClick={() => setOpen(!open)}
        >
          <h3>{section.title}</h3>
          {word && <small>{word}</small>}
        </button>
        <p>{section.summary}</p>
        {open && (
          <ul className={styles.stepItems}>
            {section.items.map((item, index) => (
              <li key={index}>
                {item.href ? (
                  <a href={item.href} download>
                    {item.text}
                  </a>
                ) : (
                  <span>{item.text}</span>
                )}
                {(item.meta || item.tag || item.page) && (
                  <small>
                    {item.meta}
                    {item.tag && <em>{item.tag}</em>}
                    {item.page && (
                      <a href={item.page} target="_blank" rel="noreferrer">
                        Посмотреть страницу
                      </a>
                    )}
                  </small>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </li>
  );
}
// правая панель
export function TaskCard({
  job,
  onCollapse,
  events = [],
  attachments = [],
  folder,
  agents = [],
  highlighted,
  detail,
  pending = false,
  collapsed = false,
  onRemove = () => {},
  onHighlight,
  onAgent,
}: {
  job?: Job;
  onCollapse: () => void;
  events?: ProgressEvent[];
  attachments?: Attachment[];
  folder?: string | null;
  agents?: AgentRow[];
  highlighted?: string;
  // ход мысли агента
  detail?: ReactNode;
  pending?: boolean;
  collapsed?: boolean;
  onRemove?: (id: string) => void;
  onHighlight?: (id: string) => void;
  onAgent?: (id: string) => void;
}) {
  const sections = cardSections(job, events);
  const done = sections.filter((section) => section.state === "done").length;
  return (
    <aside
      className={styles.card}
      aria-label="Карточка задания"
      data-empty={!job?.card}
      inert={collapsed}
    >
      <ProjectFiles
        job={job}
        attachments={attachments}
        folder={folder}
        pending={pending}
        onCollapse={onCollapse}
        onRemove={onRemove}
      />
      {detail}
      {!detail && (
        <AgentsPanel
          agents={agents}
          highlighted={highlighted}
          onHighlight={onHighlight}
          onOpen={onAgent}
        />
      )}
      <section className={styles.taskCard} hidden={!!detail}>
        <div className={styles.row}>
          <h2>Карточка задания</h2>
          <small role="status">{done} из 4 готово</small>
        </div>
        <div className={styles.bar} aria-hidden="true">
          {barOrder(sections).map((state, index) => (
            <span key={index} data-state={state} />
          ))}
        </div>
        <ol className={styles.cardSteps}>
          {sections.map((section) => (
            <Step key={section.key} section={section} />
          ))}
        </ol>
      </section>
    </aside>
  );
}

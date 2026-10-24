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
// One section as a step, as the stages in the thread; a click opens its list (Figma screen 21).
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
                {(item.meta || item.tag) && (
                  <small>
                    {item.meta}
                    {item.tag && <em>{item.tag}</em>}
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
// The right panel: the project files, the agents at work and the task card.
export function TaskCard({
  job,
  onCollapse,
  events = [],
  attachments = [],
  folder,
  agents = [],
  pending = false,
  collapsed = false,
  onRemove = () => {},
}: {
  job?: Job;
  onCollapse: () => void;
  events?: ProgressEvent[];
  attachments?: Attachment[];
  folder?: string | null;
  agents?: AgentRow[];
  pending?: boolean;
  collapsed?: boolean;
  onRemove?: (id: string) => void;
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
      <AgentsPanel agents={agents} />
      <section className={styles.taskCard}>
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

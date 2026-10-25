import { useState } from "react";
import { seconds, type AgentRun, type Retold, type Thought } from "../timeline";
import { ActionRow } from "./Timeline";
import { Icon } from "./Icon";
import styles from "../App.module.css";

function clock(ms: number) {
  const total = Math.max(0, Math.round(ms / 1000));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}
// старые мысли бледнеют
function age(index: number, count: number) {
  if (index === count - 1) return "now";
  return index === count - 2 ? "recent" : "old";
}
// рассуждение модели
function Original({ thoughts }: { thoughts: Thought[] }) {
  return (
    <div className={styles.original} lang="en">
      {thoughts.map((thought, index) => (
        <p key={index}>{thought.text.trim()}</p>
      ))}
    </div>
  );
}
// фраза рассказчика
function Phrase({ item }: { item: Retold }) {
  const [open, setOpen] = useState(false);
  if (!item.original.length) return <p>{item.text}</p>;
  return (
    <>
      <button aria-expanded={open} onClick={() => setOpen(!open)}>
        <p>{item.text}</p>
      </button>
      {open && <Original thoughts={item.original} />}
    </>
  );
}
// рассуждение под кнопкой
function Unretold({ thoughts }: { thoughts: Thought[] }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        className={styles.reveal}
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        {open ? "Скрыть размышление модели" : "Показать размышление модели"}
      </button>
      {open && <Original thoughts={thoughts} />}
    </>
  );
}
// ход мысли агента
export function AgentDetail({
  agent,
  now,
  onBack,
}: {
  agent: AgentRun;
  now: number;
  onBack: () => void;
}) {
  const running = agent.state === "run";
  const took = seconds((agent.finished ?? now) - agent.started);
  return (
    <section
      className={styles.agentDetail}
      aria-label={`Ход мыслей, ${agent.title}`}
    >
      <button className={styles.back} onClick={onBack}>
        <Icon name="chev-left" />
        Назад к заданию
      </button>
      <div className={styles.agentTitle}>
        <span>
          <Icon name={agent.icon} size={20} />
        </span>
        <div>
          <h2>{agent.title}</h2>
          <small data-tone={running ? "run" : "muted"}>
            {running ? `работает ${took}` : `завершил за ${took}`}
          </small>
        </div>
      </div>
      {agent.said.length > 0 && (
        <>
          <h3>Ход мыслей</h3>
          <ol className={styles.thoughts}>
            {agent.said.map((item, index) => (
              <li key={item.at} data-age={age(index, agent.said.length)}>
                <time>{clock(item.at - agent.started)}</time>
                <div>
                  <Phrase item={item} />
                </div>
              </li>
            ))}
          </ol>
        </>
      )}
      {!agent.said.length && agent.thoughts.length > 0 && (
        <>
          <h3>Ход мыслей</h3>
          <Unretold thoughts={agent.thoughts} />
        </>
      )}
      {agent.actions.length > 0 && (
        <>
          <h3>Действия</h3>
          <div className={styles.detailActions}>
            {agent.actions.map((action) => (
              <ActionRow key={action.id} action={action} />
            ))}
          </div>
        </>
      )}
    </section>
  );
}

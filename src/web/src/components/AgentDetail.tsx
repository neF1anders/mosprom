import { seconds, type AgentRun } from "../timeline";
import { ActionRow } from "./Timeline";
import { Icon } from "./Icon";
import styles from "../App.module.css";

function clock(ms: number) {
  const total = Math.max(0, Math.round(ms / 1000));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}
// Older thoughts fade: the last one is in full colour, the one before it is grey.
function age(index: number, count: number) {
  if (index === count - 1) return "now";
  return index === count - 2 ? "recent" : "old";
}
// An agent's train of thought in the right panel, Figma screen 18.
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
      {agent.thoughts.length > 0 && (
        <>
          <h3>Ход мыслей</h3>
          <ol className={styles.thoughts}>
            {agent.thoughts.map((thought, index) => (
              <li key={index} data-age={age(index, agent.thoughts.length)}>
                <time>{clock(thought.at - agent.started)}</time>
                <p>{thought.text.trim()}</p>
              </li>
            ))}
          </ol>
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

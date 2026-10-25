import { Icon } from "./Icon";
import styles from "../App.module.css";

export interface AgentRow {
  id: string;
  title: string;
  icon: string;
}
// "Агенты", Figma node 132:451: the agents at work right now, each with a spinner.
export function AgentsPanel({
  agents,
  highlighted,
  onHighlight,
  onOpen,
}: {
  agents: AgentRow[];
  highlighted?: string;
  onHighlight?: (id: string) => void;
  onOpen?: (id: string) => void;
}) {
  if (!agents.length) return null;
  return (
    <section className={styles.agents} aria-label="Агенты">
      <div className={styles.row}>
        <h2>Агенты</h2>
        <small>{agents.length} в работе</small>
      </div>
      <ul>
        {agents.map((agent) => (
          <li key={agent.id}>
            <button
              data-highlighted={highlighted === agent.id}
              onMouseEnter={() => onHighlight?.(agent.id)}
              onMouseLeave={() => onHighlight?.("")}
              onFocus={() => onHighlight?.(agent.id)}
              onBlur={() => onHighlight?.("")}
              onClick={() => onOpen?.(agent.id)}
            >
              <Icon name={agent.icon} size={20} />
              <span>{agent.title}</span>
              <Icon name="spinner-14" size={14} className={styles.spin} />
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

import type { CallThoughts } from "../timeline";
import { Icon } from "./Icon";
import styles from "../App.module.css";

const CHAT_AGENTS = new Set(["assistant", "analyst", "report"]);
// The assistant's reply is on its way; while it looks into the work, the narrator says how.
export function Replying({
  thoughts,
}: {
  thoughts: Record<string, CallThoughts>;
}) {
  const phrase = Object.values(thoughts)
    .filter((call) => CHAT_AGENTS.has(call.agent))
    .flatMap((call) => call.said)
    .sort((a, b) => a.at - b.at)
    .at(-1)?.text;
  return (
    <div className={styles.replying} role="status">
      <Icon name="spinner-14" size={14} className={styles.spin} />
      <span key={phrase}>{phrase || "Думаю над ответом"}</span>
    </div>
  );
}

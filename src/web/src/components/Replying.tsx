import { Icon } from "./Icon";
import styles from "../App.module.css";

// The message is on its way and the assistant has not started yet; then its card shows.
export function Replying() {
  return (
    <div className={styles.replying}>
      <Icon name="spinner-14" size={14} className={styles.spin} />
      <span className={styles.phrase}>Думаю над ответом</span>
    </div>
  );
}

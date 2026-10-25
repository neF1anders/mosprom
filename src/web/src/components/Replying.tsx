import { Icon } from "./Icon";
import styles from "../App.module.css";

// ответ в пути
export function Replying() {
  return (
    <div className={styles.replying}>
      <Icon name="spinner-14" size={14} className={styles.spin} />
      <span className={styles.phrase}>Думаю над ответом</span>
    </div>
  );
}

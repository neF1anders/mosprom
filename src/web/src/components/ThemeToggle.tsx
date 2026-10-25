import { Icon } from "./Icon";
import styles from "../App.module.css";

// переключатель темы
export function ThemeToggle({
  theme,
  onToggle,
}: {
  theme: "light" | "dark";
  onToggle: () => void;
}) {
  const dark = theme === "dark";
  return (
    <button
      className={styles.icon}
      aria-label={dark ? "Светлая тема" : "Тёмная тема"}
      title={dark ? "Светлая тема" : "Тёмная тема"}
      onClick={onToggle}
    >
      <Icon name={dark ? "sun" : "moon"} size={20} />
    </button>
  );
}

import { useEffect, useRef, useState } from "react";
import type { QueuedMessage } from "../types";
import { Icon } from "./Icon";
import styles from "../App.module.css";

// сообщение в очереди
function Plate({
  item,
  pending,
  onSend,
  onDelete,
  onEdit,
}: {
  item: QueuedMessage;
  pending: boolean;
  onSend: () => void;
  onDelete: () => void;
  onEdit: () => void;
}) {
  const [menu, setMenu] = useState(false);
  const root = useRef<HTMLLIElement>(null);
  useEffect(() => {
    if (!menu) return;
    const close = (event: MouseEvent | KeyboardEvent) => {
      if (
        event instanceof KeyboardEvent
          ? event.key === "Escape"
          : !root.current?.contains(event.target as Node)
      )
        setMenu(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", close);
    };
  }, [menu]);
  // доставка не меняется
  const busy = pending || item.status !== "queued";
  return (
    <li ref={root} className={styles.plate} data-status={item.status}>
      <Icon name="queue" />
      <span title={item.text}>{item.text}</span>
      <button className={styles.steer} disabled={busy} onClick={onSend}>
        <Icon name="redirect" size={14} />
        Скорректировать
      </button>
      <button
        className={styles.icon}
        aria-label="Удалить из очереди"
        disabled={busy}
        onClick={onDelete}
      >
        <Icon name="trash" />
      </button>
      <button
        className={styles.icon}
        aria-label="Действия с сообщением"
        aria-expanded={menu}
        disabled={busy}
        onClick={() => setMenu(!menu)}
      >
        <Icon name="more" />
      </button>
      {menu && (
        <div className={styles.plateMenu} role="menu">
          <button
            role="menuitem"
            onClick={() => {
              setMenu(false);
              onEdit();
            }}
          >
            Изменить
          </button>
        </div>
      )}
    </li>
  );
}
// очередь сообщений
export function QueuedMessages({
  items,
  pending,
  onSend,
  onDelete,
  onEdit,
}: {
  items: QueuedMessage[];
  pending: boolean;
  onSend: (id: string) => void;
  onDelete: (id: string) => void;
  onEdit: (item: QueuedMessage) => void;
}) {
  if (!items.length) return null;
  return (
    <ul className={styles.queue} aria-label="Отложенные сообщения">
      {items.map((item) => (
        <Plate
          key={item.id}
          item={item}
          pending={pending}
          onSend={() => onSend(item.id)}
          onDelete={() => onDelete(item.id)}
          onEdit={() => onEdit(item)}
        />
      ))}
    </ul>
  );
}

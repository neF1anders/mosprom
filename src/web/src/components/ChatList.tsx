import { chatDate } from "../chat";
import type { Job } from "../types";
import { statusLabel } from "../types";
import { ChatItem } from "./ChatItem";
import styles from "../App.module.css";

export function ChatList({
  jobs,
  selected,
  open,
  canCreate,
  hasMore,
  loadingMore,
  onCreate,
  onOpen,
  onRename,
  onDelete,
  onMore,
  onCollapse,
}: {
  jobs: Job[];
  selected: string;
  open: boolean;
  canCreate: boolean;
  hasMore: boolean;
  loadingMore: boolean;
  onCreate: () => void;
  onOpen: (id: string) => void;
  onRename: (id: string, title: string) => void;
  onDelete: (id: string) => void;
  onMore: () => void;
  onCollapse: () => void;
}) {
  return (
    <aside className={styles.chats} aria-label="Чаты" inert={!open}>
      <div className={styles.row}>
        <h2>Чаты</h2>
        <div className={styles.actions}>
          <button
            className={styles.icon}
            aria-label="Новое задание"
            disabled={!canCreate}
            onClick={onCreate}
          >
            <img src="/figma/new-chat.svg" alt="" />
          </button>
          <button
            className={styles.icon}
            aria-label="Свернуть чаты"
            onClick={onCollapse}
          >
            <img src="/figma/collapse-left.svg" alt="" />
          </button>
        </div>
      </div>
      <nav aria-label="Задания">
        {jobs.map((item) => (
          <ChatItem
            key={item.id}
            item={item}
            active={item.id === selected}
            label={`${item.title} ${statusLabel[item.status]}`}
            date={chatDate(item.updated_at, item.id === selected)}
            onOpen={() => onOpen(item.id)}
            onRename={(title) => onRename(item.id, title)}
            onDelete={() => onDelete(item.id)}
          />
        ))}
      </nav>
      {hasMore && (
        <button onClick={onMore} disabled={loadingMore}>
          Загрузить ещё чаты
        </button>
      )}
    </aside>
  );
}

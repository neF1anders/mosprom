import { chatDate } from "../chat";
import type { Job } from "../types";
import { jobStatus } from "../types";
import { ChatItem } from "./ChatItem";
import type { ReactNode } from "react";
import { Icon } from "./Icon";
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
  themeSwitch,
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
  themeSwitch?: ReactNode;
}) {
  return (
    <aside className={styles.chats} aria-label="Чаты" inert={!open}>
      <div className={styles.brand}>
        <h1>StereotechAI Plugin</h1>
        {themeSwitch}
      </div>
      <div className={styles.row}>
        <h2>Чаты</h2>
        <div className={styles.actions}>
          <button
            className={styles.icon}
            aria-label="Новое задание"
            disabled={!canCreate}
            onClick={onCreate}
          >
            <Icon name="new-chat" size={20} />
          </button>
          <button
            className={styles.icon}
            aria-label="Свернуть чаты"
            onClick={onCollapse}
          >
            <Icon name="collapse-left" size={20} />
          </button>
        </div>
      </div>
      <nav aria-label="Задания">
        {jobs.map((item) => (
          <ChatItem
            key={item.id}
            item={item}
            active={item.id === selected}
            label={`${item.title} ${jobStatus(item)}`}
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

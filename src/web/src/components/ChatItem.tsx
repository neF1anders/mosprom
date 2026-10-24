import { useEffect, useRef, useState } from "react";
import type { Job } from "../types";
import { Icon } from "./Icon";
import styles from "../App.module.css";

// A long title runs on hover; the menu renames the chat in place or deletes it.
export function ChatItem({
  item,
  active,
  label,
  date,
  onOpen,
  onRename,
  onDelete,
}: {
  item: Job;
  active: boolean;
  label: string;
  date: string;
  onOpen: () => void;
  onRename: (title: string) => void;
  onDelete: () => void;
}) {
  const [menu, setMenu] = useState<"closed" | "open" | "confirm">("closed");
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(item.title);
  const root = useRef<HTMLDivElement>(null);
  const title = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    if (menu === "closed") return;
    const close = (event: MouseEvent | KeyboardEvent) => {
      if (
        event instanceof KeyboardEvent
          ? event.key === "Escape"
          : !root.current?.contains(event.target as Node)
      )
        setMenu("closed");
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", close);
    };
  }, [menu]);
  function run() {
    const outer = title.current;
    const inner = outer?.firstElementChild as HTMLElement | null;
    if (!outer || !inner) return;
    // The clipped outer span reports the full text width; an inline child reports zero.
    const shift = outer.scrollWidth - outer.clientWidth;
    if (shift <= 0) return;
    inner.style.setProperty("--shift", `-${shift}px`);
    // About 40 px a second, with pauses at both ends inside the keyframes.
    inner.style.setProperty("--duration", `${Math.max(2.5, shift / 28)}s`);
    outer.dataset.marquee = "true";
  }
  function halt() {
    if (title.current) title.current.dataset.marquee = "false";
  }
  function save() {
    setEditing(false);
    const value = draft.trim();
    if (value && value !== item.title) onRename(value);
  }
  return (
    <div
      ref={root}
      className={styles.chatItem}
      data-active={active}
      data-menu={menu !== "closed"}
    >
      {editing ? (
        <input
          className={styles.chatRename}
          aria-label="Новое название чата"
          value={draft}
          maxLength={80}
          autoFocus
          onFocus={(event) => event.currentTarget.select()}
          onChange={(event) => setDraft(event.target.value)}
          onBlur={save}
          onKeyDown={(event) => {
            if (event.key === "Enter") event.currentTarget.blur();
            if (event.key === "Escape") {
              setDraft(item.title);
              setEditing(false);
            }
          }}
        />
      ) : (
        <button
          className={active ? styles.activeChat : ""}
          aria-label={label}
          title={item.title}
          onClick={onOpen}
          onMouseEnter={run}
          onMouseLeave={halt}
          onFocus={run}
          onBlur={halt}
        >
          <span ref={title} className={styles.chatTitle}>
            <span>{item.title}</span>
          </span>
          <small>{date}</small>
        </button>
      )}
      {!editing && (
        <button
          className={styles.chatMore}
          aria-label="Действия с чатом"
          aria-expanded={menu !== "closed"}
          onClick={() => setMenu(menu === "closed" ? "open" : "closed")}
        >
          <Icon name="more" />
        </button>
      )}
      {menu === "open" && (
        <div className={styles.chatMenu} role="menu">
          <button
            role="menuitem"
            onClick={() => {
              setMenu("closed");
              setDraft(item.title);
              setEditing(true);
            }}
          >
            Переименовать
          </button>
          <button role="menuitem" onClick={() => setMenu("confirm")}>
            Удалить
          </button>
        </div>
      )}
      {menu === "confirm" && (
        <div className={styles.chatMenu} role="menu">
          <button
            role="menuitem"
            data-danger="true"
            onClick={() => {
              setMenu("closed");
              onDelete();
            }}
          >
            Удалить чат
          </button>
          <button role="menuitem" onClick={() => setMenu("closed")}>
            Отмена
          </button>
        </div>
      )}
    </div>
  );
}

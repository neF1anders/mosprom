import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Attachments, type DraftFile } from "./Attachments";
import { Icon } from "./Icon";
import { useDictation } from "../hooks/useDictation";
import styles from "../App.module.css";

export function Composer({
  onSend,
  onFiles,
  onRemoveFile,
  onStop,
  pending,
  running,
  connected = true,
  files,
  filesChanged,
  placeholder,
  editing,
  onEdit,
  onCancelEdit,
}: {
  onSend: (text: string) => Promise<unknown>;
  onFiles: (files: File[]) => void;
  onRemoveFile: (file: DraftFile) => void;
  onStop: () => void;
  pending: boolean;
  running: boolean;
  connected?: boolean;
  files: DraftFile[];
  filesChanged: boolean;
  placeholder?: string;
  // правка из очереди
  editing?: { id: string; text: string } | null;
  onEdit?: (text: string) => Promise<unknown>;
  onCancelEdit?: () => void;
}) {
  // файлы ждут отправки
  const sending = useRef(false);
  const [text, setText] = useState("");
  // отправка ждёт связи
  const [waiting, setWaiting] = useState(false);
  const form = useRef<HTMLFormElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const field = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    if (!editing) return;
    setText(editing.text);
    field.current?.focus();
  }, [editing?.id]);
  useEffect(() => {
    if (!connected || !waiting) return;
    setWaiting(false);
    form.current?.requestSubmit();
  }, [connected, waiting]);
  // рост поля ввода
  useLayoutEffect(() => {
    const element = field.current;
    if (!element) return;
    element.style.height = "auto";
    element.style.height = `${element.scrollHeight}px`;
  }, [text]);
  const uploading = files.some((file) => file.uploading);
  const dictation = useDictation((spoken) =>
    setText((t) => [t, spoken].filter(Boolean).join(" ")),
  );
  return (
    <form
      ref={form}
      className={styles.composer}
      onSubmit={async (e) => {
        e.preventDefault();
        if (!connected) {
          setWaiting(true);
          return;
        }
        if (editing && onEdit) {
          if (!text.trim()) return;
          await onEdit(text.trim()).catch(() => undefined);
          setText("");
          return;
        }
        if (
          (!text.trim() && !filesChanged) ||
          pending ||
          uploading ||
          sending.current
        )
          return;
        sending.current = true;
        const draft = text;
        try {
          await onSend(draft.trim());
          setText((current) => (current === draft ? "" : current));
        } catch {
          // черновик остаётся
        } finally {
          sending.current = false;
        }
      }}
    >
      <Attachments files={files} onRemove={onRemoveFile} />
      <label className={styles.srOnly} htmlFor="message">
        Сообщение
      </label>
      <textarea
        ref={field}
        id="message"
        rows={1}
        placeholder={
          placeholder ||
          (running
            ? "Можно написать сообщение, я отвечу после текущего шага"
            : "Напишите, что нужно напечатать…")
        }
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Escape" && editing) {
            setText("");
            onCancelEdit?.();
            return;
          }
          // Enter отправляет
          if (e.key !== "Enter" || e.shiftKey || e.nativeEvent.isComposing)
            return;
          e.preventDefault();
          e.currentTarget.form?.requestSubmit();
        }}
      />
      <div className={styles.row}>
        <input
          ref={fileInput}
          aria-label="Выбрать файлы"
          type="file"
          disabled={pending}
          multiple
          accept=".stl,.pdf,.docx,.txt,.md,.jpg,.jpeg,.png"
          className={styles.srOnly}
          onChange={(e) => {
            onFiles(Array.from(e.target.files || []));
            e.target.value = "";
          }}
        />
        <button
          type="button"
          className={styles.icon}
          aria-label="Прикрепить файлы"
          disabled={pending}
          onClick={() => fileInput.current?.click()}
        >
          <Icon name="clip" />
        </button>
        <div className={styles.actions}>
          <button
            type="button"
            className={styles.icon}
            aria-label={
              dictation.listening ? "Остановить диктовку" : "Голосовой ввод"
            }
            disabled={!dictation.available}
            title={
              dictation.available
                ? "Голосовой ввод"
                : "Голосовой ввод недоступен в этом браузере"
            }
            onClick={dictation.toggle}
          >
            <Icon name="mic" size={32} />
          </button>
          {running && !text.trim() && !editing ? (
            <button
              type="button"
              className={styles.icon}
              onClick={onStop}
              aria-label="Остановить"
            >
              <Icon name="stop" size={32} />
            </button>
          ) : (
            <button
              type="submit"
              className={`${styles.icon} ${styles.send}`}
              disabled={pending || uploading || (!text.trim() && !filesChanged)}
              aria-label="Отправить"
            >
              <Icon name="arrow-up" size={32} />
            </button>
          )}
        </div>
      </div>
    </form>
  );
}

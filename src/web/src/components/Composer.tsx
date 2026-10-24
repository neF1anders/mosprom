import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Attachments, type DraftFile } from "./Attachments";
import styles from "../App.module.css";

type Recognition = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start: () => void;
  stop: () => void;
  onresult: ((event: { results: { transcript: string }[][] }) => void) | null;
  onerror: (() => void) | null;
  onend: (() => void) | null;
};
export function Composer({
  onSend,
  onFiles,
  onRemoveFile,
  onStop,
  pending,
  running,
  files,
  filesChanged,
  placeholder,
}: {
  onSend: (text: string) => Promise<unknown>;
  onFiles: (files: File[]) => void;
  onRemoveFile: (file: DraftFile) => void;
  onStop: () => void;
  pending: boolean;
  running: boolean;
  files: DraftFile[];
  filesChanged: boolean;
  placeholder?: string;
}) {
  // Attached files wait for an explicit send, with or without a message.
  const sending = useRef(false);
  const [text, setText] = useState("");
  const [listening, setListening] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const field = useRef<HTMLTextAreaElement>(null);
  // The field grows with Shift+Enter lines up to the CSS max height.
  useLayoutEffect(() => {
    const element = field.current;
    if (!element) return;
    element.style.height = "auto";
    element.style.height = `${element.scrollHeight}px`;
  }, [text]);
  const uploading = files.some((file) => file.uploading);
  const recognizer = useRef<Recognition | null>(null);
  const Speech =
    (
      window as unknown as {
        SpeechRecognition?: new () => Recognition;
        webkitSpeechRecognition?: new () => Recognition;
      }
    ).SpeechRecognition ||
    (window as unknown as { webkitSpeechRecognition?: new () => Recognition })
      .webkitSpeechRecognition;
  useEffect(
    () => () => {
      recognizer.current?.stop();
    },
    [],
  );
  function dictate() {
    if (listening) {
      recognizer.current?.stop();
      return;
    }
    if (!Speech) return;
    const recognition = new Speech();
    recognizer.current = recognition;
    recognition.lang = "ru-RU";
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.onresult = (event) =>
      setText((t) =>
        [t, event.results[0][0].transcript].filter(Boolean).join(" "),
      );
    recognition.onerror = recognition.onend = () => setListening(false);
    recognition.start();
    setListening(true);
  }
  return (
    <form
      className={styles.composer}
      onSubmit={async (e) => {
        e.preventDefault();
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
          // The parent displays the API error; keep the unsent draft for retry.
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
          // Enter sends, Shift+Enter starts a new line; IME composition keeps its Enter.
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
          <img src="/figma/clip.svg" alt="" />
        </button>
        <div className={styles.actions}>
          <button
            type="button"
            className={styles.icon}
            aria-label={listening ? "Остановить диктовку" : "Голосовой ввод"}
            disabled={!Speech}
            title={
              Speech
                ? "Голосовой ввод"
                : "Голосовой ввод недоступен в этом браузере"
            }
            onClick={dictate}
          >
            <img src="/figma/mic.svg" alt="" />
          </button>
          {running && !text.trim() ? (
            <button
              type="button"
              className={styles.icon}
              onClick={onStop}
              aria-label="Остановить"
            >
              <img src="/figma/stop.svg" alt="" />
            </button>
          ) : (
            <button
              type="submit"
              className={styles.icon}
              disabled={pending || uploading || (!text.trim() && !filesChanged)}
              aria-label="Отправить"
            >
              <img src="/figma/send.svg" alt="" />
            </button>
          )}
        </div>
      </div>
    </form>
  );
}

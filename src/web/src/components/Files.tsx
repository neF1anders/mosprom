import type { Attachment } from "../types";
import { statusLabel } from "../types";
import styles from "../App.module.css";
export function Files({
  attachments,
  jobId,
  pending,
  onRemove,
}: {
  attachments: Attachment[];
  jobId: string;
  pending: boolean;
  onRemove: (id: string) => void;
}) {
  if (!attachments.length) return null;
  if (attachments.every((file) => file.status === "completed"))
    return (
      <ul className={styles.fileChips} aria-label="Вложения">
        {attachments.map((file) => (
          <li key={file.id}>
            <img src="/figma/file.svg" alt="" />
            <a
              href={`/api/v1/jobs/${jobId}/artifacts/${file.id}`}
              download={file.filename}
            >
              {file.filename}
            </a>
          </li>
        ))}
      </ul>
    );
  return (
    <section className={styles.files} aria-label="Вложения">
      <h2>Файлы</h2>
      <ul>
        {attachments.map((file) => (
          <li key={file.id} data-failed={file.status === "failed"}>
            <div className={styles.fileRow}>
              <img src="/figma/file.svg" alt="" />
              <a
                href={`/api/v1/jobs/${jobId}/artifacts/${file.id}`}
                download={file.filename}
              >
                {file.filename}
              </a>
              <span className={styles.fileStatus}>
                {file.error ||
                  (file.status === "completed"
                    ? file.kind === "stl"
                      ? "Готов к анализу"
                      : "Текст прочитан"
                    : statusLabel[file.status] || file.status)}
              </span>
              <img
                src={`/figma/${file.status === "completed" ? "done" : file.status === "failed" ? "error" : "run"}.svg`}
                alt={statusLabel[file.status] || file.status}
              />
            </div>
            {file.status === "failed" && (
              <details>
                <summary aria-label="Действия с файлом">Заменить</summary>
                <button
                  disabled={pending}
                  aria-label={`Убрать ${file.filename}`}
                  onClick={() => onRemove(file.id)}
                >
                  Убрать
                </button>
              </details>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

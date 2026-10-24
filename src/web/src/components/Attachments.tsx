import { useEffect, useState } from "react";
import { preview, type Preview } from "../preview";
import styles from "../App.module.css";

export interface DraftFile {
  key: string;
  name: string;
  kind: string;
  uploading?: boolean;
  error?: string;
  load?: () => Promise<Blob>;
}
const icons: Record<string, string> = {
  stl: "stl",
  png: "image",
  jpg: "image",
  jpeg: "image",
  docx: "document",
  txt: "document",
  md: "document",
};
function uploadState(file: DraftFile) {
  if (file.uploading) return "uploading";
  return file.error ? "failed" : "ready";
}
// Files wait in the composer until the message is sent, as on Figma screen 11.
export function Attachments({
  files,
  onRemove,
}: {
  files: DraftFile[];
  onRemove: (file: DraftFile) => void;
}) {
  if (!files.length) return null;
  return (
    <ul className={styles.attachments} aria-label="Вложения к сообщению">
      {files.map((file) => (
        <AttachmentCard key={file.key} file={file} onRemove={onRemove} />
      ))}
    </ul>
  );
}
function AttachmentCard({
  file,
  onRemove,
}: {
  file: DraftFile;
  onRemove: (file: DraftFile) => void;
}) {
  const state = uploadState(file);
  const shown = usePreview(state === "ready" ? file : undefined);
  return (
    <li
      className={styles.attachment}
      data-state={state}
      aria-busy={file.uploading || undefined}
    >
      <div className={styles.attachmentPreview}>
        {state === "uploading" && (
          <img
            className={styles.attachmentSpinner}
            src="/figma/spinner.svg"
            alt="Загружаю"
          />
        )}
        {state === "failed" && (
          <>
            <img src="/figma/error.svg" alt="" />
            <p>{file.error}</p>
          </>
        )}
        {shown &&
          ("image" in shown ? (
            <img className={styles.attachmentImage} src={shown.image} alt="" />
          ) : (
            <div className={styles.attachmentText}>
              {shown.text.map((line, index) => (
                <p key={index}>{line}</p>
              ))}
            </div>
          ))}
      </div>
      <div className={styles.attachmentLabel}>
        <img src={`/figma/kind-${icons[file.kind] || "file"}.svg`} alt="" />
        <span title={file.name}>{file.name}</span>
      </div>
      {!file.uploading && (
        <button
          type="button"
          className={styles.attachmentRemove}
          aria-label={`Убрать ${file.name}`}
          onClick={() => onRemove(file)}
        >
          <img src="/figma/remove.svg" alt="" />
        </button>
      )}
    </li>
  );
}
function usePreview(file: DraftFile | undefined) {
  const [value, setValue] = useState<Preview>(null);
  const key = file?.load ? file.key : "";
  // The key identifies the file; a fresh load callback on each render is the same file.
  useEffect(() => {
    if (!file?.load) return;
    let live = true;
    void preview(file.key, file.kind, file.load).then(
      (result) => live && setValue(result),
    );
    return () => {
      live = false;
    };
  }, [key]);
  return value;
}

import { useEffect, useState } from "react";
import { preview, type Preview } from "../preview";
import { Icon } from "./Icon";
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
  stl: "model",
  png: "image",
  jpg: "image",
  jpeg: "image",
  pdf: "doc",
  docx: "doc",
  txt: "doc",
  md: "doc",
};
function uploadState(file: DraftFile) {
  if (file.uploading) return "uploading";
  return file.error ? "failed" : "ready";
}
// Files wait in the composer until the message is sent, as on Figma screen 11.
// Without onRemove the cards only show what a sent message carried.
export function Attachments({
  files,
  onRemove,
  label = "Вложения к сообщению",
}: {
  files: DraftFile[];
  onRemove?: (file: DraftFile) => void;
  label?: string;
}) {
  if (!files.length) return null;
  return (
    <ul className={styles.attachments} aria-label={label}>
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
  onRemove?: (file: DraftFile) => void;
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
        {state === "failed" && (
          <>
            <span className={styles.badge} data-state="error">
              <Icon name="err-x" />
            </span>
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
        <Icon name={icons[file.kind] || "plain-file"} />
        <span title={file.name}>{file.name}</span>
      </div>
      {onRemove && !file.uploading && (
        <button
          type="button"
          className={styles.attachmentRemove}
          aria-label={`Убрать ${file.name}`}
          onClick={() => onRemove(file)}
        >
          <Icon name="remove-x" size={20} />
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

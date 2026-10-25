import { useEffect, useState } from "react";
import { extension } from "../chat";
import type { Attachment, Job } from "../types";
import { Icon } from "./Icon";
import styles from "../App.module.css";

interface Node {
  name: string;
  href?: string;
  // A sent file the server could not read can be taken out of the task.
  attachment?: string;
  error?: string | null;
  children?: Node[];
}
// File icons of the Figma reference 201:755, chosen by the extension.
const kinds: Record<string, string> = {
  pdf: "doc",
  docx: "doc",
  txt: "doc",
  md: "doc",
  stl: "model",
  "3mf": "model",
  json: "data",
  png: "image",
  jpg: "image",
  jpeg: "image",
  gcode: "gcode",
};
// The project as the chat knows it: the files sent, the card and what the slicer made.
function tree(job: Job | undefined, attachments: Attachment[]): Node | null {
  if (!job || (!attachments.length && !job.card)) return null;
  const api = `/api/v1/jobs/${job.id}`;
  const children: Node[] = [];
  if (attachments.length)
    children.push({
      name: "материалы",
      children: attachments.map((file) => ({
        name: file.filename,
        href: `${api}/artifacts/${file.id}`,
        attachment: file.id,
        error: file.status === "failed" ? file.error : null,
      })),
    });
  if (job.card)
    children.push({ name: "карточка_задания.json", href: `${api}/card` });
  if (job.stage === "done" && job.parameters)
    children.push({ name: "параметры.json", href: `${api}/parameters` });
  const result: Node[] = job.result?.sliced
    ? [
        { name: "project.3mf", href: `${api}/result/project` },
        { name: "result.gcode", href: `${api}/result/gcode` },
      ]
    : [];
  children.push({ name: "результат", children: result });
  return { name: job.projects?.at(-1)?.title || job.title, children };
}
// Level guides as in a code editor: a pipe for an ancestor with siblings below, a bend for the row.
function guides(depth: number, continues: boolean[], last: boolean) {
  const lines = continues
    .map((more, level) => (more ? `M${16 + 18 * level} 0V28` : ""))
    .join("");
  const x = 16 + 18 * (depth - 1);
  const stem = last ? `M${x} 0V10` : `M${x} 0V28M${x} 10`;
  return `${lines}${stem}C${x} 12.667 ${x + 1.333} 14 ${x + 4} 14H${x + 7}`;
}
function Row({
  node,
  depth,
  continues,
  last,
  chosen,
  onChoose,
  onRemove,
  pending,
}: {
  node: Node;
  depth: number;
  continues: boolean[];
  last: boolean;
  chosen: string;
  onChoose: (name: string) => void;
  onRemove: (id: string) => void;
  pending: boolean;
}) {
  const folder = !!node.children;
  const open = folder && node.children!.length > 0;
  const folderIcon = open ? "folder-open" : "folder";
  const icon = folder
    ? folderIcon
    : kinds[extension(node.name)] || "plain-file";
  const content = (
    <>
      {depth > 0 && (
        <svg
          className={styles.guides}
          width={8 + 18 * depth}
          height={28}
          aria-hidden="true"
        >
          <path d={guides(depth, continues, last)} />
        </svg>
      )}
      <Icon name={node.error ? "circle-x" : icon} />
      <span>{node.name}</span>
    </>
  );
  const style = { paddingLeft: 8 + 18 * depth };
  return (
    <li>
      {node.href ? (
        <a
          className={styles.treeRow}
          style={style}
          href={node.href}
          download={node.name}
          title={node.error || node.name}
          data-chosen={chosen === node.href}
          data-failed={!!node.error}
          onClick={() => onChoose(node.href!)}
        >
          {content}
        </a>
      ) : (
        <div className={styles.treeRow} style={style}>
          {content}
        </div>
      )}
      {node.error && (
        <p className={styles.treeError} style={style}>
          {node.error}
          <button
            className={styles.icon}
            aria-label={`Убрать ${node.name}`}
            disabled={pending}
            onClick={() => onRemove(node.attachment!)}
          >
            <Icon name="trash" />
          </button>
        </p>
      )}
      {open && (
        <ul>
          {node.children!.map((child, index, all) => (
            <Row
              key={child.name}
              node={child}
              depth={depth + 1}
              continues={depth > 0 ? [...continues, !last] : []}
              last={index === all.length - 1}
              chosen={chosen}
              onChoose={onChoose}
              onRemove={onRemove}
              pending={pending}
            />
          ))}
        </ul>
      )}
    </li>
  );
}
// "Файлы проекта", Figma node 132:164: the folder of the projects and the job's files.
export function ProjectFiles({
  job,
  attachments,
  folder,
  pending = false,
  onCollapse,
  onRemove,
}: {
  job?: Job;
  attachments: Attachment[];
  folder?: string | null;
  pending?: boolean;
  onCollapse: () => void;
  onRemove: (id: string) => void;
}) {
  const [chosen, setChosen] = useState("");
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 1500);
    return () => clearTimeout(timer);
  }, [copied]);
  const root = tree(job, attachments);
  return (
    <section className={styles.projectFiles} aria-label="Файлы проекта">
      <div className={styles.row}>
        <h2>Файлы проекта</h2>
        <button
          className={styles.icon}
          aria-label="Свернуть карточку"
          onClick={onCollapse}
        >
          <Icon name="collapse-right" size={20} />
        </button>
      </div>
      {folder && (
        <div className={styles.path}>
          <span title={folder}>{folder}</span>
          <button
            className={styles.icon}
            aria-label={copied ? "Путь скопирован" : "Скопировать путь"}
            onClick={() =>
              void navigator.clipboard
                ?.writeText(folder)
                .then(() => setCopied(true))
            }
          >
            <Icon name={copied ? "check" : "copy"} size={14} />
          </button>
        </div>
      )}
      {root && (
        <ul className={styles.tree}>
          <Row
            node={root}
            depth={0}
            continues={[]}
            last
            chosen={chosen}
            onChoose={setChosen}
            onRemove={onRemove}
            pending={pending}
          />
        </ul>
      )}
    </section>
  );
}

import { answerPairs } from "../chat";
import type { AgentRun } from "../timeline";
import type { Attachment, Job, Message } from "../types";
import { Attachments, type DraftFile } from "./Attachments";
import { Icon } from "./Icon";
import { Markdown } from "./Markdown";
import { AgentDone } from "./Timeline";
import styles from "../App.module.css";

function sentAt(message: Message) {
  if (!message.created_at) return "";
  return new Date(message.created_at).toLocaleTimeString("ru-RU", {
    hour: "2-digit",
    minute: "2-digit",
  });
}
// файлы сообщения
function sentFiles(
  message: Message,
  files: Map<string, Attachment>,
  load: (id: string) => Promise<Blob>,
): DraftFile[] {
  return (message.attachment_ids || []).flatMap((id) => {
    const file = files.get(id);
    if (!file) return [];
    return [
      { key: id, name: file.filename, kind: file.kind, load: () => load(id) },
    ];
  });
}
// время и копирование
function UserMessage({
  message,
  job,
  files,
}: {
  message: Message;
  job?: Job;
  files: DraftFile[];
}) {
  const time = sentAt(message);
  return (
    <article className={styles.userMessage}>
      <Attachments files={files} label="Отправленные файлы" />
      {(message.text || message.kind === "answers") && (
        <div className={styles.bubble}>
          {message.kind === "answers" ? (
            <dl className={styles.answerList}>
              {answerPairs(message.text, job).map((pair, index) => (
                <div key={index}>
                  <dt>{pair.question}</dt>
                  <dd>{pair.answer}</dd>
                </div>
              ))}
            </dl>
          ) : (
            <p>{message.text}</p>
          )}
        </div>
      )}
      <div className={styles.messageMeta}>
        <div>
          {time && <time dateTime={message.created_at}>{time}</time>}
          <button
            className={styles.icon}
            aria-label="Скопировать сообщение"
            onClick={() => void navigator.clipboard?.writeText(message.text)}
          >
            <Icon name="copy" />
          </button>
        </div>
      </div>
    </article>
  );
}
// чат без повторов
export function MessageList({
  messages,
  job,
  hidden = new Set(),
  files = new Map(),
  load = () => Promise.reject(new Error("Файл недоступен")),
  thought = new Map(),
  onAgent = () => undefined,
}: {
  messages: Message[];
  job?: Job;
  hidden?: Set<string>;
  files?: Map<string, Attachment>;
  load?: (id: string) => Promise<Blob>;
  // ходы ассистента
  thought?: Map<string, AgentRun[]>;
  onAgent?: (id: string) => void;
}) {
  return (
    <>
      {messages
        .filter(
          (message) =>
            !hidden.has(message.id) &&
            (message.role === "user" || !hidden.has(message.text)),
        )
        .map((message) =>
          message.role === "user" ? (
            <UserMessage
              key={message.id}
              message={message}
              job={job}
              files={sentFiles(message, files, load)}
            />
          ) : (
            <article
              key={message.id}
              className={styles.agentMessage}
              data-kind={message.kind || "chat"}
            >
              {(thought.get(message.id) || []).map((turn) => (
                <AgentDone
                  key={turn.id}
                  agent={turn}
                  onOpen={() => onAgent(turn.id)}
                />
              ))}
              <Markdown text={message.text} />
            </article>
          ),
        )}
    </>
  );
}

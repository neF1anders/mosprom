import { Fragment } from "react";
import { answerPairs } from "../chat";
import type { Attachment, Job, Message } from "../types";
import { Files } from "./Files";
import { Icon } from "./Icon";
import styles from "../App.module.css";

function sentAt(message: Message) {
  if (!message.created_at) return "";
  return new Date(message.created_at).toLocaleTimeString("ru-RU", {
    hour: "2-digit",
    minute: "2-digit",
  });
}
// Hovering a sent message shows when it was sent and a copy button, as on Figma screen 23.
function UserMessage({ message, job }: { message: Message; job?: Job }) {
  const time = sentAt(message);
  return (
    <article className={styles.userMessage}>
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
// Sent files follow the last user message once read; until then they wait below the thread.
export function MessageList({
  messages,
  job,
  attachments,
  running,
  pending,
  onRemove,
}: {
  messages: Message[];
  job?: Job;
  attachments: Attachment[];
  running: boolean;
  pending: boolean;
  onRemove: (id: string) => void;
}) {
  const ready =
    attachments.length > 0 &&
    attachments.every((file) => file.status === "completed");
  const lastUserId = messages.reduce(
    (last, message) => (message.role === "user" ? message.id : last),
    "",
  );
  const files = (
    <Files
      attachments={attachments}
      jobId={job?.id || ""}
      running={running}
      pending={pending}
      onRemove={onRemove}
    />
  );
  return (
    <>
      {messages.map((message) => (
        <Fragment key={message.id}>
          {message.role === "user" ? (
            <UserMessage message={message} job={job} />
          ) : (
            <article className={styles.agentMessage}>
              <p>{message.text}</p>
            </article>
          )}
          {ready && message.id === lastUserId && files}
        </Fragment>
      ))}
      {(!ready || !lastUserId) && files}
    </>
  );
}

import { Fragment } from "react";
import { answerPairs } from "../chat";
import type { Attachment, Job, Message } from "../types";
import { Files } from "./Files";
import styles from "../App.module.css";

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
          <article
            className={
              message.role === "user" ? styles.userMessage : styles.agentMessage
            }
          >
            {message.role !== "user" && (
              <span className={styles.avatar} aria-hidden="true">
                M
              </span>
            )}
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
          </article>
          {ready && message.id === lastUserId && files}
        </Fragment>
      ))}
      {(!ready || !lastUserId) && files}
    </>
  );
}

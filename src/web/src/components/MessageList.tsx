import { answerPairs } from "../chat";
import type { Job, Message } from "../types";
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
// The chat as sent; the files are in the project tree of the right panel.
// A reply the timeline already shows as a stage summary is not repeated here.
export function MessageList({
  messages,
  job,
  hidden = new Set(),
}: {
  messages: Message[];
  job?: Job;
  hidden?: Set<string>;
}) {
  return (
    <>
      {messages
        .filter(
          (message) => message.role === "user" || !hidden.has(message.text),
        )
        .map((message) =>
          message.role === "user" ? (
            <UserMessage key={message.id} message={message} job={job} />
          ) : (
            <article key={message.id} className={styles.agentMessage}>
              <p>{message.text}</p>
            </article>
          ),
        )}
    </>
  );
}

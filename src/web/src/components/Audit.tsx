import type { ProgressEvent } from "../types";
import styles from "../App.module.css";
export function Audit({ events }: { events: ProgressEvent[] }) {
  return (
    <div className={styles.audit}>
      {events.map((event) => (
        <article key={event.event_id}>
          <p>{event.message}</p>
          <small>
            Версия {event.revision} · {event.status}
          </small>
          {Object.keys(event.data).length > 0 && (
            <pre>{JSON.stringify(event.data, null, 2)}</pre>
          )}
        </article>
      ))}
    </div>
  );
}

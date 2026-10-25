import { useEffect, useState, type ReactNode } from "react";
import type { Job } from "../types";
import { plural } from "../format";
import { seconds, type Action, type AgentRun, type Stage } from "../timeline";
import { CardSummary } from "./CardSummary";
import { Icon } from "./Icon";
import { ParameterSummary } from "./ParameterSummary";
import { ResultSummary } from "./ResultSummary";
import styles from "../App.module.css";

const markers: Record<Stage["state"], ReactNode> = {
  done: <Icon name="check" size={12} />,
  error: <Icon name="cross" size={12} />,
  warn: <Icon name="attention" size={12} />,
  run: <Icon name="spinner-20" size={20} className={styles.spin} />,
  wait: <Icon name="ring" size={20} />,
};
const markerLabels: Record<Stage["state"], string> = {
  done: "Завершено",
  error: "Остановлено с ошибкой",
  warn: "Ждёт ответа",
  run: "Выполняется",
  wait: "Не начат",
};
const actionIcons: Record<Action["kind"], string> = {
  file: "file",
  search: "search",
  terminal: "terminal",
  edit: "pencil",
  help: "help",
};
// строка действия
export function ActionRow({
  action,
  plain = false,
}: {
  action: Action;
  plain?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const icon = action.state === "error" ? "circle-x" : actionIcons[action.kind];
  const content = (
    <>
      {open && <Icon name="chev-down" size={14} />}
      <Icon name={icon} />
      <span>{action.text}</span>
    </>
  );
  if (plain || (!action.output && !action.command))
    return (
      <span className={styles.action} data-state={action.state}>
        {content}
      </span>
    );
  return (
    <div className={styles.actionGroup}>
      <button
        className={styles.action}
        data-state={action.state}
        data-open={open}
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        {content}
      </button>
      {open && (
        <pre className={styles.output}>
          {action.command && <span>{action.command}</span>}
          {action.output?.map((line, index) => (
            <span key={index}>{line}</span>
          ))}
        </pre>
      )}
    </div>
  );
}
// работающий агент
export function AgentCard({
  agent,
  highlighted,
  onOpen,
}: {
  agent: AgentRun;
  highlighted: boolean;
  onOpen: () => void;
}) {
  const phrase = agent.said.at(-1)?.text;
  const action = agent.actions[agent.actions.length - 1];
  return (
    <button
      className={styles.agentCard}
      data-agent={agent.id}
      data-highlighted={highlighted}
      aria-label={`${agent.title}, ход мыслей`}
      onClick={onOpen}
    >
      <span className={styles.agentHead}>
        <Icon name={agent.icon} size={18} />
        {agent.title}
      </span>
      {phrase && (
        // плавная смена фразы
        <span key={phrase} className={styles.reasoning}>
          {phrase}
        </span>
      )}
      {action && <ActionRow action={action} plain />}
    </button>
  );
}
// завершённый агент
export function AgentDone({
  agent,
  onOpen,
}: {
  agent: AgentRun;
  onOpen: () => void;
}) {
  const took = agent.finished ? seconds(agent.finished - agent.started) : "";
  const content = (
    <>
      <Icon name={agent.icon} size={20} />
      <span>{agent.title}</span>
      <small>
        {agent.state === "error" ? "остановлен" : `завершил за ${took}`}
      </small>
      {!agent.code && <Icon name="chev-right" size={14} />}
    </>
  );
  if (agent.code) return <div className={styles.agentDone}>{content}</div>;
  return (
    <button className={styles.agentDone} onClick={onOpen}>
      {content}
    </button>
  );
}
function Result({ stage, job }: { stage: Stage; job?: Job }) {
  if (!job || !stage.result) return null;
  if (stage.result === "card" && job.card)
    return <CardSummary card={job.card} />;
  if (stage.result === "parameters") return <ParameterSummary job={job} />;
  return <ResultSummary job={job} />;
}
// сводка свёрнутого этапа
function Compact({ stage }: { stage: Stage }) {
  const running = stage.agents.filter((a) => a.state === "run" && !a.code);
  const agents = running.length
    ? `${running.length} ${plural(running.length, ["агент работает", "агента работают", "агентов работают"])}, `
    : "";
  const actions = `${stage.actions.length} ${plural(stage.actions.length, ["действие", "действия", "действий"])}`;
  return (
    <span className={styles.compact}>
      {running.map((agent) => (
        <Icon key={agent.id} name={agent.icon} size={20} />
      ))}
      <span>{agents + actions}</span>
    </span>
  );
}
function defaultOpen(stage: Stage) {
  if (stage.state === "run" || stage.state === "error") return true;
  if (stage.key === "understanding" && stage.state === "warn") return true;
  return !!stage.result && stage.key !== "understanding";
}
function StageRow({
  stage,
  job,
  highlighted,
  onAgent,
}: {
  stage: Stage;
  job?: Job;
  highlighted: string;
  onAgent: (id: string) => void;
}) {
  const [open, setOpen] = useState(defaultOpen(stage));
  const [hint, setHint] = useState(false);
  useEffect(() => {
    if (!hint) return;
    const timer = setTimeout(() => setHint(false), 1600);
    return () => clearTimeout(timer);
  }, [hint]);
  const running = stage.agents.filter((a) => a.state === "run" && !a.code);
  const finished = stage.agents.filter((a) => a.state !== "run");
  const body =
    stage.actions.length > 0 ||
    stage.agents.length > 0 ||
    stage.notes.length > 0 ||
    !!stage.result;
  const future = stage.state === "wait" && !body;
  // этап сворачивается сам
  const folds =
    body &&
    (stage.state === "done" ||
      (stage.state === "warn" && stage.key !== "understanding"));
  return (
    <details
      className={styles.stage}
      data-state={stage.state}
      open={open && body}
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary
        onClick={(event) => {
          if (!future) return;
          event.preventDefault();
          setHint(true);
        }}
      >
        <span
          className={styles.stageMarker}
          role="img"
          aria-label={markerLabels[stage.state]}
        >
          {markers[stage.state]}
        </span>
        <span className={styles.stageHead}>
          <span className={styles.stageTitle}>
            {stage.title}
            {hint && (
              <span className={styles.tooltip} role="status">
                Этап ещё не начался
              </span>
            )}
          </span>
          {(stage.meta || folds) && (
            <small data-tone={stage.meta?.tone}>
              {stage.meta?.text}
              {folds && (
                <Icon name={open ? "chev-down" : "chev-right"} size={14} />
              )}
            </small>
          )}
        </span>
        {stage.summary && (
          <span className={styles.stageSummary}>{stage.summary}</span>
        )}
        {!open && stage.state === "run" && body && <Compact stage={stage} />}
      </summary>
      {body && (
        <div className={styles.stageBody}>
          {stage.actions.map((action) => (
            <ActionRow key={action.id} action={action} />
          ))}
          {running.length > 0 && (
            <div className={styles.agentCards} data-count={running.length}>
              {running.map((agent) => (
                <AgentCard
                  key={agent.id}
                  agent={agent}
                  highlighted={highlighted === agent.id}
                  onOpen={() => onAgent(agent.id)}
                />
              ))}
            </div>
          )}
          {stage.notes.map((note) =>
            note.role === "user" ? (
              <p key={note.id} className={styles.noteUser}>
                {note.text}
              </p>
            ) : (
              <p key={note.id} className={styles.noteReply}>
                <Icon name="redirect" />
                <span>{note.text}</span>
              </p>
            ),
          )}
          {stage.state !== "run" &&
            finished.map((agent) => (
              <AgentDone
                key={agent.id}
                agent={agent}
                onOpen={() => onAgent(agent.id)}
              />
            ))}
          <Result stage={stage} job={job} />
        </div>
      )}
    </details>
  );
}
// вертикальный таймлайн
export function Timeline({
  stages,
  job,
  highlighted = "",
  onAgent = () => {},
}: {
  stages: Stage[] | null;
  job?: Job;
  highlighted?: string;
  onAgent?: (id: string) => void;
}) {
  if (!stages) return null;
  return (
    <section className={styles.timeline} aria-label="Ход работы">
      {stages.map((stage) => (
        <StageRow
          // новый результат открыт
          key={`${stage.key}-${defaultOpen(stage)}`}
          stage={stage}
          job={job}
          highlighted={highlighted}
          onAgent={onAgent}
        />
      ))}
    </section>
  );
}

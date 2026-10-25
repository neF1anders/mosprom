import { useCallback, useEffect, useRef, useState } from "react";
import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { usePanelFocus } from "./usePanelFocus";
import { api, authenticate, command } from "./api";
import { answering, asksQuestions, composerPlaceholder, splitAt } from "./chat";
import type { Job, QueuedMessage, Snapshot } from "./types";
import { isRunning, jobStatus } from "./types";
import { useFollow } from "./hooks/useFollow";
import { useHistory } from "./hooks/useHistory";
import { useJobEvents } from "./hooks/useJobEvents";
import { useUploads } from "./hooks/useUploads";
import { Composer } from "./components/Composer";
import { ChatList } from "./components/ChatList";
import type { DraftFile } from "./components/Attachments";
import { MessageList } from "./components/MessageList";
import { forget } from "./preview";
import { Questions } from "./components/Questions";
import { QueuedMessages } from "./components/QueuedMessages";
import { Replying } from "./components/Replying";
import { AgentCard, Timeline } from "./components/Timeline";
import { AgentDetail } from "./components/AgentDetail";
import { buildTimeline, chatRuns, runsByReply, summaries } from "./timeline";
import { useNow } from "./hooks/useNow";
import { TaskCard } from "./components/TaskCard";
import { Icon } from "./components/Icon";
import { ThemeToggle } from "./components/ThemeToggle";
import { ModelSettings } from "./components/ModelSettings";
import { useTheme } from "./hooks/useTheme";
import styles from "./App.module.css";

function unique<T, K>(items: T[], key: (item: T) => K) {
  return [...new Map(items.map((item) => [key(item), item])).values()];
}
export function App() {
  const client = useQueryClient();
  const session = useQuery({
    queryKey: ["session"],
    queryFn: authenticate,
    retry: false,
    staleTime: Infinity,
  });
  const [selected, setSelected] = useState(
    new URLSearchParams(location.search).get("job") || "",
  );
  const selectedRef = useRef(selected);
  const [narrow, setNarrow] = useState(
    () => window.matchMedia("(max-width: 800px)").matches,
  );
  const [left, setLeft] = useState(!narrow),
    [right, setRight] = useState(!narrow);
  useEffect(() => {
    const media = window.matchMedia("(max-width: 800px)");
    const resize = () => {
      setNarrow(media.matches);
      setLeft(!media.matches);
      setRight(!media.matches);
    };
    media.addEventListener("change", resize);
    return () => media.removeEventListener("change", resize);
  }, []);
  const closePanels = useCallback(() => {
    setLeft(false);
    setRight(false);
  }, []);
  usePanelFocus(
    narrow && (left || right),
    `.${left ? styles.chats : styles.card}`,
    closePanels,
  );
  const [error, setError] = useState("");
  const { theme, toggle: toggleTheme } = useTheme();
  // The model connection opens by itself once, while no model is configured.
  const [modelOpen, setModelOpen] = useState(false);
  const modelAsked = useRef(false);
  const tools = (
    <>
      <button
        className={styles.icon}
        aria-label="Подключение модели"
        title="Подключение модели"
        onClick={() => setModelOpen(true)}
      >
        <Icon name="plug" size={20} />
      </button>
      <ThemeToggle theme={theme} onToggle={toggleTheme} />
    </>
  );
  const creating = useRef<Promise<string> | null>(null);
  const { threadRef, away, toBottom, onScroll, follow } = useFollow();
  const { events, thoughts, connected } = useJobEvents(
    selected,
    !!session.data,
  );
  // The agent whose train of thought is open, and the one pointed at in the panel.
  const [agentView, setAgentView] = useState("");
  const [highlighted, setHighlighted] = useState("");
  const jobs = useInfiniteQuery({
    queryKey: ["jobs"],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      api<Job[]>(
        `/jobs${pageParam ? `?before=${encodeURIComponent(pageParam)}` : ""}`,
      ),
    getNextPageParam: (last) =>
      last.length === 50 ? last[last.length - 1].id : undefined,
    enabled: !!session.data,
  });
  const snapshot = useQuery({
    queryKey: ["job", selected],
    queryFn: () => api<Snapshot>(`/jobs/${selected}`),
    enabled: !!session.data && !!selected,
  });
  const capability = useQuery({
    queryKey: ["capabilities"],
    queryFn: () =>
      api<{ model_configured: boolean; project_folder?: string | null }>(
        "/capabilities",
      ),
    enabled: !!session.data,
  });
  const unconfigured = !!capability.data && !capability.data.model_configured;
  useEffect(() => {
    if (!unconfigured || modelAsked.current) return;
    modelAsked.current = true;
    setModelOpen(true);
  }, [unconfigured]);
  const past = useHistory(
    selected,
    () => selectedRef.current,
    snapshot.data?.message_cursor,
    setError,
  );
  const { uploads, setUploads, picked, upload } = useUploads(ensureJob);
  useEffect(() => {
    const reauthenticate = () => {
      if (location.hash.startsWith("#launch="))
        void client.resetQueries({ queryKey: ["session"] });
    };
    window.addEventListener("hashchange", reauthenticate);
    return () => window.removeEventListener("hashchange", reauthenticate);
  }, [client]);
  const job = snapshot.data?.job;
  const refresh = () => {
    void client.invalidateQueries({ queryKey: ["job", selected] });
    void client.invalidateQueries({ queryKey: ["jobs"] });
  };
  function select(id: string) {
    follow();
    selectedRef.current = id;
    setSelected(id);
    if (narrow && id) setLeft(false);
    past.reset();
    history.replaceState(null, "", id ? `?job=${id}` : location.pathname);
  }
  // Another chat drops the files still waiting in this one's composer.
  function open(id: string) {
    setUploads([]);
    select(id);
  }
  const create = useMutation({
    mutationFn: () => command<Job>("/jobs"),
    onSuccess: (value) => {
      open(value.id);
      void client.invalidateQueries({ queryKey: ["jobs"] });
    },
    onError: (e) => setError(e.message),
  });
  // Messages on their way to the assistant, by chat, until the chat that has them is loaded.
  const [sending, setSending] = useState<Record<string, number>>({});
  const count = (id: string, step: number) =>
    setSending((now) => ({ ...now, [id]: (now[id] || 0) + step }));
  // While the job works a message waits in the queue for the end of the stage.
  const send = useMutation({
    mutationFn: async ({ text, queue }: { text: string; queue: boolean }) => {
      const id = await ensureJob();
      // Files alone go as a message too: the assistant decides what they are for.
      const result = await command(
        `/jobs/${id}/${queue ? "queue" : "messages"}`,
        {
          text,
        },
      );
      // The chat shows the message before the send ends, so the reply row never blinks out.
      await client.refetchQueries({ queryKey: ["job", id], exact: true });
      return result;
    },
    onSuccess: () => {
      // Rejected files never reached the server, so they are not part of the sent message.
      setUploads((list) => list.filter((file) => file.uploading));
      client.setQueryData<Snapshot>(
        ["job", selectedRef.current],
        (current) =>
          current && {
            ...current,
            attachments: current.attachments.map((file) => ({
              ...file,
              draft: false,
            })),
          },
      );
      refresh();
    },
    onError: (e) => setError(e.message),
  });
  const rename = useMutation({
    mutationFn: ({ id, title }: { id: string; title: string }) =>
      command(`/jobs/${id}/rename`, { title }),
    onSettled: () => client.invalidateQueries({ queryKey: ["jobs"] }),
    onError: (e) => setError(e.message),
  });
  const remove = useMutation({
    mutationFn: (id: string) => command(`/jobs/${id}/delete`),
    onSuccess: (_, id) => {
      if (id === selectedRef.current) open("");
      client.removeQueries({ queryKey: ["job", id] });
    },
    onSettled: () => client.invalidateQueries({ queryKey: ["jobs"] }),
    onError: (e) => setError(e.message),
  });
  const answer = useMutation({
    mutationFn: (values: Record<string, string>) =>
      command(`/jobs/${selected}/answers`, {
        answers: values,
        expected_revision: job?.revision,
      }),
    onSuccess: refresh,
    onError: (e) => {
      setError(e.message);
      refresh();
    },
  });
  const detach = useMutation({
    mutationFn: (id: string) =>
      command(`/jobs/${selected}/attachments/${id}/detach`),
    onMutate: (id) => {
      forget(id);
      picked.current.delete(id);
      client.setQueryData<Snapshot>(
        ["job", selected],
        (current) =>
          current && {
            ...current,
            attachments: current.attachments.filter((file) => file.id !== id),
          },
      );
    },
    onSettled: refresh,
    onError: (e) => setError(e.message),
  });
  const [editing, setEditing] = useState<QueuedMessage | null>(null);
  const queued = useMutation({
    mutationFn: ({
      id,
      action,
      text,
    }: {
      id: string;
      action: "send" | "delete" | "edit";
      text?: string;
    }) =>
      command(
        `/jobs/${selectedRef.current}/queue/${id}/${action}`,
        text === undefined ? {} : { text },
      ),
    onSuccess: refresh,
    onError: (e) => {
      setError(e.message);
      refresh();
    },
  });
  const control = useMutation({
    mutationFn: (action: string) =>
      command(`/jobs/${selected}/control/${action}`),
    onSuccess: refresh,
    onError: (e) => setError(e.message),
  });
  async function ensureJob() {
    if (selectedRef.current) return selectedRef.current;
    // Files picked together must not create a job each.
    creating.current ??= command<Job>("/jobs").then((created) => {
      select(created.id);
      return created.id;
    });
    try {
      return await creating.current;
    } finally {
      creating.current = null;
    }
  }
  const jobList = unique(jobs.data?.pages.flat() || [], (item) => item.id);
  const messages = unique(
    [...past.older, ...(snapshot.data?.messages || [])],
    (message) => message.id,
  ).sort((a, b) => a.seq - b.seq);
  const files = snapshot.data?.attachments || [];
  const project = job?.projects?.at(-1)?.number;
  // Unsent files wait in the composer; the tree shows the files of the current project.
  const sent = files.filter(
    (file) =>
      !file.draft &&
      file.active !== false &&
      (project === undefined || file.project === project),
  );
  const order = [...picked.current.keys()];
  const load = async (id: string) => {
    const local = picked.current.get(id);
    if (local) return local;
    const response = await fetch(`/api/v1/jobs/${selected}/artifacts/${id}`, {
      credentials: "same-origin",
    });
    if (!response.ok) throw new Error(response.statusText);
    return response.blob();
  };
  const drafts: DraftFile[] = [
    ...files
      .filter((file) => file.draft && file.active !== false)
      .sort((a, b) => order.indexOf(a.id) - order.indexOf(b.id))
      .map((file) => ({
        key: file.id,
        name: file.filename,
        kind: file.kind,
        load: () => load(file.id),
      })),
    ...uploads,
  ];
  const byId = new Map(files.map((file) => [file.id, file]));
  const running = isRunning(job);
  // A reply that started no work keeps the timeline of the work before it.
  const current = events.filter((e) => e.revision >= (job?.work_revision ?? 0));
  const asking = asksQuestions(job);
  const now = useNow(running);
  const stages = buildTimeline({
    events: current,
    job,
    attachments: sent,
    messages,
    thoughts,
    now,
    connected,
  });
  // Replies the timeline shows in place are not repeated in the chat.
  const hidden = summaries(stages);
  // What came after the work began, its report and the talk about it, follows the timeline.
  const [before, after] = splitAt(
    messages,
    stages ? current[0]?.created_at : undefined,
  );
  // A message on its way to the assistant already waits for its reply.
  const replying =
    answering(events, messages, running) || (sending[selected] || 0) > 0;
  // The assistant's turns show their reasoning as the agents of a stage do.
  const turns = chatRuns(events, thoughts);
  const thinking = turns.filter((turn) => turn.state === "run");
  const thought = runsByReply(messages, turns);
  const agents = [...(stages || []).flatMap((stage) => stage.agents), ...turns];
  const working = agents.filter(
    (agent) => agent.state === "run" && !agent.code,
  );
  const viewed = agents.find((agent) => agent.id === agentView);
  // A click in the panel brings the agent's card into view, Figma screen 22.
  function point(id: string) {
    setHighlighted(id);
    document
      .querySelector(`[data-agent="${id}"]`)
      ?.scrollIntoView({ block: "center", behavior: "smooth" });
  }
  if (session.isError)
    return (
      <main className={styles.locked}>
        <h1>StereotechAI Plugin</h1>
        <p>Откройте приложение по новой ссылке запуска</p>
        <p role="alert">{session.error.message}</p>
      </main>
    );
  return (
    <div className={styles.app}>
      {modelOpen && <ModelSettings onClose={() => setModelOpen(false)} />}
      <header className={styles.header}>
        <h1>StereotechAI Plugin</h1>
        <div className={styles.mobileTools}>
          {tools}
          <button
            className={styles.icon}
            aria-label="Новое задание"
            disabled={!session.data || create.isPending}
            onClick={() => create.mutate()}
          >
            <Icon name="new-chat" size={20} />
          </button>
          <button
            className={styles.icon}
            aria-label="Открыть чаты"
            onClick={() => {
              setRight(false);
              setLeft(true);
            }}
          >
            <Icon name="collapse-left" size={20} />
          </button>
          <button
            className={styles.icon}
            aria-label="Открыть карточку"
            onClick={() => {
              setLeft(false);
              setRight(true);
            }}
          >
            <Icon name="collapse-right" size={20} />
          </button>
        </div>
      </header>
      {narrow && (left || right) && (
        <button
          className={styles.panelBackdrop}
          aria-label="Закрыть панель"
          onClick={closePanels}
        />
      )}
      <div className={styles.workspace} data-left={left} data-right={right}>
        <div className={styles.side} data-side="left" data-open={left}>
          <ChatList
            jobs={jobList}
            selected={selected}
            open={left}
            canCreate={!!session.data && !create.isPending}
            hasMore={jobs.hasNextPage}
            loadingMore={jobs.isFetchingNextPage}
            onCreate={() => create.mutate()}
            onOpen={open}
            onRename={(id, title) => rename.mutate({ id, title })}
            onDelete={(id) => remove.mutate(id)}
            onMore={() => jobs.fetchNextPage()}
            onCollapse={() => setLeft(false)}
            tools={tools}
          />
        </div>
        <button
          className={styles.handle}
          data-side="left"
          data-visible={!left}
          inert={left}
          onClick={() => setLeft(true)}
        >
          <span>Показать чаты</span>
        </button>
        <main className={styles.chat}>
          {(error || snapshot.isError) && (
            <div className={styles.error} role="alert">
              {error || snapshot.error?.message}
              <button
                aria-label="Закрыть сообщение об ошибке"
                onClick={() => setError("")}
              >
                <Icon name="close" />
              </button>
            </div>
          )}
          <div className={styles.threadArea}>
            <div
              ref={threadRef}
              className={styles.thread}
              data-running={running && !!messages.length}
              onScroll={onScroll}
            >
              {!snapshot.data?.messages.length && !sent.length && (
                <section className={styles.welcome}>
                  <h2>Как работает плагин</h2>
                  <p>
                    <span />
                    Загрузите STL модель детали, которую хотите напечатать
                  </p>
                  <p>
                    <span />
                    Приложите файл с подробным ТЗ, а если его нет, опишите как
                    можно подробнее назначение детали, условия эксплуатации и
                    материал, для этого можно воспользоваться голосовым вводом
                  </p>
                  <p>
                    <span />
                    Ответьте на уточняющие вопросы модели, которая будет
                    подбирать параметры
                  </p>
                </section>
              )}
              {past.before && (
                <button disabled={past.loading} onClick={past.load}>
                  Предыдущие сообщения
                </button>
              )}
              <MessageList
                messages={before}
                job={job}
                hidden={hidden}
                files={byId}
                load={load}
                thought={thought}
                onAgent={setAgentView}
              />
              <Timeline
                stages={stages}
                job={job}
                highlighted={highlighted}
                onAgent={setAgentView}
              />
              <MessageList
                messages={after}
                job={job}
                hidden={hidden}
                files={byId}
                load={load}
                thought={thought}
                onAgent={setAgentView}
              />
              {replying && (
                // One status while the assistant answers, whichever way it shows.
                <div
                  className={styles.answering}
                  role="status"
                  aria-label="Ассистент отвечает"
                >
                  {thinking.length ? (
                    thinking.map((turn) => (
                      <AgentCard
                        key={turn.id}
                        agent={turn}
                        highlighted={highlighted === turn.id}
                        onOpen={() => setAgentView(turn.id)}
                      />
                    ))
                  ) : (
                    <Replying />
                  )}
                </div>
              )}
              {job?.status === "stopped" && (
                <button onClick={() => control.mutate("retry")}>
                  Продолжить
                </button>
              )}
            </div>
            <button
              className={styles.toBottom}
              data-visible={away}
              inert={!away}
              aria-label="Прокрутить вниз"
              onClick={() => toBottom("smooth")}
            >
              <Icon name="arrow-down" />
            </button>
          </div>
          <p className={styles.srOnly} role="status">
            {jobStatus(job)}
          </p>
          {unconfigured && (
            <section className={styles.notice} role="status">
              <span className={styles.badge} data-state="warn">
                <Icon name="attention" size={12} />
              </span>
              <p>LLM модель не подключена</p>
              <button
                className={styles.small}
                onClick={() => setModelOpen(true)}
              >
                Подключить
              </button>
            </section>
          )}
          {job?.error && (
            <section className={styles.notice} role="alert">
              <span className={styles.badge} data-state="error">
                <Icon name="err-x" />
              </span>
              <p>{job.error}</p>
              <button
                className={styles.small}
                disabled={control.isPending}
                onClick={() => control.mutate("retry")}
              >
                Повторить
              </button>
            </section>
          )}
          {connected &&
            running &&
            job?.card &&
            job.card.revision < job.revision && (
              <p className={styles.notice} role="status">
                <Icon name="spinner-14" className={styles.spin} />
                Обновляю карточку с учётом изменений
              </p>
            )}
          {!connected && (
            <p className={styles.notice} role="status">
              <Icon name="spinner-14" className={styles.spin} />
              Соединение потеряно, переподключаюсь
            </p>
          )}
          {job?.card && asking && (
            <Questions
              key={`questions-${job.revision}-${job.card.questions.map((q) => q.id).join()}`}
              questions={job.card.questions}
              pending={answer.isPending}
              onAnswer={(values) => {
                toBottom("smooth");
                answer.mutate(values);
              }}
            />
          )}
          <QueuedMessages
            items={snapshot.data?.queued || []}
            pending={queued.isPending}
            onSend={(id) => queued.mutate({ id, action: "send" })}
            onDelete={(id) => queued.mutate({ id, action: "delete" })}
            onEdit={setEditing}
          />
          <Composer
            onSend={(text) => {
              toBottom("smooth");
              // Set in the click itself, so the reply row is on the page as the click ends;
              // the mutation's own state arrives a task later.
              const chat = selected;
              const queue = running;
              if (!queue) count(chat, 1);
              return send
                .mutateAsync({ text, queue })
                .finally(() => !queue && count(chat, -1));
            }}
            editing={editing}
            onEdit={(text) =>
              queued
                .mutateAsync({ id: editing!.id, action: "edit", text })
                .finally(() => setEditing(null))
            }
            onCancelEdit={() => setEditing(null)}
            onFiles={(files) => {
              setError("");
              void upload(files);
            }}
            onRemoveFile={(file) =>
              file.load
                ? detach.mutate(file.key)
                : setUploads((list) =>
                    list.filter((item) => item.key !== file.key),
                  )
            }
            onStop={() => control.mutate("stop")}
            pending={send.isPending || create.isPending || !session.data}
            running={running}
            connected={connected}
            files={drafts}
            filesChanged={!!job?.files_changed}
            placeholder={composerPlaceholder(job, connected, sent)}
          />
        </main>
        <button
          className={styles.handle}
          data-side="right"
          data-visible={!right}
          inert={right}
          onClick={() => setRight(true)}
        >
          <span>Показать карточку</span>
        </button>
        <div className={styles.side} data-side="right" data-open={right}>
          <TaskCard
            job={job}
            events={current}
            attachments={sent}
            folder={capability.data?.project_folder}
            pending={detach.isPending}
            agents={working}
            highlighted={highlighted}
            detail={
              viewed && (
                <AgentDetail
                  agent={viewed}
                  now={now}
                  onBack={() => setAgentView("")}
                />
              )
            }
            collapsed={!right}
            onCollapse={() => setRight(false)}
            onRemove={(id) => detach.mutate(id)}
            onHighlight={setHighlighted}
            onAgent={point}
          />
        </div>
      </div>
    </div>
  );
}

import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { usePanelFocus } from "./usePanelFocus";
import { api, authenticate, command, requestId } from "./api";
import type {
  Attachment,
  Job,
  Message,
  ProgressEvent,
  Snapshot,
} from "./types";
import { statusLabel } from "./types";
import { Composer } from "./components/Composer";
import { Questions } from "./components/Questions";
import { Conflict } from "./components/Conflict";
import { Progress } from "./components/Progress";
import { Files } from "./components/Files";
import { TaskCard } from "./components/TaskCard";
import styles from "./App.module.css";

function chatDate(timestamp: string, selected: boolean) {
  if (selected) return "Сейчас";
  const date = new Date(timestamp);
  const yesterday = new Date();
  yesterday.setDate(yesterday.getDate() - 1);
  if (date.toDateString() === yesterday.toDateString()) return "Вчера";
  return date
    .toLocaleDateString("ru-RU", { day: "numeric", month: "short" })
    .replace(".", "");
}
function composerPlaceholder(
  job: Job | undefined,
  connected: boolean,
  attachments: Attachment[],
) {
  if (!connected) return "Нет связи. Текст останется в поле ввода";
  if (job?.error) return "Или напишите сообщение…";
  if (attachments.some((file) => file.status === "failed"))
    return "Приложите другой файл или напишите сообщение…";
  if (job?.status === "completed") return "Написать правку или вопрос…";
  if (job?.status === "waiting_user")
    return job.card?.questions.some((question) => question.answer === null)
      ? "Или ответьте текстом…"
      : "Можно написать сообщение…";
  if (job?.status === "running" || job?.status === "queued")
    return "Можно написать сообщение, я отвечу после текущего шага";
  return "Напишите, что нужно напечатать…";
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
  const [connectionEpoch, setConnectionEpoch] = useState(0);
  const [events, setEvents] = useState<ProgressEvent[]>([]),
    [connected, setConnected] = useState(true);
  const [error, setError] = useState(""),
    [uploading, setUploading] = useState(false);
  const uploadLock = useRef(false);
  const [olderMessages, setOlderMessages] = useState<Message[]>([]);
  const [historyCursor, setHistoryCursor] = useState<
    number | null | undefined
  >();
  const [loadingHistory, setLoadingHistory] = useState(false);
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
    queryFn: () => api<{ model_configured: boolean }>("/capabilities"),
    enabled: !!session.data,
  });
  useEffect(() => {
    const reauthenticate = () => {
      if (location.hash.startsWith("#launch="))
        void client.resetQueries({ queryKey: ["session"] });
    };
    window.addEventListener("hashchange", reauthenticate);
    return () => window.removeEventListener("hashchange", reauthenticate);
  }, [client]);
  useEffect(() => {
    const offline = () => setConnected(false);
    const online = () => setConnectionEpoch((value) => value + 1);
    window.addEventListener("offline", offline);
    window.addEventListener("online", online);
    return () => {
      window.removeEventListener("offline", offline);
      window.removeEventListener("online", online);
    };
  }, []);
  const job = snapshot.data?.job;
  const refresh = () => {
    void client.invalidateQueries({ queryKey: ["job", selected] });
    void client.invalidateQueries({ queryKey: ["jobs"] });
  };
  function select(id: string) {
    selectedRef.current = id;
    setSelected(id);
    if (narrow) setLeft(false);
    setOlderMessages([]);
    setHistoryCursor(undefined);
    history.replaceState(null, "", `?job=${id}`);
  }
  const create = useMutation({
    mutationFn: () => command<Job>("/jobs"),
    onSuccess: (value) => {
      select(value.id);
      void client.invalidateQueries({ queryKey: ["jobs"] });
    },
    onError: (e) => setError(e.message),
  });
  const send = useMutation({
    mutationFn: async (text: string) => {
      const id = await ensureJob();
      return command(`/jobs/${id}/messages`, { text });
    },
    onSuccess: refresh,
    onError: (e) => setError(e.message),
  });
  const answer = useMutation({
    mutationFn: ({
      values,
      conflict,
    }: {
      values: Record<string, string>;
      conflict?: boolean;
    }) =>
      command(`/jobs/${selected}/${conflict ? "conflicts" : "answers"}`, {
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
    onSuccess: refresh,
    onError: (e) => setError(e.message),
  });
  const control = useMutation({
    mutationFn: (action: string) =>
      command(`/jobs/${selected}/control/${action}`),
    onSuccess: refresh,
    onError: (e) => setError(e.message),
  });
  useEffect(() => {
    if (!selected || !session.data) return;
    setEvents([]);
    setConnected(navigator.onLine);
    const source = new EventSource(`/api/v1/jobs/${selected}/events`);
    let timer: ReturnType<typeof setTimeout> | undefined;
    source.onmessage = (event) => {
      if (selectedRef.current !== selected) return;
      const update: ProgressEvent = JSON.parse(event.data);
      setEvents((previous) =>
        previous.some((e) => e.event_id === update.event_id)
          ? previous
          : [...previous, update].slice(-200),
      );
      if (!timer)
        timer = setTimeout(() => {
          void client.invalidateQueries({ queryKey: ["job", selected] });
          void client.invalidateQueries({ queryKey: ["jobs"] });
          timer = undefined;
        }, 100);
    };
    source.onopen = () => {
      setConnected(navigator.onLine);
      void client.invalidateQueries({ queryKey: ["job", selected] });
    };
    source.onerror = () => setConnected(false);
    return () => {
      source.close();
      clearTimeout(timer);
    };
  }, [selected, session.data, client, connectionEpoch]);
  async function ensureJob() {
    if (selectedRef.current) return selectedRef.current;
    const created = await command<Job>("/jobs");
    select(created.id);
    return created.id;
  }
  async function upload(files: File[]) {
    if (uploadLock.current) return;
    uploadLock.current = true;
    setUploading(true);
    setError("");
    try {
      const id = await ensureJob();
      for (const file of files) {
        const form = new FormData();
        form.append("file", file);
        form.append("request_id", requestId());
        await api(`/jobs/${id}/attachments`, { method: "POST", body: form });
      }
      refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      uploadLock.current = false;
      setUploading(false);
    }
  }
  const jobList = [
    ...new Map(
      (jobs.data?.pages.flat() || []).map((item) => [item.id, item]),
    ).values(),
  ];
  const messages = [
    ...new Map(
      [...olderMessages, ...(snapshot.data?.messages || [])].map((message) => [
        message.id,
        message,
      ]),
    ).values(),
  ].sort((a, b) => a.seq - b.seq);
  const attachments = (snapshot.data?.attachments || []).filter(
    (file) =>
      file.kind !== "stl" || !job?.active_stl || file.id === job.active_stl,
  );
  const filesReady =
    attachments.length > 0 &&
    attachments.every((file) => file.status === "completed");
  const lastUserId = messages.reduce(
    (last, message) => (message.role === "user" ? message.id : last),
    "",
  );
  const before =
    historyCursor === undefined ? snapshot.data?.message_cursor : historyCursor;
  async function loadHistory() {
    if (!before || loadingHistory) return;
    const id = selected;
    setLoadingHistory(true);
    try {
      const page = await api<Snapshot>(`/jobs/${id}?before=${before}`);
      if (selectedRef.current !== id) return;
      setOlderMessages((previous) => [...page.messages, ...previous]);
      setHistoryCursor(page.message_cursor);
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setLoadingHistory(false);
    }
  }
  const running =
    !!job && ["running", "queued", "stopping"].includes(job.status);
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
      <header className={styles.header}>
        <h1>StereotechAI Plugin</h1>
        {!connected && (
          <span className={styles.connectionHeader}>
            <img
              src="/figma/dot-error.svg"
              alt=""
              className={styles.statusDot}
              data-state="error"
            />
            Нет связи
          </span>
        )}
        {!left && (
          <button
            aria-label="Новое задание"
            disabled={!session.data || create.isPending}
            onClick={() => create.mutate()}
          >
            <img
              className={styles.mobileOnly}
              src="/figma/new-chat.svg"
              alt=""
            />
            <span className={styles.desktopOnly}>Новое задание</span>
          </button>
        )}
        <div className={styles.mobileTools}>
          <button
            className={styles.icon}
            aria-label="Открыть чаты"
            onClick={() => {
              setRight(false);
              setLeft(true);
            }}
          >
            <img src="/figma/collapse-left.svg" alt="" />
          </button>
          <button
            className={styles.icon}
            aria-label="Открыть карточку"
            onClick={() => {
              setLeft(false);
              setRight(true);
            }}
          >
            <img src="/figma/collapse-right.svg" alt="" />
          </button>
        </div>
      </header>
      {narrow && (left || right) && (
        <button
          className={styles.panelBackdrop}
          aria-label="Закрыть панель"
          onClick={() => {
            setLeft(false);
            setRight(false);
          }}
        />
      )}
      <div
        className={`${styles.workspace} ${!left ? styles.noLeft : ""} ${!right ? styles.noRight : ""}`}
      >
        {left ? (
          <aside className={styles.chats} aria-label="Чаты">
            <div className={styles.row}>
              <h2>Чаты</h2>
              <div className={styles.actions}>
                <button
                  className={styles.icon}
                  aria-label="Новое задание"
                  disabled={!session.data || create.isPending}
                  onClick={() => create.mutate()}
                >
                  <img src="/figma/new-chat.svg" alt="" />
                </button>
                <button
                  className={styles.icon}
                  aria-label="Свернуть чаты"
                  onClick={() => setLeft(false)}
                >
                  <img src="/figma/collapse-left.svg" alt="" />
                </button>
              </div>
            </div>
            <nav aria-label="Задания">
              {jobList.map((item) => (
                <button
                  className={item.id === selected ? styles.activeChat : ""}
                  key={item.id}
                  aria-label={`${item.title} ${statusLabel[item.status]}`}
                  title={item.title}
                  onClick={() => select(item.id)}
                >
                  <span>{item.title}</span>
                  <small>
                    {chatDate(item.updated_at, item.id === selected)}
                  </small>
                </button>
              ))}
            </nav>
            {jobs.hasNextPage && (
              <button
                onClick={() => jobs.fetchNextPage()}
                disabled={jobs.isFetchingNextPage}
              >
                Загрузить ещё чаты
              </button>
            )}
          </aside>
        ) : (
          <button className={styles.panelToggle} onClick={() => setLeft(true)}>
            Чаты
          </button>
        )}
        <main className={styles.chat}>
          {(error || snapshot.isError) && (
            <div className={styles.error} role="alert">
              {error || snapshot.error?.message}
              <button
                aria-label="Закрыть сообщение об ошибке"
                onClick={() => setError("")}
              >
                ×
              </button>
            </div>
          )}
          {capability.data && !capability.data.model_configured && (
            <p className={styles.warning}>Qwen пока не подключён к серверу</p>
          )}
          <div
            className={styles.thread}
            data-running={running && !!messages.length}
          >
            {!snapshot.data?.messages.length &&
              !snapshot.data?.attachments.length && (
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
            {before && (
              <button disabled={loadingHistory} onClick={loadHistory}>
                Предыдущие сообщения
              </button>
            )}
            {messages.map((message) => (
              <Fragment key={message.id}>
                <article
                  className={
                    message.role === "user"
                      ? styles.userMessage
                      : styles.agentMessage
                  }
                >
                  {message.role !== "user" && (
                    <span className={styles.avatar} aria-hidden="true">
                      M
                    </span>
                  )}
                  <p>{message.text}</p>
                </article>
                {filesReady && message.id === lastUserId && (
                  <Files
                    attachments={attachments}
                    jobId={selected}
                    pending={detach.isPending}
                    onRemove={(id) => detach.mutate(id)}
                  />
                )}
              </Fragment>
            ))}
            {(!filesReady || !lastUserId) && (
              <Files
                attachments={snapshot.data?.attachments || []}
                jobId={selected}
                pending={detach.isPending}
                onRemove={(id) => detach.mutate(id)}
              />
            )}
            {uploading && <p role="status">Загружаю файлы</p>}
            <Progress
              events={events.filter((e) => e.revision === job?.revision)}
              job={job}
              compact={job?.status === "waiting_user"}
            />
            {job?.error && (
              <section className={styles.technicalError} role="alert">
                <img src="/figma/error.svg" alt="" />
                <p>{job.error}</p>
                <button
                  disabled={control.isPending}
                  onClick={() => control.mutate("retry")}
                >
                  Повторить позже
                </button>
              </section>
            )}
            {job?.card && job.card.revision === job.revision && (
              <>
                <Questions
                  key={`questions-${job.revision}`}
                  questions={job.card.questions}
                  pending={answer.isPending}
                  onAnswer={(values) => answer.mutate({ values })}
                />
                {job.card.conflicts
                  .filter((c) => !c.resolved && c.resolution !== "Не знаю")
                  .map((c) => (
                    <Conflict
                      key={c.id + job.revision}
                      conflict={c}
                      pending={answer.isPending}
                      onResolve={(values) =>
                        answer.mutate({ values, conflict: true })
                      }
                    />
                  ))}
              </>
            )}
            {job?.status === "stopped" && (
              <button onClick={() => control.mutate("resume")}>
                Продолжить
              </button>
            )}
          </div>
          {connected &&
            running &&
            job?.card &&
            job.card.revision < job.revision && (
              <p className={styles.connectionNotice} role="status">
                <img src="/figma/run.svg" alt="" />
                Пересчитываю проверки
              </p>
            )}
          {!connected && (
            <p className={styles.connectionNotice} role="status">
              <img src="/figma/run.svg" alt="" />
              Соединение потеряно, переподключаемся
            </p>
          )}
          {
            <Composer
              onSend={(text) => send.mutateAsync(text)}
              onFiles={upload}
              onStop={() => control.mutate("stop")}
              pending={
                send.isPending || create.isPending || uploading || !session.data
              }
              running={running}
              placeholder={composerPlaceholder(
                job,
                connected,
                snapshot.data?.attachments || [],
              )}
            />
          }
        </main>
        {right ? (
          <TaskCard
            job={job}
            events={events.filter((e) => e.revision === job?.revision)}
            onEdit={() => document.getElementById("message")?.focus()}
            onStop={() => control.mutate("stop")}
            onCollapse={() => setRight(false)}
          />
        ) : (
          <button className={styles.panelToggle} onClick={() => setRight(true)}>
            Карточка
          </button>
        )}
      </div>
    </div>
  );
}

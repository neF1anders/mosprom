import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { usePanelFocus } from "./usePanelFocus";
import { api, ApiError, authenticate, command, requestId } from "./api";
import type {
  Attachment,
  Job,
  Message,
  ProgressEvent,
  Snapshot,
} from "./types";
import { answered, statusLabel } from "./types";
import { Composer } from "./components/Composer";
import { ChatItem } from "./components/ChatItem";
import type { DraftFile } from "./components/Attachments";
import { forget } from "./preview";
import { Questions } from "./components/Questions";
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
  if (job?.files_changed) return "Напишите сообщение или отправьте файлы";
  if (attachments.some((file) => file.status === "failed"))
    return "Приложите другой файл или напишите сообщение…";
  if (job?.status === "completed") return "Написать правку или вопрос…";
  if (job?.status === "waiting_user")
    return job.card?.questions.some((question) => !answered(question))
      ? "Или ответьте текстом…"
      : "Можно написать сообщение…";
  if (job?.status === "running" || job?.status === "queued")
    return "Можно написать сообщение, я отвечу после текущего шага";
  return "Напишите, что нужно напечатать…";
}
// Mirrors KINDS and the upper InputLimits on the server, which may be configured lower.
const LIMITS_MIB: Record<string, number> = {
  stl: 256,
  pdf: 25,
  docx: 25,
  txt: 25,
  md: 25,
  png: 20,
  jpg: 20,
  jpeg: 20,
};
const CAD = new Set(["step", "stp", "iges", "igs", "obj", "3mf", "ply", "f3d"]);
function rejected(file: File, kind: string) {
  if (!(kind in LIMITS_MIB))
    return CAD.has(kind)
      ? "Формат не поддерживается, приложите STL"
      : "Формат не поддерживается";
  if (file.size > LIMITS_MIB[kind] * 1024 * 1024)
    return `Файл больше ${LIMITS_MIB[kind]} МБ`;
}
// Answers are stored as "question, answer" lines; known titles split them unambiguously.
function answerPairs(text: string, job: Job | undefined) {
  const titles = Object.values(job?.answers || {})
    .map((answer) => answer.title)
    .sort((a, b) => b.length - a.length);
  return text.split("\n").map((line) => {
    const title = titles.find((t) => line.startsWith(`${t}, `));
    if (title) return { question: title, answer: line.slice(title.length + 2) };
    const cut = line.lastIndexOf(", ");
    return cut < 0
      ? { question: "", answer: line }
      : { question: line.slice(0, cut), answer: line.slice(cut + 2) };
  });
}
function extension(name: string) {
  return name.includes(".") ? name.split(".").pop()!.toLowerCase() : "";
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
  const [error, setError] = useState("");
  // Files still uploading or rejected before reaching the server; they live only here.
  const [uploads, setUploads] = useState<DraftFile[]>([]);
  // Picked files by attachment id, so previews need no download; also keeps card order.
  const picked = useRef(new Map<string, File>());
  const creating = useRef<Promise<string> | null>(null);
  const threadRef = useRef<HTMLDivElement>(null);
  const following = useRef(true);
  const [away, setAway] = useState(false);
  const toBottom = useCallback((behavior: ScrollBehavior = "auto") => {
    following.current = true;
    const element = threadRef.current;
    element?.scrollTo({ top: element.scrollHeight, behavior });
  }, []);
  useEffect(() => {
    const element = threadRef.current;
    if (!element) return;
    // New messages, progress and expanded details keep the newest content in view.
    const observer = new MutationObserver(() => {
      if (following.current) element.scrollTop = element.scrollHeight;
    });
    observer.observe(element, {
      childList: true,
      subtree: true,
      characterData: true,
      attributes: true,
      attributeFilter: ["open"],
    });
    return () => observer.disconnect();
  }, []);
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
    following.current = true;
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
      setUploads([]);
      select(value.id);
      void client.invalidateQueries({ queryKey: ["jobs"] });
    },
    onError: (e) => setError(e.message),
  });
  const send = useMutation({
    mutationFn: async (text: string) => {
      const id = await ensureJob();
      return text
        ? command(`/jobs/${id}/messages`, { text })
        : command(`/jobs/${id}/control/retry`);
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
      if (id === selectedRef.current) {
        selectedRef.current = "";
        setSelected("");
        setUploads([]);
        history.replaceState(null, "", location.pathname);
      }
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
  async function upload(files: File[]) {
    setError("");
    const queued = files.map((file) => {
      const kind = extension(file.name);
      const problem = rejected(file, kind);
      return {
        file,
        card: {
          key: requestId(),
          name: file.name,
          kind,
          uploading: !problem,
          error: problem,
        },
      };
    });
    setUploads((list) => [...list, ...queued.map(({ card }) => card)]);
    for (const { file, card } of queued) {
      if (card.error) continue;
      try {
        const id = await ensureJob();
        const form = new FormData();
        form.append("file", file);
        form.append("request_id", card.key);
        const attachment = await api<Attachment>(`/jobs/${id}/attachments`, {
          method: "POST",
          body: form,
        });
        picked.current.set(attachment.id, file);
        // The card swaps to the server copy only once the snapshot holds it, without a gap.
        await client
          .fetchQuery({
            queryKey: ["job", id],
            queryFn: () => api<Snapshot>(`/jobs/${id}`),
          })
          .catch(() => undefined);
        setUploads((list) => list.filter((item) => item.key !== card.key));
        void client.invalidateQueries({ queryKey: ["jobs"] });
      } catch (e) {
        const message =
          e instanceof ApiError ? e.message : "Не удалось загрузить файл";
        setUploads((list) =>
          list.map((item) =>
            item.key === card.key
              ? { ...item, uploading: false, error: message }
              : item,
          ),
        );
      }
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
  // Unsent files wait in the composer; the thread shows only what was sent.
  const sent = (snapshot.data?.attachments || []).filter((file) => !file.draft);
  const order = [...picked.current.keys()];
  const drafts: DraftFile[] = [
    ...(snapshot.data?.attachments || [])
      .filter((file) => file.draft)
      .sort((a, b) => order.indexOf(a.id) - order.indexOf(b.id))
      .map((file) => ({
        key: file.id,
        name: file.filename,
        kind: file.kind,
        load: async () => {
          const local = picked.current.get(file.id);
          if (local) return local;
          const response = await fetch(
            `/api/v1/jobs/${selected}/artifacts/${file.id}`,
            { credentials: "same-origin" },
          );
          if (!response.ok) throw new Error(response.statusText);
          return response.blob();
        },
      })),
    ...uploads,
  ];
  const attachments = sent.filter(
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
        <div className={styles.side} data-open={left}>
          <aside className={styles.chats} aria-label="Чаты" inert={!left}>
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
                <ChatItem
                  key={item.id}
                  item={item}
                  active={item.id === selected}
                  label={`${item.title} ${statusLabel[item.status]}`}
                  date={chatDate(item.updated_at, item.id === selected)}
                  onOpen={() => {
                    setUploads([]);
                    select(item.id);
                  }}
                  onRename={(title) => rename.mutate({ id: item.id, title })}
                  onDelete={() => remove.mutate(item.id)}
                />
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
          <button
            className={styles.panelToggle}
            inert={left}
            onClick={() => setLeft(true)}
          >
            Чаты
          </button>
        </div>
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
          <div className={styles.threadArea}>
            <div
              ref={threadRef}
              className={styles.thread}
              data-running={running && !!messages.length}
              onScroll={(event) => {
                const element = event.currentTarget;
                const near =
                  element.scrollHeight -
                    element.scrollTop -
                    element.clientHeight <
                  80;
                following.current = near;
                setAway(!near);
              }}
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
                  {filesReady && message.id === lastUserId && (
                    <Files
                      attachments={attachments}
                      jobId={selected}
                      running={running}
                      pending={detach.isPending}
                      onRemove={(id) => detach.mutate(id)}
                    />
                  )}
                </Fragment>
              ))}
              {(!filesReady || !lastUserId) && (
                <Files
                  attachments={sent}
                  jobId={selected}
                  running={running}
                  pending={detach.isPending}
                  onRemove={(id) => detach.mutate(id)}
                />
              )}
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
              {job?.card &&
                job.card.revision === job.revision &&
                // Early questions are answered while the deep reading still runs.
                (!running || job.card.questions.some((q) => !answered(q))) && (
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
              <img src="/figma/arrow-down.svg" alt="" />
            </button>
          </div>
          {connected &&
            running &&
            job?.card &&
            job.card.revision < job.revision && (
              <p className={styles.connectionNotice} role="status">
                <img src="/figma/run.svg" alt="" />
                Обновляю карточку с учётом изменений
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
              onSend={(text) => {
                toBottom("smooth");
                return send.mutateAsync(text);
              }}
              onFiles={upload}
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
              files={drafts}
              filesChanged={!!job?.files_changed}
              placeholder={composerPlaceholder(job, connected, sent)}
            />
          }
        </main>
        <div className={styles.side} data-open={right}>
          <TaskCard
            job={job}
            events={events.filter((e) => e.revision === job?.revision)}
            collapsed={!right}
            onCollapse={() => setRight(false)}
          />
          <button
            className={styles.panelToggle}
            inert={right}
            onClick={() => setRight(true)}
          >
            Карточка
          </button>
        </div>
      </div>
    </div>
  );
}

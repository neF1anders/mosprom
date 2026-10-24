import { defectLabels, modelSize, plural } from "./format";
import type { Attachment, Geometry, Job, ProgressEvent } from "./types";
import { isRunning } from "./types";

export type StageState = "done" | "run" | "warn" | "error" | "wait";
export type ActionKind = "file" | "search" | "terminal" | "edit" | "help";
export interface Action {
  id: string;
  kind: ActionKind;
  state: "done" | "run" | "error";
  text: string;
  // What a click opens under the row: the command, then its output, as on Figma screen 17.
  command?: string;
  output?: string[];
  agent?: string;
}
export interface Thought {
  at: number;
  text: string;
}
export interface AgentRun {
  id: string;
  agent: string;
  title: string;
  icon: string;
  state: "run" | "done" | "error";
  started: number;
  finished?: number;
  thoughts: Thought[];
  actions: Action[];
  // A step of code shown among the agents, like the STL analysis: no reasoning of its own.
  code?: boolean;
}
export interface Stage {
  key: string;
  title: string;
  state: StageState;
  meta: { text: string; tone: "run" | "muted" | "warn" | "error" } | null;
  summary: string;
  actions: Action[];
  agents: AgentRun[];
  started?: number;
  finished?: number;
  result?: "card" | "parameters" | "project";
}
// The reasoning of one model call as it arrived; a retry starts it over.
export interface CallThoughts {
  agent: string;
  attempt: number;
  chunks: Thought[];
}

const AGENTS: Record<string, { title: string; icon: string }> = {
  interpreter: { title: "Интерпретатор ТЗ", icon: "file-search" },
  checker: { title: "Проверка карточки", icon: "list-checks" },
  steer: { title: "Корректировка", icon: "redirect" },
};
// The gate only talks in the chat, so it gets no card of its own.
const HIDDEN_AGENTS = new Set(["gate"]);
export function agentLook(agent: string, title = "") {
  return AGENTS[agent] || { title: title || agent, icon: "file-search" };
}
const STAGE_ONE = /^(files|stl|interpretation|checking|tool|agent|stage1)\./;
const LATER = [
  { key: "parameters", title: "Подбор параметров", prefix: "parameters." },
  { key: "validation", title: "Валидация", prefix: "validation." },
  { key: "slicing", title: "Слайсинг", prefix: "slicing." },
  { key: "gcode", title: "Подготовка результата", prefix: "gcode." },
];

function time(event?: ProgressEvent) {
  return event?.created_at ? Date.parse(event.created_at) : undefined;
}
function last(events: ProgressEvent[], test: (e: ProgressEvent) => boolean) {
  for (let index = events.length - 1; index >= 0; index--)
    if (test(events[index])) return events[index];
}
export function seconds(ms: number) {
  return `${Math.max(0, Math.round(ms / 1000))} с`;
}
// A stopped or failed run ends its open steps; a running one keeps them going.
function halted(job?: Job): StageState | undefined {
  if (!job || isRunning(job)) return undefined;
  if (job.status === "failed") return "error";
  return job.status === "stopped" ? "wait" : undefined;
}
function stateOf(event?: ProgressEvent): StageState {
  if (!event) return "wait";
  if (event.status === "failed") return "error";
  if (event.status === "warning") return "warn";
  return event.status === "completed" ? "done" : "run";
}
function geometryOutput(
  name: string,
  geometry?: Geometry & { volume?: number },
) {
  if (!geometry) return undefined;
  const lines = [`габариты ${modelSize(geometry)}`];
  if (geometry.volume)
    lines.push(
      `объём ${String(Number((geometry.volume / 1000).toFixed(1))).replace(".", ",")} см3`,
    );
  if (geometry.defects.length)
    lines.push(
      `дефекты ${geometry.defects.map((d) => defectLabels[d] || d).join(", ")}`,
    );
  return { command: `$ stl ${name}`, output: lines };
}
function count(message: string) {
  return Number(message.match(/\d+/)?.[0] || 0);
}

// Rows of the first stage, built from the events the server already sends.
function stageOneActions(
  events: ProgressEvent[],
  job: Job | undefined,
  attachments: Attachment[],
): Action[] {
  const actions: Action[] = [];
  const stl =
    attachments.find((file) => file.id === job?.active_stl)?.filename ||
    "модели";
  const tools = new Map<string, Action>();
  for (const event of events) {
    const id = String(event.event_id);
    const data = event.data as Record<string, unknown>;
    if (event.type === "files.started")
      actions.push({ id, kind: "file", state: "run", text: "Читаю файлы" });
    if (event.type === "files.completed" || event.type === "files.failed") {
      const failed = (data.failed as string[] | undefined) || [];
      const read = attachments.filter(
        (file) => file.kind !== "stl" && !failed.includes(file.filename),
      );
      actions.splice(
        0,
        actions.length,
        ...actions.filter((a) => a.text !== "Читаю файлы"),
      );
      for (const file of read)
        actions.push({
          id: `${id}:${file.id}`,
          kind: "file",
          state: "done",
          text: `Прочитал ${file.filename}`,
        });
      for (const name of failed)
        actions.push({
          id: `${id}:${name}`,
          kind: "file",
          state: "error",
          text: `Не прочитал ${name}`,
        });
    }
    if (event.type === "stl.started")
      actions.push({
        id: "stl",
        kind: "terminal",
        state: "run",
        text: `Разбираю ${stl}`,
      });
    if (event.type === "stl.completed" || event.type === "stl.failed") {
      const row = actions.find((a) => a.id === "stl");
      const done: Action = {
        id: "stl",
        kind: "terminal",
        state: event.type === "stl.failed" ? "error" : "done",
        text:
          event.type === "stl.failed"
            ? `Не удалось разобрать ${stl}`
            : `Запустил разбор ${stl}`,
        ...geometryOutput(stl, data.geometry as Geometry | undefined),
      };
      if (row) Object.assign(row, done);
      else actions.push(done);
    }
    if (event.type === "interpretation.started")
      actions.push({
        id: "interpretation",
        kind: "search",
        state: "run",
        text: "Читаю задание",
      });
    if (event.type === "interpretation.completed") {
      const found = count(event.message);
      const rest = actions.filter((a) => a.id !== "interpretation");
      actions.splice(0, actions.length, ...rest);
      if (found)
        actions.push({
          id,
          kind: "search",
          state: "done",
          text: `Нашёл в ТЗ ${found} ${plural(found, ["требование", "требования", "требований"])}`,
        });
    }
    if (event.type === "tool.called") {
      const action = toolAction(id, data);
      tools.set(String(data.call || id) + data.tool, action);
      actions.push(action);
    }
    if (event.type === "tool.finished") {
      const action = tools.get(String(data.call || "") + data.tool);
      if (action) {
        action.state = event.status === "warning" ? "error" : "done";
        action.text = action.text
          .replace(/^Перевожу/, "Перевёл")
          .replace(/^Смотрю/, "Посмотрел");
        action.output = [String(data.result_preview || "")];
      }
    }
    if (event.type === "checking.started")
      actions.push({
        id: "checking",
        kind: "search",
        state: "run",
        text: event.message.startsWith("Учитываю")
          ? event.message
          : "Сверяю карточку с ТЗ и моделью",
      });
    if (event.type === "checking.completed") {
      const row = actions.find((a) => a.id === "checking");
      const done: Action = {
        id: "checking",
        kind: "search",
        state: "done",
        text: event.message,
      };
      if (row) Object.assign(row, done);
      else actions.push(done);
    }
  }
  const answers = Object.keys(job?.answers || {}).length;
  if (answers && events.some((e) => e.type === "stage1.completed"))
    actions.push({
      id: "answers",
      kind: "help",
      state: "done",
      text: `Вы ответили на ${answers} ${plural(answers, ["вопрос", "вопроса", "вопросов"])}`,
    });
  if (job?.card && events.some((e) => e.type === "stage1.completed"))
    actions.push({
      id: "card",
      kind: "edit",
      state: "done",
      text:
        job.card.revision > 1
          ? "Обновил карточку задания"
          : "Записал карточку задания",
    });
  return actions;
}
function toolAction(id: string, data: Record<string, unknown>): Action {
  const args = (data.arguments || {}) as Record<string, unknown>;
  if (data.tool === "convert_units")
    return {
      id,
      kind: "terminal",
      state: "run",
      agent: String(data.agent || ""),
      text: `Перевожу ${args.value ?? ""} ${args.from_unit ?? ""} в ${args.to_unit ?? ""}`.replace(
        /\s+/g,
        " ",
      ),
      command: `$ convert ${args.value ?? ""} ${args.from_unit ?? ""} ${args.to_unit ?? ""}`,
    };
  return {
    id,
    kind: "file",
    state: "run",
    agent: String(data.agent || ""),
    text: "Смотрю страницу крупнее",
  };
}

// Agents of a stage, one per run of an agent; a call is one model step of it.
function agentRuns(
  events: ProgressEvent[],
  thoughts: Record<string, CallThoughts>,
  actions: Action[],
): AgentRun[] {
  const runs = new Map<string, AgentRun>();
  for (const event of events) {
    if (!event.type.startsWith("agent.") || event.type === "agent.dropped")
      continue;
    const data = event.data as Record<string, unknown>;
    const agent = String(data.agent || "");
    const call = String(data.call || "");
    if (HIDDEN_AGENTS.has(agent) || !call) continue;
    const id = call.slice(0, call.lastIndexOf(":"));
    const look = agentLook(agent, String(data.title || ""));
    const at = time(event) ?? 0;
    const run =
      runs.get(id) ||
      ({
        id,
        agent,
        title: look.title,
        icon: look.icon,
        state: "run",
        started: at,
        thoughts: [],
        actions: [],
      } as AgentRun);
    runs.set(id, run);
    if (event.type === "agent.started") run.state = "run";
    if (event.type === "agent.finished") {
      run.state = event.status === "failed" ? "error" : "done";
      run.finished = at;
    }
  }
  for (const run of runs.values()) {
    const calls = Object.entries(thoughts)
      .filter(([call]) => call.startsWith(`${run.id}:`))
      .sort(([a], [b]) => step(a) - step(b));
    run.thoughts = paragraphs(calls.flatMap(([, call]) => call.chunks));
    run.actions = actions.filter((a) => a.agent === run.agent);
  }
  return [...runs.values()];
}
function step(call: string) {
  return Number(call.slice(call.lastIndexOf(":") + 1));
}
// Reasoning split into paragraphs, each stamped with the time its first piece came.
export function paragraphs(chunks: Thought[]): Thought[] {
  const result: Thought[] = [];
  let open = false;
  for (const chunk of chunks) {
    const parts = chunk.text.split(/\n\s*\n/);
    parts.forEach((part, index) => {
      if (index > 0) open = false;
      if (!part.trim()) return;
      if (open) result[result.length - 1].text += part;
      else result.push({ at: chunk.at, text: part.replace(/^\s+/, "") });
      open = true;
    });
  }
  return result;
}
function stlRun(events: ProgressEvent[]): AgentRun | undefined {
  const start = last(events, (e) => e.type === "stl.started");
  const end = last(events, (e) =>
    ["stl.completed", "stl.failed"].includes(e.type),
  );
  if (!start || !end || time(start) === undefined) return undefined;
  return {
    id: "stl",
    agent: "stl",
    title: "Анализатор STL",
    icon: "scan-search",
    state: end.type === "stl.failed" ? "error" : "done",
    started: time(start)!,
    finished: time(end),
    thoughts: [],
    actions: [],
    code: true,
  };
}
function meta(
  state: StageState,
  started: number | undefined,
  finished: number | undefined,
  now: number,
  connected: boolean,
): Stage["meta"] {
  if (state === "error") return { text: "остановлен", tone: "error" };
  if (state === "run" && !connected)
    return { text: "ждёт связь", tone: "muted" };
  if (state === "run" && started !== undefined)
    return { text: `работает ${seconds(now - started)}`, tone: "run" };
  if ((state === "done" || state === "warn") && started && finished)
    return { text: seconds(finished - started), tone: "muted" };
  return null;
}

function stageOne(
  events: ProgressEvent[],
  job: Job | undefined,
  attachments: Attachment[],
  thoughts: Record<string, CallThoughts>,
  now: number,
  connected: boolean,
): Stage {
  const own = events.filter((e) => STAGE_ONE.test(e.type));
  const finishedEvent = last(own, (e) => e.type === "stage1.completed");
  const ended = halted(job);
  const asking =
    job?.status === "waiting_user" &&
    !!job.card?.questions.some((q) => !q.answer);
  let state: StageState = finishedEvent ? "done" : ended || "run";
  if (asking) state = "warn";
  const actions = stageOneActions(own, job, attachments);
  // A finished stage has no row left running, whatever events were missed.
  if (finishedEvent)
    actions.filter((a) => a.state === "run").forEach((a) => (a.state = "done"));
  if (ended === "error") {
    const open = [...actions].reverse().find((a) => a.state === "run");
    if (open) open.state = "error";
  }
  const agents = agentRuns(own, thoughts, actions);
  const stl = stlRun(own);
  const started = time(own[0]);
  const finished = time(finishedEvent);
  const running = agents.filter((a) => a.state === "run");
  const stage: Stage = {
    key: "understanding",
    title: "Интерпретация задания",
    state,
    meta: asking
      ? { text: "ждёт ответа", tone: "warn" }
      : meta(state, started, finished, now, connected),
    summary: "",
    // Rows of an agent at work are in its card until it finishes.
    actions: actions.filter(
      (a) => !running.some((agent) => agent.agent === a.agent),
    ),
    agents: stl ? [stl, ...agents] : agents,
    started,
    finished,
    result: state === "done" && job?.card ? "card" : undefined,
  };
  if (state === "error") stage.summary = job?.error || "";
  else if (finishedEvent) stage.summary = finishedEvent.message;
  return stage;
}
function laterStage(
  definition: (typeof LATER)[number],
  events: ProgressEvent[],
  job: Job | undefined,
  now: number,
  connected: boolean,
): Stage {
  const passes = events.filter((e) => e.type.startsWith(definition.prefix));
  const ended = halted(job);
  const found = stateOf(passes[passes.length - 1]);
  let state = found === "run" && ended ? ended : found;
  const summary = job?.parameters;
  const unmet = !!summary?.unsatisfied || summary?.status === "infeasible";
  if (definition.key === "parameters" && unmet && state === "done")
    state = "warn";
  const completed = last(passes, (e) => e.type.endsWith(".completed"));
  const started = time(passes[0]);
  const finished = time(completed);
  const done = job?.stage === "done";
  let result: Stage["result"];
  if (done && definition.key === "parameters" && job?.parameters)
    result = "parameters";
  if (done && definition.key === "gcode" && job?.result?.sliced)
    result = "project";
  return {
    key: definition.key,
    title: definition.title,
    state,
    meta: meta(state, started, finished, now, connected),
    summary: passes.length
      ? completed?.message || ""
      : waitingText(definition.prefix, job),
    actions: passes.map((event) => passAction(definition.key, event)),
    agents: [],
    started,
    finished,
    result,
  };
}
const PASS_TEXT: Record<string, [string, string, ActionKind]> = {
  parameters: ["Подбираю параметры", "Подобрал параметры", "terminal"],
  validation: [
    "Проверяю набор параметров",
    "Проверил набор параметров",
    "search",
  ],
  slicing: ["Нарезаю в STE Slicer", "Нарезал в STE Slicer", "terminal"],
  gcode: ["Проверяю G-code", "Проверил G-code", "search"],
};
function passAction(key: string, event: ProgressEvent): Action {
  const [running, done, kind] = PASS_TEXT[key];
  const iteration = Number(event.data.iteration || 1);
  const pass = iteration > 1 ? `, заход ${iteration}` : "";
  if (!event.type.endsWith(".completed"))
    return {
      id: String(event.event_id),
      kind,
      state: "run",
      text: `${running}${pass}`,
    };
  return {
    id: String(event.event_id),
    kind,
    state: event.status === "failed" ? "error" : "done",
    text: `${done}${pass}`,
    output: event.message ? [event.message] : undefined,
  };
}
function waitingText(prefix: string, job?: Job) {
  if (prefix === "parameters." && job?.stage === "parameters")
    return "Задание передано, ждёт подбора параметров";
  if (job?.stage !== "done") return "";
  // Without a project there is no G-code to check.
  if (prefix === "gcode." && job.result && !job.result.sliced)
    return "Не проводилась, проект не создан";
  // An infeasible selection is not checked: nothing in it can be printed as it is.
  return "Не проводилась, параметры подобрать не удалось";
}
// The five stages of the work, Figma screens 03–12 and 16–20.
export function buildTimeline({
  events,
  job,
  attachments = [],
  thoughts = {},
  now = Date.now(),
  connected = true,
}: {
  events: ProgressEvent[];
  job?: Job;
  attachments?: Attachment[];
  thoughts?: Record<string, CallThoughts>;
  now?: number;
  connected?: boolean;
}): Stage[] | null {
  const work = events.filter(
    (e) =>
      STAGE_ONE.test(e.type) || LATER.some((s) => e.type.startsWith(s.prefix)),
  );
  // Agent events alone mean a chat reply of the gate, not work.
  if (
    !work.some(
      (e) => !e.type.startsWith("agent.") && e.type !== "stage1.completed",
    )
  )
    return null;
  const stages = [
    stageOne(work, job, attachments, thoughts, now, connected),
    ...LATER.map((definition) =>
      laterStage(definition, work, job, now, connected),
    ),
  ];
  return stages;
}
const THOUGHT_LIMIT = 20000;
// One piece of reasoning added to its call; a new attempt of the call starts the text over.
export function addThought(
  store: Record<string, CallThoughts>,
  event: ProgressEvent,
): Record<string, CallThoughts> {
  const data = event.data as Record<string, unknown>;
  const call = String(data.call || "");
  if (!call) return store;
  const attempt = Number(data.attempt || 1);
  const previous = store[call];
  // A piece of an attempt already replaced, such as a late translation, is dropped.
  if (previous && attempt < previous.attempt) return store;
  const chunks =
    previous && previous.attempt === attempt ? [...previous.chunks] : [];
  chunks.push({ at: time(event) ?? Date.now(), text: String(data.text || "") });
  let size = chunks.reduce((total, chunk) => total + chunk.text.length, 0);
  while (size > THOUGHT_LIMIT && chunks.length > 1)
    size -= chunks.shift()!.text.length;
  return {
    ...store,
    [call]: { agent: String(data.agent || ""), attempt, chunks },
  };
}
// Texts the timeline already shows as a stage summary are not repeated in the chat.
export function summaries(stages: Stage[] | null) {
  return new Set((stages || []).map((stage) => stage.summary).filter(Boolean));
}

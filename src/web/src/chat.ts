import type { Attachment, Job, Message, ProgressEvent } from "./types";
import { answered } from "./types";

export function chatDate(timestamp: string, selected: boolean) {
  if (selected) return "Сейчас";
  const date = new Date(timestamp);
  const yesterday = new Date();
  yesterday.setDate(yesterday.getDate() - 1);
  if (date.toDateString() === yesterday.toDateString()) return "Вчера";
  return date
    .toLocaleDateString("ru-RU", { day: "numeric", month: "short" })
    .replace(".", "");
}
export function composerPlaceholder(
  job: Job | undefined,
  connected: boolean,
  attachments: Attachment[],
) {
  if (!connected) return "Сообщение отправится после переподключения";
  if (job?.error) return "Или напишите сообщение…";
  if (job?.files_changed) return "Напишите сообщение или отправьте файлы";
  if (attachments.some((file) => file.status === "failed"))
    return "Приложите другой файл или напишите сообщение…";
  if (job?.status === "completed") return "Написать правку или вопрос…";
  if (job?.status === "waiting_user")
    return job.card?.questions.some((question) => !answered(question))
      ? "Написать сообщение…"
      : "Можно написать сообщение…";
  if (job?.status === "running" || job?.status === "queued")
    return "Можно написать сообщение, я отвечу после текущего шага";
  return "Напишите, что нужно напечатать…";
}
// Questions come with the finished card; the window shows only while the job waits for them.
export function asksQuestions(job?: Job | null) {
  return job?.status === "waiting_user" && job.card?.revision === job.revision;
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
// A file the server would refuse is rejected before it is sent.
export function rejected(file: File, kind: string) {
  if (!(kind in LIMITS_MIB))
    return CAD.has(kind)
      ? "Формат не поддерживается, приложите STL"
      : "Формат не поддерживается";
  if (file.size > LIMITS_MIB[kind] * 1024 * 1024)
    return `Файл больше ${LIMITS_MIB[kind]} МБ`;
}
export function extension(name: string) {
  return name.includes(".") ? name.split(".").pop()!.toLowerCase() : "";
}
// Answers are stored as "question, answer" lines; known titles split them unambiguously.
export function answerPairs(text: string, job: Job | undefined) {
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
// Messages sent before the work began come before the timeline, the rest after it.
export function splitAt(
  messages: Message[],
  start: string | undefined,
): [Message[], Message[]] {
  if (!start) return [messages, []];
  const from = Date.parse(start);
  const later = (message: Message) =>
    !!message.created_at && Date.parse(message.created_at) >= from;
  return [messages.filter((m) => !later(m)), messages.filter(later)];
}
const CHAT_AGENTS = new Set(["assistant", "analyst", "report"]);
// The assistant is answering: the last message waits for its reply, or one of its calls runs.
export function answering(
  events: ProgressEvent[],
  messages: Message[],
  running: boolean,
): boolean {
  const last = messages.at(-1);
  if (!running && last?.role === "user" && (last.kind ?? "chat") === "chat")
    return true;
  const open = new Set<string>();
  for (const event of events) {
    const data = event.data as { agent?: string; call?: string };
    if (!CHAT_AGENTS.has(data.agent || "") || !data.call) continue;
    if (event.type === "agent.started") open.add(data.call);
    if (event.type === "agent.finished") open.delete(data.call);
  }
  return open.size > 0;
}

import type { Attachment, Job } from "./types";
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

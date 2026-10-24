export interface Evidence {
  source_id: string;
  quote: string;
  page: number | null;
  method?: "text" | "vision" | "user" | "knowledge" | null;
  artifact_id?: string | null;
}
export interface Superseded {
  value: string;
  unit: string | null;
  reason: string;
}
export interface Requirement {
  key: string;
  label: string;
  value: string;
  unit: string | null;
  conditions: string;
  mandatory: boolean;
  verified: boolean;
  provenance: string;
  sources: Evidence[];
  superseded: Superseded[];
}
export interface Question {
  id: string;
  kind: "units" | "purpose" | "clarify" | "verify" | "discrepancy";
  title: string;
  impact: string;
  options: string[];
  suggested: string | null;
  basis: string | null;
  sources: Evidence[];
  blocking: boolean;
  answer: string | null;
}
export interface Geometry {
  readable: boolean;
  units: string;
  extents: number[];
  defects: string[];
  limitations: string[];
  report_id: string | null;
  preview_id: string | null;
}
export interface Assumption {
  text: string;
  basis: string;
  consequence: string;
}
export interface Remark {
  severity: "critical" | "major" | "minor";
  text: string;
}
export interface Card {
  schema_version: string;
  job_id: string;
  revision: number;
  purpose: string;
  requirements: Requirement[];
  preferences: string[];
  production_constraints: string[];
  assumptions: Assumption[];
  unknowns: string[];
  questions: Question[];
  geometry: Geometry | null;
  verdict: { score: number; passed: boolean; remarks: Remark[] } | null;
  readiness: "ready" | "preliminary" | "blocked";
  allowed_actions: string[];
  blocked_actions: Record<string, string[]>;
}
export interface Job {
  active_stl?: string | null;
  id: string;
  title: string;
  revision: number;
  status: string;
  card: Card | null;
  error: string | null;
  files_changed: boolean;
  answers?: Record<string, { title: string; value: string }>;
  next_stage: "not_ready" | "queued";
  created_at: string;
  updated_at: string;
}
export interface Attachment {
  id: string;
  // Not sent yet: the file waits in the composer.
  draft?: boolean;
  filename: string;
  kind: string;
  status: string;
  error: string | null;
  artifacts: string[];
}
export interface Message {
  id: string;
  seq: number;
  role: string;
  kind?: "chat" | "answers" | "offtopic";
  text: string;
  revision: number;
}
export interface Snapshot {
  job: Job;
  messages: Message[];
  attachments: Attachment[];
  message_cursor: number | null;
}
export interface ProgressEvent {
  event_id: number;
  revision: number;
  type: string;
  message: string;
  status: string;
  data: Record<string, unknown>;
}
export const statusLabel: Record<string, string> = {
  draft: "Ожидаю материалы",
  queued: "В очереди",
  running: "Обрабатываю",
  waiting_user: "Нужны уточнения",
  failed: "Ошибка обработки",
  stopping: "Останавливаем",
  stopped: "Остановлено",
  completed: "Первый этап завершён",
  pending: "Ждёт отправки",
};
// The server stores every way of saying "unknown" as this one value.
export const UNKNOWN_ANSWER = "Не знаю";
export function answered(question: Question) {
  return !!question.answer?.trim() && question.answer !== UNKNOWN_ANSWER;
}
const ACTIVE = new Set(["running", "queued", "stopping"]);
export function isRunning(job?: Job | null) {
  return !!job && ACTIVE.has(job.status);
}

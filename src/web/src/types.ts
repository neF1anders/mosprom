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
  // Between stages the job is queued; it completes after the last one.
  stage:
    | "understanding"
    | "parameters"
    | "validation"
    | "slicing"
    | "gcode"
    | "done";
  // The revision whose work the card, the timeline and the results come from.
  work_revision: number;
  parameters: ParametersSummary | null;
  // The last slicing of the current pass, once STE Slicer was asked.
  result?: ResultSummary | null;
  // How the finished pipeline ended, as the server decided it.
  outcome: "ready" | "attention" | "parameters_attention" | "not_sliced" | null;
  created_at: string;
  updated_at: string;
}
export interface ParametersSummary {
  iteration: number;
  printing_mode: string;
  quality_type: string;
  material: string;
  changed_settings: number;
  unsatisfied: number;
  status: "proposed" | "infeasible";
  check: "pending" | "ok" | "attention";
}
export interface ResultSummary {
  iteration: number;
  sliced: boolean;
  message: string;
  gcode_check: "pending" | "ok" | "attention";
  folder: string | null;
  print_time_seconds: number | null;
  material_grams: number | null;
  material_meters: number | null;
}
interface Reasoned {
  why: string;
  source: string;
}
export interface ParameterSet {
  iteration: number;
  settings: Record<
    string,
    Reasoned & { value: string | number | boolean | unknown[]; unit?: string }
  >;
  unsatisfied: { requirement_id: string; why: string }[];
  assumptions: { id: string; text: string; basis: string }[];
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
  // A gate reply asks for details before the work starts; offtopic marks older rows.
  kind?: "chat" | "answers" | "gate" | "offtopic";
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
  completed: "Параметры подобраны",
  pending: "Ждёт отправки",
};
// The server stores every way of saying "unknown" as this one value.
export const UNKNOWN_ANSWER = "Не знаю";
export function answered(question: Question) {
  return !!question.answer?.trim() && question.answer !== UNKNOWN_ANSWER;
}
// What the chat shows for a job: the status, refined by the stage and the result.
export function jobStatus(job?: Job | null) {
  if (!job) return statusLabel.draft;
  if (job.status === "completed") return outcome(job);
  if (job.status !== "running") return statusLabel[job.status];
  return stageLabel[job.stage] || statusLabel.running;
}
const outcomeLabel: Record<NonNullable<Job["outcome"]>, string> = {
  ready: "Проект готов",
  attention: "Проект требует внимания",
  parameters_attention: "Параметры требуют внимания",
  not_sliced: "Проект не создан",
};
// Jobs finished before slicing joined the pipeline have no outcome.
function outcome(job: Job) {
  return job.outcome ? outcomeLabel[job.outcome] : statusLabel.completed;
}
const stageLabel: Partial<Record<Job["stage"], string>> = {
  parameters: "Подбираю параметры",
  validation: "Проверяю параметры",
  slicing: "Нарезаю в STE Slicer",
  gcode: "Проверяю G-code",
};
const ACTIVE = new Set(["running", "queued", "stopping"]);
export function isRunning(job?: Job | null) {
  return !!job && ACTIVE.has(job.status);
}

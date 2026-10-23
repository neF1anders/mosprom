export interface Evidence {
  source_id: string;
  quote: string;
  page: number | null;
}
export interface Requirement {
  label?: string;
  key: string;
  value: string;
  unit: string | null;
  conditions: string;
  mandatory: boolean;
  verified: boolean;
  provenance: string;
  sources: Evidence[];
}
export interface Question {
  id: string;
  title: string;
  reason: string;
  options: string[];
  answer: string | null;
  suggested?: string | null;
  basis?: string | null;
  affected_actions: string[];
}
export interface Conflict {
  id: string;
  title: string;
  options: string[];
  sources: Evidence[];
  resolved: boolean;
  resolution: string | null;
  affected_actions: string[];
}
export interface Geometry {
  readable: boolean;
  units: string;
  coordinate_unit?: "unknown" | "mm";
  extents: number[];
  defects: string[];
  limitations: string[];
  report_id: string | null;
  preview_id?: string | null;
}
export interface Card {
  schema_version?: string;
  stl_analysis?: {
    attachment_id: string;
    sha256: string;
    report: Record<string, unknown>;
  } | null;
  answers?: Record<string, string>;
  resolutions?: Record<string, string>;
  revision: number;
  purpose: string;
  requirements: Requirement[];
  preferences: string[];
  geometry: Geometry;
  assumptions: string[];
  unknowns: string[];
  questions: Question[];
  conflicts: Conflict[];
  readiness: string;
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
  handoff: string;
  created_at: string;
  updated_at: string;
}
export interface Attachment {
  id: string;
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
  pending: "Проверка в очереди",
};

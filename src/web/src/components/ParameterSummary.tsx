import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import type { Job, ParameterSet } from "../types";
import styles from "../App.module.css";

// The selected parameters inside the timeline row, like the card summary of stage one.
export function ParameterSummary({ job }: { job: Job }) {
  const summary = job.parameters;
  const details = useQuery({
    queryKey: ["parameters", job.id, job.revision, summary?.iteration],
    queryFn: () => api<ParameterSet>(`/jobs/${job.id}/parameters`),
    enabled: !!summary,
    staleTime: Infinity,
  });
  if (!summary) return null;
  const set = details.data;
  const settings = Object.entries(set?.settings || {});
  const rows: [string, string[]][] = [
    ["Режим", [summary.printing_mode]],
    ["Профиль", [summary.quality_type]],
    ["Материал", [summary.material]],
    [
      "Изменённые настройки",
      settings.length
        ? settings.map(
            ([key, setting]) =>
              `${key} ${String(setting.value)} ${setting.unit || ""}`.trim() +
              `, ${setting.why}`,
          )
        : ["Настройки не изменены"],
    ],
  ];
  if (set?.unsatisfied.length)
    rows.push(["Не выполнено", set.unsatisfied.map((item) => item.why)]);
  if (set?.assumptions.length)
    rows.push(["Допущения", set.assumptions.map((item) => item.text)]);
  return (
    <div className={styles.cardSummary}>
      <p>Что подобрано</p>
      <dl>
        {rows.map(([label, values]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>
              {values.map((value) => (
                <span key={value}>{value}</span>
              ))}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

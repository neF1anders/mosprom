import type { Job } from "../types";
import styles from "../App.module.css";

// The project STE Slicer made, inside the last timeline row; its files are in the project tree.
export function ResultSummary({ job }: { job: Job }) {
  const result = job.result;
  if (!result?.sliced) return null;
  const rows: [string, string][] = [];
  if (result.print_time_seconds)
    rows.push(["Время печати", duration(result.print_time_seconds)]);
  const material = [
    result.material_meters && `${decimal(result.material_meters)} м`,
    result.material_grams && `${decimal(result.material_grams)} г`,
  ].filter(Boolean);
  if (material.length) rows.push(["Материал", material.join(", ")]);
  if (result.folder) rows.push(["Папка проекта", result.folder]);
  return (
    <div className={styles.cardSummary}>
      <p>Что получилось</p>
      <dl>
        {rows.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>
              <span>{value}</span>
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
// The slicer's estimate as the chat says it: 5 ч 32 мин, 45 мин.
export function duration(seconds: number) {
  const minutes = Math.round(seconds / 60);
  const hours = Math.floor(minutes / 60);
  return hours ? `${hours} ч ${minutes % 60} мин` : `${minutes} мин`;
}
function decimal(value: number) {
  return String(Number(value.toFixed(1))).replace(".", ",");
}

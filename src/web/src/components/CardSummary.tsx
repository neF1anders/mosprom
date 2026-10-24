import { modelSize } from "../format";
import type { Card } from "../types";
import styles from "../App.module.css";
export function CardSummary({ card }: { card: Card }) {
  const geometry = card.geometry;
  const rows = [
    ["Деталь", card.purpose || "Назначение не указано"],
    [
      "Обязательные",
      card.requirements
        .filter((r) => r.mandatory)
        .map((r) => `${r.label || r.key} ${r.value} ${r.unit || ""}`.trim())
        .join(" · ") || "Нет подтверждённых требований",
    ],
    ["Геометрия", modelSize(geometry) || "Модели нет"],
    [
      "Допущения",
      card.assumptions.map((a) => a.text).join(" · ") || "Нет допущений",
    ],
    [
      "Ограничения",
      [...(geometry?.limitations || []), ...card.unknowns].join(" · ") ||
        "Ограничений нет",
    ],
  ];
  return (
    <div className={styles.cardSummary}>
      <p>Как я понял задачу</p>
      <dl>
        {rows.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

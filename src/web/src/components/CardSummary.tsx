import type { Card } from "../types";
import styles from "../App.module.css";
export function CardSummary({ card }: { card: Card }) {
  const rows = [
    ["Деталь", card.purpose],
    [
      "Обязательные",
      card.requirements
        .map((r) => `${r.label || r.key}: ${r.value} ${r.unit || ""}`)
        .join(" · ") || "Нет подтверждённых требований",
    ],
    [
      "Геометрия",
      card.geometry.extents.length
        ? `${card.geometry.extents.map((v) => Number(v.toFixed(3))).join(" × ")} ${card.geometry.units === "unknown" ? "единицы неизвестны" : "мм"}`
        : "Недоступна",
    ],
    ["Допущения", card.assumptions.join(" · ") || "Нет допущений"],
    [
      "Ограничения",
      card.geometry.limitations.join(" · ") ||
        "Ограничения сохранены в карточке",
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

import { useState } from "react";
import type { Conflict as ConflictType } from "../types";
import styles from "../App.module.css";

export function Conflict({
  conflict,
  pending,
  onResolve,
}: {
  conflict: ConflictType;
  pending: boolean;
  onResolve: (values: Record<string, string>) => void;
}) {
  const [value, setValue] = useState("");
  return (
    <section className={styles.question} aria-label="Расхождение источников">
      <p className={styles.conflictHeading}>
        <img src="/figma/warn.svg" alt="" />
        Нужно ваше подтверждение
      </p>
      <h3>{conflict.title}</h3>
      <p className={styles.muted}>
        Влияет на зависимые расчёты и подготовку задания
      </p>
      <div className={styles.options}>
        {conflict.options.map((option, i) => (
          <button
            key={option}
            aria-label={option}
            aria-pressed={value === option}
            onClick={() => setValue(option)}
          >
            <span className={styles.optionNumber} aria-hidden="true">
              {i + 1}
            </span>
            <span>
              {option}
              {conflict.sources[i] && (
                <small>{conflict.sources[i].quote}</small>
              )}
            </span>
          </button>
        ))}
        <div className={styles.customOption}>
          <span className={styles.optionNumber} aria-hidden="true">
            {conflict.options.length + 1}
          </span>
          <label className={styles.srOnly} htmlFor={`conflict-${conflict.id}`}>
            Своё значение
          </label>
          <input
            id={`conflict-${conflict.id}`}
            placeholder="Напишите своё значение"
            value={conflict.options.includes(value) ? "" : value}
            onChange={(e) => setValue(e.target.value)}
          />
        </div>
      </div>
      <div className={styles.conflictImpact}>
        <p>Пока нет ответа</p>
        <p>
          <img
            src="/figma/dot-error.svg"
            alt=""
            className={styles.statusDot}
            data-state="error"
          />
          Зависимые расчёты ожидают вашего решения
        </p>
        <details>
          <summary>Источники расхождения</summary>
          {conflict.sources.map((source, i) => (
            <blockquote key={i}>
              {source.quote}
              <small>
                {source.source_id}
                {source.page ? ` · стр ${source.page}` : ""}
              </small>
            </blockquote>
          ))}
        </details>
      </div>
      <div className={styles.actions}>
        <button
          className={styles.primary}
          disabled={pending || !value.trim()}
          onClick={() => onResolve({ [conflict.id]: value })}
        >
          Подтвердить выбор
        </button>
        <button
          disabled={pending}
          onClick={() => onResolve({ [conflict.id]: "Не знаю" })}
        >
          Не знаю
        </button>
      </div>
    </section>
  );
}

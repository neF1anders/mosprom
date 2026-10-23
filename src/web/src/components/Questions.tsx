import { useState } from "react";
import type { Question } from "../types";
import styles from "../App.module.css";

export function Questions({
  questions,
  onAnswer,
  pending,
}: {
  questions: Question[];
  onAnswer: (values: Record<string, string>) => void;
  pending: boolean;
}) {
  const unanswered = questions.filter((q) => q.answer === null);
  const [index, setIndex] = useState(0);
  const [values, setValues] = useState<Record<string, string>>({});
  const question = unanswered[Math.min(index, unanswered.length - 1)];
  if (!question) return null;
  const answer = values[question.id] || "";
  const options = [...new Set(question.options)].filter(
    (option) => option !== "Не знаю",
  );
  return (
    <section className={styles.question} aria-label="Уточняющие вопросы">
      <div className={styles.row}>
        <span className={styles.questionCounter}>
          Вопрос {index + 1} из {unanswered.length}
        </span>
        <nav className={styles.steps} aria-label="Номера вопросов">
          {unanswered.map((q, i) => (
            <button
              key={q.id}
              aria-current={index === i ? "step" : undefined}
              onClick={() => setIndex(i)}
            >
              {i + 1}
            </button>
          ))}
        </nav>
      </div>
      <h3>{question.title}</h3>
      <p className={styles.muted}>{question.reason}</p>
      <div className={styles.options}>
        {options.map((option, i) => (
          <button
            key={option}
            aria-label={option}
            aria-pressed={answer === option}
            data-suggested={!answer && question.suggested === option}
            aria-description={
              !answer && question.suggested === option
                ? "Предложенный вариант, требует вашего подтверждения"
                : undefined
            }
            onClick={() => setValues((v) => ({ ...v, [question.id]: option }))}
          >
            <span className={styles.optionNumber} aria-hidden="true">
              {i + 1}
            </span>
            <span>
              {option}
              {question.suggested === option && question.basis && (
                <small>Предложение, {question.basis}</small>
              )}
            </span>
          </button>
        ))}
        <div className={styles.customOption}>
          <span aria-hidden="true" className={styles.optionNumber}>
            {options.length + 1}
          </span>
          <label className={styles.srOnly} htmlFor={`answer-${question.id}`}>
            Свой ответ
          </label>
          <input
            id={`answer-${question.id}`}
            placeholder="Напишите свой вариант"
            value={
              question.options.includes(answer) || answer === "Не знаю"
                ? ""
                : answer
            }
            onChange={(e) =>
              setValues((v) => ({ ...v, [question.id]: e.target.value }))
            }
          />
        </div>
      </div>
      <div className={styles.actions}>
        {index > 0 && (
          <button onClick={() => setIndex((i) => i - 1)}>Назад</button>
        )}
        {(index < unanswered.length - 1 || !answer) && (
          <button
            aria-label={!answer ? "Не знаю" : undefined}
            title={!answer ? "Не знаю — пропустить вопрос" : undefined}
            onClick={() => {
              if (!answer)
                setValues((values) => ({
                  ...values,
                  [question.id]: "Не знаю",
                }));
              setIndex((i) => Math.min(i + 1, unanswered.length - 1));
            }}
          >
            {answer ? "Следующий вопрос" : "Пропустить"}
          </button>
        )}
        {Object.values(values).some((v) => v.trim()) && (
          <button
            className={styles.primary}
            disabled={pending || !Object.values(values).some((v) => v.trim())}
            onClick={() =>
              onAnswer(
                Object.fromEntries(
                  Object.entries(values).filter(([, v]) => v.trim()),
                ),
              )
            }
          >
            Отправить ответы
          </button>
        )}
      </div>
    </section>
  );
}

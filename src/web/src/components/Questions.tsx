import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import type { Question } from "../types";
import { answered, UNKNOWN_ANSWER } from "../types";
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
  // "Не знаю" is not an answer: such questions stay open and can be answered later.
  const open = questions.filter((q) => !answered(q));
  const [index, setIndex] = useState(0);
  const [values, setValues] = useState<Record<string, string>>({});
  const question = open[Math.min(index, open.length - 1)];
  if (!question) return null;
  const answer = values[question.id] || "";
  const options = [...new Set(question.options)].filter(
    (option) => option !== UNKNOWN_ANSWER,
  );
  const several = open.length > 1;
  const last = index >= open.length - 1;
  // Moving on without an answer records "Не знаю": the question stays open for later.
  const settle = () =>
    answer.trim() ? values : { ...values, [question.id]: UNKNOWN_ANSWER };
  // A field typed into and cleared again is not an answer, whichever way the window closes.
  const submit = (next: Record<string, string>) => {
    if (pending) return;
    onAnswer(
      Object.fromEntries(Object.entries(next).filter(([, v]) => v.trim())),
    );
  };
  const advance = () => {
    const next = settle();
    if (last) return submit(next);
    setValues(next);
    setIndex((i) => i + 1);
  };
  const advanceRef = useRef(advance);
  advanceRef.current = advance;
  useEffect(() => {
    // Enter works as Далее even when nothing on the page has focus.
    const key = (event: globalThis.KeyboardEvent) => {
      if (
        event.key === "Enter" &&
        !event.shiftKey &&
        !event.isComposing &&
        document.activeElement === document.body
      ) {
        event.preventDefault();
        advanceRef.current();
      }
    };
    document.addEventListener("keydown", key);
    return () => document.removeEventListener("keydown", key);
  }, []);
  const onKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    const target = event.target as HTMLElement;
    if (
      event.key !== "Enter" ||
      event.shiftKey ||
      event.nativeEvent.isComposing ||
      target.closest("[data-native-enter]")
    )
      return;
    event.preventDefault();
    const option = target.closest<HTMLElement>("[data-option]")?.dataset.option;
    if (option !== undefined) {
      const next = { ...values, [question.id]: option };
      setValues(next);
      if (last) submit(next);
      else setIndex((i) => i + 1);
      return;
    }
    advance();
  };
  return (
    <section
      className={styles.question}
      aria-label="Уточняющие вопросы"
      onKeyDown={onKeyDown}
    >
      {question.kind === "discrepancy" && (
        <p className={styles.conflictHeading}>
          <img src="/figma/warn.svg" alt="" />
          Нужно ваше подтверждение
        </p>
      )}
      {several && (
        <div className={styles.row}>
          <span className={styles.questionCounter}>
            Вопрос {index + 1} из {open.length}
          </span>
          <nav
            className={styles.steps}
            aria-label="Номера вопросов"
            data-native-enter
          >
            {open.map((q, i) => (
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
      )}
      <h3>{question.title}</h3>
      {question.impact && <p className={styles.muted}>{question.impact}</p>}
      {question.answer && (
        <p className={styles.muted}>Раньше вы ответили {question.answer}</p>
      )}
      <div className={styles.options}>
        {options.map((option, i) => (
          <button
            key={option}
            data-option={option}
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
              options.includes(answer) || answer === UNKNOWN_ANSWER
                ? ""
                : answer
            }
            onChange={(e) =>
              setValues((v) => ({ ...v, [question.id]: e.target.value }))
            }
          />
        </div>
      </div>
      {question.sources.length > 0 && (
        <details className={styles.sources}>
          <summary>Источники</summary>
          {question.sources.map((source, i) => (
            <blockquote key={i}>
              {source.quote}
              {source.page ? <small>страница {source.page}</small> : null}
            </blockquote>
          ))}
        </details>
      )}
      <div className={styles.actions}>
        {index > 0 && (
          <button data-native-enter onClick={() => setIndex((i) => i - 1)}>
            Назад
          </button>
        )}
        <button
          className={styles.primary}
          data-native-enter
          disabled={last && pending}
          aria-label={last ? "Отправить ответы" : undefined}
          onClick={advance}
        >
          {last ? "Отправить" : "Далее"}
        </button>
      </div>
    </section>
  );
}

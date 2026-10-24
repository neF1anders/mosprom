import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import type { Question } from "../types";
import { answered, UNKNOWN_ANSWER } from "../types";
import { useDictation } from "../hooks/useDictation";
import { Icon } from "./Icon";
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
  const dictation = useDictation((spoken) => {
    if (question)
      setValues((v) => ({
        ...v,
        [question.id]: [v[question.id], spoken].filter(Boolean).join(" "),
      }));
  });
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
  const highlighted = options.includes(answer)
    ? answer
    : !answer && question.suggested;
  const custom =
    options.includes(answer) || answer === UNKNOWN_ANSWER ? "" : answer;
  return (
    <section
      className={styles.question}
      aria-label="Уточняющие вопросы"
      onKeyDown={onKeyDown}
    >
      <div className={styles.questionHead}>
        <Icon name="help" />
        <span>
          {question.kind === "discrepancy"
            ? "Нужно ваше подтверждение"
            : "Вопрос"}
        </span>
        {several && (
          <nav className={styles.pager} aria-label="Вопросы" data-native-enter>
            <button
              className={styles.icon}
              aria-label="Предыдущий вопрос"
              disabled={index === 0}
              onClick={() => setIndex((i) => i - 1)}
            >
              <Icon name="chev-left" />
            </button>
            <span>
              {index + 1} из {open.length}
            </span>
            <button
              className={styles.icon}
              aria-label="Следующий вопрос"
              disabled={last}
              onClick={() => setIndex((i) => i + 1)}
            >
              <Icon name="chev-right" size={14} />
            </button>
          </nav>
        )}
      </div>
      <div className={styles.questionText}>
        <h3>{question.title}</h3>
        {question.impact && <p>{question.impact}</p>}
        {question.answer && <p>Раньше вы ответили {question.answer}</p>}
      </div>
      <div className={styles.options}>
        {options.map((option, i) => (
          <button
            key={option}
            data-option={option}
            aria-label={option}
            aria-pressed={answer === option}
            data-highlighted={highlighted === option}
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
            {highlighted === option && <Icon name="arrow" size={18} />}
          </button>
        ))}
      </div>
      <div className={styles.answerRow}>
        <Icon name="pencil" size={18} />
        <label className={styles.srOnly} htmlFor={`answer-${question.id}`}>
          Свой ответ
        </label>
        <input
          id={`answer-${question.id}`}
          placeholder="Или напишите свой ответ"
          value={custom}
          onChange={(e) =>
            setValues((v) => ({ ...v, [question.id]: e.target.value }))
          }
        />
        <button
          className={styles.icon}
          aria-label={
            dictation.listening
              ? "Остановить диктовку"
              : "Голосовой ввод ответа"
          }
          disabled={!dictation.available}
          data-native-enter
          onClick={dictation.toggle}
        >
          <Icon name="mic" size={32} />
        </button>
        {index > 0 && (
          <button
            className={styles.ghost}
            data-native-enter
            onClick={() => setIndex((i) => i - 1)}
          >
            Назад
          </button>
        )}
        <button
          className={styles.next}
          data-ready={!!answer.trim()}
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

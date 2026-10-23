import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import { Questions } from "./Questions";
import type { Question } from "../types";

const question: Question = {
  id: "units",
  kind: "units",
  title: "В каких единицах создан STL",
  impact: "Влияет на размеры",
  options: ["mm", "cm"],
  suggested: null,
  basis: null,
  sources: [],
  blocking: true,
  answer: null,
};
const second: Question = {
  ...question,
  id: "q2",
  kind: "clarify",
  title: "Какая среда",
};

describe("question window", () => {
  it("does not submit a preselected answer", () => {
    const answer = vi.fn();
    render(
      <Questions questions={[question]} onAnswer={answer} pending={false} />,
    );
    expect(answer).not.toHaveBeenCalled();
    expect(screen.queryByText(/Вопрос 1 из/)).toBeNull();
  });
  it.each(["mm", "cm", "Не знаю"])("accepts explicit %s", async (value) => {
    const answer = vi.fn();
    render(
      <Questions questions={[question]} onAnswer={answer} pending={false} />,
    );
    // "Не знаю" is what sending without a choice records.
    if (value !== "Не знаю")
      await userEvent.click(screen.getByRole("button", { name: value }));
    await userEvent.click(
      screen.getByRole("button", { name: "Отправить ответы" }),
    );
    expect(answer).toHaveBeenCalledWith({ units: value });
  });
  it("supports an open answer", async () => {
    const answer = vi.fn();
    render(
      <Questions questions={[question]} onAnswer={answer} pending={false} />,
    );
    await userEvent.type(screen.getByLabelText("Свой ответ"), "inch");
    await userEvent.click(
      screen.getByRole("button", { name: "Отправить ответы" }),
    );
    expect(answer).toHaveBeenCalledWith({ units: "inch" });
  });
  it("keeps a question answered with Не знаю open so it can be answered later", async () => {
    const answer = vi.fn();
    render(
      <Questions
        questions={[{ ...question, answer: "Не знаю" }]}
        onAnswer={answer}
        pending={false}
      />,
    );
    expect(screen.getByText("Раньше вы ответили Не знаю")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "mm" }));
    await userEvent.click(
      screen.getByRole("button", { name: "Отправить ответы" }),
    );
    expect(answer).toHaveBeenCalledWith({ units: "mm" });
  });
  it("hides questions with a real answer and counts the rest", () => {
    render(
      <Questions
        questions={[
          { ...question, answer: "mm" },
          second,
          { ...second, id: "q3" },
        ]}
        onAnswer={vi.fn()}
        pending={false}
      />,
    );
    expect(screen.getByText("Вопрос 1 из 2")).toBeVisible();
    expect(screen.getByRole("heading", { name: "Какая среда" })).toBeVisible();
  });
  it("a suggested option is highlighted without becoming an answer", async () => {
    const answer = vi.fn();
    render(
      <Questions
        questions={[{ ...question, suggested: "mm", basis: "Исходное ТЗ" }]}
        onAnswer={answer}
        pending={false}
      />,
    );
    expect(screen.getByRole("button", { name: /^mm$/ })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Отправить ответы" }),
    );
    expect(answer).toHaveBeenCalledWith({ units: "Не знаю" });
  });
  it("walks the questions with Далее, Назад and Enter", async () => {
    const answer = vi.fn();
    render(
      <Questions
        questions={[question, second]}
        onAnswer={answer}
        pending={false}
      />,
    );
    expect(screen.getByRole("button", { name: "Далее" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Назад" })).toBeNull();
    expect(
      screen.queryByRole("button", { name: "Отправить ответы" }),
    ).toBeNull();
    expect(screen.queryByRole("button", { name: /Пропустить/ })).toBeNull();
    await userEvent.type(screen.getByLabelText("Свой ответ"), "inch{Enter}");
    expect(screen.getByRole("heading", { name: "Какая среда" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Назад" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Далее" })).toBeNull();
    screen.getByRole("button", { name: "cm" }).focus();
    await userEvent.keyboard("{Enter}");
    expect(answer).toHaveBeenCalledWith({ units: "inch", q2: "cm" });
  });
  it("shows sources and the confirmation heading for discrepancies", () => {
    render(
      <Questions
        questions={[
          {
            ...second,
            kind: "discrepancy",
            options: ["25 Нм", "28 Нм"],
            sources: [{ source_id: "a:1", quote: "Момент 25 Нм", page: 1 }],
          },
        ]}
        onAnswer={vi.fn()}
        pending={false}
      />,
    );
    expect(screen.getByText("Нужно ваше подтверждение")).toBeVisible();
    expect(screen.getByText("Момент 25 Нм")).toBeInTheDocument();
  });
});

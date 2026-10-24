import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";
import { Progress } from "./Progress";
import type { Job, ProgressEvent } from "../types";

const event = (type: string, status = "completed"): ProgressEvent => ({
  event_id: 1,
  revision: 1,
  type,
  status,
  message: "Подтверждённое событие",
  data: {},
});
describe("timeline reflects actual events", () => {
  it("does not invent progress before any operation", () => {
    render(<Progress events={[event("job.changed")]} />);
    expect(screen.queryByRole("region", { name: "Ход работы" })).toBeNull();
  });
  it.each([
    ["files.completed", "Файлы прочитаны", "done"],
    ["stl.completed", "STL проанализирован", "done"],
    ["stl.failed", "STL проанализирован", "warn"],
    ["triage.completed", "Главные вопросы", "done"],
    ["interpretation.started", "ТЗ разобрано по аспектам", "run"],
    ["consolidation.started", "Сводка в карточку", "run"],
    ["discrepancies.completed", "Поиск несоответствий", "done"],
  ])(
    "%s marks its substep and keeps future stages waiting",
    (type, title, state) => {
      const status = type.endsWith("started")
        ? "running"
        : type.endsWith("failed")
          ? "failed"
          : "completed";
      render(<Progress events={[event(type, status)]} />);
      expect(screen.getByText(title).closest("details")).toHaveAttribute(
        "data-state",
        state,
      );
      expect(
        screen.getByText("Подбор параметров").closest("details"),
      ).toHaveAttribute("data-state", "wait");
    },
  );
  it("defects in the model show a warning on the STL substep", () => {
    render(<Progress events={[event("stl.completed", "warning")]} />);
    expect(
      screen.getByText("STL проанализирован").closest("details"),
    ).toHaveAttribute("data-state", "warn");
  });
  it.each([
    ["stopped", "wait"],
    ["failed", "warn"],
  ])("a %s run leaves no step spinning", (status, state) => {
    const job = { status, stage: "understanding" } as Job;
    render(
      <Progress
        events={[event("interpretation.started", "running")]}
        job={job}
      />,
    );
    for (const title of ["Интерпретация задания", "ТЗ разобрано по аспектам"])
      expect(screen.getByText(title).closest("details")).toHaveAttribute(
        "data-state",
        state,
      );
  });
  it("a running job keeps its open step running", () => {
    const job = { status: "running", stage: "understanding" } as Job;
    render(
      <Progress
        events={[event("interpretation.started", "running")]}
        job={job}
      />,
    );
    expect(
      screen.getByText("ТЗ разобрано по аспектам").closest("details"),
    ).toHaveAttribute("data-state", "run");
  });
});
describe("stages after the interpretation follow their own events", () => {
  const step = (
    type: string,
    iteration: number,
    status: string,
    message = "",
  ): ProgressEvent => ({
    event_id: 1,
    revision: 1,
    type,
    status,
    message,
    data: { iteration },
  });
  const state = (title: string) =>
    screen.getByText(title).closest("details")?.getAttribute("data-state");
  it("a handed over card waits for parameter selection", () => {
    const job = { status: "queued", stage: "parameters" } as Job;
    render(
      <Progress
        events={[event("files.completed"), event("stage1.completed")]}
        job={job}
      />,
    );
    expect(state("Подбор параметров")).toBe("wait");
    expect(
      screen.getByText("Задание передано, ждёт подбора параметров"),
    ).toBeInTheDocument();
  });
  it("each pass and check gets its own substep", () => {
    const job = { status: "running", stage: "parameters" } as Job;
    render(
      <Progress
        events={[
          event("stage1.completed"),
          step("parameters.started", 1, "running"),
          step("parameters.completed", 1, "completed", "Режим 3D"),
          step("validation.started", 1, "running"),
          step("validation.completed", 1, "warning", "1 ошибка"),
          step("parameters.started", 2, "running"),
        ]}
        job={job}
      />,
    );
    expect(state("Заход 1")).toBe("done");
    expect(state("Проверка 1")).toBe("warn");
    expect(state("Заход 2")).toBe("run");
    expect(state("Подбор параметров")).toBe("run");
    expect(state("Валидация")).toBe("warn");
    expect(screen.getByText("1 ошибка")).toBeInTheDocument();
    expect(state("Слайсинг")).toBe("wait");
  });
  it("a finished pipeline shows what was selected and flags unmet requirements", () => {
    const job = {
      id: "j",
      revision: 1,
      status: "completed",
      stage: "done",
      parameters: {
        iteration: 1,
        printing_mode: "3D",
        quality_type: "Fine",
        material: "PETG",
        changed_settings: 0,
        unsatisfied: 1,
        status: "proposed",
        check: "attention",
      },
    } as Job;
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={client}>
        <Progress
          events={[
            event("stage1.completed"),
            step("parameters.completed", 1, "completed"),
            step("validation.completed", 1, "completed", "Замечаний нет"),
          ]}
          job={job}
        />
      </QueryClientProvider>,
    );
    expect(screen.getByText("Что подобрано")).toBeInTheDocument();
    expect(screen.getByText("Fine")).toBeInTheDocument();
    expect(state("Подбор параметров")).toBe("warn");
    expect(state("Валидация")).toBe("done");
  });
});

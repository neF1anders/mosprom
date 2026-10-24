import { render, screen } from "@testing-library/react";
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
    const job = { status, next_stage: "not_ready" } as Job;
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
    const job = { status: "running", next_stage: "not_ready" } as Job;
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

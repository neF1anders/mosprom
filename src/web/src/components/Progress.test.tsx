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
    ["interpretation.started", "Задание разобрано", "run"],
    ["interpretation.completed", "Задание разобрано", "done"],
    ["checking.started", "Карточка проверена", "run"],
    ["checking.completed", "Карточка проверена", "done"],
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
  it("the interpretation has exactly the four steps of the chain", () => {
    render(<Progress events={[event("files.started", "running")]} />);
    const parent = screen.getByText("Интерпретация задания").closest("details");
    const titles = [
      ...parent!.querySelectorAll(":scope details summary span"),
    ].map((title) => title.textContent);
    expect(titles).toEqual([
      "Файлы прочитаны",
      "STL проанализирован",
      "Задание разобрано",
      "Карточка проверена",
    ]);
  });
  it("events of the removed agents start no timeline", () => {
    render(
      <Progress
        events={[event("triage.completed"), event("judge.completed")]}
      />,
    );
    expect(screen.queryByRole("region", { name: "Ход работы" })).toBeNull();
  });
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
    for (const title of ["Интерпретация задания", "Задание разобрано"])
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
      screen.getByText("Задание разобрано").closest("details"),
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
  it("the result opens when the pipeline ends after its row was already done", () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const events = [
      event("stage1.completed"),
      step("parameters.completed", 1, "completed"),
      step("validation.started", 1, "running"),
    ];
    const working = {
      id: "j",
      revision: 1,
      status: "running",
      stage: "validation",
    };
    const view = (job: Job) => (
      <QueryClientProvider client={client}>
        <Progress events={events} job={job} />
      </QueryClientProvider>
    );
    const { rerender } = render(view(working as Job));
    const row = () => screen.getByText("Подбор параметров").closest("details");
    expect(row()).not.toHaveAttribute("open");
    const parameters = {
      iteration: 1,
      printing_mode: "3D",
      quality_type: "Fine",
      material: "PETG",
      changed_settings: 0,
      unsatisfied: 0,
      status: "proposed",
      check: "ok",
    };
    rerender(
      view({
        ...working,
        status: "completed",
        stage: "done",
        parameters,
      } as Job),
    );
    expect(row()).toHaveAttribute("open");
    expect(screen.getByText("Что подобрано")).toBeVisible();
  });
  it("slicing and the G-code check follow their passes", () => {
    const job = { status: "running", stage: "gcode" } as Job;
    render(
      <Progress
        events={[
          event("stage1.completed"),
          step("parameters.completed", 1, "completed"),
          step("validation.completed", 1, "completed"),
          step("slicing.started", 1, "running"),
          step(
            "slicing.completed",
            1,
            "completed",
            "G-code и проект сохранены",
          ),
          step("gcode.started", 1, "running"),
        ]}
        job={job}
      />,
    );
    expect(state("Нарезка 1")).toBe("done");
    expect(state("Слайсинг")).toBe("done");
    expect(state("Проверка G-code 1")).toBe("run");
    expect(state("Подготовка результата")).toBe("run");
  });
  it("a finished pipeline offers the project and its G-code", () => {
    const job = {
      id: "j",
      revision: 1,
      status: "completed",
      stage: "done",
      parameters: null,
      result: {
        iteration: 1,
        sliced: true,
        message: "G-code и проект сохранены",
        gcode_check: "ok",
        folder: "C:\\STE_AIAssistant\\mosprom\\j-r1-i1",
        print_time_seconds: 19953,
        material_grams: 36.6,
        material_meters: 12.25,
      },
    } as Job;
    render(
      <Progress
        events={[
          event("stage1.completed"),
          step("slicing.completed", 1, "completed"),
          step("gcode.completed", 1, "completed", "Замечаний нет"),
        ]}
        job={job}
      />,
    );
    expect(state("Подготовка результата")).toBe("done");
    expect(screen.getByText("Что получилось")).toBeVisible();
    expect(screen.getByText("5 ч 33 мин")).toBeInTheDocument();
    expect(screen.getByText("12,3 м, 36,6 г")).toBeInTheDocument();
    expect(screen.getByText("Скачать проект 3MF")).toHaveAttribute(
      "href",
      "/api/v1/jobs/j/result/project",
    );
  });
  it("without a project the G-code is not checked and the slicing row says why", () => {
    const job = {
      id: "j",
      revision: 1,
      status: "completed",
      stage: "done",
      parameters: null,
      result: {
        iteration: 1,
        sliced: false,
        message: "STE Slicer с плагином AI Assistant не запущен",
        gcode_check: "pending",
        folder: null,
        print_time_seconds: null,
        material_grams: null,
        material_meters: null,
      },
    } as Job;
    render(
      <Progress
        events={[
          event("stage1.completed"),
          step("slicing.started", 1, "running"),
          step(
            "slicing.completed",
            1,
            "warning",
            "STE Slicer с плагином AI Assistant не запущен",
          ),
        ]}
        job={job}
      />,
    );
    expect(state("Слайсинг")).toBe("warn");
    expect(
      screen.getByText("STE Slicer с плагином AI Assistant не запущен"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Не проводилась, проект не создан"),
    ).toBeInTheDocument();
  });
});

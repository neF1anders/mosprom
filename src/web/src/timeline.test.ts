import { describe, expect, it } from "vitest";
import { addThought, buildTimeline, paragraphs, summaries } from "./timeline";
import type { Attachment, Job, ProgressEvent } from "./types";

let id = 0;
const event = (
  type: string,
  status = "completed",
  data: Record<string, unknown> = {},
  message = "",
  second = 0,
): ProgressEvent => ({
  event_id: ++id,
  revision: 1,
  type,
  status,
  message,
  data,
  created_at: new Date(Date.UTC(2026, 9, 24, 12, 0, second)).toISOString(),
});
const at = (second: number) => Date.UTC(2026, 9, 24, 12, 0, second);
const files: Attachment[] = [
  {
    id: "spec",
    filename: "Корпус_ТЗ.pdf",
    kind: "pdf",
    status: "completed",
    error: null,
    artifacts: [],
  },
  {
    id: "mesh",
    filename: "korpus.stl",
    kind: "stl",
    status: "completed",
    error: null,
    artifacts: [],
  },
];
const job = (update: Partial<Job> = {}) =>
  ({
    id: "j",
    revision: 1,
    status: "running",
    stage: "understanding",
    active_stl: "mesh",
    card: null,
    ...update,
  }) as Job;
const stage = (stages: ReturnType<typeof buildTimeline>, key: string) =>
  stages!.find((s) => s.key === key)!;

describe("the timeline follows the events the server sends", () => {
  it("does not invent work before any operation", () => {
    expect(buildTimeline({ events: [event("job.changed")] })).toBeNull();
    expect(
      buildTimeline({
        events: [event("triage.completed"), event("judge.completed")],
      }),
    ).toBeNull();
  });
  it("turns the file and STL events into rows with the analysis as output", () => {
    const stages = buildTimeline({
      events: [
        event("files.completed"),
        event("stl.started", "running"),
        event("stl.completed", "warning", {
          geometry: {
            units: "mm",
            extents: [84, 62, 40],
            defects: ["duplicate_faces"],
            volume: 38400,
          },
        }),
        event(
          "interpretation.completed",
          "completed",
          {},
          "Найдено требований 9",
        ),
      ],
      job: job(),
      attachments: files,
    });
    const first = stage(stages, "understanding");
    expect(first.state).toBe("run");
    expect(first.actions.map((a) => a.text)).toEqual([
      "Прочитал Корпус_ТЗ.pdf",
      "Запустил разбор korpus.stl",
      "Нашёл в ТЗ 9 требований",
    ]);
    expect(first.actions[1]).toMatchObject({
      kind: "terminal",
      command: "$ stl korpus.stl",
      output: [
        "габариты 84 × 62 × 40 мм",
        "объём 38,4 см3",
        "дефекты дублирующие грани",
      ],
    });
    expect(stage(stages, "parameters").state).toBe("wait");
  });
  it.each([
    ["stopped", "wait"],
    ["failed", "error"],
  ])("a %s run leaves no stage spinning", (status, state) => {
    const stages = buildTimeline({
      events: [event("checking.started", "running")],
      job: job({ status, error: "Модель не отвечает" }),
    });
    expect(stage(stages, "understanding").state).toBe(state);
  });
  it("a failure marks the open row and says what happened", () => {
    const stages = buildTimeline({
      events: [event("checking.started", "running", {}, "Проверяю карточку")],
      job: job({ status: "failed", error: "Модель не отвечает" }),
    });
    const first = stage(stages, "understanding");
    expect(first.summary).toBe("Модель не отвечает");
    expect(first.meta).toEqual({ text: "остановлен", tone: "error" });
    expect(first.actions.at(-1)?.state).toBe("error");
  });
  it("waits for answers with the reason as its summary", () => {
    const stages = buildTimeline({
      events: [
        event("files.completed"),
        event("stage1.completed", "waiting_user", {}, "Нужно уточнить 3 вещи"),
      ],
      job: job({
        status: "waiting_user",
        card: {
          revision: 1,
          questions: [{ id: "q", answer: null }],
        } as unknown as Job["card"],
      }),
    });
    const first = stage(stages, "understanding");
    expect(first.state).toBe("warn");
    expect(first.meta).toEqual({ text: "ждёт ответа", tone: "warn" });
    expect(first.summary).toBe("Нужно уточнить 3 вещи");
    expect(summaries(stages).has("Нужно уточнить 3 вещи")).toBe(true);
  });
  it("tells how long a stage works and how long it took", () => {
    const running = buildTimeline({
      events: [event("files.started", "running", {}, "", 0)],
      job: job(),
      now: at(14),
    });
    expect(stage(running, "understanding").meta).toEqual({
      text: "работает 14 с",
      tone: "run",
    });
    const offline = buildTimeline({
      events: [event("files.started", "running")],
      job: job(),
      connected: false,
    });
    expect(stage(offline, "understanding").meta?.text).toBe("ждёт связь");
    const done = buildTimeline({
      events: [
        event("files.started", "running", {}, "", 0),
        event("stage1.completed", "queued", {}, "Карточка готова", 41),
      ],
      job: job({ status: "queued", stage: "parameters" }),
    });
    expect(stage(done, "understanding").meta?.text).toBe("41 с");
  });
});
describe("stages after the interpretation follow their passes", () => {
  it("a handed over card waits for parameter selection", () => {
    const stages = buildTimeline({
      events: [event("files.completed"), event("stage1.completed")],
      job: job({ status: "queued", stage: "parameters" }),
    });
    expect(stage(stages, "parameters")).toMatchObject({
      state: "wait",
      summary: "Задание передано, ждёт подбора параметров",
    });
  });
  it("each pass becomes a row and a warning marks its stage", () => {
    const stages = buildTimeline({
      events: [
        event("stage1.completed"),
        event("parameters.started", "running", { iteration: 1 }),
        event(
          "parameters.completed",
          "completed",
          { iteration: 1 },
          "Режим 3D",
        ),
        event("validation.started", "running", { iteration: 1 }),
        event("validation.completed", "warning", { iteration: 1 }, "1 ошибка"),
        event("parameters.started", "running", { iteration: 2 }),
      ],
      job: job({ stage: "parameters" }),
    });
    expect(stage(stages, "parameters").state).toBe("run");
    expect(stage(stages, "parameters").actions.map((a) => a.text)).toEqual([
      "Подбираю параметры",
      "Подобрал параметры",
      "Подбираю параметры, заход 2",
    ]);
    expect(stage(stages, "validation")).toMatchObject({
      state: "warn",
      summary: "1 ошибка",
    });
    expect(stage(stages, "slicing").state).toBe("wait");
  });
  it("a finished pipeline opens what was selected and flags unmet requirements", () => {
    const stages = buildTimeline({
      events: [
        event("stage1.completed"),
        event("parameters.completed", "completed", { iteration: 1 }),
        event("validation.completed", "completed", { iteration: 1 }),
      ],
      job: job({
        status: "completed",
        stage: "done",
        parameters: {
          unsatisfied: 1,
          status: "proposed",
        } as Job["parameters"],
      }),
    });
    expect(stage(stages, "parameters")).toMatchObject({
      state: "warn",
      result: "parameters",
    });
    expect(stage(stages, "validation").state).toBe("done");
  });
  it("without a project the G-code check says why it did not run", () => {
    const stages = buildTimeline({
      events: [
        event("stage1.completed"),
        event(
          "slicing.completed",
          "warning",
          { iteration: 1 },
          "STE Slicer не запущен",
        ),
      ],
      job: job({
        status: "completed",
        stage: "done",
        result: { sliced: false } as Job["result"],
      }),
    });
    expect(stage(stages, "slicing").state).toBe("warn");
    expect(stage(stages, "gcode").summary).toBe(
      "Не проводилась, проект не создан",
    );
  });
});
describe("agents and their reasoning", () => {
  const call = "run1:interpreter:1";
  it("groups the steps of an agent into one run with its thoughts", () => {
    let thoughts = addThought(
      {},
      event(
        "agent.thinking",
        "running",
        { call, attempt: 1, text: "Читаю ТЗ" },
        "",
        2,
      ),
    );
    thoughts = addThought(
      thoughts,
      event(
        "agent.thinking",
        "running",
        { call, attempt: 1, text: ".\n\nСверяю" },
        "",
        6,
      ),
    );
    const stages = buildTimeline({
      events: [
        event("files.completed"),
        event("agent.started", "running", {
          agent: "gate",
          call: "run1:gate:1",
        }),
        event(
          "agent.started",
          "running",
          { agent: "interpreter", call },
          "",
          1,
        ),
        event("tool.called", "running", {
          agent: "interpreter",
          call,
          tool: "convert_units",
          arguments: { value: 2, from_unit: "in", to_unit: "mm" },
        }),
        event("tool.finished", "completed", {
          agent: "interpreter",
          call,
          tool: "convert_units",
          result_preview: '{"value": 50.8}',
        }),
      ],
      job: job(),
      attachments: files,
      thoughts,
    });
    const first = stage(stages, "understanding");
    expect(first.agents).toHaveLength(1);
    const agent = first.agents[0];
    expect(agent).toMatchObject({
      title: "Интерпретатор ТЗ",
      state: "run",
      thoughts: [
        { at: at(2), text: "Читаю ТЗ." },
        { at: at(6), text: "Сверяю" },
      ],
    });
    expect(agent.actions[0]).toMatchObject({
      text: "Перевёл 2 in в mm",
      output: ['{"value": 50.8}'],
    });
    // The row of an agent at work is in its card, not in the stage.
    expect(first.actions.some((a) => a.agent === "interpreter")).toBe(false);
  });
  it("a retry of a call starts its reasoning over", () => {
    const one = addThought(
      {},
      event("agent.thinking", "running", { call, attempt: 1, text: "Первая" }),
    );
    const two = addThought(
      one,
      event("agent.thinking", "running", { call, attempt: 2, text: "Вторая" }),
    );
    expect(two[call].chunks.map((c) => c.text)).toEqual(["Вторая"]);
  });
  it("splits reasoning into paragraphs across pieces", () => {
    expect(
      paragraphs([
        { at: 1, text: "Один" },
        { at: 2, text: " два\n\nТри" },
      ]),
    ).toEqual([
      { at: 1, text: "Один два" },
      { at: 2, text: "Три" },
    ]);
  });
});

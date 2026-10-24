import { describe, expect, it } from "vitest";
import { barOrder, cardSections } from "./card";
import { plural } from "./format";
import type { Card, Job, ProgressEvent } from "./types";

const geometry = {
  readable: true,
  units: "mm",
  extents: [84, 62, 40],
  defects: ["duplicate_faces"],
  limitations: [],
  report_id: null,
  preview_id: null,
};
function card(update: Partial<Card> = {}): Card {
  return {
    schema_version: "2.0",
    job_id: "j",
    revision: 1,
    purpose: "Корпус подшипника, эксплуатация в помещении",
    requirements: Array.from({ length: 9 }, (_, i) => ({
      key: `r${i}`,
      label: `Требование ${i}`,
      value: "1",
      unit: null,
      conditions: "",
      mandatory: true,
      verified: true,
      provenance: "document",
      sources: [],
      superseded: [],
    })),
    preferences: [],
    production_constraints: [],
    assumptions: [
      { text: "Масштаб STL 1 к 1 по ТЗ", basis: "", consequence: "" },
      { text: "Цвет и внешний вид не важны", basis: "", consequence: "" },
    ],
    unknowns: [],
    questions: [],
    geometry,
    readiness: "ready",
    allowed_actions: [],
    blocked_actions: {},
    ...update,
  };
}
function job(update: Partial<Job> = {}): Job {
  return {
    id: "j",
    title: "Корпус подшипника",
    revision: 1,
    status: "completed",
    card: card(),
    error: null,
    files_changed: false,
    stage: "done",
    work_revision: 1,
    parameters: null,
    outcome: null,
    created_at: "",
    updated_at: "",
    ...update,
  };
}
const question = {
  id: "q",
  kind: "clarify" as const,
  title: "Какая температура",
  impact: "",
  options: [],
  suggested: null,
  basis: null,
  sources: [],
  blocking: true,
  answer: null,
};

describe("task card sections", () => {
  it("waits without a job and works out the sections while the job runs", () => {
    expect(cardSections(undefined, []).map((s) => s.state)).toEqual([
      "wait",
      "wait",
      "wait",
      "wait",
    ]);
    const running = cardSections(job({ status: "running", card: null }), []);
    expect(running.map((s) => s.summary)).toEqual([
      "Определяется",
      "Определяется",
      "Определяется",
      "Определяется",
    ]);
  });
  it("shows the measured geometry before the card and its defect", () => {
    const event: ProgressEvent = {
      event_id: 1,
      revision: 1,
      type: "stl.completed",
      status: "warning",
      message: "",
      data: { geometry },
    };
    const [, , shape] = cardSections(job({ status: "running", card: null }), [
      event,
    ]);
    expect(shape).toMatchObject({
      state: "warn",
      summary: "84 × 62 × 40 мм · дублирующие грани",
    });
  });
  it("needs attention while questions wait for answers", () => {
    const sections = cardSections(
      job({
        status: "waiting_user",
        card: card({ questions: [question, question, question] }),
      }),
      [],
    );
    expect(sections[1]).toMatchObject({
      state: "warn",
      summary: "9 требований · 3 ждут ответа",
    });
    expect(sections[2].state).toBe("warn");
  });
  it("is done once everything is settled, the defect included", () => {
    const sections = cardSections(job(), []);
    expect(sections.map((s) => s.state)).toEqual([
      "done",
      "done",
      "done",
      "done",
    ]);
    expect(sections[1].summary).toBe("9 требований подтверждены");
    expect(sections[2].summary).toBe("84 × 62 × 40 мм · дефект учтён");
    expect(sections[3].summary).toBe(
      "Масштаб STL 1 к 1 по ТЗ, цвет и внешний вид не важны",
    );
  });
  it("counts many assumptions and marks unknowns", () => {
    const many = card({
      assumptions: Array.from({ length: 3 }, (_, i) => ({
        text: `Допущение ${i}`,
        basis: "по ТЗ п. 2",
        consequence: "",
      })),
    });
    expect(cardSections(job({ card: many }), [])[3].summary).toBe(
      "3 допущения, блокирующих неизвестных нет",
    );
    const unknown = cardSections(
      job({ card: card({ unknowns: ["Нагрузка"] }) }),
      [],
    )[3];
    expect(unknown.state).toBe("warn");
    expect(unknown.items.at(-1)).toMatchObject({ tag: "неизвестно" });
  });
  it("marks unfinished sections after a failure", () => {
    const sections = cardSections(job({ status: "failed", card: null }), []);
    expect(sections[0].state).toBe("error");
  });
  it("fills the bar from the left in the order of states", () => {
    const sections = cardSections(
      job({ status: "running", card: card({ questions: [question] }) }),
      [],
    );
    expect(barOrder(sections)).toEqual(["done", "done", "warn", "warn"]);
  });
});
describe("Russian plural forms", () => {
  it("picks the form by the last digits", () => {
    const forms: [string, string, string] = ["ответ", "ответа", "ответов"];
    expect([1, 2, 5, 11, 21, 104].map((n) => plural(n, forms))).toEqual([
      "ответ",
      "ответа",
      "ответов",
      "ответов",
      "ответ",
      "ответа",
    ]);
  });
});

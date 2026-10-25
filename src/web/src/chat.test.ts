import { describe, expect, it } from "vitest";
import { asksQuestions } from "./chat";
import type { Card, Job } from "./types";
import { UNKNOWN_ANSWER } from "./types";

const question = (answer: string | null) => ({
  id: "q1",
  kind: "clarify" as const,
  title: "Материал",
  impact: "",
  options: ["PETG", "PLA"],
  suggested: null,
  basis: null,
  sources: [],
  blocking: true,
  answer,
});
const job = (status: string, answer: string | null = null, card = 1) =>
  ({
    status,
    revision: 1,
    card: { revision: card, questions: [question(answer)] } as unknown as Card,
  }) as Job;

describe("the question window", () => {
  it("opens while the job waits for answers to its current card", () => {
    expect(asksQuestions(job("waiting_user"))).toBe(true);
  });
  it.each(["queued", "running", "completed", "failed", "stopped"])(
    "stays closed for a %s job even with open questions",
    (status) => {
      expect(asksQuestions(job(status))).toBe(false);
      // «Не знаю» закрыт
      expect(asksQuestions(job(status, UNKNOWN_ANSWER))).toBe(false);
    },
  );
  it("stays closed while the card belongs to an older revision", () => {
    expect(asksQuestions(job("waiting_user", null, 0))).toBe(false);
  });
  it("stays closed without a job or a card", () => {
    expect(asksQuestions(undefined)).toBe(false);
    expect(
      asksQuestions({ status: "waiting_user", revision: 1, card: null } as Job),
    ).toBe(false);
  });
});

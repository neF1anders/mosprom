import { describe, expect, it } from "vitest";
import { answering, splitAt } from "./chat";
import { blocks } from "./components/Markdown";
import { chatRuns, runsByReply } from "./timeline";
import type { Message, ProgressEvent } from "./types";

const message = (role: string, created_at: string, kind = "chat"): Message =>
  ({
    id: created_at,
    seq: 1,
    role,
    kind,
    text: "x",
    revision: 1,
    created_at,
  }) as Message;
const event = (type: string, agent: string, call: string): ProgressEvent => ({
  event_id: 1,
  revision: 1,
  type,
  status: "running",
  message: "",
  data: { agent, call },
});

describe("the assistant in the chat", () => {
  it("puts what came after the work began below the timeline", () => {
    const sent = message("user", "2026-10-25T10:00:00Z");
    const report = message("assistant", "2026-10-25T10:05:00Z", "report");
    expect(splitAt([sent, report], "2026-10-25T10:01:00Z")).toEqual([
      [sent],
      [report],
    ]);
    expect(splitAt([sent, report], undefined)).toEqual([[sent, report], []]);
  });
  it("is answering while a message waits or one of its calls runs", () => {
    const asked = message("user", "2026-10-25T10:00:00Z");
    const replied = message("assistant", "2026-10-25T10:00:05Z");
    expect(answering([], [asked], false)).toBe(true);
    // The work took the message, the timeline shows it.
    expect(answering([], [asked], true)).toBe(false);
    expect(answering([], [asked, replied], false)).toBe(false);
    const thinking = event("agent.started", "analyst", "r:analyst:1");
    expect(answering([thinking], [asked, replied], false)).toBe(true);
    const done = event("agent.finished", "analyst", "r:analyst:1");
    expect(answering([thinking, done], [asked, replied], false)).toBe(false);
    expect(
      answering([event("agent.started", "checker", "r:checker:1")], [], false),
    ).toBe(false);
  });
  it("reads headings, lists and paragraphs of the Markdown", () => {
    expect(
      blocks(
        "Проект готов\n\n### Допущения\n- Цвет не важен\n- Одна штука\n1. Шаг",
      ),
    ).toEqual([
      { kind: "paragraph", lines: ["Проект готов"] },
      { kind: "heading", lines: ["### Допущения"] },
      { kind: "list", lines: ["- Цвет не важен", "- Одна штука"] },
      { kind: "ordered", lines: ["1. Шаг"] },
    ]);
  });
});
describe("the assistant's reasoning", () => {
  const at = (second: number) =>
    new Date(Date.UTC(2026, 9, 25, 3, 0, second)).toISOString();
  const agentEvent = (
    type: string,
    agent: string,
    call: string,
    second: number,
  ): ProgressEvent => ({
    ...event(type, agent, call),
    created_at: at(second),
  });
  it("shows a turn like an agent and opens it above the reply it led to", () => {
    const events = [
      agentEvent("agent.started", "assistant", "t1:assistant:1", 0),
      agentEvent("agent.finished", "assistant", "t1:assistant:1", 4),
      agentEvent("agent.started", "checker", "w:checker:1", 5),
      agentEvent("agent.started", "assistant", "t2:assistant:1", 10),
    ];
    const thoughts = {
      "t1:assistant:1": {
        agent: "assistant",
        attempt: 1,
        chunks: [{ at: Date.parse(at(1)), text: "The user greets" }],
        said: [{ at: Date.parse(at(3)), text: "Отвечаю на приветствие" }],
      },
    };
    const turns = chatRuns(events, thoughts);
    expect(turns.map((t) => [t.id, t.title, t.state])).toEqual([
      ["t1:assistant", "Ассистент", "done"],
      ["t2:assistant", "Ассистент", "run"],
    ]);
    expect(turns[0].said[0].text).toBe("Отвечаю на приветствие");
    // The turn opens above its last reply; another turn's reply gets nothing of it.
    const said = { ...message("assistant", at(2)), id: "s1", turn: "t1" };
    const reply = { ...message("assistant", at(5)), id: "r1", turn: "t1" };
    const other = { ...message("assistant", at(5)), id: "r0", turn: "t0" };
    const found = runsByReply([said, other, reply], turns);
    expect([...found.keys()]).toEqual(["r1"]);
    expect(found.get("r1")!.map((t) => t.id)).toEqual(["t1:assistant"]);
  });
});

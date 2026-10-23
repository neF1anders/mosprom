import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Progress } from "./Progress";
import type { ProgressEvent } from "../types";

const event = (type: string, status = "completed"): ProgressEvent => ({
  event_id: 1,
  revision: 1,
  type,
  status,
  message: "Подтверждённое событие",
  data: {},
});
describe("Figma timeline reflects actual events", () => {
  it("does not invent progress before any operation", () => {
    render(<Progress events={[]} />);
    expect(screen.queryByRole("region", { name: "Ход работы" })).toBeNull();
  });
  it.each([
    "document.completed",
    "geometry.started",
    "geometry.failed",
    "requirements.started",
    "stage1.completed",
  ])("keeps future stages waiting after %s", (type) => {
    render(<Progress events={[event(type)]} />);
    expect(screen.getByText("Интерпретация задания")).toBeVisible();
    expect(
      screen.getByText("Подбор параметров").closest("details"),
    ).toHaveAttribute("data-state", "wait");
    expect(
      screen.getByText("Подготовка результата").closest("details"),
    ).toHaveAttribute("data-state", "wait");
  });
});

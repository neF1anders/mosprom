import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import { Composer } from "./Composer";

const props = {
  onFiles: vi.fn(),
  onRemoveFile: vi.fn(),
  onStop: vi.fn(),
  pending: false,
  running: false,
  files: [],
  filesChanged: false,
};

describe("composer keys", () => {
  it("sends on Enter and keeps Shift+Enter as a new line", async () => {
    const send = vi.fn().mockResolvedValue(undefined);
    render(<Composer {...props} onSend={send} />);
    const field = screen.getByLabelText("Сообщение");
    await userEvent.type(field, "Корпус{Shift>}{Enter}{/Shift}подшипника");
    expect(send).not.toHaveBeenCalled();
    expect(field).toHaveValue("Корпус\nподшипника");
    await userEvent.keyboard("{Enter}");
    expect(send).toHaveBeenCalledWith("Корпус\nподшипника");
  });
});

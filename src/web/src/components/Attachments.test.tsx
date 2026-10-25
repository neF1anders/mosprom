import { Blob as NodeBlob } from "node:buffer";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import { Attachments, type DraftFile } from "./Attachments";
import { Composer } from "./Composer";

const ready: DraftFile = {
  key: "a1",
  name: "Требования.txt",
  kind: "txt",
  // нет text()
  load: async () =>
    new NodeBlob(["# Корпус подшипника\nРабота в помещении"]) as Blob,
};
const uploading: DraftFile = {
  key: "local",
  name: "эскиз.png",
  kind: "png",
  uploading: true,
};
const failed: DraftFile = {
  key: "bad",
  name: "korpus.step",
  kind: "step",
  error: "Формат не поддерживается, приложите STL",
};

describe("attachments in the composer", () => {
  it("shows the start of a text file as its preview", async () => {
    render(<Attachments files={[ready]} onRemove={vi.fn()} />);
    expect(await screen.findByText("Корпус подшипника")).toBeVisible();
    expect(screen.getByText("Работа в помещении")).toBeVisible();
  });
  it("marks an uploading file busy without a spinner and offers no removal yet", () => {
    render(<Attachments files={[uploading]} onRemove={vi.fn()} />);
    expect(screen.getByRole("listitem")).toHaveAttribute("aria-busy", "true");
    expect(screen.queryByRole("img")).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
  });
  it("explains a rejected file and removes it", async () => {
    const remove = vi.fn();
    render(<Attachments files={[failed]} onRemove={remove} />);
    expect(
      screen.getByText("Формат не поддерживается, приложите STL"),
    ).toBeVisible();
    await userEvent.click(
      screen.getByRole("button", { name: "Убрать korpus.step" }),
    );
    expect(remove).toHaveBeenCalledWith(failed);
  });
  it("keeps sending off until every upload finishes", () => {
    const props = {
      onSend: vi.fn(),
      onFiles: vi.fn(),
      onRemoveFile: vi.fn(),
      onStop: vi.fn(),
      pending: false,
      running: false,
      filesChanged: true,
    };
    const { rerender } = render(
      <Composer {...props} files={[ready, uploading]} />,
    );
    expect(screen.getByRole("button", { name: "Отправить" })).toBeDisabled();
    rerender(<Composer {...props} files={[ready, failed]} />);
    return waitFor(() =>
      expect(screen.getByRole("button", { name: "Отправить" })).toBeEnabled(),
    );
  });
});

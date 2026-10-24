import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { QueuedMessages } from "./QueuedMessages";

const item = {
  id: "q1",
  text: "добавь проверку допусков на посадочное место",
  status: "queued" as const,
  attempts: 0,
};
describe("queued messages", () => {
  it("sends now, deletes and offers the text back for a change", async () => {
    const send = vi.fn();
    const remove = vi.fn();
    const edit = vi.fn();
    render(
      <QueuedMessages
        items={[item]}
        pending={false}
        onSend={send}
        onDelete={remove}
        onEdit={edit}
      />,
    );
    await userEvent.click(
      screen.getByRole("button", { name: /Скорректировать/ }),
    );
    expect(send).toHaveBeenCalledWith("q1");
    await userEvent.click(
      screen.getByRole("button", { name: "Удалить из очереди" }),
    );
    expect(remove).toHaveBeenCalledWith("q1");
    await userEvent.click(
      screen.getByRole("button", { name: "Действия с сообщением" }),
    );
    await userEvent.click(screen.getByRole("menuitem", { name: "Изменить" }));
    expect(edit).toHaveBeenCalledWith(item);
  });
  it("keeps a message being delivered as it is", () => {
    render(
      <QueuedMessages
        items={[{ ...item, status: "delivering" }]}
        pending={false}
        onSend={vi.fn()}
        onDelete={vi.fn()}
        onEdit={vi.fn()}
      />,
    );
    expect(
      screen.getByRole("button", { name: /Скорректировать/ }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Удалить из очереди" }),
    ).toBeDisabled();
  });
});

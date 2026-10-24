import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import { ChatItem } from "./ChatItem";
import type { Job } from "../types";

const item = { id: "1", title: "Шестерня привода", status: "draft" } as Job;
function view() {
  const props = {
    onOpen: vi.fn(),
    onRename: vi.fn(),
    onDelete: vi.fn(),
  };
  render(
    <ChatItem
      item={item}
      active
      label="Шестерня привода Ожидаю материалы"
      date="Сейчас"
      {...props}
    />,
  );
  return props;
}

describe("chat item", () => {
  it("renames in place with Enter and keeps the title on Escape", async () => {
    const { onRename } = view();
    await userEvent.click(
      screen.getByRole("button", { name: "Действия с чатом" }),
    );
    await userEvent.click(
      screen.getByRole("menuitem", { name: "Переименовать" }),
    );
    const field = screen.getByLabelText("Новое название чата");
    await userEvent.clear(field);
    await userEvent.type(field, "Колесо насоса{Enter}");
    expect(onRename).toHaveBeenCalledWith("Колесо насоса");
    await userEvent.click(
      screen.getByRole("button", { name: "Действия с чатом" }),
    );
    await userEvent.click(
      screen.getByRole("menuitem", { name: "Переименовать" }),
    );
    await userEvent.type(
      screen.getByLabelText("Новое название чата"),
      "x{Escape}",
    );
    expect(onRename).toHaveBeenCalledTimes(1);
  });
  it("deletes only after confirmation", async () => {
    const { onDelete } = view();
    await userEvent.click(
      screen.getByRole("button", { name: "Действия с чатом" }),
    );
    await userEvent.click(screen.getByRole("menuitem", { name: "Удалить" }));
    expect(onDelete).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("menuitem", { name: "Отмена" }));
    expect(screen.queryByRole("menu")).toBeNull();
    await userEvent.click(
      screen.getByRole("button", { name: "Действия с чатом" }),
    );
    await userEvent.click(screen.getByRole("menuitem", { name: "Удалить" }));
    await userEvent.click(
      screen.getByRole("menuitem", { name: "Удалить чат" }),
    );
    expect(onDelete).toHaveBeenCalledTimes(1);
  });
});

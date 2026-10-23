import { test, expect } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { open } from "./helpers";

test("T12 A04 older chats and messages remain accessible through cursors", async ({
  page,
}) => {
  await open(page);
  const id = new URL(page.url()).searchParams.get("job")!;
  // A page holds 100 messages; every message is a new revision of the same task.
  for (let index = 0; index < 101; index++) {
    const response = await page.request.post(`/api/v1/jobs/${id}/messages`, {
      data: {
        request_id: randomUUID(),
        text: `Архивная запись ${index}`,
      },
    });
    expect(response.ok()).toBe(true);
  }
  await page.reload();
  const thread = page.getByRole("main");
  await expect(
    thread.getByText("Архивная запись 0", { exact: true }),
  ).not.toBeVisible();
  await page
    .getByRole("button", { name: "Предыдущие сообщения", exact: true })
    .click();
  await expect(
    thread.getByText("Архивная запись 0", { exact: true }),
  ).toBeVisible();
  const title = `Архивный чат ${randomUUID()}`;
  await page.request.post("/api/v1/jobs", {
    data: { request_id: randomUUID(), title },
  });
  for (let index = 0; index < 51; index++)
    await page.request.post("/api/v1/jobs", {
      data: { request_id: randomUUID(), title: `Последующий чат ${index}` },
    });
  await page.reload();
  await expect(
    page.getByRole("button", { name: title, exact: false }),
  ).not.toBeVisible();
  await page
    .getByRole("button", { name: "Загрузить ещё чаты", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: title, exact: false }),
  ).toBeVisible();
});

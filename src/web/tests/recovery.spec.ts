import { test, expect } from "@playwright/test";
import { answer, open, send, settled, upload } from "./helpers";
test.beforeEach(async ({ page }) => open(page));

test("T12 reconnect catches up and reopens same task", async ({
  page,
  context,
}) => {
  await send(page, "Сохранённый запрос");
  await settled(page);
  const url = page.url();
  await context.setOffline(true);
  await page.getByText("Соединение потеряно, переподключаемся").waitFor();
  await context.setOffline(false);
  await expect(
    page.getByText("Соединение потеряно, переподключаемся"),
  ).not.toBeVisible();
  const second = await context.newPage();
  await second.goto(url);
  await expect(
    second.getByText("Сохранённый запрос", { exact: true }).first(),
  ).toBeVisible();
});

test("T11 stop at safe point, resume, retain correction", async ({ page }) => {
  await send(page, "TEST_DELAY Шестерня");
  await expect(
    page.getByRole("status").filter({ hasText: "Обрабатываю" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Остановить", exact: true }).click();
  await expect(
    page.getByRole("status").filter({ hasText: "Остановлено" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Продолжить", exact: true }).click();
  await settled(page);
  await send(page, "Изменить момент на 30 Нм");
  await settled(page);
  await expect(
    page.getByText("Изменить момент на 30 Нм", { exact: true }).first(),
  ).toBeVisible();
});

test("T01 remove corrupt attachment unblocks document preparation", async ({
  page,
}) => {
  await upload(page, "corrupt.pdf");
  await page
    .getByText("Не удалось прочитать файл", { exact: false })
    .first()
    .waitFor();
  await page
    .getByRole("region", { name: "Вложения" })
    .getByLabel("Действия с файлом", { exact: true })
    .click();
  await page
    .getByRole("button", { name: "Убрать corrupt.pdf", exact: true })
    .click();
  await expect(
    page.getByRole("link", { name: "corrupt.pdf", exact: true }),
  ).not.toBeVisible();
  await send(page, "Декоративная фигурка");
  await settled(page);
  await expect(page.getByText("Не прочитаны файлы corrupt.pdf")).toHaveCount(0);
});

test("T14 draft survives network error and double submit sends once", async ({
  page,
}) => {
  await page.route("**/messages", (route) => route.abort());
  await send(page, "Не потерять текст");
  await expect(page.getByLabel("Сообщение", { exact: true })).toHaveValue(
    "Не потерять текст",
  );
  await page.unroute("**/messages");
  await page.getByRole("button", { name: "Отправить", exact: true }).dblclick();
  await settled(page);
  const messages = await page.evaluate(async () => {
    const id = new URLSearchParams(location.search).get("job");
    return (await (await fetch(`/api/v1/jobs/${id}`)).json()).messages;
  });
  expect(
    messages.filter(
      (m: { role: string; text: string }) =>
        m.role === "user" && m.text === "Не потерять текст",
    ),
  ).toHaveLength(1);
});

test("T13 downloaded card embeds the full STL report of the active file", async ({
  page,
}) => {
  await send(page, "Фигурка");
  await upload(page, "box.stl");
  await settled(page);
  await answer(page, "mm");
  await expect(
    page.getByRole("status").filter({ hasText: "Первый этап завершён" }),
  ).toBeVisible();
  const href = await page
    .getByRole("link", { name: "Скачать карточку JSON" })
    .getAttribute("href");
  const result = await page.request.get(href!);
  expect(result.ok()).toBe(true);
  const card = await result.json();
  expect(card.schema_version).toBe("2.0");
  expect(card.geometry.units).toBe("mm");
  expect(
    card.questions.find((q: { id: string }) => q.id === "units").answer,
  ).toBe("mm");
  expect(card.stl_analysis.sha256).toMatch(/^[a-f0-9]{64}$/);
  expect(card.stl_analysis.report.file.sha256).toBe(card.stl_analysis.sha256);
  expect(card.stl_analysis.report.units.input_unit).toBe("mm");
  const raw = await page.request.get(
    result
      .url()
      .replace(/\/card$/, `/artifacts/${card.geometry.report_id}.json`),
  );
  expect(raw.ok()).toBe(true);
  // JSONB preserves numeric values, but canonicalizes IEEE negative zero to zero.
  const sourceReport = JSON.parse(JSON.stringify(await raw.json()));
  expect(sourceReport).toEqual(card.stl_analysis.report);
});

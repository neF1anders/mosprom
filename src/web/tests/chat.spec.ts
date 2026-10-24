import { readFile } from "node:fs/promises";
import { test, expect } from "@playwright/test";
import {
  answer,
  answered,
  attach,
  open,
  PIPELINE_DONE,
  pipelineDone,
  send,
  settled,
  upload,
} from "./helpers";

test.beforeEach(async ({ page }) => open(page));

test("T12 refresh preserves messages and questions", async ({ page }) => {
  await send(page, "TEST_QUESTIONS Шестерня привода");
  await settled(page);
  await page.reload();
  await expect(
    page.getByText("TEST_QUESTIONS Шестерня привода", { exact: true }).first(),
  ).toBeVisible();
  await expect(
    page.getByRole("region", { name: "Уточняющие вопросы" }),
  ).toBeVisible();
});
for (const [name, expected] of [
  ["empty.txt", "Файл пуст"],
  ["spoof.pdf", "Файл не является PDF"],
  ["corrupt.pdf", "Не удалось прочитать файл"],
  ["encrypted.pdf", "PDF защищён паролем"],
  ["too-many-pages.pdf", "В PDF больше 50 страниц"],
]) {
  test(`T01 T02 upload ${name}`, async ({ page }) => {
    if (name === "empty.txt") await attach(page, name);
    else await upload(page, name);
    await expect(
      page.getByText(expected, { exact: false }).first(),
    ).toBeVisible();
  });
}
test("attached files wait in the composer for an explicit send", async ({
  page,
}) => {
  await attach(page, "task.txt");
  const drafts = page.getByRole("list", { name: "Вложения к сообщению" });
  await expect(drafts.getByText("task.txt", { exact: true })).toBeVisible();
  await expect(drafts.locator("[aria-busy]")).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Ход работы" })).toHaveCount(0);
  await send(page, "Шестерня по ТЗ во вложении");
  await settled(page);
  await expect(drafts).toHaveCount(0);
  await expect(
    page.getByRole("link", { name: "task.txt", exact: true }),
  ).toBeVisible();
});
test("removing an unsent file leaves nothing to send", async ({ page }) => {
  await attach(page, "photo.png");
  const drafts = page.getByRole("list", { name: "Вложения к сообщению" });
  await expect(drafts.locator("[aria-busy]")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Отправить", exact: true }),
  ).toBeEnabled();
  await drafts.getByRole("listitem").hover();
  await drafts.getByRole("button", { name: "Убрать photo.png" }).click();
  await expect(drafts).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Отправить", exact: true }),
  ).toBeDisabled();
});
for (const name of [
  "task.txt",
  "task.docx",
  "text.pdf",
  "scan.pdf",
  "mixed.pdf",
  "photo.png",
]) {
  test(`T02 T03 document ${name}`, async ({ page }) => {
    await upload(page, name);
    await settled(page);
    await page.getByLabel("Показать требования", { exact: true }).click();
    await expect(
      page
        .getByRole("complementary", { name: "Карточка задания" })
        .locator("summary")
        .filter({ hasText: /25/ })
        .first(),
    ).toBeVisible();
    await expect(
      page
        .getByRole("complementary", { name: "Карточка задания" })
        .locator("summary")
        .filter({ hasText: /75/ })
        .first(),
    ).toBeVisible();
    if (name.endsWith(".pdf") || name === "photo.png") {
      const panel = page.getByRole("complementary", {
        name: "Карточка задания",
      });
      await panel.locator("summary").filter({ hasText: /25/ }).first().click();
      const image = panel
        .getByRole("link", { name: "Посмотреть страницу" })
        .first();
      await expect(image).toBeVisible();
      const response = await page.request.get(
        (await image.getAttribute("href"))!,
      );
      expect(response.ok()).toBe(true);
      expect(response.headers()["content-type"]).toContain("image/png");
      if (name === "scan.pdf" || name === "photo.png") {
        await expect(
          panel.getByText(/прочитано по изображению/).first(),
        ).toBeVisible();
      }
    }
  });
}
for (const [name, expected] of [
  ["box.stl", "10 × 20 × 30"],
  ["open.stl", "Открытая поверхность"],
  ["duplicate.stl", "Повторяющиеся грани"],
  ["shells.stl", "Несколько оболочек"],
  ["nan.stl", "Файл STL повреждён или не читается"],
]) {
  test(`T04 mesh ${name}`, async ({ page }) => {
    await upload(page, name);
    await expect(
      page.getByText(expected, { exact: false }).first(),
    ).toBeVisible();
  });
}
for (const option of ["mm", "cm", "m", "inch", "Не знаю"]) {
  test(`T07 units are asked first ${option}`, async ({ page }) => {
    await upload(page, "box.stl");
    await settled(page);
    await expect(
      page.getByRole("heading", { name: "В каких единицах создан STL" }),
    ).toBeVisible();
    await answer(page, option);
    await answered(page, "В каких единицах создан STL", option);
    await settled(page);
    if (option === "Не знаю")
      await expect(page.getByText("Раньше вы ответили Не знаю")).toBeVisible();
    // In metres or inches the box is larger than every working area of the printer.
    if (option === "m" || option === "inch")
      await expect(
        page
          .getByRole("status")
          .filter({ hasText: "Параметры требуют внимания" }),
      ).toBeVisible();
  });
}
for (const choice of ["80 мм", "100 мм", "90 мм", "Не знаю"]) {
  test(`T08 disagreeing sources ${choice}`, async ({ page }) => {
    await upload(page, "conflict.txt");
    await settled(page);
    const window = page.getByRole("region", { name: "Уточняющие вопросы" });
    await expect(window.getByText("Нужно ваше подтверждение")).toBeVisible();
    await expect(window.getByRole("button", { pressed: true })).toHaveCount(0);
    if (choice === "90 мм") {
      await window.getByLabel("Свой ответ").fill(choice);
      await window.getByRole("button", { name: "Отправить ответы" }).click();
    } else await answer(page, choice);
    await answered(page, "Источники расходятся, Длина детали", choice);
    await settled(page);
  });
}
test("T09 tool call is visible in the journal", async ({ page }) => {
  await send(page, "TEST_TOOL Перевести дюймы");
  await settled(page);
  await page.getByLabel("Показать журнал вызовов", { exact: true }).click();
  await expect(
    page.getByText("Разбор ТЗ, переводит единицы", { exact: true }),
  ).toBeVisible();
});
for (const message of ["TEST_PROVIDER_401", "TEST_PROVIDER_INVALID_JSON"]) {
  test(`T10 ${message}`, async ({ page }) => {
    await send(page, message);
    await expect(
      page.getByRole("button", { name: "Повторить позже" }),
    ).toBeVisible();
  });
}
for (const text of [
  "Новый момент 30 Нм",
  "Новая температура 80 C",
  "Добавить герметичность",
  "Количество 15",
  "Нужна стойкость к маслу",
]) {
  test(`T11 edit ${text}`, async ({ page }) => {
    await send(page, "Шестерня привода");
    await settled(page);
    await send(page, text);
    await expect(page.getByText(text, { exact: true }).first()).toBeVisible();
    await settled(page);
    await page.reload();
    await expect(page.getByText(text, { exact: true }).first()).toBeVisible();
  });
}
test("T15 off-topic message gets a short reply without a run", async ({
  page,
}) => {
  await send(page, "TEST_OFFTOPIC Какая погода");
  // The reply is in the thread; the card journal repeats it as an event.
  await expect(
    page
      .getByRole("main")
      .getByText("Я помогаю только с подготовкой задания на печать"),
  ).toBeVisible();
  await settled(page);
  const card = page.getByRole("complementary", { name: "Карточка задания" });
  await expect(card.getByText("Нет данных").first()).toBeVisible();
  // The declined message never reaches the agents, so the purpose comes from the new one.
  await send(page, "Шестерня привода");
  await settled(page);
  await expect(
    card.getByText("Шестерня привода", { exact: true }),
  ).toBeVisible();
});
for (const width of [390, 600, 800, 1100, 1440]) {
  test(`T14 viewport ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await expect(page.getByLabel("Сообщение", { exact: true })).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Прикрепить файлы" }),
    ).toBeVisible();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth > innerWidth,
    );
    expect(overflow).toBe(false);
  });
}
test("T14 keyboard send and panels", async ({ page }) => {
  await page.getByLabel("Сообщение", { exact: true }).fill("Клавиатура");
  await page.getByLabel("Сообщение", { exact: true }).press("Enter");
  await settled(page);
  await page.getByRole("button", { name: "Свернуть карточку" }).click();
  await page.getByRole("button", { name: "Карточка", exact: true }).click();
  await expect(
    page.getByRole("complementary", { name: "Карточка задания" }),
  ).toBeVisible();
});
test("T13 a ready card goes through parameter selection and its check", async ({
  page,
}) => {
  await send(page, "Шестерня привода");
  await upload(page, "box.stl");
  await settled(page);
  await answer(page, "mm");
  await pipelineDone(page);
  const timeline = page.getByRole("region", { name: "Ход работы" });
  for (const title of ["Подбор параметров", "Валидация"])
    await expect(
      timeline.locator("details").filter({
        has: page.getByText(title, { exact: true }),
      }),
    ).toHaveAttribute("data-state", /done|warn/);
  await expect(timeline.getByText("Что подобрано")).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Скачать карточку JSON" }),
  ).toBeVisible();
});
test("T16 the parameter set downloads as the server keeps it", async ({
  page,
}) => {
  await send(page, "Кронштейн датчика");
  await upload(page, "box.stl");
  await settled(page);
  await answer(page, "mm");
  await pipelineDone(page);
  const link = page.getByRole("link", { name: "Скачать параметры JSON" });
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    link.click(),
  ]);
  const saved = JSON.parse(
    await readFile((await download.path()) as string, "utf-8"),
  );
  const job = new URL(page.url()).searchParams.get("job");
  const served = await (
    await page.request.get(`/api/v1/jobs/${job}/parameters`)
  ).json();
  expect(saved).toEqual(served);
  expect([saved.contract, saved.version]).toEqual([
    "stage2.parameter_set",
    "0.2",
  ]);
  expect(saved.printer).toBe("hte530v5.2.4");
});
test("T17 an edit after a ready card is processed", async ({ page }) => {
  await send(page, "Шестерня привода");
  await upload(page, "box.stl");
  await settled(page);
  await answer(page, "mm");
  const done = page.getByRole("status").filter({ hasText: PIPELINE_DONE });
  await expect(done).toBeVisible();
  const job = new URL(page.url()).searchParams.get("job");
  const snapshot = async () =>
    (await (await page.request.get(`/api/v1/jobs/${job}`)).json()).job;
  const before = (await snapshot()).revision;
  await send(page, "Допуск на посадочное отверстие 0,1 мм");
  // Work queued for the ready card must not hold the edit back.
  await expect
    .poll(async () => {
      const current = await snapshot();
      return [current.revision, current.status];
    })
    .toEqual([before + 1, "completed"]);
  await expect(done).toBeVisible();
});

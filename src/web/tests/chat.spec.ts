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
  task,
  upload,
} from "./helpers";

test.beforeEach(async ({ page }) => open(page));

test("T12 refresh preserves messages and questions", async ({ page }) => {
  await task(page, "TEST_QUESTIONS Шестерня привода");
  await settled(page);
  const window = page.getByRole("region", { name: "Уточняющие вопросы" });
  await expect(window).toBeVisible();
  await page.reload();
  await expect(
    page.getByText("TEST_QUESTIONS Шестерня привода", { exact: true }).first(),
  ).toBeVisible();
  await expect(window).toBeVisible();
  await expect(window.getByText("1 из 2")).toBeVisible();
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
    // The model goes with the document, or the assistant only talks about it.
    await upload(page, name, "box.stl");
    await settled(page);
    const panel = page.getByRole("complementary", {
      name: "Карточка задания",
    });
    await panel
      .getByRole("button", { name: /Обязательные требования/ })
      .click();
    // The items of a section are listed inside its step.
    const items = panel.locator("li li");
    await expect(items.filter({ hasText: /25/ }).first()).toBeVisible();
    await expect(items.filter({ hasText: /75/ }).first()).toBeVisible();
    // A value named by a requirement code reaches the card under that code.
    if (name === "task.txt")
      await expect(
        items
          .filter({ hasText: "Максимальная рабочая температура детали" })
          .filter({ hasText: /от 10 до 70 °C/ }),
      ).toBeVisible();
    if (name.endsWith(".pdf") || name === "photo.png") {
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
  ["open.stl", "открытая поверхность"],
  ["duplicate.stl", "дублирующие грани"],
  ["shells.stl", "несколько оболочек"],
  ["nan.stl", "Файл STL повреждён или не читается"],
]) {
  test(`T04 mesh ${name}`, async ({ page }) => {
    await upload(page, name);
    // A defect the card settled is listed in the opened geometry section.
    if (/поверхность|грани|оболочек/.test(expected)) {
      await settled(page);
      const panel = page.getByRole("complementary", {
        name: "Карточка задания",
      });
      const geometry = panel.getByRole("button", { name: /Геометрия/ });
      if ((await geometry.getAttribute("aria-expanded")) === "false")
        await geometry.click();
    }
    await expect(
      page.getByText(expected, { exact: false }).first(),
    ).toBeVisible();
  });
}
for (const choice of ["80 мм", "100 мм", "90 мм", "Не знаю"]) {
  test(`T08 disagreeing sources ${choice}`, async ({ page }) => {
    await upload(page, "conflict.txt", "box.stl");
    await settled(page);
    const window = page.getByRole("region", { name: "Уточняющие вопросы" });
    await expect(window.getByText("Нужно ваше подтверждение")).toBeVisible();
    await expect(
      window.getByRole("heading", {
        name: "Источники расходятся, Длина детали",
      }),
    ).toBeVisible();
    await expect(window.getByRole("button", { pressed: true })).toHaveCount(0);
    if (choice === "90 мм") {
      await window.getByLabel("Свой ответ").fill(choice);
      await window.getByRole("button", { name: "Отправить ответы" }).click();
    } else await answer(page, choice);
    await answered(page, "Источники расходятся, Длина детали", choice);
    // The checker takes the answers in its own dialog and asks nothing more.
    await pipelineDone(page);
    await expect(window).toHaveCount(0);
    if (choice === "Не знаю") {
      const card = page.getByRole("complementary", {
        name: "Карточка задания",
      });
      await card
        .getByRole("button", { name: /Допущения и неизвестные/ })
        .click();
      await expect(card.getByText("не удалось уточнить").first()).toBeVisible();
      await expect(
        card
          .getByText("Источники расходятся, Длина детали, принято без ответа", {
            exact: false,
          })
          .first(),
      ).toBeAttached();
    }
  });
}
test("T08 a model that disagrees with the specification asks which is right", async ({
  page,
}) => {
  await task(page, "TEST_STL_MISMATCH Длина детали 100 мм");
  await settled(page);
  const window = page.getByRole("region", { name: "Уточняющие вопросы" });
  await expect(window.getByText("Нужно ваше подтверждение")).toBeVisible();
  await expect(
    window.getByRole("heading", { name: "Длина в ТЗ 100 мм, в модели 30 мм" }),
  ).toBeVisible();
  await answer(page, "Верна модель STL");
  await answered(page, "Длина в ТЗ 100 мм, в модели 30 мм", "Верна модель STL");
  await pipelineDone(page);
});
test("T09 tool call is visible in the timeline", async ({ page }) => {
  await task(page, "TEST_TOOL Перевести дюймы");
  await settled(page);
  const timeline = page.getByRole("region", { name: "Ход работы" });
  const stage = timeline.locator("details").filter({
    has: page.getByText("Интерпретация задания", { exact: true }),
  });
  if ((await stage.getAttribute("open")) === null)
    await stage.locator("summary").click();
  await expect(timeline.getByText(/^Перев(ожу|ёл) /)).toBeVisible();
});
for (const message of ["TEST_PROVIDER_401", "TEST_PROVIDER_INVALID_JSON"]) {
  test(`T10 ${message}`, async ({ page }) => {
    await task(page, message);
    // A refused call leaves the assistant without an answer, which it says; a broken
    // answer fails the work at the interpreter.
    if (message === "TEST_PROVIDER_401")
      await expect(page.getByText(/модель не отвечает/)).toBeVisible();
    else
      await expect(
        page.getByRole("button", { name: "Повторить", exact: true }),
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
    await task(page, "Шестерня привода");
    await pipelineDone(page);
    await send(page, text);
    await expect(page.getByText(text, { exact: true }).first()).toBeVisible();
    await settled(page);
    await page.reload();
    await expect(page.getByText(text, { exact: true }).first()).toBeVisible();
  });
}
test("T15 off-topic message gets a reply from the assistant without a run", async ({
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
  // A task with a model starts the work; the small talk does not describe the part.
  await task(page, "Шестерня привода");
  await pipelineDone(page);
  await expect(
    card.getByText("Шестерня привода", { exact: true }),
  ).toBeVisible();
});
test("T15 a reply in the chat after the project keeps the project", async ({
  page,
}) => {
  await task(page, "Шестерня привода");
  await pipelineDone(page);
  await send(page, "TEST_OFFTOPIC Спасибо");
  await expect(
    page
      .getByRole("main")
      .getByText("Я помогаю только с подготовкой задания на печать"),
  ).toBeVisible();
  await pipelineDone(page);
  // Nothing ran again: the timeline and the files are those of the work before.
  const job = new URL(page.url()).searchParams.get("job");
  const snapshot = await (await page.request.get(`/api/v1/jobs/${job}`)).json();
  expect(snapshot.job.work_revision).toBe(snapshot.job.revision);
  expect(snapshot.job.status).toBe("completed");
  const timeline = page.getByRole("region", { name: "Ход работы" });
  for (const title of ["Подбор параметров", "Слайсинг"])
    await expect(
      timeline.locator("details").filter({
        has: page.getByText(title, { exact: true }),
      }),
    ).toHaveAttribute("data-state", /done|warn/);
  const project = await page.request.get(`/api/v1/jobs/${job}/result/project`);
  expect(project.status()).toBe(200);
});
test("T15 the assistant asks for details, the next message starts the work", async ({
  page,
}) => {
  await task(page, "TEST_GATE_ASK Деталь");
  await expect(
    page.getByRole("main").getByText(/Расскажите подробнее о детали/),
  ).toBeVisible();
  await settled(page);
  const card = page.getByRole("complementary", { name: "Карточка задания" });
  await expect(card.getByText("Нет данных").first()).toBeVisible();
  // The model sent with the first message still waits for a project.
  await send(page, "Шестерня привода");
  await pipelineDone(page);
  await expect(
    page.getByRole("main").getByText(/Расскажите подробнее о детали/),
  ).toHaveCount(1);
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
  await page
    .getByRole("button", { name: "Показать карточку", exact: true })
    .click();
  await expect(
    page.getByRole("complementary", { name: "Карточка задания" }),
  ).toBeVisible();
});
test("T13 a ready card goes through every stage to a project", async ({
  page,
}) => {
  await task(page, "Шестерня привода");
  await pipelineDone(page);
  const timeline = page.getByRole("region", { name: "Ход работы" });
  const stages = [
    "Интерпретация задания",
    "Подбор параметров",
    "Валидация",
    "Слайсинг",
    "Подготовка результата",
  ];
  for (const title of stages)
    await expect(
      timeline.locator("details").filter({
        has: page.getByText(title, { exact: true }),
      }),
    ).toHaveAttribute("data-state", /done|warn/);
  await expect(timeline.getByText("Что подобрано")).toBeVisible();
  // The test stack slices with the stand-in of the plugin.
  await expect(timeline.getByText("Что получилось")).toBeVisible();
  const job = new URL(page.url()).searchParams.get("job");
  const project = await page.request.get(`/api/v1/jobs/${job}/result/project`);
  expect(project.status()).toBe(200);
  await expect(
    page.getByRole("link", { name: "карточка_задания.json" }),
  ).toBeVisible();
});
test("T18 a model larger than the printer asks for attention", async ({
  page,
}) => {
  // The model is 10 by 20 by 30 m, larger than every working area.
  await task(page, "Шестерня привода", "large.stl");
  await expect(
    page.getByRole("status").filter({ hasText: "Параметры требуют внимания" }),
  ).toBeVisible();
  await expect(
    page.getByText("Не проводилась, параметры подобрать не удалось").first(),
  ).toBeAttached();
  await expect(
    page
      .getByText(/Подобрать параметры под все требования не получилось/)
      .first(),
  ).toBeVisible();
});
test("T16 the parameter set downloads as the server keeps it", async ({
  page,
}) => {
  await task(page, "Кронштейн датчика");
  await pipelineDone(page);
  const link = page.getByRole("link", { name: "параметры.json" });
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
  await task(page, "Шестерня привода");
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
  // The edit names a requirement code, so the new card carries it.
  const card = (await snapshot()).card;
  expect(
    card.requirements.find(
      (r: { key: string }) => r.key === "dimensional_tol_mm",
    )?.value,
  ).toBe("0,1");
});

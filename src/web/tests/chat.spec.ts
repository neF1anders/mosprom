import { test, expect } from "@playwright/test";
import { open, send, settled, upload } from "./helpers";

test.beforeEach(async ({ page }) => open(page));

test("T12 refresh preserves messages and questions", async ({ page }) => {
  await send(page, "Шестерня привода");
  await settled(page);
  await page.reload();
  await expect(
    page.getByText("Шестерня привода", { exact: true }).first(),
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
    await upload(page, name);
    await expect(
      page.getByText(expected, { exact: false }).first(),
    ).toBeVisible();
  });
}
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
  ["nan.stl", "NaN"],
]) {
  test(`T04 mesh ${name}`, async ({ page }) => {
    await upload(page, name);
    await expect(
      page.getByText(expected, { exact: false }).first(),
    ).toBeVisible();
  });
}
for (const answer of ["mm", "cm", "m", "inch", "Не знаю"]) {
  test(`T07 units ${answer}`, async ({ page }) => {
    await send(page, "Шестерня привода");
    await settled(page);
    await page.getByRole("button", { name: answer, exact: true }).click();
    await page.getByRole("button", { name: "Отправить ответы" }).click();
    await settled(page);
    await expect(
      page.getByText(`geometry.units = ${answer}`, { exact: true }),
    ).toBeVisible();
  });
}
for (const answer of ["80 мм", "100 мм", "Не знаю", "90 мм", "100,5 мм"]) {
  test(`T08 conflict ${answer}`, async ({ page }) => {
    await send(page, "TEST_CONFLICT Размер детали");
    await settled(page);
    const conflict = page.getByRole("region", {
      name: "Расхождение источников",
    });
    await expect(
      conflict.getByRole("button", { name: "Подтвердить выбор" }),
    ).toBeDisabled();
    if (answer === "Не знаю") {
      await conflict.getByRole("button", { name: answer, exact: true }).click();
    } else {
      await conflict.getByLabel("Своё значение").fill(answer);
      await conflict.getByRole("button", { name: "Подтвердить выбор" }).click();
    }
    await expect(
      page.getByText(`test-size = ${answer}`, { exact: true }),
    ).toBeVisible();
  });
}
test("T09 tool call is visible", async ({ page }) => {
  await send(page, "TEST_TOOL плотность Proto PLA");
  await settled(page);
  await page.getByLabel("Показать журнал вызовов", { exact: true }).click();
  await expect(
    page.getByText("Завершён search_knowledge", { exact: true }),
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
  await page.getByLabel("Сообщение", { exact: true }).press("Control+Enter");
  await settled(page);
  await page.getByRole("button", { name: "Свернуть карточку" }).click();
  await page.getByRole("button", { name: "Карточка", exact: true }).click();
  await expect(
    page.getByRole("complementary", { name: "Карточка задания" }),
  ).toBeVisible();
});
test("T13 ready card export and honest handoff", async ({ page }) => {
  await send(page, "Шестерня привода");
  await upload(page, "box.stl");
  await settled(page);
  await page.getByRole("button", { name: "mm", exact: true }).click();
  await page.getByRole("button", { name: "Отправить ответы" }).click();
  await expect(
    page.getByRole("status").filter({ hasText: "Первый этап завершён" }),
  ).toBeVisible();
  await expect(
    page
      .getByText("Карточка подготовлена, следующий этап не подключён")
      .first(),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Скачать карточку JSON" }),
  ).toBeVisible();
});

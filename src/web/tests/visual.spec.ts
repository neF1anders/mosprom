import { test, expect } from "@playwright/test";
import { open, send, settled } from "./helpers";
test("T14 Figma desktop and narrow view artifacts", async ({ page }, info) => {
  await open(page);
  await page.setViewportSize({ width: 1440, height: 1024 });
  await page.screenshot({ path: info.outputPath("start-desktop.png") });
  await send(page, "TEST_QUESTIONS Проверка макета");
  await settled(page);
  await page.screenshot({ path: info.outputPath("questions-desktop.png") });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: info.outputPath("questions-mobile.png"),
    fullPage: true,
  });
});

test("T14 narrow panels open as drawers and close with Escape", async ({
  page,
}) => {
  await open(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(
    page.getByRole("heading", { name: "Карточка задания", exact: true }),
  ).not.toBeVisible();
  await page
    .getByRole("button", { name: "Открыть карточку", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Карточка задания", exact: true }),
  ).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(
    page.getByRole("heading", { name: "Карточка задания", exact: true }),
  ).not.toBeVisible();
  await page.getByRole("button", { name: "Открыть чаты", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Чаты", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Закрыть панель", exact: true })
    .click({ position: { x: 5, y: 5 } });
  await expect(page.getByLabel("Сообщение", { exact: true })).toBeVisible();
});

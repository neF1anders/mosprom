import { test, expect } from "@playwright/test";
import { designFixture, designStates } from "./figma-fixtures";

for (const state of designStates)
  test(`Figma ${state}: panels, controls and intrinsic SVG geometry`, async ({
    page,
  }, info) => {
    await designFixture(page, state);
    await page.setViewportSize({ width: 1440, height: 1024 });
    await page.goto("/?job=design");
    await expect(
      page.getByText("Крышка редуктора", { exact: true }),
    ).toBeVisible();
    await page.evaluate(() => document.fonts.ready);
    if (state === "offline")
      await page.evaluate(() => window.dispatchEvent(new Event("offline")));
    if (state === "questions")
      await expect(
        page.getByRole("region", { name: "Уточняющие вопросы" }),
      ).toBeVisible();
    if (state === "conflict") {
      await expect(page.getByText("Нужно ваше подтверждение")).toBeVisible();
      await expect(page.getByRole("button", { pressed: true })).toHaveCount(0);
    }
    await expect(
      page.getByRole("complementary", { name: "Карточка задания" }),
    ).toHaveCSS("background-color", "rgb(245, 245, 247)");
    expect(
      await page
        .getByRole("complementary", { name: "Карточка задания" })
        .boundingBox(),
    ).toEqual({ x: 1064, y: 64, width: 360, height: 944 });
    expect(
      await page
        .getByRole("navigation", { name: "Задания" })
        .locator("..")
        .boundingBox(),
    ).toEqual({ x: 16, y: 64, width: 260, height: 944 });
    expect(await page.locator("form").boundingBox()).toEqual({
      x: 310,
      y: 915,
      width: 720,
      height: 93,
    });
    if (state === "start")
      expect(
        await page
          .getByRole("heading", { name: "Как работает плагин" })
          .boundingBox(),
      ).toMatchObject({ x: 310, y: 700, height: 26 });
    await expect(async () => {
      const mismatches = await page
        .locator('img[src^="/figma/"]')
        .evaluateAll((images) =>
          images.flatMap((element) => {
            const img = element as HTMLImageElement;
            if (!img.getClientRects().length) return [];
            const box = img.getBoundingClientRect();
            return !img.complete ||
              !img.naturalWidth ||
              box.width !== img.naturalWidth ||
              box.height !== img.naturalHeight
              ? [
                  {
                    source: img.src,
                    width: box.width,
                    height: box.height,
                    natural: [img.naturalWidth, img.naturalHeight],
                  },
                ]
              : [];
          }),
        );
      expect(mismatches).toEqual([]);
    }).toPass();
    await page.screenshot({ path: info.outputPath(`${state}.png`) });
    if (state === "start") {
      const navigation = page.getByRole("navigation", { name: "Задания" });
      await navigation
        .locator("button span")
        .first()
        .evaluate((element) => {
          element.textContent = "Очень длинное название детали ".repeat(20);
        });
      expect(
        await navigation.evaluate(
          (element) => element.scrollWidth <= element.clientWidth,
        ),
      ).toBe(true);
    }
  });

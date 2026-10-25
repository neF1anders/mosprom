import { test, expect, type Page } from "@playwright/test";
import { open, pipelineDone, send, task } from "./helpers";
test.beforeEach(async ({ page }) => open(page));

// The work of a chat runs on the server, so leaving the chat never stops it.
// The timeline shows once the work has begun, whatever stage it is at.
async function working(page: Page) {
  await expect(page.getByRole("region", { name: "Ход работы" })).toBeVisible();
}

test("T19 a chat keeps working while the user talks in another one", async ({
  page,
}) => {
  await task(page, "TEST_DELAY Шестерня привода");
  await working(page);
  const first = page.url();
  await page
    .getByRole("button", { name: "Новое задание", exact: true })
    .click();
  await page.waitForURL((url) => url.href !== first);
  const second = new URL(page.url()).searchParams.get("job");
  await send(page, "TEST_OFFTOPIC Какая погода");
  await expect(
    page
      .getByRole("main")
      .getByText("Я помогаю только с подготовкой задания на печать"),
  ).toBeVisible();
  await page
    .getByRole("navigation", { name: "Задания" })
    .getByRole("button", { name: /TEST_DELAY Шестерня привода/ })
    .click();
  await pipelineDone(page);
  // The timeline of the first chat came back whole, with every stage it went through.
  const timeline = page.getByRole("region", { name: "Ход работы" });
  for (const title of ["Подбор параметров", "Слайсинг"])
    await expect(
      timeline.locator("details").filter({
        has: page.getByText(title, { exact: true }),
      }),
    ).toHaveAttribute("data-state", /done|warn/);
  // The second chat only talked, so nothing started there.
  const other = await (await page.request.get(`/api/v1/jobs/${second}`)).json();
  expect(other.job.status).toBe("draft");
});

test("T19 closing the plugin window leaves the work going", async ({
  page,
  context,
}) => {
  await task(page, "TEST_DELAY Шестерня привода");
  await working(page);
  const url = page.url();
  await page.close();
  const again = await context.newPage();
  await again.goto(url);
  await pipelineDone(again);
  await expect(
    again.getByText("TEST_DELAY Шестерня привода", { exact: true }).first(),
  ).toBeVisible();
  // The work went on from where it was, it did not start over.
  const id = new URL(url).searchParams.get("job");
  const snapshot = await (await again.request.get(`/api/v1/jobs/${id}`)).json();
  expect(snapshot.job.revision).toBe(1);
});

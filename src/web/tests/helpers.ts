import { expect, type Page } from "@playwright/test";
import { createHmac, randomUUID } from "node:crypto";
import path from "node:path";
const secret =
  process.env.E2E_SESSION_SECRET ||
  "test-only-session-secret-never-use-for-real-data";
const fixture = (name: string) => path.resolve("../../tests/fixtures", name);
function token() {
  const payload = Buffer.from(
    JSON.stringify({
      kind: "launch",
      expires: Math.floor(Date.now() / 1000) + 600,
      nonce: randomUUID(),
      user_id: "e2e",
    }),
  ).toString("base64url");
  return (
    payload + "." + createHmac("sha256", secret).update(payload).digest("hex")
  );
}
export async function open(page: Page) {
  await page.goto("/#launch=" + token());
  await page
    .getByRole("button", { name: "Новое задание", exact: true })
    .click();
  await page.waitForURL((url) => url.searchParams.has("job"));
  await expect(page.getByLabel("Сообщение", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Выбрать файлы", { exact: true })).toBeEnabled();
}
export async function send(page: Page, text: string) {
  await page.getByLabel("Сообщение", { exact: true }).fill(text);
  await page.getByRole("button", { name: "Отправить", exact: true }).click();
}
export async function settled(page: Page) {
  await expect(
    page.getByRole("status").filter({
      hasText: /Нужны уточнения|Первый этап завершён|Ошибка обработки/,
    }),
  ).toBeVisible();
}
export async function attach(page: Page, name: string) {
  await page
    .getByLabel("Выбрать файлы", { exact: true })
    .setInputFiles(fixture(name));
}
export async function upload(page: Page, name: string) {
  await attach(page, name);
  const sendButton = page.getByRole("button", {
    name: "Отправить",
    exact: true,
  });
  await expect(sendButton).toBeEnabled();
  await sendButton.click();
}
export async function answer(page: Page, option: string) {
  const window = page.getByRole("region", { name: "Уточняющие вопросы" });
  // Sending without a choice records "Не знаю".
  if (option !== "Не знаю")
    await window.getByRole("button", { name: option, exact: true }).click();
  // The other open questions are left for later: moving on records "Не знаю" for them.
  const submit = window.getByRole("button", { name: "Отправить ответы" });
  while (!(await submit.isVisible()))
    await window.getByRole("button", { name: "Далее", exact: true }).click();
  await submit.click();
}
// Answers appear in the thread as question and answer pairs.
export async function answered(page: Page, question: string, value: string) {
  const pair = page
    .locator("dl > div")
    .filter({
      has: page.getByRole("term").getByText(question, { exact: true }),
    })
    .last();
  await expect(pair.getByRole("definition")).toHaveText(value);
}

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
// модель нужна ассистенту
export async function task(page: Page, text: string, model = "box.stl") {
  await attach(page, model);
  await send(page, text);
}
// конвейер завершён
export const PIPELINE_DONE =
  /Проект готов|Проект требует внимания|Проект не создан|Параметры требуют внимания/;
// ничего не выполняется
const SETTLED = new RegExp(
  `Ожидаю материалы|Нужны уточнения|Параметры подобраны|Ошибка обработки|${PIPELINE_DONE.source}`,
);
export async function settled(page: Page) {
  // строка до ответа
  await expect(page.getByLabel("Ассистент отвечает")).toHaveCount(0);
  await expect(
    page.getByRole("status").filter({ hasText: SETTLED }),
  ).toBeVisible();
}
export async function attach(page: Page, ...names: string[]) {
  await page
    .getByLabel("Выбрать файлы", { exact: true })
    .setInputFiles(names.map(fixture));
}
export async function upload(page: Page, ...names: string[]) {
  await attach(page, ...names);
  const sendButton = page.getByRole("button", {
    name: "Отправить",
    exact: true,
  });
  await expect(sendButton).toBeEnabled();
  await sendButton.click();
}
export async function answer(page: Page, option: string) {
  const window = page.getByRole("region", { name: "Уточняющие вопросы" });
  // ответ «Не знаю»
  if (option !== "Не знаю")
    await window.getByRole("button", { name: option, exact: true }).click();
  // остальные вопросы отложены
  const submit = window.getByRole("button", { name: "Отправить ответы" });
  while (!(await submit.isVisible()))
    await window.getByRole("button", { name: "Далее", exact: true }).click();
  await submit.click();
}
// пары вопрос-ответ
export async function answered(page: Page, question: string, value: string) {
  const pair = page
    .locator("dl > div")
    .filter({
      has: page.getByRole("term").getByText(question, { exact: true }),
    })
    .last();
  await expect(pair.getByRole("definition")).toHaveText(value);
}
export async function pipelineDone(page: Page) {
  await expect(
    page.getByRole("status").filter({ hasText: PIPELINE_DONE }),
  ).toBeVisible();
}

import { join } from "node:path";

import { expect, test } from "@playwright/test";

import { installApiMock } from "./fixtures";


const output = (name: string) => join(process.cwd(), "artifacts", "phase8-screenshots", name);


test("capture Phase 8 contextual Ask states", async ({ page }) => {
  await installApiMock(page);
  await page.goto("/");
  await page.getByTestId("auth-email").fill("browser@example.com");
  await page.getByTestId("auth-password").fill("browser-test-password");
  await page.getByTestId("auth-submit").click();
  await expect(page.getByRole("heading", { name: "Today", exact: true })).toBeVisible();

  await page.goto("/ask");
  await expect(page.getByRole("heading", { name: "What are you trying to understand?" })).toBeVisible();
  await page.screenshot({ path: output("01-chat-only.png"), fullPage: false });

  const composer = page.getByPlaceholder(/Ask about your portfolio/);
  await composer.fill("Show my portfolio return and risks");
  await page.getByRole("button", { name: "Ask EagleEyes →" }).click();
  await expect(page.locator(".canvas-view-switcher summary")).toHaveText(/Portfolio return and risks/);
  await expect(page.locator(".ask-chat-pane")).toBeVisible();
  await page.screenshot({ path: output("02-chat-and-canvas.png"), fullPage: false });

  await page.getByRole("button", { name: "Close analysis canvas" }).click();
  await expect(page.locator(".ask-canvas-pane")).toHaveCount(0);
  await expect(page.getByRole("button", { name: /Portfolio return and risks/ }).first()).toBeVisible();
  await page.screenshot({ path: output("03-canvas-closed.png"), fullPage: false });

  await page.getByRole("button", { name: /Portfolio return and risks/ }).first().click();
  await expect(page.locator(".ask-canvas-pane")).toBeVisible();
  await page.screenshot({ path: output("04-canvas-reopened.png"), fullPage: false });

  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "Chat", exact: true }).click();
  await expect(page.locator(".ask-chat-pane")).toBeVisible();
  await page.screenshot({ path: output("05-mobile-chat.png"), fullPage: false });

  await page.getByRole("button", { name: "Analysis", exact: true }).click();
  await expect(page.locator(".ask-canvas-pane")).toBeVisible();
  await page.screenshot({ path: output("06-mobile-analysis.png"), fullPage: false });
});

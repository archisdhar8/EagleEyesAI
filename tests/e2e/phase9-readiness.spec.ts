import { expect, test, type Page } from "@playwright/test";
import { installApiMock } from "./fixtures";

async function signIn(page: Page) {
  await page.goto("/");
  await page.getByTestId("auth-email").fill("browser@example.com");
  await page.getByTestId("auth-password").fill("browser-test-password");
  await page.getByTestId("auth-submit").click();
  await expect(page.getByRole("heading", { name: "Today", exact: true })).toBeVisible();
}

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => sessionStorage.clear());
  await installApiMock(page);
});

test("keyboard user can compose, close, and reopen contextual analysis", async ({ page, isMobile }) => {
  await signIn(page);
  await page.goto("/ask");
  const composer = page.getByPlaceholder(/Ask about your portfolio/);
  await composer.focus();
  await expect(composer).toBeFocused();
  await composer.fill("Visualize my largest portfolio risks.");
  await page.getByRole("button", { name: "Ask EagleEyes →" }).click();
  await expect(page.locator(".ask-canvas-pane")).toBeVisible();

  if (isMobile) {
    await expect(page.getByRole("button", { name: /Chat|Back/ }).first()).toBeVisible();
  }
  const close = page.getByRole("button", { name: "Close analysis canvas" });
  await close.focus();
  await expect(close).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator(".ask-canvas-pane")).toHaveCount(0);
  const reopen = page.locator(".ask-open-analysis");
  await expect(reopen).toBeVisible();
  await reopen.focus();
  await page.keyboard.press("Enter");
  await expect(page.locator(".ask-canvas-pane")).toBeVisible();
});

test("Ask layout avoids horizontal overflow and exposes non-color status text", async ({ page }) => {
  await signIn(page);
  await page.goto("/ask");
  const composer = page.getByPlaceholder(/Ask about your portfolio/);
  await composer.fill("Visualize my largest portfolio risks.");
  await page.getByRole("button", { name: "Ask EagleEyes →" }).click();
  await expect(page.getByText("Required evidence verified")).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
  await expect(composer).toHaveAttribute("placeholder", /Ask about your portfolio/);
  await expect(page.getByRole("button", { name: "Close analysis canvas" })).toHaveAttribute("aria-label", "Close analysis canvas");
});

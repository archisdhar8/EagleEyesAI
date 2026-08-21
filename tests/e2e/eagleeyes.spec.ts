import { expect, test, type Page } from "@playwright/test";
import { installApiMock } from "./fixtures";

async function signIn(page: Page) {
  await page.goto("/");
  await page.getByTestId("auth-email").fill("browser@example.com");
  await page.getByTestId("auth-password").fill("browser-test-password");
  await page.getByTestId("auth-submit").click();
  await expect(page.getByRole("heading", { name: "Today", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Research", exact: true })).toBeVisible();
}

async function buildBoard(page: Page, prompt = "Show my portfolio return and risks") {
  await page.goto("/ask");
  const composer = page.getByPlaceholder(/Ask about your portfolio/);
  await composer.fill(prompt);
  await page.getByRole("button", { name: "Ask EagleEyes →" }).click();
  await expect(page.locator(".canvas-view-switcher summary")).toHaveText(/Portfolio return and risks/);
  await expect(page.getByText("Required evidence verified")).toBeVisible();
}

test("Ask starts chat-first, opens a resizable canvas for visuals, and preserves mobile state", async ({ page }) => {
  await installApiMock(page);
  await signIn(page);
  await page.goto("/ask");

  await expect(page.locator(".ask-chat-pane")).toBeVisible();
  await expect(page.locator(".ask-canvas-pane")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "What are you trying to understand?" })).toBeVisible();
  await expect(page.getByText("Expert tool")).toHaveCount(0);
  const askInput = page.getByPlaceholder(/Ask about your portfolio/);
  await askInput.fill("Compare my largest holdings");
  await page.getByRole("button", { name: "Ask EagleEyes →" }).click();
  await expect(page.locator(".ask-canvas-pane")).toHaveCount(0);

  await askInput.fill("Show my portfolio performance against SPY.");
  await page.getByRole("button", { name: "Ask EagleEyes →" }).click();
  const divider = page.getByRole("separator", { name: "Resize chat and analysis" });
  await expect(divider).toHaveAttribute("aria-valuenow", "38");
  await divider.press("ArrowRight");
  await expect(divider).toHaveAttribute("aria-valuenow", "40");
  const themeButton = page.getByRole("button", { name: /Light mode|Dark mode/ });
  const themeBefore = await themeButton.textContent();
  await themeButton.click();
  await expect(themeButton).not.toHaveText(themeBefore || "");

  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("tab", { name: "Analysis" }).click();
  await expect(page.locator(".ask-canvas-pane")).toBeVisible();
  await expect(page.locator(".ask-chat-pane")).toBeHidden();
  await page.getByRole("tab", { name: "Chat" }).click();
  await expect(askInput).toHaveValue("");
  await page.getByRole("tab", { name: "Analysis" }).click();
  await page.getByRole("button", { name: "Close analysis canvas" }).click();
  await expect(page.locator(".ask-canvas-pane")).toHaveCount(0);
});

test("conversational dashboard edits persist through undo, save, and reload", async ({ page }) => {
  await installApiMock(page);
  await signIn(page);
  await page.goto("/ask");
  const composer=page.getByPlaceholder(/Ask about your portfolio/);
  const send=async(question:string)=>{
    await composer.fill(question);
    await page.getByRole("button",{name:"Ask EagleEyes →"}).click();
  };

  await send("Build me a portfolio overview dashboard.");
  await expect(page.locator(".canvas-view-switcher summary")).toHaveText(/Portfolio overview/);
  await expect(page.getByRole("heading",{name:"Portfolio news"})).toBeVisible();

  await send("Add performance against SPY.");
  await expect(page.getByRole("heading",{name:"Performance vs SPY"})).toBeVisible();
  await send("Make that five years.");
  await expect(page.getByText("Updated Performance vs SPY.").last()).toBeVisible();
  await send("Move sector exposure below performance.");
  await expect(page.getByText("Moved Sector exposure.").last()).toBeVisible();
  await send("Remove news.");
  await expect(page.getByRole("heading",{name:"Portfolio news"})).toHaveCount(0);
  await send("Undo that.");
  await expect(page.getByRole("heading",{name:"Portfolio news"})).toBeVisible();
  await send("Save this as Portfolio Overview.");
  await expect(page.getByText("Saved as Portfolio Overview.").last()).toBeVisible();
  await expect(page.getByText("Saved",{exact:true})).toBeVisible();

  await page.getByRole("button",{name:"New chat",exact:true}).click();
  await expect(page.locator(".ask-canvas-pane")).toHaveCount(0);
  await page.getByRole("button",{name:"History",exact:true}).click();
  await page.getByRole("button",{name:/^Portfolio workspace \d+ messages/}).click();
  await page.locator(".ask-open-analysis").click();
  await expect(page.getByText("Saved",{exact:true})).toBeVisible();
  await expect(page.locator(".canvas-view-switcher summary")).toHaveText(/Portfolio Overview/);

  await page.reload();
  await page.locator(".ask-open-analysis").click();
  await expect(page.getByText("Saved",{exact:true})).toBeVisible();
  await expect(page.locator(".canvas-view-switcher summary")).toHaveText(/Portfolio Overview/);
  await expect(page.getByText("Saved as Portfolio Overview.").last()).toBeVisible();
});

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => sessionStorage.clear());
});

test("login survives refresh and sign-out clears the local test session", async ({ page }) => {
  const state = await installApiMock(page);
  await signIn(page);
  await page.evaluate(() => {
    const key = Object.keys(localStorage).find(item => item.startsWith("sb-") && item.endsWith("-auth-token"));
    if (!key) throw new Error("Supabase session was not persisted");
    const stored = JSON.parse(localStorage.getItem(key)!);
    stored.expires_at = 1;
    localStorage.setItem(key, JSON.stringify(stored));
  });
  await page.reload();
  await expect(page.getByRole("heading", { name: "Today", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Research", exact: true })).toBeVisible();
  await expect.poll(() => state.authGrants).toContain("refresh_token");
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByTestId("auth-form")).toBeVisible();
});

test("portfolio import flows to Research and analysis", async ({ page }) => {
  await installApiMock(page, { portfolio: false });
  await signIn(page);
  await page.goto("/portfolio?view=holdings");
  await page.getByLabel("Import portfolio CSV").setInputFiles({
    name: "portfolio.csv", mimeType: "text/csv", buffer: Buffer.from("symbol,weight\nAAPL,50%\nSPY,50%\n"),
  });
  await expect(page.locator(".save-state")).toContainText("All changes saved");
  await page.goto("/research?view=stocks");
  await page.getByLabel("Stock, ETF, or company").fill("AAPL");
  await page.getByRole("button", { name: "Open research →" }).click();
  await expect(page.getByText("Apple Inc.", { exact: true })).toBeVisible();
  await page.goto("/portfolio?view=analysis");
  await page.getByRole("button", { name: "Run portfolio analysis →" }).click();
  await expect(page.getByText("Three alternatives are ready. Review the tradeoffs—not just the headline return.")).toBeVisible();
  await expect(page.getByRole("button", { name: /Balanced 7\.0% modeled return/ })).toBeVisible();
});

test("transaction ledger previews separately and saves only after review", async ({ page }) => {
  await installApiMock(page);
  await signIn(page);
  await page.goto("/portfolio?view=holdings");
  await page.getByText("Actual-performance ledger (optional)").click();
  await page.getByText("Import transaction CSV").locator("input").setInputFiles({
    name: "transactions.csv", mimeType: "text/csv",
    buffer: Buffer.from("Date,Type,Symbol,Quantity,Price,Memo\n2025-01-02,Buy,AAPL,5,100,first lot\n"),
  });
  await expect(page.getByText("1 valid transactions")).toBeVisible();
  await expect(page.getByText("Ignored columns: Memo")).toBeVisible();
  await page.getByRole("button", { name: "Save reviewed ledger" }).click();
  await expect(page.getByRole("button", { name: "1 saved · 0 duplicates skipped" })).toBeVisible();
  await expect(page.getByText("This remains separate from the current holdings snapshot", { exact: false })).toBeVisible();
});

test("legacy routes canonicalize without losing the requested subview", async ({ page }) => {
  await installApiMock(page);
  await signIn(page);
  for (const [legacy, canonical] of [
    ["/overview", "/today"], ["/scenarios", "/research?view=scenarios"],
    ["/research", "/research"], ["/optimize", "/portfolio?view=analysis"],
    ["/ai-workspace", "/ask"], ["/research-terminal", "/advanced?view=terminal"],
    ["/decision-lab", "/research"], ["/portfolio?view=lab", "/research"],
  ]) {
    await page.goto(legacy);
    await expect(page).toHaveURL(new RegExp(canonical.replace("?", "\\?")));
  }
});

test("Learn saves, masters, and resumes a versioned lesson", async ({ page }) => {
  await installApiMock(page);
  await signIn(page);
  await page.goto("/learn");
  await expect(page.getByRole("heading", { name: "Learn", exact: true })).toBeVisible();
  await page.getByRole("button", { name: /^Continue: Why save and invest/ }).click();
  await expect(page).toHaveURL(/\/learn\/start-safely\/why-invest/);
  await page.getByRole("button", { name: "Mark lesson complete" }).click();
  await page.getByText("Which money belongs in savings?").locator("..").getByText("Emergency money").click();
  await page.getByText("What is compounding?").locator("..").getByText("Earlier growth can earn later growth").click();
  await page.getByRole("button", { name: "Submit knowledge check" }).click();
  await expect(page.getByText("Mastery score reached")).toBeVisible();
  await page.getByRole("button", { name: "← Learning hub" }).click();
  await expect(page.getByText("1/1 mastered")).toBeVisible();
});

test("manual terminal adds, resizes, moves, saves, reopens, and resets", async ({ page }) => {
  await installApiMock(page);
  await signIn(page);
  await page.goto("/advanced?view=terminal");
  await page.locator(".terminal-workspace").getByRole("button", { name: "＋ Add widget" }).click();
  await page.getByRole("button", { name: /^Portfolio Positions Saved holdings/ }).click();
  await expect(page.getByRole("heading", { name: "Positions" })).toBeVisible();
  const positionCard = page.locator("article.terminal-widget").filter({ hasText: "Positions" });
  await positionCard.getByTitle("Change widget size").click();
  const moveBackward = page.getByRole("button", { name: "Move Positions backward" });
  await expect(moveBackward).toBeEnabled();
  await moveBackward.click();
  page.once("dialog", dialog => dialog.accept("Browser terminal"));
  await page.getByRole("button", { name: "Save layout" }).click();
  await expect(page.getByText("Advanced layout saved.")).toBeVisible();
  await page.locator(".layout-toolbar select").selectOption({ label: "Browser terminal" });
  await page.getByRole("button", { name: "Reset layout" }).click();
  await expect(page.getByRole("heading", { name: "Hypothetical current-weight return" })).toBeVisible();
});

test("provider health exposes coverage, fallbacks, and degraded state without secrets", async ({ page }) => {
  await installApiMock(page);
  await signIn(page);
  await page.goto("/advanced?view=providers");
  await expect(page.getByRole("heading", { name: "Provider health, coverage, fallbacks, and limits." })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Corporate-action-adjusted prices" })).toBeVisible();
  await expect(page.locator(".provider-summary p").filter({ hasText: "healthy" }).getByText("5", { exact: true })).toBeVisible();
  await expect(page.getByText("Fixture stale fallback")).toBeVisible();
  await expect(page.locator("body")).not.toContainText("API_KEY");
});

test("AI board supports progressive build, revision, add, resize, remove, save, reopen, and exact duplicate", async ({ page }) => {
  await installApiMock(page);
  await signIn(page);
  await buildBoard(page);
  await page.getByLabel("Resize Portfolio performance").selectOption("12");
  page.once("dialog", dialog => dialog.accept());
  await page.getByRole("button", { name: "Remove Optional risk summary" }).click();
  await expect(page.getByRole("heading", { name: "Optional risk summary" })).toHaveCount(0);
  await page.getByLabel("Analysis actions").click();
  await page.getByRole("button", { name: "Add verified data" }).click();
  await page.getByRole("button", { name: /^Macro Macro trends Stored macro factors/ }).click();
  await expect(page.getByRole("heading", { name: "Macro trends" })).toBeVisible();
  await page.getByRole("button", { name: "Save dashboard" }).click();
  await expect(page.getByText("Dashboard view saved.")).toBeVisible();
  await expect(page.getByText("Saved", { exact: true })).toBeVisible();
  await page.getByLabel("Analysis actions").click();
  await page.getByRole("button", { name: "Duplicate", exact: true }).click();
  await expect(page.getByText("Dashboard duplicated with the same layout and compatible results.")).toBeVisible();
  await expect(page.locator(".canvas-view-switcher summary")).toHaveText(/Portfolio return and risks copy/);
});

test("partial widget failure preserves successful evidence and narration", async ({ page }) => {
  await installApiMock(page, { partial: true });
  await signIn(page);
  await buildBoard(page);
  await expect(page.getByText("Widget unavailable")).toBeVisible();
  await expect(page.getByText("The validated return evidence is available.")).toBeVisible();
  await expect(page.getByRole("strong").filter({ hasText: "10.0%" })).toBeVisible();
});

test("no-portfolio mode still provides cached company research", async ({ page }) => {
  await installApiMock(page, { portfolio: false, stale: true });
  await signIn(page);
  await expect(page.getByText("Add or select a portfolio")).toBeVisible();
  await page.goto("/research?view=stocks");
  await page.getByLabel("Stock, ETF, or company").fill("AAPL");
  await page.getByRole("button", { name: "Open research →" }).click();
  await expect(page.getByRole("heading", { name: "Bear, base, and bull cases" })).toBeVisible();
  await expect(page.getByText("Apple Inc.", { exact: true })).toBeVisible();
});

test("ETF Builder produces disclosed ranges, costs, and a benchmark", async ({ page }) => {
  await installApiMock(page);
  await signIn(page);
  await page.goto("/research?view=etf-builder");
  await page.getByRole("button", { name: "Build ETF allocation" }).click();
  await expect(page.getByRole("heading", { name: "ETF research allocation" })).toBeVisible();
  await expect(page.getByText("Vanguard Total Stock Market ETF")).toBeVisible();
  await expect(page.getByText("55.0%–60.0%")).toBeVisible();
  await expect(page.getByText("Estimated first-year expenses")).toBeVisible();
  await expect(page.getByText("Equal weight")).toBeVisible();
  await page.getByRole("button", { name: "Send to Decision Lab" }).click();
  await expect(page.getByText("Paired paths browser-shared-paths")).toBeVisible();
  await expect(page.getByText("today’s dollars", { exact: false }).first()).toBeVisible();
});

test("Stock Basket Builder discloses its universe, risk contribution, and benchmark", async ({ page }) => {
  await installApiMock(page);
  await signIn(page);
  await page.goto("/research?view=stock-builder");
  await page.getByRole("button", { name: "Build stock basket" }).click();
  await expect(page.getByRole("heading", { name: "Stock research allocation" })).toBeVisible();
  await expect(page.getByText("2 eligible of 5 requested", { exact: false })).toBeVisible();
  await expect(page.getByText("Risk contribution")).toBeVisible();
  await expect(page.getByText("SPY", { exact: true })).toBeVisible();
  await expect(page.locator(".builder-allocation-table")).not.toContainText(/\b(BUY|HOLD|SELL)\b/);
  await page.getByRole("button", { name: "Send to Decision Lab" }).click();
  await expect(page.getByText("Paired paths browser-shared-paths")).toBeVisible();
});

test("retired Decisions URLs preserve ticker context in unified Research", async ({ page }) => {
  await installApiMock(page);
  await signIn(page);
  await page.goto("/decisions?ticker=AAPL");
  await expect(page).toHaveURL(/\/research\?ticker=AAPL/);
  await expect(page.getByRole("heading", { name: /AAPL Apple Inc\./ })).toBeVisible();
});

test("unified Research exposes watchlist and Ask without a thesis editor", async ({ page }) => {
  await installApiMock(page);
  await signIn(page);
  await page.goto("/research?ticker=AAPL");
  await expect(page.getByRole("heading", { name: /AAPL Apple Inc\./ })).toBeVisible();
  await expect(page.getByRole("button", { name: "✓ On watchlist" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Ask EagleEyes →" })).toHaveAttribute("href", "/ask?ticker=AAPL");
  await expect(page.getByRole("button", { name: "Confirm and save thesis" })).toHaveCount(0);
});

test("default presentation stays detailed and Expert mode lives under More", async ({ page }) => {
  await installApiMock(page);
  await signIn(page);
  await buildBoard(page);
  await expect(page.getByText("Evidence", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Simple" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Detailed" })).toHaveCount(0);
  await page.getByLabel("Open secondary navigation").click();
  const menuSignOut=page.locator(".secondary-menu").getByRole("button",{name:"↪ Sign out"});
  await expect(menuSignOut).toBeVisible();
  expect(await menuSignOut.evaluate(element=>{const box=element.getBoundingClientRect();const top=document.elementFromPoint(box.left+box.width/2,box.top+box.height/2);return Boolean(top?.closest(".secondary-menu"));})).toBe(true);
  await page.getByRole("button", { name: "Expert mode off" }).click();
  const expertMethod = page.getByText("Method, lineage, and validation").first();
  await expect(expertMethod).toBeVisible();
  await expertMethod.click();
  await expect(page.getByText("golden-v1", { exact: false }).first()).toBeVisible();
});

test("separate browser users do not share saved boards", async ({ browser }) => {
  const first = await browser.newContext();
  const second = await browser.newContext();
  const firstPage = await first.newPage();
  const secondPage = await second.newPage();
  await installApiMock(firstPage);
  await installApiMock(secondPage);
  await signIn(firstPage); await buildBoard(firstPage);
  await firstPage.getByRole("button", { name: "Save dashboard" }).click();
  await signIn(secondPage);
  await secondPage.goto("/ask");
  await expect(firstPage.getByRole("heading", { name: "Portfolio return and risks", exact: true })).toBeVisible();
  await expect(secondPage.getByRole("heading", { name: "Portfolio return and risks", exact: true })).toHaveCount(0);
  await first.close(); await second.close();
});

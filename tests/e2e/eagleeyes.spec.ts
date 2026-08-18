import { expect, test, type Page } from "@playwright/test";
import { installApiMock } from "./fixtures";

async function signIn(page: Page) {
  await page.goto("/");
  await page.getByTestId("auth-email").fill("browser@example.com");
  await page.getByTestId("auth-password").fill("browser-test-password");
  await page.getByTestId("auth-submit").click();
  await expect(page.getByRole("heading", { name: "Today", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: /Your portfolio is up to date|Welcome to your research workspace|Preparing your daily brief/ })).toBeVisible();
}

async function buildBoard(page: Page, prompt = "Show my portfolio return and risks") {
  await page.goto("/ask");
  await page.getByText("Build or open a calculated research board", { exact: true }).click();
  const composer = page.getByPlaceholder("Describe the dashboard you want…");
  await composer.fill(prompt);
  await page.getByRole("button", { name: "Build view →" }).click();
  await expect(page.getByRole("heading", { name: "Portfolio return and risks" })).toBeVisible();
  await expect(page.getByText("Required evidence verified")).toBeVisible();
}

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
  await expect(page.getByRole("heading", { name: /Your portfolio is up to date|Welcome to your research workspace|Preparing your daily brief/ })).toBeVisible();
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
  await page.getByRole("button", { name: "Search research" }).click();
  await expect(page.getByText("Apple Inc.")).toBeVisible();
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
    ["/decision-lab", "/decisions"], ["/portfolio?view=lab", "/decisions"],
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
  await page.getByRole("button", { name: "＋ Add data" }).click();
  await page.getByRole("button", { name: /^Macro Macro trends Stored macro factors/ }).click();
  await expect(page.getByRole("heading", { name: "Macro trends" })).toBeVisible();
  await page.getByPlaceholder("Revise this view…").fill("Focus the explanation on drawdown risk");
  await page.getByRole("button", { name: "Revise view →" }).click();
  await expect(page.getByRole("heading", { name: "Revised portfolio board" })).toBeVisible();
  await page.getByRole("button", { name: "Save dashboard" }).click();
  await expect(page.getByText("Dashboard view saved.")).toBeVisible();
  await page.getByTitle("Open saved dashboard").click();
  await expect(page.getByText("Saved dashboard")).toBeVisible();
  await page.locator('summary[aria-label="More actions for Revised portfolio board"]').click();
  await page.getByRole("button", { name: "Duplicate exactly" }).click();
  await expect(page.getByText("Dashboard duplicated with the same layout and compatible results.")).toBeVisible();
  await expect(page.getByText("Revised portfolio board copy")).toBeVisible();
});

test("partial widget failure preserves successful evidence and narration", async ({ page }) => {
  await installApiMock(page, { partial: true });
  await signIn(page);
  await buildBoard(page);
  await expect(page.getByText("Widget unavailable")).toBeVisible();
  await expect(page.getByText("The validated return evidence is available.")).toBeVisible();
  await expect(page.getByRole("strong").filter({ hasText: "10.0%" })).toBeVisible();
});

test("stale fallback and no-portfolio mode remain useful", async ({ page }) => {
  await installApiMock(page, { portfolio: false, stale: true });
  await signIn(page);
  await expect(page.getByText("Start your workspace")).toBeVisible();
  await expect(page.getByText("Using last validated provider snapshot")).toBeVisible();
  await page.goto("/research?view=stocks");
  await page.getByLabel("Stock, ETF, or company").fill("AAPL");
  await page.getByRole("button", { name: "Search research" }).click();
  await expect(page.getByText("Browser fixture universe")).toBeVisible();
  await expect(page.getByText("Apple Inc.")).toBeVisible();
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

test("Decision Lab compares six choices on one paired path set", async ({ page }) => {
  await installApiMock(page);
  await signIn(page);
  await page.goto("/decisions");
  await page.getByText("Scenario comparison lab", { exact: true }).click();
  await page.getByRole("button", { name: "Run Decision Lab" }).click();
  await expect(page.getByText("Paired paths browser-shared-paths")).toBeVisible();
  await expect(page.getByText("Today’s dollars", { exact: false }).first()).toBeVisible();
  await expect(page.locator(".decision-frontier-table").locator("> div")).toHaveCount(7);
  await expect(page.getByText("decision-lab-block-bootstrap-v1.0.0")).toBeVisible();
});

test("EagleEyes drafts a thesis but saves beliefs only after explicit review", async ({ page }) => {
  const state = await installApiMock(page);
  await signIn(page);
  await page.goto("/decisions");
  await page.getByLabel("Search holdings or ticker").fill("AAPL");
  await page.getByRole("button", { name: "Open AAPL" }).click();
  await expect(page.getByRole("heading", { name: /AAPL/ }).first()).toBeVisible();
  await page.getByRole("button", { name: "I own it" }).click();
  await page.getByText("Create and review a thesis", { exact: true }).click();
  await page.getByLabel(/3\. Why is it on your mind/).first().fill("I want to track services durability.");
  await page.getByRole("button", { name: "Build an evidence-assisted thesis →" }).first().click();
  await expect(page.getByRole("heading", { name: "Review what must remain true." })).toBeVisible();
  await expect(page.getByText("Suggested by EagleEyes", { exact: true }).first()).toBeVisible();
  const save = page.getByRole("button", { name: "Confirm and save thesis" });
  await expect(save).toBeDisabled();
  await page.getByLabel(/I reviewed this thesis/).first().check();
  await save.click();
  await expect(page.getByText("Thesis saved as version 1.")).toBeVisible();
  const request = state.requests.find(item => item.path === "/theses" && item.method === "POST");
  expect(request).toBeTruthy();
  expect(request?.body).toMatchObject({ source_context: { relationship: "OWN", user_reason: "I want to track services durability.", confirmation_state: "USER_CONFIRMED" } });
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

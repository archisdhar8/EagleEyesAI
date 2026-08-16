import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const dashboardPath = new URL("../app/Dashboard.tsx", import.meta.url);
const catchAllRoutePath = new URL("../app/[...slug]/page.tsx", import.meta.url);
const shellPath = new URL("../app/components/shell/AppShell.tsx", import.meta.url);
const todayPath = new URL("../app/components/today/TodayPage.tsx", import.meta.url);
const workspacesPath = new URL("../app/components/shared/workspace-implementations.tsx", import.meta.url);
const researchPath = new URL("../app/components/research/ResearchDiscovery.tsx", import.meta.url);
const routesPath = new URL("../app/lib/routes.ts", import.meta.url);

async function dashboardSurface() {
  return (await Promise.all([dashboardPath, shellPath, todayPath, workspacesPath, researchPath].map(path => readFile(path, "utf8")))).join("\n");
}

test("every rendered button has an action", async () => {
  const source = await dashboardSurface();
  const buttons = [...source.matchAll(/<button\b[\s\S]*?<\/button>/g)].map(match => match[0]);
  assert.ok(buttons.length >= 15, "expected the dashboard interaction surface");
  const inert = buttons.filter(button => !/\bonClick\s*=/.test(button) && !/\btype="submit"/.test(button));
  assert.deepEqual(inert, []);
});

test("critical portfolio and analysis actions remain wired", async () => {
  const source = await dashboardSurface();
  for (const action of [
    "savePortfolio", "importCsv", "refreshMarkets", "refreshResearch",
    "runOptimization", "generateNarrative", "toggleTheme",
  ]) {
    assert.match(source, new RegExp(`function ${action}\\(`));
  }
  assert.match(source, /Duplicate ticker/);
  assert.match(source, /Unsaved changes/);
  assert.match(source, /Weight \(%\)/);
  assert.match(source, /ingest_tickers/);
});

test("manual research terminal exposes a persistent actionable widget catalog", async () => {
  const source = await dashboardSurface();
  const routes = await readFile(routesPath, "utf8");
  for (const action of ["addTerminalWidget", "moveTerminalWidget", "dropTerminalWidget", "resizeTerminalWidget"]) {
    assert.match(source, new RegExp(`function ${action}\\(`));
  }
  for (const widget of ["portfolio_return", "macro_indicators", "prediction_market_search", "security_scorecard", "model_monitoring"]) {
    assert.match(source, new RegExp(widget));
  }
  assert.match(source, /Research terminal/);
  for (const workspace of ["Today", "Plan", "Portfolio", "Research", "Ask EagleEyes", "Advanced"]) {
    assert.match(routes, new RegExp(`"${workspace}"`));
  }
  assert.match(source, /terminal_widgets/);
});

test("market workspace keeps planning secondary and route compatibility explicit", async () => {
  const source = await dashboardSurface();
  const today = await readFile(todayPath, "utf8");
  const routes = await readFile(routesPath, "utf8");
  const catchAllRoute = await readFile(catchAllRoutePath, "utf8");
  for (const legacy of ["/overview", "/scenarios", "/research", "/optimize", "/ai-workspace", "/research-terminal"]) {
    assert.match(routes, new RegExp(legacy.replaceAll("/", "\\/")));
  }
  assert.match(today, /What currently matters to your portfolio/);
  assert.match(source, /Hypothetical one-year return using current holdings and weights/);
  assert.match(source, /Customize the research around what the portfolio is for/);
  for (const path of ["Current / do nothing", "Contributions only", "Gradual transition", "Immediate transition"]) {
    assert.match(source, new RegExp(path));
  }
  assert.match(catchAllRoute, /InvestmentApp/);
});

test("planning, guidance, and flexible portfolio import are visible and actionable", async () => {
  const source = await dashboardSurface();
  for (const copy of [
    "Symbol / ticker",
    "Flexible importer",
    "funding_source",
    "flexibility",
    "Approve policy",
    "Next dollar guidance",
    "What should I do next?",
    "Decision triggers—not price alerts",
    "research_preferences",
  ]) {
    assert.match(source, new RegExp(copy));
  }
});

test("default research presentation avoids false precision", async () => {
  const source = await dashboardSurface();
  const today = await readFile(todayPath, "utf8");
  assert.match(today, /What currently matters to your portfolio/);
  assert.match(source, /Independent evidence dimensions/);
  assert.match(source, /not forced into one 100% distribution/);
  assert.match(source, /Stock research library/);
  assert.match(source, /Search stocks/);
  assert.match(source, /Rating bucket/);
  assert.match(source, /Leading evidence/);
  assert.match(source, /What kind of market are we in\?/);
  assert.match(source, /Similar historical market states/);
  assert.match(source, /Strongest evidence/);
  assert.match(source, /Weakest evidence/);
  assert.match(source, /Portfolio fit/);
  assert.match(source, /What would change the view/);
  assert.match(source, /presentation\.showDiagnostics&&<p>Expert scores/);
});

test("research search explains filters, missing data, ETF holdings, and valuation logic", async () => {
  const research = await readFile(researchPath, "utf8");
  for (const copy of [
    "AAPL, QQQ, ARKK, or Apple",
    "Requires business-quality evidence ≥60 and available valuation evidence ≥50",
    "Why some data is missing",
    "Review valuation logic",
    "ETF holdings & costs",
    "Open provider source",
  ]) assert.match(research, new RegExp(copy));
});

test("progressive planning, combined macro analysis, and saved-board deletion stay actionable", async () => {
  const source = await dashboardSurface();
  for (const copy of [
    "Essentials",
    "Goals",
    "Investment policy",
    "Run combined test",
    "historical months matched",
    "Delete permanently",
  ]) assert.match(source, new RegExp(copy));
  assert.match(source, /planSection/);
  assert.match(source, /deleteDashboardView/);
});

test("research and portfolio chats expose durable conversation controls", async () => {
  const source = await dashboardSurface();
  for (const action of [
    "newChatConversation", "openChatConversation", "renameChatConversation",
    "deleteChatConversation", "buildBoardFromConversation",
  ]) assert.match(source, new RegExp(`function ${action}\\(`));
  for (const copy of ["Research conversations", "Portfolio conversations", "Linked evidence", "＋ New"]) {
    assert.match(source, new RegExp(copy));
  }
  assert.match(source, /eagleeyes-research-conversation/);
  assert.match(source, /eagleeyes-portfolio-conversation/);
});

test("chat history remains beside the conversation on desktop", async () => {
  const css = await readFile(new URL("../app/globals.css", import.meta.url), "utf8");
  assert.match(css, /\.chat-history-shell\{display:grid;grid-template-columns:300px minmax\(0,1fr\)/);
  assert.match(css, /\.chat-history-shell>\.portfolio-analysis-chat\{grid-column:auto/);
  assert.match(css, /@media\(max-width:860px\)\{\.chat-history-shell\{grid-template-columns:1fr\}/);
});

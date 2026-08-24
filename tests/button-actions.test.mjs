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
  const inert = buttons.filter(button => !/\bonClick\s*=/.test(button) && !/\btype="submit"/.test(button) && !/Open research|Ask EagleEyes/.test(button));
  assert.deepEqual(inert, []);
  assert.match(source, /unified-research-search" onSubmit=/);
  assert.match(source, /chat-composer" onSubmit=/);
});

test("stock research search starts ready instead of blocking on an empty universe scan", async () => {
  const research = await readFile(researchPath, "utf8");
  assert.match(research, /useState\(Boolean\(deepLinkedTicker\)\)/);
  assert.match(research, /AbortController/);
  assert.match(research, /Choose a holding or search a company/);
  assert.match(research, /\/research\/security\/\$\{encodeURIComponent\(ticker\)\}\/overview/);
  assert.match(research, /Provider refreshes happen separately/);
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

test("portfolio analysis persists, auto-runs after save, and refreshes from objective sliders", async () => {
  const dashboard = await readFile(dashboardPath, "utf8");
  const workspaces = await readFile(workspacesPath, "utf8");
  assert.match(dashboard, /\/analyses\/latest/);
  assert.match(dashboard, /executeAnalysis\(saved\.holdings, saved\.name, profile, "portfolio_saved", saved\.id\)/);
  assert.match(dashboard, /executeAnalysis\(data\.portfolio\.holdings, data\.portfolio\.name, profile, "portfolio_saved", data\.portfolio\.id\)/);
  assert.match(dashboard, /analysisRefreshTimer/);
  assert.match(dashboard, /"objectives_changed"/);
  assert.match(workspaces, /onObjectiveProfileChange/);
  assert.match(workspaces, /Risk-Controlled, Balanced, and Goal-Tilted/);
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
  for (const workspace of ["Today", "Portfolio", "Research", "Market Climate", "Ask EagleEyes", "Plan & profile", "Learn", "Advanced"]) {
    assert.match(routes, new RegExp(`"${workspace}"`));
  }
  assert.match(source, /terminal_widgets/);
});

test("market workspace keeps planning secondary and route compatibility explicit", async () => {
  const source = await dashboardSurface();
  const today = await readFile(todayPath, "utf8");
  const routes = await readFile(routesPath, "utf8");
  const catchAllRoute = await readFile(catchAllRoutePath, "utf8");
  for (const legacy of ["/overview", "/scenarios", "/research", "/optimize", "/ai-workspace", "/research-terminal", "/decision-lab"]) {
    assert.match(routes, new RegExp(legacy.replaceAll("/", "\\/")));
  }
  assert.match(today, /Restoring the latest portfolio snapshot/);
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
  assert.match(today, /Preparing the first portfolio snapshot/);
  assert.match(source, /Independent evidence dimensions/);
  assert.match(source, /not forced into one 100% distribution/);
  assert.match(source, /One clear view of the evidence/);
  assert.match(source, /Stock, ETF, or company/);
  assert.match(source, /Partial evidence/);
  assert.match(source, /Bear, base, and bull cases/);
  assert.match(source, /What kind of market are we in\?/);
  assert.match(source, /Similar historical market states/);
  assert.match(source, /Fundamentals/);
  assert.match(source, /Valuation/);
  assert.match(source, /Portfolio fit/);
  assert.match(source, /What would disprove it/);
  assert.match(source, /Generated research case; not saved as your belief/);
});

test("research search explains filters, missing data, ETF holdings, and valuation logic", async () => {
  const research = await readFile(researchPath, "utf8");
  for (const copy of [
    "AAPL or Apple",
    "Partial evidence",
    "Missing:",
    "Reported earnings",
    "Forward statistics",
    "Evidence through",
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

test("Ask EagleEyes exposes durable conversation controls as the single chat surface", async () => {
  const source = await dashboardSurface();
  for (const action of [
    "newChatConversation", "openChatConversation", "renameChatConversation",
    "deleteChatConversation", "buildBoardFromConversation",
  ]) assert.match(source, new RegExp(`function ${action}\\(`));
  for (const copy of ["Research conversations", "Linked evidence", "＋ New", "Visual analysis opens only when you request it"]) {
    assert.match(source, new RegExp(copy));
  }
  assert.match(source, /ask-history-drawer/);
  assert.match(source, /`eagleeyes-\$\{workspace\}-conversation-\$\{chatScope\(\)\}`/);
  assert.match(source, /conversation-snapshot-\$\{chatScope\(\)\}/);
  assert.match(source, /onKeyDown=\{event=>\{if\(event\.key!=="Enter"\|\|event\.shiftKey\|\|event\.nativeEvent\.isComposing\)return/);
});

test("chat history remains beside the conversation on desktop", async () => {
  const css = await readFile(new URL("../app/globals.css", import.meta.url), "utf8");
  assert.match(css, /\.chat-history-shell\{display:grid;grid-template-columns:300px minmax\(0,1fr\)/);
  assert.match(css, /\.chat-history-shell>\.portfolio-analysis-chat\{grid-column:auto/);
  assert.match(css, /@media\(max-width:860px\)\{\.chat-history-shell\{grid-template-columns:1fr\}/);
});

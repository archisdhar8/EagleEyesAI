import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const root = new URL("../", import.meta.url);
const read = async path => readFile(new URL(path, root), "utf8");

test("terminal layout v1 preserves widget identity, order, type, and size", async () => {
  const fixture = JSON.parse(await read("tests/fixtures/terminal-layout-v1.json"));
  const contract = await read("app/components/terminal/contracts.ts");
  assert.equal(fixture.widgets.map(row => row.id).join(","), "portfolio-return,macro-indicators,market-monitor");
  assert.deepEqual(fixture.widgets.map(row => row.size), ["wide", "full", "small"]);
  assert.match(contract, /TERMINAL_LAYOUT_VERSION = "terminal-layout-v1"/);
  for (const widget of fixture.widgets) assert.match(contract, new RegExp(`"${widget.type}"`));
});

test("AI dashboard v1 keeps exact layout task and result references", async () => {
  const fixture = JSON.parse(await read("tests/fixtures/ai-dashboard-view-v1.json"));
  const contract = await read("app/components/ask/contracts.ts");
  assert.deepEqual(fixture.layout.map(row => row.task_id), ["inflation-sensitivity-task", "macro-trends-task"]);
  assert.deepEqual(fixture.latest_run.widget_results.map(row => row.result_ref), ["result-macro-1", "result-sensitivity-1"]);
  assert.match(contract, /AI_DASHBOARD_SPEC_VERSION = "dashboard-spec-v2"/);
  assert.match(contract, /source\.version === "string" \? source\.version : "dashboard-spec-v1"/);
  assert.match(contract, /"dashboard-layout-v1"/);
  assert.match(contract, /\.\.\.source/);
  assert.match(contract, /\.\.\.row/);
});

test("all legacy routes resolve through the centralized route contract", async () => {
  const routes = await read("app/lib/routes.ts");
  for (const path of ["/overview", "/home", "/scenarios", "/research", "/optimize", "/ai-workspace", "/research-terminal", "/decision-lab"]) {
    assert.match(routes, new RegExp(`"${path.replaceAll("/", "\\/")}"`));
  }
  assert.match(routes, /"\/today"/);
  assert.match(routes, /canonicalPath/);
});

test("Dashboard remains an orchestration surface after workspace extraction", async () => {
  const dashboard = await read("app/Dashboard.tsx");
  for (const component of ["PlanPage", "PortfolioPage", "ExplorePage", "AskPage", "AdvancedPage"]) {
    assert.match(dashboard, new RegExp(`import \\{ ${component}`));
  }
  assert.match(dashboard, /LazyDecisionsPage=lazy\(\(\)=>import\("\.\/components\/decisions\/DecisionsPage"\)/);
  for (const oldDefinition of ["function PlanPage", "function PortfolioWorkspace", "function AIWorkspace", "function AdvancedWorkspace", "function ResearchTerminal"]) {
    assert.doesNotMatch(dashboard, new RegExp(oldDefinition));
  }
  assert.match(await read("app/components/plan/PlanPage.tsx"), /PlanPage/);
  assert.match(await read("app/components/portfolio/PortfolioPage.tsx"), /PortfolioPage/);
  assert.match(await read("app/components/decisions/DecisionsPage.tsx"), /DecisionsPage/);
  assert.match(await read("app/components/ask/AskPage.tsx"), /AskPage/);
  assert.match(await read("app/components/terminal/AdvancedPage.tsx"), /AdvancedPage/);
});

test("legacy workspace module is compatibility re-exports only", async () => {
  const workspace = await read("app/components/workspaces.tsx");
  assert.match(workspace, /export \* from "\.\/shared\/workspace-implementations"/);
  for (const definition of ["function PlanPage", "function PortfolioWorkspace", "function AIWorkspace", "function AdvancedWorkspace"]) {
    assert.doesNotMatch(workspace, new RegExp(definition));
  }
  for (const entry of ["plan/PlanPage.tsx", "portfolio/PortfolioPage.tsx", "ask/AskPage.tsx", "terminal/AdvancedPage.tsx", "research/ExplorePage.tsx"]) {
    assert.match(await read(`app/components/${entry}`), /shared\/workspace-implementations/);
  }
});

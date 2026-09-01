import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";

const read=path=>readFileSync(new URL(`../${path}`,import.meta.url),"utf8");

test("Today treats partial and missing health as unknown, not zero",()=>{
  const source=read("app/components/today/TodayPage.tsx");
  assert.match(source,/health\?:/);
  assert.match(source,/Health score unavailable/);
  assert.match(source,/No score or zero-value substitute was inferred/);
  assert.match(source,/showActions&&/);
  assert.match(source,/showHoldings&&/);
  assert.match(source,/Portfolio snapshot unavailable/);
  assert.match(source,/Retry portfolio snapshot/);
});

test("Research uses bounded staged payloads and explicit lazy sections",()=>{
  const ui=read("app/components/research/ResearchDiscovery.tsx");
  const api=read("backend/main.py");
  assert.match(ui,/\/header\$\{params\}/);
  assert.match(ui,/\/core\$\{params\}/);
  assert.match(ui,/\/sections\/\$\{s\}/);
  assert.doesNotMatch(ui,/\/overview\$\{params\}/);
  assert.match(api,/def research_security_section/);
  assert.match(api,/_research_header_projection\(cached_model\)/);
  assert.match(ui,/limit=\{details\[id\]\?undefined:5\}/);
  assert.match(ui,/Load full \$\{title\}/);
  assert.match(ui,/<Compact id=\{id\} num=\{num\} title=\{title\} model=\{details\[id\]!\} embedded\/>/);
});

test("Portfolio editor is not mounted in the default overview",()=>{
  const source=read("app/components/portfolio/PortfolioPage.tsx");
  assert.match(source,/if\(editing\)return/);
  assert.match(source,/Edit holdings/);
  assert.match(source,/portfolio-summary-first/);
});

test("route error boundary and budget telemetry cover major workspaces",()=>{
  assert.match(read("app/components/shell/AppShell.tsx"),/RouteErrorBoundary route=\{activeTab\}/);
  assert.match(read("app/lib/frontend-budget-telemetry.ts"),/PerformanceObserver/);
  for(const path of ["app/components/today/TodayPage.tsx","app/components/portfolio/PortfolioPage.tsx","app/components/research/ResearchDiscovery.tsx"])
    assert.match(read(path),/data-route-budget=/);
  assert.match(read("app/lib/frontend-budget-telemetry.ts"),/JSON\.stringify\(enriched\)/);
});

test("portfolio switching clears stale overview atomically and contains background research failures",()=>{
  const source=read("app/Dashboard.tsx");
  assert.match(source,/setPortfolioOverview\(current => String\(current\?\.portfolio\?\.id \|\| ""\) === String\(portfolio\.id\) \? current : null\)/);
  assert.match(source,/void loadResearch\(selected\.holdings\)\.catch\(\(\) =>/);
  assert.match(source,/Background Research refresh is temporarily unavailable/);
});

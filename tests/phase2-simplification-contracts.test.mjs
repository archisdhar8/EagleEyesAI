import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";

const read=path=>readFileSync(new URL(`../${path}`,import.meta.url),"utf8");

test("Ask mounts a bounded latest window and can reveal older messages",()=>{
  const source=read("app/components/shared/workspace-implementations.tsx");
  assert.match(source,/count:40/);
  assert.match(source,/messages\.slice\(Math\.max\(0,messages\.length-visibleCount\)\)/);
  assert.match(source,/Load \{Math\.min\(40,hiddenCount\)\} earlier messages/);
  assert.match(source,/node\.scrollTop\+=node\.scrollHeight-restoreHeight\.current/);
  assert.match(source,/mounted_messages:visibleMessages\.length/);
});

test("conversation cache and browser snapshot are explicitly bounded",()=>{
  const source=read("app/Dashboard.tsx");
  assert.match(source,/CONVERSATION_CACHE_ENTRIES=3/);
  assert.match(source,/CONVERSATION_CACHE_BYTES=2_000_000/);
  assert.match(source,/CONVERSATION_SNAPSHOT_MESSAGES=40/);
  assert.match(source,/CONVERSATION_SNAPSHOT_BYTES=500_000/);
  assert.match(source,/cache\.delete\(oldest\)/);
  assert.match(source,/messages\.slice\(-CONVERSATION_SNAPSHOT_MESSAGES\)/);
});

test("Portfolio Edit mounts no more than 25 rows while updating canonical parent state",()=>{
  const source=read("app/components/shared/workspace-implementations.tsx");
  assert.match(source,/EDIT_PAGE_SIZE=25/);
  assert.match(source,/holdings\.slice\(pageStart,pageStart\+EDIT_PAGE_SIZE\)/);
  assert.match(source,/const i=pageStart\+localIndex/);
  assert.match(source,/update\(i, "ticker"/);
  assert.match(source,/mounted_edit_rows:mountedHoldings\.length/);
});

test("Decisions keeps heavy workflows behind security selection",()=>{
  const source=read("app/components/decisions/DecisionsPage.tsx");
  assert.match(source,/securityUniverse\.slice\(0,12\)/);
  assert.match(source,/workspace && !selectedTicker && <section className="decisions-progressive-entry"/);
  assert.match(source,/workspace && selectedTicker && <>/);
  assert.match(source,/function LazyDecisionLab/);
  assert.match(source,/open&&\(holdings\.length/);
  assert.match(source,/form\.ticker\.trim\(\)\.toUpperCase\(\)!==selectedTicker/);
  assert.match(source,/requestVersion!==draftRequestVersion\.current\|\|selectedTickerRef\.current!==requestTicker/);
});

test("generated dashboards cap initial widgets, defer heavy data, and abort obsolete streams",()=>{
  const shared=read("app/components/shared/workspace-implementations.tsx");
  const dashboard=read("app/Dashboard.tsx");
  const ask=read("app/components/ask/AskPage.tsx");
  assert.match(shared,/allWidgets\.slice\(0,6\)/);
  assert.match(shared,/Load detailed chart or table/);
  assert.match(shared,/retained_heavy_widget_bytes/);
  assert.match(dashboard,/dashboardStreamController\.current\?\.abort\(\)/);
  assert.match(dashboard,/signal:lifecycleController\.signal/);
  assert.match(dashboard,/tab!=="ask"/);
  assert.match(ask,/eagleeyes:canvas-closed/);
});

test("Research uses one section trust line with explicit disclosure",()=>{
  const source=read("app/components/research/ResearchDiscovery.tsx");
  assert.match(source,/function SectionTrust/);
  assert.match(source,/Sources, freshness & methods/);
  assert.match(source,/<SectionTrust fields=\{fields\}/);
  assert.doesNotMatch(source,/fields\.map\(f=><div key=\{f\.key\}>.*<Details field=\{f\}/);
});

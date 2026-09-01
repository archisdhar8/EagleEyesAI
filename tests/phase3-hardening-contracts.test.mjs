import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";

const read=path=>readFileSync(new URL(`../${path}`,import.meta.url),"utf8");

test("secondary routes are lazy with an accessible reduced-motion skeleton",()=>{
  const dashboard=read("app/Dashboard.tsx");
  const css=read("app/globals.css");
  for(const route of ["LearnPage","DecisionsPage","MarketClimatePage"]){
    assert.match(dashboard,new RegExp(`lazy\\(\\(\\)=>import\\(\\"\\./components/.+/${route}\\"\\)`));
  }
  assert.match(dashboard,/Suspense fallback=\{<RouteSkeleton/);
  assert.match(dashboard,/role="status" aria-live="polite"/);
  assert.match(css,/\.route-skeleton/);
  assert.match(css,/@media \(prefers-reduced-motion: reduce\)/);
});

test("Research detail requests abort on replacement, ticker change, route change, and unmount",()=>{
  const source=read("app/Dashboard.tsx");
  assert.match(source,/researchDetailController=useRef<AbortController\|null>/);
  assert.match(source,/Research ticker changed/);
  assert.match(source,/Research detail request replaced/);
  assert.match(source,/Research route closed/);
  assert.match(source,/Dashboard unmounted/);
  assert.match(source,/\/sections\\\//);
});

test("frontend telemetry enforces tolerant DOM, payload, message, row, and widget budgets",()=>{
  const source=read("app/lib/frontend-budget-telemetry.ts");
  assert.match(source,/preferred: 1_500, warning: 2_000, review: 2_500/);
  assert.match(source,/"research\.header": 50_000/);
  assert.match(source,/"research\.core": 150_000/);
  assert.match(source,/"research\.section": 200_000/);
  assert.match(source,/mountedMessages: 40/);
  assert.match(source,/mountedEditRows: 30/);
  assert.match(source,/activeDashboardWidgets: 6/);
  assert.match(source,/console\.warn/);
});

test("heap instrumentation is opt-in and long tasks over 100ms are recorded",()=>{
  const source=read("app/lib/frontend-budget-telemetry.ts");
  assert.match(source,/eagleeyes-perf-instrumentation/);
  assert.match(source,/data-eagleeyes-perf-buffer/);
  assert.match(source,/slice\(-50\)/);
  assert.match(source,/usedJSHeapSize/);
  assert.match(source,/entry\.duration > 100/);
  assert.match(source,/type: "longtask", buffered: true/);
});

test("Market Climate and Learn defer secondary density without deleting content",()=>{
  const market=read("app/components/markets/MarketClimatePage.tsx");
  const learn=read("app/components/learn/LearnPage.tsx");
  assert.match(market,/Top three forces shaping the current state/);
  assert.match(market,/market-climate-disclosure/);
  assert.match(market,/Prediction markets and upcoming events/);
  assert.match(learn,/Continue: \{currentLesson\.title\}/);
  assert.match(learn,/learn-catalog-disclosure/);
  assert.match(learn,/Browse all learning paths/);
});

test("Ask supports deterministic compact, standard, and detailed modes",()=>{
  const backend=read("backend/ask_resolution.py");
  const main=read("backend/main.py");
  assert.match(backend,/class AnswerMode\(StrEnum\)/);
  assert.match(backend,/COMPACT = "COMPACT"/);
  assert.match(backend,/STANDARD = "STANDARD"/);
  assert.match(backend,/DETAILED = "DETAILED"/);
  assert.match(main,/apply_answer_mode/);
  assert.match(main,/"answer_mode": answer_mode\.value/);
});

test("core-only Research sections bypass the portfolio-aware consolidated path",()=>{
  const source=read("backend/main.py");
  assert.match(source,/_RESEARCH_CORE_ONLY_SECTIONS/);
  assert.match(source,/if section in _RESEARCH_CORE_ONLY_SECTIONS:\n\s+core_result = _cached_research_core/);
  assert.match(source,/source_path = "core_projection"/);
  assert.match(source,/research\.section\.latency/);
});

import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const root=new URL("../",import.meta.url);
const read=path=>fs.readFileSync(new URL(path,root),"utf8");

test("five primary decision-lifecycle destinations remain the only primary navigation",()=>{
  const routes=read("app/lib/routes.ts");
  const block=routes.match(/PRIMARY_NAV_ITEMS[\s\S]*?SECONDARY_NAV_ITEMS/)?.[0]||"";
  for(const label of ["Today","Portfolio","Research","Decisions","Ask EagleEyes"])assert.match(block,new RegExp(label));
  for(const label of ["Plan & profile","Learn","Advanced"])assert.doesNotMatch(block,new RegExp(label));
});

test("shared trust vocabulary distinguishes facts, models, markets, beliefs, and interpretation",()=>{
  const trust=read("app/components/shared/EvidenceTrust.tsx");
  for(const kind of ["VERIFIED_FACT","MODEL_OUTPUT","MARKET_IMPLIED","USER_BELIEF","AI_INTERPRETATION"])assert.match(trust,new RegExp(kind));
  for(const state of ["UNAVAILABLE","INSUFFICIENT_DATA","STALE","PARTIAL_COVERAGE","UNSUPPORTED"])assert.match(trust,new RegExp(state));
  assert.match(trust,/As known on/);
});

test("alerts remain in-app, attention-derived, grouped, and preference controlled",()=>{
  const today=read("app/components/today/TodayPage.tsx");
  const backend=read("backend/product_preferences.py");
  assert.match(today,/In-app alert center/);assert.match(today,/Email and push are intentionally not enabled/);
  assert.match(backend,/group_key/);assert.match(backend,/supersedes_id/);assert.match(backend,/attention_items/);
});

test("decision inferences require explicit accept edit or dismiss",()=>{
  const decisions=read("app/components/decisions/DecisionsPage.tsx");
  assert.match(decisions,/>Accept</);assert.match(decisions,/>Edit & accept</);assert.match(decisions,/>Dismiss</);
  assert.match(decisions,/Insufficient evidence/);
});

test("Ask orchestration limits remain bounded",()=>{
  const orchestration=read("backend/ask_orchestration.py");
  assert.match(orchestration,/MAX_TOOL_CALLS = 3/);assert.match(orchestration,/MAX_RETRIES = 0/);assert.match(orchestration,/ASK_TOOL_BUDGET_SECONDS/);
  assert.match(orchestration,/"SCENARIO": \("portfolio_scenario",\)/);assert.match(orchestration,/"RESEARCH_RANKING": \("security_ranking",\)/);
});

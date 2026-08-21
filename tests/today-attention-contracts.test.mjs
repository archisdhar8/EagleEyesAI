import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const root = new URL("../", import.meta.url);
const read = (path) => readFile(new URL(path, root), "utf8");

test("Today is snapshot-first with a unified Action Center", async () => {
  const [page, attention, dashboard] = await Promise.all([
    read("app/components/today/TodayPage.tsx"),
    read("backend/attention.py"),
    read("app/Dashboard.tsx"),
  ]);
  assert.match(page, /Restoring the latest portfolio snapshot/);
  assert.match(page, /Preparing the first portfolio snapshot/);
  assert.match(page, /Future visits load the saved result immediately/);
  assert.match(dashboard, /Your saved portfolio is loaded/);
  assert.match(dashboard, /eagleeyes-today-refresh/);
  assert.match(dashboard, /Fresh price and macro checks are continuing in the background/);
  assert.match(page, /What changed/);
  assert.match(page, /Action Center/);
  assert.match(page, /Investigate/);
  assert.match(page, /Snooze/);
  assert.match(attention, /THESIS_BREAKER_TRIGGERED/);
  assert.match(attention, /breaker_override/);
  assert.match(attention, /NO_MATERIAL_EVIDENCE_CHANGE/);
  assert.match(attention, /def price_context\(/);
  assert.match(attention, /"price_context": price_context\(/);
});

test("Today refresh returns stored evidence before slow providers finish", async () => {
  const backend = await read("backend/main.py");
  assert.match(backend, /BackgroundTasks/);
  assert.match(backend, /background_tasks\.add_task\(_refresh_home_sources\)/);
  assert.match(backend, /_HOME_REFRESH_LOCK\.acquire\(blocking=False\)/);
  assert.doesNotMatch(backend, /def refresh_home_briefing[\s\S]{0,900}refresh_tiingo/);
});

test("Today restores its last completed brief and avoids duplicate portfolio research", async () => {
  const [dashboard, backend, analysis, dailyWorkflow, marketWorkflow] = await Promise.all([
    read("app/Dashboard.tsx"), read("backend/main.py"), read("backend/analysis.py"),
    read(".github/workflows/ingest-daily.yml"), read(".github/workflows/ingest-markets.yml"),
  ]);
  assert.match(dashboard, /eagleeyes-today-cache/);
  assert.match(dashboard, /36\*60\*60\*1000/);
  assert.match(backend, /_overview\(user, include_research=False\)/);
  assert.match(backend, /security_research\(portfolio_tickers, price_limit=40, stored=security_bundle\)/);
  assert.match(analysis, /stored: dict\[str, Any\] \| None = None/);
  assert.match(dailyWorkflow, /cron:/);
  assert.match(marketWorkflow, /cron:/);
});

test("attention state and Today chat tools stay authenticated and owner-scoped", async () => {
  const [main, migration] = await Promise.all([
    read("backend/main.py"),
    read("supabase/migrations/202608160005_today_attention_states.sql"),
  ]);
  assert.match(main, /\/api\/today\/attention\/\{attention_item_id\}\/state/);
  assert.match(main, /Depends\(require_user\)/);
  assert.match(main, /def _today_attention_chat_tools/);
  assert.match(main, /latest_briefing_snapshot\(user_id\)/);
  assert.match(migration, /auth\.uid\(\) = user_id/);
  assert.match(migration, /SNOOZED/);
});

test("attention layout has explicit tablet and mobile adaptations", async () => {
  const css = await read("app/globals.css");
  assert.match(css, /@media\s*\(max-width:\s*900px\)[\s\S]*today-attention-hero/);
  assert.match(css, /@media\s*\(max-width:\s*620px\)[\s\S]*today-portfolio-strip/);
});

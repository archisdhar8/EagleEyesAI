import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const root = new URL("../", import.meta.url);
const read = (path) => readFile(new URL(path, root), "utf8");

test("Today is attention-first and keeps price movement contextual", async () => {
  const [page, attention, dashboard] = await Promise.all([
    read("app/components/today/TodayPage.tsx"),
    read("backend/attention.py"),
    read("app/Dashboard.tsx"),
  ]);
  assert.match(page, /Your portfolio is up to date/);
  assert.match(page, /Preparing your daily brief/);
  assert.match(page, /restore it automatically on future sign-ins/);
  assert.match(dashboard, /Your saved portfolio is loaded/);
  assert.match(dashboard, /eagleeyes-today-refresh/);
  assert.match(dashboard, /Fresh price and macro checks are continuing in the background/);
  assert.match(page, /Nothing material changed/);
  assert.match(page, /Price is context/);
  assert.match(page, /Mark read/);
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

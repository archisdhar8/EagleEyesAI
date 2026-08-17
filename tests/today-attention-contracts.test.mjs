import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const root = new URL("../", import.meta.url);
const read = (path) => readFile(new URL(path, root), "utf8");

test("Today is attention-first and keeps price movement contextual", async () => {
  const [page, attention] = await Promise.all([
    read("app/components/today/TodayPage.tsx"),
    read("backend/attention.py"),
  ]);
  assert.match(page, /What requires my attention today\?/);
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

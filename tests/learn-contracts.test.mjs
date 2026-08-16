import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const root = new URL("../", import.meta.url);
const read = async path => readFile(new URL(path, root), "utf8");

test("Learn is a canonical workspace with versioned lesson routes", async () => {
  const routes = await read("app/lib/routes.ts");
  assert.match(routes, /"learn", "◇", "Learn"/);
  assert.match(routes, /pathname\.match\(\/\^\\\/learn\\\//);
  const dashboard = await read("app/Dashboard.tsx");
  assert.match(dashboard, /import \{ LearnPage \}/);
  assert.match(dashboard, /tab === "learn"/);
});

test("curriculum is stored in source control and not duplicated into Supabase", async () => {
  const catalog = JSON.parse(await read("content/learn/catalog.json"));
  assert.equal(catalog.modules.length, 3);
  assert.equal(catalog.lessons.length, 9);
  assert.ok(catalog.lessons.every(lesson => lesson.content_version && lesson.source_refs.length));
  for (const lesson of catalog.lessons) {
    const markdown = await read(`content/learn/${lesson.content_file}`);
    assert.match(markdown, /^# /);
  }
  const migration = await read("supabase/migrations/202608150001_learning_workspace.sql");
  assert.doesNotMatch(migration, /lesson_content|lesson_markdown/);
});

test("learning schema is owner-scoped and excludes retired FinLearn social features", async () => {
  const migration = await read("supabase/migrations/202608150001_learning_workspace.sql");
  for (const table of ["learning_preferences", "learning_progress", "learning_quiz_attempts", "learning_tutor_threads", "learning_tutor_messages"]) {
    assert.match(migration, new RegExp(`alter table public\\.${table} enable row level security`, "i"));
  }
  assert.match(migration, /user_id=auth\.uid\(\)/);
  for (const forbidden of ["leaderboard", "direct_message", "seeded_user"]) assert.doesNotMatch(migration, new RegExp(forbidden, "i"));
});

test("the retired FinLearn app cannot enter the EagleEyes build or runtime", async () => {
  const tsconfig = JSON.parse(await read("tsconfig.json"));
  assert.ok(tsconfig.exclude.includes("FinLearnAI"));
  const app = await read("app/InvestmentApp.tsx");
  const backend = await read("backend/main.py");
  assert.doesNotMatch(app, /FINLEARN_/);
  assert.doesNotMatch(backend, /FINLEARN_/);
});

import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const dashboard = readFileSync(new URL("../app/Dashboard.tsx", import.meta.url), "utf8");

test("new conversation is local-first and does not wait for persistence", () => {
  const body = dashboard.split("function newChatConversation")[1].split("async function renameChatConversation")[0];
  assert.doesNotMatch(body, /await apiRequest|refreshConversationList|openChatConversation/);
  assert.match(body, /setResearchConversationId\(null\)/);
  assert.match(body, /setResearchChatMessages\(\[\]\)/);
  assert.match(body, /NEW_CHAT_STORAGE_VALUE/);
});

test("reload restoration is cancellation-safe and preserves an explicit new chat", () => {
  assert.doesNotMatch(dashboard, /restoredChatWorkspaces/);
  assert.match(dashboard, /remembered===NEW_CHAT_STORAGE_VALUE/);
  assert.match(dashboard, /window\.localStorage\.getItem\(storageKey\)!==selected/);
  assert.match(dashboard, /setResearchConversations\(rows\)/);
});

test("conversation deletion updates the sidebar before awaiting Supabase", () => {
  const body = dashboard.split("async function deleteChatConversation")[1].split("async function refreshConversationArtifacts")[0];
  const optimisticUpdate = body.indexOf("setResearchConversations(rows)");
  const networkDelete = body.indexOf("await apiRequest");
  assert.ok(optimisticUpdate >= 0);
  assert.ok(networkDelete > optimisticUpdate);
  assert.match(body, /setResearchConversations\(previousRows\)/);
});

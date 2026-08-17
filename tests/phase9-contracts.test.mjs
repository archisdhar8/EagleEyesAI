import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const dashboard = readFileSync("app/Dashboard.tsx", "utf8");
const ask = readFileSync("app/components/ask/AskPage.tsx", "utf8");
const shared = readFileSync("app/components/shared/workspace-implementations.tsx", "utf8");
const research = readFileSync("app/components/research/ResearchDiscovery.tsx", "utf8");
const backend = readFileSync("backend/main.py", "utf8");

test("primary Ask is conversation-first while preserving the calculated board", () => {
  assert.match(ask, /ResearchChat/);
  assert.match(ask, /Build or open a calculated research board/);
  assert.match(dashboard, /messages=\{researchChatMessages\}/);
});

test("page context is visible, controllable, and sent to the typed chat contract", () => {
  assert.match(ask, /Latest evidence/);
  assert.match(ask, /Saved thesis/);
  assert.match(ask, /Portfolio context/);
  assert.match(dashboard, /page_context:/);
  assert.match(backend, /class ChatPageContext/);
});

test("tool execution and grounded navigation are visible", () => {
  assert.match(shared, /ask-execution-plan/);
  assert.match(shared, /Continue in EagleEyes/);
  assert.match(backend, /execution_state/);
  assert.match(backend, /analysis_context/);
});

test("company research leads with six decision questions and workflow handoffs", () => {
  for (const question of [
    "Is the business improving?", "Is the balance sheet dangerous?", "What does the market expect?",
    "What am I paying?", "What changes the story?", "How does it fit the portfolio?",
  ]) assert.ok(research.includes(question), question);
  assert.match(research, /Ask about \{row\.ticker\}/);
  assert.match(research, /Record WATCH decision/);
  assert.match(research, /Test portfolio scenario/);
});

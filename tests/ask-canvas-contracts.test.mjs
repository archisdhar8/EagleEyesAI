import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const ask = readFileSync("app/components/ask/AskPage.tsx", "utf8");
const shared = readFileSync("app/components/shared/workspace-implementations.tsx", "utf8");
const css = readFileSync("app/globals.css", "utf8");

test("canvas visibility is independent from dashboard persistence", () => {
  assert.match(ask, /type CanvasState = "closed" \| "open"/);
  assert.match(ask, /setCanvasState\("closed"\)/);
  assert.match(ask, /setCanvasState\("open"\)/);
  assert.doesNotMatch(ask, /function closeCanvas[\s\S]{0,180}(onDiscard|setDashboard)/);
  assert.match(ask, /hasAnalysis = Boolean\(dashboardProps\.job \|\| dashboardArtifact\)/);
});

test("ordinary questions stay in chat while explicit visual requests open analysis", () => {
  assert.match(ask, /shouldOpenCanvasForQuestion/);
  assert.match(ask, /dashboard\|chart\|graph\|plot/);
  assert.match(ask, /performance\|exposure\|allocation\|drawdown\|analysis/);
  assert.match(ask, /if \(shouldOpenCanvasForQuestion\(request, hasAnalysis\)\) openCanvas\(\)/);
});

test("history and saved views are contextual controls instead of rails", () => {
  assert.match(ask, /aria-controls="ask-history-drawer"/);
  assert.match(shared, /className="ask-history-layer"/);
  assert.match(shared, /className="canvas-view-switcher"/);
  assert.match(shared, /!canvasMode&&<aside className="ai-command-panel">/);
  assert.match(css, /#ask-history-drawer/);
});

test("analysis can close, reopen, and switch to full-screen mobile panes", () => {
  assert.match(ask, /onClose=\{closeCanvas\}/);
  assert.match(ask, /analysisLabel} ↗/);
  assert.match(shared, /Open analysis ↗/);
  assert.match(ask, /role="tab"[\s\S]*Chat<\/button>/);
  assert.match(ask, /role="tab"[\s\S]*Analysis<\/button>/);
  assert.match(css, /\.canvas-open \.ask-chat-pane\.mobile-active/);
});

test("conversation changes close visible canvas context without deleting artifacts", () => {
  assert.match(ask, /onNew: \(\) => \{ pendingQuestionRef\.current = null; setHistoryOpen\(false\); closeCanvas\(\); controls\.onNew\(\); \}/);
  assert.match(ask, /onOpen: id => \{ pendingQuestionRef\.current = null; setHistoryOpen\(false\); closeCanvas\(\); controls\.onOpen\(id\); \}/);
  assert.match(ask, /onOpenArtifact: artifact =>[\s\S]{0,140}openCanvas\(\)/);
});

test("successful dashboard operations reveal their resulting analysis", () => {
  assert.match(ask, /operation\?\.action_result\?\.status !== "SUCCESS"/);
  assert.match(ask, /pendingQuestionRef\.current = request/);
  assert.match(ask, /window\.setTimeout\(openCanvas, 0\)/);
});

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
  assert.match(ask, /performance\|return\|exposure\|allocation\|drawdown\|analysis/);
  assert.match(ask, /const visualRequest = shouldOpenCanvasForQuestion\(request, hasAnalysis\)/);
  assert.match(ask, /if \(visualRequest\) openCanvas\(\)/);
});

test("history and saved views are contextual controls instead of rails", () => {
  assert.match(ask, /aria-controls="ask-history-drawer"/);
  assert.match(shared, /className="ask-history-layer"/);
  assert.match(shared, /className="canvas-view-switcher"/);
  assert.match(shared, /!canvasMode&&<aside className="ai-command-panel">/);
  assert.match(css, /#ask-history-drawer/);
});

test("analysis can close and reopen as a contextual split surface", () => {
  assert.match(ask, /onClose=\{closeCanvas\}/);
  assert.match(ask, /analysisLabel} ↗/);
  assert.match(shared, /Open analysis ↗/);
  assert.match(ask, /<section className={`ask-chat-pane/);
  assert.match(ask, /canvasOpen && <section className={`ask-canvas-pane/);
  assert.match(css, /\.canvas-open \.ask-content-shell\{grid-template-columns:minmax\(340px,38fr\) minmax\(560px,62fr\)\}/);
});

test("conversation changes close visible canvas context without deleting artifacts", () => {
  assert.match(ask, /onNew: \(\) => \{ pendingQuestionRef\.current = null; setHistoryOpen\(false\); closeCanvas\(\); controls\.onNew\(\); \}/);
  assert.match(ask, /onOpen: id => \{ pendingQuestionRef\.current = null; setHistoryOpen\(false\); closeCanvas\(\); controls\.onOpen\(id\); \}/);
  assert.match(ask, /onOpenArtifact: artifact =>[\s\S]{0,140}openCanvas\(\)/);
});

test("successful dashboard operations reveal their resulting analysis", () => {
  assert.match(ask, /operation\?\.action_result\?\.status !== "SUCCESS"/);
  assert.match(ask, /pendingQuestionRef\.current = visualRequest \? request : null/);
  assert.match(ask, /window\.setTimeout\(openCanvas, 0\)/);
});

test("mobile preserves chat and analysis with explicit tabs", () => {
  assert.match(ask, /ask-mobile-pane-tabs/);
  assert.match(ask, /"chat" \| "analysis"/);
  assert.match(ask, /aria-pressed=\{mobilePane === "chat"\}/);
  assert.match(ask, /aria-pressed=\{mobilePane === "analysis"\}/);
  assert.match(css, /\.ask-mobile-pane-tabs\{display:grid/);
  assert.match(css, /\.mobile-active\{display:block\}/);
});

test("verified result lineage and independent widget states are visible", () => {
  assert.match(shared, /source_result_id/);
  assert.match(shared, /Market-implied/);
  assert.match(shared, /Running historical analysis/);
  assert.match(shared, /Updated data available/);
  assert.match(shared, /Partial verified result/);
});

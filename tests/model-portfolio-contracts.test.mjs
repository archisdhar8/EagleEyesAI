import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const read = path => readFileSync(new URL(`../${path}`, import.meta.url), "utf8");

test("no-portfolio journey is reachable and keeps model holdings separate", () => {
  const routes = read("app/lib/routes.ts");
  const dashboard = read("app/Dashboard.tsx");
  const main = read("backend/main.py");
  const database = read("backend/database.py");
  const research = read("app/components/shared/workspace-implementations.tsx");
  const builder = read("app/components/research/ModelPortfolioBuilder.tsx");
  assert.match(dashboard, /useState<Holding\[\]>\(\[\]\)/);
  assert.doesNotMatch(main, /"Starter portfolio"/);
  assert.doesNotMatch(database, /"Starter portfolio"/);
  assert.match(routes, /portfolio-builder/);
  assert.match(research, /portfolio-builder/);
  assert.match(builder, /Ask EagleEyes for candidates/);
  assert.match(builder, /Save draft/);
  assert.match(builder, /Convert to tracked portfolio/);
  assert.match(builder, /not universally best investments/);
});

test("model portfolio builder exposes comparisons, benchmarks, and combined stress controls", () => {
  const builder = read("app/components/research/ModelPortfolioBuilder.tsx");
  for (const label of ["equal_weight", "lower_downside", "balanced", "quality_growth", "value", "income", "custom"]) {
    assert.match(builder, new RegExp(label));
  }
  assert.match(builder, /Backtest all alternatives/);
  assert.match(builder, /economic_state/);
  assert.match(builder, /inflation_state/);
  assert.match(builder, /rate_state/);
  assert.match(builder, /Stress \+ simulate selected/);
});

test("Ask EagleEyes starts as full-width chat and reveals a contextual canvas", () => {
  const ask = read("app/components/ask/AskPage.tsx");
  const css = read("app/globals.css");
  assert.match(ask, /ask-conversational-workspace/);
  assert.match(ask, /useState<CanvasState>\("closed"\)/);
  assert.match(ask, /variant="canvas"/);
  assert.match(ask, /className="ask-content-shell"/);
  assert.match(css, /\.ask-content-shell>\.ask-chat-pane/);
  assert.match(ask, /<section className={`ask-chat-pane/);
});

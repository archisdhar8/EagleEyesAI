import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const dashboard = fs.readFileSync(new URL("../app/Dashboard.tsx", import.meta.url), "utf8");
const workspace = fs.readFileSync(new URL("../app/components/shared/workspace-implementations.tsx", import.meta.url), "utf8");

test("portfolio imports remain selectable and new portfolios do not overwrite saved ones", () => {
  assert.match(dashboard, /setPortfolios\(current=>\[data\.portfolio,\.\.\.current\.filter/);
  assert.match(dashboard, /eagleeyes-active-portfolio-/);
  assert.match(dashboard, /portfolio\/diagnostics\?portfolio_id/);
  assert.match(dashboard, /analyses\/latest\?portfolio_id/);
  assert.match(workspace, /aria-label="Saved portfolio"/);
  assert.match(workspace, /New portfolio/);
  assert.match(workspace, /Stored with your account in Supabase/);
});

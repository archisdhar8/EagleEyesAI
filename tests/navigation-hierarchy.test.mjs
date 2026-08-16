import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const root = new URL("../", import.meta.url);
const read = async path => readFile(new URL(path, root), "utf8");

test("the investment decision lifecycle owns the five primary destinations", async () => {
  const routes = await read("app/lib/routes.ts");
  const primary = routes.slice(routes.indexOf("PRIMARY_NAV_ITEMS"), routes.indexOf("SECONDARY_NAV_ITEMS"));
  const expected = ["Today", "Portfolio", "Research", "Decisions", "Ask EagleEyes"];
  assert.deepEqual(expected.map(label => primary.indexOf(`\"${label}\"`) >= 0), expected.map(() => true));
  assert.deepEqual(expected.map(label => primary.indexOf(`\"${label}\"`)), [...expected].map(label => primary.indexOf(`\"${label}\"`)).sort((a, b) => a - b));
  for (const secondary of ["Plan & profile", "Learn", "Advanced"]) assert.equal(primary.includes(`\"${secondary}\"`), false);
});

test("secondary tools remain discoverable without entering primary navigation", async () => {
  const shell = await read("app/components/shell/AppShell.tsx");
  const routes = await read("app/lib/routes.ts");
  assert.match(shell, /aria-label="Primary navigation"/);
  assert.match(shell, /aria-label="Secondary navigation"/);
  assert.match(shell, /SECONDARY_NAV_ITEMS/);
  assert.match(routes, /"plan", "◌", "Plan & profile"/);
});

test("Decision Lab has one canonical workspace and preserves its old deep links", async () => {
  const routes = await read("app/lib/routes.ts");
  const decisions = await read("app/components/decisions/DecisionsPage.tsx");
  const portfolio = await read("app/components/shared/workspace-implementations.tsx");
  assert.match(routes, /"\/decision-lab"[^\n]+canonicalPath: "\/decisions"/);
  assert.match(routes, /pathname === "\/portfolio" && requestedView === "lab"/);
  assert.match(decisions, /<DecisionLab/);
  assert.doesNotMatch(portfolio, /\["lab","Decision Lab"\]/);
  assert.match(portfolio, /simulation_run"\)return "\/decisions"/);
});

test("responsive primary navigation stays aligned to the same five destinations", async () => {
  const css = await read("app/globals.css");
  assert.match(css, /sidebar nav\{grid-template-columns:repeat\(5,1fr\)!important\}/);
});

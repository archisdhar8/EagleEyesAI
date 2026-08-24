import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const root = new URL("../", import.meta.url);
const read = async path => readFile(new URL(path, root), "utf8");

test("the simplified research lifecycle and market climate own the five primary destinations", async () => {
  const routes = await read("app/lib/routes.ts");
  const primary = routes.slice(routes.indexOf("PRIMARY_NAV_ITEMS"), routes.indexOf("SECONDARY_NAV_ITEMS"));
  const expected = ["Today", "Portfolio", "Research", "Market Climate", "Ask EagleEyes"];
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

test("normal detail is the default and the only global presentation override is Expert mode", async () => {
  const shell = await read("app/components/shell/AppShell.tsx");
  const presentation = await read("app/lib/presentation-level.ts");
  assert.match(shell, /Expert mode/);
  assert.match(shell, /presentationLevel==="expert"\?"detailed":"expert"/);
  assert.doesNotMatch(shell, /PRESENTATION_LEVELS\.map/);
  assert.doesNotMatch(shell, /aria-label="Presentation level"/);
  assert.match(presentation, /value === "expert" \? "expert" : "detailed"/);
});

test("thesis and legacy Decision Lab links resolve to the guided decision workspace", async () => {
  const routes = await read("app/lib/routes.ts");
  assert.match(routes, /"\/decisions": \{ tab: "decisions" \}/);
  assert.match(routes, /"\/decision-lab"[^\n]+canonicalPath: "\/decisions"/);
  assert.match(routes, /"decisions", "◇", "Theses & decisions"/);
  assert.match(routes, /pathname === "\/portfolio" && requestedView === "lab"/);
  assert.match(routes, /tab: "explore", exploreView: "stocks", canonicalPath: "\/research"/);
});

test("responsive primary navigation is not hard-coded to the retired six-destination grid", async () => {
  const css = await read("app/globals.css");
  assert.doesNotMatch(css, /sidebar nav\{grid-template-columns:repeat\(6,1fr\)!important\}/);
});

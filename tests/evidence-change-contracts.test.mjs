import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const research = readFileSync(new URL("../app/components/research/ResearchDiscovery.tsx", import.meta.url), "utf8");
const backend = readFileSync(new URL("../backend/main.py", import.meta.url), "utf8");

test("company research exposes a bounded what-changed Ask route", () => {
  assert.match(research, /What changed\?/);
  assert.match(research, /research_section/);
  assert.match(research, /research_capabilities/);
  assert.match(backend, /evidence\.get_changes\(user\.id, normalized, baseline_type="LAST_RESEARCH_REVIEW"\)/);
});

test("typed evidence routes stay authenticated and AI-callable", () => {
  assert.match(backend, /\/api\/evidence\/securities\/\{ticker\}\/changes/);
  assert.match(backend, /Depends\(require_user\)/);
  assert.match(backend, /tool_name": "evidence_changes"/);
  assert.match(backend, /deterministic changes since review/);
});

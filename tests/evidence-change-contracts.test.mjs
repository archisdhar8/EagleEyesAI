import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const research = readFileSync(new URL("../app/components/research/ResearchDiscovery.tsx", import.meta.url), "utf8");
const backend = readFileSync(new URL("../backend/main.py", import.meta.url), "utf8");

test("company research exposes a bounded what-changed review surface", () => {
  assert.match(research, /What changed\?/);
  assert.match(research, /Mark evidence reviewed/);
  assert.match(research, /Coverage and missing evidence/);
  assert.match(research, /evidence\/securities\/\$\{ticker\}\/changes/);
  assert.match(research, /LAST_RESEARCH_REVIEW/);
});

test("typed evidence routes stay authenticated and AI-callable", () => {
  assert.match(backend, /\/api\/evidence\/securities\/\{ticker\}\/changes/);
  assert.match(backend, /Depends\(require_user\)/);
  assert.match(backend, /tool_name": "evidence_changes"/);
  assert.match(backend, /deterministic changes since review/);
});

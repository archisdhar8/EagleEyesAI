import test from "node:test";
import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";

const root=new URL("../",import.meta.url);const read=path=>readFile(new URL(path,root),"utf8");

test("decision recording captures immutable context and append-only reviews",async()=>{const [service,theses,migration]=await Promise.all([read("backend/decision_journal.py"),read("backend/theses.py"),read("supabase/migrations/202608160006_decision_journal.sql")]);assert.match(service,/decision-context-v1/);assert.match(service,/Current values are never substituted/);assert.match(theses,/decision_journal\.insert_snapshot/);assert.match(migration,/unique\(decision_id,horizon_key,window_end\)/);assert.doesNotMatch(migration,/grant select,insert,update/);});

test("Decisions exposes journal reviews without equating return and process",async()=>{const [page,main]=await Promise.all([read("app/components/decisions/DecisionsPage.tsx"),read("backend/main.py")]);assert.match(page,/Decision Journal/);assert.match(page,/Review reasoning separately from returns/);assert.match(page,/Complete retrospective/);assert.match(main,/\/api\/decision-journal/);assert.match(main,/def _decision_journal_chat_tools/);});

test("Today receives due decision reviews and learning has sample safeguards",async()=>{const [attention,service]=await Promise.all([read("backend/attention.py"),read("backend/decision_journal.py")]);assert.match(attention,/_decision_review_candidates/);assert.match(attention,/linked_decision_id/);assert.match(service,/INSUFFICIENT_SAMPLE/);assert.match(service,/Brier score/);assert.match(service,/minimum_sample/);});

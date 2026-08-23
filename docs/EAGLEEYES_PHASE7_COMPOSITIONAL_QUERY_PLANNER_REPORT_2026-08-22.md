# EagleEyes Phase 7 — General Compositional Financial Query Planner

Date: 2026-08-22

## A. Capability registry

Registry version: `capability-registry-v1`. The registry contains descriptors, schemas, constraints, and relationships only. It contains no Python callables, SQL, URLs, or arbitrary function selectors.

Every descriptor exposes `name`, `description`, `supported_intents`, `supported_entities`, `input_schema`, `output_schema`, `synchronous`, `heavy_job`, `expected_latency_class`, `required_context`, `optional_context`, `internal_dependencies`, `can_compose_with`, `safety_constraints`, and entity bounds.

| Capability | Input/entity constraint | Output | Class | Internal dependency | Composition/constraint summary |
|---|---|---|---|---|---|
| `company_analysis` | 1 security | `CompanyAnalysisResult` | sync | company-analysis read model | Earnings where supported; verified values only |
| `company_comparison` | 2–5 securities; portfolio optional | `CompanyComparisonResult` | sync | `company_analysis` | May compose with portfolio risk/fit |
| `valuation_ranking` | active portfolio | `AnalysisResult` | sync | portfolio-factor read model | Relative valuation evidence; no return forecast |
| `multifactor_screen` | active portfolio | `AnalysisResult` | sync | portfolio-factor read model | Fundamental trend/valuation/momentum screen |
| `score_attribution` | security/portfolio | `AnalysisResult` | sync | score-attribution read model | Supported score inputs and history only |
| `historical_change` | 0–1 security or macro factor | `HistoricalComparison` | sync | compatible append-only baseline | No fake last-review baseline |
| `portfolio_overview` | active portfolio | `AnalysisResult` | sync | portfolio-opportunity read model | Opportunity evidence, not expected return |
| `portfolio_risk` | active portfolio | `AnalysisResult` | sync | portfolio-risk read model | Position/concentration risk |
| `portfolio_intelligence` | active portfolio | `AnalysisResult` | sync | portfolio-risk read model | Themes, dependencies, mapped macro exposure |
| `watchlist_comparison` | portfolio/watchlist | `AnalysisResult` | sync | watchlist-comparison read model | Supported candidates only |
| `thesis_replacement` | portfolio/security | `AnalysisResult` | sync | watchlist + thesis-status read models | Recommendation verification retained |
| `portfolio_change` | active portfolio | `AnalysisResult` | sync | portfolio-change read model | Compatible baseline required |
| `data_quality` | active portfolio | `AnalysisResult` | sync | data-quality read model | Coverage is never upgraded |
| `portfolio_events` | active portfolio | `AnalysisResult` | sync | events read model | Stored supported events only |
| `thesis_monitor` | security/portfolio | `AnalysisResult` | durable job | `THESIS_MONITOR` | Qualitative classification remains evidence-bound |
| `thesis_invalidation` | security/portfolio | `AnalysisResult` | sync | thesis-status read model | User thesis state remains distinct |
| `recommendation_countercase` | portfolio/security | `AnalysisResult` | sync | opportunity + risk read models | Preserves opposing evidence |
| `cash_allocation` | active portfolio | `AnalysisResult` | sync | watchlist-comparison read model | No superiority-to-cash claim without hurdle |
| `portfolio_analysis` | active portfolio | `AnalysisResult` | durable job | `OPTIMIZATION` + compatibility model | No trades; tax/cost prerequisites retained |
| `macro_state` | macro factors; portfolio optional | `MacroStateResult` | sync | macro-state read model | Portfolio exposure is mapped enrichment |
| `market_state` | portfolio optional | `MarketStateResult` | sync | market-state read model | Portfolio fit only when supported |
| `prediction_markets` | event; portfolio optional | `PredictionMarketResult` | sync | prediction-market read model | `MARKET_IMPLIED_EVIDENCE`, not fact |
| `portfolio_scenario` | portfolio + supported scenario factors | `AnalysisResult` | durable job | scenario read model or `SIMULATION` | Unsupported factors rejected |
| `portfolio_backtest` | portfolio + benchmark/time | `BacktestResult` | durable job | `BACKTEST` | Completed result reused or returns `PENDING` |
| `company_research` | 1–3 securities | `AnalysisResult` | durable job | `COMPANY_RESEARCH_BUILD` | Never runs synchronously in Ask |
| `security_ranking` | active portfolio | `AnalysisResult` | sync | opportunity read model | Stored evidence only |
| `benchmark_outlook` | portfolio + benchmark | `AnalysisResult` | sync | compatible benchmark model | Precise unavailable result if absent |
| `today_attention` | optional portfolio | `AnalysisResult` | sync | briefing snapshot | Stored deterministic composition |
| `decision_journal` | security/portfolio | `AnalysisResult` | sync | append-only decisions/reviews | Classified as user belief/context |

The registry reuses current Ask names. Simulation and optimization remain exposed through the existing `portfolio_scenario` and `portfolio_analysis` boundaries rather than duplicate planner aliases.

## B. Planner contract

`CapabilityPlan` contains a bounded goal, resolved entities, optional `TimeContext`, portfolio requirement, typed steps, response mode, registry version, planner model, and prompt version. Each `CapabilityPlanStep` contains a stable step ID, registered capability, structured inputs, required/optional status, dependencies, a `ReasonCode`, and expected output schema.

Allowed reason codes are `PRIMARY_QUESTION`, `SUPPORTING_CONTEXT`, `PORTFOLIO_FIT`, `CHANGE_CONTEXT`, `SCENARIO_INPUT`, and `COMPARISON_CONTEXT`. No chain-of-thought is requested or persisted.

`ResolvedEntity`, `TimeContext`, and `ConversationAnalyticalContext` are typed. Limits are four synchronous capabilities, one heavy job, eight entities, five comparison entities, depth three, three dependencies per node, and one schema-repair attempt.

## C. Hybrid routing

High-confidence Phase 3–6 and established compound Phase 4 routes bypass the planner. Their planner latency is exactly zero. General, genuinely cross-domain, unusual-composition, and structured follow-up questions enter the planner.

The optional Gemini planner receives only the question, resolved entity IDs, capability descriptors, availability flags, and compact structured conversation context. It does not receive holdings, fundamentals, markets, read-model payloads, or database access. When Gemini is disabled or unavailable, the deterministic registered planner handles supported compositions. A malformed model plan gets at most one schema repair. A recognized direct route is the only failure fallback; unsupported general questions do not reach unrestricted Gemini reasoning.

## D. Deterministic validation

Validation rejects:

- registry-version mismatch;
- nonexistent capabilities or output-schema mismatch;
- duplicate/invalid step IDs;
- more than five total nodes, four synchronous nodes, or one heavy job;
- more than eight entities or a descriptor-specific entity-count violation;
- an entity not produced by deterministic resolution, including invented tickers;
- incompatible entity kinds;
- missing portfolio context;
- non-owner-scoped permissions;
- invalid time ranges;
- missing/self dependencies, cycles, depth over three, or more than three dependencies;
- unsupported scenario factors;
- arbitrary Python, code, function, SQL, or API URL inputs;
- a planner-selected capability outside the registry.

`score_capability_plan` gives higher cost to heavy, optional, and dependency nodes. The deterministic planner selects the smallest sufficient set and deduplicates capabilities.

## E. Execution

A validated plan is compiled into the existing `CapabilityExecutionPlan` and `ExecutionNode` DAG. Independent nodes retain bounded concurrency, absolute deadlines, database statement timeouts, and required/optional semantics. No second executor or recursive agent loop was added.

Heavy capabilities check a compatible completed result first. Otherwise they create/reuse the existing durable Phase 5 job and return `PENDING` with a stable job reference. The request never waits for simulation, optimization, backtesting, deep research, or qualitative thesis monitoring.

## F. Composition

`ComposedAnalysisResult` contains the question, stable result ID, canonical component `AnalysisResult` objects, overall status, source-classified supported findings, explicit conflicts, limitations, pending jobs, and coverage counts.

Overall status is deterministic:

- `SUCCESS`: every required component succeeded;
- `PARTIAL`: useful evidence remains but a required/important dimension is partial, unavailable, or pending;
- `UNAVAILABLE`: no usable answer remains because a critical requirement is unavailable;
- `PENDING`: the answer depends primarily on heavy work and no usable synchronous component exists;
- `FAILED`: a required component failed unexpectedly.

The renderer produces Answer, Key evidence, Counterevidence/tradeoffs, Missing evidence, and Confidence/coverage sections. It retains `VERIFIED_FACT`, `MODEL_OUTPUT`, `MARKET_IMPLIED_EVIDENCE`, `USER_BELIEF`, and `AI_INTERPRETATION` distinctions. It does not infer cross-capability causality or turn mapped exposure into a modeled loss.

## G. Conversation context and result references

Every canonical component receives `result_<fingerprint>` and each composition receives `composed_<fingerprint>`. Structured context records active entities, portfolio, comparison, capabilities, result IDs, and scenario factors. Follow-ups resolve from these fields, not reconstructed chat prose. The tests cover comparison/portfolio-fit continuity; the same contract supports scenario and risk/watchlist/cash continuations.

Planner cache keys include normalized query structure, resolved entities, and registry version. Only plans are cached; analytical results continue to use calculation-version and fingerprint-controlled read models/jobs.

## H. Gemini and observability

`GEMINI_PLANNER_MODEL` defaults to the configured Gemini model. `ASK_CAPABILITY_PLANNER_GEMINI=1` enables the strict planner. Prompt version is `capability-planner-v1`. The request uses JSON MIME mode and a response schema; validation still treats the model output as untrusted.

Telemetry records whether planning was invoked, model, prompt/registry version, planner latency, validation latency, repair attempted, node count, cache hit, and token counts when a provider exposes them. Execution, deterministic composition, optional narration, and total latency remain separate. Optional Gemini narration receives only the validated plan and verified canonical result evidence; failure returns the deterministic composition.

## I. Verification and acceptance

- Ask-15: `6 SUCCESS`, `4 PARTIAL`, `5 UNAVAILABLE`, `0 FAILED`; 15/15 deterministic answers and 15/15 persistence success. The initial Phase 7 run caught a hybrid-routing regression; the direct-route gate was corrected and the mandatory suite was rerun.
- Phase 6 domain suite: 20/20 quality PASS.
- Mixed-domain planner suite: 32/32 plan/validation PASS.
- Adversarial coverage: nonexistent capability, 20 nodes, cycle, two heavy jobs, invented entity, missing/unresolved entity, unsupported scenario, arbitrary Python/SQL, output mismatch, malformed schema, and one-repair bound.
- Partial failure: successful macro/portfolio evidence survives unavailable prediction evidence and overall status is `PARTIAL`.
- Heavy job: synchronous portfolio risk survives while backtest is `PENDING` with job reference.
- Follow-ups: structured entity/result context resolves comparison continuations without relying on prose.
- Full backend: 590 passed, 9 skipped, 2 dependency warnings, 0 failed.
- `git diff --check` and Python compilation pass.

Artifacts:

- `artifacts/phase7-planner-acceptance.json`
- `artifacts/phase7-planner-benchmark.json`
- `artifacts/phase6-acceptance.json`
- `artifacts/ask-15-phase6-gemini-disabled.json`
- `artifacts/ask-15-phase6-gemini-disabled.md`

## J. Performance

Local synthetic no-I/O boundary, 500 samples (not a production network SLO):

| Stage | Median | p95 |
|---|---:|---:|
| Direct-route classification | 0.0105 ms | 0.0146 ms |
| Deterministic general planning | 0.0138 ms | 0.0193 ms |
| Plan validation | 0.0090 ms | 0.0116 ms |
| Concurrent capability DAG boundary | 0.1230 ms | 0.1544 ms |
| Deterministic composition/render | 0.0611 ms | 0.0782 ms |
| Optional narration disabled | 0 ms | 0 ms |
| Total composed boundary | 0.2207 ms | 0.2724 ms |

Production capability latency remains dominated by owner-scoped database reads. Optional Gemini planning/narration latency and cost depend on the configured provider and are explicitly observed rather than included in the synthetic result.

## K. Unsupported question classes

EagleEyes still cannot reliably answer questions requiring missing tax lots, trading-cost estimates, a sourced cash/risk-free hurdle, complete historical/security-master survivorship, complete earnings consensus/guidance/estimate revisions, full company catalysts/macro calendar, broader comparable-company fundamentals, complete market breadth/valuation, prediction-market liquidity/calibration/portfolio mapping, unsupported scenario factors, causal loss estimates without a scenario model, or genuine last-review comparisons where no genuine review baseline exists.

It also cannot place trades, submit orders, execute portfolio changes, query arbitrary databases/APIs, run code selected by a model, or give an unrestricted AI-calculated financial answer.

## L. Phase 8 handoff

Phase 8 should connect the stable plan, composed result, source categories, result references, pending jobs, and structured context to conversational dashboard artifacts. Phase 8 was not started.

## M. Verdict

The planner selects only registered capabilities, every plan is schema- and rule-validated before execution, known routes remain stable, mixed-domain questions compose canonical evidence, partial failures preserve useful results, heavy work remains durable, follow-ups use structural context, and Gemini has no calculation authority.

PHASE 7 COMPLETE

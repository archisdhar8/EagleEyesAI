import type { Page, Route } from "@playwright/test";

const now = "2026-08-10T12:00:00Z";

export const defaultWidgets = [
  { id: "portfolio-return", type: "portfolio_return", size: "wide" },
  { id: "macro-indicators", type: "macro_indicators", size: "full" },
  { id: "market-monitor", type: "market_indicators", size: "small" },
];

const profile = {
  age: 35, retirement_age: 65, horizon_years: 30, account_type: "taxable",
  annual_contribution: 12000, annual_withdrawal: 0, target_value: 1000000,
  tax_rate: .25, risk_tolerance: 6, loss_capacity: 6, annual_income_need: 0,
  preset: "balanced", restrictions: [], watchlist: ["AAPL", "SPY"],
  objectives: { return: .25, volatility: .2, drawdown: .2, diversification: .2, turnover: .1, tax_drag: .05, income: 0 },
  research_preferences: { fundamentals: .25, growth: .25, valuation: .2, macro: .15, dividends: .1, price_behavior: .05 },
  suitability_profile: { version: "suitability-v1", guidance_level: "research_only", investing_experience: "intermediate", required_risk: 5, liquidity_needs_next_24_months: 0, income_stability: "stable", household_annual_income: 0, emergency_reserve_months: 6, major_debts: [], near_term_purchases: [], employer_stock_ticker: null, employer_stock_value: 0, household_status: "single", dependents: 0, outside_accounts_value: 0, outside_accounts_notes: "" },
  llm_provider: "disabled",
};

const scenarios = [
  { key: "economic_recession", label: "Recession", dimension: "Economic state", state: "Recession", probability: .24, confidence: .6, indicators: ["FRED"], sources: ["fixture"], as_of: now, is_prior: false },
  { key: "inflation_accelerating", label: "Accelerating", dimension: "Inflation state", state: "Accelerating", probability: .31, confidence: .6, indicators: ["FRED"], sources: ["fixture"], as_of: now, is_prior: false },
  { key: "shock_oil", label: "Oil-price shock", dimension: "Independent shocks", state: "Oil-price shock", probability: .18, confidence: .55, indicators: ["WTI"], sources: ["fixture"], as_of: now, is_prior: false },
];

const research = [
  { ticker: "AAPL", company: "Apple Inc.", sector: "Technology", industry: "Consumer Electronics", final_score: 76, growth_rating: 72, valuation_score: 58, fundamental_score: 84, industry_score: 78, technical_score: 67, news_score: 65, confidence: 88, data_quality: "high", risk_flags: ["technology_concentration"], price: 225, price_change_1y: .16, price_as_of: now, fundamentals_as_of: now, revenue_growth: .08, net_margin: .24, news_count: 2, data_source: "fixture" },
  { ticker: "SPY", company: "SPDR S&P 500 ETF", sector: "Broad Market", industry: "ETF", final_score: 69, growth_rating: 61, valuation_score: 65, fundamental_score: 70, industry_score: 73, technical_score: 69, news_score: 50, confidence: 92, data_quality: "high", risk_flags: [], price: 650, price_change_1y: .11, price_as_of: now, fundamentals_as_of: now, revenue_growth: null, net_margin: null, news_count: 0, data_source: "fixture" },
];

const learnLesson = {
  id: "why-invest", module_id: "start-safely", title: "Why save and invest?", estimated_minutes: 8,
  concept_ids: ["saving", "investing", "compounding", "inflation"], source_refs: ["investor-gov"],
  lab_ids: ["compound-growth", "inflation"], eagleeyes_links: [{ label: "Open Plan assumptions", route: "/plan" }],
  content_version: "2026.08.1", content: "# Why save and invest?\n\n## The central idea\n\nSaving protects money needed soon. Investing accepts uncertainty for longer-term growth.",
  sources: [{ id: "investor-gov", title: "Saving and Investing", publisher: "SEC Investor.gov", url: "https://www.investor.gov/" }],
  quiz: { id: "why-invest-v1", version: "1", questions: [{ question: "Which money belongs in savings?", options: ["Emergency money", "Thirty-year retirement money"] }, { question: "What is compounding?", options: ["Guaranteed returns", "Earlier growth can earn later growth"] }] },
};
const learnCatalog = {
  version: "learn-catalog-v1", preview_lesson_id: "why-invest",
  modules: [{ id: "start-safely", slug: "start-safely", title: "Start Investing Safely", description: "Build a financial foundation.", outcomes: ["Separate saving from investing"], prerequisites: [], lesson_ids: ["why-invest"], content_version: "2026.08.1" }, { id: "build-portfolio", slug: "build-portfolio", title: "Build a Portfolio", description: "Understand risk and diversification.", outcomes: ["Measure diversification"], prerequisites: ["start-safely"], lesson_ids: [], content_version: "2026.08.1" }, { id: "understand-markets", slug: "understand-markets", title: "Understand Markets", description: "Judge market evidence.", outcomes: ["Interpret evidence"], prerequisites: ["start-safely"], lesson_ids: [], content_version: "2026.08.1" }],
  lessons: [{ ...learnLesson, content: undefined, sources: undefined, quiz: undefined, quiz_id: "why-invest-v1", quiz_question_count: 2 }],
};

const briefing = {
  version: "today-briefing-v2", as_of: now, evidence_state: "current",
  guidance: { level: "General Market Research", reason: "No saved holdings are used; conclusions describe general market or security evidence.", missing_context: ["saved portfolio"] },
  headline: "Rates and technology concentration matter most today.",
  summary: "No urgent portfolio-specific change is supported by the available evidence.",
  portfolio_context: { available: false, holding_count: 0, missing_symbols: [], weak_coverage_symbols: [] },
  market_movement: [], market_indicators: [],
  leadership: { leading_sectors: [], lagging_sectors: [], leading_style: null, lagging_style: null, method: "Fixture adjusted returns." },
  portfolio_relevance: [], attention: [], upcoming_events: [], research_ideas: [], warnings: [],
  event_coverage: { requested_tickers: [], earnings_covered_tickers: [], earnings_missing_tickers: [], earnings_coverage_ratio: null, macro_release_count: 0, deduplicated_count: 0, note: "Fixture coverage" },
  calculation: { method: "deterministic_attention_rules", version: "today-briefing-v2", assumptions: ["Fixture evidence"] },
};

const widgetResult = (id: string, status: "READY" | "FAILED" = "READY") => ({
  widget_id: id, status, as_of: now,
  data: status === "READY" ? { total_return: .1, annualized_volatility: .14, series: [{ date: "2026-01-01", value: 0 }, { date: "2026-08-10", value: .1 }] } : {},
  lineage: [{ provider: "fixture", dataset: "adjusted_prices", retrieved_at: now, effective_through: now, symbols: ["AAPL", "SPY"], cache_status: "hit", dataset_version: "golden-v1" }],
  calculation: { method: id === "performance" ? "portfolio_performance" : "optional_fixture", version: "ai-workspace-calculations-v1.0.0", parameters: {} },
  quality: { data_quality: status === "READY" ? "high" : "low", reasons: ["Deterministic browser fixture"] },
  assumptions: ["Adjusted closes"], warnings: status === "FAILED" ? ["Optional provider unavailable"] : [],
  how_calculated: "Calculated from deterministic adjusted-price fixtures.",
  presentation: { unit: "Percent", x_axis: "Date", y_axis: "Return (%)", timeframe: "1 year", frequency: "Daily" },
});

function makeJob(id = "job-1", partial = false) {
  const widgets = [
    { id: "performance", task_id: "performance", widget_type: "portfolio_performance", title: "Portfolio performance", visualization: "line", grid: { x: 0, y: 0, w: 8, h: 2 } },
    { id: "optional", task_id: "optional", widget_type: "risk_summary", title: "Optional risk summary", visualization: "list", grid: { x: 8, y: 0, w: 4, h: 2 } },
  ];
  return {
    id, prompt: "Show my portfolio return and risks", state: partial ? "PARTIAL_SUCCESS" : "COMPLETE", progress: 100,
    plan: { version: "dashboard-plan-v2", intent: "portfolio_review", entities: { tickers: ["AAPL", "SPY"], sectors: [], themes: [] }, questions: ["performance"], time_range: "1y", requested_outputs: ["performance"], filters: {}, ambiguities: [] },
    specification: { version: "dashboard-spec-v2", spec_version: "dashboard-spec-v2", layout_version: "dashboard-layout-v2", title: "Portfolio return and risks", description: "Deterministic test board", compiler_version: "dashboard-compiler-v2", widgets, required_evidence_review: { status: "passed", checks: ["Required evidence ready"], issues: [] } },
    widget_results: [widgetResult("performance"), widgetResult("optional", partial ? "FAILED" : "READY")],
    narrative: "### Summary\nThe validated return evidence is available.\n\n### Risks and limitations\nOptional evidence may be unavailable.",
    warnings: partial ? ["One optional widget failed"] : [],
  };
}

export type MockState = ReturnType<typeof createState>;
type TerminalLayoutFixture = { id: string; name: string; widgets: typeof defaultWidgets; version: string };
type MockRequestBody = { name?: string; widgets?: typeof defaultWidgets; terminal_widgets?: typeof defaultWidgets; prompt?: string; operation?: string; width?: number; direction?: number; [key: string]: unknown };

function createState(options: { portfolio?: boolean; stale?: boolean; partial?: boolean } = {}) {
  const holdings = options.portfolio === false ? [] : [
    { ticker: "AAPL", weight: .6, market_value: 60000, cost_basis: 40000, account_type: "taxable" },
    { ticker: "SPY", weight: .4, market_value: 40000, cost_basis: 35000, account_type: "taxable" },
  ];
  return {
    options, holdings, terminalWidgets: structuredClone(defaultWidgets), terminalLayouts: [] as TerminalLayoutFixture[],
    views: [] as Array<ReturnType<typeof viewFromJob>>, job: makeJob("job-1", options.partial), requests: [] as Array<{ method: string; path: string; body: unknown }>,
    authGrants: [] as string[], learningProgress: [] as Array<Record<string, unknown>>, theses: [] as Array<Record<string, unknown>>,
  };
}

function json(route: Route, value: unknown, status = 200) {
  return route.fulfill({ status, contentType: "application/json", body: JSON.stringify(value) });
}

export async function installApiMock(page: Page, options: { portfolio?: boolean; stale?: boolean; partial?: boolean } = {}) {
  const state = createState(options);
  const homePayload = () => ({
    portfolio: state.holdings.length ? { id: "portfolio-1", name: "Browser portfolio", holdings: state.holdings } : null,
    preferences: { presentation_level: "detailed", density: "comfortable", macro_widgets: ["rates", "inflation", "growth", "labor", "credit"], research_widgets: ["market", "scores", "fundamentals", "news", "prediction_markets"], overview_widgets: [], focused_tickers: [], terminal_widgets: state.terminalWidgets },
    profile, briefing: { ...briefing, evidence_state: options.stale ? "stale_fallback" : "current", warnings: options.stale ? ["Using last validated provider snapshot"] : [], portfolio_context: { ...briefing.portfolio_context, available: state.holdings.length > 0, holding_count: state.holdings.length } },
    macro: { regime: "neutral", score: 50, as_of: now }, macro_factors: { factors: [] },
    scenarios: { condition_dimensions: scenarios, scenarios, contracts: [], fetched_at: now, warnings: options.stale ? ["Provider stale fallback"] : [] },
    research, data_status: { storage: "fixture", counts: {}, freshness: {}, providers: [] },
    regime_history: { latest: null, sample_counts: {}, total_samples: 0 }, model_monitoring: null, latest_analysis: null,
  });
  await page.route("**/auth/v1/token**", route => {
    state.authGrants.push(new URL(route.request().url()).searchParams.get("grant_type") || "unknown");
    return json(route, {
    access_token: "browser-access-token",
    refresh_token: "browser-refresh-token",
    token_type: "bearer",
    expires_in: 3600,
    expires_at: Math.floor(Date.now() / 1000) + 3600,
    user: {
      id: "00000000-0000-4000-8000-000000000001",
      aud: "authenticated",
      role: "authenticated",
      email: "browser@example.com",
      email_confirmed_at: now,
      app_metadata: { provider: "email", providers: ["email"] },
      user_metadata: {},
      created_at: now,
      updated_at: now,
    },
    });
  });
  await page.route("**/auth/v1/logout**", route => route.fulfill({ status: 204, body: "" }));
  await page.route("http://127.0.0.1:8000/api/**", async route => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace("/api", "");
    const method = request.method();
    let body: MockRequestBody = {};
    try { body = request.postDataJSON() as MockRequestBody; } catch { body = {}; }
    state.requests.push({ method, path, body });

    if (path === "/learn/catalog") return json(route, { ...learnCatalog, preferences: { selected_path: null, knowledge_level: "beginner", interests: [], portfolio_context_enabled: false }, progress: state.learningProgress });
    if (path === "/learn/lessons/why-invest") return json(route, learnLesson);
    if (path === "/learn/labs/compound-growth/calculate" && method === "POST") return json(route, { lab_id: "compound-growth", calculation_version: "learn-labs-v1", inputs: body.inputs, result: { final_value: 105092.51, contributed: 49000, modeled_growth: 56092.51 }, assumptions: ["Constant illustrative return"], warning: "Educational illustration only; not a forecast or recommendation." });
    if (path === "/learn/progress/why-invest" && method === "PUT") { state.learningProgress = [{ id: "progress-1", module_id: "start-safely", lesson_id: "why-invest", content_version: "2026.08.1", status: "completed", completion_percentage: 1, best_score: null, updated_at: now }]; return json(route, state.learningProgress[0]); }
    if (path === "/learn/progress" && method === "GET") return json(route, state.learningProgress);
    if (path === "/learn/quizzes/why-invest-v1/attempts" && method === "POST") { state.learningProgress = [{ id: "progress-1", module_id: "start-safely", lesson_id: "why-invest", content_version: "2026.08.1", status: "mastered", completion_percentage: 1, best_score: 1, updated_at: now }]; return json(route, { score: 2, total_questions: 2, percentage: 1, mastery_eligible: true, feedback: [{ correct: true, correct_index: 0, explanation: "Emergency money needs stability." }, { correct: true, correct_index: 1, explanation: "Earlier growth can earn later growth." }], progress: state.learningProgress[0] }, 201); }

    if (path === "/portfolios" && method === "GET") return json(route, state.holdings.length ? [{ id: "portfolio-1", name: "Browser portfolio", holdings: state.holdings, updated_at: now }] : []);
    if (/^\/portfolios\/[^/]+\/activate$/.test(path) && method === "POST") return json(route, { id: path.split("/")[2], name: "Browser portfolio", holdings: state.holdings, updated_at: now });
    if (path === "/home/briefing") return json(route, homePayload());
    if (path === "/home/refresh" && method === "POST") return json(route, { ...homePayload(), refresh: { status: "queued", requested_at: now, warnings: [], message: "Saved evidence is ready; configured providers are refreshing in the background." } });
    if (path === "/decisions/workspace") return json(route, { active_theses: state.theses, recent_decisions: [], needs_thesis: [], review_dates: [], contexts: {} });
    if (path === "/decision-journal") return json(route, { version: "decision-journal-v1", recent_decisions: [], ready_for_review: [], completed_retrospectives: [], patterns: { reviewed_decisions: 0, minimum_sample: 5, status: "INSUFFICIENT_SAMPLE", patterns: [] }, forecast_calibration: { sample_size: 0, brier_score: null, status: "INSUFFICIENT_SAMPLE", message: "No resolved forecasts.", buckets: [], methodology: "No calibration result without resolved forecasts." } });
    if (path === "/personalization" && method === "GET") return json(route, { version: "decision-preferences-v1", explicit: {}, accepted: {}, inferred: [], dismissed: [], minimum_reviewed_decisions: 5, reviewed_decisions: 0 });
    if (path === "/theses/drafts/AAPL" && method === "POST") return json(route, { saved: false, warning: "Unsaved draft. Review every suggestion before confirming it as your belief.", draft: { ticker: "AAPL", summary: "Durable services growth and ecosystem retention may support long-term cash generation.", base_case: "Services growth remains durable.", bull_case: "Growth accelerates with stable margins.", bear_case: "Device demand and margins weaken.", investment_horizon: "long", review_date: null, status: "DRAFT", current_version: 1, source_context: { evidence_sources: ["fixture research"] }, assumptions: [{ description: "Services growth remains durable", category: "GROWTH", importance: "HIGH", status: "UNTESTED", evidence_mapping: { source: "fixture research" } }], factors: [{ factor_type: "RISK", description: "Device replacement cycles weaken", evidence_mapping: { source: "fixture research" } }, { factor_type: "BREAKER", description: "Ecosystem retention deteriorates materially", evidence_mapping: { source: "fixture research" } }] } });
    if (path === "/theses" && method === "POST") { const saved = { ...body, id: "thesis-1", current_version: 1, created_at: now, updated_at: now }; state.theses = [saved]; return json(route, saved, 201); }
    if (/^\/theses\/[^/]+\/monitor$/.test(path)) return json(route, { thesis_id: "thesis-1", thesis_version: 1, ticker: "AAPL", baseline_review_at: now, evaluated_at: now, overall_status: "STABLE", requires_review: false, assumption_results: [], risk_results: [], catalyst_results: [], thesis_breaker_results: [], evidence_coverage: [], freshness: "CURRENT", evidence_quality: "HIGH", counts: { SUPPORTS: 0, WEAKENS: 0, CONTRADICTS: 0, INSUFFICIENT_EVIDENCE: 0 }, warnings: ["A monitoring baseline begins after the first review."], calculation_version: "fixture-monitor-v1" });
    if (/^\/theses\/[^/]+\/reviews$/.test(path) && method === "GET") return json(route, []);
    if (path === "/portfolio/diagnostics") return json(route, { as_of: now, sector_exposure: [], industry_exposure: [], account_allocation: [], marginal_risk: { status: "unavailable", positions: [] }, holdings_fund_overlap: { status: "unavailable", items: [] }, known_fund_costs: { status: "unavailable", items: [], estimated_annual_dollars: null }, tax_data_completeness: { status: "partial", taxable_positions: 0, cost_basis_known: 0, acquisition_dates_known: 0, missing_information: [] }, performance_label: "Hypothetical one-year return using current holdings and weights", warnings: [] });
    if (path === "/plan/goals") return json(route, []);
    if (path === "/plan/policy") return json(route, {});
    if (path === "/plan/guidance") return json(route, null);
    if (path === "/terminal/portfolio-performance") return json(route, { data: { total_return: .1, annualized_volatility: .14, series: [{ date: "2026-01-01", value: 0 }, { date: now, value: .1 }] } });
    if (path === "/terminal/market-indicators") return json(route, []);
    if (path === "/terminal/layouts" && method === "GET") return json(route, state.terminalLayouts);
    if (path === "/providers/health") return json(route, { as_of: now, version: "provider-health-v1", summary: { total: 7, healthy: 5, awaiting_data: 1, degraded: 1, unconfigured: 0, storage: "fixture" }, warnings: ["Polymarket: degraded"], providers: [
      { key: "supabase", label: "Supabase authentication and storage", status: "healthy", configured: true, last_attempt_at: now, effective_through: now, datasets: ["authentication", "RLS-protected research storage"], fallbacks: ["None"], coverage: { storage: "fixture" }, rate_limit: { status: "not_reported" } },
      { key: "fred", label: "FRED / ALFRED macro data", status: "healthy", configured: true, last_attempt_at: now, effective_through: now, datasets: ["macro observations"], fallbacks: ["Stored snapshot"], coverage: {}, rate_limit: { status: "reported", remaining: 99 } },
      { key: "prices", label: "Corporate-action-adjusted prices", status: "healthy", configured: true, last_attempt_at: now, effective_through: now, datasets: ["daily adjusted prices"], fallbacks: ["Security → sector ETF → VTI"], coverage: { symbols: 5, bars: 5000 }, rate_limit: { status: "not_reported" } },
      { key: "kalshi", label: "Kalshi prediction markets", status: "healthy", configured: true, last_attempt_at: now, effective_through: now, datasets: ["probability snapshots"], fallbacks: ["Stored snapshot"], coverage: {}, rate_limit: { status: "not_reported" } },
      { key: "polymarket", label: "Polymarket prediction markets", status: "degraded", configured: true, last_attempt_at: now, effective_through: now, error: "Fixture stale fallback", datasets: ["probability snapshots"], fallbacks: ["Stored snapshot"], coverage: {}, rate_limit: { status: "not_reported" } },
      { key: "sec", label: "SEC Company Facts", status: "healthy", configured: true, last_attempt_at: now, effective_through: now, datasets: ["fundamentals"], fallbacks: ["Stored fundamentals"], coverage: {}, rate_limit: { status: "not_reported" } },
      { key: "gemini", label: "Gemini planner and narrator", status: "awaiting_data", configured: true, datasets: ["planning", "narration"], fallbacks: ["Deterministic compiler"], coverage: {}, rate_limit: { status: "not_reported" } },
    ] });
    if (path === "/terminal/layouts" && method === "POST") { const saved:TerminalLayoutFixture = { id: `layout-${state.terminalLayouts.length + 1}`, name: body.name||"Untitled", widgets: body.widgets||[], version: "terminal-layout-v1" }; state.terminalLayouts.unshift(saved); return json(route, saved, 201); }
    if (path.startsWith("/terminal/layouts/") && method === "PUT") { const id = path.split("/").at(-1)||"layout"; const saved:TerminalLayoutFixture = { id, name: body.name||"Untitled", widgets: body.widgets||[], version: "terminal-layout-v1" }; state.terminalLayouts = [saved, ...state.terminalLayouts.filter(item => item.id !== id)]; return json(route, saved); }
    if (path === "/preferences" && method === "PUT") { state.terminalWidgets = body.terminal_widgets || state.terminalWidgets; return json(route, body); }
    if (path === "/dashboard/views" && method === "GET") return json(route, state.views);
    if (path === "/dashboard/catalog") return json(route, [{ widget_type: "macro_trends", label: "Macro trends", group: "Macro", description: "Stored macro factors", available: true, record_count: 5, datasets: ["FRED"] }]);
    if (path === "/dashboard/drafts" && method === "POST") { state.job = makeJob(`job-${state.requests.length}`, options.partial); state.job.prompt = body.prompt||"Research request"; return json(route, state.job, 202); }
    if (path.endsWith("/events")) return route.fulfill({ status: 200, contentType: "text/event-stream", body: `event: dashboard\ndata: ${JSON.stringify(state.job)}\n\n` });
    if (/\/dashboard\/drafts\/[^/]+\/revise$/.test(path)) { state.job = makeJob(`job-${state.requests.length}`, options.partial); state.job.prompt = body.prompt||"Revised request"; state.job.specification.title = "Revised portfolio board"; return json(route, state.job, 202); }
    if (/\/dashboard\/drafts\/[^/]+\/widgets$/.test(path)) { state.job = structuredClone(state.job); state.job.specification.widgets.push({ id: "macro", task_id: "macro", widget_type: "macro_trends", title: "Macro trends", visualization: "cards", grid: { x: 0, y: 2, w: 8, h: 2 } }); state.job.widget_results.push(widgetResult("macro")); return json(route, state.job, 202); }
    if (/\/dashboard\/drafts\/[^/]+\/layout\/widgets\//.test(path) && method === "PATCH") { mutateJob(state.job, path.split("/").at(-1)!, body); return json(route, state.job); }
    if (/\/dashboard\/drafts\/[^/]+\/save$/.test(path)) { const view = viewFromJob(`view-${state.views.length + 1}`, body.name||"Saved board", state.job); state.views.unshift(view); return json(route, view, 201); }
    if (/\/dashboard\/views\/[^/]+\/duplicate$/.test(path)) { const source = state.views.find(item => item.id === path.split("/")[3]) || state.views[0]; const copy = structuredClone(source); copy.id = `view-${state.views.length + 1}`; copy.name = `${source.name} copy`; state.views.unshift(copy); return json(route, copy, 201); }
    if (/\/dashboard\/views\/[^/]+$/.test(path) && method === "GET") { const view = state.views.find(item => item.id === path.split("/").at(-1)); return view ? json(route, view) : json(route, { detail: "Not found" }, 404); }
    if (path === "/research/refresh" && method === "POST") return json(route, { research, searched: research.length, markets_found: 0, warnings: [] });
    if (path === "/research" || path.startsWith("/research?")) return json(route, research);
    if (/^\/evidence\/securities\/[^/]+\/changes$/.test(path)) return json(route, { baseline: { as_of: now, source: "fixture", fallback_reason: null }, current_as_of: now, changes: [], coverage: [] });
    if (/^\/forecasting\/securities\/[^/]+\/markets$/.test(path)) return json(route, { markets: [] });
    if (/^\/research\/[^/]+\/earnings$/.test(path)) return json(route, { status: "UNAVAILABLE", actual_vs_expectations: {}, changes: [], guidance_changes: [], estimate_revisions: [], warnings: ["No fixture earnings period"] });
    if (path === "/research/search") return json(route, { query: url.searchParams.get("q") || "", filters: {}, universe: { definition: "Browser fixture universe", source: "fixture", total: research.length, holdings: state.holdings.length, watchlist: 2, explicitly_requested: 0, sector_or_broad_etfs: 1, tickers: research.map(row => row.ticker) }, results: research.map((row, index) => ({ ...row, relative_rank: index + 1, evidence_bucket: index ? "Constructive evidence" : "Leading evidence", bucket_explanation: "Deterministic fixture bucket", strengths: [{ label: "Fundamentals", evidence: row.fundamental_score }], weaknesses: [{ label: "Valuation", evidence: row.valuation_score }], valuation_range: { label: "Reasonable", basis: "Fixture valuation" }, fundamental_trend: { label: "Stable", revenue_growth: row.revenue_growth, net_margin: row.net_margin }, price_behavior: { label: "Positive", one_year_change: row.price_change_1y }, catalysts: [], thesis_risks: row.risk_flags, portfolio_fit: "Review concentration", what_would_change_the_view: "Material earnings deterioration", freshness: { status: "current", price_as_of: now, fundamentals_as_of: now, coverage: "high", confidence_reasons: ["fixture"] }, disclaimer: "Research only" })), method: { name: "fixture", version: "v1", ranking_use: "ordering" }, disclaimer: "Not a recommendation" });
    if (path === "/builders/etf/optimize" && method === "POST") return json(route, {
      id: "etf-builder-1", builder_type: "etf", model_version: "etf-allocation-builder-v1.0.0", objective: body.objective,
      universe: { requested: body.candidate_tickers, eligible: ["VTI", "BND"], excluded: [], count: 2 },
      allocations: [
        { ticker: "VTI", name: "Vanguard Total Stock Market ETF", target_range: [.55,.60], reference_weight: .575, expense_ratio: .0003, what_it_contributes: "U.S. total-market exposure." },
        { ticker: "BND", name: "Vanguard Total Bond Market ETF", target_range: [.40,.45], reference_weight: .425, expense_ratio: .0003, what_it_contributes: "Diversified bond exposure." },
      ], portfolio_metrics: { annual_return: .075, volatility: .11, sharpe_ratio: .42, maximum_drawdown: -.22 }, expected_expense_dollars_year_one: 3,
      benchmarks: [{ name: "Equal weight", annual_return: .07, volatility: .105, sharpe_ratio: .38 }], overlap: [], constraints: { status: "satisfied", diagnostics: [] }, assumptions: [], warnings: [],
    });
    if (path === "/builders/stocks/optimize" && method === "POST") return json(route, {
      id: "stock-builder-1", builder_type: "stock", model_version: "stock-basket-builder-v1.0.0", objective: body.objective,
      universe: { requested: body.candidate_tickers, eligible: ["AAPL", "MSFT"], excluded: [], count: 2 },
      allocations: [
        { ticker: "AAPL", company: "Apple Inc.", target_range: [.45,.50], reference_weight: .475, marginal_contribution_to_risk: .52, included_because: "Eligible under the disclosed objective." },
        { ticker: "MSFT", company: "Microsoft", target_range: [.50,.55], reference_weight: .525, marginal_contribution_to_risk: .48, included_because: "Eligible under the disclosed objective." },
      ], portfolio_metrics: { annual_return: .12, volatility: .20, sharpe_ratio: .40, maximum_drawdown: -.30 }, benchmarks: [{ name: "SPY", annual_return: .09, volatility: .15, sharpe_ratio: .33 }], constraints: { status: "satisfied", diagnostics: [] }, assumptions: [], warnings: [],
    });
    if (path === "/simulations/runs" && method === "POST") return json(route, {
      id: "simulation-1", model_version: "decision-lab-block-bootstrap-v1.0.0", shared_path_fingerprint: "browser-shared-paths", coverage: { start: "2006-01-31", end: "2026-07-31", monthly_observations: 247, symbols_simulated: ["AAPL","SPY"] },
      outcomes: ["current","contributions_only","gradual","immediate","risk_controlled","balanced"].map((key,index)=>({ strategy_key:key, label:key.replaceAll("_"," "), wealth_percentiles:{p10:700000,p50:1200000+index*10000,p90:1900000}, real_wealth_percentiles:{p10:500000,p50:900000+index*7500,p90:1400000}, probability_of_loss:.08, drawdown_percentiles:{p10:-.32,p50:-.20,p90:-.12}, recovery_months:{median:14,unrecovered_share:.1}, goal_results:[], turnover:index*.05, estimated_taxes:index*100, estimated_fees:3000, concentration:{largest_weight:.55,effective_holdings:2}, regret:index*5000, robustness:"Moderate" })), assumptions:["5,000 reproducible block-bootstrap paths."], warnings:[],
    });
    if (path === "/portfolios/import" && method === "POST") { state.holdings = [{ ticker: "AAPL", weight: .5, market_value: 50000, cost_basis: 40000, account_type: "taxable" }, { ticker: "SPY", weight: .5, market_value: 50000, cost_basis: 45000, account_type: "taxable" }]; return json(route, { portfolio: { id: "portfolio-imported", name: body.name, holdings: state.holdings }, validated_rows: 2, warnings: [] }); }
    if (path === "/portfolio/transactions/import" && method === "POST") return json(route, {
      valid: true, rows: [{ account_id: body.account_id, trade_date: "2025-01-02", transaction_type: "buy", ticker: "AAPL", quantity: 5, price: 100, amount: null, fee: 0 }],
      errors: [], column_map: { date: "Date", type: "Type", ticker: "Symbol", quantity: "Quantity", price: "Price" }, unknown_columns: ["Memo"],
      reconstruction: { positions: { AAPL: 5 }, cash: -500, warnings: [] },
      saved: body.save ? { account_id: "account-1", inserted: 1, duplicates: 0, storage: "fixture" } : null,
    });
    if (path === "/analyses" && method === "POST") return json(route, analysisFixture());
    if (path === "/profile" && method === "PUT") return json(route, body);
    return json(route, {});
  });
  return state;
}

function mutateJob(job: ReturnType<typeof makeJob>, widgetId: string, body: MockRequestBody) {
  const index = job.specification.widgets.findIndex(item => item.id === widgetId);
  if (body.operation === "remove") { job.specification.widgets.splice(index, 1); job.widget_results = job.widget_results.filter(item => item.widget_id !== widgetId); }
  if (body.operation === "resize") job.specification.widgets[index].grid.w = body.width??8;
  if (body.operation === "move") { const target = index + ((body.direction??1) < 0 ? -1 : 1); [job.specification.widgets[index], job.specification.widgets[target]] = [job.specification.widgets[target], job.specification.widgets[index]]; }
}

function viewFromJob(id: string, name: string, job: ReturnType<typeof makeJob>) {
  return { id, name, original_prompt: job.prompt, plan: structuredClone(job.plan), specification: structuredClone(job.specification), layout: structuredClone(job.specification.widgets), spec_version: "dashboard-spec-v2", layout_version: "dashboard-layout-v2", refresh_policy: "manual", created_at: now, updated_at: now, revisions: [], latest_run: { id: `run-${id}`, widget_results: structuredClone(job.widget_results), narrative: job.narrative, warnings: job.warnings, status: job.state, created_at: now } };
}

function analysisFixture() {
  const alternative = { name: "Balanced", expected_return: .07, volatility: .13, drawdown_range: [-.25, -.12], turnover: .1, effective_holdings: 3, tradeoff: "Balanced fixture", constraint_status: "satisfied", conflicts: [], allocations: [{ ticker: "AAPL", current_weight: .5, target_weight: .45, target_min: .4, target_max: .5, delta: -.05, reason: "Diversification" }], scenario_outcomes: [{ label: "Recession", probability: .24, estimated_return: -.1 }], projection: { nominal_p10: 700000, nominal_p50: 1200000, nominal_p90: 1800000, real_p50: 850000, goal_probability: .65, assumptions: [] }, tax: { available: false, estimated_realized_gain: null, estimated_tax: null, note: "Inputs needed" }, model_assumptions: ["Fixture assumptions"] };
  return { id: "analysis-1", created_at: now, macro: { regime: "neutral", score: 50, as_of: now }, scenarios, research, alternatives: [{ ...alternative, name: "Risk-Controlled" }, alternative, { ...alternative, name: "Goal-Tilted" }], portfolio_value: 100000, warnings: [], scenario_warnings: [], data_lineage: { prices: "fixture", research: "fixture", macro: "fixture" } };
}

"use client";

import { ChangeEvent, useEffect, useMemo, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000/api";

type Tab = "overview" | "portfolio" | "scenarios" | "research" | "optimize";
type Holding = { ticker: string; shares?: number | null; weight?: number | null; market_value?: number | null; cost_basis?: number | null; account_type: string; acquisition_date?: string | null };
type Scenario = { key: string; label: string; probability: number; confidence: number; change_1d?: number | null; change_1w?: number | null; change_1m?: number | null; indicators: string[]; sources: string[]; as_of: string; is_prior: boolean };
type Research = { ticker: string; company: string; sector: string; industry: string; final_score: number; growth_rating: number; valuation_score: number; fundamental_score: number; industry_score: number; technical_score: number; news_score: number; confidence: number; data_quality: string; risk_flags: string[]; source?: string; price?: number | null; price_change_1y?: number | null; price_as_of?: string | null; fundamentals_as_of?: string | null; revenue_growth?: number | null; net_margin?: number | null; news_count?: number; latest_news?: { title: string; source_url?: string | null; published_at?: string | null } | null; data_source?: string };
type Profile = { age: number; retirement_age: number; horizon_years: number; account_type: string; annual_contribution: number; annual_withdrawal: number; target_value: number; tax_rate: number; risk_tolerance: number; preset: string; restrictions: string[]; watchlist: string[]; objectives: Record<string, number>; llm_provider: string; llm_endpoint?: string | null; llm_model?: string | null };
type Alternative = { name: string; expected_return: number; volatility: number; drawdown_range: number[]; turnover: number; effective_holdings: number; tradeoff: string; constraint_status: string; conflicts: string[]; allocations: Array<{ ticker: string; current_weight: number; target_weight: number; target_min: number; target_max: number; delta: number; reason: string }>; scenario_outcomes: Array<{ label: string; probability: number; estimated_return: number; sample_count?: number; regime_months?: number; shrinkage?: number; method?: string }>; projection: { nominal_p10: number; nominal_p50: number; nominal_p90: number; real_p50: number; goal_probability: number; assumptions: string }; tax: { available: boolean; estimated_realized_gain: number | null; estimated_tax: number | null; note: string }; model_assumptions?: string[] };
type Macro = { regime: string; score: number; as_of: string | null; source?: string; metrics?: Record<string, number | null> };
type Contract = { provider: string; id: string; title: string; scenario: string; indicator: string; probability: number; confidence: number; volume?: number; open_interest?: number; source?: string };
type PriceCoverage = { provider: string; bars: number; symbols: number; earliest: string | null; latest: string | null };
type DataStatus = { storage: string; counts: Record<string, number>; freshness: Record<string, string | null>; providers: Array<{ provider: string; status: string; fetched_at: string; metadata: Record<string, unknown> }>; price_coverage?: PriceCoverage[] };
type RegimeSummary = { latest: { as_of_date: string; dominant_regime: string; confidence: number; data_quality: number } | null; sample_counts: Record<string, number>; total_samples: number };
type ValidationMetrics = { name: string; annualized_return?: number | null; annualized_volatility?: number | null; max_drawdown?: number | null; sharpe?: number | null; average_turnover?: number; quarters_beating_equal_weight?: number; quarters_beating_static?: number };
type ValidationFold = { train_end: string; test_start: string; test_end: string; model_return: number; equal_weight_return: number; static_return: number; turnover: number; eligible_assets: number; regime_training_months: number };
type WalkForward = { status: string; period_count: number; model?: ValidationMetrics; benchmarks: ValidationMetrics[]; assumptions: string[]; periods?: ValidationFold[] };
type ModelDiagnostics = { covariance: { method: string; sample_count: number; shrinkage_intensity: number; raw_condition_number?: number | null; shrunk_condition_number?: number | null; effective_rank: number; imputed_fraction: number }; regime_returns: { method: string; labelled_forward_months: number; prior_strength_months: number }; expected_return_blend: { empirical_regime_weight: number; company_research_weight: number }; price_coverage?: { minimum_full_cycle_years: number; insufficient_full_cycle: string[]; missing_sector_proxies: string[]; sector_proxy_fallbacks: Record<string, string> } };
type ClassifierMetrics = { observations: number; brier_score: number; log_loss: number; accuracy: number; calibration_error: number; probability_instability: number };
type MlEvaluation = { status: string; model_version: string; fold_count: number; transparent_baseline?: ClassifierMetrics; ml_classifier?: ClassifierMetrics; comparison?: { brier_improvement: number; relative_brier_improvement: number; log_loss_improvement: number; fold_win_rate: number }; recommendation: string; production_model_changed?: boolean; assumptions: string[] };
type Monitoring = { status: string; created_at: string; alerts: string[]; metrics: { prediction_market_calibration?: { status: string; sample_count: number; brier_score?: number | null; calibration_error?: number | null }; covariance?: { shrunk_condition_number?: number | null }; regime_sample_counts?: Record<string, number>; walk_forward?: { period_count?: number }; turnover?: number | null; allocation_stability?: number | null }; coverage?: { tiingo_symbols?: number } };
type Analysis = { id: string; created_at: string; macro: Macro; scenarios: Scenario[]; research: Research[]; alternatives: Alternative[]; portfolio_value: number; warnings: string[]; scenario_warnings: string[]; data_lineage?: Record<string, string>; model_diagnostics?: ModelDiagnostics; walk_forward?: WalkForward; benchmarks?: ValidationMetrics[]; ml_regime_evaluation?: MlEvaluation };

const defaultProfile: Profile = {
  age: 35, retirement_age: 65, horizon_years: 20, account_type: "taxable", annual_contribution: 12000,
  annual_withdrawal: 0, target_value: 1000000, tax_rate: 0.20, risk_tolerance: 6, preset: "balanced",
  restrictions: [], watchlist: ["SPY", "QQQ", "VTI", "XLE", "XLV"], llm_provider: "disabled", llm_endpoint: null, llm_model: null,
  objectives: { expected_return: .55, volatility: .45, drawdown: .55, diversification: .65, turnover: .35, tax_drag: .35, income: .15 },
};

const seededScenarios: Scenario[] = [
  { key: "soft_landing", label: "Soft landing", probability: .38, confidence: .20, change_1d: null, change_1w: null, change_1m: null, indicators: [], sources: [], as_of: new Date().toISOString(), is_prior: true },
  { key: "sticky_inflation", label: "Sticky inflation", probability: .20, confidence: .20, change_1d: null, change_1w: null, change_1m: null, indicators: [], sources: [], as_of: new Date().toISOString(), is_prior: true },
  { key: "recession_cuts", label: "Recession / cutting cycle", probability: .18, confidence: .20, change_1d: null, change_1w: null, change_1m: null, indicators: [], sources: [], as_of: new Date().toISOString(), is_prior: true },
  { key: "growth_reacceleration", label: "Growth reacceleration", probability: .16, confidence: .20, change_1d: null, change_1w: null, change_1m: null, indicators: [], sources: [], as_of: new Date().toISOString(), is_prior: true },
  { key: "oil_shock", label: "Oil shock", probability: .08, confidence: .20, change_1d: null, change_1w: null, change_1m: null, indicators: [], sources: [], as_of: new Date().toISOString(), is_prior: true },
];

const nav: Array<[Tab, string, string]> = [
  ["overview", "⌂", "Overview"], ["portfolio", "◫", "Portfolio"], ["scenarios", "⌁", "Scenarios"],
  ["research", "◎", "Research"], ["optimize", "◇", "Optimize"],
];

function pct(value?: number | null, digits = 0) { return value == null ? "—" : `${(value * 100).toFixed(digits)}%`; }
function money(value?: number | null) { return value == null ? "—" : new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(value); }
function compact(value?: number | null) { return value == null ? "—" : new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(value); }
function dateLabel(value?: string | null) { return value ? new Date(value).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" }) : "Awaiting data"; }
function scoreTone(value: number) { return value >= 75 ? "good" : value >= 55 ? "neutral" : "risk"; }

export default function Dashboard() {
  const [tab, setTab] = useState<Tab>("overview");
  const [dark, setDark] = useState(() =>
    typeof window === "undefined"
      ? true
      : window.localStorage.getItem("investment-dashboard-theme") !== "light"
  );
  const [connected, setConnected] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState("");
  const [portfolioId, setPortfolioId] = useState<string | number | null>(null);
  const [portfolioName, setPortfolioName] = useState("Primary portfolio");
  const [holdings, setHoldings] = useState<Holding[]>([
    { ticker: "AAPL", weight: .28, account_type: "taxable" }, { ticker: "MU", weight: .22, account_type: "taxable" },
    { ticker: "CSCO", weight: .18, account_type: "taxable" }, { ticker: "SPY", weight: .22, account_type: "taxable" },
    { ticker: "CASH", weight: .10, account_type: "taxable" },
  ]);
  const [profile, setProfile] = useState<Profile>(defaultProfile);
  const [macro, setMacro] = useState<Macro>({ regime: "neutral", score: 50, as_of: null });
  const [scenarios, setScenarios] = useState<Scenario[]>(seededScenarios);
  const [contracts, setContracts] = useState<Contract[]>([]);
  const [scenarioFetchedAt, setScenarioFetchedAt] = useState<string | null>(null);
  const [scenarioWarnings, setScenarioWarnings] = useState<string[]>(["Connect the local data service to refresh live prediction markets."]);
  const [research, setResearch] = useState<Research[]>([]);
  const [dataStatus, setDataStatus] = useState<DataStatus>({ storage: "pending", counts: {}, freshness: {}, providers: [] });
  const [regimeHistory, setRegimeHistory] = useState<RegimeSummary>({ latest: null, sample_counts: {}, total_samples: 0 });
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [monitoring, setMonitoring] = useState<Monitoring | null>(null);
  const [selectedAlternative, setSelectedAlternative] = useState(1);
  const [narrative, setNarrative] = useState("");
  const [sortKey, setSortKey] = useState<keyof Research>("final_score");

  useEffect(() => {
    let active = true;
    async function loadOverview() {
      try {
        const response = await fetch(`${API}/overview`);
        if (!response.ok) throw new Error("Local API unavailable");
        const data = await response.json();
        if (!active) return;
        setConnected(true);
        if (data.portfolio) {
          setPortfolioId(data.portfolio.id); setPortfolioName(data.portfolio.name); setHoldings(data.portfolio.holdings);
        }
        setProfile(data.profile); setMacro(data.macro); setScenarios(data.scenarios.scenarios); setContracts(data.scenarios.contracts || []); setScenarioFetchedAt(data.scenarios.fetched_at || null); setScenarioWarnings(data.scenarios.warnings); setResearch(data.research); setDataStatus(data.data_status); setRegimeHistory(data.regime_history || { latest: null, sample_counts: {}, total_samples: 0 });
        setMonitoring(data.model_monitoring || null);
        if (data.latest_analysis?.alternatives?.length) setAnalysis(data.latest_analysis);
      } catch {
        if (active) setConnected(false);
      } finally { if (active) setLoading(false); }
    }
    void loadOverview();
    return () => { active = false; };
  }, []);

  useEffect(() => { document.documentElement.dataset.theme = dark ? "dark" : "light"; }, [dark]);

  function toggleTheme() {
    const next = !dark; setDark(next); window.localStorage.setItem("investment-dashboard-theme", next ? "dark" : "light");
  }

  async function savePortfolio() {
    setBusy("Saving portfolio"); setNotice("");
    try {
      const url = portfolioId ? `${API}/portfolios/${portfolioId}` : `${API}/portfolios`;
      const response = await fetch(url, { method: portfolioId ? "PUT" : "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: portfolioName, holdings: holdings.map(cleanHolding) }) });
      if (!response.ok) throw new Error(await response.text());
      const saved = await response.json(); setPortfolioId(saved.id); setConnected(true); setNotice("Portfolio saved.");
    } catch (error) { setNotice(error instanceof Error ? error.message : "Unable to save portfolio."); }
    finally { setBusy(""); }
  }

  async function importCsv(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]; if (!file) return;
    setBusy("Validating CSV"); setNotice("");
    try {
      const response = await fetch(`${API}/portfolios/import`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: file.name.replace(/\.csv$/i, ""), csv_text: await file.text() }) });
      const data = await response.json(); if (!response.ok) throw new Error(data.detail || "CSV validation failed");
      setPortfolioId(data.portfolio.id); setPortfolioName(data.portfolio.name); setHoldings(data.portfolio.holdings); setNotice(`${data.validated_rows} holdings validated and saved.`); setConnected(true);
    } catch (error) { setNotice(error instanceof Error ? error.message : "Unable to import CSV."); }
    finally { setBusy(""); event.target.value = ""; }
  }

  async function refreshMarkets() {
    setBusy("Refreshing prediction markets"); setNotice("");
    try {
      const response = await fetch(`${API}/providers/refresh?force=true`, { method: "POST" }); const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Refresh failed");
      setScenarios(data.scenarios); setContracts(data.contracts || []); setScenarioFetchedAt(data.fetched_at || null); setScenarioWarnings(data.warnings); setNotice(data.cached ? "Using the latest validated snapshot." : "Prediction-market scenarios refreshed."); setConnected(true);
    } catch (error) { setNotice(error instanceof Error ? error.message : "Refresh unavailable."); }
    finally { setBusy(""); }
  }

  async function runOptimization() {
    setBusy("Running scenario analysis"); setNotice(""); setNarrative("");
    try {
      await fetch(`${API}/profile`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(profile) });
      const response = await fetch(`${API}/analyses`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ portfolio: { name: portfolioName, holdings: holdings.map(cleanHolding) }, profile }) });
      const data = await response.json(); if (!response.ok) throw new Error(data.detail || "Analysis failed");
      setAnalysis(data); setScenarios(data.scenarios); setResearch(data.research); setMacro(data.macro); setSelectedAlternative(1); setConnected(true); setNotice("Three alternatives are ready. Review the tradeoffs—not just the headline return.");
    } catch (error) { setNotice(error instanceof Error ? error.message : "Analysis unavailable."); }
    finally { setBusy(""); }
  }

  async function generateNarrative() {
    if (!analysis) return; setBusy("Preparing explanation");
    try {
      const response = await fetch(`${API}/analyses/${analysis.id}/explanation`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ provider: profile.llm_provider, endpoint: profile.llm_endpoint, model: profile.llm_model }) });
      const data = await response.json(); setNarrative(data.text); if (data.warning) setNotice(data.warning);
    } catch { setNarrative("The optional explanation layer is unavailable. All calculated results remain visible below."); }
    finally { setBusy(""); }
  }

  const currentWeightTotal = holdings.reduce((sum, item) => sum + (Number(item.weight) || 0), 0);
  const topScenario = [...scenarios].sort((a, b) => b.probability - a.probability)[0];
  const sortedResearch = useMemo(() => [...research].sort((a, b) => Number(b[sortKey] || 0) - Number(a[sortKey] || 0)), [research, sortKey]);

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand"><div className="brand-mark">ID</div><div><strong>Investment</strong><span>Dashboard</span></div></div>
        <nav aria-label="Primary navigation">
          {nav.map(([key, icon, label]) => <button key={key} className={tab === key ? "active" : ""} onClick={() => setTab(key)}><span aria-hidden>{icon}</span>{label}</button>)}
        </nav>
        <div className="sidebar-foot">
          <div className={`connection ${connected ? "online" : ""}`}><i />{connected ? "Research engine connected" : "Research engine offline"}</div>
          <button className="theme-button" onClick={toggleTheme}>{dark ? "☀" : "◐"} {dark ? "Light mode" : "Dark mode"}</button>
          <p>Research sandbox<br />Trading is disabled</p>
        </div>
      </aside>

      <main>
        <header className="topbar">
          <div><span className="eyebrow">Quarterly decision system</span><h1>{nav.find(item => item[0] === tab)?.[2]}</h1></div>
          <div className="top-actions"><div className="freshness"><span>Data lineage</span><strong>{macro.as_of || "Awaiting refresh"}</strong></div><button className="primary" onClick={() => setTab("optimize")}>Run analysis <span>→</span></button></div>
        </header>
        {busy && <div className="progress" role="status"><span />{busy}…</div>}
        {notice && <div className="notice"><span>i</span>{notice}<button onClick={() => setNotice("")} aria-label="Dismiss">×</button></div>}

        {tab === "overview" && <Overview loading={loading} portfolioName={portfolioName} holdings={holdings} macro={macro} scenarios={scenarios} research={research} topScenario={topScenario} analysis={analysis} dataStatus={dataStatus} onNavigate={setTab} />}
        {tab === "portfolio" && <Portfolio holdings={holdings} setHoldings={setHoldings} name={portfolioName} setName={setPortfolioName} total={currentWeightTotal} onSave={savePortfolio} onImport={importCsv} />}
        {tab === "scenarios" && <Scenarios scenarios={scenarios} contracts={contracts} fetchedAt={scenarioFetchedAt} regimeHistory={regimeHistory} warnings={scenarioWarnings} onRefresh={refreshMarkets} />}
        {tab === "research" && <ResearchTable rows={sortedResearch} sortKey={sortKey} setSortKey={setSortKey} onNavigate={setTab} />}
        {tab === "optimize" && <Optimize profile={profile} setProfile={setProfile} analysis={analysis} monitoring={monitoring} selected={selectedAlternative} setSelected={setSelectedAlternative} onRun={runOptimization} narrative={narrative} onNarrative={generateNarrative} />}
      </main>
    </div>
  );
}

function Overview({ loading, portfolioName, holdings, macro, scenarios, research, topScenario, analysis, dataStatus, onNavigate }: { loading: boolean; portfolioName: string; holdings: Holding[]; macro: Macro; scenarios: Scenario[]; research: Research[]; topScenario?: Scenario; analysis: Analysis | null; dataStatus: DataStatus; onNavigate: (tab: Tab) => void }) {
  const score = research.length ? research.reduce((sum, row) => sum + row.final_score, 0) / research.length : 0;
  return <section className="workspace overview-workspace">
    <div className="hero-panel">
      <div><span className="kicker">Decision lens, not autopilot</span><h2>See what your portfolio is <em>really</em> betting on.</h2><p>Prediction markets set the scenario weights. Fundamentals, valuation, and historical behavior test whether those bets deserve space in your portfolio.</p><div className="hero-actions"><button className="primary" onClick={() => onNavigate("optimize")}>Compare alternatives</button><button className="secondary" onClick={() => onNavigate("portfolio")}>Edit holdings</button></div></div>
      <div className="regime-orbit"><div className="orbit-label"><span>Macro regime</span><strong>{macro.regime.replaceAll("_", " ")}</strong><small>{macro.score.toFixed(0)} / 100</small></div><div className="orbit-ring ring-one" /><div className="orbit-ring ring-two" /><i className="orbit-dot dot-one" /><i className="orbit-dot dot-two" /></div>
    </div>
    <div className="metric-grid">
      <Metric label="Portfolio" value={portfolioName} meta={`${holdings.length} positions`} />
      <Metric label="Research score" value={loading ? "—" : score ? score.toFixed(1) : "Pending"} meta="Coverage-weighted composite" tone={scoreTone(score)} />
      <Metric label="Leading scenario" value={topScenario?.label || "Pending"} meta={topScenario ? `${pct(topScenario.probability)} · ${pct(topScenario.confidence)} confidence` : "Refresh required"} />
      <Metric label="Latest run" value={analysis ? "Complete" : "Not run"} meta={analysis ? new Date(analysis.created_at).toLocaleString() : "Compare three alternatives"} tone={analysis ? "good" : "neutral"} />
    </div>
    <div className="two-column">
      <div className="panel"><PanelHead eyebrow="Probability map" title="Macro scenarios" action="Explore" onClick={() => onNavigate("scenarios")} />
        <div className="scenario-list">{scenarios.map(s => <div className="scenario-row" key={s.key}><div><strong>{s.label}</strong><span>{s.is_prior ? "Prior-driven" : `${s.indicators.length} market signals`}</span></div><div className="mini-bar"><i style={{ width: `${s.probability * 100}%` }} /></div><b>{pct(s.probability)}</b></div>)}</div>
      </div>
      <div className="panel"><PanelHead eyebrow="Portfolio pulse" title="What needs attention" action="Review" onClick={() => onNavigate("research")} />
        <div className="attention-list">
          {(research.length ? [...research].sort((a,b) => a.confidence - b.confidence).slice(0,4) : [{ ticker: "DATA", company: "Start the local engine", confidence: 0, data_quality: "pending", risk_flags: ["research data not loaded"] } as Research]).map(row => <div key={row.ticker}><span className={`ticker-badge ${scoreTone(row.confidence)}`}>{row.ticker.slice(0,4)}</span><p><strong>{row.company}</strong><small>{row.risk_flags[0]?.replaceAll("_", " ") || `${row.data_quality} data quality`}</small></p><b>{row.confidence.toFixed(0)}%</b></div>)}
        </div>
      </div>
    </div>
    <div className="data-lineage-panel">
      <div><span className="kicker">Supabase evidence base</span><h3>Stored research inputs</h3><p>These records—not browser samples—feed the scenario model, security ratings, and optimization covariance.</p></div>
      <div className="data-source-grid">
        <DataSource label="Prices" count={dataStatus.counts.price_bars} date={dataStatus.freshness.prices} />
        <DataSource label="Macro" count={dataStatus.counts.macro_observations} date={dataStatus.freshness.macro} />
        <DataSource label="Fundamentals" count={dataStatus.counts.fundamental_periods} date={dataStatus.freshness.fundamentals} />
        <DataSource label="News" count={dataStatus.counts.news_documents} date={dataStatus.freshness.news} />
        <DataSource label="Markets" count={dataStatus.counts.market_snapshots} date={dataStatus.freshness.markets} />
        <DataSource label="Regimes" count={dataStatus.counts.macro_regimes} date={dataStatus.freshness.regimes} />
      </div>
      {!!dataStatus.price_coverage?.length && <div className="price-coverage" aria-label="Price history coverage">
        {dataStatus.price_coverage.map(source => <div key={source.provider}><span>{source.provider}</span><strong>{source.symbols} symbols · {compact(source.bars)} bars</strong><small>{dateLabel(source.earliest)} → {dateLabel(source.latest)}</small></div>)}
      </div>}
    </div>
  </section>;
}

function Metric({ label, value, meta, tone = "neutral" }: { label: string; value: string; meta: string; tone?: string }) { return <div className="metric-card"><span>{label}</span><strong className={tone}>{value}</strong><small>{meta}</small></div>; }
function DataSource({ label, count, date }: { label: string; count?: number; date?: string | null }) { return <div><span>{label}</span><strong>{compact(count)}</strong><small>through {dateLabel(date)}</small></div>; }
function PanelHead({ eyebrow, title, action, onClick }: { eyebrow: string; title: string; action: string; onClick: () => void }) { return <div className="panel-head"><div><span>{eyebrow}</span><h3>{title}</h3></div><button onClick={onClick}>{action} →</button></div>; }

function Portfolio({ holdings, setHoldings, name, setName, total, onSave, onImport }: { holdings: Holding[]; setHoldings: (rows: Holding[]) => void; name: string; setName: (v:string) => void; total: number; onSave: () => void; onImport: (e: ChangeEvent<HTMLInputElement>) => void }) {
  const update = (index: number, key: keyof Holding, value: string) => setHoldings(holdings.map((row, i) => i === index ? { ...row, [key]: key === "ticker" || key === "account_type" || key === "acquisition_date" ? value : value === "" ? null : Number(value) } : row));
  return <section className="workspace"><div className="section-intro"><div><span className="kicker">Your source of truth</span><h2>Build the portfolio you want to examine.</h2><p>Use weights for a quick analysis, or add market value and aggregate cost basis for tax estimates.</p></div><div className={`weight-status ${Math.abs(total - 1) < .001 ? "valid" : ""}`}><span>Entered weights</span><strong>{pct(total, 1)}</strong><small>{Math.abs(total - 1) < .001 ? "Ready" : "Weights will be normalized"}</small></div></div>
    <div className="panel portfolio-panel"><div className="portfolio-toolbar"><label>Portfolio name<input value={name} onChange={e => setName(e.target.value)} /></label><div><label className="upload-button">Import CSV<input type="file" accept=".csv,text/csv" onChange={onImport} /></label><button className="secondary" onClick={() => setHoldings([...holdings, { ticker: "", weight: 0, account_type: "taxable" }])}>+ Add holding</button><button className="primary" onClick={onSave}>Save portfolio</button></div></div>
      <div className="table-scroll"><table className="holdings-table"><thead><tr><th>Ticker</th><th>Weight</th><th>Market value</th><th>Cost basis</th><th>Account</th><th>Acquired</th><th /></tr></thead><tbody>{holdings.map((row, i) => <tr key={`${row.ticker}-${i}`}><td><input className="ticker-input" value={row.ticker} onChange={e => update(i, "ticker", e.target.value.toUpperCase())} placeholder="Ticker" /></td><td><input type="number" step="0.01" value={row.weight ?? ""} onChange={e => update(i, "weight", e.target.value)} placeholder="0.10" /></td><td><input type="number" value={row.market_value ?? ""} onChange={e => update(i, "market_value", e.target.value)} placeholder="$" /></td><td><input type="number" value={row.cost_basis ?? ""} onChange={e => update(i, "cost_basis", e.target.value)} placeholder="Optional" /></td><td><select value={row.account_type} onChange={e => update(i, "account_type", e.target.value)}><option value="taxable">Taxable</option><option value="traditional_ira">Traditional IRA</option><option value="roth_ira">Roth IRA</option><option value="401k">401(k)</option><option value="other">Other</option></select></td><td><input type="date" value={row.acquisition_date || ""} onChange={e => update(i, "acquisition_date", e.target.value)} /></td><td><button className="remove" onClick={() => setHoldings(holdings.filter((_, idx) => idx !== i))} aria-label={`Remove ${row.ticker}`}>×</button></td></tr>)}</tbody></table></div>
      <div className="csv-hint"><strong>CSV columns</strong><code>ticker, weight, market_value, cost_basis, account_type, acquisition_date</code><span>Provide shares, weight, or market value for each row.</span></div>
    </div>
  </section>;
}

function Scenarios({ scenarios, contracts, fetchedAt, regimeHistory, warnings, onRefresh }: { scenarios: Scenario[]; contracts: Contract[]; fetchedAt: string | null; regimeHistory: RegimeSummary; warnings: string[]; onRefresh: () => void }) {
  return <section className="workspace"><div className="section-intro"><div><span className="kicker">Prediction markets first</span><h2>Probabilities, with their confidence attached.</h2><p>Contracts are deduplicated, weighted by market quality, and shrunk toward disclosed priors when evidence is thin.</p></div><button className="primary refresh-button" onClick={onRefresh}>↻ Refresh markets</button></div>
    {warnings.length > 0 && <div className="warning-strip">{warnings.map(w => <span key={w}>△ {w}</span>)}</div>}
    <div className="regime-sample-strip"><div><span>Point-in-time regime library</span><strong>{regimeHistory.total_samples} monthly samples</strong><small>{regimeHistory.latest ? `Latest: ${regimeHistory.latest.dominant_regime.replaceAll("_", " ")} · ${dateLabel(regimeHistory.latest.as_of_date)}` : "Historical labeling pending"}</small></div>{Object.entries(regimeHistory.sample_counts).sort((a,b) => b[1]-a[1]).map(([key,count]) => <div key={key}><span>{key.replaceAll("_", " ")}</span><strong>{count}</strong><small>{regimeHistory.total_samples ? pct(count / regimeHistory.total_samples) : "—"} of samples</small></div>)}</div>
    <div className="scenario-grid">{scenarios.map((scenario, index) => <article className="scenario-card" key={scenario.key}><div className="scenario-number">0{index + 1}</div><span className="confidence-dot"><i style={{ opacity: scenario.confidence }} /> {pct(scenario.confidence)} signal confidence</span><h3>{scenario.label}</h3><div className="big-probability">{pct(scenario.probability)}</div><div className="prob-track"><i style={{ width: `${scenario.probability * 100}%` }} /></div><div className="change-grid"><span>1 day<b className={(scenario.change_1d || 0) >= 0 ? "up" : "down"}>{scenario.change_1d == null ? "—" : `${scenario.change_1d > 0 ? "+" : ""}${pct(scenario.change_1d, 1)}`}</b></span><span>1 week<b>{scenario.change_1w == null ? "—" : pct(scenario.change_1w, 1)}</b></span><span>1 month<b>{scenario.change_1m == null ? "—" : pct(scenario.change_1m, 1)}</b></span></div><div className="indicator-tags">{scenario.indicators.length ? scenario.indicators.map(i => <span key={i}>{i}</span>) : <span>disclosed prior</span>}</div><footer>{scenario.is_prior ? "Market coverage unavailable or weak" : `${scenario.sources.length} linked source${scenario.sources.length === 1 ? "" : "s"}`}</footer></article>)}</div>
    <div className="panel contract-panel"><div className="panel-head"><div><span>Stored market evidence</span><h3>Contracts behind the probabilities</h3></div><small>Snapshot {dateLabel(fetchedAt)}</small></div>
      {contracts.length === 0 ? <EmptyState title="No matching contracts in this snapshot" body="The scenario cards above disclose when a prior is being used instead of prediction-market evidence." /> : <div className="table-scroll"><table className="contract-table"><thead><tr><th>Venue</th><th>Question</th><th>Indicator</th><th>Probability</th><th>Confidence</th><th>Activity</th></tr></thead><tbody>{[...contracts].sort((a,b) => b.confidence - a.confidence).slice(0,20).map(contract => <tr key={`${contract.provider}-${contract.id}`}><td><span className={`venue ${contract.provider.toLowerCase()}`}>{contract.provider}</span></td><td><a href={contract.source} target="_blank" rel="noreferrer">{contract.title}</a><small>{contract.scenario.replaceAll("_", " ")}</small></td><td>{contract.indicator}</td><td><strong>{pct(contract.probability,1)}</strong></td><td>{pct(contract.confidence,0)}</td><td>{compact((contract.volume || 0) + (contract.open_interest || 0))}</td></tr>)}</tbody></table></div>}
    </div>
    <div className="method-note"><span>Method</span><p>Scenario weights are normalized across five mutually interpretable states. They influence expected outcomes, but company quality, valuation, diversification, and hard risk controls remain independent checks.</p></div>
  </section>;
}

function ResearchTable({ rows, sortKey, setSortKey, onNavigate }: { rows: Research[]; sortKey: keyof Research; setSortKey: (key:keyof Research) => void; onNavigate: (tab: Tab) => void }) {
  const headers: Array<[keyof Research, string]> = [["final_score", "Composite"], ["growth_rating", "Growth"], ["valuation_score", "Value"], ["fundamental_score", "Quality"], ["industry_score", "Industry"], ["technical_score", "Technical"], ["confidence", "Confidence"]];
  return <section className="workspace"><div className="section-intro"><div><span className="kicker">Evidence before narrative</span><h2>Every rating keeps its components visible.</h2><p>Scores are comparative research signals—not price targets or instructions to buy or sell.</p></div><button className="secondary" onClick={() => onNavigate("portfolio")}>Manage universe</button></div>
    <div className="panel research-panel"><div className="research-toolbar"><span>{rows.length} securities</span><div>Sort by {headers.map(([key, label]) => <button key={key} className={sortKey === key ? "active" : ""} onClick={() => setSortKey(key)}>{label}</button>)}</div></div>
      {rows.length === 0 ? <EmptyState title="Research data is waiting" body="Start the local engine or run an analysis to load holdings, watchlist names, and ETF coverage." /> : <div className="table-scroll"><table className="research-table"><thead><tr><th>Security</th><th>Price / 1Y</th>{headers.map(([,label]) => <th key={label}>{label}</th>)}<th>Data</th><th>Evidence</th><th>Primary risk</th></tr></thead><tbody>{rows.map(row => <tr key={row.ticker}><td><div className="security-cell"><span>{row.ticker.slice(0,2)}</span><p><strong>{row.ticker}</strong><small>{row.company}<br />{row.sector}</small></p></div></td><td><div className="market-cell"><strong>{row.price == null ? "—" : money(row.price)}</strong><small className={(row.price_change_1y || 0) >= 0 ? "up" : "down"}>{row.price_change_1y == null ? "No history" : `${row.price_change_1y >= 0 ? "+" : ""}${pct(row.price_change_1y,1)}`}</small></div></td>{headers.map(([key]) => <td key={key}><Score value={Number(row[key])} /></td>)}<td><span className={`quality ${row.data_quality}`}>{row.data_quality}</span></td><td><div className="evidence-cell"><span>Price {dateLabel(row.price_as_of)}</span><span>Fund. {dateLabel(row.fundamentals_as_of)}</span><span>{row.news_count || 0} recent articles</span>{row.latest_news?.source_url && <a href={row.latest_news.source_url} target="_blank" rel="noreferrer">Latest source ↗</a>}</div></td><td className="risk-copy">{row.risk_flags[0]?.replaceAll("_", " ") || "No hard flag"}</td></tr>)}</tbody></table></div>}
    </div>
  </section>;
}

function Score({ value }: { value: number }) { return <div className="score"><b className={scoreTone(value)}>{value.toFixed(0)}</b><i><span style={{ width: `${value}%` }} /></i></div>; }

function Optimize({ profile, setProfile, analysis, monitoring, selected, setSelected, onRun, narrative, onNarrative }: { profile: Profile; setProfile: (p:Profile) => void; analysis: Analysis | null; monitoring: Monitoring | null; selected: number; setSelected: (i:number) => void; onRun: () => void; narrative: string; onNarrative: () => void }) {
  const update = (key: keyof Profile, value: string | number) => setProfile({ ...profile, [key]: value });
  const updateObjective = (key: string, value: number) => setProfile({ ...profile, objectives: { ...profile.objectives, [key]: value } });
  const alternative = analysis?.alternatives[selected];
  const presets = [["growth", "Growth", "Higher return tolerance"], ["balanced", "Balanced", "Multi-objective tradeoff"], ["preservation", "Preservation", "Downside first"], ["income", "Income", "Cash-flow preference"]];
  return <section className="workspace optimize-workspace"><div className="section-intro"><div><span className="kicker">Build, compare, decide</span><h2>Choose your tradeoffs before the model runs.</h2><p>The engine returns three alternatives under the same hard constraints. You remain the decision-maker.</p></div><button className="primary run-button" onClick={onRun}>Run three-way analysis →</button></div>
    <div className="optimizer-layout"><div className="control-column">
      <div className="panel control-panel"><div className="panel-title"><span>01</span><div><h3>Investor frame</h3><p>Time, cash flow, and account context</p></div></div><div className="form-grid"><Field label="Current age" value={profile.age} onChange={v => update("age", Number(v))} /><Field label="Retirement age" value={profile.retirement_age} onChange={v => update("retirement_age", Number(v))} /><Field label="Horizon (years)" value={profile.horizon_years} onChange={v => update("horizon_years", Number(v))} /><label>Account type<select value={profile.account_type} onChange={e => update("account_type", e.target.value)}><option value="taxable">Taxable</option><option value="traditional_ira">Traditional IRA</option><option value="roth_ira">Roth IRA</option><option value="401k">401(k)</option></select></label><Field label="Annual contribution" value={profile.annual_contribution} onChange={v => update("annual_contribution", Number(v))} /><Field label="Annual withdrawal" value={profile.annual_withdrawal} onChange={v => update("annual_withdrawal", Number(v))} /><Field label="Target portfolio" value={profile.target_value} onChange={v => update("target_value", Number(v))} /><Field label="Tax rate (decimal)" value={profile.tax_rate} onChange={v => update("tax_rate", Number(v))} /><Field label="Risk tolerance (1–10)" value={profile.risk_tolerance} onChange={v => update("risk_tolerance", Number(v))} /></div><label className="full-field">Watchlist / ETF universe<input value={profile.watchlist.join(", ")} onChange={e => setProfile({ ...profile, watchlist: e.target.value.split(",").map(v => v.trim().toUpperCase()).filter(Boolean) })} placeholder="SPY, QQQ, VTI, XLV" /></label><label className="full-field">Excluded tickers or sectors<input value={profile.restrictions.join(", ")} onChange={e => setProfile({ ...profile, restrictions: e.target.value.split(",").map(v => v.trim().toUpperCase()).filter(Boolean) })} placeholder="Ticker or exact sector name" /></label></div>
      <div className="panel control-panel"><div className="panel-title"><span>02</span><div><h3>Starting posture</h3><p>A preset, then your adjustments</p></div></div><div className="preset-grid">{presets.map(([key,label,desc]) => <button key={key} className={profile.preset === key ? "active" : ""} onClick={() => update("preset", key)}><strong>{label}</strong><span>{desc}</span></button>)}</div></div>
      <div className="panel control-panel"><div className="panel-title"><span>03</span><div><h3>Objective weights</h3><p>Make the tradeoff explicit</p></div></div><div className="slider-list">{Object.entries(profile.objectives).map(([key,value]) => <label key={key}><span>{key.replaceAll("_", " ")}<b>{Math.round(value * 100)}</b></span><input type="range" min="0" max="1" step="0.05" value={value} onChange={e => updateObjective(key, Number(e.target.value))} /></label>)}</div></div>
      <div className="panel control-panel"><div className="panel-title"><span>04</span><div><h3>Explanation layer</h3><p>Optional; calculations never depend on it</p></div></div><label>Provider<select value={profile.llm_provider} onChange={e => update("llm_provider", e.target.value)}><option value="disabled">Template only</option><option value="ollama">Local Ollama</option><option value="openai_compatible">OpenAI-compatible API</option></select></label>{profile.llm_provider !== "disabled" && <><label>Endpoint<input value={profile.llm_endpoint || ""} onChange={e => update("llm_endpoint", e.target.value)} placeholder={profile.llm_provider === "ollama" ? "http://127.0.0.1:11434" : "https://…/v1"} /></label><label>Model<input value={profile.llm_model || ""} onChange={e => update("llm_model", e.target.value)} placeholder="Model name" /></label></>}</div>
    </div>
    <div className="result-column">{!analysis || !alternative ? <div className="empty-result"><div className="result-rings"><i /><i /><span>3</span></div><h3>Three alternatives, one clear comparison.</h3><p>Run the analysis to compare Risk-Controlled, Balanced, and Goal-Tilted allocations against your current portfolio.</p><ul><li>Scenario-conditioned outcomes</li><li>Target ranges and allocation deltas</li><li>Tax, turnover, and retirement ranges</li><li>Constraint diagnostics and source lineage</li></ul></div> : <>
      <div className="alternative-tabs">{analysis.alternatives.map((alt,i) => <button key={alt.name} className={selected === i ? "active" : ""} onClick={() => setSelected(i)}><span>0{i+1}</span><strong>{alt.name}</strong><small>{pct(alt.expected_return,1)} modeled return</small></button>)}</div>
      <div className="result-summary"><div><span>Modeled return</span><strong>{pct(alternative.expected_return,1)}</strong></div><div><span>Volatility</span><strong>{pct(alternative.volatility,1)}</strong></div><div><span>Est. turnover</span><strong>{pct(alternative.turnover,1)}</strong></div><div><span>Effective holdings</span><strong>{alternative.effective_holdings}</strong></div></div>
      <div className="tradeoff"><span>Tradeoff</span><p>{alternative.tradeoff}</p><b className={alternative.constraint_status === "satisfied" ? "good" : "risk"}>{alternative.constraint_status}</b></div>
      <div className="model-lineage"><span>Model inputs</span><p>Prices: <b>{analysis.data_lineage?.prices || "validated history"}</b></p><p>Research: <b>{analysis.data_lineage?.research || "validated scores"}</b></p><p>Macro: <b>{analysis.data_lineage?.macro || "FRED"}</b></p></div>
      {monitoring && <div className="panel monitoring-panel"><div className="panel-head"><div><span>Production monitoring</span><h3>Recorded model health</h3></div><small>{dateLabel(monitoring.created_at)}</small></div><div className="diagnostic-grid"><div><span>Monitor status</span><strong className={monitoring.status === "healthy" ? "good" : "risk"}>{monitoring.status}</strong><small>{monitoring.alerts.length} active alert{monitoring.alerts.length === 1 ? "" : "s"}</small></div><div><span>Market calibration</span><strong>{monitoring.metrics.prediction_market_calibration?.brier_score?.toFixed(3) || "Building"}</strong><small>{monitoring.metrics.prediction_market_calibration?.sample_count || 0} realized monthly forecasts</small></div><div><span>Long history</span><strong>{monitoring.coverage?.tiingo_symbols || 0} symbols</strong><small>{monitoring.metrics.walk_forward?.period_count || 0} walk-forward tests</small></div></div>{monitoring.alerts.length > 0 && <ul className="assumption-list">{monitoring.alerts.map(alert => <li key={alert}>{alert}</li>)}</ul>}<div className="monitor-policy"><span>Promotion policy</span><p>Challengers remain evaluation-only until a promotion decision and supporting validation are stored.</p></div></div>}
      {analysis.model_diagnostics && <div className="panel diagnostic-panel"><div className="panel-head"><div><span>Estimator diagnostics</span><h3>What the model trusted</h3></div><small>{analysis.model_diagnostics.covariance.sample_count} daily observations</small></div><div className="diagnostic-grid"><div><span>Covariance shrinkage</span><strong>{pct(analysis.model_diagnostics.covariance.shrinkage_intensity,1)}</strong><small>Condition {analysis.model_diagnostics.covariance.raw_condition_number ?? "—"} → {analysis.model_diagnostics.covariance.shrunk_condition_number ?? "—"}</small></div><div><span>Empirical regime weight</span><strong>{pct(analysis.model_diagnostics.expected_return_blend.empirical_regime_weight,1)}</strong><small>{analysis.model_diagnostics.regime_returns.labelled_forward_months} labeled forward months</small></div><div><span>Effective covariance rank</span><strong>{analysis.model_diagnostics.covariance.effective_rank.toFixed(1)}</strong><small>{pct(analysis.model_diagnostics.covariance.imputed_fraction,1)} missing observations imputed</small></div>{analysis.model_diagnostics.price_coverage && <div><span>Full-cycle coverage</span><strong>{analysis.model_diagnostics.price_coverage.insufficient_full_cycle.length ? `${analysis.model_diagnostics.price_coverage.insufficient_full_cycle.length} short` : "Complete"}</strong><small>{analysis.model_diagnostics.price_coverage.missing_sector_proxies.length ? `${analysis.model_diagnostics.price_coverage.missing_sector_proxies.length} missing proxies` : "Sector proxies available"}</small></div>}</div></div>}
      {analysis.walk_forward && <div className="panel validation-panel"><div className="panel-head"><div><span>Walk-forward validation</span><h3>Out-of-sample comparison</h3></div><small>{analysis.walk_forward.status === "complete" ? `${analysis.walk_forward.period_count} quarterly tests` : "Insufficient overlapping history"}</small></div>{analysis.walk_forward.model && <div className="benchmark-grid">{[analysis.walk_forward.model, ...analysis.walk_forward.benchmarks].map(item => <div key={item.name} className={item.name.startsWith("Walk-forward") ? "primary-benchmark" : ""}><span>{item.name}</span><strong>{pct(item.annualized_return,1)}</strong><small>Vol {pct(item.annualized_volatility,1)} · Drawdown {pct(item.max_drawdown,1)}</small></div>)}</div>}<ul className="assumption-list">{analysis.walk_forward.assumptions.map(item => <li key={item}>{item}</li>)}</ul>{analysis.walk_forward.periods?.length ? <details className="fold-details"><summary>Inspect saved validation folds</summary><div className="fold-table"><div><b>Test window</b><b>Model</b><b>Equal</b><b>Static</b></div>{analysis.walk_forward.periods.map(fold => <div key={fold.test_start}><span>{dateLabel(fold.test_start)}–{dateLabel(fold.test_end)}</span><strong className={fold.model_return >= 0 ? "good" : "risk"}>{pct(fold.model_return,1)}</strong><span>{pct(fold.equal_weight_return,1)}</span><span>{pct(fold.static_return,1)}</span></div>)}</div></details> : null}</div>}
      {analysis.ml_regime_evaluation && <div className="panel ml-panel"><div className="panel-head"><div><span>Experimental challenger</span><h3>Does ML improve the transparent rules?</h3></div><small>{analysis.ml_regime_evaluation.fold_count} embargoed folds</small></div>{analysis.ml_regime_evaluation.status === "complete" && analysis.ml_regime_evaluation.transparent_baseline && analysis.ml_regime_evaluation.ml_classifier ? <><div className="ml-comparison"><div><span>Transparent rules</span><strong>{analysis.ml_regime_evaluation.transparent_baseline.brier_score.toFixed(3)}</strong><small>Brier · log loss {analysis.ml_regime_evaluation.transparent_baseline.log_loss.toFixed(3)}</small></div><div><span>ML classifier</span><strong>{analysis.ml_regime_evaluation.ml_classifier.brier_score.toFixed(3)}</strong><small>Brier · log loss {analysis.ml_regime_evaluation.ml_classifier.log_loss.toFixed(3)}</small></div><div><span>Fold win rate</span><strong>{pct(analysis.ml_regime_evaluation.comparison?.fold_win_rate,0)}</strong><small>{pct(analysis.ml_regime_evaluation.comparison?.relative_brier_improvement,1)} relative Brier improvement</small></div></div><div className={`ml-decision ${analysis.ml_regime_evaluation.recommendation === "consider_probability_blend" ? "good" : "neutral"}`}><span>Evaluation decision</span><strong>{analysis.ml_regime_evaluation.recommendation.replaceAll("_", " ")}</strong><small>Production model changed: no</small></div></> : <p className="validation-note">More point-in-time history is required before the challenger can be evaluated.</p>}<ul className="assumption-list">{analysis.ml_regime_evaluation.assumptions.map(item => <li key={item}>{item}</li>)}</ul></div>}
      <div className="panel scenario-outcome-panel"><div className="panel-head"><div><span>Scenario test</span><h3>Empirical return by macro state</h3></div><small>Prediction-market weighted</small></div><div className="scenario-outcome-grid">{alternative.scenario_outcomes.map(outcome => <div key={outcome.label}><span>{outcome.label}</span><strong className={outcome.estimated_return >= 0 ? "good" : "risk"}>{outcome.estimated_return >= 0 ? "+" : ""}{pct(outcome.estimated_return,1)}</strong><small>{pct(outcome.probability)} probability · n={outcome.sample_count ?? 0} · {pct(outcome.shrinkage,0)} shrunk</small></div>)}</div></div>
      {alternative.model_assumptions?.length ? <div className="panel assumptions-panel"><div className="panel-head"><div><span>Assumptions beside this result</span><h3>How to read these estimates</h3></div></div><ul className="assumption-list">{alternative.model_assumptions.map(item => <li key={item}>{item}</li>)}</ul></div> : null}
      <div className="panel allocation-panel"><div className="panel-head"><div><span>Target ranges</span><h3>Allocation changes</h3></div><small>Current → target</small></div><div className="allocation-list">{alternative.allocations.map(item => <div key={item.ticker}><span className="ticker-badge neutral">{item.ticker.slice(0,4)}</span><p><strong>{item.ticker}</strong><small>{item.reason}</small></p><div className="allocation-values"><span>{pct(item.current_weight)}</span><b>→</b><strong>{pct(item.target_weight)}</strong><small>{pct(item.target_min)}–{pct(item.target_max)}</small></div><em className={item.delta >= 0 ? "up" : "down"}>{item.delta >= 0 ? "+" : ""}{pct(item.delta,1)}</em></div>)}</div></div>
      <div className="projection-grid"><div className="panel"><span className="kicker">Retirement range</span><h3>{money(alternative.projection.nominal_p50)}</h3><p>Median nominal value in {profile.horizon_years} years</p><div className="range-line"><i /><span style={{ left: "10%" }}>P10 {money(alternative.projection.nominal_p10)}</span><span style={{ right: "8%" }}>P90 {money(alternative.projection.nominal_p90)}</span></div><footer>{pct(alternative.projection.goal_probability)} modeled goal frequency</footer></div><div className="panel"><span className="kicker">Tax & turnover</span><h3>{alternative.tax.available ? money(alternative.tax.estimated_tax) : "Inputs needed"}</h3><p>{alternative.tax.note}</p><footer>{pct(alternative.turnover)} one-way turnover</footer></div></div>
      <div className="narrative-panel"><div><span>Optional explanation</span><h3>Validated facts in plain language</h3></div><button className="secondary" onClick={onNarrative}>Generate explanation</button>{narrative && <p>{narrative}</p>}</div>
    </>}</div></div>
  </section>;
}

function Field({ label, value, onChange }: { label: string; value: number; onChange: (value:string) => void }) { return <label>{label}<input type="number" value={value} onChange={e => onChange(e.target.value)} /></label>; }
function EmptyState({ title, body }: { title: string; body: string }) { return <div className="empty-state"><span>◎</span><h3>{title}</h3><p>{body}</p></div>; }
function cleanHolding(row: Holding) { const output: Record<string, unknown> = { ticker: row.ticker.toUpperCase(), account_type: row.account_type }; (["shares","weight","market_value","cost_basis","acquisition_date"] as const).forEach(key => { if (row[key] !== null && row[key] !== undefined && row[key] !== "") output[key] = row[key]; }); return output; }

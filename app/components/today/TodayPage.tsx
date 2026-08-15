"use client";

import type { Tab, ExploreView, PortfolioView, AdvancedView } from "../../lib/routes";
import type { GuidanceDisclosure } from "../shared/GuidanceLevel";

type EvidenceLink = { label: string; url?: string | null; as_of?: string | null; provider: string };
type DataTimeliness = "live" | "delayed" | "end-of-day" | "cached" | "stale";
type Movement = { ticker: string; label: string; group: "index" | "sector" | "portfolio"; value: number; change_1d?: number | null; change_1w?: number | null; change_1m?: number | null; as_of?: string | null; unit: string; provider: string; source?: string | null; data_status: DataTimeliness };
type MarketIndicator = { key: string; series_id: string; label: string; unit: string; value: number; change?: number | null; as_of?: string | null; provider: string; source?: string | null; data_status: DataTimeliness };
type Relevance = { key: string; factor: string; relevance: "high" | "moderate" | "low"; direction: "positive" | "negative" | "mixed"; explanation: string; destination: string; evidence: EvidenceLink[] };
type Attention = { key: string; severity: string; title: string; why: string; changed: string; affected: string[]; confidence: string; destination: string; evidence: EvidenceLink[] };
type Event = { id: string; event_type: string; title: string; starts_at: string; tickers?: string[]; provider: string; source_url?: string | null; metadata?: Record<string, unknown>; event_status?:string; timing_status?:string; verified_at?:string|null; timezone?:string };
type EventCoverage = { requested_tickers:string[]; earnings_covered_tickers:string[]; earnings_missing_tickers:string[]; earnings_coverage_ratio:number|null; macro_release_count:number; deduplicated_count:number; note:string };
type ResearchIdea = { key: string; title: string; why: string; why_appeared: string; what_would_invalidate: string; universe: string; eligibility_filters: string[]; exclusions: string[]; minimum_data_requirements: string[]; selection_method: string; freshness?: string | null; ticker?: string; confidence: string; destination: string; evidence: EvidenceLink[] };

export type TodayBriefing = {
  version: string;
  as_of: string;
  market_data_as_of?: string | null;
  market_business_days_old?: number | null;
  evidence_state: "current" | "partial" | "stale_fallback";
  guidance: GuidanceDisclosure;
  headline: string;
  summary: string;
  portfolio_context: { available: boolean; name?: string | null; holding_count: number; missing_symbols: string[]; weak_coverage_symbols: string[] };
  market_movement: Movement[];
  market_indicators: MarketIndicator[];
  leadership: { leading_sectors: Movement[]; lagging_sectors: Movement[]; leading_style?: Movement | null; lagging_style?: Movement | null; method: string };
  portfolio_relevance: Relevance[];
  attention: Attention[];
  upcoming_events: Event[];
  event_coverage: EventCoverage;
  research_ideas: ResearchIdea[];
  warnings: string[];
  calculation: { method: string; version: string; assumptions: string[] };
};

type MacroFactor = { key: string; label: string; why_it_matters: string; as_of: string | null; evidence: Array<{ series_id: string; value: number; change: number | null; date: string; source: string }> };
type DataStatus = { counts: Record<string, number>; freshness: Record<string, string | null>; price_coverage?: Array<{ provider: string; bars: number; symbols: number; earliest: string | null; latest: string | null }> };

function pct(value?: number | null, digits = 1) { return value == null ? "—" : `${value >= 0 ? "+" : ""}${(value * 100).toFixed(digits)}%`; }
function number(value?: number | null, digits = 2) { return value == null ? "—" : value.toFixed(digits); }
function compact(value?: number | null) { return value == null ? "—" : new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(value); }
function dateLabel(value?: string | null) {
  if (!value) return "Awaiting data";
  const dateOnly = /^\d{4}-\d{2}-\d{2}$/.test(value);
  const parsed = new Date(dateOnly ? `${value}T12:00:00` : value);
  return parsed.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}
function eventDate(value: string) { return new Date(value).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }); }

function EvidenceLinks({ evidence }: { evidence: EvidenceLink[] }) {
  return <div className="claim-sources">{evidence.filter(item => item.url).map(item => <a key={`${item.label}-${item.url}`} href={item.url || "#"} target={item.url?.startsWith("http") ? "_blank" : undefined} rel="noreferrer"><span>{item.label}</span><small>{item.provider} · {dateLabel(item.as_of)}</small></a>)}</div>;
}

function MovementTable({ rows, title }: { rows: Movement[]; title: string }) {
  return <div className="today-movement-table"><div className="today-table-title"><strong>{title}</strong><span>Adjusted close · latest 1 / 5 / 21 sessions</span></div>{rows.length ? <><div className="today-table-row header"><span>Market</span><span>1 day</span><span>1 week</span><span>1 month</span><span>As of</span></div>{rows.map(row => <a className="today-table-row" href={row.source || "#"} key={row.ticker}><strong>{row.ticker}<small>{row.label}</small></strong><span className={(row.change_1d || 0) >= 0 ? "good" : "risk"}>{pct(row.change_1d)}</span><span className={(row.change_1w || 0) >= 0 ? "good" : "risk"}>{pct(row.change_1w)}</span><span className={(row.change_1m || 0) >= 0 ? "good" : "risk"}>{pct(row.change_1m)}</span><span>{dateLabel(row.as_of)}<small className={`data-status ${row.data_status}`}>{row.data_status}</small></span></a>)}</> : <p className="today-empty-copy">Stored adjusted-price history is waiting for coverage.</p>}</div>;
}

export function TodayPage({ loading, refreshing, briefing, macroFactors, dataStatus, onRefresh, onNavigate, onExplore: navigateExplore, onPortfolio, onAdvanced }: {
  loading: boolean;
  refreshing: boolean;
  briefing: TodayBriefing | null;
  macroFactors: MacroFactor[];
  dataStatus: DataStatus;
  onRefresh: () => void;
  onNavigate: (tab: Tab) => void;
  onExplore: (view: ExploreView) => void;
  onPortfolio: (view: PortfolioView) => void;
  onAdvanced: (view: AdvancedView) => void;
}) {
  const indexes = briefing?.market_movement.filter(row => row.group === "index") || [];
  const sectors = briefing?.market_movement.filter(row => row.group === "sector") || [];
  const onExplore = (view: ExploreView | "securities") => navigateExplore(view === "securities" ? "stocks" : view);
  const investigate = (destination: string) => destination === "portfolio" ? onPortfolio("analysis") : destination === "explore" ? onExplore("securities") : onAdvanced("lineage");
  const leadSector=briefing?.leadership?.leading_sectors?.[0];
  const topAttention=briefing?.attention?.[0];
  const conciseHeadline=loading
    ? "Building today’s market briefing…"
    : leadSector
      ? `${leadSector.label} leads this week${topAttention?`; ${topAttention.title.toLowerCase()}.`:". No urgent portfolio issue was found."}`
      : topAttention?.title || "No urgent portfolio-specific concern was found.";
  return <section className="workspace today-workspace">
    <div className="market-briefing-hero today-hero">
      <div><span className="kicker">What currently matters to your portfolio</span><h2>{conciseHeadline}</h2><p>This page answers three things: what moved, what matters to your holdings, and what deserves investigation next.</p><div className="briefing-state-row"><span className={`briefing-state ${briefing?.evidence_state || "partial"}`}>{briefing?.evidence_state?.replaceAll("_", " ") || "loading"}</span><small>Market data through {dateLabel(briefing?.market_data_as_of)} · briefing built {dateLabel(briefing?.as_of)}</small></div>{briefing?.warnings.slice(0,2).map(warning => <p className="briefing-warning" key={warning}>△ {warning}</p>)}<div className="hero-actions"><button className="primary" disabled={refreshing} onClick={onRefresh}>{refreshing?"Refreshing providers…":"Refresh today’s data"}</button><button className="secondary" onClick={() => onExplore("macro")}>Explore evidence</button><button className="secondary" onClick={() => onPortfolio("analysis")}>Portfolio analysis</button></div></div>
      <aside className="portfolio-relevance-summary"><span>What it shows</span>{(briefing?.portfolio_relevance||[]).slice(0,3).map(item => <div key={item.key}><strong>{item.factor}</strong><b className={`${item.relevance} ${item.direction}`}>{item.relevance} {item.direction}</b><small>{item.explanation}</small></div>)}{!(briefing?.portfolio_relevance||[]).length&&<p>Portfolio relevance is waiting for validated holdings and market evidence.</p>}</aside>
    </div>

    {!briefing?.portfolio_context.available && <div className="today-no-portfolio"><div><span>General market mode</span><strong>No saved portfolio is required</strong><p>Today can summarize market evidence now. Add holdings later to calculate concentration and portfolio-specific relevance.</p></div><button className="primary" onClick={() => onPortfolio("holdings")}>Add a portfolio →</button></div>}

    <div className="today-market-grid">
      <div className="panel today-market-panel"><div className="panel-head"><div><span>Market movement</span><h3>Indexes and styles</h3></div><button onClick={() => onExplore("securities")}>Research →</button></div><MovementTable title="Broad market ETFs" rows={indexes} /></div>
      <div className="panel today-market-panel"><div className="panel-head"><div><span>Sector tape</span><h3>Sector movement</h3></div><button onClick={() => onExplore("securities")}>Explore →</button></div><MovementTable title="Sector ETFs" rows={sectors} /></div>
    </div>

    <div className="panel today-indicator-panel"><div className="panel-head"><div><span>Cross-asset evidence</span><h3>Rates, oil, credit, dollar, and volatility</h3></div><button onClick={() => onExplore("macro")}>Macro history →</button></div><div className="today-indicator-grid">{briefing?.market_indicators.length ? briefing.market_indicators.map(row => <a href={row.source || "#"} target="_blank" rel="noreferrer" key={row.key}><span>{row.label}</span><strong>{number(row.value)} <small>{row.unit}</small></strong><b className={(row.change || 0) >= 0 ? "good" : "risk"}>{row.change == null ? "No prior observation" : `${row.change >= 0 ? "+" : ""}${number(row.change)} from prior`}</b><small>{row.provider} · {dateLabel(row.as_of)} · <b className={`data-status ${row.data_status}`}>{row.data_status}</b></small></a>) : <p className="today-empty-copy">Cross-asset series are waiting for FRED coverage.</p>}</div></div>

    <div className="two-column today-decision-grid">
      <div className="panel"><div className="panel-head"><div><span>Relative leadership</span><h3>Sector and style leadership</h3></div><button onClick={() => onExplore("securities")}>Investigate →</button></div><div className="leadership-grid"><div><span>Leading sectors</span>{briefing?.leadership.leading_sectors.map(row => <p key={row.ticker}><strong>{row.label}</strong><b className="good">{pct(row.change_1w)}</b></p>)}</div><div><span>Lagging sectors</span>{briefing?.leadership.lagging_sectors.map(row => <p key={row.ticker}><strong>{row.label}</strong><b className="risk">{pct(row.change_1w)}</b></p>)}</div><div><span>Style leaders</span><p><strong>{briefing?.leadership.leading_style?.label || "Awaiting data"}</strong><b>{pct(briefing?.leadership.leading_style?.change_1w)}</b></p><p><strong>{briefing?.leadership.lagging_style?.label || "Awaiting data"}</strong><b>{pct(briefing?.leadership.lagging_style?.change_1w)}</b></p></div></div><details><summary>How leadership was calculated</summary><p>{briefing?.leadership.method || "Stored sector and broad-market ETF history is required."}</p></details></div>
      <div className="panel"><div className="panel-head"><div><span>Portfolio pulse</span><h3>What needs attention</h3></div><button onClick={() => onNavigate("ask")}>Ask →</button></div><div className="priority-attention-list">{briefing?.attention.length ? briefing.attention.map(item => <article key={item.key}><span className={`attention-severity ${item.severity}`}>{item.severity}</span><div><strong>{item.title}</strong><p><b>What changed:</b> {item.changed}</p><p>{item.why}</p><small>{item.affected.join(", ")} · {item.confidence} confidence</small><EvidenceLinks evidence={item.evidence} /></div><button onClick={() => investigate(item.destination)}>Investigate →</button></article>) : <div className="today-clear-state"><strong>No urgent portfolio-specific issue was found</strong><p>That is a valid research result. Continue monitoring data freshness and revisit when holdings, policy limits, or evidence change.</p></div>}</div></div>
    </div>

    <div className="today-forward-grid">
      <div className="panel"><div className="panel-head"><div><span>Upcoming</span><h3>Earnings, macro releases, and catalysts</h3></div><button onClick={() => onExplore("prediction-markets")}>Market evidence →</button></div>{briefing?.event_coverage&&<div className="event-coverage"><strong>{briefing.event_coverage.earnings_coverage_ratio==null?"General calendar":`${Math.round(briefing.event_coverage.earnings_coverage_ratio*100)}% holdings earnings coverage`}</strong><span>{briefing.event_coverage.macro_release_count} macro releases · {briefing.event_coverage.deduplicated_count} duplicates removed</span>{briefing.event_coverage.earnings_missing_tickers.length>0&&<small>Missing validated earnings dates: {briefing.event_coverage.earnings_missing_tickers.join(", ")}. This is a coverage warning, not proof that no earnings event exists.</small>}</div>}{briefing?.upcoming_events.length ? <div className="today-event-list">{briefing.upcoming_events.map(event => <a key={event.id} href={event.source_url || "#"} target={event.source_url?.startsWith("http") ? "_blank" : undefined} rel="noreferrer"><time>{eventDate(event.starts_at)}</time><div><strong>{event.title}</strong><small>{event.event_type.replaceAll("_", " ")} · {event.provider}{event.tickers?.length ? ` · ${event.tickers.join(", ")}` : ""} · {event.timing_status||"confirmed"}{event.verified_at?` · verified ${dateLabel(event.verified_at)}`:""}</small></div></a>)}</div> : <div className="today-clear-state"><strong>No validated upcoming events are stored</strong><p>The app does not invent an earnings or macro calendar when the event provider has no coverage.</p></div>}</div>
      <div className="panel"><div className="panel-head"><div><span>Research queue</span><h3>Ideas requiring investigation</h3></div><button onClick={() => onNavigate("ask")}>Build a board →</button></div>{briefing?.research_ideas.length ? <div className="today-idea-list">{briefing.research_ideas.map(idea => <article key={idea.key}><div><span>{idea.confidence} evidence confidence · {idea.freshness?dateLabel(idea.freshness):"freshness unknown"}</span><strong>{idea.title}</strong><p>{idea.why}</p><details><summary>Why this appeared and eligibility rules</summary><p><b>Why:</b> {idea.why_appeared}</p><p><b>Universe:</b> {idea.universe}</p><p><b>Filters:</b> {idea.eligibility_filters.join("; ")}</p><p><b>Excluded:</b> {idea.exclusions.join("; ")}</p><p><b>Minimum data:</b> {idea.minimum_data_requirements.join("; ")}</p><p><b>Method:</b> {idea.selection_method}</p><p><b>Would invalidate:</b> {idea.what_would_invalidate}</p></details><EvidenceLinks evidence={idea.evidence} /></div><a href={idea.destination}>Open →</a></article>)}</div> : <div className="today-clear-state"><strong>No research idea cleared the evidence rules</strong><p>Refresh security coverage or expand the saved watchlist; no generic “opportunity” is manufactured.</p></div>}</div>
    </div>

    <details className="panel today-method"><summary>Evidence, data coverage, and methodology</summary><p>Deterministic rules prioritize concentration, freshness, market movement, and stored catalysts. These are research prompts—not trade instructions.</p><div>{macroFactors.slice(0,5).map(factor => <p key={factor.key}><strong>{factor.label}</strong><span>{factor.evidence[0] ? `${factor.evidence[0].series_id} ${number(factor.evidence[0].value)}` : "Awaiting data"}</span><small>{factor.why_it_matters} · {dateLabel(factor.as_of)}</small></p>)}</div>{briefing?.calculation.assumptions.map(item => <p key={item}>— {item}</p>)}<div className="today-coverage-row"><span>Prices {compact(dataStatus.counts.price_bars)}</span><span>Macro {compact(dataStatus.counts.macro_observations)}</span><span>Fundamentals {compact(dataStatus.counts.fundamental_periods)}</span><span>News {compact(dataStatus.counts.news_documents)}</span><span>Markets {compact(dataStatus.counts.market_snapshots)}</span></div></details>
  </section>;
}

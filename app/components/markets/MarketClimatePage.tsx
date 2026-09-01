"use client";

import { useEffect, useMemo, useState } from "react";
import type { ForecastMarket, Macro, MacroFactor, RegimeSummary, Scenario } from "../workspaces";

type MarketPayload = {
  markets: ForecastMarket[];
  disagreements: Array<{ event_key: string; range: number[] }>;
  as_of: string;
};

const CLIMATE_NAMES: Record<string, { name: string; summary: string; tone: string }> = {
  supportive_growth: { name: "Growth is holding up", summary: "Growth evidence is supportive without a dominant inflation or downturn warning.", tone: "supportive" },
  sticky_inflation: { name: "Inflation pressure is persistent", summary: "Inflation and rates are the main constraints on the market backdrop.", tone: "caution" },
  recession_risk: { name: "Downturn risk is elevated", summary: "Growth and labor evidence point to a greater risk of economic contraction.", tone: "risk" },
  neutral: { name: "Mixed, transitionary conditions", summary: "No single macro force dominates. Conflicting signals deserve more weight than a simple risk-on label.", tone: "mixed" },
  expansion: { name: "Broad economic expansion", summary: "Economic activity is expanding across the available indicators.", tone: "supportive" },
  slowdown: { name: "Growth is slowing", summary: "Activity remains positive, but momentum is weakening.", tone: "caution" },
  recession: { name: "Economic contraction", summary: "The available point-in-time evidence is consistent with recessionary conditions.", tone: "risk" },
};

function climateLabel(value?: string | null) {
  const key = String(value || "neutral").toLowerCase();
  return CLIMATE_NAMES[key] || {
    name: key.replaceAll("_", " ").replace(/\b\w/g, letter => letter.toUpperCase()),
    summary: "A point-in-time evidence state used to compare market behavior—not a promise about future returns.",
    tone: "mixed",
  };
}

function pct(value?: number | null, digits = 0) {
  return value == null ? "—" : `${(value * 100).toFixed(digits)}%`;
}

function dateLabel(value?: string | null) {
  if (!value) return "Awaiting data";
  return new Date(/^\d{4}-\d{2}-\d{2}$/.test(value) ? `${value}T12:00:00` : value).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

export function MarketClimatePage({ macro, factors, regimeHistory, request, onRefresh, onAsk }: {
  macro: Macro;
  factors: MacroFactor[];
  scenarios: Scenario[];
  regimeHistory: RegimeSummary;
  request: (path: string, init?: RequestInit) => Promise<Response>;
  onRefresh: () => void;
  onAsk: (question: string) => void;
}) {
  const [payload, setPayload] = useState<MarketPayload>({ markets: [], disagreements: [], as_of: "" });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const fallbackClimate = climateLabel(macro.regime);
  const climate = {
    name: macro.climate_label || fallbackClimate.name,
    summary: macro.climate_summary || fallbackClimate.summary,
    tone: macro.score >= 60 ? "supportive" : macro.score < 45 ? "risk" : "mixed",
  };

  async function load() {
    setLoading(true); setError("");
    try {
      const response = await request("/forecasting/markets?limit=40");
      if (!response.ok) throw new Error("Forward-looking market evidence is temporarily unavailable.");
      const data=await response.json();
      setPayload({
        markets:Array.isArray(data.markets)?data.markets:[],
        disagreements:Array.isArray(data.disagreements)?data.disagreements:[],
        as_of:typeof data.as_of==="string"?data.as_of:"",
      });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Forward-looking market evidence is temporarily unavailable.");
    } finally { setLoading(false); }
  }

  useEffect(() => {
    const task = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(task);
  // The authenticated request function is stable for the mounted session.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const markets = useMemo(() => [...payload.markets].sort((a, b) => b.relevance_score - a.relevance_score), [payload.markets]);
  const portfolioMarkets = markets.filter(item => item.affected_holdings.length || item.affected_theses.length).slice(0, 6);
  const macroMarkets = markets.filter(item => item.category === "MACRO" || item.category === "POLICY").slice(0, 8);
  const scale = macro.climate_scale || ["Economic stress", "Slowing growth", "Mixed conditions", "Steady growth", "Strong expansion"];
  const activeScale = Math.max(0, Math.min(4, macro.score >= 75 ? 4 : macro.score >= 60 ? 3 : macro.score >= 45 ? 2 : macro.score >= 30 ? 1 : 0));
  const primaryFactors=factors.slice(0,3);
  const supportingFactors=factors.slice(3,5);
  const portfolioImplication=macro.score<45?"Prioritize concentration and drawdown review; the current climate is not a sell signal.":macro.score>=60?"Growth conditions are supportive, but position limits and thesis evidence still govern portfolio decisions.":"Keep portfolio changes evidence-led while the macro signals remain mixed.";

  return <section className="workspace market-climate-workspace">
    <header className={`market-climate-hero ${climate.tone}`}>
      <div><span className="kicker">Market Climate</span><h2>{climate.name}</h2><p>{climate.summary}</p><div><span>Climate score {macro.score.toFixed(0)}/100</span><span>Evidence through {dateLabel(macro.as_of)}</span><span>{regimeHistory.total_samples} historical months classified</span></div></div>
      <aside><span>Portfolio implication</span><strong>{portfolioImplication}</strong><small>Climate evidence changes review priority; it does not override your policy or security-level thesis.</small><button className="primary" onClick={() => { onRefresh(); void load(); }}>Refresh climate</button></aside>
    </header>

    <section className="market-climate-section"><div className="section-heading"><div><span className="kicker">What is driving it</span><h2>Top three forces shaping the current state</h2><p>Direction first; source series stay inside each disclosure.</p></div></div><div className="market-driver-grid">{primaryFactors.map(factor => { const change = factor.evidence[0]?.change; const direction = change == null ? "Awaiting trend" : Math.abs(change) < .01 ? "Broadly stable" : change > 0 ? "Rising" : "Falling"; return <article className="panel" key={factor.key}><span>{factor.label}</span><h3>{direction}</h3><p>{factor.why_it_matters}</p><details><summary>Evidence</summary>{factor.evidence.map(row => <div key={row.series_id}><b>{row.series_id}</b><span>{row.value.toFixed(2)} · {dateLabel(row.date)}</span></div>)}</details></article>; })}</div></section>

    <section className="market-climate-section"><div className="section-heading"><div><span className="kicker">Supporting indicators</span><h2>Additional evidence to watch</h2></div><button className="secondary" onClick={() => onAsk("Explain the current market climate score and how it affects my portfolio.")}>Ask about this climate →</button></div><div className="market-driver-grid">{supportingFactors.map(factor=><article className="panel" key={factor.key}><span>{factor.label}</span><h3>{factor.evidence[0]?.value?.toFixed(2)??"Unavailable"}</h3><p>{factor.why_it_matters}</p></article>)}</div><details className="market-climate-disclosure"><summary>Five-state scale and methodology</summary><p>{macro.score_methodology || "Current macro evidence is combined into one deterministic five-state climate."}</p><div className="climate-state-scale">{scale.map((label,index)=><article className={`panel ${index===activeScale?"active":""}`} key={label}><span>{index===activeScale?"Current climate":"Possible state"}</span><h3>{label}</h3>{index===activeScale&&<strong>{macro.score.toFixed(0)}/100</strong>}</article>)}</div></details></section>

    <details className="market-climate-section market-climate-disclosure"><summary>Prediction markets and upcoming events</summary><div className="section-heading"><div><span className="kicker">On demand</span><h2>What markets are pricing now</h2><p>Market-implied probabilities are evidence—not truth and not an EagleEyes forecast.</p></div><small>{loading ? "Loading market expectations…" : `Snapshot ${dateLabel(payload.as_of)}`}</small></div>{error && <div className="warning-strip"><span>△ {error}</span><button onClick={() => void load()}>Retry</button></div>}{payload.disagreements.length > 0 && <div className="warning-strip"><span>△ Providers materially disagree on {payload.disagreements.length} tracked event{payload.disagreements.length === 1 ? "" : "s"}; their probabilities are not averaged.</span></div>}
      {portfolioMarkets.length > 0 && <><h3 className="market-group-title">Most relevant to your holdings and theses</h3><div className="climate-market-grid">{portfolioMarkets.map(MarketCard)}</div></>}
      <h3 className="market-group-title">Macro and policy expectations</h3><div className="climate-market-grid">{macroMarkets.length ? macroMarkets.map(MarketCard) : !loading && <div className="panel climate-empty"><strong>No validated macro contracts are stored</strong><p>EagleEyes will not substitute an invented probability.</p></div>}</div>
    </details>

    <section className="panel unified-assistant-callout"><div><span>One assistant, all the context</span><h3>Ask EagleEyes to connect this climate to your holdings.</h3><p>The routed assistant can use macro evidence, prediction markets, company research, saved theses, decisions, and portfolio data without creating another chat history on this page.</p></div><button className="primary" onClick={() => onAsk("How does the current market climate affect my portfolio, and which holdings are most exposed if the state changes?")}>Open Ask EagleEyes →</button></section>
  </section>;
}

function MarketCard(market: ForecastMarket) {
  return <article className="panel climate-market-card" key={`${market.provider}-${market.market_id}`}><header><span>{market.provider}</span><small>{market.category.replaceAll("_", " ")}</small></header><h3>{market.title}</h3><strong>{pct(market.probability.probability, 1)}</strong><p>{market.change.percentage_point_change == null ? "No comparable prior snapshot" : `${market.change.percentage_point_change >= 0 ? "+" : ""}${market.change.percentage_point_change.toFixed(1)} percentage points since the prior snapshot`}</p><small>Quality {market.quality.level.replaceAll("_", " ").toLowerCase()} · liquidity {market.quality.liquidity.toLowerCase()}</small>{market.affected_holdings.length > 0 && <p><b>Portfolio link:</b> {market.affected_holdings.join(", ")}</p>}{market.source_url && <a href={market.source_url} target="_blank" rel="noreferrer">Open source market ↗</a>}</article>;
}

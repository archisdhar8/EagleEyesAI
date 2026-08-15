"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { resultPresentation } from "../../lib/result-presentation";
import type { PresentationLevel } from "../../lib/presentation-level";
import { GuidanceLevel } from "../shared/GuidanceLevel";

type Universe = {
  definition: string; source: string; total: number; holdings: number; watchlist: number;
  explicitly_requested: number; sector_or_broad_etfs: number; tickers: string[];
};

type SecurityResult = {
  ticker: string; company: string; sector: string; industry: string; relative_rank: number;
  evidence_bucket: string; bucket_explanation: string;
  strengths: Array<{label:string;evidence:number}>; weaknesses: Array<{label:string;evidence:number}>;
  valuation_range: {label:string;basis:string}; comparable_valuation?: {label:string;security_evidence:number;peer_median_evidence?:number|null;peer_count:number;peer_tickers:string[];basis:string}; fundamental_trend: {label:string;revenue_growth?:number|null;net_margin?:number|null};
  valuation_methodology?:{status:"available"|"insufficient";score?:number|null;source:string;method:string;raw_metrics:Record<string,number|null>;components:Array<{metric:string;value?:number|null;score_effect:number;reason?:string}>;formula:string;thresholds?:Record<string,string>;missing_inputs?:string[];limitations:string[]};
  price_behavior: {label:string;one_year_change?:number|null}; catalysts: Array<{title:string;source_url?:string|null}>;
  thesis_risks: string[]; portfolio_fit: string; what_would_change_the_view: string;
  field_coverage?:{available:string[];missing:string[];ratio:number;policy:string};
  classification?:{sector:string;industry:string;memberships:Array<{type:string;name:string;weight?:number|null;as_of?:string|null;provider?:string|null;source_url?:string|null}>};
  fund_details?:null|{expense_ratio?:number|null;effective_at?:string|null;provider?:string|null;source_url?:string|null;total_holdings?:number;top_holdings:Array<{ticker:string;weight:number;as_of?:string|null;provider?:string|null}>};
  fund_coverage?:{status:string;reason?:string|null;provider?:string|null;source_url?:string|null};
  etf_overlap?:Array<{fund_ticker:string;weight:number;as_of?:string|null;provider?:string|null;source_url?:string|null}>;
  freshness: {status:string;price_as_of?:string|null;fundamentals_as_of?:string|null;coverage:string;confidence_reasons:string[]};
  disclaimer: string; final_score?:number; growth_rating?:number; valuation_score?:number; fundamental_score?:number;
  technical_score?:number; industry_score?:number; news_score?:number;
  market_statistics?:{status:string;reason?:string;method?:string;observations?:number;start_date?:string;end_date?:string;last_price?:number;return_1d?:number|null;return_1m?:number|null;return_3m?:number|null;return_1y?:number|null;annualized_return?:number|null;annualized_volatility?:number|null;sharpe_ratio?:number|null;max_drawdown?:number|null;rsi_14?:number|null;sma_50?:number|null;sma_200?:number|null;high_52w?:number|null;low_52w?:number|null;latest_volume?:number|null;average_volume_20d?:number|null;assumptions?:string[]};
  fundamental_statistics?:{revenue?:number|null;net_income?:number|null;eps_diluted?:number|null;free_cash_flow?:number|null;total_assets?:number|null;total_debt?:number|null;shares_diluted?:number|null;net_margin?:number|null;debt_to_assets?:number|null;period_end?:string|null;fiscal_period?:string|null;source?:string|null};
  news_sentiment?:{label:string;mean_score?:number|null;article_count:number;latest_published_at?:string|null;method:string};
  historical_coverage?: { provider?:string|null; first_date?:string|null; last_date?:string|null; observations?:number; estimated_missing_sessions?:number; years?:number; corporate_action_adjusted?:boolean; adjustment_method?:string; full_cycle_available?:boolean; direct_factor_model_eligible?:boolean; fallback?:{ticker:string;available:boolean;provider?:string|null}; warnings?:string[]; lineage?:Array<{provider:string;dataset:string;effective_through?:string|null;dataset_version?:string}> };
  missing_data?:Array<{field:string;reason:string;provider?:string|null}>;
};

type SearchPayload = {query:string;filters:Record<string,string|null>;universe:Universe;results:SecurityResult[];method:{name:string;version:string;ranking_use:string};disclaimer:string;historical_coverage?:{summary:{requested:number;full_cycle:number;insufficient:number;insufficient_symbols:string[]};warnings:string[]};supported_scope?:{scope:string;unsupported_reason?:string|null;results:Array<{ticker:string;name:string;coverage_tier:string;instrument_type:string;active:boolean;verified_at?:string|null}>}};
type SectorPayload = {universe:Universe;sectors:Array<{sector:string;security_count:number;coverage:string;evidence_mix:Record<string,number>;leaders:string[];disclaimer:string}>};
type ThemePayload = {universe:Universe;themes:Array<{key:string;label:string;description:string;member_count:number;tickers:string[];mapping_rule:string;universe:Universe}>};

const emptyUniverse:Universe={definition:"Research universe is loading.",source:"pending",total:0,holdings:0,watchlist:0,explicitly_requested:0,sector_or_broad_etfs:0,tickers:[]};
const percent=(value?:number|null)=>value==null?"—":`${(value*100).toFixed(1)}%`;
const dateLabel=(value?:string|null)=>value?new Date(value).toLocaleDateString(undefined,{month:"short",day:"numeric",year:"numeric"}):"Unknown";
const multiple=(value?:number|null)=>value==null?"—":`${value.toFixed(2)}×`;
const dollars=(value?:number|null)=>value==null?"—":new Intl.NumberFormat(undefined,{style:"currency",currency:"USD",notation:"compact",maximumFractionDigits:2}).format(value);

function UniverseCard({universe}:{universe:Universe}){
  const guidance=universe.holdings>0
    ?{level:"Portfolio-Aware Analysis" as const,reason:"Saved holdings affect portfolio-fit evidence; company-quality evidence remains independent.",missing_context:["approved personalized-guidance profile"]}
    :{level:"General Market Research" as const,reason:"This result uses the disclosed research universe without personal portfolio constraints.",missing_context:["saved portfolio"]};
  return <><GuidanceLevel guidance={guidance}/><aside className="research-universe-card"><div><span>Disclosed ranking universe</span><strong>{universe.total} securities</strong><p>{universe.definition}</p></div><dl><div><dt>Holdings</dt><dd>{universe.holdings}</dd></div><div><dt>Watchlist</dt><dd>{universe.watchlist}</dd></div><div><dt>Broad / sector ETFs</dt><dd>{universe.sector_or_broad_etfs}</dd></div><div><dt>Requested</dt><dd>{universe.explicitly_requested}</dd></div></dl></aside></>;
}

function SecurityCard({row,expert}:{row:SecurityResult;expert:boolean}){
  const history=row.historical_coverage;
  const valuation=row.valuation_methodology;
  const stats=row.market_statistics;
  const fundamentals=row.fundamental_statistics;
  return <article className="research-result-card">
    <header><div><span>#{row.relative_rank} in visible universe · {row.sector}</span><h3>{row.ticker} <small>{row.company}</small></h3><p>{row.industry}</p></div><b className={`research-bucket ${row.evidence_bucket.toLowerCase().includes("limited")?"caution":""}`}>{row.evidence_bucket}</b></header>
    <p className="bucket-explanation">{row.bucket_explanation}</p>
    {row.field_coverage&&<div className={`field-coverage-strip ${row.field_coverage.ratio<.6?"warning":""}`}><strong>{Math.round(row.field_coverage.ratio*100)}% component coverage</strong><span>Available: {row.field_coverage.available.join(", ")||"none"}</span><span>Missing: {row.field_coverage.missing.join(", ")||"none"}</span><small>{row.field_coverage.policy}</small></div>}
    <div className="research-evidence-grid">
      <section><span>Strengths</span>{row.strengths.map(item=><p key={item.label}><strong>{item.label}</strong><small>{item.evidence.toFixed(0)} relative evidence</small></p>)}</section>
      <section><span>Weaknesses</span>{row.weaknesses.map(item=><p key={item.label}><strong>{item.label}</strong><small>{item.evidence.toFixed(0)} relative evidence</small></p>)}</section>
      <section><span>Valuation range</span><p><strong>{row.valuation_range.label}</strong><small>{row.valuation_range.basis}</small></p></section>
      <section><span>Comparable valuation</span><p><strong>{row.comparable_valuation?.label||"Peer coverage unavailable"}</strong><small>{row.comparable_valuation?.peer_count||0} stored peers{row.comparable_valuation?.peer_tickers?.length?` · ${row.comparable_valuation.peer_tickers.slice(0,5).join(", ")}`:""}</small></p></section>
      <section><span>Fundamental trend</span><p><strong>{row.fundamental_trend.label}</strong><small>Revenue {percent(row.fundamental_trend.revenue_growth)} · margin {percent(row.fundamental_trend.net_margin)}</small></p></section>
      <section><span>Price behavior</span><p><strong>{row.price_behavior.label}</strong><small>One-year adjusted-price change {percent(row.price_behavior.one_year_change)}</small></p></section>
      <section><span>Portfolio fit</span><p><strong>{row.portfolio_fit}</strong></p></section>
    </div>
    <section className="security-stat-workbench"><header><div><span>Financial analysis</span><h4>Market, fundamental, and sentiment statistics</h4></div><small>{stats?.observations||0} adjusted daily observations · {dateLabel(stats?.start_date)}–{dateLabel(stats?.end_date)}</small></header>
      <div className="security-stat-grid">
        <p><span>Price</span><strong>{dollars(stats?.last_price)}</strong><small>1D {percent(stats?.return_1d)} · 1M {percent(stats?.return_1m)}</small></p>
        <p><span>1-year return</span><strong>{percent(stats?.return_1y)}</strong><small>3M {percent(stats?.return_3m)}</small></p>
        <p><span>Volatility</span><strong>{percent(stats?.annualized_volatility)}</strong><small>Annualized from daily returns</small></p>
        <p><span>Sharpe ratio</span><strong>{stats?.sharpe_ratio==null?"—":stats.sharpe_ratio.toFixed(2)}</strong><small>0% risk-free assumption</small></p>
        <p><span>Maximum drawdown</span><strong>{percent(stats?.max_drawdown)}</strong><small>Available stored period</small></p>
        <p><span>RSI (14 day)</span><strong>{stats?.rsi_14==null?"—":stats.rsi_14.toFixed(1)}</strong><small>{stats?.rsi_14==null?"History required":stats.rsi_14>=70?"Historically overbought range":stats.rsi_14<=30?"Historically oversold range":"Neutral range"}</small></p>
        <p><span>Moving averages</span><strong>{dollars(stats?.sma_50)} / {dollars(stats?.sma_200)}</strong><small>50-day / 200-day</small></p>
        <p><span>52-week range</span><strong>{dollars(stats?.low_52w)}–{dollars(stats?.high_52w)}</strong><small>Adjusted daily close</small></p>
        <p><span>Revenue</span><strong>{fundamentals?.revenue==null?"—":dollars(fundamentals.revenue)}</strong><small>Growth {percent(row.fundamental_trend.revenue_growth)}</small></p>
        <p><span>Net income / margin</span><strong>{fundamentals?.net_income==null?"—":dollars(fundamentals.net_income)}</strong><small>{percent(fundamentals?.net_margin)} margin</small></p>
        <p><span>Free cash flow</span><strong>{fundamentals?.free_cash_flow==null?"—":dollars(fundamentals.free_cash_flow)}</strong><small>FCF yield {percent(valuation?.raw_metrics?.free_cash_flow_yield)}</small></p>
        <p><span>Debt / assets</span><strong>{percent(fundamentals?.debt_to_assets)}</strong><small>{fundamentals?.fiscal_period||"Period unavailable"} · {dateLabel(fundamentals?.period_end)}</small></p>
        <p><span>News sentiment</span><strong>{row.news_sentiment?.label||"unavailable"}</strong><small>{row.news_sentiment?.article_count||0} scored articles · through {dateLabel(row.news_sentiment?.latest_published_at)}</small></p>
      </div>
      <details><summary>Algorithm comparison rating</summary><div className="algorithm-rating-grid"><p><span>Overall comparative evidence</span><strong>{row.final_score?.toFixed(0)??"—"}/100</strong></p><p><span>Fundamentals</span><strong>{row.fundamental_score?.toFixed(0)??"—"}/100</strong></p><p><span>Growth</span><strong>{row.growth_rating?.toFixed(0)??"—"}/100</strong></p><p><span>Valuation</span><strong>{row.valuation_score?.toFixed(0)??"—"}/100</strong></p><p><span>Technicals</span><strong>{row.technical_score?.toFixed(0)??"—"}/100</strong></p><p><span>Sentiment</span><strong>{row.news_score?.toFixed(0)??"—"}/100</strong></p></div><small>The overall score is a deterministic weighted comparison inside the disclosed universe. It is not a price target or buy recommendation; missing evidence reduces coverage and confidence.</small></details>
      {stats?.status!=="available"&&<p className="stat-warning">△ {stats?.reason||"Market statistics are unavailable."}</p>}
    </section>
    <div className="research-reference-grid">
      <section><span>Sector, industry & membership</span><p><strong>{row.classification?.sector||row.sector}</strong> · {row.classification?.industry||row.industry}</p>{row.classification?.memberships?.length?row.classification.memberships.slice(0,5).map(item=><a key={`${item.type}-${item.name}`} href={item.source_url||undefined} target="_blank" rel="noreferrer">{item.type}: {item.name}</a>):<small>No index or theme membership dataset is stored.</small>}</section>
      <section><span>ETF holdings & costs</span>{row.fund_details?<><p><strong>{row.fund_details.expense_ratio==null?"Expense ratio unavailable":`${percent(row.fund_details.expense_ratio)} expense ratio`}</strong><small>{row.fund_details.total_holdings??row.fund_details.top_holdings.length} holdings loaded · showing the largest {row.fund_details.top_holdings.length} · {row.fund_details.provider||"provider unknown"}</small></p><div className="etf-holdings-list">{row.fund_details.top_holdings.map(item=><div key={item.ticker}><b>{item.ticker}</b><span>{percent(item.weight)}</span><i><em style={{width:`${Math.min(100,(item.weight||0)*100)}%`}}/></i></div>)}</div>{row.fund_details.source_url&&<a href={row.fund_details.source_url} target="_blank" rel="noreferrer">Open provider source ↗</a>}</>:<><strong>Holdings unavailable</strong><small>{row.fund_coverage?.reason||"No current ETF reference or constituent snapshot is stored."}</small>{row.fund_coverage?.source_url&&<a href={row.fund_coverage.source_url} target="_blank" rel="noreferrer">Open fund source ↗</a>}</>}</section>
      <section><span>Funds containing this security</span>{row.etf_overlap?.length?row.etf_overlap.slice(0,5).map((item,index)=><a key={`${item.fund_ticker}-${item.as_of||index}`} href={item.source_url||undefined} target="_blank" rel="noreferrer">{item.fund_ticker} · {percent(item.weight)} of fund</a>):<small>No stored ETF look-through overlap is available.</small>}</section>
    </div>
    <details className={`valuation-audit ${valuation?.status==="available"?"ready":"warning"}`} open={valuation?.status!=="available"}><summary>Review valuation logic</summary>{valuation?.status==="available"?<><p><b>{valuation.method}</b><small>{valuation.source}</small></p><div className="valuation-metrics"><p><span>Price</span><b>{dollars(valuation.raw_metrics.price)}</b></p><p><span>P / E</span><b>{multiple(valuation.raw_metrics.pe)}</b></p><p><span>P / sales</span><b>{multiple(valuation.raw_metrics.price_to_sales)}</b></p><p><span>FCF yield</span><b>{percent(valuation.raw_metrics.free_cash_flow_yield)}</b></p></div><p>{valuation.formula}</p>{valuation.components.map(item=><small key={item.metric}><b>{item.metric}:</b> {item.value==null?item.reason||"not available":item.metric.includes("yield")?percent(item.value):multiple(item.value)} · {item.score_effect>=0?"+":""}{item.score_effect} evidence points</small>)}{valuation.thresholds&&<details><summary>Exact thresholds</summary>{Object.entries(valuation.thresholds).map(([key,value])=><small key={key}><b>{key.replaceAll("_"," ")}:</b> {value}</small>)}</details>}{valuation.limitations.map(item=><small key={item}>△ {item}</small>)}</>:<><p><b>No valuation conclusion</b><small>The card will not turn a neutral fallback into a valuation claim.</small></p><p>Missing: {valuation?.missing_inputs?.join(", ")||"auditable price and fundamental inputs"}.</p><small>Connect or refresh adjusted prices and SEC Company Facts, then search again.</small></>}</details>
    {!!row.missing_data?.length&&<details className="missing-data-audit" open><summary>Why some data is missing ({row.missing_data.length})</summary>{row.missing_data.map(item=><div key={item.field}><b>{item.field}</b><p>{item.reason}</p><small>Needed source: {item.provider||"not identified"}</small></div>)}</details>}
    <div className="research-thesis-grid"><section><span>Catalysts</span>{row.catalysts.length?row.catalysts.slice(0,3).map((item,index)=><a key={`${item.title}-${index}`} href={item.source_url||undefined} target="_blank" rel="noreferrer">{item.title}</a>):<p>No current stored catalyst coverage.</p>}</section><section><span>Thesis risks</span>{row.thesis_risks.slice(0,3).map(item=><p key={item}>{item.replaceAll("_"," ")}</p>)}</section><section><span>What would change the view</span><p>{row.what_would_change_the_view}</p></section></div>
    {history&&<details className={`research-history-coverage ${history.full_cycle_available?"ready":"warning"}`} open={!history.full_cycle_available}><summary>{history.full_cycle_available?"Full-cycle adjusted-price coverage":"Historical coverage warning"}</summary><div><p><b>{history.years?.toFixed(1)||"0.0"} years</b><small>{history.observations||0} daily observations · {history.provider||"no provider"}</small></p><p><b>{history.corporate_action_adjusted?"Adjustment verified":"Adjustment unverified"}</b><small>{history.adjustment_method||"Unknown adjustment method"}</small></p><p><b>Fallback {history.fallback?.ticker||"VTI"}</b><small>{history.fallback?.available?"Verified full-cycle proxy available":"Fallback coverage is also insufficient"}</small></p></div>{history.warnings?.map(item=><small className="history-warning" key={item}>△ {item}</small>)}{expert&&history.lineage?.map(item=><small key={`${item.provider}-${item.dataset}`}>{item.provider} · {item.dataset} · through {dateLabel(item.effective_through)} · {item.dataset_version}</small>)}</details>}
    <footer><span>{row.freshness.coverage} coverage</span><span>{row.freshness.status} evidence</span><span>Price {dateLabel(row.freshness.price_as_of)}</span><span>Fundamentals {dateLabel(row.freshness.fundamentals_as_of)}</span>{history&&<span>{history.direct_factor_model_eligible?"Direct factor history eligible":"Proxy / limited-history treatment required"}</span>}</footer>
    {expert&&<details><summary>Expert ranking components</summary><p>Composite ordering input {row.final_score?.toFixed(0)??"—"} · growth {row.growth_rating?.toFixed(0)??"—"} · valuation {row.valuation_score?.toFixed(0)??"—"} · fundamentals {row.fundamental_score?.toFixed(0)??"—"}</p><small>The composite only orders eligible results; it is not the conclusion.</small></details>}
  </article>;
}

export function ResearchDiscovery({view,request,presentationLevel}:{view:"stocks"|"sectors"|"themes";request:(path:string,init?:RequestInit)=>Promise<Response>;presentationLevel:PresentationLevel}){
  const requestRef=useRef(request);
  const requestIdRef=useRef(0);
  const [query,setQuery]=useState("");
  const [preset,setPreset]=useState(false);
  const [payload,setPayload]=useState<SearchPayload|null>(null);
  const [sectors,setSectors]=useState<SectorPayload|null>(null);
  const [themes,setThemes]=useState<ThemePayload|null>(null);
  const [selectedTheme,setSelectedTheme]=useState("");
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState("");
  const presentation=resultPresentation(presentationLevel);

  useEffect(()=>{requestRef.current=request;},[request]);

  async function loadStocks(search=query,filter=preset,theme=selectedTheme){
    const requestId=++requestIdRef.current;
    setLoading(true);setError("");
    const params=new URLSearchParams();if(search)params.set("q",search);if(filter){params.set("fundamentals","strong");params.set("valuation","reasonable");}if(theme)params.set("theme",theme);
    try{
      const response=await requestRef.current(`/research/search?${params}`);if(!response.ok)throw new Error(await response.text());const result=await response.json();if(requestId===requestIdRef.current)setPayload(result);
    }catch(reason){setError(reason instanceof Error?reason.message:"Research search failed");}finally{if(requestId===requestIdRef.current)setLoading(false);}
  }

  useEffect(()=>{let cancelled=false;const requestId=++requestIdRef.current;(async()=>{try{if(view==="stocks"){const response=await requestRef.current("/research/search?");if(!cancelled&&requestId===requestIdRef.current&&response.ok)setPayload(await response.json());}if(view==="sectors"){const response=await requestRef.current("/research/sectors");if(!cancelled&&requestId===requestIdRef.current&&response.ok)setSectors(await response.json());}if(view==="themes"){const response=await requestRef.current("/research/themes");if(!cancelled&&requestId===requestIdRef.current&&response.ok)setThemes(await response.json());}}catch{}finally{if(!cancelled&&requestId===requestIdRef.current)setLoading(false);}})();return()=>{cancelled=true};},[view]);

  const submit=(event:FormEvent)=>{event.preventDefault();void loadStocks();};
  if(view==="sectors")return <section className="workspace research-discovery"><div className="section-intro"><div><span className="kicker">Sector research</span><h2>See coverage and evidence breadth before comparing sectors.</h2><p>Sector summaries reflect only the disclosed stored universe and are not allocation recommendations.</p></div></div><UniverseCard universe={sectors?.universe||emptyUniverse}/><div className="sector-research-grid">{sectors?.sectors.map(item=><article className="panel" key={item.sector}><span>{item.coverage} coverage · {item.security_count} securities</span><h3>{item.sector}</h3><p>Leading stored names: {item.leaders.join(", ")||"none"}</p><div>{Object.entries(item.evidence_mix).map(([key,value])=><small key={key}>{key}: {value}</small>)}</div><footer>{item.disclaimer}</footer></article>)}</div></section>;
  if(view==="themes")return <section className="workspace research-discovery"><div className="section-intro"><div><span className="kicker">Theme research</span><h2>Theme membership is disclosed, not implied.</h2><p>Every result shows the mapping rule and the actual stored universe searched.</p></div></div><UniverseCard universe={themes?.universe||emptyUniverse}/><div className="theme-research-grid">{themes?.themes.map(item=><article className="panel" key={item.key}><span>{item.member_count} matched securities</span><h3>{item.label}</h3><p>{item.description}</p><strong>{item.tickers.slice(0,12).join(", ")||"No stored matches"}</strong><small>{item.mapping_rule}</small><button onClick={()=>{setSelectedTheme(item.key);void loadStocks("",false,item.key);}}>Open matching stocks</button></article>)}</div>{selectedTheme&&payload&&<><UniverseCard universe={payload.universe}/><div className="research-result-list">{payload.results.map(row=><SecurityCard key={row.ticker} row={row} expert={presentation.showDiagnostics}/>)}</div></>}</section>;
  return <section className="workspace research-discovery"><div className="section-intro"><div><span className="kicker">Stock discovery and investigation</span><h2>Search by symbol, company, or deterministic evidence filters.</h2><p>Word-based conclusions lead. Numeric component scores remain available only in Expert mode and for ordering.</p></div></div>
    <form className="research-search-form" onSubmit={submit}><label>Stock, ETF, or company<input value={query} onChange={event=>setQuery(event.target.value)} placeholder="AAPL, QQQ, ARKK, or Apple"/></label><label className="check-row" title="Requires stored business-quality evidence of at least 60/100 and auditable valuation evidence of at least 50/100. Missing inputs exclude a result."><input type="checkbox" checked={preset} onChange={event=>setPreset(event.target.checked)}/><span><b>Only show supportive fundamentals + valuation</b><small>Requires business-quality evidence ≥60 and available valuation evidence ≥50. This is an optional strict filter; leave it off for a normal symbol search.</small></span></label><button type="submit" className="primary" disabled={loading}>{loading?"Searching stored evidence…":"Search research"}</button></form>
    {error&&<div className="warning-strip"><span>{error}</span></div>}<UniverseCard universe={payload?.universe||emptyUniverse}/>
    {payload?.supported_scope&&<aside className={`research-scope-disclosure ${payload.supported_scope.unsupported_reason?"warning":""}`}><strong>Supported security scope</strong><p>{payload.supported_scope.scope}</p>{payload.supported_scope.unsupported_reason&&<small>{payload.supported_scope.unsupported_reason}</small>}{payload.supported_scope.results.length>0&&<span>{payload.supported_scope.results.slice(0,8).map(item=>`${item.ticker} · ${item.coverage_tier.replaceAll("_"," ")}`).join("  |  ")}</span>}</aside>}
    {payload?.historical_coverage&&payload.historical_coverage.summary.insufficient>0&&<div className="warning-strip"><span>△ {payload.historical_coverage.summary.insufficient} of {payload.historical_coverage.summary.requested} researched securities lack a verified full market cycle. Factor, regime, and backtest claims will use disclosed proxy or limited-history treatment.</span></div>}
    <div className="research-result-list">{payload?.results.map(row=><SecurityCard key={row.ticker} row={row} expert={presentation.showDiagnostics}/>)}</div>
    {!loading&&!payload&&<div className="panel empty-state"><h3>Search the supported stock and ETF universe</h3><p>Enter a symbol or company name. Stored evidence appears first; provider refreshes are separate so search stays responsive.</p></div>}
    {!loading&&payload?.results.length===0&&<div className="panel empty-state"><h3>{preset?"The current filter excluded this result":"No eligible evidence is available yet"}</h3><p>{preset?"The symbol may exist, but it did not meet both the fundamentals and auditable-valuation thresholds. Remove the filter to inspect all available evidence.":"No usable stored evidence matched. Check the missing-data explanation or Provider health, then refresh the symbol deliberately."}</p>{preset&&<button className="primary" onClick={()=>{setPreset(false);void loadStocks(query,false,selectedTheme);}}>Show available evidence without the filter</button>}</div>}
  </section>;
}

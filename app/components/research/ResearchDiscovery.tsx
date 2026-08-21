"use client";

/*
 * The consolidated endpoint intentionally returns several versioned research
 * payloads whose provider-specific fields are not stable enough to model as a
 * single frontend interface. Refs also coordinate cancellation across rapid
 * searches, and the mount effects intentionally initialize external URL/prop
 * state once. Keep these exceptions local to this integration boundary.
 */
/* eslint-disable @typescript-eslint/no-explicit-any, react-hooks/set-state-in-effect, react-hooks/refs, react-hooks/exhaustive-deps */

import { type FormEvent, useEffect, useRef, useState } from "react";
import Link from "next/link";
import type { PresentationLevel } from "../../lib/presentation-level";

type Request = (path: string, init?: RequestInit) => Promise<Response>;
type Holding = { ticker: string; weight?: number | null; market_value?: number | null };
type Case = { key:string; label:string; outcome:string; drivers:string[]; invalidation_conditions:string[]; full_text:string; confidence:string; evidence_as_of?:string|null; source:string; saved_as_user_belief:boolean };
type Overview = {
  ticker:string; security:Record<string,any>; membership:{holding:boolean;watchlist:boolean;holding_detail?:Holding|null};
  earnings:Record<string,any>; forecasts:Record<string,any>; changes:Record<string,any>;
  cases:Record<"bear"|"base"|"bull",Case>; freshness:Record<string,any>; confidence:string;
  missing_data:string[]; partial:boolean; cache:{status:string};
};
type Props = { view:"stocks"|"sectors"|"themes"; request:Request; presentationLevel:PresentationLevel; holdings:Holding[]; watchlist:string[]; portfolioId?:string|number|null; onWatchlistChange?:(tickers:string[])=>void };
type CollectionItem = { sector?:string; key?:string; label?:string; security_count?:number; member_count?:number; description?:string; leaders?:string[]; mapping_rule?:string };
type CollectionPayload = { sectors?:CollectionItem[]; themes?:CollectionItem[] };

const money=(value:unknown)=>typeof value==="number"&&Number.isFinite(value)?new Intl.NumberFormat("en-US",{style:"currency",currency:"USD",maximumFractionDigits:2}).format(value):"—";
const compact=(value:unknown)=>typeof value==="number"&&Number.isFinite(value)?new Intl.NumberFormat("en-US",{notation:"compact",maximumFractionDigits:1}).format(value):"—";
const percent=(value:unknown)=>typeof value==="number"&&Number.isFinite(value)?`${(Math.abs(value)<=2?value*100:value).toFixed(1)}%`:"—";
const dateLabel=(value:unknown)=>typeof value==="string"&&value?new Date(value).toLocaleDateString(undefined,{month:"short",day:"numeric",year:"numeric"}):"Awaiting data";
const text=(value:unknown,fallback="Unavailable")=>typeof value==="string"&&value.trim()?value:fallback;
const score=(value:unknown)=>typeof value==="number"&&Number.isFinite(value)?Math.round(value).toString():"—";
const errorMessage=(reason:unknown,fallback:string)=>reason instanceof Error?reason.message:fallback;

function Stat({label,value,detail}:{label:string;value:string;detail:string}){return <article><span>{label}</span><strong>{value}</strong><small>{detail}</small></article>;}

function CaseColumn({item}:{item:Case}){
  return <article className={`research-case ${item.key}`}>
    <header><div><span>{item.label} case</span><h3>{item.outcome}</h3></div><small>{item.confidence} confidence</small></header>
    <p>{item.full_text.split(/\n\n/)[0]}</p>
    <div><strong>What drives it</strong>{item.drivers.length?item.drivers.map(driver=><span key={driver}>• {driver}</span>):<span>More company evidence is needed.</span>}</div>
    <div><strong>What would disprove it</strong>{item.invalidation_conditions.length?item.invalidation_conditions.map(driver=><span key={driver}>• {driver}</span>):<span>No measurable invalidation condition is stored.</span>}</div>
    <footer>Evidence through {dateLabel(item.evidence_as_of)} · {item.saved_as_user_belief?"Includes saved thesis history":"Generated research case; not saved as your belief"}</footer>
    <details><summary>Read full case</summary><p>{item.full_text}</p></details>
  </article>;
}

function SecurityOverview({overview,busy,onToggleWatchlist}:{overview:Overview;busy:boolean;onToggleWatchlist:()=>void}){
  const row=overview.security;const stats=row.statistics||row.market_statistics||{};const fundamentals=row.fundamentals||{};const trend=row.fundamental_trend||{};const valuation=row.valuation_evidence||row.valuation||{};
  const earnings=overview.earnings||{};const markets=Array.isArray(overview.forecasts?.markets)?overview.forecasts.markets:[];const changes=Array.isArray(overview.changes?.changes)?overview.changes.changes:[];
  return <div className="unified-security-report">
    <header className="unified-security-hero"><div><span>{overview.membership.holding?"Portfolio holding":overview.membership.watchlist?"Watchlist":"Company research"}</span><h2>{overview.ticker} <small>{text(row.company,overview.ticker)}</small></h2><p>{text(row.sector,"Sector unavailable")} · {text(row.industry,"Industry unavailable")} · {overview.confidence} evidence confidence</p></div><div><button className={overview.membership.watchlist?"secondary active":"secondary"} disabled={busy} onClick={onToggleWatchlist}>{overview.membership.watchlist?"✓ On watchlist":"＋ Add to watchlist"}</button><Link className="primary" href={`/ask?ticker=${encodeURIComponent(overview.ticker)}`}>Ask EagleEyes →</Link></div></header>
    {overview.partial&&<div className="research-partial-state"><strong>Partial evidence</strong><span>The useful stored results are shown now. Missing: {overview.missing_data.join(", ")||"some research inputs"}.</span></div>}
    <section className="research-summary-table" aria-label="Company statistics">
      <Stat label="Price" value={money(stats.last_price??row.price)} detail={`1 year ${percent(stats.return_1y??row.price_change_1y)}`}/><Stat label="Fundamentals" value={score(row.fundamental_score)} detail={`Revenue growth ${percent(trend.revenue_growth??row.revenue_growth)}`}/><Stat label="Valuation" value={score(row.valuation_score)} detail={text(row.valuation_range?.label??valuation.label,"Evidence unavailable")}/><Stat label="Momentum" value={score(row.technical_score)} detail={`3 month ${percent(stats.return_3m)}`}/><Stat label="Risk" value={percent(stats.annualized_volatility)} detail={`Max drawdown ${percent(stats.max_drawdown)}`}/><Stat label="Portfolio fit" value={overview.membership.holding?percent(overview.membership.holding_detail?.weight):"Not held"} detail={overview.membership.holding?money(overview.membership.holding_detail?.market_value):text(row.portfolio_fit,"New exposure")}/>
    </section>
    <section className="research-detail-grid"><article><span>Reported earnings</span><strong>{earnings.status==="AVAILABLE"?`${earnings.period?.fiscal_period||"Period"} ${earnings.period?.fiscal_year||""}`:"Stored report unavailable"}</strong><p>Revenue {compact(earnings.actual_vs_expectations?.revenue?.actual??fundamentals.revenue)} · EPS {earnings.actual_vs_expectations?.eps?.actual??"—"}</p><small>{(earnings.warnings||[])[0]||`Period ending ${dateLabel(earnings.period?.period_end)}`}</small></article><article><span>Forward statistics</span><strong>{markets.length?`${markets.length} relevant market signal${markets.length===1?"":"s"}`:"No mapped market signal"}</strong><p>{markets[0]?.title||"Prediction-market evidence is shown only when a verified company mapping exists."}</p><small>{markets[0]?.probability?.probability!=null?`${percent(markets[0].probability.probability)} market-implied`:"No probability inferred"}</small></article><article><span>Recent material changes</span><strong>{changes.length?`${changes.length} stored change${changes.length===1?"":"s"}`:"No material change recorded"}</strong><p>{changes[0]?.summary||changes[0]?.label||"A prior research baseline is required before change attribution is available."}</p><small>Compared with the latest saved research review</small></article></section>
    <section className="research-cases"><header><div><span>Scenario report</span><h2>Bear, base, and bull cases</h2></div><small>Distinct operating outcomes built from cached evidence. Generated cases are never silently saved as your beliefs.</small></header><div>{(["bear","base","bull"] as const).map(key=><CaseColumn key={key} item={overview.cases[key]}/>)}</div></section>
    <footer className="research-report-footer"><span>Price through {dateLabel(overview.freshness?.price_as_of)}</span><span>Fundamentals through {dateLabel(overview.freshness?.fundamentals_as_of)}</span><span>{overview.cache.status==="hit"?"Loaded from cache":"Cached for the next view"}</span></footer>
  </div>;
}

export function ResearchDiscovery({view,request,holdings,watchlist,portfolioId,onWatchlistChange}:Props){
  const deepLinkedTicker=typeof window==="undefined"?"":new URL(window.location.href).searchParams.get("ticker")?.toUpperCase()||"";
  const [query,setQuery]=useState(deepLinkedTicker);const [selected,setSelected]=useState(deepLinkedTicker);const [overview,setOverview]=useState<Overview|null>(null);const [membership,setMembership]=useState<"holdings"|"watchlist">("holdings");const [localWatchlist,setLocalWatchlist]=useState(watchlist);const [loading,setLoading]=useState(Boolean(deepLinkedTicker));const [watchlistBusy,setWatchlistBusy]=useState(false);const [error,setError]=useState("");const [collection,setCollection]=useState<CollectionPayload|null>(null);
  const activeRequest=useRef(0);const abortRef=useRef<AbortController|null>(null);
  useEffect(()=>setLocalWatchlist(watchlist),[watchlist]);
  async function loadOverview(raw:string){
    const search=raw.trim();if(!search)return;const requestId=++activeRequest.current;abortRef.current?.abort();const controller=new AbortController();abortRef.current=controller;setLoading(true);setError("");
    try{let ticker=search.toUpperCase();if(!/^[A-Z][A-Z0-9.-]{0,9}$/.test(ticker)){const searchResponse=await request(`/research/search?q=${encodeURIComponent(search)}&limit=1`,{signal:controller.signal});if(!searchResponse.ok)throw new Error("No supported company matched that search.");const searchPayload=await searchResponse.json();ticker=searchPayload.results?.[0]?.ticker||"";}if(!ticker)throw new Error("No supported company matched that search.");const params=portfolioId?`?portfolio_id=${encodeURIComponent(String(portfolioId))}`:"";const response=await request(`/research/security/${encodeURIComponent(ticker)}/overview${params}`,{signal:controller.signal});if(!response.ok){const body=await response.json().catch(()=>({}));throw new Error(body.detail||"Company research is unavailable.");}const data=await response.json();if(requestId!==activeRequest.current)return;setSelected(ticker);setQuery(ticker);setOverview(data);window.history.replaceState({},"",`/research?ticker=${encodeURIComponent(ticker)}`);}catch(reason){if(controller.signal.aborted||requestId!==activeRequest.current)return;setError(errorMessage(reason,"Company research is unavailable."));setOverview(null);}finally{if(requestId===activeRequest.current)setLoading(false);}
  }
  useEffect(()=>{if(deepLinkedTicker)void loadOverview(deepLinkedTicker);return()=>abortRef.current?.abort();},[]);
  useEffect(()=>{if(view==="stocks")return;let active=true;const task=window.setTimeout(()=>{if(!active)return;setLoading(true);request(view==="sectors"?"/research/sectors":"/research/themes").then(async response=>{if(!response.ok)throw new Error("Research collection unavailable");const data=await response.json();if(active)setCollection(data);}).catch(reason=>{if(active)setError(errorMessage(reason,"Research collection unavailable"));}).finally(()=>{if(active)setLoading(false);});},0);return()=>{active=false;window.clearTimeout(task);};},[view,request]);
  async function toggleWatchlist(){if(!overview||watchlistBusy)return;const ticker=overview.ticker;const removing=overview.membership.watchlist;const previous=[...localWatchlist];const next=removing?previous.filter(item=>item!==ticker):Array.from(new Set([...previous,ticker]));setWatchlistBusy(true);setLocalWatchlist(next);setOverview({...overview,membership:{...overview.membership,watchlist:!removing}});onWatchlistChange?.(next);try{const response=await request(`/watchlist/${encodeURIComponent(ticker)}`,{method:removing?"DELETE":"PUT"});if(!response.ok)throw new Error("Watchlist update failed");const result=await response.json();setLocalWatchlist(result.tickers);onWatchlistChange?.(result.tickers);}catch(reason){setLocalWatchlist(previous);setOverview(current=>current?{...current,membership:{...current.membership,watchlist:removing}}:current);onWatchlistChange?.(previous);setError(errorMessage(reason,"Watchlist update failed"));}finally{setWatchlistBusy(false);}}
  if(view!=="stocks"){const items=view==="sectors"?collection?.sectors:collection?.themes;return <section className="workspace research-collection"><div className="section-intro"><div><span className="kicker">More research</span><h2>{view==="sectors"?"Sector coverage":"Theme coverage"}</h2><p>Browse the disclosed stored universe, then open a company in the main Research workspace.</p></div></div>{error&&<div className="warning-strip">{error}</div>}<div className="compact-research-table">{(items||[]).map(item=><article key={item.sector||item.key}><strong>{item.sector||item.label}</strong><span>{item.security_count??item.member_count??0} securities</span><small>{item.description||item.leaders?.join(", ")||item.mapping_rule}</small></article>)}</div>{loading&&<p className="report-loading"><span/>Loading stored coverage…</p>}</section>;}
  const symbols=membership==="holdings"?holdings.map(item=>item.ticker):localWatchlist;
  const unique=Array.from(new Set(symbols.map(item=>item.trim().toUpperCase()).filter(item=>item&&item!=="CASH")));
  const submit=(event:FormEvent<HTMLFormElement>)=>{event.preventDefault();void loadOverview(query);};
  return <section className="workspace unified-research-workspace">
    <header className="unified-research-header"><div><span className="kicker">Company research</span><h1>One clear view of the evidence.</h1><p>Search a company, scan your holdings or watchlist, and compare a distinct bear, base, and bull case without waiting for Gemini or a live provider.</p></div></header>
    <form className="unified-research-search" onSubmit={submit}><label><span>Stock, ETF, or company</span><input value={query} onChange={event=>setQuery(event.target.value)} placeholder="AAPL or Apple" autoComplete="off"/></label><button type="submit" className="primary" disabled={loading||!query.trim()}>{loading?"Loading saved research…":"Open research →"}</button></form>
    <div className="research-collection-bar"><div role="tablist" aria-label="Research lists"><button className={membership==="holdings"?"active":""} onClick={()=>setMembership("holdings")}>Holdings <span>{holdings.length}</span></button><button className={membership==="watchlist"?"active":""} onClick={()=>setMembership("watchlist")}>Watchlist <span>{localWatchlist.length}</span></button></div><div>{unique.length?unique.map(ticker=><button key={ticker} className={selected===ticker?"selected":""} onClick={()=>void loadOverview(ticker)}>{ticker}</button>):<span>{membership==="holdings"?"No saved holdings yet.":"Your watchlist is empty."}</span>}</div></div>
    {error&&<div className="warning-strip"><span>{error}</span><button onClick={()=>void loadOverview(query)}>Retry</button></div>}
    {loading&&<div className="panel research-report-skeleton" role="status"><span/><div><strong>Loading cached company evidence</strong><small>Superseded searches are cancelled automatically.</small></div></div>}
    {!loading&&overview&&<SecurityOverview overview={overview} busy={watchlistBusy} onToggleWatchlist={()=>void toggleWatchlist()}/>} {!loading&&!overview&&!error&&<div className="panel research-start-state"><span>◎</span><h2>Choose a holding or search a company.</h2><p>The first useful partial result appears immediately. Provider refreshes happen separately and never block this page.</p></div>}
  </section>;
}

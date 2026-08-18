"use client";

import { useMemo, useState } from "react";
import type { Tab, ExploreView, PortfolioView, AdvancedView } from "../../lib/routes";
import type { GuidanceDisclosure } from "../shared/GuidanceLevel";

type EvidenceLink = { label:string;url?:string|null;as_of?:string|null;provider:string };
type Movement = {ticker:string;label:string;group:"index"|"sector"|"portfolio";value:number;change_1d?:number|null;as_of?:string|null;unit:string;provider:string;data_status:string};
type MarketIndicator = {key:string;series_id:string;label:string;unit:string;value:number;change?:number|null;as_of?:string|null;provider:string;data_status:string};
type Relevance = {key:string;factor:string;relevance:"high"|"moderate"|"low";direction:"positive"|"negative"|"mixed";explanation:string;destination:string;evidence:EvidenceLink[]};
type Event = {id:string;event_type:string;title:string;starts_at:string;tickers?:string[];provider:string;source_url?:string|null};
type EventCoverage = {requested_tickers:string[];earnings_covered_tickers:string[];earnings_missing_tickers:string[];earnings_coverage_ratio:number|null;macro_release_count:number;deduplicated_count:number;note:string};
type Attention = {id:string;title:string;ask_prompts:string[]};
type PortfolioSummary = {available:boolean;change_1d?:number|null;dollar_change?:number|null;portfolio_value?:number|null;benchmark_ticker:string;benchmark_change_1d?:number|null;contributors:Array<{ticker:string;contribution:number;change_1d:number}>;methodology:string};

export type TodayBriefing = {
  version:string;as_of:string;market_data_as_of?:string|null;evidence_state:"current"|"partial"|"stale_fallback";guidance:GuidanceDisclosure;headline:string;summary:string;
  portfolio_context:{available:boolean;name?:string|null;holding_count:number;missing_symbols:string[];weak_coverage_symbols:string[]};
  market_movement:Movement[];market_indicators:MarketIndicator[];portfolio_relevance:Relevance[];attention:Attention[];
  portfolio_summary?:PortfolioSummary;daily_brief?:{text:string};upcoming_events:Event[];event_coverage:EventCoverage;
  warnings:string[];calculation:{method:string;version:string;assumptions:string[]};
};

type HealthComponent = {score:number;weight:number;coverage:number};
export type PortfolioAction = {
  id:string;source_key:string;source:string;action:"REVIEW"|"REDUCE"|"ADD"|"HOLD"|"INVESTIGATE";
  title:string;reason:string;affected_holdings:string[];materiality:string;urgency:string;confidence:string;
  portfolio_exposure:number;evidence_date?:string|null;suggested_next_step:string;follow_up_date?:string|null;priority:number;
  state:"OPEN"|"INVESTIGATING"|"ACCEPTED"|"SNOOZED"|"COMPLETED"|"DISMISSED";snoozed_until?:string|null;
};
export type PortfolioHoldingHealth = {
  ticker:string;company:string;weight:number;market_value?:number|null;health_score:number;health_contribution:number;
  fundamental_score?:number|null;valuation_score?:number|null;momentum_score?:number|null;risk_contribution?:number|null;
  performance:{"1d"?:number|null;"1m"?:number|null;"1y"?:number|null};thesis_status:string;thesis_monitor_status:string;
  conviction?:number|null;data_confidence:string;data_quality:string;evidence_date?:string|null;change:number;active_action_count:number;
};
export type PortfolioOverview = {
  version:string;portfolio:{id:string;name:string};as_of:string;trigger:string;snapshot_id?:string;refresh_queued?:boolean;
  health:{score:number;band:string;confidence:string;coverage:number;delta?:number|null;components:Record<string,HealthComponent>;largest_positive?:string|null;largest_negative?:string|null};
  holdings:PortfolioHoldingHealth[];actions:PortfolioAction[];changes:Array<{type:string;title:string;delta?:number;occurred_at:string;ticker?:string;component?:string;status?:string}>;
  history:Array<{id:string;effective_at:string;trigger:string;score:number;band:string}>;warnings:string[];methodology:string;
};

type MacroFactor = {key:string;label:string;why_it_matters:string;as_of:string|null;evidence:Array<{series_id:string;value:number;change:number|null;date:string;source:string}>};
type DataStatus = {counts:Record<string,number>;freshness:Record<string,string|null>};
type PortfolioOption = {id:string|number;name:string;holdings:Array<unknown>};
type HeatSort = "priority"|"weight"|"health"|"risk"|"performance"|"change";

function pct(value?:number|null,digits=1,sign=true){return value==null?"—":`${sign&&value>=0?"+":""}${(value*100).toFixed(digits)}%`;}
function money(value?:number|null){return value==null?"—":new Intl.NumberFormat(undefined,{style:"currency",currency:"USD",notation:"compact",maximumFractionDigits:1}).format(value);}
function dateLabel(value?:string|null){if(!value)return"Awaiting data";const dateOnly=/^\d{4}-\d{2}-\d{2}$/.test(value);return new Date(dateOnly?`${value}T12:00:00`:value).toLocaleDateString(undefined,{month:"short",day:"numeric",year:"numeric"});}
function eventDate(value:string){return new Date(value).toLocaleString(undefined,{month:"short",day:"numeric",hour:"numeric",minute:"2-digit"});}
function scoreTone(score:number){return score>=70?"good":score>=55?"watch":"weak";}
function componentLabel(value:string){return value.replaceAll("_"," ").replace(/\b\w/g,letter=>letter.toUpperCase());}

export function TodayPage({loading,refreshing,briefing,overview,portfolios,selectedPortfolioId,hasSavedPortfolio,macroFactors,dataStatus,onRefresh,onRefreshOverview,onSelectPortfolio,onOverviewChange,onNavigate,onExplore,onPortfolio,request}:{
  loading:boolean;refreshing:boolean;briefing:TodayBriefing|null;overview:PortfolioOverview|null;portfolios:PortfolioOption[];selectedPortfolioId:string|number|null;
  hasSavedPortfolio:boolean;macroFactors:MacroFactor[];dataStatus:DataStatus;onRefresh:()=>void;onRefreshOverview:()=>void;onSelectPortfolio:(id:string)=>void;
  onOverviewChange:(overview:PortfolioOverview)=>void;onNavigate:(tab:Tab)=>void;onExplore:(view:ExploreView)=>void;onPortfolio:(view:PortfolioView)=>void;onAdvanced:(view:AdvancedView)=>void;
  request:(path:string,init?:RequestInit)=>Promise<Response>;
}){
  const [sort,setSort]=useState<HeatSort>("priority");
  const [busyAction,setBusyAction]=useState<string|null>(null);
  const [actionError,setActionError]=useState<string|null>(null);
  const portfolioExpected=hasSavedPortfolio||Boolean(briefing?.portfolio_context.available);
  const sortedHoldings=useMemo(()=>[...(overview?.holdings||[])].sort((left,right)=>{
    if(sort==="weight")return right.weight-left.weight;
    if(sort==="health")return left.health_score-right.health_score;
    if(sort==="risk")return Number(right.risk_contribution||0)-Number(left.risk_contribution||0);
    if(sort==="performance")return Number(right.performance["1y"]||0)-Number(left.performance["1y"]||0);
    if(sort==="change")return left.change-right.change;
    return right.active_action_count-left.active_action_count||left.health_score-right.health_score||right.weight-left.weight;
  }),[overview?.holdings,sort]);
  const activeActions=(overview?.actions||[]).filter(item=>!["COMPLETED","DISMISSED"].includes(item.state));

  const setActionState=async(item:PortfolioAction,state:PortfolioAction["state"])=>{
    setBusyAction(item.id);setActionError(null);
    try{
      const snoozedUntil=state==="SNOOZED"?new Date(Date.now()+24*60*60*1000).toISOString():null;
      const response=await request(`/portfolio-actions/${item.id}/state`,{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({state,snoozed_until:snoozedUntil,note:""})});
      if(!response.ok)throw new Error(await response.text());
      const updated=await response.json();
      if(overview)onOverviewChange({...overview,actions:overview.actions.map(action=>action.id===item.id?updated:action)});
    }catch{setActionError("That action state could not be saved. The recommendation remains unchanged.");}
    finally{setBusyAction(null);}
  };

  if(!portfolioExpected&&!loading)return <section className="workspace today-workspace"><div className="today-no-portfolio"><div><span>Portfolio intelligence</span><strong>Add or select a portfolio</strong><p>Save holdings once and EagleEyes will build a private, persistent health history for that portfolio.</p></div><button className="primary" onClick={()=>onPortfolio("holdings")}>Add portfolio →</button></div></section>;

  return <section className="workspace today-workspace portfolio-overview-workspace" aria-busy={loading}>
    <header className="portfolio-overview-header">
      <div><span className="kicker">Portfolio intelligence</span><h1>Is my portfolio healthy?</h1><p>A deterministic view of health, changes, and decisions. No language model changes these scores.</p></div>
      <div className="portfolio-overview-controls"><label>Portfolio<select value={selectedPortfolioId==null?"":String(selectedPortfolioId)} onChange={event=>onSelectPortfolio(event.target.value)}>{portfolios.map(item=><option key={String(item.id)} value={String(item.id)}>{item.name} · {item.holdings.length} holdings</option>)}</select></label><button className="secondary" disabled={!overview||refreshing} onClick={onRefreshOverview}>{refreshing?"Refreshing…":"Recalculate"}</button></div>
    </header>

    {!overview?<section className="panel overview-snapshot-loading"><strong>{loading?"Restoring the latest portfolio snapshot…":"Preparing the first portfolio snapshot…"}</strong><p>Stored evidence is being composed. Future visits load the saved result immediately.</p></section>:<>
      <section className={`portfolio-health-hero ${scoreTone(overview.health.score)}`}>
        <div className="health-score-primary"><span>Portfolio Health Score</span><strong>{overview.health.score.toFixed(0)}</strong><b>{overview.health.band}</b><small>{overview.health.delta==null?"First recorded baseline":`${overview.health.delta>=0?"▲":"▼"} ${Math.abs(overview.health.delta).toFixed(1)} since the previous nightly snapshot`}</small></div>
        <div className="health-component-grid">{Object.entries(overview.health.components).map(([key,item])=><article key={key} className={scoreTone(item.score)}><header><span>{componentLabel(key)}</span><strong>{item.score.toFixed(0)}</strong></header><div><i style={{width:`${item.score}%`}}/></div><small>{Math.round(item.weight*100)}% of score · {Math.round(item.coverage*100)}% covered</small></article>)}</div>
        <aside><span>Score confidence</span><strong>{overview.health.confidence}</strong><small>{Math.round(overview.health.coverage*100)}% weighted evidence coverage</small><p>Strongest: {componentLabel(overview.health.largest_positive||"unavailable")}<br/>Weakest: {componentLabel(overview.health.largest_negative||"unavailable")}</p><time>Calculated {dateLabel(overview.as_of)}</time></aside>
      </section>
      {overview.warnings.map(warning=><p className="briefing-warning" key={warning}>△ {warning}</p>)}

      <section className="portfolio-action-center"><div className="section-heading"><div><span className="kicker">Action Center</span><h2>What requires attention?</h2><p>Prioritized from portfolio exposure, materiality, thesis relevance, urgency, and evidence confidence.</p></div><small>{activeActions.length} active decision{activeActions.length===1?"":"s"}</small></div>{actionError&&<p className="briefing-warning" role="alert">△ {actionError}</p>}
        {activeActions.length?<div className="action-center-list">{activeActions.map((item,index)=><article key={item.id}><div className="action-rank"><b>{index+1}</b><span className={`action-type ${item.action.toLowerCase()}`}>{item.action}</span></div><div><header><div><h3>{item.title}</h3><small>{item.source.replaceAll("_"," ")} · {item.urgency.toLowerCase()} · {item.confidence.toLowerCase()} confidence</small></div><strong>{item.priority.toFixed(0)}</strong></header><p>{item.reason}</p>{item.affected_holdings.length>0&&<small>Affected: {item.affected_holdings.join(", ")} · {pct(item.portfolio_exposure,1,false)} exposure</small>}<details><summary>Recommended next step</summary><p>{item.suggested_next_step}</p><small>Evidence {dateLabel(item.evidence_date)} · follow up {dateLabel(item.follow_up_date)} · research decision only; no trade is submitted</small></details><footer><button disabled={busyAction===item.id} onClick={()=>void setActionState(item,"INVESTIGATING")}>Investigate</button><button disabled={busyAction===item.id} onClick={()=>void setActionState(item,"ACCEPTED")}>Accept plan</button><button disabled={busyAction===item.id} onClick={()=>void setActionState(item,"SNOOZED")}>Snooze</button>{["INVESTIGATING","ACCEPTED"].includes(item.state)&&<button disabled={busyAction===item.id} onClick={()=>void setActionState(item,"COMPLETED")}>Complete</button>}<button disabled={busyAction===item.id} onClick={()=>void setActionState(item,"DISMISSED")}>Dismiss</button><button onClick={()=>onNavigate("ask")}>Ask why →</button></footer></div></article>)}</div>:<div className="today-clear-state"><strong>No open portfolio actions</strong><p>Quiet is a valid state. EagleEyes will not manufacture a recommendation.</p></div>}
      </section>

      <section className="portfolio-change-center"><div className="section-heading"><div><span className="kicker">What changed</span><h2>Changes since the nightly baseline</h2><p>Score, component, holding, and thesis changes remain attached to their recorded snapshots.</p></div><small>{overview.history.length} snapshot{overview.history.length===1?"":"s"} retained</small></div>{overview.changes.length?<div className="portfolio-change-list">{overview.changes.map((item,index)=><article key={`${item.type}-${item.title}-${index}`}><span>{item.type.replaceAll("_"," ")}</span><strong>{item.title}</strong>{item.delta!=null&&<b className={item.delta>=0?"up":"down"}>{item.delta>=0?"▲":"▼"} {Math.abs(item.delta).toFixed(1)}</b>}<small>{dateLabel(item.occurred_at)}</small></article>)}</div>:<div className="today-clear-state"><strong>No material score change is recorded yet</strong><p>The first nightly snapshot establishes the comparison baseline.</p></div>}
      </section>

      <section className="holdings-heatmap"><div className="section-heading"><div><span className="kicker">Holdings heatmap</span><h2>Every holding, one control surface</h2><p>Scores are coverage-aware. Conviction appears only when the user explicitly recorded it.</p></div><label>Sort<select value={sort} onChange={event=>setSort(event.target.value as HeatSort)}><option value="priority">Action priority</option><option value="weight">Position size</option><option value="health">Weakest health</option><option value="risk">Risk contribution</option><option value="performance">One-year performance</option><option value="change">Largest deterioration</option></select></label></div><div className="heatmap-table" role="table"><div className="heatmap-row heatmap-head" role="row"><span>Holding</span><span>Position</span><span>Health</span><span>Fundamentals</span><span>Valuation</span><span>Momentum</span><span>Risk</span><span>1Y return</span><span>Thesis / conviction</span><span>Evidence</span></div>{sortedHoldings.map(item=><div className={`heatmap-row ${scoreTone(item.health_score)}`} role="row" key={item.ticker}><span><strong>{item.ticker}</strong><small>{item.company}</small>{item.active_action_count>0&&<b>{item.active_action_count} action{item.active_action_count===1?"":"s"}</b>}</span><span><strong>{pct(item.weight,1,false)}</strong><small>{money(item.market_value)}</small></span><span><strong>{item.health_score.toFixed(0)}</strong><small className={item.change>=0?"up":"down"}>{item.change===0?"No change":`${item.change>0?"▲":"▼"} ${Math.abs(item.change).toFixed(1)}`}</small></span><ScoreCell value={item.fundamental_score}/><ScoreCell value={item.valuation_score}/><ScoreCell value={item.momentum_score}/><span><strong>{item.risk_contribution==null?"—":pct(item.risk_contribution,1,false)}</strong><small>modeled share</small></span><span><strong>{pct(item.performance["1y"])}</strong><small>{pct(item.performance["1m"])} 1M</small></span><span><strong>{item.thesis_status.replaceAll("_"," ")}</strong><small>Conviction {item.conviction==null?"Not set":`${item.conviction}/5`}</small></span><span><strong>{item.data_confidence}</strong><small>{item.data_quality} data · {dateLabel(item.evidence_date)}</small></span></div>)}</div></section>
    </>}

    <div className="today-forward-grid"><section className="panel"><div className="panel-head"><div><span>Upcoming</span><h3>Events within the decision horizon</h3></div><button onClick={()=>onExplore("prediction-markets")}>Market expectations →</button></div>{briefing?.event_coverage&&<div className="event-coverage"><strong>{briefing.event_coverage.earnings_coverage_ratio==null?"General calendar":`${Math.round(briefing.event_coverage.earnings_coverage_ratio*100)}% holdings earnings coverage`}</strong>{briefing.event_coverage.earnings_missing_tickers.length>0&&<small>Missing validated dates: {briefing.event_coverage.earnings_missing_tickers.join(", ")}. Missing data is not interpreted as no event.</small>}</div>}<div className="today-event-list">{briefing?.upcoming_events.length?briefing.upcoming_events.slice(0,8).map(event=><a key={event.id} href={event.source_url||"#"} target={event.source_url?.startsWith("http")?"_blank":undefined} rel="noreferrer"><time>{eventDate(event.starts_at)}</time><div><strong>{event.title}</strong><small>{event.event_type.replaceAll("_"," ")} · {event.provider}{event.tickers?.length?` · ${event.tickers.join(", ")}`:""}</small></div></a>):<div className="today-clear-state"><strong>No validated upcoming events are stored</strong><p>EagleEyes does not invent event dates.</p></div>}</div></section><section className="panel today-ask-prompts"><div className="panel-head"><div><span>Ask EagleEyes</span><h3>Continue the investigation</h3></div></div><button onClick={()=>onNavigate("ask")}>Why is my health score {overview?.health.score.toFixed(0)||"unavailable"}? →</button><button onClick={()=>onNavigate("ask")}>Which holding needs attention first? →</button><button onClick={()=>onNavigate("ask")}>What changed since the last nightly snapshot? →</button></section></div>

    <details className="panel today-secondary-context"><summary>Secondary market and methodology context</summary><p>Broad prices and macro indicators provide context; they do not outrank verified thesis or portfolio evidence.</p><div className="today-secondary-grid"><section><h3>Broad market</h3>{briefing?.market_movement.filter(row=>row.group==="index").slice(0,5).map(row=><p key={row.ticker}><b>{row.ticker}</b><span>{pct(row.change_1d)} · {dateLabel(row.as_of)}</span></p>)}</section><section><h3>Macro indicators</h3>{briefing?.market_indicators.slice(0,5).map(row=><p key={row.key}><b>{row.label}</b><span>{row.value.toFixed(2)} {row.unit} · {dateLabel(row.as_of)}</span></p>)}</section><section><h3>Portfolio factors</h3>{briefing?.portfolio_relevance.slice(0,5).map(row=><p key={row.key}><b>{row.factor}</b><span>{row.relevance} · {row.direction}</span></p>)}</section></div><p>{overview?.methodology}</p><div className="today-coverage-row"><span>Prices {dataStatus.counts.price_bars||0}</span><span>Macro {dataStatus.counts.macro_observations||0}</span><span>Markets {dataStatus.counts.market_snapshots||0}</span><span>Health model {overview?.version||"preparing"}</span></div>{macroFactors.slice(0,3).map(factor=><small key={factor.key}>{factor.label} · {factor.why_it_matters}</small>)}</details>
  </section>;
}

function ScoreCell({value}:{value?:number|null}){return <span><strong>{value==null?"—":value.toFixed(0)}</strong><small>{value==null?"uncovered":value>=70?"supportive":value>=55?"mixed":"weak"}</small></span>;}

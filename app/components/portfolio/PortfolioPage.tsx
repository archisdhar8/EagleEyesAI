"use client";

import { type ComponentProps, useMemo, useState } from "react";
import { PortfolioWorkspace } from "../shared/workspace-implementations";
import { useRouteBudgetTelemetry } from "../../lib/frontend-budget-telemetry";

type Props=ComponentProps<typeof PortfolioWorkspace>;
const pct=(value?:number|null)=>value==null?"—":`${(value*100).toFixed(1)}%`;
const money=(value:number)=>new Intl.NumberFormat(undefined,{style:"currency",currency:"USD",notation:"compact",maximumFractionDigits:1}).format(value);

export function PortfolioPage(props:Props){
  const [editing,setEditing]=useState(false);
  useRouteBudgetTelemetry("portfolio");
  const sorted=useMemo(()=>[...props.holdings].filter(row=>row.ticker).sort((a,b)=>Number(b.weight||0)-Number(a.weight||0)),[props.holdings]);
  const totalValue=props.holdings.reduce((sum,row)=>sum+Number(row.market_value||0),0);
  const intelligence=props.diagnostics?.intelligence;
  const topRisks=props.diagnostics?.marginal_risk.positions.slice(0,3)||[];
  const missingTheses=intelligence?.thesis_health.holdings_without_thesis.slice(0,3)||[];
  const changes=intelligence?.upcoming_events.slice(0,3)||[];
  if(props.view==="analysis")return <div data-route-budget="portfolio"><PortfolioWorkspace {...props}/></div>;
  if(editing)return <div data-route-budget="portfolio"><div className="portfolio-mode-bar"><button className="secondary" onClick={()=>setEditing(false)}>← Portfolio overview</button><span>Holdings edit mode · {props.holdings.length} rows</span></div><PortfolioWorkspace {...props}/></div>;
  return <section className="workspace portfolio-summary-first" data-route-budget="portfolio">
    <div className="section-intro"><div><span className="kicker">Portfolio overview</span><h2>What needs attention in this portfolio?</h2><p>Understand the current state first. Editing and optimizer controls stay in their dedicated modes.</p></div><div className="portfolio-overview-actions"><button className="secondary" onClick={()=>setEditing(true)}>Edit holdings</button><button className="primary" onClick={()=>props.setView("analysis")}>Open Optimize →</button></div></div>
    <div className="portfolio-summary-hero"><article className="panel"><span>Total saved value</span><h3>{totalValue?money(totalValue):"Value unavailable"}</h3><p>{props.holdings.length} saved rows · {pct(props.total)} entered weight</p></article><article className="panel"><span>Portfolio health</span><h3>{intelligence?`${pct(intelligence.fundamental_health.coverage)} fundamental coverage`:"Health snapshot unavailable"}</h3><p>{intelligence?`${intelligence.thesis_health.active_thesis_count} active theses · ${intelligence.thesis_health.holdings_without_thesis.length} missing`:"No score is inferred without diagnostics."}</p></article><article className="panel"><span>Largest common dependency</span><h3>{intelligence?.economic_dependencies[0]?.factor.replaceAll("_"," ")||"Not mapped"}</h3><p>{intelligence?.economic_dependencies[0]?.mapped_portfolio_weight!=null?`${pct(intelligence.economic_dependencies[0].mapped_portfolio_weight)} mapped weight`:"Dependency coverage is partial or unavailable."}</p></article></div>
    <div className="portfolio-summary-columns"><section className="panel"><header><span>Top risks</span><h3>Modeled contributors</h3></header>{topRisks.length?topRisks.map(item=><p key={item.ticker}><strong>{item.ticker}</strong><span>{pct(item.risk_contribution)} modeled risk · {pct(item.portfolio_weight)} weight</span></p>):<p>No qualifying deterministic risk ranking is available.</p>}</section><section className="panel"><header><span>Opportunities / changes</span><h3>What may need review</h3></header>{changes.length?changes.map(item=><p key={item.id}><strong>{item.title}</strong><span>{item.affected_holdings.join(", ")} · {pct(item.portfolio_weight)}</span></p>):<p>No material upcoming portfolio event is stored.</p>}</section><section className="panel"><header><span>Actions requiring attention</span><h3>Thesis coverage</h3></header>{missingTheses.length?missingTheses.map(ticker=><p key={ticker}><strong>{ticker}</strong><span>No active thesis</span></p>):<p>No uncovered thesis item is recorded.</p>}</section></div>
    <section className="panel portfolio-largest-holdings"><header><div><span>Largest holdings</span><h3>Allocation and concentration</h3></div><button className="secondary" onClick={()=>setEditing(true)}>Manage holdings →</button></header>{sorted.slice(0,8).map(row=><div key={row.ticker}><strong>{row.ticker}</strong><span>{pct(row.weight)}</span><i><em style={{width:`${Math.min(100,Number(row.weight||0)*100)}%`}}/></i><small>{row.market_value==null?"Value unavailable":money(row.market_value)}</small></div>)}</section>
    <div className="portfolio-summary-columns"><article className="panel"><span>Performance</span><h3>{props.performance?"Latest reconstructed performance available":"Performance unavailable"}</h3><p>Actual account performance remains separate from hypothetical current-weight reconstruction.</p></article><article className="panel"><span>Thesis coverage</span><h3>{intelligence?`${intelligence.thesis_health.active_thesis_count} of ${intelligence.thesis_health.holding_count} holdings`:"Unavailable"}</h3><p>Missing theses remain explicit and are not treated as neutral.</p></article></div>
  </section>;
}

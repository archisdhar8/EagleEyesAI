"use client";

import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { DecisionLab } from "../portfolio/DecisionLab";
import type { Goal, Holding, Profile } from "../workspaces";
import type { DecisionJournalWorkspace, DecisionRetrospective, DecisionType, DecisionsWorkspace, InvestmentThesis, ThesisAssumption, ThesisFactor, ThesisMonitorResult, MonitoringEvidence } from "./contracts";
import { EvidenceTrust } from "../shared/EvidenceTrust";
import { GuidedThesisEditor, type ThesisRelationship } from "./GuidedThesisEditor";

const EMPTY: InvestmentThesis = {
  ticker: "", summary: "", base_case: "", bull_case: "", bear_case: "", investment_horizon: "long",
  review_date: null, status: "DRAFT", source_context: {}, assumptions: [], factors: [],
};
type DecisionPersonalization={version:string;explicit:Record<string,unknown>;accepted:Record<string,{label?:string;basis?:string;sample_size?:number}>;inferred:Array<{key:string;label:string;basis:string;sample_size:number;value:string}>;dismissed:string[];minimum_reviewed_decisions:number;reviewed_decisions:number};
type SecurityResearch={ticker:string;company?:string;sector?:string;industry?:string;evidence_bucket?:string;bucket_explanation?:string;portfolio_fit?:string;what_would_change_the_view?:string;thesis_risks?:string[];catalysts?:Array<{title:string;source_url?:string|null}>;market_statistics?:Record<string,number|null|string>;fundamental_statistics?:Record<string,number|null|string>;freshness?:{status?:string;price_as_of?:string|null;fundamentals_as_of?:string|null;coverage?:string};strengths?:Array<{label:string;evidence:number}>;weaknesses?:Array<{label:string;evidence:number}>};
type SecurityIntelligence={research:SecurityResearch|null;earnings:Record<string,unknown>|null;markets:Array<Record<string,unknown>>;warnings:string[]};

async function readJson<T>(response: Response): Promise<T> {
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || "EagleEyes could not complete that request.");
  return body as T;
}

function dateLabel(value?: string | null) {
  if (!value) return "No review date";
  return new Date(`${value.slice(0, 10)}T12:00:00`).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function money(value?: number | null) {
  return value == null ? "Price unavailable" : value.toLocaleString(undefined, { style: "currency", currency: "USD" });
}

function monitorValue(value: MonitoringEvidence["current_value"], unit?: string | null) {
  if (value == null) return "Missing";
  if (typeof value !== "number") return String(value);
  if (unit === "ratio" || unit === "probability") return `${(value * 100).toFixed(1)}%`;
  return Number.isInteger(value) ? String(value) : value.toFixed(2);
}

function MonitorEvidenceRow({item}:{item:MonitoringEvidence}) {
  const market=item.metadata?.current_metadata;
  return <details className="monitor-evidence-row"><summary><span>{item.evidence_type.replaceAll("_", " ")} · {item.materiality}</span><strong>{item.label}</strong><small>{monitorValue(item.previous_value,item.unit)} → {monitorValue(item.current_value,item.unit)}{item.percentage_point_change!=null?` · ${item.percentage_point_change>0?"+":""}${item.percentage_point_change.toFixed(1)} pts`:""}</small></summary><p>{item.relationship} · {item.freshness.toLowerCase()} · {item.evidence_quality.toLowerCase()} quality</p>{item.evidence_type==="PREDICTION_MARKET"&&<small>Market quality {market?.market_quality||"unavailable"} · volume {market?.volume??"unavailable"} · spread {market?.spread??"unavailable"} · resolves {dateLabel(market?.resolution_date)}</small>}<small>{item.source} · {item.methodology || "Method unavailable"}</small>{item.source_references.map(url => <a key={url} href={url} target="_blank" rel="noreferrer">View evidence →</a>)}</details>;
}

export function DecisionsPage({
  request, holdings, profile, goals, onOpenPortfolio,
}: {
  request: (path: string, init?: RequestInit) => Promise<Response>;
  holdings: Holding[];
  profile: Profile;
  goals: Goal[];
  onOpenPortfolio: () => void;
}) {
  const [workspace, setWorkspace] = useState<DecisionsWorkspace | null>(null);
  const [form, setForm] = useState<InvestmentThesis>(EMPTY);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [drafting, setDrafting] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [decisionType, setDecisionType] = useState<DecisionType>("WATCH");
  const [confidence, setConfidence] = useState("");
  const [decisionNotes, setDecisionNotes] = useState("");
  const [expectedOutcome, setExpectedOutcome] = useState("");
  const [reviewHorizon, setReviewHorizon] = useState("90");
  const [benchmark, setBenchmark] = useState("SPY");
  const [journal, setJournal] = useState<DecisionJournalWorkspace | null>(null);
  const [journalReview, setJournalReview] = useState<DecisionRetrospective | null>(null);
  const [journalDecisionId, setJournalDecisionId] = useState<string | null>(null);
  const [journalHorizon, setJournalHorizon] = useState("90D");
  const [retrospectiveNotes, setRetrospectiveNotes] = useState("");
  const [journalLoading, setJournalLoading] = useState(false);
  const [monitor, setMonitor] = useState<ThesisMonitorResult | null>(null);
  const [monitorLoading, setMonitorLoading] = useState(false);
  const [monitorError, setMonitorError] = useState("");
  const [reviewHistory, setReviewHistory] = useState<Array<{id:string;reviewed_at:string;overall_status:string;thesis_version:number;monitoring_result:{counts?:Record<string,number>}}>>([]);
  const [personalization,setPersonalization]=useState<DecisionPersonalization|null>(null);
  const [guidedStage,setGuidedStage]=useState<"setup"|"review">("setup");
  const [relationship,setRelationship]=useState<ThesisRelationship>("CONSIDER");
  const [personalReason,setPersonalReason]=useState("");
  const [reviewConfirmed,setReviewConfirmed]=useState(false);
  const [selectedTicker,setSelectedTicker]=useState("");
  const [securitySearch,setSecuritySearch]=useState("");
  const [intelligence,setIntelligence]=useState<SecurityIntelligence>({research:null,earnings:null,markets:[],warnings:[]});
  const [intelligenceLoading,setIntelligenceLoading]=useState(false);
  const [caseTab,setCaseTab]=useState<"base"|"bull"|"bear">("base");
  const autoDraftedTickers=useRef(new Set<string>());

  const load = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const [raw,journalData,personalizationData] = await Promise.all([
        readJson<Partial<DecisionsWorkspace>>(await request("/decisions/workspace")),
        readJson<DecisionJournalWorkspace>(await request("/decision-journal")),
        readJson<DecisionPersonalization>(await request("/personalization")),
      ]);
      const data: DecisionsWorkspace = {
        active_theses: Array.isArray(raw.active_theses) ? raw.active_theses : [],
        recent_decisions: Array.isArray(raw.recent_decisions) ? raw.recent_decisions : [],
        needs_thesis: Array.isArray(raw.needs_thesis) ? raw.needs_thesis : [],
        review_dates: Array.isArray(raw.review_dates) ? raw.review_dates : [],
        contexts: raw.contexts || {},
      };
      const searchParams = typeof window === "undefined" ? new URLSearchParams() : new URLSearchParams(window.location.search);
      const queryTicker = searchParams.get("ticker")?.toUpperCase() || "";
      setWorkspace(data);
      setSelectedTicker(current=>current||queryTicker||holdings[0]?.ticker?.toUpperCase()||profile.watchlist[0]?.toUpperCase()||data.active_theses[0]?.ticker||"");
      setJournal({version:journalData.version||"decision-journal-v1",recent_decisions:Array.isArray(journalData.recent_decisions)?journalData.recent_decisions:[],ready_for_review:Array.isArray(journalData.ready_for_review)?journalData.ready_for_review:[],completed_retrospectives:Array.isArray(journalData.completed_retrospectives)?journalData.completed_retrospectives:[],patterns:{reviewed_decisions:journalData.patterns?.reviewed_decisions||0,minimum_sample:journalData.patterns?.minimum_sample||5,status:journalData.patterns?.status||"INSUFFICIENT_SAMPLE",patterns:Array.isArray(journalData.patterns?.patterns)?journalData.patterns.patterns:[]},forecast_calibration:{sample_size:journalData.forecast_calibration?.sample_size||0,brier_score:journalData.forecast_calibration?.brier_score??null,status:journalData.forecast_calibration?.status||"INSUFFICIENT_SAMPLE",message:journalData.forecast_calibration?.message||"Resolved forecasts are insufficient for calibration.",buckets:Array.isArray(journalData.forecast_calibration?.buckets)?journalData.forecast_calibration.buckets:[],methodology:journalData.forecast_calibration?.methodology||"No calibration result without resolved forecasts."}});
      setPersonalization({version:personalizationData.version||"decision-preferences-v1",explicit:personalizationData.explicit||{},accepted:personalizationData.accepted||{},inferred:Array.isArray(personalizationData.inferred)?personalizationData.inferred:[],dismissed:Array.isArray(personalizationData.dismissed)?personalizationData.dismissed:[],minimum_reviewed_decisions:personalizationData.minimum_reviewed_decisions||5,reviewed_decisions:personalizationData.reviewed_decisions||0});
      const queryDecision = searchParams.get("decision")?.toUpperCase() as DecisionType | null;
      if(queryDecision&&["WATCH","BUY","ADD","HOLD","REDUCE","SELL","AVOID"].includes(queryDecision))setDecisionType(queryDecision);
      const selected = data.active_theses.find(item => item.id === selectedId)
        || data.active_theses.find(item => item.ticker === queryTicker);
      if (selected) { setSelectedId(selected.id || null); setForm(selected);setGuidedStage("review");setReviewConfirmed(true);setRelationship((selected.source_context?.relationship as ThesisRelationship)||"CONSIDER");setPersonalReason(String(selected.source_context?.user_reason||"")); }
      else if (queryTicker && !selectedId) setForm({ ...EMPTY, ticker: queryTicker });
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not load decisions."); }
    finally { setLoading(false); }
  }, [request, selectedId, holdings, profile.watchlist]);

  const securityUniverse=useMemo(()=>{
    const source=[...holdings.map(item=>({ticker:item.ticker.toUpperCase(),source:"Holding"})),...profile.watchlist.map(ticker=>({ticker:ticker.toUpperCase(),source:"Watchlist"})),...(workspace?.active_theses||[]).map(item=>({ticker:item.ticker,source:"Thesis"})),...(workspace?.needs_thesis||[]).map(item=>({ticker:item.ticker,source:item.source==="holding"?"Holding":"Watchlist"}))];
    const unique=new Map<string,{ticker:string;source:string}>();source.forEach(item=>{if(item.ticker&&!unique.has(item.ticker))unique.set(item.ticker,item);});
    const needle=securitySearch.trim().toUpperCase();return [...unique.values()].filter(item=>!needle||item.ticker.includes(needle)).sort((a,b)=>a.ticker.localeCompare(b.ticker));
  },[holdings,profile.watchlist,workspace,securitySearch]);

  useEffect(()=>{
    if(!selectedTicker||!workspace)return;
    const saved=workspace.active_theses.find(item=>item.ticker===selectedTicker);
    if(saved)selectThesis(saved);else startThesis(selectedTicker);
  // Selection intentionally resets the editor to that security's saved state.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  },[selectedTicker,workspace]);

  useEffect(()=>{
    if(!selectedTicker)return;
    let active=true;setIntelligenceLoading(true);setIntelligence({research:null,earnings:null,markets:[],warnings:[]});
    void Promise.allSettled([
      request(`/research/search?q=${encodeURIComponent(selectedTicker)}&limit=1`).then(readJson<{results?:SecurityResearch[]}>),
      request(`/research/${selectedTicker}/earnings`).then(readJson<Record<string,unknown>>),
      request(`/forecasting/securities/${selectedTicker}/markets`).then(readJson<{markets?:Array<Record<string,unknown>>;warnings?:string[]}>),
    ]).then(results=>{if(!active)return;const research=results[0].status==="fulfilled"?results[0].value.results?.find(item=>item.ticker===selectedTicker)||null:null;const earnings=results[1].status==="fulfilled"?results[1].value:null;const marketPayload=results[2].status==="fulfilled"?results[2].value:null;const warnings=results.flatMap((item,index)=>item.status==="rejected"?[`${["Stored research","Earnings","Prediction markets"][index]}: ${item.reason instanceof Error?item.reason.message:"unavailable"}`]:[]);setIntelligence({research,earnings,markets:marketPayload?.markets||[],warnings:[...warnings,...(marketPayload?.warnings||[])]});}).finally(()=>{if(active)setIntelligenceLoading(false);});
    return()=>{active=false};
  },[request,selectedTicker]);

  useEffect(() => {
    const task = window.setTimeout(() => { void load(); }, 0);
    return () => window.clearTimeout(task);
  }, [load]);

  const loadMonitor = useCallback(async (thesisId: string) => {
    setMonitorLoading(true); setMonitorError("");
    try { const [status,history]=await Promise.all([readJson<ThesisMonitorResult>(await request(`/theses/${thesisId}/monitor`)),readJson<typeof reviewHistory>(await request(`/theses/${thesisId}/reviews`))]);setMonitor(status);setReviewHistory(history); }
    catch (reason) { setMonitor(null); setMonitorError(reason instanceof Error ? reason.message : "Thesis monitoring is unavailable."); }
    finally { setMonitorLoading(false); }
  }, [request]);

  useEffect(() => { const task=window.setTimeout(()=>{if(selectedId)void loadMonitor(selectedId);else setMonitor(null);},0);return()=>window.clearTimeout(task); }, [selectedId, loadMonitor]);

  const selectThesis = (thesis: InvestmentThesis) => {
    setSelectedId(thesis.id || null); setForm(thesis);setGuidedStage("review");setReviewConfirmed(true);setRelationship((thesis.source_context?.relationship as ThesisRelationship)||"CONSIDER");setPersonalReason(String(thesis.source_context?.user_reason||""));setNotice(""); setError("");
  };
  const startThesis = (ticker = "") => {
    const owned=holdings.some(item=>item.ticker.toUpperCase()===ticker.toUpperCase());
    setSelectedId(null); setForm({ ...EMPTY, ticker });setGuidedStage("setup");setReviewConfirmed(false);setRelationship(owned?"OWN":"CONSIDER");setPersonalReason("");setNotice(""); setError("");
  };

  const markReviewed = async () => {
    if (!selectedId) return;
    setSaving(true); setError("");
    try { const result = await readJson<{reviewed_at:string}>(await request(`/theses/${selectedId}/reviews`, {method:"POST"})); setNotice(`Thesis reviewed ${dateLabel(result.reviewed_at)}. This is now the next evidence baseline.`); await loadMonitor(selectedId); await load(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Could not mark the thesis reviewed."); }
    finally { setSaving(false); }
  };
  const updateInference=async(item:DecisionPersonalization["inferred"][number],action:"accept"|"edit"|"dismiss")=>{if(!personalization)return;const accepted={...personalization.accepted};let dismissed=[...personalization.dismissed];if(action==="dismiss")dismissed=Array.from(new Set([...dismissed,item.key]));else{const edited=action==="edit"?window.prompt("Edit this preference before accepting it",item.label):item.label;if(!edited)return;accepted[item.key]={...item,label:edited};}setSaving(true);try{const next=await readJson<DecisionPersonalization>(await request("/personalization",{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({explicit:personalization.explicit,accepted,dismissed})}));setPersonalization(next);setNotice("Decision preference updated. Accepted preferences may reorder related evidence, with the reason shown in Today.");}catch(reason){setError(reason instanceof Error?reason.message:"Could not update the preference.");}finally{setSaving(false);}};

  const draft = async () => {
    if (!form.ticker.trim()) { setError("Enter a ticker before drafting from research."); return; }
    setDrafting(true); setError(""); setNotice("");
    try {
      const result = await readJson<{ draft: InvestmentThesis; saved: false; warning: string }>(
        await request(`/theses/drafts/${form.ticker.trim().toUpperCase()}`, { method: "POST" }),
      );
      const suggestedAssumptions=(result.draft.assumptions||[]).map(item=>({...item,evidence_mapping:{...item.evidence_mapping,origin:"EAGLEEYES_SUGGESTION"}}));
      const suggestedFactors=(result.draft.factors||[]).map(item=>({...item,evidence_mapping:{...item.evidence_mapping,origin:"EAGLEEYES_SUGGESTION"}}));
      setForm({ ...result.draft, ticker: form.ticker.trim().toUpperCase(),investment_horizon:form.investment_horizon,
        assumptions:suggestedAssumptions,factors:suggestedFactors,source_context:{...result.draft.source_context,relationship,user_reason:personalReason,confirmation_state:"PENDING"} });
      setSelectedId(null);
      setGuidedStage("review");setReviewConfirmed(false);
      setNotice(result.warning);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Draft unavailable."); }
    finally { setDrafting(false); }
  };

  useEffect(()=>{
    if(!selectedTicker||intelligenceLoading||selectedId||form.summary||drafting||autoDraftedTickers.current.has(selectedTicker))return;
    autoDraftedTickers.current.add(selectedTicker);
    void draft();
  // The selected ticker is drafted once; draft intentionally reads the latest setup state.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  },[selectedTicker,intelligenceLoading,selectedId,form.summary,drafting]);

  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (!form.ticker.trim() || !form.summary.trim()) { setError("Ticker and thesis summary are required."); return; }
    if(!reviewConfirmed){setError("Review and confirm the thesis before saving it as your belief.");return;}
    setSaving(true); setError(""); setNotice("");
    try {
      const response = await request(selectedId ? `/theses/${selectedId}` : "/theses", {
        method: selectedId ? "PUT" : "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...form, ticker: form.ticker.toUpperCase(),
          source_context:{...form.source_context,relationship,user_reason:personalReason,confirmation_state:"USER_CONFIRMED",confirmed_at:new Date().toISOString()},
          assumptions:form.assumptions.map(item=>({...item,evidence_mapping:{...item.evidence_mapping,confirmation_state:"USER_CONFIRMED"}})),
          factors:form.factors.map(item=>({...item,evidence_mapping:{...item.evidence_mapping,confirmation_state:"USER_CONFIRMED"}})),
          change_note: selectedId ? "User reviewed and confirmed guided thesis update" : "User reviewed and confirmed original thesis" }),
      });
      const saved = await readJson<InvestmentThesis>(response);
      setSelectedId(saved.id || null); setForm(saved); setNotice(`Thesis saved as version ${saved.current_version}.`);
      await load();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not save thesis."); }
    finally { setSaving(false); }
  };

  const recordDecision = async (event: FormEvent) => {
    event.preventDefault();
    if (!form.ticker.trim()) { setError("Choose a security before recording a decision."); return; }
    setSaving(true); setError(""); setNotice("");
    try {
      await readJson(await request("/investment-decisions", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ticker: form.ticker.toUpperCase(), thesis_id: selectedId, decision_type: decisionType,
          user_confidence: confidence ? Number(confidence) : null, notes: decisionNotes,
          investment_horizon: form.investment_horizon, portfolio_context: { source: "decisions_workspace" },
          expected_outcome: expectedOutcome, review_horizon_days: Number(reviewHorizon), comparison_benchmark: benchmark,
        }),
      }));
      setDecisionNotes(""); setExpectedOutcome(""); setConfidence(""); setNotice(`${decisionType} recorded with an immutable context snapshot.`);
      await load();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not record decision."); }
    finally { setSaving(false); }
  };

  const updateAssumption = (index: number, patch: Partial<ThesisAssumption>) => setForm(value => ({
    ...value, assumptions: value.assumptions.map((item, itemIndex) => itemIndex === index ? { ...item, ...patch } : item),
  }));
  const openJournalReview = async (decisionId:string, horizon=journalHorizon) => {
    setJournalDecisionId(decisionId); setJournalLoading(true); setError("");
    try { setJournalReview(await readJson<DecisionRetrospective>(await request(`/investment-decisions/${decisionId}/retrospective?horizon=${horizon}`))); }
    catch(reason){setJournalReview(null);setError(reason instanceof Error?reason.message:"Could not build the retrospective.");}
    finally{setJournalLoading(false);}
  };
  useEffect(()=>{const decisionId=typeof window==="undefined"?null:new URLSearchParams(window.location.search).get("journal");if(journal&&decisionId&&!journalDecisionId)void openJournalReview(decisionId);},[journal,journalDecisionId]);
  const completeJournalReview = async () => {
    if(!journalDecisionId)return; setSaving(true);setError("");
    try { await readJson(await request(`/investment-decisions/${journalDecisionId}/retrospectives`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({horizon:journalHorizon,notes:retrospectiveNotes})}));setNotice("Retrospective saved. Earlier reviews remain unchanged.");setRetrospectiveNotes("");await load(); }
    catch(reason){setError(reason instanceof Error?reason.message:"Could not save the retrospective.");}
    finally{setSaving(false);}
  };
  const updateFactor = (index: number, patch: Partial<ThesisFactor>) => setForm(value => ({...value, factors: value.factors.map((item, itemIndex) => itemIndex === index ? { ...item, ...patch } : item)}));
  const factors = {
    CATALYST: form.factors.map((item, index) => ({ item, index })).filter(({ item }) => item.factor_type === "CATALYST"),
    RISK: form.factors.map((item, index) => ({ item, index })).filter(({ item }) => item.factor_type === "RISK"),
    BREAKER: form.factors.map((item, index) => ({ item, index })).filter(({ item }) => item.factor_type === "BREAKER"),
  };

  const chooseSecurity=(ticker:string)=>{const normalized=ticker.trim().toUpperCase();if(!/^[A-Z][A-Z0-9.-]{0,9}$/.test(normalized)){setError("Enter a valid stock or ETF ticker.");return;}setError("");setSelectedTicker(normalized);setSecuritySearch("");window.history.replaceState({},"",`/decisions?ticker=${encodeURIComponent(normalized)}`);};
  const research=intelligence.research;
  const statistics=research?.market_statistics||{};
  const fundamentals=research?.fundamental_statistics||{};
  const scenarioText=caseTab==="bull"?form.bull_case:caseTab==="bear"?form.bear_case:form.base_case;
  const scenarioHeading=caseTab==="bull"?"What would need to go right":caseTab==="bear"?"What could break the thesis":`${research?.company||selectedTicker} base case`;
  const scenarioEvidence=caseTab==="bull"
    ? (factors.CATALYST.length?factors.CATALYST.map(({item})=>item.description):research?.catalysts?.map(item=>item.title)||[])
    : caseTab==="bear"
      ? ([...factors.RISK,...factors.BREAKER].length?[...factors.RISK,...factors.BREAKER].map(({item})=>item.description):research?.thesis_risks||[])
      : form.assumptions.map(item=>item.description);
  const relationshipLabel:Record<ThesisRelationship,string>={OWN:"I own it",CONSIDER:"I’m considering it",WATCH:"I’m watching it",AVOID:"I’m avoiding it"};

  return <section className="workspace decisions-workspace">
    <div className="section-intro decisions-intro">
      <div><span className="kicker">Persistent investment memory</span><h2>Remember the decision, the thesis, and what would invalidate it.</h2><p>Company quality and portfolio fit remain separate. Watching—or doing nothing—is a valid recorded decision.</p></div>
      <div className="section-actions"><button className="secondary" onClick={onOpenPortfolio}>Review portfolio</button><button className="primary" onClick={() => startThesis()}>New thesis</button></div>
    </div>

    {loading && <div className="panel decisions-empty"><h3>Loading your decision memory…</h3></div>}
    {error && <div className="validation-list" role="alert"><span>{error}</span><button className="secondary" onClick={() => void load()}>Retry</button></div>}
    {notice && <div className="panel decision-notice" role="status"><p>{notice}</p></div>}

    {!loading&&workspace&&<section className="security-decision-cockpit" aria-label="Security decision dashboard">
      <aside className="panel security-picker">
        <header><span>Choose a security</span><h3>Holdings and watchlist</h3><p>Select a saved name or search any supported ticker.</p></header>
        <form onSubmit={event=>{event.preventDefault();chooseSecurity(securitySearch);}}><input aria-label="Search holdings or ticker" value={securitySearch} onChange={event=>setSecuritySearch(event.target.value.toUpperCase())} placeholder="Search AAPL or company ticker"/><button className="secondary">Open{securitySearch?` ${securitySearch}`:""}</button></form>
        <div className="security-picker-list">{securityUniverse.length?securityUniverse.map(item=><button key={item.ticker} className={selectedTicker===item.ticker?"selected":""} onClick={()=>chooseSecurity(item.ticker)}><strong>{item.ticker}</strong><span>{item.source}</span><small>{workspace.contexts[item.ticker]?.has_open_thesis?"Saved thesis":workspace.contexts[item.ticker]?.latest_decision||"Needs review"}</small></button>):<p>No saved name matches. Press Open to research this ticker.</p>}</div>
      </aside>

      <div className="security-report">
        <section className="panel security-report-hero"><div><span>{research?.sector||"Security decision report"}{research?.industry?` · ${research.industry}`:""}</span><h2>{selectedTicker||"Choose a security"} <small>{research?.company||""}</small></h2><p>{research?.bucket_explanation||"Stored evidence will appear here without creating an investment conclusion."}</p></div><div className="relationship-control"><span>How does it fit today?</span><div>{(["OWN","CONSIDER","WATCH","AVOID"] as ThesisRelationship[]).map(value=><button key={value} className={relationship===value?"active":""} onClick={()=>setRelationship(value)}>{relationshipLabel[value]}</button>)}</div></div></section>

        {intelligenceLoading?<section className="panel report-loading"><span/>Loading the stored evidence report…</section>:<>
          <div className="security-evidence-grid">
            <article className="panel"><span>Stored research</span><strong>{research?.evidence_bucket||"No stored coverage"}</strong><p>{research?.portfolio_fit||"Portfolio fit has not been calculated for this security."}</p><small>{research?.freshness?.coverage||"Unknown"} coverage · {research?.freshness?.status||"unknown"} freshness</small></article>
            <article className="panel"><span>Price and risk</span><strong>{typeof statistics.last_price==="number"?money(statistics.last_price):"Price unavailable"}</strong><p>{typeof statistics.return_1y==="number"?`${(statistics.return_1y*100).toFixed(1)}% one-year return`:"One-year return unavailable"} · {typeof statistics.annualized_volatility==="number"?`${(statistics.annualized_volatility*100).toFixed(1)}% volatility`:"volatility unavailable"}</p><small>{research?.freshness?.price_as_of?`Through ${dateLabel(research.freshness.price_as_of)}`:"No verified price date"}</small></article>
            <article className="panel"><span>Reported fundamentals</span><strong>{typeof fundamentals.revenue==="number"?money(fundamentals.revenue):"Revenue unavailable"}</strong><p>{typeof fundamentals.net_margin==="number"?`${(fundamentals.net_margin*100).toFixed(1)}% net margin`:"Net margin unavailable"} · {typeof fundamentals.free_cash_flow==="number"?`${money(fundamentals.free_cash_flow)} FCF`:"FCF unavailable"}</p><small>{String(fundamentals.fiscal_period||"")} {String(fundamentals.period_end||research?.freshness?.fundamentals_as_of||"No verified period")}</small></article>
            <article className="panel"><span>Earnings and expectations</span><strong>{String(intelligence.earnings?.status||"Unavailable").replaceAll("_"," ")}</strong><p>{intelligence.earnings&&typeof intelligence.earnings.actual_vs_expectations==="object"?"Reported results and provider-supplied expectations are stored.":"No provider-supplied consensus is stored for this period."}</p><small>Missing consensus is never inferred.</small></article>
          </div>

          <section className="panel forward-signals"><header><div><span>Forward-looking indicators</span><h3>Earnings events and prediction markets</h3></div><small>{intelligence.markets.length} linked market{intelligence.markets.length===1?"":"s"}</small></header>{intelligence.markets.length?<div>{intelligence.markets.slice(0,6).map((market,index)=>{const probability=(market.probability as Record<string,unknown>|undefined)?.probability;return <article key={String(market.market_id||index)}><strong>{String(market.title||"Linked prediction market")}</strong><span>{typeof probability==="number"?`${(probability*100).toFixed(0)}% market-implied probability`:"Probability unavailable"}</span><small>{String(market.provider||"Stored provider")} · market-implied, not an EagleEyes forecast</small></article>})}</div>:<p>No stored Polymarket, Kalshi, or other prediction market is reliably linked to {selectedTicker}. This remains missing evidence.</p>}</section>

          <section className="panel scenario-report"><header><div><span>One-page thesis report</span><h3>Evidence-built scenarios</h3><small>Bull, base, and bear cases are populated automatically from stored research, then remain editable.</small></div>{drafting&&<span className="scenario-building">Refreshing stored evidence…</span>}</header><div className="scenario-tabs" role="tablist">{(["bear","base","bull"] as const).map(value=><button role="tab" aria-selected={caseTab===value} className={caseTab===value?"active":""} onClick={()=>setCaseTab(value)} key={value}><strong>{value[0].toUpperCase()+value.slice(1)}</strong><small>{(value==="bull"?form.bull_case:value==="bear"?form.bear_case:form.base_case)?"Ready":"Building"}</small></button>)}</div><article className={`scenario-copy ${caseTab}`}><span>{caseTab} case</span><h4>{scenarioHeading}</h4><p>{scenarioText||"The evidence-built case is loading. You can still add or edit your own view below."}</p><section className="scenario-evidence"><strong>{caseTab==="bull"?"Upside evidence":caseTab==="bear"?"Risks and invalidation":"Conditions that must remain true"}</strong>{scenarioEvidence.length?scenarioEvidence.slice(0,4).map((item,index)=><small key={`${item}-${index}`}>{item}</small>):<small>No company-specific evidence is stored for this case yet.</small>}</section></article>
            <details className="report-editor"><summary>{form.summary?"Edit thesis and monitoring rules":"Create and review a thesis"}</summary><form onSubmit={save}><GuidedThesisEditor form={form} setForm={setForm} selected={Boolean(selectedId)} drafting={drafting} saving={saving} stage={guidedStage} setStage={setGuidedStage} relationship={relationship} setRelationship={setRelationship} personalReason={personalReason} setPersonalReason={setPersonalReason} reviewConfirmed={reviewConfirmed} setReviewConfirmed={setReviewConfirmed} onDraft={draft}/></form></details>
          </section>

          <form className="panel decision-capture" onSubmit={recordDecision}><header><div><span>Decision under review</span><h3>What are you considering for {selectedTicker}?</h3></div><small>Recording is optional and creates an immutable journal entry.</small></header><div className="decision-capture-actions">{(["WATCH","BUY","ADD","HOLD","REDUCE","SELL","AVOID"] as DecisionType[]).map(value=><button type="button" key={value} className={decisionType===value?"active":""} onClick={()=>setDecisionType(value)}>{value}</button>)}</div><div className="decision-capture-fields"><label>Expected outcome<textarea value={expectedOutcome} onChange={event=>setExpectedOutcome(event.target.value)} placeholder="What do you expect by the review date?"/></label><label>Reasoning now<textarea value={decisionNotes} onChange={event=>setDecisionNotes(event.target.value)} placeholder="Why this action—or no action—now?"/></label></div><footer><small>Append-only journal · Price unavailable remains disclosed when no observation exists.</small><button className="primary" disabled={saving}>{saving?"Recording…":`Record ${decisionType}`}</button></footer></form>

          <section className="panel unified-assistant-callout"><div><span>Questions live in one place</span><h3>Discuss {selectedTicker} in Ask EagleEyes.</h3><p>The main assistant receives the ticker, saved thesis, portfolio context, earnings, and prediction-market evidence through its routing layer.</p></div><a className="primary" href={`/ask?ticker=${encodeURIComponent(selectedTicker)}&prompt=${encodeURIComponent(`Review my ${selectedTicker} decision report. What evidence most strengthens or weakens the thesis?`)}`}>Ask about {selectedTicker} →</a></section>
          {!!intelligence.warnings.length&&<div className="validation-list">{intelligence.warnings.map(item=><span key={item}>{item}</span>)}</div>}
        </>}
      </div>
    </section>}

    {!loading && workspace && <>
      <div className="decision-memory-grid">
        <article className="panel"><span>Active theses</span><h3>{workspace.active_theses.length}</h3><p>{workspace.active_theses.length ? "Draft, active, or under review" : "No saved thesis yet"}</p></article>
        <article className="panel"><span>Recent decisions</span><h3>{workspace.recent_decisions.length}</h3><p>Append-only decision observations</p></article>
        <article className="panel"><span>Needs a thesis</span><h3>{workspace.needs_thesis.length}</h3><p>Holdings and watchlist names only</p></article>
        <article className="panel"><span>Scheduled reviews</span><h3>{workspace.review_dates.length}</h3><p>Dates you chose—not generated alerts</p></article>
      </div>

      <div className="decision-workbench">
        <aside className="panel decision-index">
          <h3>Active theses</h3>
          {workspace.active_theses.length === 0 && <p>No active thesis. Holdings remain valid without one.</p>}
          {workspace.active_theses.map(item => <button key={item.id} className={selectedId === item.id ? "selected" : ""} onClick={() => selectThesis(item)}><strong>{item.ticker}</strong><span>{item.monitor_status?.overall_status?.replaceAll("_", " ") || `${item.status.replaceAll("_", " ")} · not reviewed`}</span><small>{item.monitor_status?.reviewed_at?`Reviewed ${dateLabel(item.monitor_status.reviewed_at)}`:dateLabel(item.review_date)}</small></button>)}
          <h3>Consider adding context</h3>
          {workspace.needs_thesis.slice(0, 12).map(item => <button key={`${item.source}-${item.ticker}`} onClick={() => startThesis(item.ticker)}><strong>{item.ticker}</strong><span>{item.source}</span><small>Create an optional thesis →</small></button>)}
        </aside>

        <div className="decision-editor-stack">
          {selectedId && <section className="panel thesis-monitor"><header><div><span>Thesis Monitor</span><h3>{monitor?.overall_status.replaceAll("_", " ") || (monitorLoading ? "Evaluating verified evidence…" : "Monitoring unavailable")}</h3><small>{monitor?`Since ${dateLabel(monitor.baseline_review_at)} · ${monitor.freshness.toLowerCase()} freshness · ${monitor.evidence_quality.toLowerCase()} quality`:"The monitor does not make an investment decision."}</small></div>{monitor&&<button className="primary" disabled={saving} onClick={()=>void markReviewed()}>{saving?"Saving review…":"Mark reviewed"}</button>}</header>
            {monitor&&<EvidenceTrust compact label="Thesis-monitor trust" data={{kind:"MODEL_OUTPUT",provider:"EagleEyes thesis monitor",asOf:monitor.evaluated_at,knownAt:monitor.baseline_review_at,currentAt:monitor.evaluated_at,methodology:"Deterministic threshold rules plus bounded qualitative evidence mapping; the monitor never chooses an investment action.",coverage:`${monitor.evidence_coverage.filter(item=>item.status==="AVAILABLE").length}/${monitor.evidence_coverage.length} evidence categories`,freshness:monitor.freshness,quality:monitor.evidence_quality,agreement:monitor.assumption_results.length?monitor.assumption_results[0].evidence_agreement:undefined,modelVersion:monitor.calculation_version,assumptions:monitor.warnings,missingState:monitor.evidence_coverage.some(item=>item.status!=="AVAILABLE")?"PARTIAL_COVERAGE":null}}/>}
            {monitorError&&<div className="validation-list" role="alert"><span>{monitorError}</span><button className="secondary" onClick={()=>void loadMonitor(selectedId)}>Retry</button></div>}
            {monitor&&<><div className="monitor-overview"><article><span>Supports</span><strong>{monitor.counts.SUPPORTS||0}</strong></article><article><span>Weakens</span><strong>{monitor.counts.WEAKENS||0}</strong></article><article><span>Contradicts</span><strong>{monitor.counts.CONTRADICTS||0}</strong></article><article><span>Insufficient</span><strong>{monitor.counts.INSUFFICIENT_EVIDENCE||0}</strong></article></div>
              <section className="monitor-section breakers"><h4>Breakers and warnings</h4>{monitor.thesis_breaker_results.length?monitor.thesis_breaker_results.map(item=><article key={item.factor_id}><span>{item.state.replaceAll("_"," ")}</span><strong>{item.description}</strong><p>{item.explanation}</p><small>{item.rule||"Qualitative verified-evidence mapping"}</small>{item.evidence.map(trace=><MonitorEvidenceRow key={`${item.factor_id}-${trace.metric}`} item={trace}/>)}</article>):<p>No thesis breakers were saved.</p>}</section>
              <section className="monitor-section"><h4>Assumptions affected</h4>{monitor.assumption_results.map(item=><article key={item.assumption_id}><span>{item.state} · {item.importance}</span><strong>{item.description}</strong><p>{item.explanation}</p><small>{item.deterministic?`Deterministic rule · ${item.rule}`:`Qualitative mapping · agreement ${item.evidence_agreement.toLowerCase()}`} · coverage {item.data_coverage.toLowerCase()}</small>{item.evidence.map(trace=><MonitorEvidenceRow key={`${item.assumption_id}-${trace.metric}`} item={trace}/>)}</article>)}</section>
              <details className="monitor-coverage"><summary>Coverage and unavailable evidence</summary>{monitor.evidence_coverage.map(item=><p key={item.evidence_type}><b>{item.evidence_type.replaceAll("_"," ")} · {item.status}</b><small>{item.message}</small></p>)}</details>
              <details className="monitor-history"><summary>Thesis review history ({reviewHistory.length})</summary>{reviewHistory.length?reviewHistory.map(item=><p key={item.id}><b>{dateLabel(item.reviewed_at)} · {item.overall_status.replaceAll("_"," ")}</b><small>Thesis v{item.thesis_version} · {item.monitoring_result.counts?.SUPPORTS||0} supporting · {item.monitoring_result.counts?.WEAKENS||0} weakening · {item.monitoring_result.counts?.CONTRADICTS||0} contradicting</small></p>):<p>No completed review events yet. Normal edits do not create review events.</p>}</details>
              <footer><small>EagleEyes shows how evidence relates to your saved reasoning. You choose whether to keep or update the thesis and whether to record a decision.</small><a className="secondary" href={`/decisions?ticker=${form.ticker}`}>Update thesis below</a></footer></>}
          </section>}
          <form className="panel thesis-editor guided-thesis-editor" onSubmit={save}>
            <GuidedThesisEditor form={form} setForm={setForm} selected={Boolean(selectedId)} drafting={drafting} saving={saving} stage={guidedStage} setStage={setGuidedStage} relationship={relationship} setRelationship={setRelationship} personalReason={personalReason} setPersonalReason={setPersonalReason} reviewConfirmed={reviewConfirmed} setReviewConfirmed={setReviewConfirmed} onDraft={draft}/>
            <details className="legacy-thesis-editor" onToggle={event=>{if(event.currentTarget.open)setReviewConfirmed(false);}}><summary>Additional structured fields</summary><div onChange={()=>setReviewConfirmed(false)}>
            <header><div><span>{selectedId ? `Version ${form.current_version}` : "Unsaved"}</span><h3>{selectedId ? `Edit ${form.ticker} thesis` : "Create an investment thesis"}</h3></div><button type="button" className="secondary" disabled={drafting || !form.ticker} onClick={draft}>{drafting ? "Drafting…" : "Draft from verified research"}</button></header>
            <div className="thesis-fields">
              <label>Ticker<input value={form.ticker} disabled={!!selectedId} maxLength={10} onChange={event => setForm({ ...form, ticker: event.target.value.toUpperCase() })} placeholder="AAPL" /></label>
              <label>Status<select value={form.status} onChange={event => setForm({ ...form, status: event.target.value as InvestmentThesis["status"] })}><option>DRAFT</option><option>ACTIVE</option><option>UNDER_REVIEW</option><option>CLOSED</option><option>ARCHIVED</option></select></label>
              <label>Horizon<select value={form.investment_horizon} onChange={event => setForm({ ...form, investment_horizon: event.target.value as InvestmentThesis["investment_horizon"] })}><option value="short">Short</option><option value="medium">Medium</option><option value="long">Long</option><option value="custom">Custom</option></select></label>
              <label>Review date<input type="date" value={form.review_date || ""} onChange={event => setForm({ ...form, review_date: event.target.value || null })} /></label>
            </div>
            <label>Thesis summary<textarea required value={form.summary} onChange={event => setForm({ ...form, summary: event.target.value })} placeholder="Why might this investment deserve capital or continued attention?" /></label>
            <label>Base case<textarea value={form.base_case} onChange={event => setForm({ ...form, base_case: event.target.value })} /></label>

            <section className="thesis-structured-list"><div><h4>Key assumptions</h4><button type="button" className="secondary" onClick={() => setForm({ ...form, assumptions: [...form.assumptions, { description: "", category: "CUSTOM", importance: "MEDIUM", status: "UNTESTED", evidence_mapping: {} }] })}>+ Assumption</button></div>
              {form.assumptions.length === 0 && <p>No assumptions yet. Missing structure is shown as missing, not neutral.</p>}
              {form.assumptions.map((item, index) => <div className="structured-item" key={item.id || index}><div className="structured-row"><input aria-label={`Assumption ${index + 1}`} value={item.description} onChange={event => updateAssumption(index, { description: event.target.value })} placeholder="Assumption that supports the thesis" /><select value={item.importance} onChange={event => updateAssumption(index, { importance: event.target.value as ThesisAssumption["importance"] })}><option>LOW</option><option>MEDIUM</option><option>HIGH</option><option>CRITICAL</option></select><select value={item.status} onChange={event => updateAssumption(index, { status: event.target.value as ThesisAssumption["status"] })}><option>UNTESTED</option><option>SUPPORTED</option><option>WEAKENING</option><option>BROKEN</option><option>NOT_MONITORABLE</option></select><button type="button" className="remove" onClick={() => setForm({ ...form, assumptions: form.assumptions.filter((_, itemIndex) => itemIndex !== index) })}>×</button></div><div className="condition-row"><input aria-label={`Metric for assumption ${index + 1}`} value={item.metric||""} onChange={event=>updateAssumption(index,{metric:event.target.value||null})} placeholder="Optional metric, e.g. gross_margin"/><select aria-label={`Operator for assumption ${index + 1}`} value={item.operator||""} onChange={event=>updateAssumption(index,{operator:(event.target.value||null) as ThesisAssumption["operator"]})}><option value="">No rule</option>{[">",">=","<","<=","=","!="].map(value=><option key={value}>{value}</option>)}</select><input aria-label={`Target for assumption ${index + 1}`} type="number" step="any" value={item.target_value??""} onChange={event=>updateAssumption(index,{target_value:event.target.value===""?null:Number(event.target.value)})} placeholder="Target"/><input aria-label={`Unit for assumption ${index + 1}`} value={item.unit||""} onChange={event=>updateAssumption(index,{unit:event.target.value||null})} placeholder="Unit"/></div></div>)}
            </section>

            <details><summary>Bull case, bear case, catalysts, risks, and thesis breakers</summary>
              <label>Bull case<textarea value={form.bull_case} onChange={event => setForm({ ...form, bull_case: event.target.value })} /></label>
              <label>Bear case<textarea value={form.bear_case} onChange={event => setForm({ ...form, bear_case: event.target.value })} /></label>
              {(["CATALYST", "RISK", "BREAKER"] as const).map(type => <section className="thesis-structured-list" key={type}><div><h4>{type === "BREAKER" ? "Thesis breakers" : `${type[0]}${type.slice(1).toLowerCase()}s`}</h4><button type="button" className="secondary" onClick={() => setForm({ ...form, factors: [...form.factors, { factor_type: type, description: "", evidence_mapping: {} }] })}>+ Add</button></div>{factors[type].map(({ item, index }) => <div className="structured-item" key={item.id || index}><div className="structured-row"><input value={item.description} onChange={event => updateFactor(index, { description: event.target.value })} placeholder={type === "BREAKER" ? "Condition that invalidates the thesis" : `${type.toLowerCase()} and evidence`} /><button type="button" className="remove" onClick={() => setForm({ ...form, factors: form.factors.filter((_, itemIndex) => itemIndex !== index) })}>×</button></div><div className="condition-row"><input aria-label={`Metric for ${type.toLowerCase()} ${index + 1}`} value={item.metric||""} onChange={event=>updateFactor(index,{metric:event.target.value||null})} placeholder="Optional metric"/><select aria-label={`Operator for ${type.toLowerCase()} ${index + 1}`} value={item.operator||""} onChange={event=>updateFactor(index,{operator:(event.target.value||null) as ThesisFactor["operator"]})}><option value="">No rule</option>{[">",">=","<","<=","=","!="].map(value=><option key={value}>{value}</option>)}</select><input aria-label={`Threshold for ${type.toLowerCase()} ${index + 1}`} type="number" step="any" value={item.threshold??""} onChange={event=>updateFactor(index,{threshold:event.target.value===""?null:Number(event.target.value)})} placeholder="Threshold"/><input aria-label={`Periods for ${type.toLowerCase()} ${index + 1}`} value={item.period_requirement||""} onChange={event=>updateFactor(index,{period_requirement:event.target.value||null})} placeholder="e.g. 2 quarters"/><input aria-label={`Unit for ${type.toLowerCase()} ${index + 1}`} value={item.unit||""} onChange={event=>updateFactor(index,{unit:event.target.value||null})} placeholder="Unit"/></div></div>)}</section>)}
            </details>
            <footer><small>These advanced fields use the same saved thesis and monitoring contracts.</small><button className="primary" disabled={saving||!reviewConfirmed}>{saving ? "Saving…" : selectedId ? "Confirm and save new version" : "Confirm and save thesis"}</button></footer>
            </div></details>
          </form>

          <form className="panel decision-recorder" onSubmit={recordDecision}><header><div><span>Append-only journal</span><h3>Record a decision for {form.ticker || "a security"}</h3></div></header><div className="decision-record-fields"><label>Decision<select value={decisionType} onChange={event => setDecisionType(event.target.value as DecisionType)}>{["WATCH", "BUY", "ADD", "HOLD", "REDUCE", "SELL", "AVOID"].map(item => <option key={item}>{item}</option>)}</select></label><label>Confidence (optional)<select value={confidence} onChange={event => setConfidence(event.target.value)}><option value="">Not specified</option>{[1,2,3,4,5].map(item => <option key={item}>{item}</option>)}</select></label><label>Review horizon<select value={reviewHorizon} onChange={event=>setReviewHorizon(event.target.value)}><option value="30">30 days</option><option value="90">90 days</option><option value="183">6 months</option><option value="365">1 year</option></select></label><label>Benchmark<input value={benchmark} maxLength={10} onChange={event=>setBenchmark(event.target.value.toUpperCase())}/></label></div><label>Expected outcome (optional)<textarea value={expectedOutcome} onChange={event=>setExpectedOutcome(event.target.value)} placeholder="What do you expect to be true by the review horizon?"/></label><label>Reasoning at the time<textarea value={decisionNotes} onChange={event => setDecisionNotes(event.target.value)} placeholder="Why this action—or no action—now?" /></label><footer><small>The saved thesis version, evidence boundary, forecasts, price, and available portfolio context are captured once. Missing history remains missing.</small><button className="primary" disabled={saving || !form.ticker}>Record decision</button></footer></form>
        </div>
      </div>

      <section className="panel decision-journal"><header><div><span>Decision Journal</span><h3>Review reasoning separately from returns</h3><p>Each retrospective uses the immutable context saved at the decision boundary.</p></div><small>{journal?.ready_for_review.length||0} due · {journal?.completed_retrospectives.length||0} completed</small></header>
        {journalReview&&<EvidenceTrust compact label="Point-in-time decision boundary" data={{kind:"VERIFIED_FACT",provider:"Immutable EagleEyes decision snapshot",knownAt:journalReview.snapshot.decision_date,currentAt:journalReview.horizon.end,asOf:journalReview.horizon.end,methodology:journalReview.methodology,coverage:journalReview.snapshot.missing.length?"partial snapshot coverage":"captured decision context",freshness:journalReview.horizon.matured?"completed horizon":"interim horizon",quality:journalReview.warnings.length?"PARTIAL":"SUPPORTED",missingState:journalReview.snapshot.missing.length?"PARTIAL_COVERAGE":null,assumptions:journalReview.warnings}}/>}
        {!journal?<p>Decision journal unavailable.</p>:<div className="journal-layout"><div className="journal-list"><h4>Ready for review</h4>{journal.ready_for_review.length===0?<p>No decision review has reached its saved horizon.</p>:journal.ready_for_review.map(row=><button key={row.decision.id} className={journalDecisionId===row.decision.id?"selected":""} onClick={()=>void openJournalReview(row.decision.id)}><strong>{row.decision.ticker} · {row.decision.decision_type}</strong><span>Due {dateLabel(row.due_at)} · {row.horizon_days} days</span></button>)}<h4>Recent decision context</h4>{journal.recent_decisions.slice(0,10).map(row=><button key={row.id} disabled={row.snapshot_available===false} title={row.snapshot_missing_reason||undefined} className={journalDecisionId===row.id?"selected":""} onClick={()=>void openJournalReview(row.id)}><strong>{row.ticker} · {row.decision_type}</strong><span>{row.snapshot_available===false?row.snapshot_missing_reason:`${dateLabel(row.decision_date)} · ${(row.source_context?.expected_outcome as string)||"Expected outcome not recorded"}`}</span></button>)}</div>
          <div className="journal-review">{journalLoading?<p>Reconstructing the bounded evidence window…</p>:!journalReview?<div className="decisions-empty"><h3>Select a decision to review.</h3><p>Market return will remain separate from whether the original process was well supported.</p></div>:<><div className="journal-review-head"><div><span>{journalReview.decision.ticker} · {journalReview.decision.decision_type}</span><h3>{journalReview.process_review.thesis_support.replaceAll("_"," ")}</h3><small>{dateLabel(journalReview.horizon.start)} → {dateLabel(journalReview.horizon.end)} · {journalReview.horizon.matured?"horizon matured":"interim review"}</small></div><label>Window<select value={journalHorizon} onChange={event=>{setJournalHorizon(event.target.value);if(journalDecisionId)void openJournalReview(journalDecisionId,event.target.value);}}>{["30D","90D","6M","1Y","THESIS"].map(item=><option key={item}>{item}</option>)}</select></label></div><p>{journalReview.grounded_summary}</p><div className="journal-outcomes"><article><span>Original expectation</span><strong>{journalReview.snapshot.expected_outcome||"Not recorded"}</strong><small>Confidence {journalReview.snapshot.user_confidence||"not recorded"} · price {money(journalReview.snapshot.price.value)}</small></article><article><span>Market outcome</span><strong>{journalReview.market_outcome.security_return==null?"Unavailable":`${(journalReview.market_outcome.security_return*100).toFixed(1)}%`}</strong><small>vs {journalReview.market_outcome.benchmark}: {journalReview.market_outcome.relative_return==null?"comparison unavailable":`${(journalReview.market_outcome.relative_return*100).toFixed(1)} pts relative`}</small></article><article><span>Process evidence</span><strong>{journalReview.process_review.confirmed_assumptions} confirmed · {journalReview.process_review.invalidated_assumptions} invalidated</strong><small>{journalReview.process_review.interpretation}</small></article></div><details open><summary>Assumption outcomes</summary>{journalReview.thesis_outcomes.assumptions.length?journalReview.thesis_outcomes.assumptions.map((item,index)=><p key={`${item.description}-${index}`}><b>{item.status.replaceAll("_"," ")}</b> {item.description}<small>{item.rule||"Stored thesis-monitor evidence"}</small></p>):<p>No structured assumptions were saved at this decision.</p>}</details><details><summary>Evidence and decision timeline ({journalReview.evidence_timeline.length})</summary>{journalReview.evidence_timeline.map((item,index)=><p key={`${item.at}-${index}`}><b>{dateLabel(item.at)} · {item.type.replaceAll("_"," ")}</b><small>{item.title}</small></p>)}</details><label>Retrospective notes<textarea value={retrospectiveNotes} onChange={event=>setRetrospectiveNotes(event.target.value)} placeholder="What did you learn? What would you repeat or change?"/></label><button className="primary" disabled={saving} onClick={()=>void completeJournalReview()}>{saving?"Saving…":"Complete retrospective"}</button><footer>{journalReview.methodology}</footer></>}</div></div>}
        {journal&&<div className="journal-learning"><article><span>Recurring patterns</span><strong>{journal.patterns.status.replaceAll("_"," ")}</strong><p>{journal.patterns.status==="INSUFFICIENT_SAMPLE"?`${journal.patterns.reviewed_decisions} reviewed decisions; ${journal.patterns.minimum_sample} required before pattern claims.`:journal.patterns.patterns.filter(item=>item.established).map(item=>item.pattern).join(" · ")||"No recurring pattern crossed the threshold."}</p></article><article><span>Forecast calibration</span><strong>{journal.forecast_calibration.brier_score==null?"Unavailable":journal.forecast_calibration.brier_score.toFixed(3)}</strong><p>{journal.forecast_calibration.message||`${journal.forecast_calibration.sample_size} resolved forecasts · lower Brier score is better.`}</p></article></div>}
        {personalization&&<details className="phase10-personalization"><summary><span>Decision preferences</span><strong>{Object.keys(personalization.accepted).length} accepted · {personalization.inferred.length} proposed</strong><small>Transparent inputs only; inferences require at least {personalization.minimum_reviewed_decisions} reviewed decisions.</small></summary><div><section><h4>Explicit profile and policy</h4><p>Risk tolerance, horizon, research preferences, and approved portfolio limits remain editable in Plan settings.</p>{Object.entries(personalization.explicit).filter(([,value])=>value!=null&&value!=="").slice(0,8).map(([key,value])=><small key={key}>{key.replaceAll("_"," ")}: {typeof value==="object"?JSON.stringify(value):String(value)}</small>)}</section><section><h4>Reviewable inferences</h4>{personalization.inferred.length?personalization.inferred.map(item=><article key={item.key}><strong>{item.label}</strong><p>{item.basis}</p><small>Based on {item.sample_size} reviewed decisions</small><div><button disabled={saving} onClick={()=>void updateInference(item,"accept")}>Accept</button><button disabled={saving} onClick={()=>void updateInference(item,"edit")}>Edit & accept</button><button disabled={saving} onClick={()=>void updateInference(item,"dismiss")}>Dismiss</button></div></article>):<p>{personalization.reviewed_decisions<personalization.minimum_reviewed_decisions?`Insufficient evidence: ${personalization.reviewed_decisions} reviewed decisions. No preference is inferred yet.`:"No unreviewed preference inference is available."}</p>}</section></div></details>}
      </section>

      <section className="panel decision-history"><header><div><span>Recent decisions</span><h3>What you decided at the time</h3></div></header>{workspace.recent_decisions.length === 0 ? <p>No decisions recorded yet.</p> : <div className="table-scroll"><table><thead><tr><th>Date</th><th>Security</th><th>Decision</th><th>Thesis version</th><th>Observed price</th><th>Confidence</th><th>Notes</th></tr></thead><tbody>{workspace.recent_decisions.map(item => <tr key={item.id}><td>{new Date(item.decision_date).toLocaleDateString()}</td><td>{item.ticker}</td><td><strong>{item.decision_type}</strong></td><td>{item.thesis_version ? `v${item.thesis_version}` : "No linked thesis"}</td><td>{money(item.price_at_decision)}{item.price_source && <small> · {item.price_source}</small>}</td><td>{item.user_confidence || "Not specified"}</td><td>{item.notes || "No note"}</td></tr>)}</tbody></table></div>}</section>
    </>}

    <details className="panel legacy-decision-lab"><summary>Scenario comparison lab</summary>{holdings.length ? <DecisionLab request={request} holdings={holdings} profile={profile} goals={goals} /> : <div className="decisions-empty"><h3>Add portfolio holdings before comparing modeled alternatives.</h3><p>The lab does not invent positions or placeholder financial data.</p><button className="primary" onClick={onOpenPortfolio}>Add holdings</button></div>}</details>
  </section>;
}

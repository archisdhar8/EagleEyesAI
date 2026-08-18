"use client";

import { ChangeEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AppShell } from "./components/shell/AppShell";
import { TodayPage, type TodayBriefing } from "./components/today/TodayPage";
import { PlanPage } from "./components/plan/PlanPage";
import { PortfolioPage } from "./components/portfolio/PortfolioPage";
import { ExplorePage } from "./components/research/ExplorePage";
import { LearnPage } from "./components/learn/LearnPage";
import { AskPage } from "./components/ask/AskPage";
import { DecisionsPage } from "./components/decisions/DecisionsPage";
import { MarketClimatePage } from "./components/markets/MarketClimatePage";
import { AdvancedPage, ResearchTerminal } from "./components/terminal/AdvancedPage";
import { adaptDashboardSpecification } from "./components/ask/contracts";
import { adaptTerminalWidgets, type TerminalLayout, type TerminalWidgetConfig, type TerminalWidgetType } from "./components/terminal/contracts";
import { normalizePresentationLevel } from "./lib/presentation-level";
import { navigationLabel, pathForTab, resolveAppRoute, type AdvancedView, type ExploreView, type PortfolioView, type RouteState, type Tab } from "./lib/routes";
import {
  defaultPolicy, defaultProfile, defaultTerminalWidgets, seededScenarios, terminalCatalog,
  type Analysis, type Contract, type DashboardCatalogItem, type DashboardJob,
  type DashboardSpec, type DashboardView, type DataStatus, type Goal,
  type GoalProjection, type Holding, type InvestmentPolicy, type Macro, type MacroFactor,
  type Monitoring, type PlanGuidance, type PortfolioDiagnostics, type Preferences, type Profile,
  type RegimeSummary, type Research, type Scenario, type TerminalMarketIndicator, type TerminalPerformance, type ChatMessage,
  type ChatConversation, type ChatArtifact,
} from "./components/workspaces";

const API = (process.env.NEXT_PUBLIC_API_URL || (process.env.NODE_ENV === "development" ? "http://127.0.0.1:8000/api" : "/api")).replace(/\/$/, "");
const DASHBOARD_TERMINAL_STATES = new Set(["COMPLETE", "PARTIAL_SUCCESS", "FAILED", "CANCELLED", "EXPIRED"]);
type SavedPortfolio = { id: string | number; name: string; holdings: Holding[]; updated_at?: string | null };
type CachedToday = { cachedAt:number; briefing:TodayBriefing; macro?:Macro; macroFactors?:MacroFactor[]; dataStatus?:DataStatus };
export default function Dashboard({ accessToken, email, onSignOut }: { accessToken: string; email: string; onSignOut: () => void }) {
  const [tab, setTab] = useState<Tab>("today");
  const [exploreView, setExploreView] = useState<ExploreView>("stocks");
  const [portfolioView, setPortfolioView] = useState<PortfolioView>("holdings");
  const [advancedView, setAdvancedView] = useState<AdvancedView>("terminal");
  const [learningModule, setLearningModule] = useState<string>();
  const [learningLesson, setLearningLesson] = useState<string>();
  // Keep the server and first client render identical. The saved browser-only
  // preference is applied after hydration.
  const [dark, setDark] = useState(true);
  const [connected, setConnected] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState("");
  const [portfolioId, setPortfolioId] = useState<string | number | null>(null);
  const [portfolios, setPortfolios] = useState<SavedPortfolio[]>([]);
  const [portfolioName, setPortfolioName] = useState("Primary portfolio");
  const [holdings, setHoldings] = useState<Holding[]>([]);
  const [savedPortfolioSnapshot, setSavedPortfolioSnapshot] = useState(() => portfolioSignature("Primary portfolio", []));
  const [persistedTickers, setPersistedTickers] = useState<string[]>([]);

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(""), 5000);
    return () => window.clearTimeout(timer);
  }, [notice]);
  const [profile, setProfile] = useState<Profile>(defaultProfile);
  const [goals, setGoals] = useState<Goal[]>([]);
  const [goalProjections, setGoalProjections] = useState<Record<string,GoalProjection>>({});
  const [investmentPolicy,setInvestmentPolicy]=useState<InvestmentPolicy>(defaultPolicy);
  const [planGuidance,setPlanGuidance]=useState<PlanGuidance|null>(null);
  const [portfolioDiagnostics,setPortfolioDiagnostics]=useState<PortfolioDiagnostics|null>(null);
  const [homeBriefing, setHomeBriefing] = useState<TodayBriefing | null>(null);
  const [macro, setMacro] = useState<Macro>({ regime: "neutral", score: 50, as_of: null });
  const [scenarios, setScenarios] = useState<Scenario[]>(seededScenarios);
  const [contracts, setContracts] = useState<Contract[]>([]);
  const [scenarioFetchedAt, setScenarioFetchedAt] = useState<string | null>(null);
  const [scenarioWarnings, setScenarioWarnings] = useState<string[]>(["Connect the local data service to refresh live prediction markets."]);
  const [research, setResearch] = useState<Research[]>([]);
  const [dataStatus, setDataStatus] = useState<DataStatus>({ storage: "pending", counts: {}, freshness: {}, providers: [] });
  const [regimeHistory, setRegimeHistory] = useState<RegimeSummary>({ latest: null, sample_counts: {}, total_samples: 0 });
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const analysisRefreshTimer = useRef<number | null>(null);
  const [monitoring, setMonitoring] = useState<Monitoring | null>(null);
  const [selectedAlternative, setSelectedAlternative] = useState(1);
  const [narrative, setNarrative] = useState("");
  const [sortKey, setSortKey] = useState<keyof Research>("final_score");
  const [macroFactors, setMacroFactors] = useState<MacroFactor[]>([]);
  const [preferences, setPreferences] = useState<Preferences>({ overview_widgets: ["portfolio","macro","scenarios","research","freshness"], macro_widgets: ["rates","inflation","growth","labor","credit"], research_widgets: ["market","scores","fundamentals","news","prediction_markets"], focused_tickers: [], density: "comfortable", presentation_level: "detailed", terminal_widgets: defaultTerminalWidgets });
  const [customizing, setCustomizing] = useState(false);
  const [dashboardPrompt, setDashboardPrompt] = useState("");
  const [dashboardJob, setDashboardJob] = useState<DashboardJob | null>(null);
  const [dashboardViews, setDashboardViews] = useState<DashboardView[]>([]);
  const [dashboardCatalog, setDashboardCatalog] = useState<DashboardCatalogItem[]>([]);
  const [selectedDashboardView, setSelectedDashboardView] = useState<string | null>(null);
  const [dashboardBusy, setDashboardBusy] = useState(false);
  const [dashboardSourceConversationId,setDashboardSourceConversationId]=useState<string|null>(null);
  const [researchChatMessages, setResearchChatMessages] = useState<ChatMessage[]>([]);
  const [researchChatQuestion, setResearchChatQuestion] = useState("");
  const [researchChatBusy, setResearchChatBusy] = useState(false);
  const [askEnabledContext,setAskEnabledContext]=useState<Array<"evidence"|"thesis"|"portfolio">>(["evidence","thesis","portfolio"]);
  const [researchConversationId, setResearchConversationId] = useState<string | null>(null);
  const [researchConversations,setResearchConversations]=useState<ChatConversation[]>([]);
  const [researchChatArtifacts,setResearchChatArtifacts]=useState<ChatArtifact[]>([]);
  const conversationCache=useRef<Record<"research"|"portfolio",Map<string,{messages:ChatMessage[];artifacts:ChatArtifact[]}>>>({research:new Map(),portfolio:new Map()});
  const [portfolioChatMessages, setPortfolioChatMessages] = useState<ChatMessage[]>([]);
  const [portfolioChatQuestion, setPortfolioChatQuestion] = useState("");
  const [portfolioChatBusy, setPortfolioChatBusy] = useState(false);
  const [portfolioConversationId, setPortfolioConversationId] = useState<string | null>(null);
  const [portfolioConversations,setPortfolioConversations]=useState<ChatConversation[]>([]);
  const [portfolioChatArtifacts,setPortfolioChatArtifacts]=useState<ChatArtifact[]>([]);
  const [terminalCatalogOpen, setTerminalCatalogOpen] = useState(false);
  const [terminalPerformance, setTerminalPerformance] = useState<TerminalPerformance>(null);
  const [terminalMarketIndicators, setTerminalMarketIndicators] = useState<TerminalMarketIndicator[]>([]);
  const [terminalTicker, setTerminalTicker] = useState("SPY");
  const [terminalContractSearch, setTerminalContractSearch] = useState("");
  const [draggedTerminalWidget, setDraggedTerminalWidget] = useState<string | null>(null);
  const [terminalLayouts, setTerminalLayouts] = useState<TerminalLayout[]>([]);
  const [selectedTerminalLayout, setSelectedTerminalLayout] = useState<string | null>(null);
  const restoredChatWorkspaces=useRef(new Set<"research"|"portfolio">());

  const apiFetch = useCallback(async (input: string, init: RequestInit = {}) => {
    const headers = new Headers(init.headers);
    headers.set("Authorization", `Bearer ${accessToken}`);
    const method=(init.method||"GET").toUpperCase();
    const attempts=method==="GET"?2:1;
    let lastError:unknown;
    for(let attempt=1;attempt<=attempts;attempt++){
      const controller=new AbortController();
      const timeout=window.setTimeout(()=>controller.abort(new DOMException("Request timed out","TimeoutError")),method==="GET"?20_000:45_000);
      try{
        const response=await fetch(input,{...init,headers,signal:init.signal||controller.signal});
        if(attempt<attempts&&[408,429,500,502,503,504].includes(response.status)){await new Promise(resolve=>window.setTimeout(resolve,250*attempt));continue;}
        return response;
      }catch(error){
        lastError=error;
        if(attempt>=attempts||init.signal?.aborted)throw error;
        await new Promise(resolve=>window.setTimeout(resolve,250*attempt));
      }finally{window.clearTimeout(timeout);}
    }
    throw lastError instanceof Error?lastError:new Error("Request failed");
  }, [accessToken]);
  const apiRequest = useCallback((path: string, init?: RequestInit) => apiFetch(`${API}${path}`, init), [apiFetch]);
  const todayCacheKey=useCallback((id:string|number)=>`eagleeyes-today-cache-${email}-${id}`,[email]);
  const storeTodayCache=useCallback((id:string|number|null|undefined,data:{briefing?:TodayBriefing|null;macro?:Macro;macro_factors?:{factors?:MacroFactor[]};data_status?:DataStatus})=>{
    if(id==null||!data.briefing)return;
    try{
      const cached:CachedToday={cachedAt:Date.now(),briefing:data.briefing,macro:data.macro,macroFactors:data.macro_factors?.factors||[],dataStatus:data.data_status};
      window.localStorage.setItem(todayCacheKey(id),JSON.stringify(cached));
    }catch{/* A full or unavailable browser cache must never block Today. */}
  },[todayCacheKey]);

  useEffect(()=>{
    const workspace=tab==="ask"?"research":tab==="portfolio"?"portfolio":null;
    if(!workspace||restoredChatWorkspaces.current.has(workspace))return;
    const activeWorkspace: "research"|"portfolio"=workspace;
    let active=true;
    async function restore(){
      const response=await apiRequest(`/chat/conversations?workspace=${activeWorkspace}`);
      if(!response.ok)return;
      const payload=await response.json();
      const rows:ChatConversation[]=Array.isArray(payload)?payload:[];
      if(!active)return;
      restoredChatWorkspaces.current.add(activeWorkspace);
      if(activeWorkspace==="research")setResearchConversations(rows);else setPortfolioConversations(rows);
      const remembered=window.localStorage.getItem(`eagleeyes-${activeWorkspace}-conversation`);
      const selected=rows.find(item=>item.id===remembered)?.id||rows[0]?.id;
      if(!selected)return;
      const detailResponse=await apiRequest(`/chat/conversations/${selected}`);
      if(!detailResponse.ok||!active)return;
      const detail=await detailResponse.json();
      conversationCache.current[activeWorkspace].set(selected,{messages:detail.messages||[],artifacts:detail.artifacts||[]});
      if(activeWorkspace==="research"){setResearchConversationId(selected);setResearchChatMessages(detail.messages||[]);setResearchChatArtifacts(detail.artifacts||[]);}
      else{setPortfolioConversationId(selected);setPortfolioChatMessages(detail.messages||[]);setPortfolioChatArtifacts(detail.artifacts||[]);}
      window.localStorage.setItem(`eagleeyes-${activeWorkspace}-conversation`,selected);
    }
    void restore();
    return()=>{active=false;};
  },[apiRequest,tab]);

  useEffect(() => {
    function applyRoute(route: RouteState) {
      setTab(route.tab);
      if(route.exploreView)setExploreView(route.exploreView);
      if(route.portfolioView)setPortfolioView(route.portfolioView);
      if(route.advancedView)setAdvancedView(route.advancedView);
      setLearningModule(route.learningModule);
      setLearningLesson(route.learningLesson);
    }
    function handleLocation() {
      const route = resolveAppRoute(window.location.pathname, window.location.search);
      if (!route) return;
      if (`${window.location.pathname}${window.location.search}` !== route.canonicalPath) window.history.replaceState({}, "", route.canonicalPath);
      applyRoute(route);
      if(route.tab==="ask"){
        const suggested=new URLSearchParams(window.location.search).get("prompt");
        if(suggested)setResearchChatQuestion(suggested);
      }
    }
    const frame=window.requestAnimationFrame(handleLocation);
    window.addEventListener("popstate", handleLocation);
    return()=>{window.cancelAnimationFrame(frame);window.removeEventListener("popstate",handleLocation);};
  },[]);

  useEffect(()=>{
    function handleInternalLink(event:MouseEvent){
      if(event.defaultPrevented||event.button!==0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;
      const target=event.target;
      if(!(target instanceof Element))return;
      const anchor=target.closest("a[href]") as HTMLAnchorElement|null;
      if(!anchor||anchor.target||anchor.hasAttribute("download"))return;
      const url=new URL(anchor.href,window.location.origin);
      if(url.origin!==window.location.origin||!resolveAppRoute(url.pathname,url.search))return;
      event.preventDefault();
      navigateDeepLink(`${url.pathname}${url.search}${url.hash}`);
    }
    document.addEventListener("click",handleInternalLink);
    return()=>document.removeEventListener("click",handleInternalLink);
  });

  useEffect(() => {
    document.title = `${navigationLabel(tab)} — EagleEyes`;
  }, [tab]);

  useEffect(() => {
    let active = true;
    async function loadOverview() {
      let portfolioLibraryLoaded=false;
      try {
        const rememberedBeforeLoad=window.localStorage.getItem(`eagleeyes-active-portfolio-${email}`);
        if(rememberedBeforeLoad){
          try{
            const cached=JSON.parse(window.localStorage.getItem(todayCacheKey(rememberedBeforeLoad))||"null") as CachedToday|null;
            if(cached&&Date.now()-cached.cachedAt<36*60*60*1000){
              setHomeBriefing(cached.briefing);
              if(cached.macro)setMacro(cached.macro);
              if(cached.macroFactors)setMacroFactors(cached.macroFactors);
              if(cached.dataStatus)setDataStatus(cached.dataStatus);
            }
          }catch{/* Ignore an old or partial browser cache. */}
        }
        const libraryResponse=await apiFetch(`${API}/portfolios`);
        const libraryRows:SavedPortfolio[]=libraryResponse.ok?await libraryResponse.json():[];
        const rememberedId=window.localStorage.getItem(`eagleeyes-active-portfolio-${email}`);
        const librarySelection=libraryRows.find(item=>String(item.id)===rememberedId)||libraryRows[0];
        if(active&&libraryResponse.ok){portfolioLibraryLoaded=true;setConnected(true);setPortfolios(libraryRows);if(librarySelection)showPortfolio(librarySelection);}
        // Today is composed from the server's active portfolio. Restore that
        // selection before requesting the briefing so a returning user never
        // sees a false "no portfolio" state while their saved holdings exist.
        if(librarySelection){
          const activation=await apiFetch(`${API}/portfolios/${librarySelection.id}/activate`,{method:"POST"});
          // Keep rendering the saved client-side selection if activation is
          // temporarily unavailable; the briefing retry below can still
          // recover without trapping the user on an empty loading screen.
          if(!activation.ok&&active)setNotice("Your saved portfolio is loaded. Its latest evidence is still reconnecting.");
        }
        let response = await apiFetch(`${API}/home/briefing`);
        if (!response.ok) throw new Error("Local API unavailable");
        let data = await response.json();
        if(librarySelection?.holdings.length&&!data.briefing?.portfolio_context?.available){
          response=await apiFetch(`${API}/home/briefing`);
          if(response.ok)data=await response.json();
        }
        if (!active) return;
        setConnected(true);
        const savedPortfolios:SavedPortfolio[]=libraryRows.length?libraryRows:Array.isArray(data.portfolios)?data.portfolios:(data.portfolio?[data.portfolio]:[]);
        const selectedPortfolio=savedPortfolios.find(item=>String(item.id)===rememberedId)||savedPortfolios[0];
        setPortfolios(savedPortfolios);
        if (selectedPortfolio) {
          showPortfolio(selectedPortfolio);
          if(String(data.portfolio?.id)!==String(selectedPortfolio.id))void apiFetch(`${API}/portfolios/${selectedPortfolio.id}/activate`,{method:"POST"});
        } else {
          setPortfolioId(null); setPortfolioName("Primary portfolio"); setHoldings([]);
          setSavedPortfolioSnapshot(portfolioSignature("Primary portfolio", []));
          setPersistedTickers([]);
        }
        const loadedPreferences=data.preferences||{};
        const loadedTerminalWidgets = loadedPreferences.terminal_widgets?.length ? adaptTerminalWidgets(loadedPreferences.terminal_widgets) : defaultTerminalWidgets;
        setProfile({ ...defaultProfile, ...data.profile, suitability_profile:{...defaultProfile.suitability_profile,...(data.profile?.suitability_profile||{})} }); setHomeBriefing(data.briefing||null); setMacro(data.macro); setMacroFactors(data.macro_factors?.factors || []); setPreferences(current => ({ ...current, ...loadedPreferences, presentation_level:normalizePresentationLevel(loadedPreferences.presentation_level), terminal_widgets: loadedTerminalWidgets })); setScenarios(data.scenarios.condition_dimensions||data.scenarios.scenarios); setContracts(data.scenarios.contracts || []); setScenarioFetchedAt(data.scenarios.fetched_at || null); setScenarioWarnings(data.scenarios.warnings); setResearch(data.research); setDataStatus(data.data_status); setRegimeHistory(data.regime_history || { latest: null, sample_counts: {}, total_samples: 0 });
        storeTodayCache(selectedPortfolio?.id||data.portfolio?.id,data);
        setMonitoring(data.model_monitoring || null);
        const selectedId=selectedPortfolio?.id;
        const diagnosticsResponse=await apiFetch(`${API}/portfolio/diagnostics${selectedId?`?portfolio_id=${encodeURIComponent(String(selectedId))}`:""}`);if(active&&diagnosticsResponse.ok)setPortfolioDiagnostics(await diagnosticsResponse.json());
        const analysisResponse=selectedId?await apiFetch(`${API}/analyses/latest?portfolio_id=${encodeURIComponent(String(selectedId))}`):null;
        const selectedAnalysis=analysisResponse?.ok?(await analysisResponse.json()).analysis:null;
        if(active)setAnalysis(selectedAnalysis?.alternatives?.length?selectedAnalysis:null);
        const autoRefreshKey=`eagleeyes-today-refresh-${email}-${new Date().toISOString().slice(0,10)}`;
        if(active&&data.briefing?.evidence_state!=="current"&&!window.sessionStorage.getItem(autoRefreshKey)){
          window.sessionStorage.setItem(autoRefreshKey,"started");
          void apiFetch(`${API}/home/refresh`,{method:"POST"}).then(async refreshResponse=>{
            if(!refreshResponse.ok||!active)return;
            const refreshed=await refreshResponse.json();
            if(!active)return;
            setHomeBriefing(refreshed.briefing||data.briefing||null);setMacro(refreshed.macro||data.macro);
            setMacroFactors(refreshed.macro_factors?.factors||data.macro_factors?.factors||[]);
            setDataStatus(refreshed.data_status||data.data_status);setResearch(refreshed.research||data.research||[]);
            storeTodayCache(selectedPortfolio?.id||refreshed.portfolio?.id||data.portfolio?.id,refreshed);
          }).catch(()=>undefined);
        }
      } catch {
        if (active) setConnected(portfolioLibraryLoaded);
      } finally { if (active) setLoading(false); }
    }
    void loadOverview();
    return () => { active = false; };
  }, [apiFetch,email,storeTodayCache,todayCacheKey]);

  useEffect(() => {
    if(!portfolioId){setAnalysis(null);return;}
    let active = true;
    apiFetch(`${API}/analyses/latest?portfolio_id=${encodeURIComponent(String(portfolioId))}`).then(async response => {
      if (!response.ok) return;
      const payload = await response.json();
      if (active) setAnalysis(payload.analysis?.alternatives?.length?payload.analysis:null);
    }).catch(() => undefined);
    return () => { active = false; };
  }, [apiFetch,portfolioId]);

  useEffect(() => () => {
    if (analysisRefreshTimer.current !== null) window.clearTimeout(analysisRefreshTimer.current);
  }, []);

  useEffect(()=>{
    if(tab!=="plan"&&tab!=="portfolio")return;
    let active=true;
    Promise.all([apiFetch(`${API}/plan/goals`),apiFetch(`${API}/plan/policy`),apiFetch(`${API}/plan/guidance`)]).then(async([goalsResponse,policyResponse,guidanceResponse])=>{
      const loadedGoals=goalsResponse.ok?await goalsResponse.json():[];
      const loadedPolicy=policyResponse.ok?await policyResponse.json():defaultPolicy; const loadedGuidance=guidanceResponse.ok?await guidanceResponse.json():null;
      if(active){setGoals(loadedGoals);setInvestmentPolicy({...defaultPolicy,...loadedPolicy});setPlanGuidance(loadedGuidance);}
    }).catch(()=>undefined);
    return()=>{active=false;};
  },[apiFetch,tab]);

  useEffect(()=>{
    if(tab!=="advanced")return;
    let active=true;
    apiFetch(`${API}/terminal/layouts`).then(response=>response.ok?response.json():[]).then((rows:TerminalLayout[])=>{
      if(active)setTerminalLayouts(rows.map(layout=>({...layout,widgets:adaptTerminalWidgets(layout.widgets)})));
    }).catch(()=>undefined);
    return()=>{active=false;};
  },[apiFetch,tab]);

  useEffect(() => {
    if(tab!=="advanced")return;
    let active=true;
    apiFetch(`${API}/terminal/portfolio-performance?years=1`).then(async response => {
      if (!response.ok) return null;
      return response.json();
    }).then(result => { if(active&&result)setTerminalPerformance(result); }).catch(() => undefined);
    return () => { active=false; };
  }, [apiFetch,tab]);

  useEffect(() => {
    if(tab!=="advanced")return;
    let active=true;
    apiFetch(`${API}/terminal/market-indicators`).then(response=>response.ok?response.json():[]).then(rows=>{if(active)setTerminalMarketIndicators(rows);}).catch(()=>undefined);
    return()=>{active=false;};
  },[apiFetch,tab]);

  useEffect(() => {
    if(tab!=="ask")return;
    let active = true;
    Promise.all([apiFetch(`${API}/dashboard/views`),apiFetch(`${API}/dashboard/catalog`)]).then(async ([viewsResponse,catalogResponse]) => {
      const items=viewsResponse.ok?await viewsResponse.json():[]; const catalog=catalogResponse.ok?await catalogResponse.json():[];
      if(active){setDashboardViews(items);setDashboardCatalog(catalog);}
    }).catch(() => undefined);
    return () => { active = false; };
  }, [apiFetch,tab]);

  useEffect(() => {
    const savedThemeIsDark = window.localStorage.getItem("investment-dashboard-theme") !== "light";
    const frame = window.requestAnimationFrame(() => setDark(savedThemeIsDark));
    return () => window.cancelAnimationFrame(frame);
  }, []);

  useEffect(() => { document.documentElement.dataset.theme = dark ? "dark" : "light"; }, [dark]);

  const portfolioErrors = useMemo(() => validatePortfolio(portfolioName, holdings), [portfolioName, holdings]);
  const portfolioDirty = portfolioSignature(portfolioName, holdings) !== savedPortfolioSnapshot;

  useEffect(() => {
    if (!portfolioDirty) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [portfolioDirty]);

  function toggleTheme() {
    const next = !dark; setDark(next); window.localStorage.setItem("investment-dashboard-theme", next ? "dark" : "light");
  }

  function researchTickers(nextHoldings: Holding[] = holdings) {
    return [...new Set([
      ...nextHoldings.map(row => row.ticker.trim().toUpperCase()),
      ...profile.watchlist.map(ticker => ticker.trim().toUpperCase()),
    ].filter(ticker => ticker && ticker !== "CASH"))].slice(0, 50);
  }

  async function loadResearch(nextHoldings: Holding[] = holdings, refreshProvider = false, ingestTickers: string[] = []) {
    const tickers = researchTickers(nextHoldings);
    const response = refreshProvider
      ? await apiFetch(`${API}/research/refresh`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ tickers, ingest_tickers: ingestTickers }),
        })
      : await apiFetch(`${API}/research?tickers=${encodeURIComponent(tickers.join(","))}`);
    if (!response.ok) throw new Error(await apiError(response, "Research refresh failed"));
    const data = await response.json();
    setResearch(refreshProvider ? data.research : data);
    return refreshProvider ? data : { research: data, markets_found: 0, warnings: [] };
  }

  function showPortfolio(portfolio:SavedPortfolio){
    setPortfolioId(portfolio.id);setPortfolioName(portfolio.name);setHoldings(portfolio.holdings);
    setSavedPortfolioSnapshot(portfolioSignature(portfolio.name,portfolio.holdings));
    setPersistedTickers(portfolio.holdings.map(row=>row.ticker.trim().toUpperCase()));
    setAnalysis(null);setNarrative("");
    window.localStorage.setItem(`eagleeyes-active-portfolio-${email}`,String(portfolio.id));
  }

  async function selectPortfolio(nextId:string){
    if(String(portfolioId)===nextId)return;
    if(portfolioDirty&&!window.confirm("Switch portfolios and discard unsaved changes?"))return;
    const selected=portfolios.find(item=>String(item.id)===nextId);if(!selected)return;
    showPortfolio(selected);setNotice(`Opened ${selected.name} with ${selected.holdings.length} saved holdings.`);
    try{
      await apiFetch(`${API}/portfolios/${selected.id}/activate`,{method:"POST"});
      const [diagnosticsResponse,analysisResponse]=await Promise.all([
        apiFetch(`${API}/portfolio/diagnostics?portfolio_id=${encodeURIComponent(String(selected.id))}`),
        apiFetch(`${API}/analyses/latest?portfolio_id=${encodeURIComponent(String(selected.id))}`),
      ]);
      if(diagnosticsResponse.ok)setPortfolioDiagnostics(await diagnosticsResponse.json());
      if(analysisResponse.ok){const payload=await analysisResponse.json();setAnalysis(payload.analysis?.alternatives?.length?payload.analysis:null);}
      void loadResearch(selected.holdings);
    }catch{setNotice(`${selected.name} is open. Some linked analysis is still loading.`);}
  }

  function newPortfolio(){
    if(portfolioDirty&&!window.confirm("Start a new portfolio and discard unsaved changes?"))return;
    setPortfolioId(null);setPortfolioName(`Portfolio ${portfolios.length+1}`);setHoldings([]);setPersistedTickers([]);
    setSavedPortfolioSnapshot(portfolioSignature(`Portfolio ${portfolios.length+1}`,[]));setAnalysis(null);setPortfolioDiagnostics(null);setNarrative("");
    window.localStorage.removeItem(`eagleeyes-active-portfolio-${email}`);
    setNotice("New portfolio started. Add holdings or import a file, then save it to your portfolio library.");
  }

  async function savePortfolio() {
    setBusy("Saving portfolio"); setNotice("");
    try {
      const errors = validatePortfolio(portfolioName, holdings);
      if (errors.length) throw new Error(errors[0]);
      const addedTickers = researchTickers(holdings).filter(ticker => !persistedTickers.includes(ticker));
      const url = portfolioId ? `${API}/portfolios/${portfolioId}` : `${API}/portfolios`;
      const response = await apiFetch(url, { method: portfolioId ? "PUT" : "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: portfolioName, holdings: holdings.map(cleanHolding) }) });
      if (!response.ok) throw new Error(await apiError(response, "Unable to save portfolio"));
      const saved = await response.json();
      setPortfolioId(saved.id); setHoldings(saved.holdings); setConnected(true);
      setPortfolios(current=>[saved,...current.filter(item=>String(item.id)!==String(saved.id))]);
      window.localStorage.setItem(`eagleeyes-active-portfolio-${email}`,String(saved.id));
      setSavedPortfolioSnapshot(portfolioSignature(saved.name, saved.holdings));
      setPersistedTickers(saved.holdings.map((row: Holding) => row.ticker.trim().toUpperCase()));
      try {
        const refreshed = await loadResearch(saved.holdings, true, addedTickers);
        const suffix = refreshed.markets_found ? ` ${refreshed.markets_found} Polymarket company signal${refreshed.markets_found === 1 ? "" : "s"} found.` : " Research universe updated.";
        setNotice(`Portfolio saved.${suffix}`);
      } catch {
        setNotice("Portfolio saved, but company-market evidence could not be refreshed. Existing research remains available.");
      }
      await executeAnalysis(saved.holdings, saved.name, profile, "portfolio_saved", saved.id);
    } catch (error) { setNotice(error instanceof Error ? error.message : "Unable to save portfolio."); }
    finally { setBusy(""); }
  }

  async function importCsv(event: ChangeEvent<HTMLInputElement>) {
    const input = event.currentTarget;
    const file = input.files?.[0]; if (!file) return;
    setBusy("Validating CSV"); setNotice("");
    try {
      const response = await apiFetch(`${API}/portfolios/import`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: file.name.replace(/\.(csv|tsv|txt)$/i, ""), csv_text: await file.text() }) });
      const data = await response.json(); if (!response.ok) throw new Error(formatApiDetail(data.detail) || "CSV validation failed");
      setPortfolioId(data.portfolio.id); setPortfolioName(data.portfolio.name); setHoldings(data.portfolio.holdings); setConnected(true);
      setPortfolios(current=>[data.portfolio,...current.filter(item=>String(item.id)!==String(data.portfolio.id))]);
      window.localStorage.setItem(`eagleeyes-active-portfolio-${email}`,String(data.portfolio.id));
      setSavedPortfolioSnapshot(portfolioSignature(data.portfolio.name, data.portfolio.holdings));
      setPersistedTickers(data.portfolio.holdings.map((row: Holding) => row.ticker.trim().toUpperCase()));
      const warningCopy=data.warnings?.length?` ${data.warnings.join(" ")}`:"";
      setBusy("");
      input.value = "";
      setNotice(`${data.validated_rows} holdings imported and saved. Research evidence is refreshing in the background.${warningCopy}`);
      void (async () => {
        try {
          await loadResearch(data.portfolio.holdings, true, researchTickers(data.portfolio.holdings));
          await refreshPlanGuidance();
          setNotice(`${data.validated_rows} holdings imported and saved. Research refresh complete.${warningCopy}`);
        } catch {
          setNotice(`${data.validated_rows} holdings imported and saved. Research refresh is temporarily unavailable; the portfolio itself is ready.${warningCopy}`);
        }
        await executeAnalysis(data.portfolio.holdings, data.portfolio.name, profile, "portfolio_saved", data.portfolio.id);
      })();
    } catch (error) { setNotice(error instanceof Error ? error.message : "Unable to import CSV."); }
    finally { setBusy(""); input.value = ""; }
  }

  async function refreshMarkets() {
    setBusy("Refreshing prediction markets"); setNotice("");
    try {
      const response = await apiFetch(`${API}/providers/refresh?force=true`, { method: "POST" }); const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Refresh failed");
      setScenarios(data.condition_dimensions||data.scenarios); setContracts(data.contracts || []); setScenarioFetchedAt(data.fetched_at || null); setScenarioWarnings(data.warnings); setNotice(data.cached ? "Using the latest validated snapshot." : "Prediction-market scenarios refreshed."); setConnected(true);
    } catch (error) { setNotice(error instanceof Error ? error.message : "Refresh unavailable."); }
    finally { setBusy(""); }
  }

  async function refreshToday() {
    setBusy("Refreshing market and macro data"); setNotice("");
    try {
      const response = await apiFetch(`${API}/home/refresh`, { method: "POST" });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Today refresh failed");
      setHomeBriefing(data.briefing || null); setMacro(data.macro); setMacroFactors(data.macro_factors?.factors || []);
      setDataStatus(data.data_status); setResearch(data.research || []); setConnected(true);
      storeTodayCache(portfolioId||data.portfolio?.id,data);
      const warnings = data.refresh?.warnings || [];
      setNotice(data.refresh?.status==="queued"
        ? "Your saved evidence is ready. Fresh price and macro checks are continuing in the background."
        : warnings.length ? `Saved evidence is ready with ${warnings.length} provider warning${warnings.length === 1 ? "" : "s"}.` : "Today uses the latest validated market and macro observations.");
    } catch (error) {
      const aborted=error instanceof DOMException&&error.name==="AbortError"||error instanceof Error&&/abort|timeout/i.test(`${error.name} ${error.message}`);
      setNotice(aborted?"The live refresh is taking longer than expected. Your saved portfolio and evidence remain available; try again shortly.":error instanceof Error?error.message:"Today refresh unavailable.");
    }
    finally { setBusy(""); }
  }

  async function refreshResearch() {
    setBusy("Refreshing company research"); setNotice("");
    try {
      const data = await loadResearch(holdings, true, researchTickers(holdings));
      setConnected(true);
      setNotice(`Research refreshed for ${data.searched} securities; ${data.markets_found} live Polymarket company signals found.`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Research refresh unavailable.");
    } finally { setBusy(""); }
  }

  async function executeAnalysis(
    nextHoldings: Holding[] = holdings,
    nextName: string = portfolioName,
    nextProfile: Profile = profile,
    reason: "manual" | "portfolio_saved" | "objectives_changed" = "manual",
    nextPortfolioId: string | number | null = portfolioId,
  ) {
    setBusy("Running scenario analysis"); setNotice(""); setNarrative("");
    try {
      const errors = validatePortfolio(nextName, nextHoldings);
      if (errors.length) throw new Error(`Portfolio needs attention: ${errors[0]}`);
      const analysisProfile={...nextProfile,research_preferences:investmentPolicy.research_preferences};
      await apiFetch(`${API}/profile`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(analysisProfile) });
      const response = await apiFetch(`${API}/analyses`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ portfolio_id:nextPortfolioId, portfolio: { name: nextName, holdings: nextHoldings.map(cleanHolding) }, profile:analysisProfile }) });
      const data = await response.json(); if (!response.ok) throw new Error(data.detail || "Analysis failed");
      setAnalysis(data); setResearch(data.research); setMacro(data.macro); setSelectedAlternative(1); setConnected(true); setNotice("Three alternatives are ready. Review the tradeoffs—not just the headline return.");
      if (data.cache_status === "hit") setNotice(`Three alternatives restored from the ${data.market_session || "latest"} market-session cache.`);
      else if (reason === "portfolio_saved") setNotice("Portfolio saved. Default Risk-Controlled, Balanced, and Goal-Tilted analyses are ready.");
      else if (reason === "objectives_changed") setNotice("All three alternatives refreshed for the updated objective sliders.");
    } catch (error) { setNotice(error instanceof Error ? error.message : "Analysis unavailable."); }
    finally { setBusy(""); }
  }

  async function runOptimization() {
    await executeAnalysis();
  }

  function updateObjectiveProfile(nextProfile: Profile) {
    setProfile(nextProfile);
    if (!portfolioId || portfolioDirty) return;
    if (analysisRefreshTimer.current !== null) window.clearTimeout(analysisRefreshTimer.current);
    setNotice("Objective weights changed. Refreshing all three alternatives…");
    analysisRefreshTimer.current = window.setTimeout(() => {
      analysisRefreshTimer.current = null;
      void executeAnalysis(holdings, portfolioName, nextProfile, "objectives_changed");
    }, 700);
  }

  async function generateNarrative() {
    if (!analysis) return; setBusy("Preparing explanation");
    try {
      const response = await apiFetch(`${API}/analyses/${analysis.id}/explanation`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ provider: profile.llm_provider, endpoint: profile.llm_endpoint, model: profile.llm_model }) });
      const data = await response.json(); setNarrative(data.text); if (data.warning) setNotice(data.warning);
    } catch { setNarrative("The optional explanation layer is unavailable. All calculated results remain visible below."); }
    finally { setBusy(""); }
  }

  async function savePreferences(next: Preferences) {
    setPreferences(next);
    try {
      const response = await apiFetch(`${API}/preferences`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(next) });
      if (!response.ok) throw new Error("Unable to save layout");
      setPreferences(await response.json());
    } catch { setNotice("The widget layout changed on screen but could not be saved."); }
  }

  function toggleWidget(group: "macro_widgets" | "research_widgets", key: string) {
    const current = preferences[group];
    void savePreferences({ ...preferences, [group]: current.includes(key) ? current.filter(item => item !== key) : [...current, key] });
  }

  function saveTerminalWidgets(widgets: TerminalWidgetConfig[]) {
    void savePreferences({ ...preferences, terminal_widgets: widgets });
  }

  function addTerminalWidget(type: TerminalWidgetType) {
    if (preferences.terminal_widgets.some(widget => widget.type === type)) return;
    const item=terminalCatalog.find(widget => widget.type===type);
    saveTerminalWidgets([...preferences.terminal_widgets,{ id:`${type}-${Date.now()}`, type, size:item?.defaultSize||"wide" }]);
    setTerminalCatalogOpen(false);
  }

  function moveTerminalWidget(id: string, direction: -1 | 1) {
    const widgets=[...preferences.terminal_widgets]; const index=widgets.findIndex(widget=>widget.id===id); const target=index+direction;
    if(index<0||target<0||target>=widgets.length)return;
    [widgets[index],widgets[target]]=[widgets[target],widgets[index]]; saveTerminalWidgets(widgets);
  }

  function dropTerminalWidget(targetId: string) {
    if(!draggedTerminalWidget||draggedTerminalWidget===targetId)return;
    const widgets=[...preferences.terminal_widgets]; const from=widgets.findIndex(widget=>widget.id===draggedTerminalWidget); const to=widgets.findIndex(widget=>widget.id===targetId);
    if(from<0||to<0)return; const [moved]=widgets.splice(from,1); widgets.splice(to,0,moved); setDraggedTerminalWidget(null); saveTerminalWidgets(widgets);
  }

  function resizeTerminalWidget(id: string) {
    const order:TerminalWidgetConfig["size"][]=["small","wide","full"];
    saveTerminalWidgets(preferences.terminal_widgets.map(widget=>widget.id===id?{...widget,size:order[(order.indexOf(widget.size)+1)%order.length]}:widget));
  }

  async function saveGoal(goal: Goal) {
    setBusy("Saving plan"); setNotice("");
    try {
      const response=await apiFetch(goal.id?`${API}/plan/goals/${goal.id}`:`${API}/plan/goals`,{method:goal.id?"PUT":"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(goal)});
      if(!response.ok)throw new Error(await apiError(response,"Unable to save goal"));
      const saved=await response.json(); setGoals(items=>[...items.filter(item=>item.id!==saved.id),saved].sort((a,b)=>a.priority-b.priority));
      setNotice(`${saved.name} saved.`); await projectGoal(saved);
    } catch(error){setNotice(error instanceof Error?error.message:"Unable to save goal.");}
    finally{setBusy("");}
  }

  async function deleteGoal(goalId:string) {
    if(!window.confirm("Delete this goal?"))return;
    const response=await apiFetch(`${API}/plan/goals/${goalId}`,{method:"DELETE"});
    if(response.ok){setGoals(items=>items.filter(item=>item.id!==goalId));setGoalProjections(items=>{const next={...items};delete next[goalId];return next;});}
  }

  async function projectGoal(goal:Goal) {
    const response=await apiFetch(`${API}/plan/projections`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({goal,risk_tolerance:profile.risk_tolerance})});
    if(!response.ok)return; const projection=await response.json(); const key=goal.id||goal.name;
    setGoalProjections(items=>({...items,[key]:projection}));
  }

  async function refreshPlanGuidance(){
    try{const response=await apiFetch(`${API}/plan/guidance`);if(response.ok)setPlanGuidance(await response.json());}catch{/* Existing saved guidance remains visible. */}
  }

  async function saveInvestmentPolicy(approve=false){
    setBusy(approve?"Approving investment policy":"Saving investment policy");setNotice("");
    try{const response=await apiFetch(`${API}/plan/policy${approve?"/approve":""}`,{method:approve?"POST":"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify(investmentPolicy)});if(!response.ok)throw new Error(await apiError(response,"Unable to save policy"));const saved=await response.json();setInvestmentPolicy({...defaultPolicy,...saved});setNotice(approve?"Investment policy approved. Future guidance will be checked against it.":"Investment policy draft saved.");await refreshPlanGuidance();}
    catch(error){setNotice(error instanceof Error?error.message:"Unable to save policy.");}finally{setBusy("");}
  }

  async function savePlanProfile() {
    setBusy("Saving profile");
    try{const response=await apiFetch(`${API}/plan/profile`,{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify(profile)});if(!response.ok)throw new Error(await apiError(response,"Unable to save profile"));setProfile({...defaultProfile,...await response.json()});setNotice("Planning profile saved.");}
    catch(error){setNotice(error instanceof Error?error.message:"Unable to save profile.");}finally{setBusy("");}
  }

  async function saveTerminalLayout() {
    const existing=terminalLayouts.find(item=>item.id===selectedTerminalLayout); const name=window.prompt("Layout name",existing?.name||"Market research board");if(!name?.trim())return;
    const response=await apiFetch(existing?`${API}/terminal/layouts/${existing.id}`:`${API}/terminal/layouts`,{method:existing?"PUT":"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({name:name.trim(),widgets:preferences.terminal_widgets})});
    if(!response.ok){setNotice(await apiError(response,"Unable to save layout"));return;}const saved=await response.json();setTerminalLayouts(items=>[saved,...items.filter(item=>item.id!==saved.id)]);setSelectedTerminalLayout(saved.id);setNotice("Advanced layout saved.");
  }

  function openTerminalLayout(layout:TerminalLayout){setSelectedTerminalLayout(layout.id);saveTerminalWidgets(layout.widgets);}
  async function duplicateTerminalLayout(layout:TerminalLayout){const response=await apiFetch(`${API}/terminal/layouts`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({name:`${layout.name} copy`,widgets:layout.widgets})});if(response.ok){const saved=await response.json();setTerminalLayouts(items=>[saved,...items]);setSelectedTerminalLayout(saved.id);saveTerminalWidgets(saved.widgets);}}
  async function deleteTerminalLayout(layoutId:string){if(!window.confirm("Delete this manual terminal layout?"))return;const response=await apiFetch(`${API}/terminal/layouts/${layoutId}`,{method:"DELETE"});if(response.ok){setTerminalLayouts(items=>items.filter(item=>item.id!==layoutId));if(selectedTerminalLayout===layoutId)setSelectedTerminalLayout(null);}}

  async function dashboardStatus(jobId: string) {
    const response = await apiFetch(`${API}/dashboard/drafts/${jobId}`);
    if (!response.ok) throw new Error(await apiError(response, "Dashboard status unavailable"));
    const job: DashboardJob = await response.json();
    setDashboardJob(job);
    return job;
  }

  async function streamDashboard(jobId: string) {
    const maxReconnects = 4;
    for (let reconnect = 0; reconnect <= maxReconnects; reconnect += 1) {
      let streamError: unknown;
      try {
        const response = await apiFetch(`${API}/dashboard/drafts/${jobId}/events`);
        if (!response.ok || !response.body) throw new Error(await apiError(response, "Dashboard stream unavailable"));
        const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = ""; let terminal = false;
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const chunks = buffer.split("\n\n"); buffer = chunks.pop() || "";
          for (const chunk of chunks) {
            const event = chunk.split("\n").find(line => line.startsWith("event:"))?.slice(6).trim();
            const data = chunk.split("\n").find(line => line.startsWith("data:"))?.slice(5).trim();
            if (event === "dashboard" && data) {
              const job: DashboardJob = JSON.parse(data);
              setDashboardJob(job);
              terminal = DASHBOARD_TERMINAL_STATES.has(job.state);
            }
            if (event === "done") terminal = true;
          }
          if (terminal) { await reader.cancel(); return; }
        }
      } catch (error) {
        streamError = error;
      }

      try {
        const job = await dashboardStatus(jobId);
        if (DASHBOARD_TERMINAL_STATES.has(job.state)) return;
      } catch (statusError) {
        if (reconnect === maxReconnects) throw statusError;
      }
      if (reconnect === maxReconnects) {
        if (streamError instanceof Error) throw streamError;
        throw new Error("Dashboard connection ended before the job completed");
      }
      await new Promise(resolve => window.setTimeout(resolve, Math.min(4_000, 500 * 2 ** reconnect)));
    }
  }

  async function createAIDashboard(prompt = dashboardPrompt) {
    if (!prompt.trim() || dashboardBusy) return;
    setDashboardBusy(true); setDashboardPrompt(""); setSelectedDashboardView(null); setNotice("");
    try {
      const response = await apiFetch(`${API}/dashboard/drafts`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ prompt,conversation_id:dashboardSourceConversationId }) });
      if (!response.ok) throw new Error(await apiError(response, "Unable to create dashboard"));
      const job = await response.json(); setDashboardJob(job);
      await streamDashboard(job.id);
    } catch (error) { setNotice(error instanceof Error ? error.message : "Dashboard generation failed."); }
    finally { setDashboardBusy(false); }
  }

  async function refreshConversationList(workspace:"research"|"portfolio") {
    const response=await apiRequest(`/chat/conversations?workspace=${workspace}`);
    if(!response.ok)return [];
    const rows:ChatConversation[]=await response.json();
    if(workspace==="research")setResearchConversations(rows);else setPortfolioConversations(rows);
    return rows;
  }

  async function openChatConversation(workspace:"research"|"portfolio",conversationId:string) {
    const cached=conversationCache.current[workspace].get(conversationId);
    if(workspace==="research"){
      setResearchConversationId(conversationId);setResearchChatMessages(cached?.messages||[]);setResearchChatArtifacts(cached?.artifacts||[]);
    }else{
      setPortfolioConversationId(conversationId);setPortfolioChatMessages(cached?.messages||[]);setPortfolioChatArtifacts(cached?.artifacts||[]);
    }
    window.localStorage.setItem(`eagleeyes-${workspace}-conversation`,conversationId);
    const response=await apiRequest(`/chat/conversations/${conversationId}`);
    if(!response.ok){setNotice(await apiError(response,"Unable to open conversation"));return;}
    const detail=await response.json();
    if(detail.workspace!==workspace){setNotice("That conversation belongs to a different workspace.");return;}
    conversationCache.current[workspace].set(conversationId,{messages:detail.messages||[],artifacts:detail.artifacts||[]});
    if(window.localStorage.getItem(`eagleeyes-${workspace}-conversation`)!==conversationId)return;
    if(workspace==="research"){
      setResearchConversationId(conversationId);setResearchChatMessages(detail.messages||[]);setResearchChatArtifacts(detail.artifacts||[]);
    }else{
      setPortfolioConversationId(conversationId);setPortfolioChatMessages(detail.messages||[]);setPortfolioChatArtifacts(detail.artifacts||[]);
    }
    window.localStorage.setItem(`eagleeyes-${workspace}-conversation`,conversationId);
  }

  function newChatConversation(workspace:"research"|"portfolio") {
    window.localStorage.removeItem(`eagleeyes-${workspace}-conversation`);
    if(workspace==="research"){
      setResearchConversationId(null);setResearchChatMessages([]);setResearchChatArtifacts([]);setResearchChatQuestion("");
    }else{
      setPortfolioConversationId(null);setPortfolioChatMessages([]);setPortfolioChatArtifacts([]);setPortfolioChatQuestion("");
    }
  }

  async function renameChatConversation(workspace:"research"|"portfolio",conversationId:string) {
    const existing=(workspace==="research"?researchConversations:portfolioConversations).find(item=>item.id===conversationId);
    const title=window.prompt("Conversation name",existing?.title||"")?.trim();
    if(!title)return;
    const response=await apiRequest(`/chat/conversations/${conversationId}`,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify({title})});
    if(!response.ok){setNotice(await apiError(response,"Unable to rename conversation"));return;}
    await refreshConversationList(workspace);
  }

  async function deleteChatConversation(workspace:"research"|"portfolio",conversationId:string) {
    if(!window.confirm("Delete this conversation and its saved messages?"))return;
    const previousRows=workspace==="research"?researchConversations:portfolioConversations;
    const isCurrent=(workspace==="research"?researchConversationId:portfolioConversationId)===conversationId;
    const rows=previousRows.filter(item=>item.id!==conversationId);
    conversationCache.current[workspace].delete(conversationId);
    if(workspace==="research")setResearchConversations(rows);else setPortfolioConversations(rows);
    if(isCurrent){
      window.localStorage.removeItem(`eagleeyes-${workspace}-conversation`);
      if(workspace==="research"){setResearchConversationId(null);setResearchChatMessages([]);setResearchChatArtifacts([]);}
      else{setPortfolioConversationId(null);setPortfolioChatMessages([]);setPortfolioChatArtifacts([]);}
      if(rows[0])void openChatConversation(workspace,rows[0].id);
    }
    const response=await apiRequest(`/chat/conversations/${conversationId}`,{method:"DELETE"});
    if(!response.ok){
      if(workspace==="research")setResearchConversations(previousRows);else setPortfolioConversations(previousRows);
      setNotice(await apiError(response,"Unable to delete conversation"));
      return;
    }
    void refreshConversationList(workspace);
  }

  async function refreshConversationArtifacts(workspace:"research"|"portfolio",conversationId:string) {
    const response=await apiRequest(`/chat/conversations/${conversationId}`);if(!response.ok)return;
    const detail=await response.json();
    if(workspace==="research")setResearchChatArtifacts(detail.artifacts||[]);else setPortfolioChatArtifacts(detail.artifacts||[]);
  }

  function buildBoardFromConversation(workspace:"research"|"portfolio") {
    const id=workspace==="research"?researchConversationId:portfolioConversationId;
    if(!id)return;
    const item=(workspace==="research"?researchConversations:portfolioConversations).find(row=>row.id===id);
    setDashboardSourceConversationId(id);
    setDashboardPrompt(`Build a research dashboard that organizes the validated evidence from this ${workspace} conversation: ${item?.title||"saved conversation"}.`);
    navigate("ask");
  }

  async function askResearchChat(question = researchChatQuestion) {
    const cleanQuestion = question.trim();
    if (!cleanQuestion || researchChatBusy) return;
    const userMessage: ChatMessage = { role: "user", content: cleanQuestion };
    setResearchChatMessages(items => [...items, userMessage]);
    setResearchChatQuestion("");
    setResearchChatBusy(true);
    try {
      const currentUrl=new URL(window.location.href);
      const contextTicker=(currentUrl.searchParams.get("ticker")||"").toUpperCase()||undefined;
      const response = await apiRequest("/chat/messages", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: cleanQuestion, conversation_id: researchConversationId, workspace: "research", page_context:{route:`${currentUrl.pathname}${currentUrl.search}`,workspace:tab==="ask"?"ask":"research",entity_type:contextTicker?"security":undefined,ticker:contextTicker,enabled_context:askEnabledContext} }),
      });
      if (!response.ok) throw new Error(await apiError(response, "Unable to answer the research question"));
      const data = await response.json();
      setResearchConversationId(data.conversation_id || null);
      if(data.conversation_id)window.localStorage.setItem("eagleeyes-research-conversation",data.conversation_id);
      setResearchChatMessages(items => [...items, data.message]);
      void refreshConversationList("research");
      if(data.conversation_id)void refreshConversationArtifacts("research",data.conversation_id);
    } catch (error) {
      setResearchChatMessages(items => [...items, { role: "assistant", content: error instanceof Error ? error.message : "The research answer is temporarily unavailable." }]);
    } finally {
      setResearchChatBusy(false);
    }
  }

  async function askPortfolioChat(question = portfolioChatQuestion) {
    const cleanQuestion = question.trim();
    if (!cleanQuestion || portfolioChatBusy) return;
    setPortfolioChatMessages(items => [...items, { role: "user", content: cleanQuestion }]);
    setPortfolioChatQuestion("");
    setPortfolioChatBusy(true);
    try {
      const response = await apiRequest("/chat/messages", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: cleanQuestion, conversation_id: portfolioConversationId, workspace: "portfolio" }),
      });
      if (!response.ok) throw new Error(await apiError(response, "Unable to explain the portfolio analysis"));
      const data = await response.json();
      setPortfolioConversationId(data.conversation_id || null);
      if(data.conversation_id)window.localStorage.setItem("eagleeyes-portfolio-conversation",data.conversation_id);
      setPortfolioChatMessages(items => [...items, data.message]);
      void refreshConversationList("portfolio");
      if(data.conversation_id)void refreshConversationArtifacts("portfolio",data.conversation_id);
    } catch (error) {
      setPortfolioChatMessages(items => [...items, { role: "assistant", content: error instanceof Error ? error.message : "The model explanation is temporarily unavailable." }]);
    } finally {
      setPortfolioChatBusy(false);
    }
  }

  async function reviseAIDashboard(prompt: string) {
    if (!dashboardJob || !prompt.trim()) return;
    setDashboardBusy(true); setSelectedDashboardView(null);
    try {
      const response = await apiFetch(`${API}/dashboard/drafts/${dashboardJob.id}/revise`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ prompt }) });
      if (!response.ok) throw new Error(await apiError(response, "Unable to revise dashboard"));
      const job = await response.json(); setDashboardJob(job); await streamDashboard(job.id);
    } catch (error) { setNotice(error instanceof Error ? error.message : "Dashboard revision failed."); }
    finally { setDashboardBusy(false); }
  }

  async function cancelAIDashboard() {
    if (!dashboardJob) return;
    const response = await apiFetch(`${API}/dashboard/drafts/${dashboardJob.id}/cancel`, { method: "POST" });
    if (response.ok) setDashboardJob(await response.json());
  }

  async function saveAIDashboard() {
    if (!dashboardJob) return;
    const response = await apiFetch(`${API}/dashboard/drafts/${dashboardJob.id}/save`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: dashboardJob.specification?.title || "AI research view", layout: dashboardJob.specification?.widgets || [] }) });
    if (!response.ok) { setNotice(await apiError(response, "Unable to save dashboard")); return; }
    const saved = await response.json(); setDashboardViews(items => [saved, ...items.filter(item => item.id !== saved.id)]); setSelectedDashboardView(saved.id); setNotice("Dashboard view saved.");
  }

  async function openDashboardView(viewId: string) {
    const response = await apiFetch(`${API}/dashboard/views/${viewId}`);
    if (!response.ok) { setNotice(await apiError(response, "Unable to open saved view")); return; }
    const view: DashboardView = await response.json(); setSelectedDashboardView(view.id);
    const specification = adaptDashboardSpecification(view.specification) as DashboardSpec;
    setDashboardJob({ id: view.latest_run?.created_at || view.id, prompt: view.original_prompt, state: view.latest_run?.status || "COMPLETE", progress: 100, plan: view.plan, specification: { ...specification, widgets: view.layout?.length ? view.layout : specification.widgets }, widget_results: view.latest_run?.widget_results || [], narrative: view.latest_run?.narrative, warnings: view.latest_run?.warnings || [] });
  }

  async function refreshDashboardView(viewId: string) {
    setDashboardBusy(true);
    try {
      const response = await apiFetch(`${API}/dashboard/views/${viewId}/refresh`, { method: "POST" });
      if (!response.ok) throw new Error(await apiError(response, "Unable to refresh saved view"));
      const job = await response.json(); setDashboardJob(job); await streamDashboard(job.id);
    } catch (error) { setNotice(error instanceof Error ? error.message : "Dashboard refresh failed."); }
    finally { setDashboardBusy(false); }
  }

  async function renameDashboardView(viewId: string) {
    const current = dashboardViews.find(item => item.id === viewId); const name = window.prompt("Rename dashboard", current?.name || "");
    if (!name?.trim()) return;
    const response = await apiFetch(`${API}/dashboard/views/${viewId}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: name.trim() }) });
    if (response.ok) { const updated = await response.json(); setDashboardViews(items => items.map(item => item.id === viewId ? updated : item)); }
  }

  async function deleteDashboardView(viewId: string) {
    if (!window.confirm("Delete this saved dashboard view?")) return;
    const response = await apiFetch(`${API}/dashboard/views/${viewId}`, { method: "DELETE" });
    if (response.ok) { setDashboardViews(items => items.filter(item => item.id !== viewId)); if (selectedDashboardView === viewId) { setSelectedDashboardView(null); setDashboardJob(null); } }
  }

  async function duplicateDashboardView(viewId:string){
    const response=await apiFetch(`${API}/dashboard/views/${viewId}/duplicate`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({})});
    if(!response.ok){setNotice(await apiError(response,"Unable to duplicate dashboard"));return;}
    const duplicated:DashboardView=await response.json();setDashboardViews(items=>[duplicated,...items]);await openDashboardView(duplicated.id);setNotice("Dashboard duplicated with the same layout and compatible results.");
  }

  async function addDashboardWidget(widgetType: string) {
    if (!dashboardJob) return;
    setDashboardBusy(true); setNotice("");
    try {
      const target = selectedDashboardView ? `${API}/dashboard/views/${selectedDashboardView}/widgets` : `${API}/dashboard/drafts/${dashboardJob.id}/widgets`;
      const response = await apiFetch(target, { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({widget_type:widgetType}) });
      if(!response.ok) throw new Error(await apiError(response,"Unable to add data"));
      const job=await response.json(); setSelectedDashboardView(null); setDashboardJob(job); await streamDashboard(job.id);
    } catch(error){setNotice(error instanceof Error?error.message:"Unable to add data to this dashboard.");}
    finally{setDashboardBusy(false);}
  }

  async function mutateDashboardWidget(widgetId:string,operation:"move"|"resize"|"remove",options:{direction?:number;width?:number;height?:number}={}){
    if(!dashboardJob?.specification)return;
    const target=selectedDashboardView?`${API}/dashboard/views/${selectedDashboardView}/layout/widgets/${widgetId}`:`${API}/dashboard/drafts/${dashboardJob.id}/layout/widgets/${widgetId}`;
    const response=await apiFetch(target,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify({operation,...options})});
    if(!response.ok){setNotice(await apiError(response,"Unable to update widget layout"));return;}
    if(selectedDashboardView){const view:DashboardView=await response.json();setDashboardViews(items=>items.map(item=>item.id===view.id?view:item));await openDashboardView(view.id);}
    else setDashboardJob(await response.json());
  }

  function moveDashboardWidget(widgetId: string, direction: -1 | 1) {
    if (!dashboardJob?.specification) return;
    const widgets = [...dashboardJob.specification.widgets]; const index = widgets.findIndex(widget => widget.id === widgetId); const target = index + direction;
    if (index < 0 || target < 0 || target >= widgets.length) return;
    [widgets[index], widgets[target]] = [widgets[target], widgets[index]];
    setDashboardJob({ ...dashboardJob, specification: { ...dashboardJob.specification, widgets } });
    void mutateDashboardWidget(widgetId,"move",{direction});
  }

  function resizeDashboardWidget(widgetId:string,width:number,height:number){void mutateDashboardWidget(widgetId,"resize",{width,height});}
  function removeDashboardWidget(widgetId:string){if(window.confirm("Remove this widget from the board?"))void mutateDashboardWidget(widgetId,"remove");}

  const currentWeightTotal = holdings.reduce((sum, item) => sum + (Number(item.weight) || 0), 0);
  const sortedResearch = useMemo(() => [...research].sort((a, b) => Number(b[sortKey] || 0) - Number(a[sortKey] || 0)), [research, sortKey]);

  function navigate(next: Tab) {
    if (tab === "portfolio" && next !== "portfolio" && portfolioDirty && !window.confirm("You have unsaved portfolio changes. Leave without saving?")) return;
    setNotice(""); if(next==="learn"){setLearningModule(undefined);setLearningLesson(undefined);} setTab(next); window.history.pushState({},"",pathForTab(next));
  }

  function navigatePortfolio(view:PortfolioView){setNotice("");setPortfolioView(view);setTab("portfolio");window.history.pushState({},"",`/portfolio?view=${view}`);}
  function navigateExplore(view:ExploreView){setNotice("");setExploreView(view);setTab("explore");window.history.pushState({},"",`/research?view=${view}`);}
  function navigateAdvanced(view:AdvancedView){setNotice("");setAdvancedView(view);setTab("advanced");window.history.pushState({},"",`/advanced?view=${view}`);}
  function navigateLearn(module?:string,lesson?:string){setNotice("");setLearningModule(module);setLearningLesson(lesson);setTab("learn");window.history.pushState({},"",module&&lesson?`/learn/${module}/${lesson}`:"/learn");}
  function navigateDeepLink(path:string){const url=new URL(path,window.location.origin);const route=resolveAppRoute(url.pathname,url.search);if(!route)return;setNotice("");setTab(route.tab);if(route.exploreView)setExploreView(route.exploreView);if(route.portfolioView)setPortfolioView(route.portfolioView);if(route.advancedView)setAdvancedView(route.advancedView);setLearningModule(route.learningModule);setLearningLesson(route.learningLesson);window.history.pushState({},"",`${url.pathname}${url.search}`);}

  return (
    <AppShell activeTab={tab} density={preferences.density} connected={connected} dark={dark} email={email} freshness={macro.as_of || "Awaiting refresh"} presentationLevel={preferences.presentation_level} onNavigate={navigate} onPresentationLevel={level=>void savePreferences({...preferences,presentation_level:level})} onToggleTheme={toggleTheme} onSignOut={onSignOut} onLearnConcept={navigateLearn} onDismissNotice={()=>setNotice("")} status={busy} notice={notice}
      topAction={tab==="learn"?<button className="widget-button" onClick={()=>navigateExplore("stocks")}>Open Research →</button>:tab==="decisions"?<button className="primary" onClick={()=>navigatePortfolio("holdings")}>Review portfolio <span>→</span></button>:<>{tab==="advanced"&&advancedView==="terminal"?<button className="widget-button" onClick={()=>setTerminalCatalogOpen(true)}>＋ Add widget</button>:<button className="widget-button" onClick={()=>setCustomizing(!customizing)}>View settings</button>}<button className="primary" onClick={() => navigatePortfolio("analysis")}>Run analysis <span>→</span></button></>}
      drawer={customizing ? <div className="widget-drawer"><div><strong>Macro evidence</strong>{["rates","inflation","growth","labor","credit"].map(key => <label key={key}><input type="checkbox" checked={preferences.macro_widgets.includes(key)} onChange={() => toggleWidget("macro_widgets", key)} />{key}</label>)}</div><div><strong>Security evidence</strong>{["market","scores","fundamentals","news","prediction_markets"].map(key => <label key={key}><input type="checkbox" checked={preferences.research_widgets.includes(key)} onChange={() => toggleWidget("research_widgets", key)} />{key.replaceAll("_", " ")}</label>)}</div><label>Density<select value={preferences.density} onChange={event => void savePreferences({ ...preferences, density: event.target.value as Preferences["density"] })}><option value="comfortable">Comfortable</option><option value="compact">Compact</option></select></label></div> : undefined}>
        {tab === "today" && <TodayPage loading={loading} refreshing={busy === "Refreshing market and macro data"} briefing={homeBriefing} hasSavedPortfolio={holdings.length>0} macroFactors={macroFactors.filter(item => preferences.macro_widgets.includes(item.key))} dataStatus={dataStatus} onRefresh={refreshToday} onNavigate={navigate} onExplore={navigateExplore} onPortfolio={navigatePortfolio} onAdvanced={navigateAdvanced} request={apiRequest} />}
        {tab === "plan" && <PlanPage profile={profile} setProfile={setProfile} goals={goals} projections={goalProjections} policy={investmentPolicy} setPolicy={setInvestmentPolicy} guidance={planGuidance} onSavePolicy={()=>saveInvestmentPolicy(false)} onApprovePolicy={()=>saveInvestmentPolicy(true)} onSaveProfile={savePlanProfile} onSaveGoal={saveGoal} onDeleteGoal={deleteGoal} onProject={projectGoal} onOpenPortfolio={()=>navigatePortfolio("analysis")} />}
        {tab === "portfolio" && <PortfolioPage view={portfolioView} setView={navigatePortfolio} request={apiRequest} portfolioId={portfolioId} portfolios={portfolios} onSelectPortfolio={id=>void selectPortfolio(id)} onNewPortfolio={newPortfolio} holdings={holdings} setHoldings={setHoldings} name={portfolioName} setName={setPortfolioName} total={currentWeightTotal} dirty={portfolioDirty} errors={portfolioErrors} saving={busy === "Saving portfolio"} onSave={savePortfolio} onImport={importCsv} profile={profile} goals={goals} setProfile={setProfile} onObjectiveProfileChange={updateObjectiveProfile} analysis={analysis} monitoring={monitoring} guidance={planGuidance} diagnostics={portfolioDiagnostics} performance={terminalPerformance} presentationLevel={preferences.presentation_level} selected={selectedAlternative} setSelected={setSelectedAlternative} onRun={runOptimization} analysisBusy={busy === "Running scenario analysis"} narrative={narrative} onNarrative={generateNarrative} portfolioChatMessages={portfolioChatMessages} portfolioChatQuestion={portfolioChatQuestion} setPortfolioChatQuestion={setPortfolioChatQuestion} onAskPortfolio={askPortfolioChat} portfolioChatBusy={portfolioChatBusy} portfolioConversationControls={{conversations:portfolioConversations,currentId:portfolioConversationId,artifacts:portfolioChatArtifacts,onNew:()=>void newChatConversation("portfolio"),onOpen:id=>void openChatConversation("portfolio",id),onRename:id=>void renameChatConversation("portfolio",id),onDelete:id=>void deleteChatConversation("portfolio",id),onBuildBoard:()=>buildBoardFromConversation("portfolio")}} />}
        {tab === "decisions" && <DecisionsPage request={apiRequest} holdings={holdings} profile={profile} goals={goals} onOpenPortfolio={()=>navigatePortfolio("holdings")} />}
        {tab === "climate" && <MarketClimatePage macro={macro} factors={macroFactors} scenarios={scenarios} regimeHistory={regimeHistory} request={apiRequest} onRefresh={refreshMarkets} onAsk={question=>{setResearchChatQuestion(question);navigate("ask");}} />}
        {tab === "explore" && <ExplorePage view={exploreView} setView={navigateExplore} request={(path,init)=>apiFetch(`${API}${path}`,init)} onManageUniverse={()=>navigatePortfolio("holdings")} scenarios={scenarios} contracts={contracts} fetchedAt={scenarioFetchedAt} regimeHistory={regimeHistory} warnings={scenarioWarnings} onRefreshMarkets={refreshMarkets} rows={sortedResearch} holdings={holdings} profile={profile} presentationLevel={preferences.presentation_level} sortKey={sortKey} setSortKey={setSortKey} onRefreshResearch={refreshResearch} widgets={preferences.research_widgets} macro={macro} macroFactors={macroFactors} watchlist={profile.watchlist} researchChatMessages={researchChatMessages} researchChatQuestion={researchChatQuestion} setResearchChatQuestion={setResearchChatQuestion} onAskResearch={askResearchChat} researchChatBusy={researchChatBusy} researchConversationControls={{conversations:researchConversations,currentId:researchConversationId,artifacts:researchChatArtifacts,onNew:()=>void newChatConversation("research"),onOpen:id=>void openChatConversation("research",id),onRename:id=>void renameChatConversation("research",id),onDelete:id=>void deleteChatConversation("research",id),onBuildBoard:()=>buildBoardFromConversation("research")}} />}
        {tab === "learn" && <LearnPage request={apiRequest} moduleSlug={learningModule} lessonId={learningLesson} onOpenLesson={navigateLearn} onOpenHub={()=>navigateLearn()} onDeepLink={navigateDeepLink} />}
        {tab === "ask" && <AskPage messages={researchChatMessages} question={researchChatQuestion} setQuestion={setResearchChatQuestion} onSend={askResearchChat} loading={researchChatBusy} controls={{conversations:researchConversations,currentId:researchConversationId,artifacts:researchChatArtifacts,onNew:()=>void newChatConversation("research"),onOpen:id=>void openChatConversation("research",id),onRename:id=>void renameChatConversation("research",id),onDelete:id=>void deleteChatConversation("research",id),onBuildBoard:()=>buildBoardFromConversation("research")}} contextTicker={new URL(window.location.href).searchParams.get("ticker")} enabledContext={askEnabledContext} onToggleContext={key=>setAskEnabledContext(items=>items.includes(key)?items.filter(item=>item!==key):[...items,key])} job={dashboardJob} views={dashboardViews} catalog={dashboardCatalog} selectedView={selectedDashboardView} prompt={dashboardPrompt} setPrompt={setDashboardPrompt} busy={dashboardBusy} presentationLevel={preferences.presentation_level} onCreate={createAIDashboard} onRevise={reviseAIDashboard} onCancel={cancelAIDashboard} onSave={saveAIDashboard} onDiscard={() => { setDashboardJob(null); setSelectedDashboardView(null); setDashboardSourceConversationId(null); }} onOpenView={openDashboardView} onRefreshView={refreshDashboardView} onDuplicateView={duplicateDashboardView} onRenameView={renameDashboardView} onDeleteView={deleteDashboardView} onMoveWidget={moveDashboardWidget} onResizeWidget={resizeDashboardWidget} onRemoveWidget={removeDashboardWidget} onAddWidget={addDashboardWidget} />}
        {tab === "advanced" && <AdvancedPage view={advancedView} setView={navigateAdvanced} layouts={terminalLayouts} selectedLayout={selectedTerminalLayout} onOpenLayout={openTerminalLayout} onSaveLayout={saveTerminalLayout} onDuplicateLayout={duplicateTerminalLayout} onDeleteLayout={deleteTerminalLayout} terminal={<ResearchTerminal widgets={preferences.terminal_widgets} catalogOpen={terminalCatalogOpen} setCatalogOpen={setTerminalCatalogOpen} onAdd={addTerminalWidget} onRemove={id=>saveTerminalWidgets(preferences.terminal_widgets.filter(widget=>widget.id!==id))} onMove={moveTerminalWidget} onResize={resizeTerminalWidget} onReset={()=>saveTerminalWidgets(defaultTerminalWidgets)} dragged={draggedTerminalWidget} setDragged={setDraggedTerminalWidget} onDrop={dropTerminalWidget} performance={terminalPerformance} holdings={holdings} macro={macro} macroFactors={macroFactors} marketIndicators={terminalMarketIndicators} scenarios={scenarios} contracts={contracts} research={research} analysis={analysis} monitoring={monitoring} dataStatus={dataStatus} selectedTicker={terminalTicker} setSelectedTicker={setTerminalTicker} contractSearch={terminalContractSearch} setContractSearch={setTerminalContractSearch} />} analysis={analysis} monitoring={monitoring} dataStatus={dataStatus} regimeHistory={regimeHistory} request={apiRequest} />}
    </AppShell>
  );
}

function cleanHolding(row: Holding) { const output: Record<string, unknown> = { ticker: row.ticker.toUpperCase(), account_type: row.account_type }; (["shares","weight","market_value","cost_basis","acquisition_date"] as const).forEach(key => { if (row[key] !== null && row[key] !== undefined && row[key] !== "") output[key] = row[key]; }); return output; }
function portfolioSignature(name: string, holdings: Holding[]) { return JSON.stringify({ name: name.trim(), holdings: holdings.map(cleanHolding) }); }
function validatePortfolio(name: string, holdings: Holding[]) {
  const errors: string[] = [];
  if (!name.trim()) errors.push("Portfolio name is required.");
  if (!holdings.length) errors.push("Add at least one holding.");
  const tickers = holdings.map(row => row.ticker.trim().toUpperCase());
  const duplicates = [...new Set(tickers.filter((ticker, index) => ticker && tickers.indexOf(ticker) !== index))];
  if (duplicates.length) errors.push(`Duplicate ticker${duplicates.length === 1 ? "" : "s"}: ${duplicates.join(", ")}. Combine each ticker into one row.`);
  holdings.forEach((row, index) => {
    const ticker = row.ticker.trim().toUpperCase();
    if (!ticker) errors.push(`Row ${index + 1}: ticker is required.`);
    else if (!/^[A-Z][A-Z0-9.-]{0,9}$/.test(ticker)) errors.push(`Row ${index + 1}: ${ticker} is not a valid ticker format.`);
    if (row.shares == null && row.weight == null && row.market_value == null) errors.push(`Row ${index + 1}: provide shares, weight, or market value.`);
    if (row.weight != null && (row.weight < 0 || row.weight > 1)) errors.push(`Row ${index + 1}: weight must be between 0% and 100%.`);
  });
  return errors;
}
function formatApiDetail(detail: unknown) { if (typeof detail === "string") return detail; if (Array.isArray(detail)) return detail.map(item => typeof item?.msg === "string" ? `${item.loc?.at(-1) || "field"}: ${item.msg}` : String(item)).join(" · "); return ""; }
async function apiError(response: Response, fallback: string) { try { const data = await response.json(); return formatApiDetail(data.detail) || fallback; } catch { return fallback; } }

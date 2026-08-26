"use client";

import { type ComponentProps, useEffect, useRef, useState } from "react";
import { AIWorkspace, ResearchChat, type ChatMessage, type ConversationControls } from "../shared/workspace-implementations";

type DashboardProps = ComponentProps<typeof AIWorkspace>;
type CanvasState = "closed" | "open";

type AskProps = DashboardProps & {
  messages: ChatMessage[];
  question: string;
  setQuestion: (value: string) => void;
  onSend: (question?: string) => void;
  loading: boolean;
  controls: ConversationControls;
  contextTicker?: string | null;
  enabledContext: string[];
  onToggleContext: (key: "evidence" | "thesis" | "portfolio") => void;
};

export function shouldOpenCanvasForQuestion(question: string, hasAnalysis: boolean) {
  const value = question.trim().toLowerCase();
  if (!value) return false;
  if (/\b(dashboard|chart|graph|plot|visual(?:ize|ise|ly|ization|isation)?|heatmap|canvas|widget)\b/.test(value)) return true;
  if (/\b(compare|comparison)\b.*\btable\b|\btable\b.*\b(compare|comparison)\b/.test(value)) return true;
  if (/\b(show|display|open|view)\b.*\b(performance|return|exposure|allocation|drawdown|analysis|research view|risk view|portfolio view|portfolio risk)\b/.test(value)) return true;
  if (hasAnalysis && /\b(add|remove|delete|move|resize|bigger|smaller|wider|underneath|above|below|rename|save|undo|revert|refresh|duplicate)\b/.test(value)) return true;
  if (hasAnalysis && /\b(make that|change that|compare against|benchmark against)\b/.test(value)) return true;
  return false;
}

export function AskPage({ messages, question, setQuestion, onSend, loading, controls, contextTicker, enabledContext, onToggleContext, ...dashboardProps }: AskProps) {
  const pendingQuestionRef = useRef<string | null>(null);
  const [canvasState, setCanvasState] = useState<CanvasState>("closed");
  const [historyOpen, setHistoryOpen] = useState(false);
  const [mobilePane, setMobilePane] = useState<"chat" | "analysis">("chat");

  const dashboardArtifact = controls.artifacts.find(artifact => artifact.artifact_type === "dashboard_view");
  const hasAnalysis = Boolean(dashboardProps.job || dashboardArtifact);
  const activeView = dashboardProps.views.find(view => view.id === dashboardProps.selectedView);
  const analysisLabel = activeView?.name || dashboardProps.job?.specification?.title || dashboardArtifact?.label || "Analysis";
  const canvasOpen = canvasState === "open";
  const researchSection = typeof window === "undefined" ? null : new URL(window.location.href).searchParams.get("research_section");

  useEffect(() => {
    const latest = messages.at(-1);
    const operation = latest?.role === "assistant" ? latest.structured_content?.dashboard_operation : undefined;
    if (!pendingQuestionRef.current || operation?.action_result?.status !== "SUCCESS") return;
    pendingQuestionRef.current = null;
    const task = window.setTimeout(openCanvas, 0);
    return () => window.clearTimeout(task);
  }, [messages]);

  function openCanvas() {
    setCanvasState("open");
    setMobilePane("analysis");
  }

  function closeCanvas() {
    setCanvasState("closed");
    setMobilePane("chat");
  }

  function sendFromChat(value?: string) {
    const request = value ?? question;
    const visualRequest = shouldOpenCanvasForQuestion(request, hasAnalysis);
    pendingQuestionRef.current = visualRequest ? request : null;
    if (visualRequest) openCanvas();
    onSend(value);
  }

  const workspaceControls: ConversationControls = {
    ...controls,
    onNew: () => { pendingQuestionRef.current = null; setHistoryOpen(false); closeCanvas(); controls.onNew(); },
    onOpen: id => { pendingQuestionRef.current = null; setHistoryOpen(false); closeCanvas(); controls.onOpen(id); },
    onBuildBoard: () => {
      setHistoryOpen(false);
      controls.onBuildBoard();
      openCanvas();
      onSend("Build a research dashboard from the validated evidence in this conversation.");
    },
    onOpenArtifact: artifact => { setHistoryOpen(false); controls.onOpenArtifact?.(artifact); openCanvas(); },
  };

  return <main className={`ask-decision-workspace ask-conversational-workspace canvas-${canvasState}`}>
    <header className="ask-workspace-header">
      <div className="ask-workspace-title"><span>Ask EagleEyes</span><strong>{contextTicker ? `Analyzing ${contextTicker}` : "Investment research assistant"}</strong></div>
      <div className="ask-context-controls" aria-label="Answer context">
        {(["evidence", "thesis", "portfolio"] as const).map(key => <label key={key}>
          <input type="checkbox" checked={enabledContext.includes(key)} onChange={() => onToggleContext(key)} />
          {key === "evidence" ? "Latest evidence" : key === "thesis" ? "Saved thesis" : "Portfolio context"}
        </label>)}
      </div>
      <div className="ask-header-actions">
        {contextTicker && researchSection && <a className="ask-open-analysis" href={`/research?ticker=${encodeURIComponent(contextTicker)}#${encodeURIComponent(researchSection === "market_data" ? "technicals" : researchSection === "portfolio_fit" ? "portfolio" : researchSection === "catalysts_risks" ? "catalysts" : researchSection)}`}>Back to Research ↩</a>}
        {hasAnalysis && !canvasOpen && <button className="ask-open-analysis" onClick={openCanvas}>{analysisLabel} ↗</button>}
        <button aria-expanded={historyOpen} aria-controls="ask-history-drawer" onClick={() => setHistoryOpen(value => !value)}>History</button>
        <button onClick={workspaceControls.onNew}>New chat</button>
      </div>
    </header>

    <div className="ask-content-shell">
      {canvasOpen && <nav className="ask-mobile-pane-tabs" aria-label="Ask workspace view">
        <button className={mobilePane === "chat" ? "active" : ""} aria-pressed={mobilePane === "chat"} onClick={() => setMobilePane("chat")}>Chat</button>
        <button className={mobilePane === "analysis" ? "active" : ""} aria-pressed={mobilePane === "analysis"} onClick={() => setMobilePane("analysis")}>Analysis</button>
      </nav>}
      <section className={`ask-chat-pane ${mobilePane === "chat" ? "mobile-active" : ""}`} aria-label="Conversation">
        <ResearchChat messages={messages} question={question} setQuestion={setQuestion} onSend={sendFromChat} loading={loading} controls={workspaceControls} variant="workspace" historyOpen={historyOpen} onCloseHistory={() => setHistoryOpen(false)} canvasOpen={canvasOpen} analysisLabel={analysisLabel} onOpenAnalysis={hasAnalysis ? openCanvas : undefined} />
      </section>
      {canvasOpen && <section className={`ask-canvas-pane ${mobilePane === "analysis" ? "mobile-active" : ""}`} aria-label="Analysis canvas">
          <AIWorkspace {...dashboardProps} variant="canvas" onClose={closeCanvas} onRequestAnalysisRefresh={() => sendFromChat("Refresh this analysis using the latest verified data.")} />
        </section>}
    </div>
  </main>;
}

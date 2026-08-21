"use client";

import { type ComponentProps, type CSSProperties, type PointerEvent as ReactPointerEvent, useEffect, useRef, useState } from "react";
import { AIWorkspace, ResearchChat, type ChatMessage, type ConversationControls } from "../shared/workspace-implementations";

type DashboardProps = ComponentProps<typeof AIWorkspace>;
type MobilePane = "chat" | "analysis";
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

const SPLIT_STORAGE_KEY = "eagleeyes-ask-chat-width";
const MIN_CHAT_WIDTH = 32;
const MAX_CHAT_WIDTH = 48;

function clampChatWidth(value: number) {
  return Math.min(MAX_CHAT_WIDTH, Math.max(MIN_CHAT_WIDTH, value));
}

export function shouldOpenCanvasForQuestion(question: string, hasAnalysis: boolean) {
  const value = question.trim().toLowerCase();
  if (!value) return false;
  if (/\b(dashboard|chart|graph|plot|visual(?:ize|ise|ly|ization|isation)?|heatmap|canvas|widget)\b/.test(value)) return true;
  if (/\b(compare|comparison)\b.*\btable\b|\btable\b.*\b(compare|comparison)\b/.test(value)) return true;
  if (/\b(show|display|open|view)\b.*\b(performance|exposure|allocation|drawdown|analysis|research view|risk view|portfolio view)\b/.test(value)) return true;
  if (hasAnalysis && /\b(add|remove|delete|move|resize|bigger|smaller|wider|underneath|above|below|rename|save|undo|revert|refresh|duplicate)\b/.test(value)) return true;
  if (hasAnalysis && /\b(make that|change that|compare against|benchmark against)\b/.test(value)) return true;
  return false;
}

export function AskPage({ messages, question, setQuestion, onSend, loading, controls, contextTicker, enabledContext, onToggleContext, ...dashboardProps }: AskProps) {
  const shellRef = useRef<HTMLDivElement>(null);
  const pendingQuestionRef = useRef<string | null>(null);
  const [chatWidth, setChatWidth] = useState(38);
  const [canvasState, setCanvasState] = useState<CanvasState>("closed");
  const [mobilePane, setMobilePane] = useState<MobilePane>("chat");
  const [historyOpen, setHistoryOpen] = useState(false);

  useEffect(() => {
    const task = window.setTimeout(() => {
      const saved = Number(window.localStorage.getItem(SPLIT_STORAGE_KEY));
      if (Number.isFinite(saved) && saved > 0) setChatWidth(clampChatWidth(saved));
    }, 0);
    return () => window.clearTimeout(task);
  }, []);

  const dashboardArtifact = controls.artifacts.find(artifact => artifact.artifact_type === "dashboard_view");
  const hasAnalysis = Boolean(dashboardProps.job || dashboardArtifact);
  const activeView = dashboardProps.views.find(view => view.id === dashboardProps.selectedView);
  const analysisLabel = activeView?.name || dashboardProps.job?.specification?.title || dashboardArtifact?.label || "Analysis";
  const canvasOpen = canvasState === "open";

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
    pendingQuestionRef.current = request;
    if (shouldOpenCanvasForQuestion(request, hasAnalysis)) openCanvas();
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

  function updateChatWidth(value: number) {
    const next = clampChatWidth(value);
    setChatWidth(next);
    window.localStorage.setItem(SPLIT_STORAGE_KEY, String(next));
  }

  function beginResize(event: ReactPointerEvent<HTMLButtonElement>) {
    if (!shellRef.current) return;
    event.preventDefault();
    const bounds = shellRef.current.getBoundingClientRect();
    const move = (pointerEvent: PointerEvent) => updateChatWidth(((pointerEvent.clientX - bounds.left) / bounds.width) * 100);
    const stop = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", stop);
      document.body.classList.remove("ask-resizing");
    };
    document.body.classList.add("ask-resizing");
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", stop, { once: true });
  }

  const splitStyle = { "--ask-chat-width": `${chatWidth}%` } as CSSProperties;

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
        {hasAnalysis && !canvasOpen && <button className="ask-open-analysis" onClick={openCanvas}>{analysisLabel} ↗</button>}
        <button aria-expanded={historyOpen} aria-controls="ask-history-drawer" onClick={() => setHistoryOpen(value => !value)}>History</button>
        <button onClick={workspaceControls.onNew}>New chat</button>
      </div>
    </header>

    {canvasOpen && <div className="ask-mobile-tabs" role="tablist" aria-label="Ask workspace view">
      <button role="tab" aria-selected={mobilePane === "chat"} className={mobilePane === "chat" ? "active" : ""} onClick={() => setMobilePane("chat")}>Chat</button>
      <button role="tab" aria-selected={mobilePane === "analysis"} className={mobilePane === "analysis" ? "active" : ""} onClick={() => setMobilePane("analysis")}>Analysis</button>
    </div>}

    <div ref={shellRef} className="ask-split-shell" style={splitStyle}>
      <section className={`ask-chat-pane ${mobilePane === "chat" ? "mobile-active" : ""}`} aria-label="Conversation">
        <ResearchChat messages={messages} question={question} setQuestion={setQuestion} onSend={sendFromChat} loading={loading} controls={workspaceControls} variant="workspace" historyOpen={historyOpen} onCloseHistory={() => setHistoryOpen(false)} canvasOpen={canvasOpen} analysisLabel={analysisLabel} onOpenAnalysis={hasAnalysis ? openCanvas : undefined} />
      </section>
      {canvasOpen && <>
        <button type="button" className="ask-split-divider" role="separator" aria-label="Resize chat and analysis" aria-orientation="vertical" aria-valuemin={MIN_CHAT_WIDTH} aria-valuemax={MAX_CHAT_WIDTH} aria-valuenow={Math.round(chatWidth)} onPointerDown={beginResize} onKeyDown={event => {
          if (event.key === "ArrowLeft") { event.preventDefault(); updateChatWidth(chatWidth - 2); }
          if (event.key === "ArrowRight") { event.preventDefault(); updateChatWidth(chatWidth + 2); }
          if (event.key === "Home") { event.preventDefault(); updateChatWidth(MIN_CHAT_WIDTH); }
          if (event.key === "End") { event.preventDefault(); updateChatWidth(MAX_CHAT_WIDTH); }
        }}><span /></button>
        <section className={`ask-canvas-pane ${mobilePane === "analysis" ? "mobile-active" : ""}`} aria-label="Analysis canvas">
          <AIWorkspace {...dashboardProps} variant="canvas" onClose={closeCanvas} />
        </section>
      </>}
    </div>
  </main>;
}

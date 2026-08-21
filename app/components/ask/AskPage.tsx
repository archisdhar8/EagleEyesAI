"use client";

import { type ComponentProps, type CSSProperties, type PointerEvent as ReactPointerEvent, useEffect, useRef, useState } from "react";
import {
  AIWorkspace,
  ResearchChat,
  type ChatMessage,
  type ConversationControls,
} from "../shared/workspace-implementations";

type DashboardProps = ComponentProps<typeof AIWorkspace>;
type MobilePane = "chat" | "dashboard";

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
const MIN_CHAT_WIDTH = 28;
const MAX_CHAT_WIDTH = 52;

function clampChatWidth(value: number) {
  return Math.min(MAX_CHAT_WIDTH, Math.max(MIN_CHAT_WIDTH, value));
}

export function AskPage({
  messages, question, setQuestion, onSend, loading, controls, contextTicker,
  enabledContext, onToggleContext, ...dashboardProps
}: AskProps) {
  const shellRef = useRef<HTMLDivElement>(null);
  const [chatWidth, setChatWidth] = useState(35);
  const [mobilePane, setMobilePane] = useState<MobilePane>("chat");

  useEffect(() => {
    const task = window.setTimeout(() => {
      const saved = Number(window.localStorage.getItem(SPLIT_STORAGE_KEY));
      if (Number.isFinite(saved) && saved > 0) setChatWidth(clampChatWidth(saved));
    }, 0);
    return () => window.clearTimeout(task);
  }, []);

  const workspaceControls: ConversationControls = {
    ...controls,
    onBuildBoard: () => { controls.onBuildBoard(); setMobilePane("dashboard"); },
    onOpenArtifact: artifact => { controls.onOpenArtifact?.(artifact); setMobilePane("dashboard"); },
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

  return <main className="ask-decision-workspace ask-conversational-workspace">
    <section className="ask-context-bar" aria-label="Answer context">
      <div><span>Ask EagleEyes</span><strong>{contextTicker ? `Analyzing ${contextTicker}` : "Conversational financial workspace"}</strong></div>
      <div className="ask-context-controls">
        {(["evidence", "thesis", "portfolio"] as const).map(key => <label key={key}>
          <input type="checkbox" checked={enabledContext.includes(key)} onChange={() => onToggleContext(key)} />
          {key === "evidence" ? "Latest evidence" : key === "thesis" ? "Saved thesis" : "Portfolio context"}
        </label>)}
      </div>
      <small>Enabled context is used for answers and attached analysis.</small>
    </section>

    <div className="ask-mobile-tabs" role="tablist" aria-label="Ask workspace view">
      <button role="tab" aria-selected={mobilePane === "chat"} className={mobilePane === "chat" ? "active" : ""} onClick={() => setMobilePane("chat")}>Chat</button>
      <button role="tab" aria-selected={mobilePane === "dashboard"} className={mobilePane === "dashboard" ? "active" : ""} onClick={() => setMobilePane("dashboard")}>Dashboard</button>
    </div>

    <div ref={shellRef} className="ask-split-shell" style={splitStyle}>
      <section className={`ask-chat-pane ${mobilePane === "chat" ? "mobile-active" : ""}`} aria-label="Conversation">
        <ResearchChat messages={messages} question={question} setQuestion={setQuestion} onSend={onSend} loading={loading} controls={workspaceControls} variant="workspace" />
      </section>
      <button type="button" className="ask-split-divider" role="separator" aria-label="Resize chat and dashboard" aria-orientation="vertical" aria-valuemin={MIN_CHAT_WIDTH} aria-valuemax={MAX_CHAT_WIDTH} aria-valuenow={Math.round(chatWidth)} onPointerDown={beginResize} onKeyDown={event => {
        if (event.key === "ArrowLeft") { event.preventDefault(); updateChatWidth(chatWidth - 2); }
        if (event.key === "ArrowRight") { event.preventDefault(); updateChatWidth(chatWidth + 2); }
        if (event.key === "Home") { event.preventDefault(); updateChatWidth(MIN_CHAT_WIDTH); }
        if (event.key === "End") { event.preventDefault(); updateChatWidth(MAX_CHAT_WIDTH); }
      }}><span /></button>
      <section className={`ask-canvas-pane ${mobilePane === "dashboard" ? "mobile-active" : ""}`} aria-label="Analysis canvas">
        <AIWorkspace {...dashboardProps} variant="canvas" />
      </section>
    </div>
  </main>;
}

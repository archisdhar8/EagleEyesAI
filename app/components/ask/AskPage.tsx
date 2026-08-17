"use client";

import type { ComponentProps } from "react";
import {
  AIWorkspace,
  ResearchChat,
  type ChatMessage,
  type ConversationControls,
} from "../shared/workspace-implementations";

type DashboardProps = ComponentProps<typeof AIWorkspace>;

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

export function AskPage({
  messages, question, setQuestion, onSend, loading, controls, contextTicker,
  enabledContext, onToggleContext, ...dashboardProps
}: AskProps) {
  return <div className="ask-decision-workspace">
    <section className="ask-context-bar" aria-label="Answer context">
      <div><span>Answer context</span><strong>{contextTicker ? `Analyzing ${contextTicker}` : "No company page selected"}</strong></div>
      <div className="ask-context-controls">
        {(["evidence", "thesis", "portfolio"] as const).map(key => <label key={key}>
          <input type="checkbox" checked={enabledContext.includes(key)} onChange={() => onToggleContext(key)} />
          {key === "evidence" ? "Latest evidence" : key === "thesis" ? "Saved thesis" : "Portfolio context"}
        </label>)}
      </div>
      <small>Only enabled context is sent to approved tools. Portfolio fit remains separate from company quality.</small>
    </section>
    <section className="ask-start-portfolio">
      <div><span>No tracked portfolio?</span><strong>Build a research model before creating holdings.</strong><small>Screen stocks, ETFs, or a mixed universe; compare alternatives; backtest; simulate; then save it separately.</small></div>
      <a href="/research?view=portfolio-builder">Start a portfolio →</a>
    </section>
    <ResearchChat messages={messages} question={question} setQuestion={setQuestion} onSend={onSend} loading={loading} controls={controls} />
    <details className="ask-board-secondary">
      <summary><span>Expert tool</span><strong>Build or open a calculated research board</strong><small>Dashboards remain available without competing with the decision conversation.</small></summary>
      <AIWorkspace {...dashboardProps} />
    </details>
  </div>;
}

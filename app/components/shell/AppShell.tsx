"use client";

import type { ReactNode } from "react";
import { NAV_ITEMS, type Tab } from "../../lib/routes";
import { PRESENTATION_LEVELS, presentationCopy, type PresentationLevel } from "../../lib/presentation-level";
import { ConceptGlossary } from "../learn/ConceptGlossary";

export function AppShell({
  activeTab, density, connected, dark, email, freshness, presentationLevel, children,
  onNavigate, onPresentationLevel, onToggleTheme, onSignOut, onLearnConcept, topAction, drawer, status, notice, onDismissNotice,
}: {
  activeTab: Tab;
  density: "compact" | "comfortable";
  connected: boolean;
  dark: boolean;
  email: string;
  freshness: string;
  presentationLevel: PresentationLevel;
  children: ReactNode;
  onNavigate: (tab: Tab) => void;
  onPresentationLevel: (level: PresentationLevel) => void;
  onToggleTheme: () => void;
  onSignOut: () => void;
  onLearnConcept: (module: string, lesson: string) => void;
  topAction: ReactNode;
  drawer?: ReactNode;
  status?: string;
  notice?: string;
  onDismissNotice: () => void;
}) {
  return <div className={`app-shell density-${density}`}>
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark">EE</div><div><strong>EagleEyes</strong><span>Research terminal</span></div></div>
      <nav aria-label="Primary navigation">
        {NAV_ITEMS.map(([key, icon, label]) => <button key={key} className={activeTab === key ? "active" : ""} onClick={() => onNavigate(key)}><span aria-hidden>{icon}</span>{label}</button>)}
      </nav>
      <div className="sidebar-foot">
        <div className={`connection ${connected ? "online" : ""}`}><i />{connected ? "Research engine connected" : "Research engine offline"}</div>
        <ConceptGlossary onOpen={onLearnConcept} />
        <button className="theme-button" onClick={onToggleTheme}>{dark ? "☀" : "◐"} {dark ? "Light mode" : "Dark mode"}</button>
        <button className="theme-button" onClick={onSignOut}>↪ Sign out</button>
        <small className="signed-in-email">{email}</small>
        <p>Research sandbox<br />Trading is disabled</p>
      </div>
    </aside>
    <main>
      <header className="topbar">
        <div><span className="eyebrow">Market research workspace</span><h1>{NAV_ITEMS.find(item => item[0] === activeTab)?.[2]}</h1></div>
        <div className="top-actions">
          {topAction}
          <div className="view-level" aria-label="Presentation level">
            {PRESENTATION_LEVELS.map(level => <button key={level} title={presentationCopy(level).detail} className={presentationLevel === level ? "active" : ""} onClick={() => onPresentationLevel(level)}>{presentationCopy(level).label}</button>)}
          </div>
          <div className="freshness"><span>Data lineage</span><strong>{freshness}</strong></div>
        </div>
      </header>
      {drawer}
      {status && <div className="progress" role="status"><span />{status}…</div>}
      {notice && <div className="notice"><span>i</span>{notice}<button onClick={onDismissNotice} aria-label="Dismiss">×</button></div>}
      {children}
    </main>
  </div>;
}

"use client";

import type { ReactNode } from "react";
import { isPrimaryTab, navigationLabel, PRIMARY_NAV_ITEMS, SECONDARY_NAV_ITEMS, type Tab } from "../../lib/routes";
import type { PresentationLevel } from "../../lib/presentation-level";
import { ConceptGlossary } from "../learn/ConceptGlossary";

export function AppShell({
  activeTab, density, connected, connectionChecked, dark, email, freshness, presentationLevel, children,
  onNavigate, onPresentationLevel, onToggleTheme, onSignOut, onLearnConcept, topAction, drawer, status, notice, onDismissNotice,
}: {
  activeTab: Tab;
  density: "compact" | "comfortable";
  connected: boolean;
  connectionChecked: boolean;
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
      <div className="brand"><div className="brand-mark">EE</div><div><strong>EagleEyes</strong><span>Decision workspace</span></div></div>
      <nav aria-label="Primary navigation">
        {PRIMARY_NAV_ITEMS.map(([key, icon, label]) => <button key={key} className={activeTab === key ? "active" : ""} onClick={() => onNavigate(key)}><span aria-hidden>{icon}</span>{label}</button>)}
      </nav>
      <div className="sidebar-foot">
        <div className={`connection ${connected ? "online" : ""}`}><i />{connected ? "Research engine connected" : connectionChecked ? "Research engine unavailable" : "Research engine connecting"}</div>
        <ConceptGlossary onOpen={onLearnConcept} />
        <button className="theme-button" onClick={onToggleTheme}>{dark ? "☀" : "◐"} {dark ? "Light mode" : "Dark mode"}</button>
        <button className="theme-button" onClick={onSignOut}>↪ Sign out</button>
        <small className="signed-in-email">{email}</small>
        <p>Research sandbox<br />Trading is disabled</p>
      </div>
    </aside>
    <main>
      <header className="topbar">
        <div><span className="eyebrow">EagleEyes / {isPrimaryTab(activeTab) ? "Workspace" : "More"}</span><h1>{navigationLabel(activeTab)}</h1></div>
        <div className="top-actions">
          {topAction}
          <div className="freshness"><span>Data lineage</span><strong>{freshness}</strong></div>
          <details className="secondary-menu">
            <summary aria-label="Open secondary navigation">More <span aria-hidden>⌄</span></summary>
            <div>
              <nav aria-label="Secondary navigation">
                {SECONDARY_NAV_ITEMS.map(([key, icon, label]) => <button key={key} className={activeTab === key ? "active" : ""} onClick={() => onNavigate(key)}><span aria-hidden>{icon}</span><b>{label}</b></button>)}
              </nav>
              <div className="secondary-menu-actions">
                <button className={presentationLevel==="expert"?"active":""} aria-pressed={presentationLevel==="expert"} onClick={()=>onPresentationLevel(presentationLevel==="expert"?"detailed":"expert")}>▦ Expert mode {presentationLevel==="expert"?"on":"off"}</button>
                <button onClick={onToggleTheme}>{dark ? "☀ Light mode" : "◐ Dark mode"}</button>
                <button onClick={onSignOut}>↪ Sign out</button>
              </div>
            </div>
          </details>
        </div>
      </header>
      {drawer}
      {status && <div className="progress" role="status"><span />{status}…</div>}
      {notice && <div className="notice"><span>i</span>{notice}<button onClick={onDismissNotice} aria-label="Dismiss">×</button></div>}
      {children}
    </main>
  </div>;
}

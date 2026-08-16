"use client";

import { DecisionLab } from "../portfolio/DecisionLab";
import type { Goal, Holding, Profile } from "../workspaces";

export function DecisionsPage({
  request,
  holdings,
  profile,
  goals,
  onOpenPortfolio,
}: {
  request: (path: string, init?: RequestInit) => Promise<Response>;
  holdings: Holding[];
  profile: Profile;
  goals: Goal[];
  onOpenPortfolio: () => void;
}) {
  return <section className="workspace decisions-workspace">
    <div className="section-intro decisions-intro">
      <div>
        <span className="kicker">Investment decision workspace</span>
        <h2>Compare choices without losing the reason behind them.</h2>
        <p>Start with the portfolio and planning context you have already saved. EagleEyes compares explicit alternatives—including doing nothing—on the same modeled paths.</p>
      </div>
      <button className="secondary" onClick={onOpenPortfolio}>Review portfolio inputs</button>
    </div>
    <div className="decision-lifecycle" aria-label="Investment decision lifecycle">
      <span><b>1</b> Define the choice</span>
      <span><b>2</b> Review evidence</span>
      <span><b>3</b> Compare outcomes</span>
      <span><b>4</b> Re-evaluate later</span>
    </div>
    {holdings.length
      ? <DecisionLab request={request} holdings={holdings} profile={profile} goals={goals} />
      : <div className="panel decisions-empty"><h3>Add portfolio holdings before comparing decisions.</h3><p>The Decision Lab does not invent a portfolio or use placeholder positions.</p><button className="primary" onClick={onOpenPortfolio}>Add holdings</button></div>}
  </section>;
}

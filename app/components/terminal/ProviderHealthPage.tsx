"use client";

import { useCallback, useEffect, useState } from "react";
import { ErrorState, FreshnessBadge, LoadingState } from "../shared/ResearchStates";

type ProviderRow = {
  key: string; label: string; status: "healthy" | "awaiting_data" | "degraded" | "unconfigured";
  configured: boolean; last_attempt_at?: string | null; effective_through?: string | null; error?: string | null;
  datasets: string[]; fallbacks: string[]; coverage: Record<string, unknown>;
  rate_limit: Record<string, unknown>;
};

type ProviderHealth = { as_of: string; version: string; summary: Record<string, string | number>; providers: ProviderRow[]; warnings: string[] };

export function ProviderHealthPage({ request }: { request: (path: string, init?: RequestInit) => Promise<Response> }) {
  const [health, setHealth] = useState<ProviderHealth | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");

  const load = useCallback(async () => {
    setError("");
    const response = await request("/providers/health");
    if (!response.ok) throw new Error("Provider health could not be loaded.");
    setHealth(await response.json());
  }, [request]);

  useEffect(() => {
    const timer = window.setTimeout(() => { void load().catch(reason => setError(reason instanceof Error ? reason.message : "Provider health failed.")); }, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  async function refresh(key: string) {
    const endpoint = key === "kalshi" || key === "polymarket" ? "prediction_markets" : key;
    if (!["fred", "prices", "prediction_markets", "sec"].includes(endpoint)) return;
    setBusy(key); setError("");
    try {
      const response = await request(`/providers/refresh/${endpoint}`, { method: "POST" });
      if (!response.ok) throw new Error(`${key} refresh failed.`);
      await load();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Provider refresh failed."); }
    finally { setBusy(""); }
  }

  if (error && !health) return <section className="workspace"><ErrorState detail={error} action={<button onClick={() => void load()}>Retry</button>} /></section>;
  if (!health) return <section className="workspace"><LoadingState label="Checking provider coverage and fallbacks" /></section>;
  return <section className="workspace provider-health-workspace">
    <div className="section-intro"><div><span className="kicker">Live data integration</span><h2>Provider health, coverage, fallbacks, and limits.</h2><p>Credentials are never displayed. This page reports capability, last validated ingestion, stored coverage, and the fallback used when a provider is unavailable.</p></div><button onClick={() => void load()}>Refresh status</button></div>
    {error && <ErrorState title="Refresh warning" detail={error} />}
    <div className="provider-summary"><p><strong>{health.summary.healthy || 0}</strong><span>healthy</span></p><p><strong>{health.summary.awaiting_data || 0}</strong><span>awaiting data</span></p><p><strong>{health.summary.degraded || 0}</strong><span>degraded</span></p><p><strong>{health.summary.unconfigured || 0}</strong><span>unconfigured</span></p></div>
    <div className="provider-health-grid">{health.providers.map(provider => {
      const freshness = provider.status === "healthy" ? "fresh" : provider.status === "degraded" ? "stale" : "missing";
      const canRefresh = ["fred", "prices", "kalshi", "polymarket", "sec"].includes(provider.key) && provider.configured;
      return <article className="panel provider-health-card" key={provider.key}><header><div><span>{provider.key}</span><h3>{provider.label}</h3></div><FreshnessBadge status={freshness} asOf={provider.effective_through} /></header>
        <div className="provider-datasets">{provider.datasets.map(item => <span key={item}>{item}</span>)}</div>
        <p><b>Effective through</b>{provider.effective_through || "No validated snapshot"}</p>
        <p><b>Last attempt</b>{provider.last_attempt_at || "Not recorded"}</p>
        <details><summary>Coverage, fallback, and rate limits</summary><pre>{JSON.stringify(provider.coverage, null, 2)}</pre><strong>Fallback order</strong>{provider.fallbacks.map(item => <small key={item}>{item}</small>)}<strong>Rate limit</strong><small>{String(provider.rate_limit.status || "not reported")}</small></details>
        {provider.error && <small className="provider-error">{provider.error}</small>}
        {canRefresh && <button disabled={busy === provider.key} onClick={() => void refresh(provider.key)}>{busy === provider.key ? "Refreshing…" : `Refresh ${provider.key}`}</button>}
      </article>;
    })}</div>
    <footer className="provider-health-footer">Status contract {health.version} · checked {new Date(health.as_of).toLocaleString()}</footer>
  </section>;
}

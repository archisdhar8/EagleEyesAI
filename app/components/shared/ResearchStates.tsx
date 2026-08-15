import type { ReactNode } from "react";

export function LoadingState({ label = "Loading validated evidence" }: { label?: string }) {
  return <div className="shared-state loading" role="status" aria-live="polite"><i aria-hidden="true" /><span>{label}</span></div>;
}

export function ErrorState({ title = "Evidence unavailable", detail, action }: { title?: string; detail: string; action?: ReactNode }) {
  return <div className="shared-state error" role="alert"><strong>{title}</strong><span>{detail}</span>{action}</div>;
}

export function FreshnessBadge({ status, asOf }: { status: "fresh" | "stale" | "missing"; asOf?: string | null }) {
  const label = status === "fresh" ? "Current" : status === "stale" ? "Stale fallback" : "Missing";
  return <span className={`freshness-badge ${status}`} title={asOf ? `Effective through ${asOf}` : "No effective date available"}>{label}</span>;
}

export type LineageEntry = { provider: string; dataset?: string; effective_through?: string | null; cache_status?: string; dataset_version?: string | null };

export function LineageList({ entries }: { entries: LineageEntry[] }) {
  if (!entries.length) return <ErrorState title="Lineage missing" detail="This evidence should not be treated as decision-ready until provider lineage is available." />;
  return <div className="shared-lineage-list">{entries.map((entry, index) => <div key={`${entry.provider}-${entry.dataset || index}`}><strong>{entry.provider}</strong><span>{entry.dataset || "dataset"}</span><small>through {entry.effective_through || "unknown"} · {entry.cache_status || "stored"} · {entry.dataset_version || "unversioned"}</small></div>)}</div>;
}

export function PresentationLayers({ answer, evidence, method, showEvidence, showMethod }: { answer: ReactNode; evidence: ReactNode; method: ReactNode; showEvidence: boolean; showMethod: boolean }) {
  return <div className="presentation-layers"><section><b>Answer</b>{answer}</section>{showEvidence && <section><b>Evidence</b>{evidence}</section>}{showMethod && <section><b>Method</b>{method}</section>}</div>;
}

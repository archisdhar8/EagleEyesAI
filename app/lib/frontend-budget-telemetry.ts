"use client";

import { useEffect } from "react";

export type FrontendBudgetMetric = {
  route: string;
  dom_nodes?: number;
  cards?: number;
  tables?: number;
  rows?: number;
  charts?: number;
  payload_bytes?: number;
  long_task_ms?: number;
  mounted_messages?: number;
  total_messages?: number;
  conversation_cache_entries?: number;
  conversation_cache_bytes?: number;
  local_snapshot_bytes?: number;
  snapshot_messages?: number;
  mounted_edit_rows?: number;
  total_edit_rows?: number;
  mounted_decision_buttons?: number;
  selected_security?: number;
  active_dashboard_widgets?: number;
  total_dashboard_widgets?: number;
  retained_heavy_widget_bytes?: number;
  heavy_widget_mounted?: number;
  active_streams?: number;
  heap_used_bytes?: number;
  dom_budget_state?: "OK" | "WARNING" | "REVIEW";
  payload_budget_state?: "OK" | "WARNING" | "REVIEW";
};

export const FRONTEND_BUDGETS = {
  dom: { preferred: 1_500, warning: 2_000, review: 2_500 },
  payload: {
    "research.header": 50_000,
    "research.core": 150_000,
    "research.section": 200_000,
    "ask.response": 200_000,
    "dashboard.initial": 250_000,
    "portfolio.overview": 250_000,
  },
  mountedMessages: 40,
  mountedEditRows: 30,
  activeDashboardWidgets: 6,
} as const;

function budgetState(value: number, warning: number, review: number): "OK" | "WARNING" | "REVIEW" {
  if (value >= review) return "REVIEW";
  if (value >= warning) return "WARNING";
  return "OK";
}

function payloadLimit(route: string) {
  if (route === "research.header") return FRONTEND_BUDGETS.payload["research.header"];
  if (route === "research.core") return FRONTEND_BUDGETS.payload["research.core"];
  if (route.startsWith("research.") && !route.endsWith("search")) return FRONTEND_BUDGETS.payload["research.section"];
  if (route.startsWith("ask.")) return FRONTEND_BUDGETS.payload["ask.response"];
  if (route.startsWith("dashboard.")) return FRONTEND_BUDGETS.payload["dashboard.initial"];
  if (route.startsWith("portfolio.")) return FRONTEND_BUDGETS.payload["portfolio.overview"];
  return null;
}

function performanceOptedIn() {
  return typeof window !== "undefined" && (
    new URLSearchParams(window.location.search).get("perf") === "1"
    || window.localStorage.getItem("eagleeyes-perf-instrumentation") === "1"
    || document.documentElement.hasAttribute("data-eagleeyes-perf-opt-in")
  );
}

export function recordFrontendBudget(metric: FrontendBudgetMetric) {
  const enriched = { ...metric };
  if (metric.dom_nodes != null) {
    enriched.dom_budget_state = budgetState(metric.dom_nodes, FRONTEND_BUDGETS.dom.warning, FRONTEND_BUDGETS.dom.review);
  }
  if (metric.payload_bytes != null) {
    const limit = payloadLimit(metric.route);
    if (limit != null) enriched.payload_budget_state = budgetState(metric.payload_bytes, limit, Math.round(limit * 1.25));
  }
  const overBound = enriched.dom_budget_state !== undefined && enriched.dom_budget_state !== "OK"
    || enriched.payload_budget_state !== undefined && enriched.payload_budget_state !== "OK"
    || (metric.mounted_messages ?? 0) > FRONTEND_BUDGETS.mountedMessages
    || (metric.mounted_edit_rows ?? 0) > FRONTEND_BUDGETS.mountedEditRows
    || (metric.active_dashboard_widgets ?? 0) > FRONTEND_BUDGETS.activeDashboardWidgets;
  (overBound ? console.warn : console.info)("[eagleeyes:frontend-budget]", JSON.stringify(enriched));
  window.dispatchEvent(new CustomEvent("eagleeyes:frontend-budget", { detail: enriched }));
  if (performanceOptedIn()) {
    const attribute = "data-eagleeyes-perf-buffer";
    let prior: FrontendBudgetMetric[] = [];
    try { prior = JSON.parse(document.documentElement.getAttribute(attribute) || "[]"); } catch {/* Test-only buffer resets if malformed. */}
    document.documentElement.setAttribute(attribute, JSON.stringify([...prior, enriched].slice(-50)));
  }
}

export function responseBytes(response: Response, payload: unknown) {
  const header = Number(response.headers.get("content-length"));
  if (Number.isFinite(header) && header > 0) return header;
  return new TextEncoder().encode(JSON.stringify(payload)).byteLength;
}

export function useRouteBudgetTelemetry(route: string) {
  useEffect(() => {
    let cancelled = false;
    let observer: PerformanceObserver | undefined;
    const root = document.querySelector(`[data-route-budget="${route}"]`);
    const report = (longTask?: number) => {
      if (cancelled || !root) return;
      const memory = (performance as Performance & { memory?: { usedJSHeapSize?: number } }).memory;
      recordFrontendBudget({
        route,
        dom_nodes: root.querySelectorAll("*").length + 1,
        cards: root.querySelectorAll("article,.panel").length,
        tables: root.querySelectorAll("table,[role=table]").length,
        rows: root.querySelectorAll("tr,[role=row]").length,
        charts: root.querySelectorAll("svg,canvas").length,
        ...(performanceOptedIn() && memory?.usedJSHeapSize != null ? { heap_used_bytes: memory.usedJSHeapSize } : {}),
        ...(longTask == null ? {} : { long_task_ms: Math.round(longTask) }),
      });
    };
    const frame = window.requestAnimationFrame(() => window.setTimeout(() => report(), 0));
    if ("PerformanceObserver" in window) {
      try {
        observer = new PerformanceObserver(list => list.getEntries().forEach(entry => {
          if (entry.duration > 100) report(entry.duration);
        }));
        observer.observe({ type: "longtask", buffered: true });
      } catch {/* Long-task entries are not supported in every browser. */}
    }
    return () => { cancelled = true; window.cancelAnimationFrame(frame); observer?.disconnect(); };
  }, [route]);
}

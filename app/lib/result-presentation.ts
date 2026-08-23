import type { PresentationLevel } from "./presentation-level";

export type ResultPresentation = {
  level: PresentationLevel;
  showEvidence: boolean;
  showMethod: boolean;
  showDiagnostics: boolean;
  answerLabel: string;
  evidenceLabel: string;
  methodLabel: string;
};

const PRESENTATIONS: Record<PresentationLevel, ResultPresentation> = {
  simple: {
    level: "simple", showEvidence: false, showMethod: false, showDiagnostics: false,
    answerLabel: "Answer", evidenceLabel: "Supporting evidence", methodLabel: "How it was calculated",
  },
  detailed: {
    level: "detailed", showEvidence: true, showMethod: true, showDiagnostics: false,
    answerLabel: "Answer", evidenceLabel: "Evidence", methodLabel: "Method",
  },
  expert: {
    level: "expert", showEvidence: true, showMethod: true, showDiagnostics: true,
    answerLabel: "Answer", evidenceLabel: "Evidence and comparisons", methodLabel: "Method, lineage, and validation",
  },
};

export function resultPresentation(level: PresentationLevel): ResultPresentation {
  return PRESENTATIONS[level] || PRESENTATIONS.detailed;
}

export function plainResultAnswer(widgetType: string, data: unknown): string {
  const value = data && typeof data === "object" && !Array.isArray(data) ? data as Record<string, unknown> : {};
  if (widgetType === "portfolio_performance") return "This shows how today’s holdings and weights behaved historically; it is not your actual account return.";
  if (widgetType === "sector_exposure") return "This groups your current saved portfolio weights by the latest stored sector classification.";
  if (widgetType === "canonical_result" && value.concentration && typeof value.concentration === "object") {
    const concentration = value.concentration as Record<string, unknown>;
    const positions = Array.isArray(concentration.positions) ? concentration.positions : [];
    const largest = positions[0] && typeof positions[0] === "object" ? positions[0] as Record<string, unknown> : null;
    const effective = typeof concentration.effective_holdings === "number" ? concentration.effective_holdings : null;
    if (largest && typeof largest.ticker === "string" && typeof largest.weight === "number") {
      return `${largest.ticker} is the largest visible position at ${(largest.weight * 100).toFixed(1)}%${effective == null ? "." : `, with ${effective.toFixed(1)} effective holdings.`}`;
    }
    return "This shows the available position, sector, modeled-risk, and shared-dependency evidence from the saved portfolio analysis.";
  }
  if (widgetType === "correlation_matrix") return "Higher relationships mean the positions have tended to move together and may provide less diversification.";
  if (widgetType === "scenario_probabilities") return "These are separate condition estimates. Economic, inflation, rate, and shock conditions may occur together.";
  if (widgetType === "holdings_sensitivity") return "This compares which holdings historically moved most when the selected macro factor changed.";
  if (widgetType === "factor_correlation_candidates") return "This ranks historical relationships with the named macro factor, not relationships among the stocks.";
  if (widgetType === "research_universe") return "This is the exact group searched; results do not claim to cover the full market.";
  if (widgetType.includes("candidate") || widgetType.includes("comparison")) return "These are relative research comparisons within the disclosed universe, not buy recommendations.";
  if (typeof value.interpretation === "string") return value.interpretation;
  return "This result summarizes the validated evidence currently available for the requested question.";
}

export function nextInvestigation(widgetType: string): string {
  if (widgetType.includes("scenario")) return "Compare the condition with portfolio sensitivity and historical regime evidence.";
  if (widgetType.includes("correlation")) return "Check whether the relationship remains stable across different periods.";
  if (widgetType.includes("research") || widgetType.includes("candidate") || widgetType.includes("comparison")) return "Open the underlying fundamentals, valuation, risks, and freshness before drawing a conclusion.";
  return "Review the evidence date, assumptions, and data gaps before using the result.";
}

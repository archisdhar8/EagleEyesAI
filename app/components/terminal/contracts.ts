export const TERMINAL_LAYOUT_VERSION = "terminal-layout-v1";

export type TerminalWidgetType = "portfolio_return" | "portfolio_allocation" | "positions" | "price_board" | "macro_regime" | "macro_indicators" | "market_indicators" | "scenario_probabilities" | "recession_monitor" | "prediction_market_search" | "research_scores" | "security_scorecard" | "optimizer_snapshot" | "data_freshness" | "model_monitoring";
export type TerminalWidgetConfig = { id: string; type: TerminalWidgetType; size: "small" | "wide" | "full" };
export type TerminalLayout = { id: string; name: string; widgets: TerminalWidgetConfig[]; updated_at: string };

const TYPES = new Set<TerminalWidgetType>([
  "portfolio_return", "portfolio_allocation", "positions", "price_board", "macro_regime", "macro_indicators",
  "market_indicators", "scenario_probabilities", "recession_monitor", "prediction_market_search", "research_scores",
  "security_scorecard", "optimizer_snapshot", "data_freshness", "model_monitoring",
]);
const SIZES = new Set<TerminalWidgetConfig["size"]>(["small", "wide", "full"]);

export function adaptTerminalWidgets(value: unknown): TerminalWidgetConfig[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => {
    if (!item || typeof item !== "object") throw new Error("Invalid terminal widget");
    const row = item as Record<string, unknown>;
    if (typeof row.id !== "string" || !TYPES.has(row.type as TerminalWidgetType) || !SIZES.has(row.size as TerminalWidgetConfig["size"])) {
      throw new Error("Unsupported terminal widget contract");
    }
    return { id: row.id, type: row.type as TerminalWidgetType, size: row.size as TerminalWidgetConfig["size"] };
  });
}

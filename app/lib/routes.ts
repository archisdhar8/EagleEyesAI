export type Tab = "today" | "portfolio" | "explore" | "decisions" | "ask" | "plan" | "learn" | "advanced";
export type ExploreView = "stocks" | "etfs" | "etf-builder" | "stock-builder" | "sectors" | "themes" | "macro" | "scenarios" | "prediction-markets" | "compare" | "watchlist";
export type PortfolioView = "holdings" | "analysis";
export type AdvancedView = "terminal" | "diagnostics" | "validation" | "lineage" | "providers";

export type RouteState = {
  tab: Tab;
  exploreView?: ExploreView;
  portfolioView?: PortfolioView;
  advancedView?: AdvancedView;
  learningModule?: string;
  learningLesson?: string;
  canonicalPath: string;
};

export const PRIMARY_NAV_ITEMS: ReadonlyArray<readonly [Tab, string, string]> = [
  ["today", "⌂", "Today"],
  ["portfolio", "◫", "Portfolio"],
  ["explore", "◎", "Research"],
  ["decisions", "◈", "Decisions"],
  ["ask", "✦", "Ask EagleEyes"],
];

export const SECONDARY_NAV_ITEMS: ReadonlyArray<readonly [Tab, string, string]> = [
  ["plan", "◌", "Plan & profile"],
  ["learn", "◇", "Learn"],
  ["advanced", "▦", "Advanced"],
];

export const NAV_ITEMS = [...PRIMARY_NAV_ITEMS, ...SECONDARY_NAV_ITEMS] as const;

const ROUTES: Record<string, Omit<RouteState, "canonicalPath"> & { canonicalPath?: string }> = {
  "/": { tab: "today", canonicalPath: "/today" },
  "/today": { tab: "today" },
  "/home": { tab: "today", canonicalPath: "/today" },
  "/overview": { tab: "today", canonicalPath: "/today" },
  "/plan": { tab: "plan" },
  "/portfolio": { tab: "portfolio" },
  "/optimize": { tab: "portfolio", portfolioView: "analysis", canonicalPath: "/portfolio?view=analysis" },
  "/decisions": { tab: "decisions" },
  "/decision-lab": { tab: "decisions", canonicalPath: "/decisions" },
  "/explore": { tab: "explore", canonicalPath: "/research" },
  "/research": { tab: "explore", exploreView: "stocks" },
  "/learn": { tab: "learn" },
  "/scenarios": { tab: "explore", exploreView: "scenarios", canonicalPath: "/research?view=scenarios" },
  "/ask": { tab: "ask" },
  "/ai-workspace": { tab: "ask", canonicalPath: "/ask" },
  "/advanced": { tab: "advanced" },
  "/research-terminal": { tab: "advanced", advancedView: "terminal", canonicalPath: "/advanced?view=terminal" },
};

function oneOf<T extends string>(value: string | null, allowed: readonly T[]): T | undefined {
  return value && allowed.includes(value as T) ? value as T : undefined;
}

export function resolveAppRoute(pathname: string, search = ""): RouteState | null {
  const lessonRoute = pathname.match(/^\/learn\/([a-z0-9-]+)\/([a-z0-9-]+)\/?$/i);
  if (lessonRoute) {
    return {
      tab: "learn",
      learningModule: lessonRoute[1],
      learningLesson: lessonRoute[2],
      canonicalPath: pathname,
    };
  }
  const definition = ROUTES[pathname];
  if (!definition) return null;
  const requestedView = new URLSearchParams(search).get("view");
  if (pathname === "/portfolio" && requestedView === "lab") {
    return { tab: "decisions", canonicalPath: "/decisions" };
  }
  const normalizedExploreView = requestedView === "securities" ? "stocks" : requestedView === "comparisons" ? "compare" : requestedView;
  const exploreView = definition.tab === "explore"
    ? oneOf(normalizedExploreView, ["stocks", "etfs", "etf-builder", "stock-builder", "sectors", "themes", "macro", "scenarios", "prediction-markets", "compare", "watchlist"] as const) || definition.exploreView || "stocks"
    : undefined;
  const portfolioView = definition.tab === "portfolio"
    ? oneOf(requestedView, ["holdings", "analysis"] as const) || definition.portfolioView
    : undefined;
  const advancedView = definition.tab === "advanced"
    ? oneOf(requestedView, ["terminal", "diagnostics", "validation", "lineage", "providers"] as const) || definition.advancedView
    : undefined;
  return {
    tab: definition.tab,
    exploreView,
    portfolioView,
    advancedView,
    learningModule: undefined,
    learningLesson: undefined,
    canonicalPath: definition.canonicalPath || `${pathname}${search}`,
  };
}

export function pathForTab(tab: Tab): string {
  if (tab === "today") return "/today";
  if (tab === "explore") return "/research";
  return `/${tab}`;
}

export function navigationLabel(tab: Tab): string {
  return NAV_ITEMS.find(item => item[0] === tab)?.[2] || "EagleEyes";
}

export function isPrimaryTab(tab: Tab): boolean {
  return PRIMARY_NAV_ITEMS.some(item => item[0] === tab);
}

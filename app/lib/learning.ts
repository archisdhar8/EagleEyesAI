export type LearningModule = {
  id: string; slug: string; title: string; description: string; outcomes: string[];
  prerequisites: string[]; lesson_ids: string[]; content_version: string;
};

export type LearningLessonSummary = {
  id: string; module_id: string; title: string; estimated_minutes: number; concept_ids: string[];
  source_refs: string[]; lab_ids: string[]; quiz_id?: string; quiz_question_count: number;
  eagleeyes_links: Array<{label:string;route:string}>; content_version: string;
};

export type LearningLesson = LearningLessonSummary & {
  content: string;
  quiz?: {id:string;version:string;questions:Array<{question:string;options:string[]}>};
  sources: Array<{id:string;title:string;publisher:string;url:string}>;
};

export type LearningProgress = {
  id:string;module_id:string;lesson_id:string;content_version:string;
  status:"not_started"|"in_progress"|"completed"|"mastered";
  completion_percentage:number;best_score?:number|null;completed_at?:string|null;updated_at:string;
};

export type LearningPreferences = {
  selected_path:string|null;knowledge_level:"beginner"|"developing"|"confident";
  interests:string[];portfolio_context_enabled:boolean;updated_at?:string;
};

export type LearningCatalog = {
  version:string;preview_lesson_id:string;modules:LearningModule[];lessons:LearningLessonSummary[];
  preferences?:LearningPreferences;progress?:LearningProgress[];
};

export const LEARNING_GLOSSARY = [
  {term:"Valuation",lesson:"fundamentals-and-valuation",module:"understand-markets",definition:"How the price paid compares with business evidence and expected future cash flows."},
  {term:"Volatility",lesson:"risk-and-time",module:"build-portfolio",definition:"The measured variability of returns over a stated period; it is not the same as permanent loss."},
  {term:"Drawdown",lesson:"costs-rebalancing-and-declines",module:"build-portfolio",definition:"The decline from an earlier peak to a later low over the measured period."},
  {term:"Sharpe ratio",lesson:"risk-and-time",module:"build-portfolio",definition:"A historical or modeled excess-return-per-unit-of-volatility measure whose usefulness depends on its inputs."},
  {term:"Diversification",lesson:"diversification-and-etfs",module:"build-portfolio",definition:"Spreading exposure across investments whose underlying risks and outcomes are not identical."},
  {term:"Correlation",lesson:"diversification-and-etfs",module:"build-portfolio",definition:"Measured historical co-movement; it does not establish causation or future stability."},
  {term:"Inflation",lesson:"why-invest",module:"start-safely",definition:"A broad increase in prices that reduces the purchasing power of a fixed amount of money."},
  {term:"Treasury yield",lesson:"macro-news-and-evidence",module:"understand-markets",definition:"The market yield on U.S. Treasury debt for a stated maturity and date."},
  {term:"ETF",lesson:"accounts-and-assets",module:"start-safely",definition:"A pooled fund whose shares trade on an exchange; its holdings and strategy determine its exposure."},
  {term:"Expense ratio",lesson:"costs-rebalancing-and-declines",module:"build-portfolio",definition:"A fund's annual operating expenses expressed as a percentage of assets."},
  {term:"Rebalancing",lesson:"costs-rebalancing-and-declines",module:"build-portfolio",definition:"Returning an allocation toward intended ranges while considering taxes, costs, and constraints."},
] as const;

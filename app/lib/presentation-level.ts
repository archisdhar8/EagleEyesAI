export const PRESENTATION_LEVEL_VERSION = "presentation-level-v1";
export const PRESENTATION_LEVELS = ["simple", "detailed", "expert"] as const;
export type PresentationLevel = typeof PRESENTATION_LEVELS[number];

export function normalizePresentationLevel(value: unknown): PresentationLevel {
  return PRESENTATION_LEVELS.includes(value as PresentationLevel) ? value as PresentationLevel : "detailed";
}
export function presentationCopy(level: PresentationLevel) {
  if (level === "simple") return { label: "Simple", detail: "Conclusions and essential evidence" };
  if (level === "expert") return { label: "Expert", detail: "Methods, diagnostics, and lineage" };
  return { label: "Detailed", detail: "Charts, comparisons, and assumptions" };
}

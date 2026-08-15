"use client";

export type GuidanceDisclosure = {
  level: "General Market Research" | "Portfolio-Aware Analysis" | "Personalized Guidance";
  reason: string;
  missing_context?: string[];
};

export function GuidanceLevel({ guidance }: { guidance: GuidanceDisclosure }) {
  return <div className="guidance-level" title={guidance.reason}>
    <span>Guidance level</span><strong>{guidance.level}</strong><small>{guidance.reason}</small>
  </div>;
}

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import database
from .dashboard_workspace import DraftRequest, create_draft
from .migrations import connect


@dataclass(frozen=True)
class QuestionCase:
    question: str
    intent: str
    widgets: frozenset[str]
    answer_terms: tuple[str, ...]
    expected_scenario: str | None = None
    expected_theme: str | None = None
    expected_factor_series: str | None = None
    expected_factor_correlation: str | None = None


CASES = (
    QuestionCase(
        "Show my three-year portfolio return, drawdown, allocation, and the macro risks that matter now.",
        "portfolio_review", frozenset({"portfolio_performance", "drawdown", "allocation", "macro_trends"}),
        ("return", "drawdown"),
    ),
    QuestionCase(
        "Which of my holdings has been most sensitive to inflation acceleration, and how reliable is that relationship?",
        "macro_analysis", frozenset({"holdings_sensitivity", "macro_trends", "historical_regimes"}),
        ("inflation", "confidence"),
    ),
    QuestionCase(
        "Compare AAPL and MSFT on growth, valuation, cumulative performance, downside risk, and evidence quality.",
        "compare_securities", frozenset({"security_comparison", "security_performance", "security_drawdown", "risk_summary"}),
        ("aapl", "msft"),
    ),
    QuestionCase(
        "How correlated are my holdings, which positions overlap most, and is that relationship stable?",
        "correlation_analysis", frozenset({"correlation_matrix", "diversification_summary", "correlation_stability"}),
        ("correlation", "diversification"),
    ),
    QuestionCase(
        "Under an oil shock scenario, which holdings appear most exposed and what evidence supports that conclusion?",
        "scenario_analysis", frozenset({"scenario_probabilities", "scenario_history", "scenario_sensitivity"}),
        ("oil", "historical"), expected_scenario="oil_shock",
    ),
    QuestionCase(
        "Find research candidates in energy with strong fundamentals and explain the exact universe being screened.",
        "research_candidates", frozenset({"research_universe", "candidate_ranking", "portfolio_fit"}),
        ("universe", "candidate"), expected_theme="energy",
    ),
    QuestionCase(
        "Which holdings are most sensitive to rising Treasury yields, and are those estimates statistically stable?",
        "macro_analysis", frozenset({"holdings_sensitivity", "macro_trends"}),
        ("yield", "confidence"), expected_factor_series="DGS10",
    ),
    QuestionCase(
        "What does the current recession and rate-cutting scenario imply for my holdings, and what are the limitations?",
        "scenario_analysis", frozenset({"scenario_probabilities", "scenario_sensitivity"}),
        ("recession", "limitation"), expected_scenario="recession_cuts",
    ),
    QuestionCase(
        "Find research candidates correlated with oil.",
        "research_candidates", frozenset({"research_universe", "factor_correlation_candidates"}),
        ("oil", "correlation"), expected_factor_correlation="oil",
    ),
)


def _wait(job_id: str, user_id: str, timeout: float = 150) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = database.get_dashboard_job(job_id, user_id)
        if job["state"] in {"COMPLETE", "PARTIAL_SUCCESS", "FAILED", "CANCELLED"}:
            return job
        time.sleep(.25)
    raise TimeoutError(job_id)


def _evaluate(case: QuestionCase, job: dict[str, Any]) -> dict[str, Any]:
    spec = job.get("specification") or {}
    results = job.get("widget_results") or []
    actual_widgets = {widget["widget_type"] for widget in spec.get("widgets", [])}
    ready = [result for result in results if result.get("status") == "READY"]
    failed = [result["widget_id"] for result in results if result.get("status") == "FAILED"]
    verification_warnings = [
        {"widget": result["widget_id"], "issues": (result.get("verification") or {}).get("issues", [])}
        for result in ready if (result.get("verification") or {}).get("status") != "passed"
    ]
    narrative = job.get("narrative") or ""
    answer_body = narrative.partition("### Key observations")[2]
    lowered = answer_body.lower()
    review = spec.get("answer_review") or {}
    by_method = {result.get("calculation", {}).get("method"): result for result in ready}
    checks = {
        "terminal_success": job["state"] in {"COMPLETE", "PARTIAL_SUCCESS"},
        "intent": (job.get("plan") or {}).get("intent") == case.intent,
        "required_widgets": case.widgets.issubset(actual_widgets),
        "no_failed_widgets": not failed,
        "widgets_verified": not verification_warnings,
        "answer_review": review.get("status") == "passed",
        "answer_length": len(narrative.split()) >= 60,
        "answer_terms": all(term in lowered for term in case.answer_terms),
    }
    if case.expected_scenario:
        scenario_data = (by_method.get("scenario_sensitivity") or {}).get("data") or {}
        checks["requested_scenario_used"] = (scenario_data.get("selected_scenario") or {}).get("key") == case.expected_scenario
    if case.expected_theme:
        candidates = (by_method.get("candidate_ranking") or {}).get("data") or []
        checks["theme_filter_applied"] = bool(candidates) and all(
            case.expected_theme in " ".join(str(row.get(key, "")) for key in ("ticker", "company", "sector", "industry")).lower()
            for row in candidates
        )
    if case.expected_factor_series:
        sensitivity = (by_method.get("holdings_sensitivity") or {}).get("data") or {}
        checks["factor_series_used"] = sensitivity.get("series_id") == case.expected_factor_series
        checks["quantitative_sensitivity"] = bool(sensitivity.get("rows"))
    if case.expected_factor_correlation:
        factor_result = (by_method.get("factor_correlation_candidates") or {}).get("data") or {}
        checks["named_factor_used"] = factor_result.get("factor") == case.expected_factor_correlation
        checks["candidate_factor_rows"] = bool(factor_result.get("rows"))
        checks["not_pairwise_portfolio_correlation"] = "correlation_matrix" not in by_method
    return {
        "question": case.question, "state": job["state"],
        "planned_intent": (job.get("plan") or {}).get("intent"),
        "widgets": sorted(actual_widgets), "failed_widgets": failed,
        "verification_warnings": verification_warnings,
        "answer_review": review, "checks": checks,
        "score": round(100 * sum(checks.values()) / len(checks)),
        "narrative_words": len(narrative.split()),
        "narrative_preview": narrative[:700],
    }


def main() -> None:
    with connect() as conn:
        row = conn.execute(
            """SELECT u.id FROM auth.users u
            LEFT JOIN public.portfolios p ON p.user_id=u.id
            LEFT JOIN public.holdings h ON h.portfolio_id=p.id
            GROUP BY u.id ORDER BY count(h.id) DESC, max(p.updated_at) DESC NULLS LAST LIMIT 1"""
        ).fetchone()
    if not row:
        raise RuntimeError("No authenticated Supabase user is available for evaluation")
    user_id = str(row[0])
    selected = os.getenv("WORKSPACE_EVAL_CASES", "").strip()
    cases = CASES
    if selected:
        indexes = {int(value.strip()) for value in selected.split(",") if value.strip()}
        cases = tuple(case for index, case in enumerate(CASES, start=1) if index in indexes)
        if not cases:
            raise ValueError("WORKSPACE_EVAL_CASES did not select a valid 1-based case number")
    jobs: list[dict[str, Any]] = []
    try:
        reports = []
        for offset in range(0, len(cases), 2):
            batch_cases = cases[offset:offset + 2]
            batch_jobs = [create_draft(user_id, DraftRequest(prompt=case.question)) for case in batch_cases]
            jobs.extend(batch_jobs)
            reports.extend(_evaluate(case, _wait(job["id"], user_id)) for case, job in zip(batch_cases, batch_jobs))
        summary = {
            "questions": len(reports),
            "average_score": round(sum(report["score"] for report in reports) / len(reports), 1),
            "perfect": sum(report["score"] == 100 for report in reports),
            "answer_reviews_passed": sum(report["answer_review"].get("status") == "passed" for report in reports),
            "widget_failures": sum(len(report["failed_widgets"]) for report in reports),
            "verification_warnings": sum(len(report["verification_warnings"]) for report in reports),
        }
        rendered = json.dumps({"summary": summary, "reports": reports}, indent=2)
        output_path = os.getenv("WORKSPACE_EVAL_OUTPUT", "/tmp/eagleeyes-workspace-evaluation.json").strip()
        Path(output_path).write_text(rendered)
        print(rendered, flush=True)
    finally:
        with connect() as conn:
            conn.execute("DELETE FROM public.dashboard_jobs WHERE id = ANY(%s)", ([job["id"] for job in jobs],))


if __name__ == "__main__":
    main()

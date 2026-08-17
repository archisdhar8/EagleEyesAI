from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any


def _num(value: Any) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def surprise(actual: Any, consensus: Any) -> dict[str, Any]:
    actual_value, consensus_value = _num(actual), _num(consensus)
    change = None if actual_value is None or consensus_value in (None, 0) else (actual_value / consensus_value - 1)
    return {"actual": actual_value, "consensus": consensus_value, "surprise_percent": change,
            "status": "UNAVAILABLE" if actual_value is None or consensus_value is None else "AVAILABLE",
            "methodology": "(actual / consensus) - 1; consensus must be provider-supplied."}


def guidance_delta(previous: Any, current: Any, *, unit: str = "USD") -> dict[str, Any]:
    def bounds(value: Any) -> tuple[float | None, float | None]:
        if isinstance(value, dict):
            return _num(value.get("low")), _num(value.get("high"))
        scalar = _num(value)
        return scalar, scalar
    prior_low, prior_high = bounds(previous); new_low, new_high = bounds(current)
    prior_mid = None if prior_low is None or prior_high is None else (prior_low + prior_high) / 2
    new_mid = None if new_low is None or new_high is None else (new_low + new_high) / 2
    midpoint_change = None if prior_mid in (None, 0) or new_mid is None else new_mid / prior_mid - 1
    basis_points = None
    if unit in {"ratio", "percent"} and prior_mid is not None and new_mid is not None:
        basis_points = (new_mid - prior_mid) * (10000 if unit == "ratio" else 100)
    return {"previous": {"low": prior_low, "high": prior_high, "midpoint": prior_mid},
            "current": {"low": new_low, "high": new_high, "midpoint": new_mid},
            "midpoint_change_percent": midpoint_change, "change_basis_points": basis_points,
            "unit": unit, "status": "AVAILABLE" if prior_mid is not None and new_mid is not None else "UNAVAILABLE"}


def _metrics(row: dict[str, Any] | None) -> dict[str, Any]:
    value = (row or {}).get("metrics") or {}
    return value if isinstance(value, dict) else {}


def _aligned(rows: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None]:
    ordered = sorted(rows, key=lambda row: (str(row.get("period_end") or ""), str(row.get("fetched_at") or "")), reverse=True)
    if not ordered:
        return None, None, None
    latest = ordered[0]
    previous = next((row for row in ordered[1:] if row.get("fiscal_period") != "FY"), ordered[1] if len(ordered) > 1 else None)
    prior_year = next((row for row in ordered[1:] if row.get("fiscal_period") == latest.get("fiscal_period") and row.get("fiscal_year") != latest.get("fiscal_year")), None)
    return latest, previous, prior_year


def build_earnings_intelligence(ticker: str, periods: list[dict[str, Any]], *, thesis: dict[str, Any] | None = None,
                                monitor: dict[str, Any] | None = None, transcript_chunks: list[dict[str, Any]] | None = None,
                                now: datetime | None = None) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    latest, previous, prior_year = _aligned(periods)
    if latest is None:
        return {"version": "earnings-intelligence-v1", "ticker": ticker, "status": "UNAVAILABLE",
                "period": None, "reported_at": None, "warnings": ["No verified reported financial period is stored."],
                "coverage": {key: "UNAVAILABLE" for key in ("reported_results", "consensus", "guidance", "estimate_revisions", "transcript")}}
    metrics, prior_metrics, year_metrics = _metrics(latest), _metrics(previous), _metrics(prior_year)
    consensus = metrics.get("consensus") if isinstance(metrics.get("consensus"), dict) else {}
    revenue = surprise(metrics.get("revenue"), consensus.get("revenue") or metrics.get("revenue_consensus"))
    eps = surprise(metrics.get("eps_diluted"), consensus.get("eps") or metrics.get("eps_consensus"))
    changes: list[dict[str, Any]] = []
    for key, label in (("revenue", "Revenue"), ("eps_diluted", "Diluted EPS"), ("free_cash_flow", "Free cash flow")):
        value, prior, year = _num(metrics.get(key)), _num(prior_metrics.get(key)), _num(year_metrics.get(key))
        changes.append({"category": "REVENUE" if key == "revenue" else "EPS" if key == "eps_diluted" else "CASH_FLOW",
                        "metric": key, "label": label, "current": value, "previous_quarter": prior,
                        "prior_year_period": year, "quarter_change_percent": None if prior in (None, 0) or value is None else value / prior - 1,
                        "year_change_percent": None if year in (None, 0) or value is None else value / year - 1,
                        "period_alignment": "same fiscal period" if prior_year else "prior-year comparison unavailable"})
    revenue_value = _num(metrics.get("revenue")); prior_revenue = _num(prior_metrics.get("revenue"))
    for key, label in (("gross_profit", "Gross margin"), ("operating_income", "Operating margin"), ("net_income", "Net margin")):
        current_value, prior_value = _num(metrics.get(key)), _num(prior_metrics.get(key))
        current_margin = None if current_value is None or revenue_value in (None, 0) else current_value / revenue_value
        prior_margin = None if prior_value is None or prior_revenue in (None, 0) else prior_value / prior_revenue
        changes.append({"category": "MARGIN", "metric": key.replace("_profit", "_margin").replace("_income", "_margin"),
                        "label": label, "current": current_margin, "previous_quarter": prior_margin,
                        "change_basis_points": None if current_margin is None or prior_margin is None else (current_margin - prior_margin) * 10000})
    current_guidance = metrics.get("guidance") if isinstance(metrics.get("guidance"), dict) else {}
    previous_guidance = metrics.get("previous_guidance") if isinstance(metrics.get("previous_guidance"), dict) else {}
    guidance = [{"metric": key, **guidance_delta(previous_guidance.get(key), value,
                 unit=(value.get("unit", "USD") if isinstance(value, dict) else "USD"))}
                for key, value in current_guidance.items()]
    revisions_raw = metrics.get("estimate_revisions") if isinstance(metrics.get("estimate_revisions"), dict) else {}
    revisions = []
    for key, value in revisions_raw.items():
        if not isinstance(value, dict): continue
        before, after = _num(value.get("before")), _num(value.get("after"))
        revisions.append({"metric": key, "before": before, "after": after,
                          "change_percent": None if before in (None, 0) or after is None else after / before - 1,
                          "window_hours": value.get("window_hours"), "up": value.get("up"), "down": value.get("down"),
                          "as_of": value.get("as_of"), "provider": value.get("provider")})
    relevant_assumptions = []
    if monitor:
        for item in monitor.get("assumption_results", []):
            evidence_types = {row.get("evidence_type") for row in item.get("evidence", [])}
            if evidence_types.intersection({"FUNDAMENTAL", "EARNINGS", "GUIDANCE", "ESTIMATE"}):
                relevant_assumptions.append({"id": item.get("assumption_id"), "description": item.get("description"),
                                             "state": item.get("state"), "importance": item.get("importance"),
                                             "explanation": item.get("explanation")})
    coverage = {"reported_results": "AVAILABLE", "consensus": "AVAILABLE" if revenue["status"] == "AVAILABLE" or eps["status"] == "AVAILABLE" else "UNAVAILABLE",
                "guidance": "AVAILABLE" if guidance else "UNAVAILABLE", "estimate_revisions": "AVAILABLE" if revisions else "UNAVAILABLE",
                "transcript": "AVAILABLE" if transcript_chunks else "UNAVAILABLE"}
    warnings = [f"{label} not available; it is not interpreted as unchanged." for key, label in (("consensus", "Consensus"), ("guidance", "Guidance"), ("estimate_revisions", "Post-earnings revisions")) if coverage[key] == "UNAVAILABLE"]
    return {"version": "earnings-intelligence-v1", "ticker": ticker, "status": "AVAILABLE", "period": {"fiscal_period": latest.get("fiscal_period"), "fiscal_year": latest.get("fiscal_year"), "period_end": latest.get("period_end")},
            "reported_at": latest.get("fetched_at"), "actual_vs_expectations": {"revenue": revenue, "eps": eps},
            "changes": changes, "guidance_changes": guidance, "estimate_revisions": revisions,
            "thesis_impact": {"thesis_id": (thesis or {}).get("id"), "overall_status": (monitor or {}).get("overall_status"), "assumptions": relevant_assumptions},
            "transcript_evidence": (transcript_chunks or [])[:8], "coverage": coverage, "warnings": warnings,
            "source": {"provider": latest.get("provider") or "stored fundamentals", "url": latest.get("source_url"), "data_quality_score": latest.get("data_quality_score")},
            "methodology": {"period_alignment": "Fiscal labels and period ends are matched; incompatible periods are not compared.", "consensus": "Provider-supplied values only.", "generated_at": current.isoformat()}}

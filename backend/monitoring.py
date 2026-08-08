from __future__ import annotations

import argparse
import math
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import numpy as np

from . import database
from .analysis import run_analysis
from .models import InvestorProfile
from .quant import REGIME_KEYS


def calibration_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        item = grouped.setdefault(
            str(row["snapshot_id"]),
            {
                "probabilities": {}, "actual": row["dominant_regime"],
                "observed_at": row["observed_at"], "realized_at": row["realized_at"],
            },
        )
        item["probabilities"][row["scenario_key"]] = float(row["probability"])
    samples = [item for item in grouped.values() if item["actual"] in REGIME_KEYS]
    cutoff = max((item["realized_at"] for item in samples), default=datetime.now(timezone.utc).date().isoformat())
    assumptions = [
        "Uses the last genuine prediction-market scenario snapshot in each month.",
        "Scores that probability vector against the next available point-in-time dominant macro regime.",
        "This is a one-month macro calibration proxy; contract-specific resolution calibration is retained separately as contracts resolve.",
    ]
    if len(samples) < 6:
        return {
            "status": "insufficient_history", "model_version": "prediction-market-v1",
            "horizon_months": 1, "data_cutoff": str(cutoff)[:10],
            "sample_count": len(samples), "genuine_market_sample_count": len(samples),
            "brier_score": None, "calibration_error": None, "metrics": {},
            "assumptions": assumptions,
        }
    probabilities = np.asarray([
        [max(0.0, float(item["probabilities"].get(key, 0.0))) for key in REGIME_KEYS]
        for item in samples
    ])
    totals = probabilities.sum(axis=1, keepdims=True)
    probabilities = probabilities / np.where(totals > 0, totals, 1.0)
    targets = np.asarray([REGIME_KEYS.index(item["actual"]) for item in samples])
    one_hot = np.eye(len(REGIME_KEYS))[targets]
    brier = float(np.mean(np.sum((probabilities - one_hot) ** 2, axis=1)))
    flattened_probabilities = probabilities.ravel()
    flattened_outcomes = one_hot.ravel()
    calibration_error = 0.0
    for low in np.linspace(0, 1, 10, endpoint=False):
        high = low + .1
        mask = (flattened_probabilities >= low) & (flattened_probabilities < high if high < 1 else flattened_probabilities <= high)
        if mask.any():
            calibration_error += float(mask.mean()) * abs(
                float(flattened_outcomes[mask].mean()) - float(flattened_probabilities[mask].mean())
            )
    return {
        "status": "complete", "model_version": "prediction-market-v1",
        "horizon_months": 1, "data_cutoff": str(cutoff)[:10],
        "sample_count": len(samples), "genuine_market_sample_count": len(samples),
        "brier_score": round(brier, 6),
        "calibration_error": round(calibration_error, 6),
        "metrics": {"realized_regime_counts": dict(sorted({key: sum(item["actual"] == key for item in samples) for key in REGIME_KEYS}.items()))},
        "assumptions": assumptions,
    }


def _days_old(value: str | None, now: datetime) -> float | None:
    if not value:
        return None
    timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return max(0.0, (now - timestamp).total_seconds() / 86400)


def build_monitoring_result(
    analysis: dict[str, Any], data_status: dict[str, Any], calibration: dict[str, Any],
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    diagnostics = analysis.get("model_diagnostics") or {}
    covariance = diagnostics.get("covariance") or {}
    walk = analysis.get("walk_forward") or {}
    balanced = next((item for item in analysis.get("alternatives", []) if item.get("name") == "Balanced"), {})
    allocations = {item["ticker"]: item["target_weight"] for item in balanced.get("allocations", [])}
    previous_allocations = ((previous or {}).get("metrics") or {}).get("balanced_allocations", {})
    allocation_stability = None
    if previous_allocations:
        symbols = set(allocations) | set(previous_allocations)
        allocation_stability = sum(abs(float(allocations.get(key, 0)) - float(previous_allocations.get(key, 0))) for key in symbols) / 2
    history = database.regime_history(1000) if database.DATABASE_URL else []
    regime_counts: dict[str, int] = defaultdict(int)
    for row in history:
        regime_counts[row["dominant_regime"]] += 1
    now = datetime.now(timezone.utc)
    freshness = data_status.get("freshness", {})
    freshness_days = {key: _days_old(value, now) for key, value in freshness.items()}
    coverage_rows = data_status.get("price_coverage", [])
    tiingo = next((row for row in coverage_rows if row.get("provider") == "tiingo"), {})
    alerts: list[str] = []
    if calibration.get("status") == "complete" and previous:
        prior_brier = (((previous.get("metrics") or {}).get("prediction_market_calibration") or {}).get("brier_score"))
        if prior_brier is not None and calibration.get("brier_score") is not None and calibration["brier_score"] - prior_brier > .03:
            alerts.append("Prediction-market Brier score deteriorated by more than 0.03.")
    if float(covariance.get("shrunk_condition_number") or 0) > 100000:
        alerts.append("Shrunk covariance condition number exceeds 100,000.")
    if any(regime_counts.get(key, 0) < 12 for key in REGIME_KEYS):
        alerts.append("At least one macro regime has fewer than 12 historical samples.")
    if walk.get("status") != "complete":
        alerts.append("Walk-forward validation is incomplete.")
    model_metrics = walk.get("model") or {}
    benchmarks = walk.get("benchmarks") or []
    best_benchmark = max((float(item.get("annualized_return") or -math.inf) for item in benchmarks), default=-math.inf)
    if best_benchmark > float(model_metrics.get("annualized_return") or -math.inf):
        alerts.append("The optimizer trails the strongest static benchmark on annualized return.")
    if float(balanced.get("turnover") or 0) > .50:
        alerts.append("Balanced allocation turnover exceeds 50%.")
    if allocation_stability is not None and allocation_stability > .20:
        alerts.append("Balanced target weights changed by more than 20% one-way since the prior monitor run.")
    if freshness_days.get("prices") is None or float(freshness_days["prices"]) > 4:
        alerts.append("Price data is more than four days old or missing.")
    if freshness_days.get("markets") is None or float(freshness_days["markets"]) > .125:
        alerts.append("Prediction-market snapshots are more than three hours old or missing.")
    if int(tiingo.get("symbols") or 0) == 0:
        alerts.append("Long-history Tiingo coverage is missing.")
    metrics = {
        "prediction_market_calibration": calibration,
        "covariance": covariance,
        "regime_sample_counts": dict(regime_counts),
        "walk_forward": {"model": model_metrics, "benchmarks": benchmarks, "period_count": walk.get("period_count", 0)},
        "turnover": balanced.get("turnover"),
        "allocation_stability": None if allocation_stability is None else round(allocation_stability, 6),
        "balanced_allocations": allocations,
    }
    return {
        "status": "warning" if alerts else "healthy", "metrics": metrics,
        "alerts": alerts, "freshness": freshness_days,
        "coverage": {"providers": coverage_rows, "tiingo_symbols": tiingo.get("symbols", 0)},
    }


def run_monitoring() -> dict[str, Any]:
    portfolios = database.list_portfolios()
    if not portfolios:
        raise RuntimeError("A saved portfolio is required for model monitoring")
    profile = InvestorProfile.model_validate(database.load_profile() or {})
    portfolio = portfolios[0]
    analysis = run_analysis(portfolio["holdings"], profile)
    request = {"portfolio_id": portfolio["id"], "portfolio": portfolio, "profile": profile.model_dump(mode="json"), "source": "automated_model_monitoring"}
    database.save_analysis(analysis["id"], request, analysis)
    calibration = calibration_metrics(database.prediction_calibration_inputs())
    calibration_run_id = database.save_prediction_calibration(calibration)
    previous = database.latest_monitoring_run()
    result = build_monitoring_result(analysis, database.provider_data_status(), calibration, previous)
    monitoring_id = database.save_monitoring_run(
        analysis_run_id=analysis["id"], calibration_run_id=calibration_run_id,
        status=result["status"], data_cutoff=datetime.now(timezone.utc).date().isoformat(),
        metrics=result["metrics"], alerts=result["alerts"],
        freshness=result["freshness"], coverage=result["coverage"],
    )
    return {"id": monitoring_id, "analysis_run_id": analysis["id"], **result}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run InvestmentDashboard model monitoring")
    parser.add_argument("command", choices=["run", "status"])
    args = parser.parse_args()
    if args.command == "status":
        print(database.latest_monitoring_run() or "No monitoring runs")
        return 0
    result = run_monitoring()
    print(f"monitoring={result['status']} alerts={len(result['alerts'])} id={result['id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

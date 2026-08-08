from __future__ import annotations

import math
from typing import Any

import numpy as np
from scipy.optimize import minimize

from .quant import REGIME_KEYS


MODEL_VERSION = "multinomial-logit-regime-v1"
FEATURES = (
    "inflation_yoy",
    "unemployment",
    "unemployment_change_3m",
    "yield_curve",
    "credit_spread",
    "policy_rate_change_3m",
    "oil_change_3m",
    "industrial_growth_yoy",
    "payroll_growth_yoy",
)


def _softmax(scores: np.ndarray) -> np.ndarray:
    shifted = scores - scores.max(axis=1, keepdims=True)
    values = np.exp(np.clip(shifted, -60, 60))
    return values / values.sum(axis=1, keepdims=True)


def _fit_multinomial(
    x: np.ndarray, y: np.ndarray, *, l2: float = 1.0
) -> tuple[np.ndarray, np.ndarray, bool, int]:
    rows, features = x.shape
    classes = len(REGIME_KEYS)

    def objective(parameters: np.ndarray) -> tuple[float, np.ndarray]:
        weights = parameters[:features * classes].reshape(features, classes)
        intercept = parameters[features * classes:].reshape(1, classes)
        probabilities = _softmax(x @ weights + intercept)
        loss = -float(np.log(np.maximum(probabilities[np.arange(rows), y], 1e-12)).mean())
        loss += l2 * float(np.sum(weights * weights)) / (2 * rows)
        residual = probabilities
        residual[np.arange(rows), y] -= 1
        weight_gradient = x.T @ residual / rows + l2 * weights / rows
        intercept_gradient = residual.mean(axis=0)
        return loss, np.concatenate([weight_gradient.ravel(), intercept_gradient.ravel()])

    initial = np.zeros(features * classes + classes)
    result = minimize(
        lambda parameters: objective(parameters), initial, jac=True,
        method="L-BFGS-B", options={"maxiter": 350, "ftol": 1e-10},
    )
    weights = result.x[:features * classes].reshape(features, classes)
    intercept = result.x[features * classes:]
    return weights, intercept, bool(result.success), int(result.nit)


def _metrics(probabilities: np.ndarray, targets: np.ndarray) -> dict[str, float | int]:
    one_hot = np.eye(len(REGIME_KEYS))[targets]
    brier = float(np.mean(np.sum((probabilities - one_hot) ** 2, axis=1)))
    log_loss = -float(np.log(np.maximum(probabilities[np.arange(len(targets)), targets], 1e-12)).mean())
    predictions = probabilities.argmax(axis=1)
    confidence = probabilities.max(axis=1)
    correct = (predictions == targets).astype(float)
    calibration_error = 0.0
    for low in np.linspace(0, 1, 10, endpoint=False):
        high = low + .1
        mask = (confidence >= low) & (confidence < high if high < 1 else confidence <= high)
        if mask.any():
            calibration_error += float(mask.mean()) * abs(float(correct[mask].mean()) - float(confidence[mask].mean()))
    stability = float(np.mean(np.abs(np.diff(probabilities, axis=0)))) if len(probabilities) > 1 else 0.0
    return {
        "observations": int(len(targets)),
        "brier_score": round(brier, 6),
        "log_loss": round(log_loss, 6),
        "accuracy": round(float(correct.mean()), 6),
        "calibration_error": round(calibration_error, 6),
        "probability_instability": round(stability, 6),
    }


def _feature_value(label: dict[str, Any], feature: str) -> float:
    value = (label.get("inputs") or {}).get(feature)
    try:
        result = float(value)
        return result if math.isfinite(result) else math.nan
    except (TypeError, ValueError):
        return math.nan


def evaluate_regime_classifier(
    labels: list[dict[str, Any]], *, initial_train_months: int = 60,
    test_months: int = 12, l2: float = 1.0,
) -> dict[str, Any]:
    ordered = sorted(labels, key=lambda item: item["as_of_date"])
    if len(ordered) < initial_train_months + test_months + 2:
        return {
            "status": "insufficient_history", "model_version": MODEL_VERSION,
            "folds": [], "fold_count": 0, "recommendation": "retain_transparent_baseline",
            "assumptions": [
                f"At least {initial_train_months + test_months + 2} monthly point-in-time labels are required."
            ],
        }
    class_index = {key: index for index, key in enumerate(REGIME_KEYS)}
    feature_rows: list[list[float]] = []
    targets: list[int] = []
    baseline_probabilities: list[list[float]] = []
    feature_dates: list[str] = []
    target_dates: list[str] = []
    for index in range(len(ordered) - 1):
        current, following = ordered[index], ordered[index + 1]
        if following.get("dominant_regime") not in class_index:
            continue
        feature_rows.append([_feature_value(current, feature) for feature in FEATURES])
        targets.append(class_index[following["dominant_regime"]])
        raw = current.get("probabilities") or {}
        values = np.array([max(0.0, float(raw.get(key, 0))) for key in REGIME_KEYS])
        values = values / (values.sum() or 1.0)
        baseline_probabilities.append(values.tolist())
        feature_dates.append(str(current["as_of_date"])[:10])
        target_dates.append(str(following["as_of_date"])[:10])
    x = np.asarray(feature_rows, dtype=float)
    y = np.asarray(targets, dtype=int)
    baseline = np.asarray(baseline_probabilities, dtype=float)
    fold_results: list[dict[str, Any]] = []
    all_ml: list[np.ndarray] = []
    all_baseline: list[np.ndarray] = []
    all_targets: list[np.ndarray] = []
    split = initial_train_months
    fold_index = 0
    while split + 1 < len(x):
        test_start = split + 1  # one-month embargo; train target predates first test feature
        test_end = min(test_start + test_months, len(x))
        if test_end - test_start < 3:
            break
        train_x, train_y = x[:split], y[:split]
        test_x, test_y = x[test_start:test_end], y[test_start:test_end]
        medians = np.array([
            float(np.median(column[np.isfinite(column)])) if np.isfinite(column).any() else 0.0
            for column in train_x.T
        ])
        train_x = np.where(np.isfinite(train_x), train_x, medians)
        test_x = np.where(np.isfinite(test_x), test_x, medians)
        means = train_x.mean(axis=0)
        scales = train_x.std(axis=0)
        scales = np.where(scales > 1e-8, scales, 1.0)
        standardized_train = (train_x - means) / scales
        standardized_test = (test_x - means) / scales
        weights, intercept, converged, iterations = _fit_multinomial(
            standardized_train, train_y, l2=l2
        )
        ml_probabilities = _softmax(standardized_test @ weights + intercept)
        baseline_fold = baseline[test_start:test_end]
        ml_metrics = _metrics(ml_probabilities, test_y)
        baseline_metrics = _metrics(baseline_fold, test_y)
        fold_results.append({
            "fold_index": fold_index,
            "train_start": feature_dates[0],
            "train_end": target_dates[split - 1],
            "test_start": feature_dates[test_start],
            "test_end": target_dates[test_end - 1],
            "data_cutoff": feature_dates[test_start],
            "train_samples": int(split), "test_samples": int(len(test_y)),
            "ml_metrics": ml_metrics, "baseline_metrics": baseline_metrics,
            "brier_improvement": round(
                float(baseline_metrics["brier_score"] - ml_metrics["brier_score"]), 6
            ),
            "leakage_check": target_dates[split - 1] < feature_dates[test_start],
            "diagnostics": {
                "converged": converged, "iterations": iterations,
                "missing_training_fraction": round(float(np.isnan(x[:split]).mean()), 6),
                "classes_observed": int(len(np.unique(train_y))), "embargo_months": 1,
            },
        })
        all_ml.append(ml_probabilities)
        all_baseline.append(baseline_fold)
        all_targets.append(test_y)
        fold_index += 1
        split += test_months
    if not fold_results:
        return {
            "status": "insufficient_history", "model_version": MODEL_VERSION,
            "folds": [], "fold_count": 0, "recommendation": "retain_transparent_baseline",
            "assumptions": ["No complete embargoed out-of-sample fold was available."],
        }
    ml_metrics = _metrics(np.vstack(all_ml), np.concatenate(all_targets))
    baseline_metrics = _metrics(np.vstack(all_baseline), np.concatenate(all_targets))
    wins = float(np.mean([fold["brier_improvement"] > 0 for fold in fold_results]))
    brier_improvement = float(baseline_metrics["brier_score"] - ml_metrics["brier_score"])
    relative_brier = brier_improvement / max(float(baseline_metrics["brier_score"]), 1e-9)
    qualifies = (
        relative_brier >= .02
        and float(ml_metrics["log_loss"]) < float(baseline_metrics["log_loss"])
        and wins >= .60
        and all(fold["leakage_check"] for fold in fold_results)
    )
    return {
        "status": "complete", "model_version": MODEL_VERSION,
        "baseline_version": "macro-regime-rules-v1",
        "fold_count": len(fold_results), "folds": fold_results,
        "transparent_baseline": baseline_metrics, "ml_classifier": ml_metrics,
        "comparison": {
            "brier_improvement": round(brier_improvement, 6),
            "relative_brier_improvement": round(relative_brier, 6),
            "log_loss_improvement": round(
                float(baseline_metrics["log_loss"] - ml_metrics["log_loss"]), 6
            ),
            "fold_win_rate": round(wins, 6),
        },
        "recommendation": "consider_probability_blend" if qualifies else "retain_transparent_baseline",
        "production_model_changed": False,
        "features": list(FEATURES),
        "configuration": {
            "algorithm": "L2-regularized multinomial logistic regression",
            "initial_train_months": initial_train_months,
            "test_months": test_months, "embargo_months": 1, "l2": l2,
        },
        "assumptions": [
            "Predicts next month's dominant regime using only point-in-time macro features available at the current month end.",
            "Uses expanding training windows, twelve-month tests, and a one-month fold embargo.",
            "Transparent baseline is the existing rules-based probability vector at each forecast date.",
            "Evaluation does not change production weights; a blend is considered only after Brier, log-loss, and fold-consistency gates pass.",
        ],
    }

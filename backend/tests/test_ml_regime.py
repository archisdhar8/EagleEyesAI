from backend.ml_regime import FEATURES, evaluate_regime_classifier
from backend.quant import REGIME_KEYS


def _labels(months: int = 180) -> list[dict]:
    labels = []
    for index in range(months):
        target_class = index % len(REGIME_KEYS)
        inputs = {feature: 0.0 for feature in FEATURES}
        inputs[FEATURES[target_class]] = 1.0
        labels.append({
            "as_of_date": f"{2008 + index // 12:04d}-{index % 12 + 1:02d}-28",
            "dominant_regime": REGIME_KEYS[0],
            "probabilities": {key: 1 / len(REGIME_KEYS) for key in REGIME_KEYS},
            "inputs": inputs,
        })
    for index in range(months - 1):
        labels[index + 1]["dominant_regime"] = REGIME_KEYS[index % len(REGIME_KEYS)]
    return labels


def test_ml_evaluation_is_deterministic_and_embargoed() -> None:
    first = evaluate_regime_classifier(_labels())
    second = evaluate_regime_classifier(_labels())
    assert first == second
    assert first["status"] == "complete"
    assert first["fold_count"] >= 5
    assert all(fold["leakage_check"] for fold in first["folds"])
    assert all(fold["train_end"] < fold["test_start"] for fold in first["folds"])
    assert first["production_model_changed"] is False


def test_ml_must_clear_consistency_gates_before_blend_recommendation() -> None:
    result = evaluate_regime_classifier(_labels())
    assert result["ml_classifier"]["brier_score"] < result["transparent_baseline"]["brier_score"]
    assert result["comparison"]["fold_win_rate"] >= .60
    assert result["recommendation"] == "consider_probability_blend"


def test_ml_evaluation_retains_baseline_with_insufficient_history() -> None:
    result = evaluate_regime_classifier(_labels(40))
    assert result["status"] == "insufficient_history"
    assert result["recommendation"] == "retain_transparent_baseline"

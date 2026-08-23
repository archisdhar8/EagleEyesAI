from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend import ask_portfolio, database, read_models
from backend.ask_runtime import build_portfolio_context


def _source(*, fundamentals_at: str | None = None) -> tuple[dict, dict, dict]:
    now = datetime.now(timezone.utc).isoformat()
    portfolio = database.save_portfolio(
        "Primary", [{"ticker": "MSFT", "weight": .6}, {"ticker": "AAPL", "weight": .4}],
        user_id="user-a",
    )
    rows = [
        {"ticker": "MSFT", "health_score": 80, "fundamental_score": 75, "valuation_score": 60,
         "momentum_score": 70, "risk_contribution": .6, "data_confidence": "High", "as_of": now},
        {"ticker": "AAPL", "health_score": 70, "fundamental_score": 68, "valuation_score": 55,
         "momentum_score": 65, "risk_contribution": .4, "data_confidence": "High", "as_of": now},
    ]
    overview = {
        "as_of": now, "health": {"score": 75, "coverage": 1}, "holdings": rows,
        "changes": [], "warnings": [],
        "ask_cache": {
            "portfolio_intelligence": {"concentration": {"positions": []}},
            "watchlist_research": [{"ticker": "GOOG", "fundamental_score": 80, "valuation_score": 70,
                                    "technical_score": 75, "confidence": 90, "as_of": now}],
            "events": [{"ticker": "MSFT", "type": "earnings", "as_of": now}],
            "scenarios": [{"key": "rates", "fetched_at": now}],
            "latest_simulation": {"id": "sim-1", "created_at": now, "input": {"scenario": {"rate_state": "tightening"}}},
            "latest_optimizer": {"id": "opt-1", "created_at": now, "input_fingerprint": "old"},
        },
    }
    bundle = {
        "prices": [{"ticker": "MSFT", "date": now}, {"ticker": "AAPL", "date": now}],
        "fundamentals": [{"ticker": "MSFT", "as_of": fundamentals_at or now},
                         {"ticker": "AAPL", "as_of": fundamentals_at or now}],
        "securities": [{"ticker": "MSFT", "sector": "Technology", "industry": "Software"},
                       {"ticker": "AAPL", "sector": "Technology", "industry": "Hardware"}],
    }
    return portfolio, overview, bundle


def _build(*, fundamentals_at: str | None = None):
    portfolio, overview, bundle = _source(fundamentals_at=fundamentals_at)
    context = build_portfolio_context(portfolio)
    models = read_models.build_capability_read_models(
        "user-a", portfolio, overview, input_fingerprint=context.version,
        profile={"watchlist": ["GOOG"], "updated_at": portfolio["updated_at"]}, thesis_rows=[],
        security_bundle=bundle, watchlist_bundle={"prices": [], "fundamentals": [], "securities": []},
        briefing=None, baseline_available=False,
    )
    return portfolio, context, {model.metadata.read_model_type: model for model in models}


def test_builders_persist_all_capability_models_with_independent_metadata():
    portfolio, context, models = _build()
    assert set(models) == set(read_models.PORTFOLIO_READ_MODEL_TYPES)
    for model_type, model in models.items():
        assert model.metadata.input_fingerprint == context.version
        assert model.metadata.calculation_version == read_models.READ_MODEL_CALCULATION_VERSIONS[model_type]
        assert set(read_models.READ_MODEL_DEPENDENCIES[model_type]["required"]) <= set(model.metadata.upstream_versions)
        assert database.capability_read_model_history("user-a", portfolio["id"], model_type)


@pytest.mark.parametrize(
    ("dataset", "affected"),
    [
        ("portfolio_holdings", {"portfolio_opportunity", "portfolio_risk", "portfolio_events",
                                "portfolio_scenario", "optimizer_compatibility"}),
        ("prices", {"portfolio_opportunity", "portfolio_risk", "portfolio_factor_state",
                    "watchlist_comparison", "score_attribution"}),
        ("fundamentals", {"portfolio_opportunity", "portfolio_factor_state", "watchlist_comparison",
                          "portfolio_data_quality", "score_attribution"}),
        ("theses", {"thesis_status", "portfolio_opportunity", "portfolio_risk", "portfolio_change",
                    "watchlist_comparison"}),
        ("macro_state", {"portfolio_scenario"}),
        ("prediction_markets", {"portfolio_scenario"}),
    ],
)
def test_dependency_invalidation_matrix(dataset: str, affected: set[str]):
    portfolio, _, _ = _build()
    actual = set(read_models.invalidate_for_upstream_change("user-a", str(portfolio["id"]), dataset, f"{dataset}-v2"))
    assert affected <= actual
    for model_type in actual:
        latest = database.capability_read_model_history("user-a", portfolio["id"], model_type, 1)[0]
        assert latest["metadata"]["read_model_state"] == "STALE"


def test_price_update_does_not_invalidate_thesis_status():
    portfolio, context, _ = _build()
    read_models.invalidate_for_upstream_change("user-a", str(portfolio["id"]), "prices", "prices-v2")
    thesis = read_models.load_compatible_read_model("user-a", str(portfolio["id"]), "thesis_status", context.version)
    assert thesis.state == read_models.CompatibilityState.CURRENT


def test_portfolio_mutation_rebuilds_with_new_fingerprint():
    portfolio, old_context, _ = _build()
    mutated = database.save_portfolio("Primary", [{"ticker": "MSFT", "weight": 1}], portfolio["id"], "user-a")
    new_context = build_portfolio_context(mutated)
    assert new_context.version != old_context.version
    affected = read_models.invalidate_for_upstream_change(
        "user-a", str(portfolio["id"]), "portfolio_holdings", new_context.version, mutated["updated_at"],
    )
    assert {"portfolio_risk", "portfolio_opportunity", "portfolio_scenario",
            "optimizer_compatibility", "portfolio_events"} <= set(affected)
    now = datetime.now(timezone.utc).isoformat()
    row = {"ticker": "MSFT", "health_score": 80, "fundamental_score": 75, "valuation_score": 60,
           "momentum_score": 70, "risk_contribution": 1, "data_confidence": "High", "as_of": now}
    read_models.build_capability_read_models(
        "user-a", mutated, {"as_of": now, "health": {}, "holdings": [row], "changes": [], "warnings": [],
                            "ask_cache": {"portfolio_intelligence": {}, "watchlist_research": [], "events": [],
                                          "scenarios": [], "latest_simulation": {}, "latest_optimizer": {}}},
        input_fingerprint=new_context.version, profile={"watchlist": [], "updated_at": now}, thesis_rows=[],
        security_bundle={"prices": [{"ticker": "MSFT", "date": now}],
                         "fundamentals": [{"ticker": "MSFT", "as_of": now}],
                         "securities": [{"ticker": "MSFT", "sector": "Technology", "industry": "Software"}]},
        watchlist_bundle={"prices": [], "fundamentals": [], "securities": []},
    )
    loaded = read_models.load_compatible_read_model("user-a", str(portfolio["id"]), "portfolio_risk", new_context.version)
    assert loaded.state == read_models.CompatibilityState.CURRENT
    assert loaded.model and loaded.model.metadata.input_fingerprint == new_context.version


def test_reconciliation_detects_a_missed_invalidation_event():
    portfolio, context, _ = _build()
    database.upsert_analytical_dataset_version("user-a", portfolio["id"], "prices", "missed-price-version")
    states = read_models.reconcile_portfolio_read_models("user-a", str(portfolio["id"]), context.version)
    assert states["portfolio_opportunity"] == "STALE"
    assert states["thesis_status"] == "CURRENT"


def test_reconciliation_detects_missed_optional_dependency_change():
    portfolio, context, _ = _build()
    database.upsert_analytical_dataset_version("user-a", portfolio["id"], "prediction_markets", "missed-market-version")
    states = read_models.reconcile_portfolio_read_models("user-a", str(portfolio["id"]), context.version)
    assert states["portfolio_scenario"] == "STALE"
    assert states["portfolio_events"] == "CURRENT"


def test_freshness_is_bounded_by_oldest_required_input_not_build_time():
    old = datetime.now(timezone.utc) - timedelta(days=7)
    _, _, models = _build(fundamentals_at=old.isoformat())
    model = models["portfolio_factor_state"]
    assert model.metadata.calculated_at > old
    assert model.metadata.effective_through is not None
    assert abs((model.metadata.oldest_required_input - old).total_seconds()) < 2
    assert model.metadata.effective_through == model.metadata.oldest_required_input


def test_loader_rejects_fingerprint_schema_and_calculation_mismatches():
    portfolio, context, _ = _build()
    kwargs = ("user-a", str(portfolio["id"]), "portfolio_risk")
    assert read_models.load_compatible_read_model(*kwargs, "different").state == read_models.CompatibilityState.INCOMPATIBLE
    assert read_models.load_compatible_read_model(*kwargs, context.version, schema_version="2").state == read_models.CompatibilityState.INCOMPATIBLE
    assert read_models.load_compatible_read_model(*kwargs, context.version, calculation_version="risk-v2").state == read_models.CompatibilityState.INCOMPATIBLE


def test_old_optimizer_and_different_scenario_definition_become_stale():
    portfolio, context, _ = _build()
    read_models.invalidate_for_upstream_change("user-a", str(portfolio["id"]), "optimizer_config", "optimizer-v2")
    read_models.invalidate_for_upstream_change("user-a", str(portfolio["id"]), "scenario_model", "scenario-definition-v2")
    assert read_models.load_compatible_read_model("user-a", str(portfolio["id"]), "optimizer_compatibility", context.version).state == read_models.CompatibilityState.STALE
    assert read_models.load_compatible_read_model("user-a", str(portfolio["id"]), "portfolio_scenario", context.version).state == read_models.CompatibilityState.STALE


def test_failed_rebuild_does_not_destroy_previous_valid_history():
    portfolio, context, models = _build()
    valid = models["portfolio_risk"]
    failed = valid.metadata.model_copy(update={"read_model_state": read_models.ReadModelState.FAILED,
                                               "analysis_status": read_models.AnalysisStatus.FAILED, "failure_class": "ValueError",
                                               "failure_at": datetime.now(timezone.utc)})
    database.save_capability_read_model("user-a", portfolio["id"], failed.model_dump(mode="json"), {})
    history = database.capability_read_model_history("user-a", portfolio["id"], "portfolio_risk")
    assert len(history) == 2
    loaded = read_models.load_compatible_read_model("user-a", str(portfolio["id"]), "portfolio_risk", context.version)
    assert loaded.model is not None
    assert loaded.model.id == valid.id
    assert loaded.state == read_models.CompatibilityState.STALE


def test_real_ask_acceptance_path_consumes_capability_models_without_legacy_adapter():
    portfolio, context, _ = _build()
    for tool in read_models.TOOL_READ_MODEL:
        tickers = ("MSFT",) if tool == "score_attribution" else ()
        results, _ = ask_portfolio.run(tool, "user-a", str(portfolio["id"]), "rates rise", tickers, context)
        assert results
        assert results[0]["read_model"]["type"] == read_models.TOOL_READ_MODEL[tool]
        assert results[0]["read_model"]["legacy_adapter_used"] is False
        assert results[0]["read_model"]["state"] == "CURRENT"

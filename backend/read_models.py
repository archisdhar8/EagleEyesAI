from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Callable

from pydantic import BaseModel, Field

from . import database
from .analytical_contract import AnalysisStatus, Coverage, Freshness, build_freshness, parse_timestamp, stable_fingerprint
from .operational_monitoring import record_metric
from . import phase4_analytics


READ_MODEL_SCHEMA_VERSION = "1"
BUILDER_VERSION = "ask-read-model-builder-v2"


def _persist_telemetry() -> bool:
    return os.getenv("ANALYTICAL_TELEMETRY_DURABLE", "1").strip().lower() not in {"0", "false", "off", "no"}


class ReadModelState(StrEnum):
    CURRENT = "CURRENT"
    STALE = "STALE"
    BUILDING = "BUILDING"
    FAILED = "FAILED"
    MISSING = "MISSING"


class CompatibilityState(StrEnum):
    CURRENT = "CURRENT"
    STALE = "STALE"
    INCOMPATIBLE = "INCOMPATIBLE"
    MISSING = "MISSING"


class ReadModelMetadata(BaseModel):
    read_model_type: str
    schema_version: str = READ_MODEL_SCHEMA_VERSION
    calculation_version: str
    input_fingerprint: str
    portfolio_id: str | None = None
    calculated_at: datetime
    effective_through: datetime | None = None
    oldest_required_input: datetime | None = None
    upstream_versions: dict[str, str] = Field(default_factory=dict)
    analysis_status: AnalysisStatus = AnalysisStatus.SUCCESS
    read_model_state: ReadModelState = ReadModelState.CURRENT
    coverage: Coverage = Field(default_factory=Coverage.not_tracked)
    freshness: Freshness
    builder_version: str | None = BUILDER_VERSION
    failure_class: str | None = None
    failure_at: datetime | None = None
    stale_reason: str | None = None


class CapabilityReadModel(BaseModel):
    id: str | None = None
    metadata: ReadModelMetadata
    data: dict[str, Any]


class CompatibleReadModel(BaseModel):
    state: CompatibilityState
    reason: str
    model: CapabilityReadModel | None = None
    input_fingerprint_match: bool | None = None
    upstream_version_match: bool | None = None


READ_MODEL_DEPENDENCIES: dict[str, dict[str, tuple[str, ...]]] = {
    "company_analysis": {
        "required": ("prices", "fundamentals", "security_metadata"),
        "optional": ("earnings", "news", "score_model", "thesis_state"),
    },
    "macro_state": {
        "required": ("macro_observations",),
        "optional": ("macro_regime_labels", "macro_calendar"),
    },
    "market_state": {
        "required": ("market_prices",),
        "optional": ("volatility", "breadth", "sector_data"),
    },
    "prediction_market_state": {
        "required": ("prediction_market_observations",),
        "optional": ("calibration", "portfolio_mappings"),
    },
    "portfolio_opportunity": {
        "required": ("portfolio_holdings", "prices", "fundamentals"),
        "optional": ("security_classification", "theses"),
    },
    "portfolio_risk": {
        "required": ("portfolio_holdings", "prices", "security_classification"),
        "optional": ("theme_mappings", "theses"),
    },
    "portfolio_change": {
        "required": ("portfolio_holdings",),
        "optional": ("portfolio_health_history", "theses"),
    },
    "portfolio_factor_state": {
        "required": ("portfolio_holdings", "prices", "fundamentals"),
        "optional": (),
    },
    "watchlist_comparison": {
        "required": ("portfolio_holdings", "portfolio_profile", "prices", "fundamentals"),
        "optional": ("theses",),
    },
    "portfolio_events": {
        "required": ("portfolio_holdings",),
        "optional": ("earnings_calendar", "macro_calendar", "company_catalysts"),
    },
    "portfolio_data_quality": {
        "required": ("portfolio_holdings", "prices", "fundamentals"),
        "optional": ("provider_state",),
    },
    "score_attribution": {
        "required": ("portfolio_holdings", "prices", "fundamentals"),
        "optional": ("portfolio_health_history",),
    },
    "thesis_status": {
        "required": ("portfolio_holdings", "theses"),
        "optional": ("thesis_monitor",),
    },
    "portfolio_scenario": {
        "required": ("portfolio_holdings", "scenario_model"),
        "optional": ("macro_state", "prediction_markets", "theme_mappings"),
    },
    "optimizer_compatibility": {
        "required": ("portfolio_holdings", "portfolio_constraints", "optimizer_config"),
        "optional": ("tax_lots",),
    },
}


READ_MODEL_CALCULATION_VERSIONS = {
    "company_analysis": "company-analysis-v1",
    "macro_state": "macro-state-v1",
    "market_state": "market-state-v1",
    "prediction_market_state": "prediction-market-state-v1",
    "portfolio_opportunity": "portfolio-opportunity-read-v2",
    "portfolio_risk": "portfolio-risk-read-v2",
    "portfolio_change": "portfolio-change-read-v2",
    "portfolio_factor_state": "portfolio-factor-state-read-v2",
    "watchlist_comparison": "watchlist-comparison-read-v2",
    "portfolio_events": "portfolio-events-read-v2",
    "portfolio_data_quality": "portfolio-data-quality-read-v2",
    "score_attribution": "score-attribution-read-v2",
    "thesis_status": "thesis-status-read-v2",
    "portfolio_scenario": "portfolio-scenario-read-v2",
    "optimizer_compatibility": "optimizer-compatibility-read-v2",
}

PORTFOLIO_READ_MODEL_TYPES = (
    "portfolio_opportunity", "portfolio_risk", "portfolio_change", "portfolio_factor_state",
    "watchlist_comparison", "portfolio_events", "portfolio_data_quality", "score_attribution",
    "thesis_status", "portfolio_scenario", "optimizer_compatibility",
)


TOOL_READ_MODEL = {
    "portfolio_overview": "portfolio_opportunity",
    "portfolio_intelligence": "portfolio_risk",
    "recommendation_countercase": "portfolio_risk",
    "portfolio_change": "portfolio_change",
    "valuation_ranking": "portfolio_factor_state",
    "multifactor_screen": "portfolio_factor_state",
    "watchlist_comparison": "watchlist_comparison",
    "thesis_replacement": "watchlist_comparison",
    "cash_allocation": "watchlist_comparison",
    "portfolio_events": "portfolio_events",
    "data_quality": "portfolio_data_quality",
    "score_attribution": "score_attribution",
    "thesis_monitor": "thesis_status",
    "portfolio_scenario": "portfolio_scenario",
    "portfolio_analysis": "optimizer_compatibility",
}


def affected_read_models(dataset_type: str) -> list[str]:
    return sorted(
        capability for capability, dependencies in READ_MODEL_DEPENDENCIES.items()
        if capability in PORTFOLIO_READ_MODEL_TYPES
        if dataset_type in dependencies["required"] or dataset_type in dependencies["optional"]
    )


def _timestamps(value: Any) -> list[datetime]:
    found: list[datetime] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"as_of", "effective_at", "effective_through", "updated_at", "created_at", "fetched_at", "observed_at", "date"}:
                parsed = parse_timestamp(child)
                if parsed:
                    found.append(parsed)
            elif isinstance(child, (dict, list)):
                found.extend(_timestamps(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_timestamps(child))
    return found


def dataset_descriptor(value: Any, *, effective_hint: Any = None) -> dict[str, str | None]:
    timestamps = _timestamps(value)
    hinted = parse_timestamp(effective_hint)
    if hinted:
        timestamps.append(hinted)
    return {
        "version": stable_fingerprint(value),
        "effective_through": max(timestamps).isoformat() if timestamps else None,
    }


def source_dataset_descriptors(
    portfolio: dict[str, Any], overview: dict[str, Any], *, profile: dict[str, Any],
    thesis_rows: list[dict[str, Any]], security_bundle: dict[str, Any],
    watchlist_bundle: dict[str, Any], briefing: dict[str, Any] | None,
) -> dict[str, dict[str, str | None]]:
    ask_cache = overview.get("ask_cache") or {}
    holdings = portfolio.get("holdings") or []
    prices = (security_bundle.get("prices") or []) + (watchlist_bundle.get("prices") or [])
    fundamentals = (security_bundle.get("fundamentals") or []) + (watchlist_bundle.get("fundamentals") or [])
    securities = (security_bundle.get("securities") or []) + (watchlist_bundle.get("securities") or [])
    latest_simulation = ask_cache.get("latest_simulation") or {}
    latest_optimizer = ask_cache.get("latest_optimizer") or {}
    upcoming = list((briefing or {}).get("upcoming_events") or ask_cache.get("events") or [])
    scenarios = list((briefing or {}).get("scenarios") or ask_cache.get("scenarios") or [])
    result = {
        "portfolio_holdings": dataset_descriptor(holdings, effective_hint=portfolio.get("updated_at")),
        "portfolio_profile": dataset_descriptor({"watchlist": profile.get("watchlist", [])}, effective_hint=profile.get("updated_at")),
        "portfolio_constraints": dataset_descriptor({"profile": profile, "policy": overview.get("policy")}),
        "prices": dataset_descriptor(prices),
        "fundamentals": dataset_descriptor(fundamentals),
        "security_classification": dataset_descriptor([{key: row.get(key) for key in ("ticker", "sector", "industry")} for row in securities]),
        "theme_mappings": dataset_descriptor((ask_cache.get("portfolio_intelligence") or {}).get("dependency_exposure") or []),
        "theses": dataset_descriptor(thesis_rows),
        "thesis_monitor": dataset_descriptor(overview.get("monitors") or []),
        "portfolio_health_history": dataset_descriptor({"changes": overview.get("changes") or [], "baseline": overview.get("baseline_available")}),
        "earnings_calendar": dataset_descriptor([row for row in upcoming if "earn" in str(row.get("type") or row.get("category") or "").lower()]),
        "macro_calendar": dataset_descriptor([row for row in upcoming if "economic" in str(row.get("type") or row.get("category") or "").lower()]),
        "company_catalysts": dataset_descriptor(upcoming),
        "provider_state": dataset_descriptor(overview.get("warnings") or []),
        "scenario_model": dataset_descriptor(latest_simulation),
        "macro_state": dataset_descriptor(scenarios),
        "prediction_markets": dataset_descriptor(scenarios),
        "optimizer_config": dataset_descriptor(latest_optimizer),
        "tax_lots": dataset_descriptor((latest_optimizer.get("tax_lots") if isinstance(latest_optimizer, dict) else None) or []),
    }
    return result


def _coverage(rows: list[dict[str, Any]], portfolio: dict[str, Any]) -> Coverage:
    requested = [str(row.get("ticker") or "").upper() for row in portfolio.get("holdings") or [] if row.get("ticker")]
    evaluated = [str(row.get("ticker") or "").upper() for row in rows if row.get("ticker")]
    return Coverage(requested_entities=requested, evaluated_entities=evaluated)


def _model_payloads(portfolio: dict[str, Any], overview: dict[str, Any], *, profile: dict[str, Any],
                    thesis_rows: list[dict[str, Any]], baseline_available: bool,
                    snapshot_identity: dict[str, Any] | None, baseline_identity: dict[str, Any] | None,
                    security_bundle: dict[str, Any], watchlist_bundle: dict[str, Any],
                    input_fingerprint: str) -> dict[str, dict[str, Any]]:
    ask_cache = overview.get("ask_cache") or {}
    holdings = list(overview.get("holdings") or [])
    intelligence = ask_cache.get("portfolio_intelligence") or {}
    owned = {str(row.get("ticker") or "").upper() for row in holdings}
    ranked_holdings = sorted(holdings, key=lambda row: float(row.get("health_score") or 0), reverse=True)
    watchlist_research = [{**row, "owned": str(row.get("ticker") or "").upper() in owned,
                           "candidate_eligibility": "ADD_TO_EXISTING" if str(row.get("ticker") or "").upper() in owned else "NEW_POSITION"}
                          for row in ask_cache.get("watchlist_research") or []]
    current_scores = [{key: row.get(key) for key in ("ticker", "health_score", "fundamental_score",
                      "valuation_score", "momentum_score", "component_changes", "change")} for row in holdings]
    previous_scores = [{"ticker": row.get("ticker"),
                        "health_score": (float(row.get("health_score")) - float(row.get("change")))
                        if row.get("health_score") is not None and row.get("change") is not None else None,
                        "calculation_version": "portfolio-health-v1"} for row in holdings]
    simulation = ask_cache.get("latest_simulation") or {}
    optimizer = ask_cache.get("latest_optimizer") or {}
    combined_bundle = {
        key: list(security_bundle.get(key) or []) + list(watchlist_bundle.get(key) or [])
        for key in {"securities", "fundamentals", "prices", "news", "company_markets"}
    }
    opportunities = phase4_analytics.build_opportunity_candidates(holdings, security_bundle)
    relative_valuation = phase4_analytics.build_relative_valuation(holdings, security_bundle)
    trends_by_ticker = {
        str(row.get("ticker") or "").upper(): phase4_analytics.build_fundamental_trend([
            period for period in security_bundle.get("fundamentals") or []
            if str(period.get("ticker") or "").upper() == str(row.get("ticker") or "").upper()
        ]).model_dump(mode="json") for row in holdings
    }
    improving_screen = [
        {**row, "fundamental_trend": trends_by_ticker.get(str(row.get("ticker") or "").upper())}
        for row in holdings
        if (trends_by_ticker.get(str(row.get("ticker") or "").upper()) or {}).get("direction") == "IMPROVING"
        and float(row.get("valuation_score") or 0) >= 45 and float(row.get("momentum_score") or 0) >= 55
    ]
    improving_screen.sort(key=lambda row: (
        float(row.get("fundamental_score") or 0) + float(row.get("valuation_score") or 0)
        + float(row.get("momentum_score") or 0)
    ), reverse=True)
    dominance = phase4_analytics.build_watchlist_dominance(watchlist_research, holdings, combined_bundle)
    replacements = phase4_analytics.build_replacement_comparisons(thesis_rows, dominance, holdings, combined_bundle)
    cash_allocation = phase4_analytics.build_cash_allocation(dominance, profile)
    change_set = phase4_analytics.build_material_change_set(
        overview.get("changes") or [], holdings, baseline_available=baseline_available,
        baseline_identity=baseline_identity,
    )
    typed_events = phase4_analytics.build_portfolio_events(ask_cache.get("events") or [], holdings)
    data_quality = phase4_analytics.build_data_quality(holdings, security_bundle)
    baseline_timestamp = next((baseline_identity.get(key) for key in (
        "effective_at", "effective_through", "as_of", "created_at", "calculated_at"
    ) if baseline_identity and baseline_identity.get(key)), None)
    attribution_holdings = [{**row, "baseline_timestamp": baseline_timestamp} for row in holdings]
    baseline_calculation_version = next((baseline_identity.get(key) for key in (
        "calculation_version", "model_version"
    ) if baseline_identity and baseline_identity.get(key)), None)
    score_attributions = phase4_analytics.build_score_attributions(
        attribution_holdings, baseline_calculation_version=baseline_calculation_version,
    )
    thesis_invalidation = phase4_analytics.build_thesis_invalidation(thesis_rows, holdings)
    scenario_support = phase4_analytics.build_scenario_support(simulation or None, intelligence)
    countercase = phase4_analytics.build_countercase(opportunities, holdings, intelligence, input_fingerprint)
    rebalance = phase4_analytics.build_rebalance_contract(optimizer or None, input_fingerprint, holdings)
    return {
        "portfolio_opportunity": {"health": overview.get("health") or {}, "holdings": holdings,
                                  "ranked_holdings": ranked_holdings,
                                  "opportunity_candidates": opportunities,
                                  "opportunity_methodology": "opportunity-v2",
                                  "eligibility": [{"ticker": row.get("ticker"), **dict(candidate.get("eligibility") or {})}
                                                  for candidate in opportunities
                                                  for row in holdings if row.get("ticker") == candidate.get("ticker")]},
        "portfolio_risk": {"health": overview.get("health") or {}, "holdings": holdings, "intelligence": intelligence,
                           "countercase": countercase},
        "portfolio_change": {"health": overview.get("health") or {}, "changes": overview.get("changes") or [],
                             "warnings": overview.get("warnings") or [], "holdings": holdings,
                             "change_set": change_set,
                             "baseline_available": baseline_available,
                             "current_snapshot_identity": snapshot_identity,
                             "baseline_snapshot_identity": baseline_identity},
        "portfolio_factor_state": {"holdings": holdings, "relative_valuation": relative_valuation,
                                   "fundamental_trends": trends_by_ticker,
                                   "improving_fundamental_screen": improving_screen},
        "watchlist_comparison": {"research": watchlist_research, "holdings": holdings,
                                 "watchlist": profile.get("watchlist") or [], "theses": thesis_rows,
                                 "dominance": dominance, "replacement_comparisons": replacements,
                                 "cash_allocation": cash_allocation},
        "portfolio_events": {"events": ask_cache.get("events") or [], "typed_events": typed_events,
                             "holdings": [{"ticker": row.get("ticker")} for row in holdings if row.get("ticker")]},
        "portfolio_data_quality": {"holdings": holdings, "warnings": overview.get("warnings") or [],
                                   "trust_classifications": data_quality},
        "score_attribution": {"holdings": holdings, "current_scores": current_scores,
                              "previous_scores": previous_scores, "baseline_available": baseline_available,
                              "attributions": score_attributions,
                              "current_snapshot_identity": snapshot_identity,
                              "baseline_snapshot_identity": baseline_identity,
                              "calculation_version": "portfolio-health-v1"},
        "thesis_status": {"theses": thesis_rows, "holdings": holdings,
                          "invalidation_results": thesis_invalidation},
        "portfolio_scenario": {"latest_simulation": simulation or None, "scenarios": ask_cache.get("scenarios") or [],
                               "run_identity": simulation.get("id"), "scenario_definition": (simulation.get("input") or {}).get("scenario"),
                               "portfolio_fingerprint": simulation.get("input_fingerprint") or simulation.get("portfolio_context_version"),
                               "supported_factors": scenario_support,
                               "factor_registry": phase4_analytics.SCENARIO_FACTOR_REGISTRY},
        "optimizer_compatibility": {"latest_optimizer": optimizer or None, "run_identity": optimizer.get("id"),
                                    "rebalance_decision": rebalance,
                                    "portfolio_fingerprint": optimizer.get("input_fingerprint") or optimizer.get("portfolio_context_version"),
                                    "constraints_fingerprint": stable_fingerprint(optimizer.get("request") or optimizer.get("constraints") or {}),
                                    "feasibility": (optimizer.get("model_diagnostics") or {}).get("constraint_status") or optimizer.get("constraint_status"),
                                    "tax_lots_available": bool(optimizer.get("tax_lots")),
                                    "turnover_assumptions": optimizer.get("turnover_assumptions")},
    }


def _required_freshness(read_model_type: str, descriptors: dict[str, dict[str, str | None]],
                        calculated_at: datetime) -> Freshness:
    names = READ_MODEL_DEPENDENCIES[read_model_type]["required"]
    return build_freshness(
        [(name, descriptors.get(name, {}).get("effective_through")) for name in names],
        calculated_at=calculated_at,
    )


def build_capability_read_models(
    user_id: str, portfolio: dict[str, Any], overview: dict[str, Any], *,
    input_fingerprint: str, profile: dict[str, Any], thesis_rows: list[dict[str, Any]],
    security_bundle: dict[str, Any], watchlist_bundle: dict[str, Any],
    briefing: dict[str, Any] | None = None, baseline_available: bool = False,
    read_model_types: tuple[str, ...] | None = None,
    snapshot_identity: dict[str, Any] | None = None, baseline_identity: dict[str, Any] | None = None,
) -> list[CapabilityReadModel]:
    """Split one completed legacy overview build into independently versioned read models."""
    started = time.monotonic()
    portfolio_id = str(portfolio["id"])
    descriptors = source_dataset_descriptors(
        portfolio, overview, profile=profile, thesis_rows=thesis_rows, security_bundle=security_bundle,
        watchlist_bundle=watchlist_bundle, briefing=briefing,
    )
    for dataset_type, descriptor in descriptors.items():
        database.upsert_analytical_dataset_version(
            user_id, portfolio_id, dataset_type, str(descriptor["version"]), descriptor.get("effective_through"),
        )
    payloads = _model_payloads(portfolio, overview, profile=profile, thesis_rows=thesis_rows,
                               baseline_available=baseline_available, snapshot_identity=snapshot_identity,
                               baseline_identity=baseline_identity, security_bundle=security_bundle,
                               watchlist_bundle=watchlist_bundle, input_fingerprint=input_fingerprint)
    calculated_at = datetime.now(timezone.utc)
    built: list[CapabilityReadModel] = []
    selected = set(read_model_types or payloads)
    for read_model_type, data in payloads.items():
        if read_model_type not in selected:
            continue
        build_started = time.monotonic()
        try:
            dependencies = READ_MODEL_DEPENDENCIES[read_model_type]
            dependency_names = (*dependencies["required"], *dependencies["optional"])
            versions = {name: str(descriptors[name]["version"]) for name in dependency_names if name in descriptors}
            freshness = _required_freshness(read_model_type, descriptors, calculated_at)
            coverage = _coverage(list(data.get("holdings") or []), portfolio)
            metadata = ReadModelMetadata(
                read_model_type=read_model_type,
                calculation_version=READ_MODEL_CALCULATION_VERSIONS[read_model_type],
                input_fingerprint=input_fingerprint,
                portfolio_id=portfolio_id,
                calculated_at=calculated_at,
                effective_through=freshness.effective_through,
                oldest_required_input=freshness.oldest_required_input,
                upstream_versions=versions,
                analysis_status=AnalysisStatus.PARTIAL if freshness.stale else AnalysisStatus.SUCCESS,
                coverage=coverage,
                freshness=freshness,
            )
            row = database.save_capability_read_model(
                user_id, portfolio_id, metadata.model_dump(mode="json"), data,
            )
            built.append(CapabilityReadModel(id=row["id"], metadata=metadata, data=data))
            record_metric("ask.read_model.build", (time.monotonic() - build_started) * 1000,
                          tags={"read_model_type": read_model_type, "build_status": "SUCCESS",
                                "builder_version": BUILDER_VERSION}, persist=_persist_telemetry())
        except Exception as exc:
            failure_at = datetime.now(timezone.utc)
            metadata = ReadModelMetadata(
                read_model_type=read_model_type,
                calculation_version=READ_MODEL_CALCULATION_VERSIONS[read_model_type],
                input_fingerprint=input_fingerprint,
                portfolio_id=portfolio_id,
                calculated_at=failure_at,
                upstream_versions={},
                analysis_status=AnalysisStatus.FAILED,
                read_model_state=ReadModelState.FAILED,
                coverage=Coverage.not_tracked(),
                freshness=build_freshness([], calculated_at=failure_at),
                failure_class=type(exc).__name__, failure_at=failure_at,
            )
            database.save_capability_read_model(user_id, portfolio_id, metadata.model_dump(mode="json"), {})
            record_metric("ask.read_model.build", (time.monotonic() - build_started) * 1000,
                          tags={"read_model_type": read_model_type, "build_status": "FAILED",
                                "error_class": type(exc).__name__}, persist=_persist_telemetry())
    record_metric("ask.read_model.build_batch", (time.monotonic() - started) * 1000,
                  tags={"build_status": "COMPLETE", "models": len(built)}, persist=_persist_telemetry())
    return built


def _parse_row(row: dict[str, Any]) -> CapabilityReadModel:
    return CapabilityReadModel(id=row["id"], metadata=ReadModelMetadata.model_validate(row["metadata"]), data=row["data"])


def load_compatible_read_model(
    user_id: str, portfolio_id: str, read_model_type: str, input_fingerprint: str, *,
    schema_version: str = READ_MODEL_SCHEMA_VERSION, calculation_version: str | None = None,
) -> CompatibleReadModel:
    expected_calculation = calculation_version or READ_MODEL_CALCULATION_VERSIONS[read_model_type]
    history = database.capability_read_model_history(user_id, portfolio_id, read_model_type, 20)
    if not history:
        return CompatibleReadModel(state=CompatibilityState.MISSING, reason="No capability read model exists.")
    dependencies = READ_MODEL_DEPENDENCIES[read_model_type]
    tracked_dependencies = list((*dependencies["required"], *dependencies["optional"]))
    current_versions = database.analytical_dataset_versions(user_id, portfolio_id, tracked_dependencies)
    newest_failure = next((row for row in history if row["metadata"].get("read_model_state") == ReadModelState.FAILED), None)
    mismatch_reason = "No compatible model was found."
    for row in history:
        model = _parse_row(row)
        metadata = model.metadata
        if metadata.read_model_state in {ReadModelState.FAILED, ReadModelState.BUILDING, ReadModelState.MISSING}:
            continue
        if metadata.schema_version != schema_version:
            mismatch_reason = f"Schema version mismatch ({metadata.schema_version} != {schema_version})."
            continue
        if metadata.calculation_version != expected_calculation:
            mismatch_reason = f"Calculation version mismatch ({metadata.calculation_version} != {expected_calculation})."
            continue
        if metadata.input_fingerprint != input_fingerprint:
            mismatch_reason = "Portfolio/input fingerprint mismatch."
            continue
        mismatches = [
            name for name in tracked_dependencies
            if name not in current_versions or metadata.upstream_versions.get(name) != current_versions[name]["version"]
        ]
        if mismatches:
            mismatch_reason = f"Upstream version mismatch: {', '.join(mismatches)}."
            if metadata.read_model_state == ReadModelState.CURRENT:
                database.update_capability_read_model_state(model.id or "", ReadModelState.STALE, mismatch_reason)
                metadata.read_model_state = ReadModelState.STALE
                metadata.stale_reason = mismatch_reason
            return CompatibleReadModel(state=CompatibilityState.STALE, reason=mismatch_reason, model=model,
                                       input_fingerprint_match=True, upstream_version_match=False)
        if metadata.read_model_state == ReadModelState.STALE or newest_failure:
            reason = metadata.stale_reason or ("Latest rebuild failed; using the previous compatible model." if newest_failure else "Model is stale.")
            return CompatibleReadModel(state=CompatibilityState.STALE, reason=reason, model=model,
                                       input_fingerprint_match=True, upstream_version_match=True)
        return CompatibleReadModel(state=CompatibilityState.CURRENT, reason="Fingerprint and required upstream versions match.",
                                   model=model, input_fingerprint_match=True, upstream_version_match=True)
    return CompatibleReadModel(state=CompatibilityState.INCOMPATIBLE, reason=mismatch_reason,
                               input_fingerprint_match=False, upstream_version_match=None)


def invalidate_for_upstream_change(user_id: str, portfolio_id: str, dataset_type: str, version: str,
                                   effective_through: str | None = None) -> list[str]:
    database.upsert_analytical_dataset_version(user_id, portfolio_id, dataset_type, version, effective_through)
    affected = affected_read_models(dataset_type)
    reason = f"{dataset_type} advanced to {version}."
    for read_model_type in affected:
        history = database.capability_read_model_history(user_id, portfolio_id, read_model_type, 1)
        if history:
            database.update_capability_read_model_state(history[0]["id"], ReadModelState.STALE, reason)
        record_metric("ask.read_model.invalidated", tags={"read_model_type": read_model_type,
                      "upstream_dependency": dataset_type, "stale_reason": reason}, persist=_persist_telemetry())
    return affected


def reconcile_portfolio_read_models(user_id: str, portfolio_id: str, input_fingerprint: str) -> dict[str, str]:
    """Durable scheduler entry point: detect missed events by comparing stored dependency versions."""
    states: dict[str, str] = {}
    for read_model_type in PORTFOLIO_READ_MODEL_TYPES:
        result = load_compatible_read_model(user_id, portfolio_id, read_model_type, input_fingerprint)
        states[read_model_type] = result.state.value
        if result.state == CompatibilityState.STALE:
            record_metric("ask.read_model.reconciliation", tags={"read_model_type": read_model_type,
                          "read_model_state": result.state.value, "stale_reason": result.reason}, persist=_persist_telemetry())
    return states


def _single(read_model_type: str, *args: Any, **kwargs: Any) -> CapabilityReadModel | None:
    built = build_capability_read_models(*args, **kwargs, read_model_types=(read_model_type,))
    return built[0] if built else None


def build_portfolio_opportunity_read_model(*args: Any, **kwargs: Any) -> CapabilityReadModel | None:
    return _single("portfolio_opportunity", *args, **kwargs)


def build_portfolio_risk_read_model(*args: Any, **kwargs: Any) -> CapabilityReadModel | None:
    return _single("portfolio_risk", *args, **kwargs)


def build_portfolio_change_read_model(*args: Any, **kwargs: Any) -> CapabilityReadModel | None:
    return _single("portfolio_change", *args, **kwargs)


def build_portfolio_factor_state_read_model(*args: Any, **kwargs: Any) -> CapabilityReadModel | None:
    return _single("portfolio_factor_state", *args, **kwargs)


def build_watchlist_comparison_read_model(*args: Any, **kwargs: Any) -> CapabilityReadModel | None:
    return _single("watchlist_comparison", *args, **kwargs)


def build_portfolio_events_read_model(*args: Any, **kwargs: Any) -> CapabilityReadModel | None:
    return _single("portfolio_events", *args, **kwargs)


def build_portfolio_data_quality_read_model(*args: Any, **kwargs: Any) -> CapabilityReadModel | None:
    return _single("portfolio_data_quality", *args, **kwargs)


def build_score_attribution_read_model(*args: Any, **kwargs: Any) -> CapabilityReadModel | None:
    return _single("score_attribution", *args, **kwargs)


def build_thesis_status_read_model(*args: Any, **kwargs: Any) -> CapabilityReadModel | None:
    return _single("thesis_status", *args, **kwargs)


def build_portfolio_scenario_read_model(*args: Any, **kwargs: Any) -> CapabilityReadModel | None:
    return _single("portfolio_scenario", *args, **kwargs)


def build_optimizer_compatibility_read_model(*args: Any, **kwargs: Any) -> CapabilityReadModel | None:
    return _single("optimizer_compatibility", *args, **kwargs)


BUILDERS: dict[str, Callable[..., CapabilityReadModel | None]] = {
    "portfolio_opportunity": build_portfolio_opportunity_read_model,
    "portfolio_risk": build_portfolio_risk_read_model,
    "portfolio_change": build_portfolio_change_read_model,
    "portfolio_factor_state": build_portfolio_factor_state_read_model,
    "watchlist_comparison": build_watchlist_comparison_read_model,
    "portfolio_events": build_portfolio_events_read_model,
    "portfolio_data_quality": build_portfolio_data_quality_read_model,
    "score_attribution": build_score_attribution_read_model,
    "thesis_status": build_thesis_status_read_model,
    "portfolio_scenario": build_portfolio_scenario_read_model,
    "optimizer_compatibility": build_optimizer_compatibility_read_model,
}

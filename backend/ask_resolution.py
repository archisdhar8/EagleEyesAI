from __future__ import annotations

import re
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from .analytical_contract import canonical_data
from .ask_runtime import PortfolioContext


class DependencyClass(StrEnum):
    ALWAYS_AVAILABLE_SYSTEM_DATA = "ALWAYS_AVAILABLE_SYSTEM_DATA"
    ON_DEMAND_COMPUTATION = "ON_DEMAND_COMPUTATION"
    USER_REQUIRED_CONTEXT = "USER_REQUIRED_CONTEXT"


class DataHealthStatus(StrEnum):
    CURRENT = "CURRENT"
    PARTIAL = "PARTIAL"
    STALE = "STALE"
    MISSING = "MISSING"
    FAILED = "FAILED"


class DataHealthDomain(BaseModel):
    domain: str
    status: DataHealthStatus
    coverage: float | None = None
    freshness: str | None = None
    last_successful_update: str | None = None
    failure_reason: str | None = None
    repair_action: str | None = None


class SupportedClaim(BaseModel):
    claim: str
    scope: str = "objective"
    evidence_ids: list[str] = Field(default_factory=list)


class RequirementResolution(BaseModel):
    claims_requested: list[str] = Field(default_factory=list)
    evidence_available: list[str] = Field(default_factory=list)
    stale_or_missing_system_data: list[str] = Field(default_factory=list)
    automatically_creatable_computation: list[str] = Field(default_factory=list)
    user_required_missing_context: list[str] = Field(default_factory=list)
    jobs_or_actions: list[dict[str, Any]] = Field(default_factory=list)
    fallback_capabilities: list[str] = Field(default_factory=list)


class SupportedAnswer(BaseModel):
    direct_answer: str
    supported_claims: list[SupportedClaim] = Field(default_factory=list)
    partial_claims: list[SupportedClaim] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
    pending_claims: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    jobs_started: list[dict[str, Any]] = Field(default_factory=list)
    data_gaps: list[str] = Field(default_factory=list)
    user_input_needed: list[str] = Field(default_factory=list)
    confidence: str = "LOW"
    coverage: dict[str, Any] = Field(default_factory=dict)


DEPENDENCY_MATRIX: dict[str, DependencyClass] = {
    "prices": DependencyClass.ALWAYS_AVAILABLE_SYSTEM_DATA,
    "price_history": DependencyClass.ALWAYS_AVAILABLE_SYSTEM_DATA,
    "fundamentals": DependencyClass.ALWAYS_AVAILABLE_SYSTEM_DATA,
    "fundamental_history": DependencyClass.ALWAYS_AVAILABLE_SYSTEM_DATA,
    "classifications": DependencyClass.ALWAYS_AVAILABLE_SYSTEM_DATA,
    "events": DependencyClass.ALWAYS_AVAILABLE_SYSTEM_DATA,
    "earnings_events": DependencyClass.ALWAYS_AVAILABLE_SYSTEM_DATA,
    "macro_events": DependencyClass.ALWAYS_AVAILABLE_SYSTEM_DATA,
    "company_catalysts": DependencyClass.ALWAYS_AVAILABLE_SYSTEM_DATA,
    "prediction_market_events": DependencyClass.ALWAYS_AVAILABLE_SYSTEM_DATA,
    "macro": DependencyClass.ALWAYS_AVAILABLE_SYSTEM_DATA,
    "market": DependencyClass.ALWAYS_AVAILABLE_SYSTEM_DATA,
    "prediction_markets": DependencyClass.ALWAYS_AVAILABLE_SYSTEM_DATA,
    "portfolio_history": DependencyClass.ALWAYS_AVAILABLE_SYSTEM_DATA,
    "score_history": DependencyClass.ALWAYS_AVAILABLE_SYSTEM_DATA,
    "cash_hurdle": DependencyClass.ALWAYS_AVAILABLE_SYSTEM_DATA,
    "simulation": DependencyClass.ON_DEMAND_COMPUTATION,
    "optimization": DependencyClass.ON_DEMAND_COMPUTATION,
    "backtest": DependencyClass.ON_DEMAND_COMPUTATION,
    "deep_research": DependencyClass.ON_DEMAND_COMPUTATION,
    "saved_thesis": DependencyClass.USER_REQUIRED_CONTEXT,
    "thesis_breakers": DependencyClass.USER_REQUIRED_CONTEXT,
    "tax_lots": DependencyClass.USER_REQUIRED_CONTEXT,
    "custom_constraints": DependencyClass.USER_REQUIRED_CONTEXT,
}


_REQUESTED_CLAIMS = {
    "PORTFOLIO_PERFORMANCE": ["hypothetical portfolio return versus SPY and Nasdaq 100", "actual-account limitation"],
    "GAIN_LOSS_ATTRIBUTION": ["holding-level unrealized gain and loss contribution", "realized-return limitation"],
    "RISK_EFFICIENCY": ["risk concentration relative to saved tolerance", "expected-return limitation"],
    "DIVERSIFICATION": ["company, sector, strategy, and correlation diversification"],
    "OVERLAP_RISK": ["correlated clusters and shared economic dependencies"],
    "DOWNSIDE_CAPACITY": ["modeled loss and drawdown range"],
    "POSITION_SIZING": ["position weights versus saved policy maximum"],
    "CASH_RESERVE": ["saved cash floor and target allocation"],
    "SECTOR_SHOCK": ["first-order technology-sector shock estimate"],
    "DECISION_VS_INDEX": ["decision performance after taxes and fees"],
    "THESIS_STRENGTH": ["saved thesis state and objective evidence strength"],
    "POSITION_ACTION_REVIEW": ["evidence-based review queue without trade execution"],
    "AVERAGING_DOWN_REVIEW": ["named-position thesis and price evidence"],
    "TARGET_PRICE_REVIEW": ["named-stock valuation evidence and price bands"],
    "OPTIONS_COSTS": ["option premium, spread, commission, and theta costs"],
    "OPTIONS_EXPIRY": ["expiration versus expected catalyst timing"],
    "TRADE_PLAN_METRICS": ["expected return, maximum loss, breakeven, and exit plan"],
    "OPPORTUNITY_RANKING": ["eligible opportunity ranking", "supporting evidence"],
    "THESIS_REPLACEMENT": ["personal weakest thesis", "objective weakest setup", "replacement evidence"],
    "PORTFOLIO_CHANGE": ["material change since compatible baseline"],
    "VALUATION_RANKING": ["relative valuation burden"],
    "HIDDEN_RISK": ["position, sector, theme, and correlation concentration"],
    "MULTI_SCENARIO": ["scenario loss/wealth estimate", "immediate exposure mapping"],
    "WATCHLIST_COMPARISON": ["candidate versus incumbent dominance"],
    "PORTFOLIO_EVENTS": ["upcoming portfolio events by category"],
    "DATA_QUALITY": ["field-level ranking reliability"],
    "SCORE_ATTRIBUTION": ["score delta attribution"],
    "THESIS_INVALIDATION": ["personal thesis breakers", "objective holding risks"],
    "PORTFOLIO_ANALYSIS": ["actionable rebalance", "current objective portfolio issues"],
    "MULTIFACTOR_SCREEN": ["full matches", "strongest near matches"],
    "RECOMMENDATION_COUNTERCASE": ["countercase to a verified recommendation"],
    "CASH_ALLOCATION": ["candidate evidence versus a sourced cash hurdle"],
}


def _num(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _summaries(tool_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in tool_results:
        data = canonical_data(row)
        if not isinstance(data, dict) or not data:
            data = row.get("summary")
        if isinstance(data, dict):
            output.append(data)
    return output


def _first_summary(tool_results: list[dict[str, Any]]) -> dict[str, Any]:
    return next(iter(_summaries(tool_results)), {})


def _summary_for(tool_results: list[dict[str, Any]], *tool_names: str) -> dict[str, Any]:
    wanted = set(tool_names)
    for row in tool_results:
        if str(row.get("tool_name") or "") not in wanted:
            continue
        data = canonical_data(row)
        if isinstance(data, dict) and data:
            return data
        if isinstance(row.get("summary"), dict):
            return row["summary"]
    return _first_summary(tool_results)


def _pct(value: Any) -> str:
    number = _num(value)
    return "unavailable" if number is None else f"{number:.1%}"


def _money(value: Any) -> str:
    number = _num(value)
    return "unavailable" if number is None else f"${number:,.0f}"


def _markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return ""
    return "| " + " | ".join(headers) + " |\n| " + " | ".join("---" for _ in headers) + " |\n" + "\n".join(
        "| " + " | ".join(row) + " |" for row in rows
    )


def _job_rows(tool_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"job_id": row.get("job_id"), "capability": row.get("tool_name"), "status": row.get("status")}
            for row in tool_results if row.get("job_id")]


def resolve_requirements(
    *, intent: str, question: str, context: PortfolioContext | None,
    tool_results: list[dict[str, Any]], data_health: list[DataHealthDomain] | None = None,
    conversation_context: dict[str, Any] | None = None,
) -> RequirementResolution:
    del question, context, conversation_context
    resolution = RequirementResolution(claims_requested=_REQUESTED_CLAIMS.get(intent, [intent.lower().replace("_", " ")]))
    for row in tool_results:
        canonical = row.get("analysis_result") or {}
        capability = str(canonical.get("capability") or row.get("tool_name") or "analysis")
        if str(row.get("status") or "").lower() in {"complete", "success", "partial"}:
            resolution.evidence_available.append(capability)
        for prerequisite in canonical.get("prerequisites") or []:
            if prerequisite.get("satisfied"):
                continue
            name = str(prerequisite.get("name") or "")
            normalized = ("saved_thesis" if "thesis" in name else "tax_lots" if "tax_lot" in name else
                          "simulation" if "scenario" in name else "optimization" if "optimizer" in name else
                          "cash_hurdle" if "cash_hurdle" in name else "portfolio_history" if "historical" in name else name)
            dependency_class = DEPENDENCY_MATRIX.get(normalized, DependencyClass.ALWAYS_AVAILABLE_SYSTEM_DATA)
            reason = str(prerequisite.get("reason") or normalized.replace("_", " "))
            if dependency_class == DependencyClass.USER_REQUIRED_CONTEXT:
                resolution.user_required_missing_context.append(reason)
            elif dependency_class == DependencyClass.ON_DEMAND_COMPUTATION:
                resolution.automatically_creatable_computation.append(normalized)
            else:
                resolution.stale_or_missing_system_data.append(reason)
    resolution.jobs_or_actions = _job_rows(tool_results)
    for item in data_health or []:
        if item.status != DataHealthStatus.CURRENT:
            resolution.stale_or_missing_system_data.append(
                f"{item.domain}: {item.status.value.lower()}" + (f" ({item.failure_reason})" if item.failure_reason else "")
            )
    fallback = {
        "OPPORTUNITY_RANKING": ["near_match_factor_evidence"],
        "THESIS_REPLACEMENT": ["objective_holding_evidence", "watchlist_dominance"],
        "PORTFOLIO_CHANGE": ["current_portfolio_snapshot"],
        "VALUATION_RANKING": ["partial_relative_valuation"],
        "MULTI_SCENARIO": ["portfolio_exposure_mapping"],
        "THESIS_INVALIDATION": ["objective_risk_evidence"],
        "PORTFOLIO_ANALYSIS": ["concentration_and_risk_diagnostics"],
        "MULTIFACTOR_SCREEN": ["near_match_factor_evidence"],
        "CASH_ALLOCATION": ["candidate_evidence_without_cash_superiority_claim"],
    }
    resolution.fallback_capabilities = fallback.get(intent, [])
    resolution.evidence_available = list(dict.fromkeys(resolution.evidence_available))
    resolution.stale_or_missing_system_data = list(dict.fromkeys(resolution.stale_or_missing_system_data))
    resolution.user_required_missing_context = list(dict.fromkeys(resolution.user_required_missing_context))
    return resolution


def _failed_gates(row: dict[str, Any]) -> list[str]:
    eligibility = row.get("eligibility") or {}
    missing = list(eligibility.get("missing_fields") or row.get("missing_fields") or [])
    placeholders = [f"placeholder {value}" for value in eligibility.get("placeholder_fields") or []]
    return [*missing, *placeholders]


def _near_score(row: dict[str, Any], keys: tuple[str, ...]) -> float:
    values = [_num(row.get(key)) for key in keys]
    observed = [value for value in values if value is not None]
    return sum(observed) / len(observed) if observed else -1


def _holding_line(row: dict[str, Any]) -> str:
    fields = []
    for key, label in (("health_score", "health"), ("fundamental_score", "fundamentals"),
                       ("valuation_score", "valuation"), ("momentum_score", "momentum")):
        if (value := _num(row.get(key))) is not None:
            fields.append(f"{label} {value:.1f}")
    weight = _num(row.get("weight"))
    if weight is not None:
        fields.append(f"weight {weight:.1%}")
    return f"**{row.get('ticker')}** — " + (", ".join(fields) or "limited stored factor evidence")


def compose_supported_answer(
    *, intent: str, question: str, context: PortfolioContext | None,
    tool_results: list[dict[str, Any]], deterministic_answer: str | None,
    data_health: list[DataHealthDomain] | None = None,
    conversation_context: dict[str, Any] | None = None,
) -> tuple[RequirementResolution, SupportedAnswer]:
    resolution = resolve_requirements(intent=intent, question=question, context=context, tool_results=tool_results,
                                      data_health=data_health, conversation_context=conversation_context)
    summary = _first_summary(tool_results)
    jobs = resolution.jobs_or_actions
    gaps = resolution.stale_or_missing_system_data
    user_gaps = resolution.user_required_missing_context
    answer = deterministic_answer or "The requested claim is not supported by the currently validated evidence."
    supported: list[SupportedClaim] = []
    partial: list[SupportedClaim] = []
    unsupported: list[str] = []
    pending = [str(row.get("capability") or "calculation") for row in jobs]

    if intent == "PORTFOLIO_PERFORMANCE":
        backtest = _summary_for(tool_results, "portfolio_backtest")
        results = list(backtest.get("results") or [])
        if results:
            labels = {
                "current_portfolio": "Current portfolio",
                "benchmark_spy": "S&P 500 (SPY)",
                "benchmark_relevant_qqq": "Nasdaq 100 (QQQ)",
            }
            rows = [[labels.get(str(row.get("key")), str(row.get("label") or row.get("key"))),
                     _pct(row.get("total_return")), _pct(row.get("annual_return")), _pct(row.get("volatility")),
                     _pct(row.get("maximum_drawdown")),
                     f"{_num(row.get('ending_growth_of_one')):.2f}×" if _num(row.get("ending_growth_of_one")) is not None else "unavailable"]
                    for row in results if str(row.get("key")) in labels]
            answer = "## Hypothetical benchmark comparison\n\n" + _markdown_table(
                ["Series", "Total return", "Annualized return", "Volatility", "Max drawdown", "Growth of $1"], rows,
            )
            period = ""
            if backtest.get("period_start") and backtest.get("period_end"):
                period = f" The common displayed period is **{backtest.get('period_start')} through {backtest.get('period_end')}**."
            answer += "\n\nThis reconstructs the **current holdings and current weights** over the common stored history." + period + " It is not your actual account return because deposits, withdrawals, fills, dividends, taxes, and fees are not fully represented.\n\n**To calculate your actual return:** reply with or import dated transactions and external cash flows; EagleEyes can then calculate time-weighted and money-weighted performance without treating today's holdings as historical holdings."
            supported.append(SupportedClaim(claim="Current-weight hypothetical portfolio backtest versus stored benchmarks"))
            unsupported.append("Actual account performance without a complete transaction and valuation ledger")
        else:
            answer = (
                "I cannot yet state your actual performance versus the S&P 500 or Nasdaq because EagleEyes does not have a complete transaction-and-cash-flow ledger for this account. "
                "A current-weight hypothetical backtest against **SPY and QQQ** has been queued; it will compare the same common history and disclose drawdown and volatility.\n\n"
                "**Needed for actual performance:** dated deposits and withdrawals, fills, dividends, fees, and account valuations. Current weights alone cannot reconstruct what you personally earned."
            )
            pending.append("current-weight benchmark backtest")
            unsupported.append("Actual account return versus SPY and QQQ")
            partial.append(SupportedClaim(claim="Specific benchmark calculation and missing actual-account inputs identified"))
    elif intent == "GAIN_LOSS_ATTRIBUTION":
        risk_summary = _summary_for(tool_results, "portfolio_risk")
        positions = list(risk_summary.get("positions") or [])
        known = [row for row in positions if _num(row.get("unrealized_gain_loss")) is not None]
        if known:
            winners = sorted((row for row in known if _num(row.get("unrealized_gain_loss")) >= 0), key=lambda row: _num(row.get("unrealized_gain_loss")) or 0, reverse=True)[:5]
            losers = sorted((row for row in known if _num(row.get("unrealized_gain_loss")) < 0), key=lambda row: _num(row.get("unrealized_gain_loss")) or 0)[:5]
            table_rows = [[str(row.get("ticker")), _money(row.get("unrealized_gain_loss")), _pct(row.get("weight")), "Gain" if _num(row.get("unrealized_gain_loss")) >= 0 else "Loss"] for row in [*winners, *losers]]
            answer = "## Largest stored unrealized contributors\n\n" + _markdown_table(["Holding", "Unrealized P/L", "Current weight", "Direction"], table_rows)
            answer += "\n\nThis uses saved aggregate cost basis and current market value. It excludes realized gains, dividends, deposits/withdrawals, taxes, and fees, so it is **not total-return attribution**."
            supported.append(SupportedClaim(claim="Holding-level unrealized gain/loss from saved cost basis"))
            unsupported.append("Complete total-return contribution without transaction history")
        else:
            largest = sorted(positions, key=lambda row: _num(row.get("weight")) or 0, reverse=True)[:5]
            answer = "EagleEyes cannot truthfully rank gain and loss contributors because the saved holdings do not contain enough cost basis or transaction history. Current influence by portfolio weight is:\n\n" + "\n".join(f"- **{row.get('ticker')}** — {_pct(row.get('weight'))}" for row in largest)
            answer += "\n\nAdd cost basis for unrealized P/L; add dated fills, cash flows, dividends, and fees for true contribution analysis."
            partial.append(SupportedClaim(claim="Current position influence shown while attribution inputs are missing"))
            unsupported.append("Gain/loss contribution without cost basis and transactions")
    elif intent == "RISK_EFFICIENCY":
        risk_summary = _summary_for(tool_results, "portfolio_risk")
        backtest = _summary_for(tool_results, "portfolio_backtest")
        profile = risk_summary.get("profile") or {}
        contributors = list(risk_summary.get("risk_contributors") or [])
        if not contributors:
            contributors = list(risk_summary.get("positions") or [])
        leaders = sorted(contributors, key=lambda row: _num(row.get("risk_contribution")) or _num(row.get("weight")) or 0, reverse=True)[:5]
        performance_rows = list(backtest.get("results") or [])
        comparison_rows = []
        for row in performance_rows:
            annual, volatility = _num(row.get("annual_return")), _num(row.get("volatility"))
            comparison_rows.append([
                str(row.get("label") or row.get("key")), _pct(annual), _pct(volatility),
                _pct(row.get("maximum_drawdown")), f"{annual / volatility:.2f}" if annual is not None and volatility and volatility > 0 else "unavailable",
            ])
        answer = (
            "## What the stored evidence says\n\n"
            f"Your saved risk tolerance is **{profile.get('risk_tolerance', 'not saved')}/10** and loss capacity is **{profile.get('loss_capacity', 'not saved')}/10**."
        )
        if comparison_rows:
            answer += " The current-weight historical proxy is:\n\n" + _markdown_table(
                ["Series", "Annualized return", "Volatility", "Max drawdown", "Return / volatility"], comparison_rows,
            )
            answer += "\n\nThe last column is a simple historical return-to-volatility ratio, not a forecast or a Sharpe ratio. It lets you see whether the current mix delivered more or less historical return per unit of volatility than SPY and QQQ over the same window."
        answer += "\n\n## Largest current risk/influence concentrations\n\n" + "\n".join(
            f"- **{row.get('ticker')}** — " + (f"modeled risk contribution {_pct(row.get('risk_contribution'))}" if _num(row.get("risk_contribution")) is not None else f"portfolio weight {_pct(row.get('weight'))}") for row in leaders
        )
        answer += "\n\nThis can flag inefficient-looking historical risk and concentration, but it cannot prove a forward-looking optimum without expected-return assumptions. **Next question:** should EagleEyes optimize for lower drawdown, lower volatility, or a minimum return target?"
        partial.append(SupportedClaim(claim="Saved risk preference and current risk concentration"))
        unsupported.append("Risk efficiency without a supported expected-return model")
    elif intent in {"DIVERSIFICATION", "OVERLAP_RISK"}:
        intelligence = _summary_for(tool_results, "portfolio_intelligence")
        concentration = intelligence.get("concentration") or {}
        positions = list(concentration.get("positions") or intelligence.get("all_holdings") or [])
        sectors = list(concentration.get("sector") or [])
        correlation = intelligence.get("correlation") or {}
        clusters = list(correlation.get("clusters") or [])
        dependencies = list(intelligence.get("economic_dependencies") or [])
        answer = "## Diversification and overlapping bets\n\n"
        if concentration.get("effective_holdings") is not None:
            answer += f"The saved weights behave like roughly **{_num(concentration.get('effective_holdings')):.1f} equally sized holdings**.\n\n"
        if positions:
            answer += "**Largest companies/funds**\n\n" + "\n".join(f"- **{row.get('ticker')}** — {_pct(row.get('weight'))}" for row in positions[:6]) + "\n\n"
        if sectors:
            answer += "**Largest classified sectors**\n\n" + "\n".join(f"- **{row.get('sector')}** — {_pct(row.get('weight'))}" for row in sectors[:5]) + "\n\n"
        if clusters:
            answer += "**Holdings behaving like the same bet**\n\n" + "\n".join(
                f"- **{', '.join(row.get('holdings') or [])}** — {_pct(row.get('portfolio_weight'))} combined" +
                (f"; strongest pair correlation {_num((row.get('strongest_pair') or {}).get('correlation')):.2f}" if _num((row.get('strongest_pair') or {}).get('correlation')) is not None else "")
                for row in clusters[:4]
            ) + "\n\n"
        if dependencies:
            answer += "**Shared economic drivers**\n\n" + "\n".join(f"- **{str(row.get('factor')).replace('_', ' ').title()}** — {_pct(row.get('mapped_portfolio_weight'))} mapped across {', '.join((row.get('holdings') or [])[:8])}" for row in dependencies[:5])
        if not any((positions, sectors, clusters, dependencies)):
            answer += "The cached intelligence result has no usable position, sector, correlation, or dependency rows. Refresh portfolio intelligence before drawing a diversification conclusion."
            unsupported.append("Diversification conclusion without portfolio-intelligence coverage")
        else:
            supported.append(SupportedClaim(claim="Company, sector, correlation-cluster, and economic-dependency diversification"))
    elif intent == "DOWNSIDE_CAPACITY":
        scenario = _summary_for(tool_results, "portfolio_scenario", "portfolio_decision_lab")
        simulation = scenario.get("latest_simulation") or scenario
        outcomes = list(simulation.get("outcomes") or simulation.get("strategies") or [])
        current = next((row for row in outcomes if row.get("strategy_key") in {"current", "current_portfolio"} or row.get("key") == "current_portfolio"), None)
        if current:
            drawdowns = current.get("drawdown_percentiles") or {}
            answer = (
                "The latest compatible model does not produce one certain loss percentage; it produces a distribution. "
                f"For the current portfolio, probability of finishing below the starting value is **{_pct(current.get('probability_of_loss'))}** and the disclosed adverse drawdown estimate is **{_pct(drawdowns.get('p10') if drawdowns else current.get('modeled_drawdown'))}**.\n\n"
                "This is a modeled historical/simulation result, not a guarantee or a worst-case bound. A crisis can exceed the modeled range."
            )
            supported.append(SupportedClaim(claim="Latest compatible modeled loss probability and adverse drawdown"))
        else:
            answer = "No compatible loss-distribution result is available yet, so EagleEyes will not invent a percentage. A canonical scenario simulation has been queued. Until it completes, current weights and historical drawdowns can identify exposure but cannot establish a major-decline loss estimate."
            pending.append("portfolio loss-distribution simulation")
            unsupported.append("Major-decline loss percentage before compatible simulation")
            partial.append(SupportedClaim(claim="Specific pending calculation and limitation identified"))
    elif intent == "POSITION_SIZING":
        risk_summary = _summary_for(tool_results, "portfolio_risk")
        positions = list(risk_summary.get("positions") or [])
        policy = risk_summary.get("policy") or {}
        limit = _num(policy.get("max_single_stock_weight"))
        if limit is None:
            answer = "No saved single-position maximum is available, so EagleEyes cannot label a position too large relative to your policy. The largest current positions are:\n\n" + "\n".join(f"- **{row.get('ticker')}** — {_pct(row.get('weight'))}" for row in positions[:8])
            answer += "\n\nSave or approve a maximum single-stock weight to turn this into a policy-breach test."
            partial.append(SupportedClaim(claim="Largest current position weights"))
        else:
            oversized = [row for row in positions if (_num(row.get("weight")) or 0) > limit]
            answer = f"Your saved policy maximum is **{limit:.1%} per position** ({policy.get('status') or 'status unavailable'}).\n\n"
            answer += _markdown_table(["Position", "Weight", "Above limit"], [[str(row.get("ticker")), _pct(row.get("weight")), f"{((_num(row.get('weight')) or 0)-limit):.1%}"] for row in oversized]) if oversized else "No current position exceeds that saved maximum."
            answer += "\n\nFund ETFs may require look-through analysis before treating fund-level weight as single-company exposure."
            supported.append(SupportedClaim(claim="Position weights compared with saved policy maximum"))
    elif intent == "CASH_RESERVE":
        risk_summary = _summary_for(tool_results, "portfolio_risk")
        policy = risk_summary.get("policy") or {}
        profile = risk_summary.get("profile") or {}
        floor = _num(policy.get("minimum_cash_reserve"))
        target = _num((policy.get("target_allocation") or {}).get("cash"))
        answer = "## Saved cash framework\n\n"
        answer += f"- Minimum cash reserve: **{_money(floor)}**\n" if floor is not None else "- Minimum cash reserve: **not saved**\n"
        answer += f"- Target portfolio cash allocation: **{_pct(target)}**\n" if target is not None else "- Target portfolio cash allocation: **not saved**\n"
        answer += f"- Saved annual withdrawals: **{_money(profile.get('annual_withdrawal'))}**\n"
        answer += f"- Saved annual income need: **{_money(profile.get('annual_income_need'))}**\n\n"
        answer += "Use the greater of the approved dollar floor, near-term spending/liquidity needs, and the amount required to keep the portfolio inside its target range. EagleEyes cannot personalize an emergency reserve further without monthly essential spending and near-term purchase timing."
        supported.append(SupportedClaim(claim="Saved cash floor, allocation target, and withdrawal context"))
    elif intent == "SECTOR_SHOCK":
        intelligence = _summary_for(tool_results, "portfolio_intelligence")
        concentration = intelligence.get("concentration") or {}
        sectors = list(concentration.get("sector") or [])
        technology = sum((_num(row.get("weight")) or 0) for row in sectors if "tech" in str(row.get("sector") or "").lower())
        magnitude_match = re.search(r"(\d+(?:\.\d+)?)%", question)
        magnitude = float(magnitude_match.group(1)) / 100 if magnitude_match else .20
        if technology > 0:
            first_order = -(technology * magnitude)
            answer = (
                f"Classified technology exposure is **{technology:.1%}**. A **{magnitude:.0%}** decline applied only to that mapped sleeve implies an immediate first-order portfolio effect of about **{first_order:.1%}**.\n\n"
                "That is arithmetic exposure mapping—not a stress-test forecast. It excludes ETF look-through gaps, cross-sector spillovers, changing correlations, options, and any recovery. A full scenario model may show a larger or smaller result."
            )
            supported.append(SupportedClaim(claim="First-order technology-sector exposure shock"))
        else:
            answer = "Technology-sector weight is not sufficiently classified in the current intelligence snapshot, so EagleEyes cannot multiply a 20% sector move into a defensible portfolio loss. Refresh classifications and ETF look-through first."
            unsupported.append("Technology shock estimate without classified exposure")
            partial.append(SupportedClaim(claim="Classification prerequisite for the requested shock identified"))
    elif intent == "DECISION_VS_INDEX":
        backtest = _summary_for(tool_results, "portfolio_backtest")
        results = list(backtest.get("results") or [])
        current = next((row for row in results if row.get("key") == "current_portfolio"), None)
        benchmarks = [row for row in results if str(row.get("key") or "").startswith("benchmark_")]
        answer = "## Best available gross proxy\n\n"
        if current and benchmarks:
            rows = []
            current_return = _num(current.get("total_return"))
            for row in benchmarks:
                benchmark_return = _num(row.get("total_return"))
                gap = current_return - benchmark_return if current_return is not None and benchmark_return is not None else None
                rows.append([str(row.get("label") or row.get("key")), _pct(current_return), _pct(benchmark_return), _pct(gap)])
            answer += _markdown_table(["Benchmark", "Current-weight portfolio", "Benchmark", "Gross gap"], rows)
            positive_gaps = [(_num(current.get("total_return")) or 0) - (_num(row.get("total_return")) or 0) for row in benchmarks]
            answer += "\n\nThe gross gap is also the approximate **maximum combined tax, fee, timing, and trading drag** the portfolio could absorb before losing that historical lead; a negative gap means there was no gross cushion in this proxy."
            supported.append(SupportedClaim(claim="Current-weight gross historical comparison versus SPY and QQQ"))
        else:
            answer += "The current-weight SPY/QQQ comparison could not be calculated from the stored common price window."
        answer += (
            "\n\nThis is not your realized decision performance: today's holdings create survivorship and timing bias. "
            "For the after-tax, after-fee answer, EagleEyes still needs dated buys, sells, deposits, withdrawals, dividends, realized tax lots, tax rates by account, commissions, and spread/slippage estimates.\n\n"
            "**Next step:** import that ledger, or reply with the evaluation period, benchmark, and estimated all-in annual drag to run an explicit approximation."
        )
        unsupported.append("After-tax, after-fee decision attribution without a complete ledger")
        partial.append(SupportedClaim(claim="Specific ledger requirements and current-weight backtest limitation identified"))
    elif intent == "THESIS_STRENGTH":
        thesis = _summary_for(tool_results, "thesis_invalidation", "thesis_monitor")
        saved = list(thesis.get("saved_theses") or [])
        if saved:
            rows = [[str(row.get("ticker")), str(row.get("status") or "saved"), str((row.get("monitor") or {}).get("overall_status") or "not evaluated")] for row in saved[:15]]
            answer = "## Saved thesis status\n\n" + _markdown_table(["Holding", "Thesis", "Monitor"], rows)
            answer += "\n\nA strong thesis requires both a saved claim and current supporting evidence; the monitor status is not a return forecast."
            supported.append(SupportedClaim(claim="Saved thesis and monitor status"))
        else:
            largest = sorted(
                list(thesis.get("largest_positions") or []),
                key=lambda row: _near_score(row, ("health_score", "fundamental_score", "valuation_score", "momentum_score")),
                reverse=True,
            )
            answer = "No personal theses are saved, so the honest substitute is an **objective evidence-strength ranking**:\n\n" + "\n".join(f"- {_holding_line(row)}" for row in largest[:10])
            answer += "\n\nThese leaders have stronger stored evidence; that does not prove your original investment claim. **Reply with one holding and one sentence explaining why you own it** (for example, `MSFT: durable cloud growth with stable margins`). EagleEyes can turn that into a draft thesis with supporting evidence and explicit invalidation tests for you to review—not silently save it."
            partial.append(SupportedClaim(claim="Objective holding evidence while personal thesis state is absent"))
            unsupported.append("Personal thesis-strength ranking without saved theses")
    elif intent == "POSITION_ACTION_REVIEW":
        overview = _summary_for(tool_results, "portfolio_overview")
        candidates = list(overview.get("candidates") or overview.get("opportunities") or [])
        holdings = list(overview.get("all_holdings") or overview.get("positions") or [])
        ranked = candidates or sorted(holdings, key=lambda row: _num(row.get("health_score")) or _num(row.get("opportunity_score")) or -1, reverse=True)
        if ranked:
            answer = "EagleEyes cannot issue automatic buy/sell instructions, but it can create a review queue from current verified evidence.\n\n" + _markdown_table(
                ["Holding", "Evidence score", "Review category", "Reason"],
                [[str(row.get("ticker")), f"{(_num(row.get('opportunity_score')) or _num(row.get('health_score')) or 0):.1f}",
                  "Hold / verify" if index < 5 else "Reduce / exit review",
                  "; ".join((row.get("opposing_evidence") or row.get("risk_flags") or [])[:2]) or "Confirm thesis, valuation, sizing, and taxes"]
                 for index, row in enumerate(ranked[:10])],
            )
            answer += "\n\nThese are research categories, not trade instructions. A reduce/exit decision still requires saved thesis breakers, tax lots, transaction costs, and an approved policy."
            partial.append(SupportedClaim(claim="Evidence-based position review queue"))
        else:
            answer = "No eligible portfolio ranking is available, so no position can be placed into a buy/hold/reduce/exit review category. Refresh the portfolio overview and save thesis/policy context first."
            unsupported.append("Position action review without eligible portfolio evidence")
    elif intent == "AVERAGING_DOWN_REVIEW":
        ticker = next((str(row.get("ticker")) for row in tool_results if row.get("ticker")), None)
        company = _summary_for(tool_results, "company_analysis")
        if not ticker and context:
            ticker = None
        if not ticker and not company.get("ticker"):
            risk = _summary_for(tool_results, "portfolio_risk")
            losing = sorted(
                [row for row in risk.get("positions") or [] if (_num(row.get("unrealized_gain_loss")) or 0) < 0],
                key=lambda row: _num(row.get("unrealized_gain_loss")) or 0,
            )
            answer = "## Current losing positions with stored cost basis\n\n"
            if losing:
                answer += _markdown_table(
                    ["Holding", "Unrealized P/L", "Current weight"],
                    [[str(row.get("ticker")), _money(row.get("unrealized_gain_loss")), _pct(row.get("weight"))] for row in losing[:10]],
                )
            else:
                answer += "No current position has a negative stored unrealized P/L, or cost basis is missing."
            answer += "\n\nA loss alone is not a reason to add. Name one ticker and the proposed dollar amount. EagleEyes will test: thesis/breaker status, evidence change since purchase, current valuation, resulting weight versus policy, and whether the lower price improved expected payoff rather than merely lowering average cost."
            user_gaps.append("A losing-position ticker and proposed add size")
            unsupported.append("Averaging-down decision without a named position")
            partial.append(SupportedClaim(claim="Minimum clarification and decision criteria identified"))
        else:
            name = ticker or str(company.get("ticker"))
            answer = f"For **{name}**, adding is justified only if the original thesis remains supported, no breaker has triggered, valuation has improved on unchanged or stronger fundamentals, and the resulting position stays inside policy limits. A lower price by itself is not evidence.\n\nCurrent stored company evidence was retrieved, but a personal decision still requires the purchase thesis, cost basis, and proposed add size."
            partial.append(SupportedClaim(claim=f"Objective averaging-down decision framework for {name}"))
    elif intent == "TARGET_PRICE_REVIEW":
        company = _summary_for(tool_results, "company_analysis")
        ticker = str(company.get("ticker") or "")
        if not ticker:
            overview = _summary_for(tool_results, "portfolio_overview")
            candidates = list(overview.get("candidates") or overview.get("opportunities") or overview.get("all_holdings") or [])
            candidates = sorted(
                candidates,
                key=lambda row: _num(row.get("valuation_score")) or _num(row.get("valuation")) or -1,
                reverse=True,
            )
            answer = "## Relative valuation starting point\n\n"
            if candidates:
                answer += _markdown_table(
                    ["Holding", "Stored valuation score", "Evidence score"],
                    [[str(row.get("ticker")), f"{(_num(row.get('valuation_score')) or _num(row.get('valuation')) or 0):.1f}", f"{(_num(row.get('health_score')) or _num(row.get('opportunity_score')) or _num(row.get('decision_score')) or 0):.1f}"] for row in candidates[:8]],
                )
                answer += "\n\nA higher stored valuation score means relatively more supportive valuation evidence; it is not a dollar price target."
            answer += "\n\nName one ticker and choose a method—`earnings multiple`, `free-cash-flow yield`, or `DCF`. If you do not have assumptions, EagleEyes can show a labeled sensitivity table rather than one false-precision target."
            user_gaps.append("A stock ticker")
            unsupported.append("Target-price bands without a named stock")
            partial.append(SupportedClaim(claim="Company-specific target-price prerequisites identified"))
        else:
            price_state = company.get("price_state") or {}
            valuation = company.get("valuation") or {}
            price = _num(price_state.get("price") or price_state.get("current_price") or company.get("price"))
            valuation_score = _num(valuation.get("score") or company.get("valuation_score"))
            answer = f"## {ticker} valuation starting point\n\n- Stored price: **{_money(price)}**\n- Relative valuation score: **{valuation_score:.1f}/100**" if valuation_score is not None else f"## {ticker} valuation starting point\n\n- Stored price: **{_money(price)}**\n- Relative valuation score: **unavailable**"
            answer += "\n\nChoose `earnings multiple`, `free-cash-flow yield`, or `DCF`, and provide your normalized earnings/cash flow plus growth and margin-of-safety assumptions. EagleEyes will return attractive/fair/overvalued bands as a sensitivity table; it will not disguise unstated assumptions as a verified target."
            partial.append(SupportedClaim(claim=f"Stored relative valuation evidence for {ticker}"))
            unsupported.append("Intrinsic-value price bands without a verified valuation model")
    elif intent in {"OPTIONS_COSTS", "OPTIONS_EXPIRY", "TRADE_PLAN_METRICS"}:
        missing_by_intent = {
            "OPTIONS_COSTS": "option contracts, fills, bid/ask quotes at execution, commissions, current marks, implied volatility, and theta/Greeks",
            "OPTIONS_EXPIRY": "option symbol, strike, expiration, position direction, expected catalyst date, implied volatility, and expected-move horizon",
            "TRADE_PLAN_METRICS": "each trade's legs, quantities, fills/credits, expiration, underlying price, commissions, thesis, and exit rules",
        }
        label = {"OPTIONS_COSTS": "option-cost", "OPTIONS_EXPIRY": "expiration-fit", "TRADE_PLAN_METRICS": "trade-plan"}[intent]
        risk = _summary_for(tool_results, "portfolio_risk")
        position_count = len(risk.get("positions") or [])
        answer = f"The saved portfolio contains **{position_count} weighted positions**, but none has the contract-level fields needed for a verified {label} calculation.\n\n"
        if intent == "OPTIONS_COSTS":
            contracts_match = re.search(r"\b(?:long|short|contracts?)\s+(\d+)\b|\b(\d+)\s+contracts?\b", question, re.I)
            contracts = int(next((value for value in (contracts_match.groups() if contracts_match else ()) if value), "0"))
            def option_number(field: str) -> float | None:
                match = re.search(rf"\b{field}\s*[:=]?\s*(-?\d+(?:\.\d+)?)", question, re.I)
                return float(match.group(1)) if match else None
            fill, bid, ask, commission, theta = (option_number(field) for field in ("fill", "bid", "ask", "commission", "theta"))
            if contracts and fill is not None:
                premium = fill * 100 * contracts
                answer += "## Calculated from the supplied ticket\n\n"
                answer += f"- Premium notional: **${premium:,.2f}** ({fill:.2f} × 100 × {contracts})\n"
                if bid is not None and ask is not None:
                    answer += f"- Full quoted spread notional: **${max(0, ask - bid) * 100 * contracts:,.2f}**\n"
                if commission is not None:
                    answer += f"- Supplied commission: **${commission:,.2f}** (treated as the total because no per-contract label was supplied)\n"
                if theta is not None:
                    answer += f"- Current daily theta estimate: **${theta * 100 * contracts:,.2f} per day** at the supplied theta\n"
                answer += "\nThese values are arithmetic from your message and are not yet saved or market-verified.\n\n"
            answer += (
                "## What EagleEyes will calculate\n\n"
                "- Premium paid/received = option price × 100 × contracts\n"
                "- Entry spread estimate = bid/ask spread × 100 × contracts (with the fill location shown separately)\n"
                "- Commissions = per-contract fee × contracts, including both entry and planned exit\n"
                "- Daily time decay estimate = position theta × contracts × 100\n\n"
                "Paste one line such as: `AAPL 200C, long 2, expiry 2026-12-18, fill 8.40, bid 8.10, ask 8.60, commission 1.30, theta -0.07`."
            )
        elif intent == "OPTIONS_EXPIRY":
            dates = [date for date in re.findall(r"\b\d{4}-\d{2}-\d{2}\b", question)]
            if len(dates) >= 2:
                from datetime import date as calendar_date
                expiry = calendar_date.fromisoformat(dates[0])
                catalyst = calendar_date.fromisoformat(dates[1])
                answer += f"## Calculated from the supplied dates\n\n- Expiration-to-catalyst buffer: **{(expiry - catalyst).days} days** ({expiry} minus {catalyst})\n\nA negative buffer means the option expires before the catalyst. This timing result is arithmetic and is not yet saved.\n\n"
            answer += (
                "## Useful timing checks\n\n"
                "- Catalyst buffer = expiration date − expected catalyst date\n"
                "- One-standard-deviation move ≈ stock price × implied volatility × √(days/365)\n"
                "- Compare expected catalyst timing with theta acceleration and the option's breakeven—not DTE alone.\n\n"
                "Paste: `ticker, strike/type, long or short, expiration, catalyst date, stock price, implied volatility, expected move horizon`. EagleEyes will calculate the buffer and flag whether the thesis window extends beyond expiration."
            )
        else:
            contracts_match = re.search(r"\b(?:quantity|qty|long|short)\s*[:=]?\s*(\d+)\b", question, re.I)
            strike_match = re.search(r"\bstrike\s*[:=]?\s*(\d+(?:\.\d+)?)|\b(\d+(?:\.\d+)?)[CP]\b", question, re.I)
            fill_match = re.search(r"\bfill\s*[:=]?\s*(\d+(?:\.\d+)?)", question, re.I)
            contracts = int(contracts_match.group(1)) if contracts_match else 0
            strike = float(next((value for value in (strike_match.groups() if strike_match else ()) if value), "0"))
            fill = float(fill_match.group(1)) if fill_match else None
            is_call = bool(re.search(r"\bcall\b|\d+(?:\.\d+)?C\b", question, re.I))
            is_put = bool(re.search(r"\bput\b|\d+(?:\.\d+)?P\b", question, re.I))
            is_long = bool(re.search(r"\blong\b", question, re.I))
            if is_long and contracts and strike and fill is not None and (is_call or is_put):
                breakeven = strike + fill if is_call else strike - fill
                answer += "## Calculated from the supplied long-option leg\n\n"
                answer += f"- Maximum premium loss: **${fill * 100 * contracts:,.2f}** before commissions\n"
                answer += f"- Expiration breakeven: **${breakeven:,.2f}**\n\nExpected return still requires outcome probabilities, and an exit plan still requires your profit target, breaker, and time stop.\n\n"
            answer += (
                "## Metrics that can be calculated from a trade ticket\n\n"
                "- Long option maximum loss = premium + commissions\n"
                "- Long call breakeven = strike + premium per share; long put breakeven = strike − premium per share\n"
                "- Vertical-spread maximum loss and gain come from strike width and net debit/credit\n"
                "- Expected return requires explicit outcome probabilities; EagleEyes will show the probability assumptions\n"
                "- Exit plan should specify profit target, thesis breaker, time stop, and latest exit date\n\n"
                "Paste each leg as `ticker, call/put, long/short, strike, expiry, quantity, fill`, plus the underlying price, probabilities, and exit rules."
            )
        answer += f"\n\n**Still missing:** {missing_by_intent[intent]}. No numeric trade value was inferred from stock-only holdings."
        unsupported.append(f"{label} analytics without an options/trade ledger")
        user_gaps.append(missing_by_intent[intent])
        partial.append(SupportedClaim(claim=f"Specific missing {label} inputs identified"))
    elif intent == "OPPORTUNITY_RANKING" and not summary.get("candidates"):
        rows = sorted(summary.get("ineligible_candidates") or [],
                      key=lambda row: _near_score(row, ("fundamental_quality", "valuation", "momentum", "portfolio_fit")), reverse=True)[:3]
        body = []
        for row in rows:
            gates = _failed_gates(row)
            body.append(_holding_line({"ticker": row.get("ticker"), "fundamental_score": row.get("fundamental_quality"),
                                      "valuation_score": row.get("valuation"), "momentum_score": row.get("momentum")})
                        + f". Failed gates: {', '.join(gates) or 'full opportunity score unavailable'}."
                        + (f" Supported signals: {'; '.join(row.get('supporting_evidence') or [])}." if row.get("supporting_evidence") else ""))
        answer = "No holding passes every opportunity gate, so none is labeled fully eligible. The strongest partial setups are:\n\n" + "\n\n".join(body or ["No holding has enough observed factor evidence for a near-match comparison."])
        partial.append(SupportedClaim(claim="Strongest partial setups shown with their failed eligibility gates."))
        unsupported.append("A fully eligible opportunity ranking")
    elif intent == "THESIS_REPLACEMENT" and not (summary.get("thesis") or {}).get("exists"):
        weak = sorted(summary.get("weakest_evidence_holdings") or summary.get("weakest_holdings") or [],
                      key=lambda row: _num(row.get("health_score")) if _num(row.get("health_score")) is not None else 999)[:5]
        candidates = summary.get("dominance_results") or []
        candidate_text = "\n".join(
            f"- **{row.get('candidate')}** — {str(row.get('dominance_status') or 'not proven').replace('_', ' ').lower()}; decision score {_num(row.get('decision_score')):.1f}."
            for row in candidates[:3] if _num(row.get("decision_score")) is not None
        )
        answer = "I cannot rank your personal theses because none are saved. Based only on objective stored evidence, the weakest current setups are:\n\n" + "\n".join(f"- {_holding_line(row)}" for row in weak)
        if candidate_text:
            answer += "\n\nWatchlist evidence (not a forced replacement):\n" + candidate_text
        answer += "\n\n**Next question:** which of these holdings do you own for a specific company thesis rather than allocation or income exposure? Reply with one ticker and the reason you own it; EagleEyes can draft a reviewable thesis and breakers before comparing replacements."
        supported.append(SupportedClaim(claim="Objective weakest-evidence holdings", scope="objective"))
        unsupported.append("Personal weakest-thesis ranking and personalized replacement")
    elif intent == "PORTFOLIO_CHANGE" and not (summary.get("historical_snapshot") or {}).get("exists"):
        current = sorted(summary.get("all_holdings") or [], key=lambda row: _num(row.get("weight")) or 0, reverse=True)[:5]
        answer = "There is no compatible prior snapshot, so I cannot truthfully say what changed since the last review. The current baseline is:\n\n" + "\n".join(f"- {_holding_line(row)}" for row in current)
        answer += "\n\nThis snapshot is the durable comparison point for future reviews; it is not presented as a past review."
        supported.append(SupportedClaim(claim="Current portfolio baseline"))
        unsupported.append("Change since last review")
    elif intent == "VALUATION_RANKING" and not summary.get("positions"):
        rows = [row for row in summary.get("all_relative_valuation") or [] if any(value is not None for value in (row.get("inputs") or {}).values())][:8]
        body = []
        for row in rows:
            inputs = row.get("inputs") or {}
            observed = ", ".join(f"{key.replace('_', ' ')} {value:.2f}" for key, raw in inputs.items() if (value := _num(raw)) is not None)
            body.append(f"- **{row.get('ticker')}** — {observed or 'no raw valuation input'}; missing gates: {', '.join(_failed_gates(row)) or 'relative comparison inputs'}."
                        )
        answer = "No position qualifies for the full relative-valuation ranking. These are the strongest partial comparisons, without labeling them overvalued:\n\n" + "\n".join(body or ["- No position has any usable raw valuation input."])
        partial.append(SupportedClaim(claim="Partial valuation evidence with failed gates"))
        unsupported.append("Full relative overvaluation ranking")
    elif intent == "MULTI_SCENARIO" and not summary.get("latest_simulation"):
        rows = sorted(summary.get("all_holdings") or [],
                      key=lambda row: _num(row.get("weight")) or 0, reverse=True)[:8]
        factors = summary.get("scenario_factors") or []
        factor_text = ", ".join(
            f"{str(row.get('factor') or 'factor').replace('_', ' ')} {row.get('direction') or ''}".strip()
            for row in factors
        ) or "the requested factors"
        mapped = summary.get("supported_scenario_factors") or []
        mapped_text = "\n".join(
            f"- **{str(row.get('factor') or 'factor').replace('_', ' ').title()}** — "
            f"{_num(row.get('mapped_portfolio_weight')):.1%} mapped weight across "
            f"{', '.join(row.get('affected_holdings') or []) or 'covered holdings'}; "
            f"{str(row.get('support_type') or 'exposure mapping').replace('_', ' ').lower()}."
            for row in mapped if _num(row.get("mapped_portfolio_weight")) is not None
        )
        answer = (
            f"A compatible simulation for **{factor_text}** is not cached yet, so I cannot state a loss, drawdown, "
            "or terminal-wealth estimate. The canonical simulation job has been queued.\n\n"
            "**Current exposure starting point**\n\n" +
            "\n".join(f"- {_holding_line(row)}" for row in rows)
        )
        if mapped_text:
            answer += "\n\n**Available deterministic factor mapping**\n\n" + mapped_text
        answer += "\n\nThese weights and mappings show where a shock could enter the portfolio; they are not a modeled loss estimate."
        supported.append(SupportedClaim(claim="Current portfolio exposure and supported factor mapping"))
        pending.append("compatible multi-factor simulation")
        unsupported.append("Scenario loss, drawdown, and wealth estimates before simulation completion")
    elif intent == "DATA_QUALITY":
        rows = summary.get("positions") or []
        checks = sorted({key for row in rows for key in (row.get("eligibility") or {}).get("required_checks", {})})
        counts = {
            check: sum(bool((row.get("eligibility") or {}).get("required_checks", {}).get(check)) for row in rows)
            for check in checks
        }
        coverage_lines = []
        for check in checks:
            coverage_lines.append(f"- **{check.replace('_', ' ').title()}**: {counts[check]}/{len(rows)} holdings")
        rankable = sum(bool(row.get("rankable")) for row in rows)
        momentum_count = counts.get("momentum_history", counts.get("momentum", 0))
        domain_lines = [
            f"- **Prices and price history**: {min(counts.get('price_freshness', 0), momentum_count)}/{len(rows)} holdings",
            f"- **Fundamentals and history**: {min(counts.get('fundamental_freshness', 0), counts.get('fundamental_history', 0))}/{len(rows)} holdings",
            f"- **Momentum inputs**: {momentum_count}/{len(rows)} holdings",
            f"- **Ranking eligibility**: {rankable}/{len(rows)} holdings",
            "- **Full opportunity eligibility**: not independently counted by this data-quality read model.",
            "- **Classifications and valuation inputs**: not independently counted by this read model; they remain separate data-health domains and are not inferred from symbol presence.",
        ]
        holding_lines = []
        for row in rows:
            missing = _failed_gates(row)
            if missing or row.get("trust_classification") != "HIGH":
                holding_lines.append(f"- **{row.get('ticker')}** — {row.get('trust_classification')}; missing: {', '.join(missing) or 'no required field, but confidence remains below high'}."
                                     )
        answer = "Ranking reliability is field-specific; it is not a single all-or-nothing coverage number.\n\n**Decision-domain coverage**\n\n" + "\n".join(domain_lines)
        answer += "\n\n**Methodology checks**\n\n" + "\n".join(coverage_lines or ["- Field coverage is not present in the current read model."])
        answer += "\n\n**Holdings needing attention**\n\n" + "\n".join(holding_lines[:20] or ["- No lower-confidence holding is recorded."])
        supported.append(SupportedClaim(claim="Field-level and per-holding data quality"))
    elif intent == "SCORE_ATTRIBUTION" and not summary.get("holding"):
        overview = _summary_for(tool_results, "portfolio_overview")
        holdings = list(overview.get("candidates") or overview.get("all_holdings") or overview.get("positions") or [])
        if not holdings and context:
            holdings = list(context.positions)
        answer = (
            "Name a holding (for example, `MSFT`) or open that holding's research page before asking why its score changed. "
            "Score attribution requires one company plus a compatible prior score snapshot."
        )
        if holdings:
            answer += "\n\n**Available holdings to inspect:** " + ", ".join(f"`{row.get('ticker')}`" for row in holdings[:12]) + "."
        answer += "\n\nReply with one ticker. EagleEyes will show the prior and current score, component deltas, evidence dates, and whether the change came from fundamentals, valuation, momentum, portfolio fit, or a methodology/version change."
        user_gaps.append("A holding ticker")
        unsupported.append("Score attribution without a named holding")
    elif intent == "THESIS_INVALIDATION" and not (summary.get("thesis") or {}).get("exists"):
        rows = summary.get("largest_positions") or []
        body = []
        for row in rows:
            risks = []
            if (_num(row.get("risk_contribution")) or 0) >= .05:
                risks.append(f"modeled risk contribution {_num(row.get('risk_contribution')):.1%}")
            if (_num(row.get("valuation_score")) or 100) < 45:
                risks.append(f"weak valuation evidence {_num(row.get('valuation_score')):.0f}/100")
            if (_num(row.get("momentum_score")) or 100) < 45:
                risks.append(f"weak momentum evidence {_num(row.get('momentum_score')):.0f}/100")
            body.append(f"- **{row.get('ticker')}** — {', '.join(risks) or 'no objective breaker-like risk crossed the stored thresholds'}."
                        )
        answer = "No saved personal breakers exist yet. These are the objective risks most suitable for turning into explicit invalidation tests:\n\n" + "\n".join(body)
        answer += (
            "\n\n**Make this actionable:** reply with one holding and the core reason you own it. EagleEyes will draft three reviewable breakers: "
            "one operating/fundamental threshold, one valuation or capital-allocation threshold, and one portfolio-risk threshold. "
            "You can edit or reject them before anything is saved."
        )
        supported.append(SupportedClaim(claim="Objective risks for largest positions", scope="objective"))
        unsupported.append("Personal thesis invalidation conditions")
    elif intent == "PORTFOLIO_ANALYSIS" and not summary.get("optimizer_run"):
        rows = sorted(summary.get("all_holdings") or [], key=lambda row: _num(row.get("weight")) or 0, reverse=True)[:8]
        answer = "A compatible optimizer job has been queued. While it runs, the current objective concentration starting point is:\n\n" + "\n".join(f"- {_holding_line(row)}" for row in rows)
        answer += "\n\nI cannot make tax-aware trade claims without tax lots, and exact turnover/cost claims remain pending with the optimizer."
        supported.append(SupportedClaim(claim="Current position concentration"))
        pending.append("compatible optimization")
        unsupported.append("Tax-aware trades without tax lots")
    elif intent == "MULTIFACTOR_SCREEN" and not summary.get("positions"):
        rows = sorted(summary.get("near_matches") or summary.get("all_holdings") or [],
                      key=lambda row: _near_score(row, ("fundamental_score", "valuation_score", "momentum_score")), reverse=True)[:10]
        body = []
        for row in rows:
            failed = list(row.get("failed_criteria") or [])
            if not failed:
                trend = ((row.get("fundamental_trend") or {}).get("direction") or "UNAVAILABLE")
                if trend != "IMPROVING": failed.append(f"fundamental trend is {trend.lower()}")
                if (_num(row.get("valuation_score")) or 0) <= 0: failed.append("valuation unavailable")
                if (_num(row.get("momentum_score")) or 0) < 50: failed.append("momentum is not positive")
            body.append(f"- {_holding_line(row)}. Failed criteria: {', '.join(failed) or 'full historical eligibility'}.")
        answer = "No company passes all multifactor gates. The strongest near-matches are:\n\n" + "\n".join(body or ["- No company has enough factor evidence for a near-match."])
        partial.append(SupportedClaim(claim="Multifactor near matches with failed criteria"))
        unsupported.append("Full multifactor eligibility")
    elif intent == "RECOMMENDATION_COUNTERCASE" and not (summary.get("countercase") or {}).get("ticker"):
        candidates = summary.get("top_candidate") or []
        answer = "There is no current verified EagleEyes recommendation, so there is no recommendation-specific countercase to audit."
        if candidates:
            answer += "\n\nThe strongest current holding by stored health evidence is not a recommendation: " + _holding_line(candidates[0]) + "."
        unsupported.append("Countercase to a nonexistent recommendation")
    elif intent == "CASH_ALLOCATION":
        cash = summary.get("cash_allocation") or {}
        hurdle = cash.get("cash_hurdle") or {}
        if not hurdle.get("available"):
            candidates = cash.get("candidates") or summary.get("dominance_results") or []
            body = "\n".join(f"- **{row.get('candidate')}** — {str(row.get('dominance_status') or 'not proven').replace('_', ' ').lower()}; decision score {_num(row.get('decision_score')):.1f}."
                                for row in candidates[:5] if _num(row.get("decision_score")) is not None)
            answer = "The sourced cash hurdle is missing, so I cannot claim that investing beats cash. Current candidate evidence is:\n\n" + (body or "- No candidate has sufficient verified comparison evidence.")
            partial.append(SupportedClaim(claim="Candidate evidence without a cash-superiority claim"))
            unsupported.append("Investing is better than cash")
    elif deterministic_answer:
        supported.append(SupportedClaim(claim="Deterministic capability answer"))

    coverage = next((row.get("coverage") for row in tool_results if isinstance(row.get("coverage"), dict)), {})
    return resolution, SupportedAnswer(
        direct_answer=answer, supported_claims=supported, partial_claims=partial,
        unsupported_claims=list(dict.fromkeys(unsupported)), pending_claims=list(dict.fromkeys(pending)),
        evidence=resolution.evidence_available, jobs_started=jobs, data_gaps=gaps,
        user_input_needed=user_gaps, confidence="HIGH" if supported and not partial else "MEDIUM" if supported or partial else "LOW",
        coverage=coverage or {},
    )

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any

from .portfolio_eligibility import equity_analysis_holdings


FULL_COVERAGE_PERCENT = 90.0
PARTIAL_COVERAGE_PERCENT = 60.0


class CandidateType(StrEnum):
    CURRENT_HOLDING = "CURRENT_HOLDING"
    ADD_TO_EXISTING = "ADD_TO_EXISTING"
    NEW_POSITION = "NEW_POSITION"
    REPLACEMENT = "REPLACEMENT"
    REDUCE = "REDUCE"
    EXIT = "EXIT"


@dataclass(frozen=True)
class PortfolioContext:
    portfolio_id: str
    name: str
    positions: tuple[dict[str, Any], ...]
    excluded_positions: tuple[dict[str, Any], ...]
    excluded_symbols: tuple[str, ...]
    total_positions: int
    source_positions: int
    normalized_weights: dict[str, float]
    as_of: str | None
    version: str

    @property
    def symbols(self) -> tuple[str, ...]:
        return tuple(str(row.get("ticker") or "").upper() for row in self.positions)

    def portfolio_payload(self) -> dict[str, Any]:
        return {
            "id": self.portfolio_id,
            "name": self.name,
            "updated_at": self.as_of,
            "holdings": [dict(row) for row in self.positions],
            "context_version": self.version,
        }


@dataclass(frozen=True)
class ScenarioFactor:
    factor: str
    direction: str
    magnitude: float | None = None


@dataclass
class AskVerification:
    status: str
    coverage: dict[str, Any]
    scenario_valid: bool = True
    constraints_valid: bool = True
    optimizer_feasible: bool | None = None
    answer_allowed: bool = True
    recommendation_allowed: bool = True
    warnings: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

    def payload(self) -> dict[str, Any]:
        return asdict(self)


def build_portfolio_context(portfolio: dict[str, Any]) -> PortfolioContext:
    source = [dict(row) for row in portfolio.get("holdings") or []]
    eligible, excluded = equity_analysis_holdings(source)
    values = {
        str(row.get("ticker") or "").upper(): max(0.0, _number(row.get("market_value")))
        for row in eligible
    }
    total_value = sum(values.values())
    raw_weights = {
        str(row.get("ticker") or "").upper(): max(0.0, _number(row.get("weight")))
        for row in eligible
    }
    denominator = total_value if total_value > 0 else sum(raw_weights.values())
    normalized: dict[str, float] = {}
    positions: list[dict[str, Any]] = []
    for row in eligible:
        ticker = str(row.get("ticker") or "").upper()
        numerator = values[ticker] if total_value > 0 else raw_weights[ticker]
        weight = numerator / denominator if denominator > 0 else 0.0
        normalized[ticker] = weight
        positions.append({**row, "ticker": ticker, "weight": weight})
    fingerprint_payload = {
        "portfolio_id": str(portfolio.get("id")),
        "positions": [
            {"ticker": row["ticker"], "weight": round(_number(row.get("weight")), 10),
             "market_value": row.get("market_value")}
            for row in sorted(positions, key=lambda item: item["ticker"])
        ],
        "excluded": sorted(str(row.get("ticker") or "").upper() for row in excluded),
    }
    version = hashlib.sha256(
        json.dumps(fingerprint_payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()[:20]
    return PortfolioContext(
        portfolio_id=str(portfolio.get("id")),
        name=str(portfolio.get("name") or "Portfolio"),
        positions=tuple(positions),
        excluded_positions=tuple(excluded),
        excluded_symbols=tuple(sorted(str(row.get("ticker") or "").upper() for row in excluded)),
        total_positions=len(positions),
        source_positions=len(source),
        normalized_weights=normalized,
        as_of=portfolio.get("updated_at"),
        version=version,
    )


_SCENARIO_ALIASES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("interest_rates", "increase", ("rates rise", "interest rates rose", "higher rates", "higher yields", "yields increase", "fed stays higher", "higher-for-longer", "rate hike", "tightening")),
    ("interest_rates", "decrease", ("rates fall", "interest rates fall", "lower rates", "lower yields", "rate cut", "easing")),
    ("ai_capex", "decrease", ("ai spending slows", "ai spending slowed", "ai capex declines", "ai capex declined", "ai capex falls", "hyperscaler capex cuts", "ai investment weakens", "slowing ai spending")),
    ("ai_capex", "increase", ("ai spending accelerates", "ai capex rises", "ai investment strengthens")),
    ("economic_growth", "decrease", ("recession", "economy entered a recession", "economic slowdown", "growth slows", "weaker consumer demand")),
    ("economic_growth", "increase", ("expansion", "growth accelerates", "stronger consumer demand")),
    ("inflation", "increase", ("inflation rises", "accelerating inflation", "higher inflation")),
    ("inflation", "decrease", ("inflation falls", "cooling inflation", "lower inflation")),
    ("unemployment", "increase", ("unemployment increases", "unemployment rises", "joblessness rises")),
    ("unemployment", "decrease", ("unemployment falls", "joblessness falls")),
    ("oil", "increase", ("oil rises", "oil prices rise", "oil shock")),
    ("oil", "decrease", ("oil falls", "oil prices fall")),
    ("us_dollar", "increase", ("dollar strengthens", "stronger dollar", "usd strengthens")),
    ("us_dollar", "decrease", ("dollar weakens", "weaker dollar", "usd weakens")),
    ("technology_sector", "decrease", ("technology stocks fell", "technology stocks fall", "tech stocks fell", "tech stocks fall", "technology sector fell", "technology sector falls")),
)


def parse_scenario_factors(question: str) -> list[ScenarioFactor]:
    lowered = " ".join(question.lower().replace("’", "'").split())
    factors: list[ScenarioFactor] = []
    seen: set[tuple[str, str]] = set()
    for factor, direction, aliases in _SCENARIO_ALIASES:
        if any(alias in lowered for alias in aliases) and (factor, direction) not in seen:
            magnitude = None
            if factor == "technology_sector":
                match = re.search(r"(?:technology|tech)(?:\s+sector|\s+stocks?)?\s+(?:fell|falls?|declined?|drops?)\s+(\d+(?:\.\d+)?)%", lowered)
                magnitude = float(match.group(1)) / 100 if match else None
            factors.append(ScenarioFactor(factor, direction, magnitude))
            seen.add((factor, direction))
    return factors


def scenario_payload(question: str) -> dict[str, Any]:
    factors = parse_scenario_factors(question)
    economic = "recession" if any(row.factor == "economic_growth" and row.direction == "decrease" for row in factors) else "expansion" if any(row.factor == "economic_growth" and row.direction == "increase" for row in factors) else "unconditioned"
    inflation = "accelerating" if any(row.factor == "inflation" and row.direction == "increase" for row in factors) else "cooling" if any(row.factor == "inflation" and row.direction == "decrease" for row in factors) else "unconditioned"
    rates = "tightening" if any(row.factor == "interest_rates" and row.direction == "increase" for row in factors) else "easing" if any(row.factor == "interest_rates" and row.direction == "decrease" for row in factors) else "unconditioned"
    # Preserve the legacy SimulationRunInput shock vocabulary while exposing
    # all richer factors separately in scenario_factors.
    shocks = [row.factor for row in factors if row.factor in {"oil", "credit", "geopolitical"}]
    return {"economic_state": economic, "inflation_state": inflation, "rate_state": rates,
            "shocks": shocks, "scenario_factors": [asdict(row) for row in factors]}


def attach_coverage(result: dict[str, Any], context: PortfolioContext | None,
                    evaluated_symbols: list[str] | tuple[str, ...] | set[str] | None = None) -> dict[str, Any]:
    if context is None:
        return result
    evaluated = {str(value).upper() for value in (evaluated_symbols or context.symbols)} & set(context.symbols)
    requested = context.total_positions
    count = len(evaluated)
    result["coverage"] = {
        "requested": requested, "evaluated": count, "missing": requested - count,
        "missing_symbols": sorted(set(context.symbols) - evaluated),
        "percent": round((count / requested * 100.0) if requested else 100.0, 1),
    }
    result["portfolio_context_version"] = context.version
    return result


def classify_candidate(ticker: str, action: str, context: PortfolioContext) -> CandidateType:
    owned = ticker.upper() in set(context.symbols)
    normalized = action.upper()
    if normalized in {"REDUCE", "TRIM"}:
        return CandidateType.REDUCE
    if normalized in {"EXIT", "SELL"}:
        return CandidateType.EXIT
    if owned and normalized in {"ADD", "BUY", "NEW_POSITION", "REPLACEMENT"}:
        return CandidateType.ADD_TO_EXISTING
    if owned:
        return CandidateType.CURRENT_HOLDING
    return CandidateType.REPLACEMENT if normalized == "REPLACEMENT" else CandidateType.NEW_POSITION


def verify_results(intent: str, context: PortfolioContext | None, scenario_factors: list[ScenarioFactor],
                   tool_results: list[dict[str, Any]]) -> AskVerification:
    warnings: list[str] = []
    failures: list[str] = []
    coverages = [
        row.get("coverage") for row in tool_results
        if isinstance(row.get("coverage"), dict) and int((row.get("coverage") or {}).get("requested") or 0) > 0
    ]
    coverage_requested = max((int(row.get("requested") or 0) for row in coverages), default=0)
    evaluated = min(
        (int(row.get("evaluated") or 0) for row in coverages if int(row.get("requested") or 0) == coverage_requested),
        default=0,
    )
    percent = round((evaluated / coverage_requested * 100.0) if coverage_requested else 100.0, 1)
    if coverage_requested and percent < FULL_COVERAGE_PERCENT:
        warnings.append(f"Analytical coverage is {evaluated}/{coverage_requested} ({percent:.1f}%).")
    low_coverage = bool(coverage_requested and percent < PARTIAL_COVERAGE_PERCENT)

    if context:
        mismatched = [
            str(row.get("portfolio_context_version")) for row in tool_results
            if row.get("portfolio_context_version") not in {None, context.version}
        ]
        if mismatched:
            failures.append("A tool returned results for a different portfolio context version.")

    stale_before = datetime.now(timezone.utc) - timedelta(days=7)
    stale_tools: list[str] = []
    for row in tool_results:
        raw_as_of = row.get("as_of")
        if not raw_as_of:
            continue
        try:
            parsed = datetime.fromisoformat(str(raw_as_of).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            if parsed < stale_before:
                stale_tools.append(str(row.get("tool_name") or "unknown"))
        except ValueError:
            warnings.append(f"{row.get('tool_name') or 'A tool'} returned an invalid evidence timestamp.")
    if stale_tools:
        warnings.append("Stored evidence is older than seven days for: " + ", ".join(sorted(set(stale_tools))))

    excluded = set(context.excluded_symbols if context else ())
    leaked = sorted(excluded & _collect_tickers(tool_results))
    if leaked:
        failures.append("Excluded positions reappeared in tool output: " + ", ".join(leaked))

    owned = set(context.symbols if context else ())
    invalid_candidates = sorted({
        ticker for ticker, candidate_type in _collect_candidates(tool_results)
        if ticker in owned and candidate_type in {CandidateType.NEW_POSITION, CandidateType.REPLACEMENT}
    })
    if invalid_candidates:
        failures.append("Owned positions were mislabeled as new or replacement candidates: " + ", ".join(invalid_candidates))

    scenario_valid = True
    if intent in {"SCENARIO", "MULTI_SCENARIO"}:
        scenario_valid = bool(scenario_factors)
        if not scenario_valid:
            failures.append("No supported scenario factor was parsed.")
        supported = {
            (str(item.get("factor")), str(item.get("direction")))
            for row in tool_results
            for item in ((row.get("summary") or {}).get("supported_scenario_factors") or [])
        }
        requested_factors = {(row.factor, row.direction) for row in scenario_factors}
        missing_factors = sorted(requested_factors - supported)
        if missing_factors:
            scenario_valid = False
            failures.append("No cached scenario mapping exists for: " + ", ".join(
                f"{factor} {direction}" for factor, direction in missing_factors
            ))

    optimizer_feasible: bool | None = None
    optimizer_rows = [
        row for row in tool_results
        if row.get("tool_name") in {
            "latest_portfolio_analysis",
            "portfolio_rebalance_review",
            "portfolio_decision_lab",
            "portfolio_scenario",
        }
    ]
    for row in optimizer_rows:
        summary = row.get("summary") or {}
        simulation = summary.get("simulation") or summary.get("latest_simulation") or {}
        optimizer = summary.get("optimizer") or row.get("optimizer") or (
            simulation.get("optimizer") if isinstance(simulation, dict) else None
        ) or {}
        if not optimizer:
            continue
        diagnostics = summary.get("model_diagnostics") or row.get("model_diagnostics") or {}
        diagnostic_status = diagnostics.get("constraint_status") if isinstance(diagnostics, dict) else ""
        status = str(optimizer.get("status") or optimizer.get("constraint_status") or diagnostic_status or "").upper()
        optimizer_text = json.dumps(optimizer, default=str).lower()
        if status in {"INFEASIBLE", "FAILED"} or "infeasible" in optimizer_text or "constraints incompatible" in optimizer_text:
            optimizer_feasible = False
            failures.append("The optimizer did not produce a feasible solution; attempted weights are not recommendations.")
        elif status in {"FEASIBLE", "SATISFIED"}:
            optimizer_feasible = True

    unavailable = [row for row in tool_results if str(row.get("status") or "").lower() in {"unavailable", "failed"}]
    if unavailable:
        warnings.append("One or more required saved-data prerequisites are unavailable.")
    if intent == "THESIS_REPLACEMENT" and unavailable:
        failures.append("No saved thesis exists, so a weakest-thesis replacement cannot be validated.")
    if intent == "PORTFOLIO_CHANGE":
        snapshots = [(row.get("summary") or {}).get("historical_snapshot") or {} for row in tool_results]
        if snapshots and not any(row.get("exists") for row in snapshots):
            warnings.append("No previous historical snapshot exists; a since-last-review comparison is unavailable.")

    bounded_screen_intents = {"OPPORTUNITY_RANKING", "VALUATION_RANKING", "MULTIFACTOR_SCREEN"}
    coverage_blocks_answer = low_coverage and not unavailable and intent not in bounded_screen_intents
    if coverage_blocks_answer:
        failures.append("Coverage is too low for a whole-portfolio conclusion.")

    recommendation_intents = {"PORTFOLIO_ANALYSIS", "THESIS_REPLACEMENT", "WATCHLIST_COMPARISON", "CASH_ALLOCATION"}
    recommendation_allowed = intent not in recommendation_intents or not failures
    answer_allowed = not coverage_blocks_answer
    status = "FAILED" if not answer_allowed else "PARTIAL" if warnings or failures else "SUCCESS"
    return AskVerification(status, {"requested": coverage_requested, "evaluated": evaluated,
        "missing": max(0, coverage_requested - evaluated), "percent": percent}, scenario_valid,
        optimizer_feasible is not False, optimizer_feasible, answer_allowed,
        recommendation_allowed, warnings, failures)


def verified_analysis_result(intent: str, context: PortfolioContext | None,
                             scenario_factors: list[ScenarioFactor], tool_results: list[dict[str, Any]],
                             verification: AskVerification) -> dict[str, Any]:
    return {
        "schema_version": "ask-analysis-v1",
        "intent": intent,
        "portfolio": None if context is None else {
            "id": context.portfolio_id, "name": context.name,
            "position_count": context.total_positions,
            "excluded_symbols": list(context.excluded_symbols),
            "context_version": context.version, "as_of": context.as_of,
        },
        "scenario_factors": [asdict(row) for row in scenario_factors],
        "tool_results": sanitize_tool_results(tool_results, verification),
        "verification": verification.payload(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def sanitize_tool_results(tool_results: list[dict[str, Any]], verification: AskVerification) -> list[dict[str, Any]]:
    """Remove invalid attempted solutions before either renderer can narrate them."""
    rows = json.loads(json.dumps(tool_results, default=str))
    if verification.optimizer_feasible is not False:
        return rows
    blocked_keys = {
        "alternatives", "allocations", "trades", "implementation_paths", "selected_alternative",
        "outcomes", "strategies", "target_weights", "solution", "candidates",
    }

    def scrub(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: scrub(item) for key, item in value.items() if key not in blocked_keys}
        if isinstance(value, list):
            return [scrub(item) for item in value]
        return value

    return scrub(rows)


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _collect_tickers(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"ticker", "symbol"} and isinstance(item, str):
                found.add(item.upper())
            else:
                found.update(_collect_tickers(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_collect_tickers(item))
    return found


_SYMBOL_KEYS = {"ticker", "symbol", "candidate", "incumbent", "entity"}
_SYMBOL_LIST_KEYS = {"holdings", "affected_holdings", "affected_entities", "tickers", "symbols", "compared_incumbents"}


def suppress_excluded_symbols(value: Any, excluded_symbols: set[str] | frozenset[str]) -> Any:
    """Remove complete claims that refer to request-excluded portfolio symbols.

    Request-scoped exclusions are a hard boundary.  A cached read model may be
    useful after a portfolio change, but no row, cluster, dependency, event, or
    free-form claim that still names an excluded asset may reach a renderer.
    """
    excluded = {str(symbol).upper() for symbol in excluded_symbols if symbol}
    if not excluded:
        return value

    def contains_excluded_text(item: Any) -> bool:
        if not isinstance(item, str):
            return False
        tokens = set(re.findall(r"\b[A-Z][A-Z0-9.\-]{0,9}\b", item.upper()))
        # CASH is both an excluded pseudo-position and ordinary financial
        # vocabulary.  Structural symbol fields enforce its exclusion; prose
        # such as "cash hurdle" must remain valid contract metadata.
        return bool(tokens & (excluded - {"CASH"}))

    def scrub(item: Any, parent_key: str | None = None) -> Any:
        if isinstance(item, dict):
            identity = {
                str(item.get(key) or "").upper()
                for key in _SYMBOL_KEYS if item.get(key) is not None
            }
            if identity & excluded:
                return None
            cleaned: dict[str, Any] = {}
            for key, child in item.items():
                if key in _SYMBOL_LIST_KEYS and isinstance(child, list):
                    kept = [entry for entry in child if str(entry).upper() not in excluded]
                    cleaned[key] = [result for entry in kept if (result := scrub(entry, key)) is not None]
                    continue
                result = scrub(child, key)
                if result is not None:
                    cleaned[key] = result
            return cleaned
        if isinstance(item, list):
            return [result for child in item if (result := scrub(child, parent_key)) is not None]
        if isinstance(item, str) and contains_excluded_text(item):
            # Suppress the entire textual claim.  Editing financial prose in
            # place could change its meaning and is therefore not permitted.
            return None
        return item

    return scrub(value)


def enforce_output_symbol_boundary(tool_results: list[dict[str, Any]], context: PortfolioContext | None) -> list[dict[str, Any]]:
    if not context or not context.excluded_symbols:
        return tool_results
    excluded = set(context.excluded_symbols)
    cleaned = suppress_excluded_symbols(tool_results, excluded)
    rows = cleaned if isinstance(cleaned, list) else []
    leaked = _collect_tickers(rows) & excluded
    if leaked:
        # Fail closed if a newly introduced schema shape bypasses the scrubber.
        return [{
            "tool_name": "output_symbol_validation",
            "status": "unavailable",
            "title": "Portfolio result invalidated",
            "summary": {
                "message": "A cached result violated the request-scoped portfolio boundary and was suppressed. A compatible rebuild is required.",
                "invalidated": True,
            },
        }]
    return rows


def _collect_candidates(value: Any) -> list[tuple[str, CandidateType]]:
    found: list[tuple[str, CandidateType]] = []
    if isinstance(value, dict):
        ticker = str(value.get("ticker") or value.get("symbol") or "").upper()
        raw_type = value.get("candidate_type")
        if ticker and raw_type:
            try:
                found.append((ticker, CandidateType(str(raw_type))))
            except ValueError:
                pass
        for item in value.values():
            found.extend(_collect_candidates(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_collect_candidates(item))
    return found


def _flatten(value: Any) -> list[Any]:
    if isinstance(value, dict):
        return [item for child in value.values() for item in _flatten(child)]
    if isinstance(value, list):
        return [item for child in value for item in _flatten(child)]
    return [value]

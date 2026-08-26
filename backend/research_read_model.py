from __future__ import annotations

"""Registry-driven shared Research/Ask capability read model."""

import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

from . import database
from .research_metric_registry import REGISTRY, ResearchMetric
from .research_metrics import VERSION as METRIC_VERSION
from .research_metrics import financial_metrics, growth, historical_valuation, peer_medians, portfolio_metrics, technical_metrics, valuation_metrics
from .research_provider_capability_registry import CAPABILITY_BY_KEY


VERSION = "research-read-model-v2.0.0"
MODEL_VERSION = "research-decision-rules-v1.0.0"
METHOD_VERSION_AS_OF = "2026-08-26"
MIN_VALID_PEERS = 3


def _business_type(security: Mapping[str, Any]) -> str:
    """Bound the formulas to business models they actually support."""
    sector = str(security.get("sector") or "").lower()
    industry = str(security.get("industry") or "").lower()
    if sector in {"financials", "financial services"} or any(
        token in industry for token in ("bank", "credit services", "financial services", "capital markets")
    ):
        return "BANK"
    return "OPERATING_COMPANY"


def _source_ref(row: Mapping[str, Any] | None, *, metric: str | None = None) -> dict[str, Any] | None:
    if not row:
        return None
    identifier = row.get("id") or row.get("external_id") or row.get("accession_number") or row.get("context_id")
    if identifier is None and row.get("dataset") and row.get("metric"):
        identifier = f"{row.get('dataset')}:{row.get('metric')}:{row.get('effective_at') or row.get('retrieved_at')}"
    if identifier is None and row.get("ticker") and row.get("date"):
        identifier = f"price_bars:{row.get('ticker')}:{row.get('date')}:{row.get('provider') or 'stored'}"
    if identifier is None and row.get("ticker"):
        identifier = f"security_master:{row.get('ticker')}"
    provider = row.get("provider") or ("SEC" if row.get("accession_number") or row.get("metrics") else None)
    if not provider and row.get("ticker") and any(key in row for key in ("name", "company_name", "verified_at", "exchange")):
        provider = "EagleEyes security master"
    return {
        "provider": provider,
        "source_url": row.get("source_url"),
        "source_record": str(identifier) if identifier is not None else metric,
        "effective_at": row.get("effective_at") or row.get("period_end") or row.get("published_at") or row.get("date"),
        "retrieved_at": row.get("retrieved_at") or row.get("fetched_at") or row.get("filed_at"),
        "metric": metric,
    }


def _coherent_dimension_rows(rows: Sequence[Mapping[str, Any]], family: str) -> tuple[list[Mapping[str, Any]], dict[str, Any]]:
    """Select one coherent disclosed axis; reject unresolved overlapping hierarchies."""
    axis_tokens = {
        "segments": ("product", "service", "segment"),
        "geographies": ("geograph", "country", "region"),
        "customers": ("customer",),
    }[family]
    by_axis: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        axes = [str(key) for key in (row.get("dimensions") or {}) if any(token in str(key).lower() for token in axis_tokens)]
        if len(axes) == 1:
            by_axis[axes[0]].append(row)
    candidates: list[tuple[int, float, str, list[Mapping[str, Any]]]] = []
    for axis, axis_rows in by_axis.items():
        unique: dict[str, Mapping[str, Any]] = {}
        for row in axis_rows:
            member = str((row.get("dimensions") or {}).get(axis) or "")
            current = unique.get(member)
            if current is None or abs(float(row.get("value") or 0)) > abs(float(current.get("value") or 0)):
                unique[member] = row
        all_rows = list(unique.values())
        subsets = [all_rows]
        if len(all_rows) > 2:
            aggregate_rows = [row for row in all_rows if str((row.get("dimensions") or {}).get(axis) or "").split(":")[-1].removesuffix("Member").lower()
                              in {"product", "products", "service", "services", "segment", "segments", "total"}]
            subsets.extend([[row for row in all_rows if row is not aggregate] for aggregate in aggregate_rows])
        for selected in subsets:
            values = [float(row.get("_share")) for row in selected if row.get("_share") is not None]
            total = sum(values)
            if family == "customers" or (len(values) >= 2 and .80 <= total <= 1.05):
                candidates.append((len(values), -abs(1 - total), axis, selected))
    if not candidates:
        return [], {"status": "INSUFFICIENT_EVIDENCE", "reason": "No single non-overlapping dimensional axis forms a coherent distribution."}
    _, _, axis, selected = max(candidates, key=lambda item: (item[0], item[1]))
    return selected, {"status": "SUCCESS", "axis": axis, "sum": sum(float(row.get("_share") or 0) for row in selected)}


def _present(value: Any) -> bool:
    return value is not None and value != "" and value != [] and value != {} and not (isinstance(value, float) and not math.isfinite(value))


def _ticker_rows(bundle: Mapping[str, Any], key: str, ticker: str) -> list[dict[str, Any]]:
    return [row for row in bundle.get(key, []) if str(row.get("ticker") or "").upper() == ticker]


def _latest_observations(rows: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    output: dict[str, Mapping[str, Any]] = {}
    for row in sorted(rows, key=lambda item: str(item.get("effective_at") or ""), reverse=True):
        output.setdefault(str(row.get("metric") or ""), row)
    return output


def _observation_value(row: Mapping[str, Any] | None) -> Any:
    if not row:
        return None
    return row.get("value_numeric") if row.get("value_numeric") is not None else row.get("value_text") if row.get("value_text") is not None else row.get("value_json")


def _filing_periods(bundle: Mapping[str, Any], ticker: str) -> list[dict[str, Any]]:
    # Keep every context separate so duration facts never overwrite YTD facts.
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    concept_map = {
        "RevenueFromContractWithCustomerExcludingAssessedTax": "revenue", "Revenues": "revenue", "SalesRevenueNet": "revenue",
        "GrossProfit": "gross_profit", "OperatingIncomeLoss": "operating_income", "NetIncomeLoss": "net_income",
        "ProfitLoss": "net_income", "EarningsPerShareDiluted": "eps_diluted",
        "NetCashProvidedByUsedInOperatingActivities": "operating_cash_flow",
        "PaymentsToAcquirePropertyPlantAndEquipment": "capex",
        "PaymentsToAcquireProductiveAssets": "capex",
        "CashAndCashEquivalentsAtCarryingValue": "cash", "LongTermDebt": "total_debt",
        "LongTermDebtAndFinanceLeaseObligations": "total_debt", "StockholdersEquity": "shareholder_equity",
        "WeightedAverageNumberOfDilutedSharesOutstanding": "shares_diluted",
        "EntityCommonStockSharesOutstanding": "shares_outstanding",
        "DepreciationDepletionAndAmortization": "depreciation_amortization",
        "DepreciationDepletionAndAmortizationPropertyPlantAndEquipment": "depreciation_amortization",
        "DepreciationAmortizationAndOther": "depreciation_amortization",
        "IncomeTaxExpenseBenefit": "income_tax_expense",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest": "pretax_income",
    }
    for fact in _ticker_rows(bundle, "filing_facts", ticker):
        if fact.get("dimensions"):
            continue
        metric_name = concept_map.get(str(fact.get("concept") or ""))
        if not metric_name:
            continue
        key = (str(fact.get("accession_number") or ""), f"{fact.get('period_start') or 'instant'}:{fact.get('period_end')}")
        row = grouped.setdefault(key, {
            "period_start": fact.get("period_start"), "period_end": fact.get("period_end"),
            "filed_at": fact.get("filed_at"), "form_type": fact.get("form_type"),
            "accession_number": fact.get("accession_number"), "source_url": fact.get("source_url"),
            "provider": fact.get("provider") or "SEC", "retrieved_at": fact.get("retrieved_at") or fact.get("fetched_at"),
            "fiscal_period": fact.get("fiscal_period"), "fiscal_year": fact.get("fiscal_year"), "metrics": {}, "context_ids": [],
        })
        row["metrics"][metric_name] = fact.get("value")
        row["context_ids"].append(fact.get("context_id"))
    return sorted(grouped.values(), key=lambda row: (str(row.get("period_end") or ""), str(row.get("filed_at") or "")), reverse=True)


def _periods(bundle: Mapping[str, Any], ticker: str) -> list[dict[str, Any]]:
    normalized = [dict(row) for row in _ticker_rows(bundle, "fundamentals", ticker)]
    inline = _filing_periods(bundle, ticker)
    # Inline facts add duration/filing provenance.  Company Facts remains a
    # fallback for comparable fiscal-period labels until inline data is present.
    return inline if inline else normalized


def _dimension_family(dimensions: Mapping[str, Any]) -> str | None:
    axes = " ".join(str(key) for key in dimensions).lower()
    members = " ".join(str(value) for value in dimensions.values()).lower()
    if "majorcustomer" in axes or "customer" in axes:
        return "customers"
    if any(token in axes for token in ("geograph", "country", "region")) or any(
        token in members for token in ("americas", "europe", "china", "japan", "asiapacific", "othercountries")
    ):
        return "geographies"
    if any(token in axes for token in ("product", "service", "segment")):
        return "segments"
    return None


def _dimensional_overview(bundle: Mapping[str, Any], ticker: str) -> dict[str, Any]:
    revenue_concepts = {"RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"}
    facts = []
    for row in _ticker_rows(bundle, "filing_facts", ticker):
        dimensions = row.get("dimensions") or {}
        family = _dimension_family(dimensions)
        if row.get("concept") in revenue_concepts:
            facts.append(row)
        elif family == "customers" and "ConcentrationRiskPercentage" in str(row.get("concept") or "") and any(
            "SalesRevenue" in str(value) for key, value in dimensions.items() if "BenchmarkAxis" in str(key)
        ):
            facts.append(row)
    consolidated = defaultdict(list)
    for row in facts:
        if not row.get("dimensions"):
            consolidated[(row.get("accession_number"), row.get("period_start"), row.get("period_end"), row.get("concept"))].append(row)
    output: dict[str, list[dict[str, Any]]] = {"segments": [], "geographies": [], "customers": []}
    groups_by_family: dict[str, dict[tuple[Any, Any, Any], list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for row in facts:
        family = _dimension_family(row.get("dimensions") or {})
        if family:
            groups_by_family[family][(row.get("accession_number"), row.get("period_start"), row.get("period_end"))].append(row)
    selected_groups: dict[str, tuple[Any, Any, Any]] = {}
    for family, groups in groups_by_family.items():
        # One coherent issuer-reported context only. Prefer the latest ending
        # period, then a discrete quarter over YTD duplicates, then the filing
        # with the richest dimensional disclosure.
        def group_rank(item: tuple[tuple[Any, Any, Any], list[dict[str, Any]]]) -> tuple[str, int, int, str]:
            (accession, start, end), rows = item
            duration = 9999
            try:
                duration = (datetime.fromisoformat(str(end)[:10]) - datetime.fromisoformat(str(start)[:10])).days if start else 9999
            except ValueError:
                pass
            discrete_rank = 1 if 70 <= duration <= 120 else 0
            return str(end or ""), discrete_rank, len(rows), str(accession or "")
        selected_groups[family] = max(groups.items(), key=group_rank)[0]
    for row in facts:
        family = _dimension_family(row.get("dimensions") or {})
        group = (row.get("accession_number"), row.get("period_start"), row.get("period_end"))
        if not family or group != selected_groups.get(family):
            continue
        denominator_rows = consolidated.get((row.get("accession_number"), row.get("period_start"), row.get("period_end"), row.get("concept")), [])
        denominator = next((item.get("value") for item in denominator_rows if item.get("value") not in (None, 0)), None)
        dimensions = row.get("dimensions") or {}
        member_values = [value for key, value in dimensions.items() if
                         (family == "customers" and "MajorCustomersAxis" in str(key))
                         or (family == "geographies" and any(token in str(key).lower() for token in ("geograph", "country", "region")))
                         or (family == "segments" and any(token in str(key).lower() for token in ("product", "service", "segment")))]
        name = " / ".join(str(value).split(":")[-1].removesuffix("Member") for value in member_values)
        share = float(row["value"]) if family == "customers" and "ConcentrationRiskPercentage" in str(row.get("concept")) else (float(row["value"]) / float(denominator)) if row.get("value") is not None and denominator else None
        prior = None
        try:
            current_end = datetime.fromisoformat(str(row.get("period_end"))[:10])
            current_start = datetime.fromisoformat(str(row.get("period_start"))[:10]) if row.get("period_start") else None
            current_duration = (current_end - current_start).days if current_start else None
            aligned = [candidate for candidate in facts if candidate is not row and candidate.get("concept") == row.get("concept")
                       and candidate.get("dimensions") == dimensions and candidate.get("period_start") and candidate.get("period_end")
                       and 330 <= (current_end - datetime.fromisoformat(str(candidate["period_end"])[:10])).days <= 400]
            aligned = [candidate for candidate in aligned if current_duration is not None and abs((datetime.fromisoformat(str(candidate["period_end"])[:10]) - datetime.fromisoformat(str(candidate["period_start"])[:10])).days - current_duration) <= 7]
            prior = max(aligned, key=lambda candidate: str(candidate.get("period_end")), default=None)
        except ValueError:
            prior = None
        output[family].append({
            "name": name or "Undisclosed", "value": row.get("value"),
            "revenue_share": share, "growth": growth(row.get("value"), (prior or {}).get("value")),
            "period_end": row.get("period_end"), "filed_at": row.get("filed_at"),
            "accession_number": row.get("accession_number"), "context_id": row.get("context_id"),
            "dimensions": dimensions, "unit": row.get("unit"), "source_url": row.get("source_url"),
            "provider": row.get("provider") or "SEC", "_share": share,
        })
    for family in ("segments", "geographies", "customers"):
        coherent, group = _coherent_dimension_rows(output[family], family)
        output[family] = sorted((dict(row) for row in coherent), key=lambda row: abs(float(row.get("value") or 0)), reverse=True)
        for row in output[family]:
            row.pop("_share", None)
            row["axis"] = group.get("axis")
            row["distribution_status"] = group.get("status")
        output[f"{family}_methodology"] = group  # type: ignore[assignment]
    return output


def _chart_periods(periods: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Select unique, complete discrete quarters for Research charts."""
    candidates: list[Mapping[str, Any]] = []
    for row in periods:
        try:
            duration = (datetime.fromisoformat(str(row.get("period_end"))[:10]) - datetime.fromisoformat(str(row.get("period_start"))[:10])).days
        except (TypeError, ValueError):
            continue
        if 70 <= duration <= 120 and (row.get("metrics") or {}).get("revenue") is not None:
            candidates.append(row)
    selected: dict[str, Mapping[str, Any]] = {}
    for row in candidates:
        period_end = str(row.get("period_end") or "")[:10]
        current = selected.get(period_end)
        populated = sum(value is not None for value in (row.get("metrics") or {}).values())
        current_populated = sum(value is not None for value in (current or {}).get("metrics", {}).values())
        if current is None or (populated, str(row.get("filed_at") or "")) > (current_populated, str(current.get("filed_at") or "")):
            selected[period_end] = row
    return [dict(row) for row in sorted(selected.values(), key=lambda item: str(item.get("period_end") or ""), reverse=True)[:8]]


def _section_stale(metric: ResearchMetric, as_of: Any) -> bool:
    if not as_of:
        return False
    try:
        parsed = datetime.fromisoformat(str(as_of).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return True
    age = datetime.now(timezone.utc) - parsed
    if metric.section in {"header", "market_data"}:
        return age > timedelta(days=4)
    if metric.section in {"financial_health", "valuation", "earnings", "overview"}:
        return age > timedelta(days=400 if "FY" in metric.freshness_policy else 120)
    if metric.section == "ownership_sentiment":
        return age > timedelta(days=30)
    return False


def section_statuses(fields: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    by_section: dict[str, list[ResearchMetric]] = defaultdict(list)
    for item in REGISTRY:
        by_section[item.section].append(item)
    output: dict[str, Any] = {}
    for section, contract in by_section.items():
        available, missing, gated, stale, failures, insufficient = [], [], [], [], [], []
        for item in contract:
            field = fields.get(item.key) or {}
            capability = CAPABILITY_BY_KEY[item.key].classification
            if capability == "PLAN_GATED":
                gated.append(item.key)
            elif _present(field.get("value")):
                available.append(item.key)
                if _section_stale(item, field.get("as_of")):
                    stale.append(item.key)
            else:
                missing.append(item.key)
                if field.get("status") in {"COMPUTATION_FAILED", "DEPENDENCY_FAILED"}:
                    failures.append(item.key)
                if field.get("status") == "INSUFFICIENT_EVIDENCE":
                    insufficient.append(item.key)
        coverage = len(available) / len(contract) if contract else 0.0
        status = "SUCCESS" if len(available) == len(contract) else "PARTIAL" if available else "UNAVAILABLE"
        execution_status = "FAILED" if failures else "SUCCESS"
        freshness_status = "STALE" if stale else "CURRENT" if available else "UNKNOWN"
        output[section] = {"status": status, "coverage": round(coverage, 4), "available_fields": available,
                           "missing_fields": missing, "plan_gated_fields": gated, "stale_fields": stale,
                           "insufficient_evidence_fields": insufficient, "failed_fields": failures,
                           "execution_status": execution_status, "freshness_status": freshness_status}
    all_available = sum(len(row["available_fields"]) for row in output.values())
    output["page"] = {
        "status": "SUCCESS" if all(row["status"] == "SUCCESS" for key, row in output.items() if key != "page") else "PARTIAL" if all_available else "UNAVAILABLE",
        "coverage": round(all_available / len(REGISTRY), 4),
        "available_fields": [value for row in output.values() for value in row.get("available_fields", [])],
        "missing_fields": [value for row in output.values() for value in row.get("missing_fields", [])],
        "plan_gated_fields": [value for row in output.values() for value in row.get("plan_gated_fields", [])],
        "stale_fields": [value for row in output.values() for value in row.get("stale_fields", [])],
        "execution_status": "FAILED" if any(row.get("execution_status") == "FAILED" for row in output.values()) else "SUCCESS",
        "freshness_status": "STALE" if any(row.get("freshness_status") == "STALE" for row in output.values()) else "CURRENT",
    }
    return output


def _field(value: Any, *, as_of: Any = None, source_url: str | None = None, evidence: str = "VERIFIED_FACT",
           methodology: Any = None, provider: str | None = None, source_record: str | None = None,
           retrieved_at: Any = None, input_evidence: Sequence[Mapping[str, Any]] = (),
           state: str | None = None, reason: str | None = None) -> dict[str, Any]:
    return {"value": value, "as_of": as_of, "source_url": source_url, "evidence_type": evidence,
            "methodology": methodology, "provider": provider, "source_record": source_record,
            "retrieved_at": retrieved_at, "input_evidence": [dict(item) for item in input_evidence if item],
            "state": state, "reason": reason}


def _decorate_fields(fields: dict[str, dict[str, Any]]) -> None:
    """Attach the registry contract to every field returned to product clients.

    React and Ask should not need their own provider, null-state, freshness, or
    formula tables.  Keeping this metadata beside the value also makes a field's
    evidence inspectable without introducing card-specific API contracts.
    """
    for metric in REGISTRY:
        field = fields[metric.key]
        capability = CAPABILITY_BY_KEY[metric.key].classification
        present = _present(field.get("value"))
        if metric.key == "portfolio.beta_before_after" and isinstance(field.get("value"), Mapping):
            present = field["value"].get("before") is not None and field["value"].get("after") is not None
        if not present:
            field["evidence_type"] = metric.evidence_type
        stale = present and _section_stale(metric, field.get("as_of"))
        explicit_state = str(field.get("state") or "").upper()
        if explicit_state in {"DATA_UNAVAILABLE", "NOT_DISCLOSED", "NOT_APPLICABLE", "INSUFFICIENT_EVIDENCE", "COMPUTATION_FAILED", "DEPENDENCY_FAILED"} and not present:
            status = explicit_state
        elif capability == "PLAN_GATED" and not present:
            status = "PLAN_GATED"
        elif metric.implementation_state == "CONTEXT_REQUIRED" and not present:
            status = "REQUIRES_CONTEXT"
        elif stale:
            status = "STALE"
        elif present:
            status = "AVAILABLE"
        else:
            status = "UNAVAILABLE"
        field.update({
            "key": metric.key,
            "label": metric.label,
            "classification": metric.classification,
            "status": status,
            "provider": field.get("provider"),
            "registered_providers": list(metric.providers),
            "source_tables": list(metric.source_tables),
            "freshness_policy": metric.freshness_policy,
            "stale": stale,
            "formula": metric.formula if metric.classification in {"DERIVED", "MODEL"} else None,
            "null_behavior": metric.null_behavior,
            "required_inputs": list(metric.required_inputs),
        })


def _apply_value_provenance(fields: dict[str, dict[str, Any]], *, price_row: Mapping[str, Any] | None,
                            fundamental_row: Mapping[str, Any] | None, master_row: Mapping[str, Any] | None,
                            observations: Mapping[str, Mapping[str, Any]], dimensions: Mapping[str, Any],
                            risk_row: Mapping[str, Any] | None, news_row: Mapping[str, Any] | None,
                            form4_row: Mapping[str, Any] | None = None) -> None:
    price_ref, fundamental_ref, master_ref = _source_ref(price_row), _source_ref(fundamental_row), _source_ref(master_row)
    dimension_refs = {
        family: [_source_ref(row) for row in dimensions.get(family, []) if _source_ref(row)]
        for family in ("segments", "geographies", "customers")
    }
    registry = {item.key: item for item in REGISTRY}
    for key, field in fields.items():
        if not _present(field.get("value")):
            field["provider"] = None
            field["source_url"] = None
            continue
        refs: list[dict[str, Any]] = []
        if key.startswith(("technical.", "performance.")) or key in {"header.current_price", "header.daily_change", "header.market_timestamp", "header.market_delay", "header.price_history"}:
            refs = [price_ref] if price_ref else []
        elif key.startswith("financial.") or key.startswith("earnings.surprise"):
            refs = [fundamental_ref] if fundamental_ref else []
        elif key.startswith("valuation."):
            refs = [item for item in (price_ref, fundamental_ref) if item]
        elif key.startswith("overview.segment"):
            refs = dimension_refs["segments"]
        elif key.startswith("overview.geography"):
            refs = dimension_refs["geographies"]
        elif key.startswith("overview.customer"):
            refs = dimension_refs["customers"]
        elif key in {"summary.what_it_does", "overview.business_description"}:
            refs = [ref for ref in (_source_ref(observations.get("description")), master_ref) if ref][:1]
        elif key.startswith("risk."):
            refs = [ref for ref in (_source_ref(risk_row),) if ref]
        elif key.startswith("sentiment."):
            refs = [ref for ref in (_source_ref(news_row),) if ref]
        elif key.startswith("ownership."):
            source_row = observations.get("short_interest") if "short" in key or "days_to_cover" in key else form4_row
            refs = [ref for ref in (_source_ref(source_row),) if ref]
        elif key.startswith("header."):
            observation_key = {"header.market_cap": "market_cap", "header.employees": "employees",
                               "header.headquarters": "headquarters", "header.exchange": "exchange",
                               "header.after_hours_change": "after_hours_price"}.get(key)
            refs = [ref for ref in (_source_ref(observations.get(observation_key)) if observation_key else master_ref, master_ref) if ref][:1]
        elif key in {"overview.competitor", "overview.peer_methodology"}:
            refs = [master_ref] if master_ref else []
        elif key.startswith("sources.model."):
            refs = []
        elif key.startswith("sources."):
            refs = [item for item in (fundamental_ref, price_ref) if item]
        elif key.startswith(("portfolio.", "thesis.", "decision.")):
            refs = [item for item in (price_ref, fundamental_ref, _source_ref(risk_row)) if item]
        refs = list({str(ref): ref for ref in refs}.values())
        if (registry.get(key) and registry[key].classification in {"DERIVED", "MODEL"}) or key.startswith(("portfolio.", "thesis.", "decision.", "sources.model.")):
            field["provider"] = "EagleEyes"
            field["source_record"] = f"calculation:{key}:{METRIC_VERSION if registry.get(key) and registry[key].classification == 'DERIVED' else MODEL_VERSION}"
            field["input_evidence"] = refs
        elif refs:
            field["provider"] = refs[0].get("provider")
            field["source_record"] = refs[0].get("source_record")
            field["retrieved_at"] = refs[0].get("retrieved_at")
            field["source_url"] = field.get("source_url") or refs[0].get("source_url")


def _quality_peer_medians(rows: Sequence[Mapping[str, Any]]) -> tuple[dict[str, float | None], dict[str, Any]]:
    bounds = {"pe_ttm": (0, 100), "price_to_sales": (0, 50), "ev_to_ebitda": (0, 80), "fcf_yield": (0, .25)}
    output: dict[str, float | None] = {}
    quality: dict[str, Any] = {}
    for metric, (low, high) in bounds.items():
        samples = [(str(row.get("ticker") or ""), float(row[metric])) for row in rows
                   if row.get(metric) is not None and low < float(row[metric]) <= high]
        values = [value for _, value in samples]
        if len(values) >= 4:
            ordered = sorted(values)
            q1, q3 = ordered[len(ordered) // 4], ordered[(3 * len(ordered)) // 4]
            spread = q3 - q1
            if spread > 0:
                samples = [(ticker, value) for ticker, value in samples if q1 - 1.5 * spread <= value <= q3 + 1.5 * spread]
        accepted = len(samples) >= MIN_VALID_PEERS
        output[metric] = peer_medians([{metric: value} for _, value in samples], (metric,))[metric] if accepted else None
        quality[metric] = {"status": "SUCCESS" if accepted else "INSUFFICIENT_EVIDENCE",
                           "minimum_valid_peers": MIN_VALID_PEERS, "valid_peer_count": len(samples),
                           "peers": [ticker for ticker, _ in samples], "bounds": [low, high],
                           "outlier_rule": "1.5× IQR when at least four valid samples"}
    return output, quality


def _model_outputs(financials: Mapping[str, Any], valuation: Mapping[str, Any], history: Mapping[str, Any],
                   dimensions: Mapping[str, Any], documents: Sequence[Mapping[str, Any]], price: float | None,
                   *, as_of: str | None = None, business_type: str = "OPERATING_COMPANY",
                   earnings_available: bool = False, catalysts_available: bool = False) -> dict[str, Any]:
    percentile = history.get("current_percentile")
    interpretation = None
    if percentile is not None:
        interpretation = "Low versus its point-in-time history" if percentile <= .25 else "High versus its point-in-time history" if percentile >= .75 else "Near its historical middle range"
    values = [float(item["value"]) for item in history.get("samples") or [] if item.get("value") is not None]
    fair_value = None
    current_eps = (financials.get("ttm") or {}).get("eps_diluted")
    if len(values) >= 24 and current_eps is not None and current_eps > 0 and business_type == "OPERATING_COMPANY":
        ordered = sorted(values)
        multiple_cases = {"bear": ordered[int(.25 * (len(ordered) - 1))], "base": ordered[int(.50 * (len(ordered) - 1))], "bull": ordered[int(.75 * (len(ordered) - 1))]}
        fair_value = {name: round(multiple * float(current_eps), 2) for name, multiple in multiple_cases.items()}
    evidence = []
    positives, negatives = [], []
    if business_type == "OPERATING_COMPANY" and financials.get("revenue_growth_yoy") is not None and financials["revenue_growth_yoy"] > 0:
        positives.append({"statement": "Revenue grew year over year", "metric": "financial.revenue_growth_yoy",
                          "invalidation": "Year-over-year revenue growth falls to 0% or below"})
    if financials.get("net_cash_debt") is not None and financials["net_cash_debt"] > 0:
        positives.append({"statement": "Balance sheet is in a net-cash position", "metric": "financial.net_cash_debt",
                          "invalidation": "Net cash turns into a net-debt position"})
    if business_type == "OPERATING_COMPANY" and financials.get("free_cash_flow") is not None and financials["free_cash_flow"] > 0:
        positives.append({"statement": "Reported period produced positive free cash flow", "metric": "financial.free_cash_flow",
                          "invalidation": "Free cash flow turns negative on a comparable reported basis"})
    if dimensions.get("customers"):
        negatives.append({"statement": "Issuer reports material customer concentration", "metric": "overview.customer.revenue_share",
                          "invalidation": "Disclosed largest-customer concentration falls below 10% of revenue"})
    if percentile is not None and percentile >= .75:
        negatives.append({"statement": "Valuation is in the upper quartile of its point-in-time P/E history", "metric": "valuation.history_range",
                          "invalidation": "Point-in-time P/E percentile falls below the 50th percentile without estimate substitution"})
    risk_docs = [row for row in documents if row.get("document_type") == "risk_factor"]
    if risk_docs:
        negatives.append({"statement": "Latest filing contains company-specific risk-factor evidence", "metric": "risk.explanation",
                          "invalidation": None})
        evidence += [row.get("source_url") for row in risk_docs[:3] if row.get("source_url")]
    metadata = {"inputs": {"financials": dict(financials), "valuation": dict(valuation), "historical_valuation": history},
                "assumptions": ["No consensus estimates or transcript evidence are substituted", "10% cost of equity only for the disclosed implied-expectations identity"],
                "methodology": "deterministic evidence rules and point-in-time historical multiples", "model_version": MODEL_VERSION,
                "evidence_links": list(dict.fromkeys(evidence)), "as_of": as_of}
    bull_ready = business_type == "OPERATING_COMPANY" and len(positives) >= 2
    bear_ready = len([item for item in negatives if item.get("metric") != "risk.explanation"]) >= 1
    decision_ready = bull_ready and bear_ready and fair_value is not None and earnings_available and catalysts_available
    rating = ("RESEARCH_CANDIDATE" if len(negatives) <= 1 else "WATCH") if decision_ready else "RESEARCH"
    confidence = None
    if decision_ready:
        confidence = "HIGH" if earnings_available and catalysts_available and len(positives) >= 3 else "MEDIUM"
    common = {**metadata, "sufficiency": {"business_type": business_type, "bull_ready": bull_ready,
               "bear_ready": bear_ready, "earnings_available": earnings_available,
               "catalysts_available": catalysts_available, "valuation_reliable": fair_value is not None}}
    return {
        "historical_interpretation": {"value": interpretation, **common} if interpretation and business_type == "OPERATING_COMPANY" else None,
        "fair_value": {"value": fair_value, **common, "methodology": "current TTM diluted EPS × point-in-time historical P/E quartiles"} if fair_value else None,
        "implied_expectations": None,
        "bull_thesis": {"value": [item["statement"] for item in positives], **common} if bull_ready else None,
        "bear_thesis": {"value": [item["statement"] for item in negatives], **common} if bear_ready else None,
        "bull_invalidation": {"value": [item["invalidation"] for item in positives if item.get("invalidation")], **common} if bull_ready else None,
        "bear_invalidation": {"value": [item["invalidation"] for item in negatives if item.get("invalidation")], **common} if bear_ready and any(item.get("invalidation") for item in negatives) else None,
        "decision": {"value": rating, **common, "reason": None if decision_ready else "Insufficient earnings/catalyst evidence for a stronger decision state."},
        "decision_confidence": {"value": confidence, **common} if confidence else None,
        "entry_range": {"value": [round(fair_value["base"] * .85, 2), round(fair_value["base"] * .95, 2)], **common} if decision_ready and fair_value else None,
    }


def _year_to_date(rows: Sequence[Mapping[str, Any]]) -> float | None:
    if len(rows) < 2:
        return None
    ordered = sorted(rows, key=lambda row: str(row.get("date") or ""))
    year = str(ordered[-1].get("date") or "")[:4]
    first = next((row for row in ordered if str(row.get("date") or "").startswith(year)), None)
    return growth(ordered[-1].get("close"), (first or {}).get("close"))


def _trend_read(technical: Mapping[str, Any]) -> str | None:
    price = technical.get("price")
    averages = technical.get("moving_averages") or {}
    sma50, sma200 = averages.get("sma_50"), averages.get("sma_200")
    if price is None or sma50 is None:
        return None
    if sma200 is not None and price > sma50 > sma200:
        return "UPTREND"
    if sma200 is not None and price < sma50 < sma200:
        return "DOWNTREND"
    return "MIXED"


def build_shared_research_model(ticker: str, *, bundle: Mapping[str, Any] | None = None,
                                peer_valuations: Sequence[Mapping[str, Any]] = (), portfolio: Mapping[str, Any] | None = None) -> dict[str, Any]:
    ticker = ticker.upper()
    if bundle is None:
        peer_tickers = database.research_peer_tickers(ticker)
        holding_tickers = [str(row.get("ticker") or "").upper() for row in (portfolio or {}).get("holdings", [])]
        bundle = database.research_capability_data([ticker, *peer_tickers, *holding_tickers, "SPY", "QQQ", "XLK", "SOXX"])
    securities = _ticker_rows(bundle, "securities", ticker)
    masters = _ticker_rows(bundle, "security_master", ticker)
    security, master = (securities[0] if securities else {}), (masters[0] if masters else {})
    business_type = _business_type(security)
    metadata = master.get("metadata") or {}
    observations = _latest_observations(_ticker_rows(bundle, "source_observations", ticker))
    periods = _periods(bundle, ticker)
    chart_periods = _chart_periods(periods)
    financials = financial_metrics(periods)
    prices = _ticker_rows(bundle, "prices", ticker)
    spy = _ticker_rows(bundle, "prices", "SPY")
    qqq = _ticker_rows(bundle, "prices", "QQQ")
    sector_prices = _ticker_rows(bundle, "prices", "XLK") or _ticker_rows(bundle, "prices", "SOXX")
    technical = technical_metrics(prices, spy)
    spy_technical, qqq_technical, sector_technical = technical_metrics(spy), technical_metrics(qqq), technical_metrics(sector_prices)
    latest_price = technical.get("price")
    shares = _observation_value(observations.get("shares_outstanding")) or metadata.get("weighted_shares_outstanding")
    valuation = valuation_metrics(latest_price, financials, shares_outstanding=shares)
    if not peer_valuations:
        target_industry, target_sector = security.get("industry"), security.get("sector")
        candidates = [row for row in bundle.get("securities", []) if str(row.get("ticker") or "").upper() != ticker
                      and str(row.get("asset_type") or "").lower() == "stock"
                      and ((target_industry and row.get("industry") == target_industry) or (target_sector and row.get("sector") == target_sector))]
        # A sector-only fallback is too broad for valuation comparison (for
        # example, software and hardware issuers can have structurally
        # different margins and multiples).  If an exact industry cohort is
        # unavailable, the honest result is an unavailable peer comparison.
        preferred = [row for row in candidates if target_industry and row.get("industry") == target_industry]
        calculated_peers = []
        for peer in preferred[:8]:
            peer_ticker = str(peer.get("ticker") or "").upper()
            peer_periods = _periods(bundle, peer_ticker)
            peer_financials = financial_metrics(peer_periods)
            peer_prices = _ticker_rows(bundle, "prices", peer_ticker)
            peer_price = technical_metrics(peer_prices).get("price")
            peer_observations = _latest_observations(_ticker_rows(bundle, "source_observations", peer_ticker))
            peer_masters = _ticker_rows(bundle, "security_master", peer_ticker)
            peer_metadata = (peer_masters[0].get("metadata") or {}) if peer_masters else {}
            peer_shares = _observation_value(peer_observations.get("shares_outstanding")) or peer_metadata.get("weighted_shares_outstanding")
            peer_value = valuation_metrics(peer_price, peer_financials, shares_outstanding=peer_shares)
            if any(_present(peer_value.get(key)) for key in ("pe_ttm", "price_to_sales", "ev_to_ebitda", "fcf_yield")):
                calculated_peers.append({"ticker": peer_ticker, **peer_value})
        peer_valuations = calculated_peers
    filing_prices = prices[::21] if len(prices) > 21 else prices
    filing_periods = _filing_periods(bundle, ticker)
    valuation_history = historical_valuation(filing_prices, filing_periods, "pe_ttm")
    dimensions = _dimensional_overview(bundle, ticker)
    docs = _ticker_rows(bundle, "filing_documents", ticker)
    calculated_at = datetime.now(timezone.utc).isoformat()
    model_as_of = max((str(value) for value in (financials.get("as_of"), technical.get("as_of")) if value), default=calculated_at)
    model_outputs = _model_outputs(
        financials, valuation, valuation_history, dimensions, docs, latest_price, as_of=model_as_of,
        business_type=business_type, earnings_available=False, catalysts_available=False,
    )
    after = _observation_value(observations.get("after_hours_price"))
    regular = _observation_value(observations.get("regular_close"))
    after_change = growth(after, regular) if after is not None and regular is not None else None
    description_doc = next((row for row in docs if row.get("document_type") == "10_k_section" and str((row.get("metadata") or {}).get("section") or "").lower() == "business"), None)
    risk_doc = next((row for row in docs if row.get("document_type") == "risk_factor"), None)
    risk_metadata = (risk_doc or {}).get("metadata") or {}
    risk_name = risk_metadata.get("primary_category") or risk_metadata.get("category") or risk_metadata.get("risk_category") or (risk_doc or {}).get("title")
    risk_explanation = str((risk_doc or {}).get("content") or risk_metadata.get("supporting_text") or "").strip()[:800] or None
    description = _observation_value(observations.get("description")) or metadata.get("description") or (description_doc or {}).get("content")
    headquarters = _observation_value(observations.get("headquarters")) or metadata.get("headquarters")
    employees = _observation_value(observations.get("employees")) or metadata.get("employees")
    market_cap = _observation_value(observations.get("market_cap")) or valuation.get("market_cap") or metadata.get("market_cap")
    as_of_market = technical.get("as_of")
    as_of_fund = financials.get("as_of")

    form4 = [row for row in _ticker_rows(bundle, "source_observations", ticker) if row.get("dataset") == "form_4"]
    short_interest = observations.get("short_interest")
    ownership = {"form_4": form4, "short_interest": (short_interest or {}).get("value_json") if short_interest else None,
                 "short_volume": (observations.get("short_volume") or {}).get("value_json"), "float": (observations.get("float") or {}).get("value_json")}
    news_rows = _ticker_rows(bundle, "news", ticker)
    sentiment_counts = defaultdict(int)
    for row in news_rows:
        sentiment_counts[str((row.get("metadata") or {}).get("sentiment_label") or (row.get("metadata") or {}).get("sentiment") or "unknown").lower()] += 1
    classified_news = sum(sentiment_counts[key] for key in ("positive", "negative", "neutral"))
    news_score = ((sentiment_counts["positive"] - sentiment_counts["negative"]) / classified_news) if classified_news else None
    short_payload = ownership.get("short_interest") or {}
    short_percent = (float(short_payload.get("short_interest")) / float(shares)) if short_payload.get("short_interest") is not None and shares else None
    short_history = sorted([row for row in _ticker_rows(bundle, "source_observations", ticker)
                            if row.get("dataset") == "short_interest" and row.get("metric") == "short_interest"],
                           key=lambda row: str(row.get("effective_at") or ""), reverse=True)
    short_change = growth(short_history[0].get("value_numeric"), short_history[1].get("value_numeric")) if len(short_history) >= 2 else None
    form4_payloads = [row.get("value_json") or {} for row in form4]
    insider_buys = sum(1 for row in form4_payloads if str(row.get("acquisition_disposition") or row.get("transaction_code") or "").upper() in {"A", "P"})
    insider_sells = sum(1 for row in form4_payloads if str(row.get("acquisition_disposition") or row.get("transaction_code") or "").upper() in {"D", "S"})
    peer_values, peer_quality = _quality_peer_medians(peer_valuations)
    peer_values_display = peer_values if any(value is not None for value in peer_values.values()) else None
    valuation_read = (model_outputs.get("historical_interpretation") or {}).get("value")
    improving = None
    improving_reason = None
    improving_inputs = ("revenue_growth_yoy", "gross_margin_change_bps", "operating_margin_change_bps", "free_cash_flow")
    if business_type != "OPERATING_COMPANY":
        improving_reason = "Business-type-specific analysis is not yet supported."
    elif not all(financials.get(key) is not None for key in improving_inputs):
        improving_reason = "Insufficient evidence to determine business trend."
    else:
        revenue_growth = float(financials["revenue_growth_yoy"])
        gross_change = float(financials["gross_margin_change_bps"])
        operating_change = float(financials["operating_margin_change_bps"])
        fcf = float(financials["free_cash_flow"])
        improving = "YES" if revenue_growth > 0 and gross_change >= 0 and operating_change >= 0 and fcf > 0 else (
            "NO" if revenue_growth < 0 and (gross_change < 0 or operating_change < 0) else "MIXED"
        )
    holdings = list((portfolio or {}).get("holdings") or [])
    price_by_ticker = {symbol: _ticker_rows(bundle, "prices", symbol) for symbol in {str(row.get("ticker") or "").upper() for row in holdings}}
    portfolio_fit = portfolio_metrics(ticker, prices, holdings, price_by_ticker, spy,
                                      proposed_weight=(portfolio or {}).get("proposed_weight")) if holdings else {}
    classification = {str(row.get("ticker") or "").upper(): row.get("sector") for row in bundle.get("securities", [])}
    sector_after = sum((float(row.get("weight") or 0) / (100 if float(row.get("weight") or 0) > 1 else 1))
                       for row in holdings if classification.get(str(row.get("ticker") or "").upper()) == security.get("sector")) if holdings and security.get("sector") else None

    fields = {item.key: _field(None) for item in REGISTRY}
    values: dict[str, tuple[Any, Any, str | None, str]] = {
        "header.ticker": (ticker, master.get("verified_at") or security.get("updated_at"), None, "VERIFIED_FACT"), "header.company_name": (master.get("name") or security.get("company_name"), master.get("verified_at") or security.get("updated_at"), None, "VERIFIED_FACT"),
        "header.exchange": (_observation_value(observations.get("exchange")) or master.get("exchange"), master.get("verified_at"), None, "VERIFIED_FACT"),
        "header.sector": (security.get("sector"), security.get("updated_at"), None, "VERIFIED_FACT"), "header.industry": (security.get("industry"), security.get("updated_at"), None, "VERIFIED_FACT"),
        "header.current_price": (latest_price, as_of_market, None, "VERIFIED_MARKET_DATA"), "header.daily_change": ((technical.get("returns") or {}).get("1_week") if len(prices) < 2 else growth(prices[-1].get("close"), prices[-2].get("close")), as_of_market, None, "VERIFIED_MARKET_DATA"),
        "header.after_hours_change": (after_change, (observations.get("after_hours_price") or {}).get("effective_at"), (observations.get("after_hours_price") or {}).get("source_url"), "VERIFIED_MARKET_DATA"),
        "header.market_timestamp": (as_of_market, as_of_market, None, "VERIFIED_MARKET_DATA"), "header.market_delay": ("end-of-day" if prices else None, as_of_market, None, "VERIFIED_MARKET_DATA"),
        "header.market_cap": (market_cap, (observations.get("market_cap") or {}).get("effective_at") or as_of_market, (observations.get("market_cap") or {}).get("source_url"), "VERIFIED_FACT"),
        "header.employees": (employees, master.get("verified_at"), None, "VERIFIED_FACT"), "header.headquarters": (headquarters, master.get("verified_at"), None, "VERIFIED_FACT"),
        "header.price_history": (prices, as_of_market, None, "VERIFIED_MARKET_DATA"), "summary.what_it_does": (description, master.get("verified_at"), (description_doc or {}).get("source_url"), "VERIFIED_FACT"),
        "overview.business_description": (description, master.get("verified_at"), (description_doc or {}).get("source_url"), "VERIFIED_FACT"),
        "summary.improving": (improving, as_of_fund, None, "OPINION"), "summary.cheap": (valuation_read, as_of_market, None, "OPINION"),
        "overview.segment.name": ([row["name"] for row in dimensions["segments"]], as_of_fund, None, "VERIFIED_FACT"), "overview.segment.revenue_share": ([row["revenue_share"] for row in dimensions["segments"]], as_of_fund, None, "VERIFIED_FACT"),
        "overview.segment.growth": ([row["growth"] for row in dimensions["segments"] if row.get("growth") is not None], as_of_fund, None, "VERIFIED_FACT"),
        "overview.geography.name": ([row["name"] for row in dimensions["geographies"]], as_of_fund, None, "VERIFIED_FACT"), "overview.geography.revenue_share": ([row["revenue_share"] for row in dimensions["geographies"]], as_of_fund, None, "VERIFIED_FACT"),
        "overview.customer.name": ([row["name"] for row in dimensions["customers"]], as_of_fund, None, "VERIFIED_FACT"), "overview.customer.revenue_share": ([row["revenue_share"] for row in dimensions["customers"]], as_of_fund, None, "VERIFIED_FACT"),
        "overview.competitor": ([row.get("ticker") for row in peer_valuations], as_of_market, None, "VERIFIED_FACT"),
        "overview.peer_methodology": ("exact industry; active common stocks; issuer and funds excluded; minimum three valid observations per metric", METHOD_VERSION_AS_OF, None, "VERIFIED_FACT"),
        "financial.revenue_growth_yoy": (financials.get("revenue_growth_yoy"), as_of_fund, None, "VERIFIED_FACT"), "financial.revenue_trend": (financials.get("revenue_growth_acceleration"), as_of_fund, None, "VERIFIED_FACT"),
        "financial.eps_growth_yoy": (financials.get("eps_growth_yoy"), as_of_fund, None, "VERIFIED_FACT"), "financial.gross_margin": (financials.get("gross_margin"), as_of_fund, None, "VERIFIED_FACT"),
        "financial.gross_margin_change": (financials.get("gross_margin_change_bps"), as_of_fund, None, "VERIFIED_FACT"), "financial.operating_margin": (financials.get("operating_margin"), as_of_fund, None, "VERIFIED_FACT"),
        "financial.operating_margin_change": (financials.get("operating_margin_change_bps"), as_of_fund, None, "VERIFIED_FACT"), "financial.free_cash_flow": (financials.get("free_cash_flow"), as_of_fund, None, "VERIFIED_FACT"),
        "financial.fcf_margin": (financials.get("fcf_margin"), as_of_fund, None, "VERIFIED_FACT"), "financial.cash": (financials.get("cash"), as_of_fund, None, "VERIFIED_FACT"),
        "financial.debt": (financials.get("debt"), as_of_fund, None, "VERIFIED_FACT"), "financial.net_cash_debt": (financials.get("net_cash_debt"), as_of_fund, None, "VERIFIED_FACT"),
        "financial.share_count_change": (financials.get("share_count_change"), as_of_fund, None, "VERIFIED_FACT"), "financial.roic": (financials.get("roic"), as_of_fund, None, "VERIFIED_FACT"),
        "financial.chart.period": (chart_periods, as_of_fund, None, "VERIFIED_FACT"), "valuation.pe_ttm": (valuation.get("pe_ttm"), as_of_market, None, "VERIFIED_FACT"),
        # Period labels alone are not an earnings-surprise history.
        "earnings.surprise.period": (None, as_of_fund, None, "VERIFIED_FACT"),
        "financial.chart.revenue": ([row.get("metrics", {}).get("revenue") for row in chart_periods], as_of_fund, None, "VERIFIED_FACT"),
        "financial.chart.fcf": ([financial_metrics([row]).get("free_cash_flow") for row in chart_periods], as_of_fund, None, "VERIFIED_FACT"),
        "financial.chart.gross_margin": ([financial_metrics([row]).get("gross_margin") for row in chart_periods], as_of_fund, None, "VERIFIED_FACT"),
        "financial.chart.operating_margin": ([financial_metrics([row]).get("operating_margin") for row in chart_periods], as_of_fund, None, "VERIFIED_FACT"),
        "valuation.price_to_sales": (valuation.get("price_to_sales"), as_of_market, None, "VERIFIED_FACT"), "valuation.ev_ebitda": (valuation.get("ev_to_ebitda"), as_of_market, None, "VERIFIED_FACT"),
        "valuation.fcf_yield": (valuation.get("fcf_yield"), as_of_market, None, "VERIFIED_FACT"), "valuation.history_range": ({"pe_ttm": valuation_history.get("range"), "current_percentile": valuation_history.get("current_percentile"), "sample_count": len(valuation_history.get("samples") or [])} if valuation_history.get("range") else None, as_of_market, None, "VERIFIED_FACT"),
        "valuation.peer_median": (peer_values_display, as_of_market, None, "VERIFIED_FACT"), "valuation.read": (valuation_read, as_of_market, None, "OPINION"),
        "technical.trend": (_trend_read(technical), as_of_market, None, "VERIFIED_MARKET_DATA"), "technical.sma_50": ((technical.get("moving_averages") or {}).get("sma_50"), as_of_market, None, "VERIFIED_MARKET_DATA"),
        "technical.sma_50_distance": (growth(latest_price, (technical.get("moving_averages") or {}).get("sma_50")), as_of_market, None, "VERIFIED_MARKET_DATA"),
        "technical.sma_200": ((technical.get("moving_averages") or {}).get("sma_200"), as_of_market, None, "VERIFIED_MARKET_DATA"), "technical.rsi_14": (technical.get("rsi_14"), as_of_market, None, "VERIFIED_MARKET_DATA"),
        "technical.sma_200_distance": (growth(latest_price, (technical.get("moving_averages") or {}).get("sma_200")), as_of_market, None, "VERIFIED_MARKET_DATA"),
        "technical.rsi_read": ("OVERSOLD" if technical.get("rsi_14") is not None and technical["rsi_14"] < 30 else "OVERBOUGHT" if technical.get("rsi_14") is not None and technical["rsi_14"] > 70 else "NEUTRAL" if technical.get("rsi_14") is not None else None, as_of_market, None, "VERIFIED_MARKET_DATA"),
        "technical.support": ((technical.get("support_resistance") or {}).get("support"), as_of_market, None, "VERIFIED_MARKET_DATA"), "technical.resistance": ((technical.get("support_resistance") or {}).get("resistance"), as_of_market, None, "VERIFIED_MARKET_DATA"),
        "technical.beta": (technical.get("beta"), as_of_market, None, "VERIFIED_MARKET_DATA"), "technical.max_drawdown": (technical.get("maximum_drawdown"), as_of_market, None, "VERIFIED_MARKET_DATA"),
        "technical.benchmark_drawdown": (spy_technical.get("maximum_drawdown"), spy_technical.get("as_of"), None, "VERIFIED_MARKET_DATA"),
        "performance.security_3m": ((technical.get("returns") or {}).get("3_month"), as_of_market, None, "VERIFIED_MARKET_DATA"),
        "performance.security_ytd": (_year_to_date(prices), as_of_market, None, "VERIFIED_MARKET_DATA"), "performance.security_1y": ((technical.get("returns") or {}).get("1_year"), as_of_market, None, "VERIFIED_MARKET_DATA"),
        "performance.spy": ((spy_technical.get("returns") or {}).get("1_year"), spy_technical.get("as_of"), None, "VERIFIED_MARKET_DATA"),
        "performance.qqq": ((qqq_technical.get("returns") or {}).get("1_year"), qqq_technical.get("as_of"), None, "VERIFIED_MARKET_DATA"),
        "performance.sector_etf": ((sector_technical.get("returns") or {}).get("1_year"), sector_technical.get("as_of"), None, "VERIFIED_MARKET_DATA"),
        "ownership.insider_net": (insider_buys - insider_sells if form4 else None, form4[0].get("effective_at") if form4 else None, form4[0].get("source_url") if form4 else None, "VERIFIED_FACT"),
        "ownership.insider_count": (len(form4) if form4 else None, form4[0].get("effective_at") if form4 else None, form4[0].get("source_url") if form4 else None, "VERIFIED_FACT"),
        "ownership.short_percent": (short_percent, (short_interest or {}).get("effective_at"), (short_interest or {}).get("source_url"), "VERIFIED_FACT"),
        "ownership.short_change": (short_change, (short_interest or {}).get("effective_at"), (short_interest or {}).get("source_url"), "VERIFIED_FACT"),
        "ownership.days_to_cover": (short_payload.get("days_to_cover"), (short_interest or {}).get("effective_at"), (short_interest or {}).get("source_url"), "VERIFIED_FACT"),
        "sentiment.news_score": (news_score, news_rows[0].get("published_at") if news_rows else None, news_rows[0].get("source_url") if news_rows else None, "VERIFIED_FACT"),
        "sentiment.news_driver": (next((row.get("title") for row in news_rows if (row.get("metadata") or {}).get("sentiment_reasoning")), None), news_rows[0].get("published_at") if news_rows else None, None, "VERIFIED_FACT"),
        "risk.name": (risk_name, (risk_doc or {}).get("published_at"), (risk_doc or {}).get("source_url"), "OPINION"),
        "risk.explanation": (risk_explanation, (risk_doc or {}).get("published_at"), (risk_doc or {}).get("source_url"), "OPINION"),
        "risk.severity": (risk_metadata.get("severity"), (risk_doc or {}).get("published_at"), (risk_doc or {}).get("source_url"), "OPINION"),
        "portfolio.current_exposure": (portfolio_fit.get("current_exposure"), as_of_market, None, "VERIFIED_FACT"),
        "portfolio.sector_after": (sector_after, as_of_market, None, "FORECAST"),
        "portfolio.sector_limit": ((portfolio or {}).get("sector_limit"), as_of_market, None, "VERIFIED_FACT"),
        "portfolio.highest_overlap": (portfolio_fit.get("highest_overlap"), as_of_market, None, "FORECAST"),
        "portfolio.correlation": (portfolio_fit.get("correlation"), as_of_market, None, "FORECAST"),
        "portfolio.suggested_position": (portfolio_fit.get("proposed_weight"), as_of_market, None, "OPINION"),
        "portfolio.beta_before_after": ({"before": portfolio_fit.get("portfolio_beta_before"), "after": portfolio_fit.get("portfolio_beta_after")} if portfolio_fit.get("portfolio_beta_before") is not None else None, as_of_market, None, "FORECAST"),
        "portfolio.stress_test": (portfolio_fit.get("stress_test_increment_at_minus_20_market"), as_of_market, None, "FORECAST"),
        "sources.verified.provider": ("SEC EDGAR" if periods else None, as_of_fund, next((row.get("source_url") for row in periods if row.get("source_url")), None), "VERIFIED_FACT"),
        "sources.verified.as_of": (as_of_fund, as_of_fund, None, "VERIFIED_FACT"), "sources.market.provider": (prices[-1].get("provider") if prices else None, as_of_market, None, "VERIFIED_MARKET_DATA"),
        "sources.market.delay": ("end-of-day" if prices else None, as_of_market, None, "VERIFIED_MARKET_DATA"), "sources.model.version": (MODEL_VERSION, model_as_of, None, "OPINION"),
        "sources.model.methodology": ("deterministic evidence rules and point-in-time valuation", model_as_of, None, "OPINION"),
    }
    for key, (value, as_of, source_url, evidence) in values.items():
        if key in fields:
            fields[key] = _field(value, as_of=as_of, source_url=source_url, evidence=evidence, methodology={"version": METRIC_VERSION})
    if improving is None:
        fields["summary.improving"] = _field(
            None, as_of=as_of_fund, evidence="OPINION",
            state="NOT_APPLICABLE" if business_type != "OPERATING_COMPANY" else "INSUFFICIENT_EVIDENCE",
            reason=improving_reason,
            methodology={"version": MODEL_VERSION, "required_inputs": list(improving_inputs),
                         "business_type": business_type, "minimum_coverage": 1.0, "freshness_days": 120},
        )
    if business_type != "OPERATING_COMPANY":
        for key in [item.key for item in REGISTRY if item.section == "financial_health"]:
            fields[key] = _field(None, evidence="VERIFIED_FACT", state="NOT_APPLICABLE",
                                 reason="Business-type-specific analysis is not yet supported.",
                                 methodology={"business_type": business_type, "version": METRIC_VERSION})
        for key in ("summary.cheap", "valuation.read", "valuation.fair_value.bear", "valuation.fair_value.base",
                    "valuation.fair_value.bull", "valuation.fair_value.assumptions", "valuation.implied_expectations"):
            if key in fields:
                fields[key] = _field(None, evidence="OPINION", state="NOT_APPLICABLE",
                                     reason="Business-type-specific valuation is not yet supported.",
                                     methodology={"business_type": business_type, "version": MODEL_VERSION})
    model_field_map = {
        "valuation.fair_value.bear": ("fair_value", "bear"), "valuation.fair_value.base": ("fair_value", "base"),
        "valuation.fair_value.bull": ("fair_value", "bull"), "valuation.fair_value.assumptions": ("fair_value", None),
        "valuation.implied_expectations": ("implied_expectations", None), "thesis.bull.statement": ("bull_thesis", None),
        "thesis.bear.statement": ("bear_thesis", None), "thesis.bull_invalidation": ("bull_invalidation", None),
        "thesis.bear_invalidation": ("bear_invalidation", None), "decision.rating": ("decision", None),
        "decision.entry": ("entry_range", None), "decision.invalidation": ("bull_invalidation", None),
        "decision.bull_thesis": ("bull_thesis", None), "decision.bear_thesis": ("bear_thesis", None),
        "decision.confidence": ("decision_confidence", None),
    }
    for registry_key, (output_key, child_key) in model_field_map.items():
        output = model_outputs.get(output_key)
        if registry_key in fields and output:
            value = output.get("value")
            value = value.get(child_key) if child_key and isinstance(value, dict) else output if registry_key == "valuation.fair_value.assumptions" else value
            fields[registry_key] = _field(value, as_of=output.get("as_of"), evidence="OPINION", methodology=output)
    primary_risk = ((model_outputs.get("bear_thesis") or {}).get("value") or [None])[0]
    if primary_risk:
        fields["summary.breaks"] = _field(primary_risk, as_of=model_outputs["bear_thesis"].get("as_of"), evidence="OPINION", methodology=model_outputs["bear_thesis"])
        fields["decision.primary_risk"] = _field(primary_risk, as_of=model_outputs["bear_thesis"].get("as_of"), evidence="OPINION", methodology=model_outputs["bear_thesis"])
    insufficiency = {
        "summary.cheap": "Insufficient point-in-time valuation history for a valuation conclusion.",
        "valuation.read": "Insufficient point-in-time valuation history for a valuation conclusion.",
        "valuation.fair_value.bear": "A valid current denominator and at least 24 point-in-time P/E samples are required.",
        "valuation.fair_value.base": "A valid current denominator and at least 24 point-in-time P/E samples are required.",
        "valuation.fair_value.bull": "A valid current denominator and at least 24 point-in-time P/E samples are required.",
        "valuation.implied_expectations": "A defensible reverse-DCF solver is not implemented; the prior heuristic is suppressed.",
        "summary.moves": "No qualifying known or model catalyst evidence is available.",
        "thesis.bull.statement": "Insufficient evidence to construct a supported bull case.",
        "thesis.bear.statement": "Insufficient evidence to construct a supported bear case.",
        "thesis.bull_invalidation": "No defensible bull-case invalidation is available.",
        "thesis.bear_invalidation": "No defensible bear-case invalidation is available.",
        "decision.confidence": "Confidence is unavailable until the minimum decision evidence contract is satisfied.",
        "decision.entry": "A valid gated valuation and decision contract is required for an entry range.",
    }
    for key, reason in insufficiency.items():
        if key in fields and not _present(fields[key].get("value")):
            fields[key] = _field(None, as_of=model_as_of, evidence="OPINION", state="INSUFFICIENT_EVIDENCE",
                                 reason=reason, methodology={"version": MODEL_VERSION})
    if not _present(fields.get("catalyst.event", {}).get("value")):
        fields["catalyst.event"] = _field(
            None, as_of=model_as_of, evidence="OPINION", state="INSUFFICIENT_EVIDENCE",
            reason="No qualifying known dated, known undated, or model-potential catalyst evidence is available.",
            methodology={"version": MODEL_VERSION, "accepted_event_types": [
                "KNOWN_DATED_EVENT", "KNOWN_UNDATED_EVENT", "MODEL_POTENTIAL_CATALYST",
            ], "generic_theme_as_catalyst": False},
        )
    if not _present(fields.get("catalyst.date", {}).get("value")):
        fields["catalyst.date"] = _field(
            None, evidence="VERIFIED_FACT", state="DATA_UNAVAILABLE",
            reason="No qualifying known dated company event is stored.",
            methodology={"accepted_event_type": "KNOWN_DATED_EVENT", "version": METRIC_VERSION},
        )
    _decorate_fields(fields)
    _apply_value_provenance(
        fields, price_row=prices[-1] if prices else None,
        fundamental_row=next((row for row in periods if str(row.get("period_end")) == str(as_of_fund)), periods[0] if periods else None),
        master_row=master, observations=observations, dimensions=dimensions,
        risk_row=risk_doc, news_row=news_rows[0] if news_rows else None,
        form4_row=form4[0] if form4 else None,
    )
    statuses = section_statuses(fields)
    return {
        "ticker": ticker, "version": VERSION, "generated_at": datetime.now(timezone.utc).isoformat(),
        "identity": {"ticker": ticker, "company": master.get("name") or security.get("company_name"), "exchange": master.get("exchange"),
                     "sector": security.get("sector"), "industry": security.get("industry"), "description": description,
                     "market_cap": market_cap, "employees": employees, "founded": None, "headquarters": headquarters,
                     "business_type": business_type},
        "market": {**technical, "after_hours_change": after_change}, "overview": {**dimensions, "business_description": description},
        "financial_health": financials if business_type == "OPERATING_COMPANY" else {"status": "NOT_APPLICABLE", "business_type": business_type},
        "valuation": {**valuation, "history": valuation_history, "peer_medians": peer_values, "peer_quality": peer_quality},
        "ownership_sentiment": {"ownership": ownership, "news_sentiment": dict(sentiment_counts)},
        "documents": docs, "portfolio_fit": {**dict(portfolio or {}), **portfolio_fit}, "model_outputs": model_outputs,
        "fields": fields, "sections": statuses, "status": statuses["page"]["status"], "coverage": statuses["page"]["coverage"],
        "plan_gated_fields": statuses["page"]["plan_gated_fields"],
        "lineage": {"fundamentals": [row.get("source_url") for row in periods[:8]], "market_as_of": as_of_market,
                    "fundamentals_as_of": as_of_fund, "metric_version": METRIC_VERSION},
    }

from __future__ import annotations

from backend.research_metrics import financial_metrics, historical_valuation, technical_metrics, valuation_metrics
from backend.research_read_model import _dimensional_overview, _model_outputs, _quality_peer_medians, section_statuses
from backend.research_read_model import build_shared_research_model
from backend.phase6_domains import build_company_analysis
from backend.sec_inline_xbrl import parse_inline_xbrl


def period(year: int, fp: str, revenue: float, *, eps: float, start: str, end: str, filed: str) -> dict:
    return {"fiscal_year": year, "fiscal_period": fp, "period_start": start, "period_end": end, "filed_at": filed,
            "metrics": {"revenue": revenue, "gross_profit": revenue * .4, "operating_income": revenue * .2,
                        "net_income": revenue * .15, "eps_diluted": eps, "operating_cash_flow": revenue * .25,
                        "capex": revenue * .05, "shares_diluted": 100}}


def test_financial_and_valuation_formulas_are_canonical() -> None:
    rows = [
        period(2026, "Q1", 120, eps=1.2, start="2026-01-01", end="2026-03-31", filed="2026-05-01"),
        period(2025, "Q1", 100, eps=1.0, start="2025-01-01", end="2025-03-31", filed="2025-05-01"),
    ]
    result = financial_metrics(rows)
    assert round(result["revenue_growth_yoy"], 6) == .2
    assert result["gross_margin"] == .4
    assert result["operating_margin"] == .2
    assert result["net_margin"] == .15
    assert result["free_cash_flow"] == 24
    assert result["fcf_margin"] == .2
    valuation = valuation_metrics(20, result)
    assert valuation["market_cap"] == 2000


def test_historical_valuation_never_uses_future_filing() -> None:
    rows = [period(2025, "FY", 100, eps=2, start="2025-01-01", end="2025-12-31", filed="2026-02-15")]
    history = historical_valuation(
        [{"date": "2026-02-01", "close": 20}, {"date": "2026-03-01", "close": 30}], rows, "pe_ttm",
    )
    assert [sample["date"] for sample in history["samples"]] == ["2026-03-01"]
    assert history["samples"][0]["value"] == 15
    assert history["methodology"]["point_in_time"] is True


def test_technical_output_is_deterministic() -> None:
    prices = [{"date": f"2026-01-{index + 1:02d}", "close": 100 + index} for index in range(28)]
    result = technical_metrics(prices)
    assert result["rsi_14"] == 100
    assert result["moving_averages"]["sma_50"] is None
    assert result["support_resistance"]["method"].startswith("10th/25th")


def test_inline_xbrl_preserves_context_dimensions_and_units() -> None:
    html = """
    <xbrli:context id="c1"><xbrli:period><xbrli:startDate>2025-01-01</xbrli:startDate>
    <xbrli:endDate>2025-12-31</xbrli:endDate></xbrli:period><xbrli:scenario>
    <xbrldi:explicitMember dimension="us-gaap:ProductOrServiceAxis">aapl:IPhoneMember</xbrldi:explicitMember>
    </xbrli:scenario></xbrli:context><xbrli:unit id="USD"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>
    <ix:nonFraction name="us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax" contextRef="c1" unitRef="USD" scale="6">12,345</ix:nonFraction>
    """
    fact = parse_inline_xbrl(html)[0]
    assert fact["period_start"] == "2025-01-01"
    assert fact["period_end"] == "2025-12-31"
    assert fact["dimensions"] == {"us-gaap:ProductOrServiceAxis": "aapl:IPhoneMember"}
    assert fact["unit"] == "iso4217:USD"
    assert fact["value"] == 12_345_000_000


def test_section_status_shape_is_registry_driven() -> None:
    statuses = section_statuses({"header.ticker": {"value": "AAPL"}})
    assert statuses["header"]["status"] == "PARTIAL"
    assert statuses["header"]["coverage"] > 0
    assert "available_fields" in statuses["header"]
    assert "plan_gated_fields" in statuses["valuation"]


def test_ask_company_analysis_embeds_exact_shared_research_model() -> None:
    stored = {
        "securities": [{"ticker": "ACME", "asset_type": "stock", "company_name": "Acme", "sector": "Tech", "industry": "Software"}],
        "security_master": [], "source_observations": [], "filing_facts": [], "filing_documents": [], "fundamental_observations": [], "news": [],
        "fundamentals": [period(2026, "Q1", 120, eps=1.2, start="2026-01-01", end="2026-03-31", filed="2026-05-01"),
                         period(2025, "Q1", 100, eps=1.0, start="2025-01-01", end="2025-03-31", filed="2025-05-01")],
        "prices": [{"ticker": "ACME", "date": f"2026-01-{index + 1:02d}", "close": 100 + index, "provider": "test"} for index in range(28)],
    }
    for row in stored["fundamentals"]:
        row["ticker"] = "ACME"
    direct = build_shared_research_model("ACME", bundle=stored)
    ask = build_company_analysis("ACME", stored, {"ticker": "ACME", "company": "Acme"})
    revenue = direct["fields"]["financial.revenue_growth_yoy"]
    assert revenue["status"] == "AVAILABLE"
    assert revenue["provider"] == "EagleEyes"
    assert revenue["input_evidence"][0]["provider"] == "SEC"
    assert revenue["formula"].startswith("Revenue[current]")
    assert revenue["freshness_policy"]
    assert direct["fields"]["valuation.forward_pe"]["status"] == "PLAN_GATED"
    assert direct["fields"]["valuation.forward_pe"]["evidence_type"] == "FORECAST"
    assert ask.research_capabilities["version"] == direct["version"]
    assert ask.research_capabilities["fields"] == direct["fields"]


def test_improving_requires_margin_and_cash_flow_evidence() -> None:
    stored = {
        "securities": [{"ticker": "ACME", "asset_type": "stock", "company_name": "Acme", "sector": "Tech", "industry": "Software"}],
        "security_master": [], "source_observations": [], "filing_facts": [], "filing_documents": [], "fundamental_observations": [], "news": [],
        "fundamentals": [
            {"ticker": "ACME", "fiscal_year": 2026, "fiscal_period": "Q1", "period_start": "2026-01-01", "period_end": "2026-03-31", "filed_at": "2026-05-01", "metrics": {"revenue": 120}},
            {"ticker": "ACME", "fiscal_year": 2025, "fiscal_period": "Q1", "period_start": "2025-01-01", "period_end": "2025-03-31", "filed_at": "2025-05-01", "metrics": {"revenue": 100}},
        ],
        "prices": [{"ticker": "ACME", "date": "2026-08-01", "close": 100, "provider": "test"}],
    }
    field = build_shared_research_model("ACME", bundle=stored)["fields"]["summary.improving"]
    assert field["value"] is None
    assert field["status"] == "INSUFFICIENT_EVIDENCE"


def test_bank_does_not_receive_operating_company_financial_conclusions() -> None:
    stored = {
        "securities": [{"ticker": "BANK", "asset_type": "stock", "company_name": "Bank", "sector": "Financials", "industry": "Banks - Diversified"}],
        "security_master": [], "source_observations": [], "filing_facts": [], "filing_documents": [], "fundamental_observations": [], "news": [],
        "fundamentals": [period(2026, "Q1", 120, eps=1.2, start="2026-01-01", end="2026-03-31", filed="2026-05-01")],
        "prices": [{"ticker": "BANK", "date": "2026-08-01", "close": 100, "provider": "test"}],
    }
    stored["fundamentals"][0]["ticker"] = "BANK"
    result = build_shared_research_model("BANK", bundle=stored)
    assert result["identity"]["business_type"] == "BANK"
    assert result["fields"]["financial.gross_margin"]["status"] == "NOT_APPLICABLE"
    assert result["fields"]["summary.improving"]["status"] == "NOT_APPLICABLE"


def test_fair_value_uses_current_ttm_eps_and_weak_peer_samples_are_rejected() -> None:
    history = {"current_percentile": .5, "samples": [{"value": 10 + index} for index in range(24)]}
    output = _model_outputs({"ttm": {"eps_diluted": 5}, "revenue_growth_yoy": .1, "net_cash_debt": 1, "free_cash_flow": 1},
                            {}, history, {"customers": []}, [], 999, as_of="2026-08-01")
    ordered = sorted(item["value"] for item in history["samples"])
    assert output["fair_value"]["value"]["base"] == ordered[int(.5 * 23)] * 5
    medians, quality = _quality_peer_medians([{"ticker": "A", "pe_ttm": 212}, {"ticker": "B", "pe_ttm": 240}, {"ticker": "C", "pe_ttm": 180}])
    assert medians["pe_ttm"] is None
    assert quality["pe_ttm"]["status"] == "INSUFFICIENT_EVIDENCE"


def test_staleness_does_not_turn_full_coverage_into_partial_coverage() -> None:
    fields = {item.key: {"value": 1, "as_of": "2020-01-01", "status": "AVAILABLE"} for item in __import__("backend.research_metric_registry", fromlist=["REGISTRY"]).REGISTRY}
    status = section_statuses(fields)["market_data"]
    assert status["status"] == "SUCCESS"
    assert status["coverage"] == 1
    assert status["freshness_status"] == "STALE"


def test_dimensional_distribution_removes_parent_child_overlap_or_suppresses() -> None:
    def fact(member: str | None, value: float) -> dict:
        return {"ticker": "AAPL", "concept": "RevenueFromContractWithCustomerExcludingAssessedTax",
                "accession_number": "acc", "period_start": "2026-01-01", "period_end": "2026-03-31",
                "value": value, "dimensions": ({"us-gaap:ProductOrServiceAxis": f"aapl:{member}Member"} if member else {}),
                "context_id": member or "total", "source_url": "https://sec.example/acc"}
    coherent = _dimensional_overview({"filing_facts": [fact(None, 100), fact("Product", 70), fact("IPhone", 50), fact("Mac", 20), fact("Services", 30)]}, "AAPL")
    assert [row["name"] for row in coherent["segments"]] == ["IPhone", "Services", "Mac"]
    assert round(sum(row["revenue_share"] for row in coherent["segments"]), 6) == 1
    overlapping = _dimensional_overview({"filing_facts": [fact(None, 100), fact("DataCenter", 90), fact("ComputeAndNetworking", 85), fact("Hyperscale", 50)]}, "AAPL")
    assert overlapping["segments"] == []
    assert overlapping["segments_methodology"]["status"] == "INSUFFICIENT_EVIDENCE"

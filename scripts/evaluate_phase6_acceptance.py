#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import database, phase6_domains  # noqa: E402
from backend.analytical_contract import AnalysisResult, AnalysisStatus  # noqa: E402


USER = "phase6-acceptance"
NOW = datetime.now(timezone.utc)


def _company(ticker: str, score: float) -> None:
    prices = [{"ticker": ticker, "date": (NOW - timedelta(days=260-index)).isoformat(),
               "close": 100 + index, "provider": "acceptance"} for index in range(261)]
    fundamentals = [
        {"ticker": ticker, "period_end": f"{year}-06-30", "fiscal_period": "Q2", "fiscal_year": year,
         "metrics": {"revenue": revenue, "net_income": revenue * .2, "free_cash_flow": revenue * .16,
                     "total_assets": revenue * 2.5, "total_debt": revenue * .5, "eps_diluted": revenue / 45},
         "provider": "SEC"}
        for year, revenue in ((2024, 90), (2025, 100), (2026, 120))
    ]
    stored = {"securities": [{"ticker": ticker, "company_name": ticker, "asset_type": "equity",
                               "sector": "Technology", "industry": "Software", "updated_at": NOW.isoformat()}],
              "fundamentals": fundamentals, "prices": prices,
              "news": [{"ticker": ticker, "published_at": NOW.isoformat(), "title": "Stored update",
                        "metadata": {"sentiment_score": .2}, "provider": "stored"}], "company_markets": []}
    research = {"ticker": ticker, "company": ticker, "sector": "Technology", "industry": "Software",
                "price": 360, "price_as_of": NOW.isoformat(), "price_change_1y": .35,
                "fundamentals_as_of": "2026-06-30", "revenue_growth": .2, "net_margin": .2,
                "final_score": score, "growth_rating": 80, "fundamental_score": 82, "valuation_score": 55,
                "industry_score": 75, "technical_score": 72, "news_score": 60,
                "valuation_evidence": {"score": 55, "method": "stored multiples"},
                "market_statistics": {"return_1m": .04, "return_3m": .12, "return_1y": .35, "rsi_14": 58},
                "fundamental_statistics": {"revenue": 120, "net_income": 24, "free_cash_flow": 19.2,
                                           "total_assets": 300, "total_debt": 60, "debt_to_assets": .2},
                "news_sentiment": {"label": "positive", "article_count": 1}, "latest_news": stored["news"][0]}
    phase6_domains.materialize_company(USER, ticker, stored=stored, research_row=research)


def _macro_rows() -> list[dict]:
    values = {"FEDFUNDS": (5.25, 5.0), "DGS10": (4.4, 4.1), "T10Y2Y": (-.2, .1),
              "CPIAUCSL": (310, 311), "PCEPI": (124, 124.3), "INDPRO": (102, 101),
              "RSAFS": (700, 705), "PCE": (19000, 19100), "UNRATE": (4.1, 4.4),
              "PAYEMS": (160000, 160080), "ICSA": (220, 230), "BAMLH0A0HYM2": (3.5, 4.1)}
    return [{"series_id": series, "date": (NOW - timedelta(days=30-index * 30)).isoformat(),
             "value": value, "provider": "FRED"}
            for series, pair in values.items() for index, value in enumerate(pair)]


def _market_rows() -> list[dict]:
    return [{"ticker": ticker, "date": (NOW - timedelta(days=90-index)).isoformat(),
             "close": 100 + index * (1 + offset / 40), "provider": "stored"}
            for offset, ticker in enumerate((*phase6_domains.MARKET_INDEXES, *phase6_domains.MARKET_SECTORS))
            for index in range(90)]


def _prediction(holdings: list[dict], portfolio_id: str) -> dict:
    intelligence = {"markets": [{"provider": "Polymarket", "market_id": "ai-reg", "event_key": "ai-reg",
                                  "title": "Will AI regulation pass?", "category": "POLICY",
                                  "probability": {"source_type": "MARKET_IMPLIED", "probability": .62,
                                                  "as_of": NOW.isoformat(), "source": "Polymarket"},
                                  "quality": {"level": "HIGH"},
                                  "change": {"previous_probability": .54, "percentage_point_change": 8.0},
                                  "affected_holdings": ["MSFT"], "linked_companies": ["MSFT"]}],
                    "disagreements": []}
    phase6_domains.materialize_prediction_markets(USER, portfolio_id=portfolio_id, intelligence=intelligence, holdings=holdings)
    return intelligence


def seed(db_path: Path) -> tuple[list[dict], str]:
    database.DATABASE_URL = None
    database.DB_PATH = db_path
    database.initialize()
    holdings = [{"ticker": "MSFT", "weight": .23}, {"ticker": "AMZN", "weight": .77}]
    portfolio = database.save_portfolio("Acceptance", holdings, user_id=USER)
    portfolio_id = str(portfolio["id"])
    _company("MSFT", 78)
    _company("AMZN", 72)
    phase6_domains.materialize_macro(USER, rows=_macro_rows(), regime_rows=[{"dominant_regime": "mixed", "model_version": "v1"}])
    phase6_domains.materialize_market(USER, rows=_market_rows())
    _prediction(holdings, portfolio_id)
    # A second comparable company snapshot starts future score-attribution history.
    _company("MSFT", 82)
    return holdings, portfolio_id


def _record(question: str, capability: str, producer, renderer=None) -> dict:
    started = time.perf_counter()
    result = producer()
    latency_ms = (time.perf_counter() - started) * 1000
    if isinstance(result, AnalysisResult):
        canonical = result
        deterministic = renderer(result.data) if renderer and result.data else (result.limitations[0] if result.limitations else result.status.value)
        dependencies = [row.name for row in result.dependencies]
        coverage = result.coverage.model_dump(mode="json")
        freshness = result.freshness.model_dump(mode="json")
        status = result.status.value
    else:
        deterministic = renderer(result) if renderer else str(result.status)
        dependencies = [result.domain]
        coverage = {"baseline": result.baseline.model_dump(mode="json")}
        freshness = {"baseline_at": result.baseline.timestamp}
        status = "SUCCESS" if result.status not in {phase6_domains.HistoricalStatus.NO_BASELINE,
                                                    phase6_domains.HistoricalStatus.INCOMPATIBLE_BASELINE} else "UNAVAILABLE"
    return {"question": question, "capability": capability, "dependencies": dependencies, "status": status,
            "coverage": coverage, "freshness": freshness, "latency_ms": round(latency_ms, 3),
            "deterministic_answer": deterministic, "quality_verdict": "PASS" if deterministic else "FAIL"}


def evaluate(db_path: Path) -> list[dict]:
    holdings, portfolio_id = seed(db_path)
    company = lambda ticker: lambda: phase6_domains.company_analysis_result(USER, ticker)
    comparison = lambda: phase6_domains.company_comparison_result(USER, ["MSFT", "AMZN"], holdings)
    macro = lambda: phase6_domains.macro_state_result(USER)
    market = lambda: phase6_domains.market_state_result(USER)
    prediction = lambda: phase6_domains.prediction_market_result(USER, portfolio_id)
    questions = [
        ("How is MSFT doing?", "COMPANY_ANALYSIS", company("MSFT"), lambda data: phase6_domains.render_company(phase6_domains.CompanyAnalysisResult.model_validate(data))),
        ("Is MSFT expensive?", "COMPANY_ANALYSIS", company("MSFT"), lambda data: phase6_domains.render_company(phase6_domains.CompanyAnalysisResult.model_validate(data))),
        ("How are Microsoft's fundamentals trending?", "COMPANY_ANALYSIS", company("MSFT"), lambda data: phase6_domains.render_company(phase6_domains.CompanyAnalysisResult.model_validate(data))),
        ("How is AMZN doing?", "COMPANY_ANALYSIS", company("AMZN"), lambda data: phase6_domains.render_company(phase6_domains.CompanyAnalysisResult.model_validate(data))),
        ("Compare MSFT and Amazon.", "COMPANY_COMPARISON", comparison, lambda data: phase6_domains.render_comparison(phase6_domains.CompanyComparisonResult.model_validate(data))),
        ("Which company has stronger profitability?", "COMPANY_COMPARISON", comparison, lambda data: phase6_domains.render_comparison(phase6_domains.CompanyComparisonResult.model_validate(data))),
        ("What is the macro environment?", "MACRO_STATE", macro, lambda data: phase6_domains.render_macro(phase6_domains.MacroStateResult.model_validate(data))),
        ("Are recession risks rising?", "MACRO_STATE", macro, lambda data: phase6_domains.render_macro(phase6_domains.MacroStateResult.model_validate(data))),
        ("What changed in rates and inflation?", "MACRO_STATE", macro, lambda data: phase6_domains.render_macro(phase6_domains.MacroStateResult.model_validate(data))),
        ("What kind of market are we in?", "MARKET_STATE", market, lambda data: phase6_domains.render_market(phase6_domains.MarketStateResult.model_validate(data))),
        ("Is the market risk-on or risk-off?", "MARKET_STATE", market, lambda data: phase6_domains.render_market(phase6_domains.MarketStateResult.model_validate(data))),
        ("Which sectors are leading?", "MARKET_STATE", market, lambda data: phase6_domains.render_market(phase6_domains.MarketStateResult.model_validate(data))),
        ("What prediction markets matter most?", "PREDICTION_MARKETS", prediction, lambda data: phase6_domains.render_prediction(phase6_domains.PredictionMarketResult.model_validate(data))),
        ("Which probabilities changed materially?", "PREDICTION_MARKETS", prediction, lambda data: phase6_domains.render_prediction(phase6_domains.PredictionMarketResult.model_validate(data))),
        ("What prediction-market risks matter to my portfolio?", "PREDICTION_MARKETS_PORTFOLIO", prediction, lambda data: phase6_domains.render_prediction(phase6_domains.PredictionMarketResult.model_validate(data))),
        ("What macro factors matter to my portfolio?", "MACRO_PORTFOLIO", macro, lambda data: phase6_domains.render_macro(phase6_domains.MacroStateResult.model_validate(data))),
        ("How well positioned is my portfolio for this market?", "MARKET_PORTFOLIO", market, lambda data: phase6_domains.render_market(phase6_domains.MarketStateResult.model_validate(data))),
        ("Why did MSFT's score change?", "HISTORICAL_CHANGE", lambda: phase6_domains.historical_comparison(USER, "company_analysis", "company:MSFT"), None),
        ("What changed for AMZN since I last looked?", "HISTORICAL_CHANGE", lambda: phase6_domains.historical_comparison(USER, "company_analysis", "company:AMZN", selection="last_review"), None),
        ("What changed in macro since last month?", "HISTORICAL_CHANGE", lambda: phase6_domains.historical_comparison(USER, "macro_state", "global:macro_state", selection="one_month_ago", baseline_at=NOW-timedelta(days=30)), None),
    ]
    return [_record(*row) for row in questions]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="eagleeyes-phase6-") as directory:
        records = evaluate(Path(directory) / "acceptance.db")
    payload = {"generated_at": datetime.now(timezone.utc).isoformat(), "question_count": len(records),
               "pass_count": sum(row["quality_verdict"] == "PASS" for row in records), "records": records,
               "note": "Synthetic local acceptance evidence; not a production SLO or live-provider evaluation."}
    target = ROOT / "artifacts" / "phase6-acceptance.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, default=str) + "\n")
    print(json.dumps({"artifact": str(target), "questions": len(records), "passed": payload["pass_count"]}, indent=2))
    return 0 if payload["pass_count"] == len(records) else 1


if __name__ == "__main__":
    raise SystemExit(main())

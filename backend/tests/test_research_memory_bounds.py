from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

from backend import database, main
from backend.auth import AuthenticatedUser
from backend.research_read_model import build_shared_research_model


def test_research_payload_projections_are_bounded_and_nonduplicative() -> None:
    fields = {
        "header.ticker": {"value": "AAPL"},
        "summary.cheap": {"value": "Fair"},
        "financial.revenue_growth": {"value": 0.1},
        "valuation.pe": {"value": 25},
        "earnings.surprise.eps": {"value": [0.02]},
        "thesis.bull.statement": {"value": ["Growth"]},
        "portfolio.correlation": {"value": 0.4},
    }
    model = {"ticker": "AAPL", "version": "v1", "generated_at": "now", "status": "PARTIAL",
             "coverage": 0.75, "fields": fields, "sections": {key: {"status": "PARTIAL"}
             for key in ("header", "summary", "financial_health", "valuation", "earnings", "thesis", "portfolio_relevance")}}
    header = main._research_header_projection(model)
    core = main._research_core_projection(model)
    thesis = main._project_research_model(model, ("thesis",), main._RESEARCH_SECTION_PREFIXES["thesis"])
    assert set(header["fields"]) == {"header.ticker", "summary.cheap"}
    assert set(core["fields"]) == {"financial.revenue_growth", "valuation.pe", "earnings.surprise.eps"}
    assert set(thesis["fields"]) == {"thesis.bull.statement"}
    assert not (set(header["fields"]) & set(core["fields"]))
    assert "portfolio.correlation" not in core["fields"]


def test_research_header_projection_bounds_visible_price_history() -> None:
    history = [{"date": f"day-{index}", "close": index} for index in range(800)]
    model = {"ticker": "AAPL", "version": "v1", "generated_at": "now", "status": "SUCCESS",
             "coverage": 1.0, "fields": {"header.ticker": {"value": "AAPL"},
             "header.price_history": {"value": history, "provider": "stored"}},
             "sections": {"header": {"status": "SUCCESS"}}}
    projected = main._research_header_projection(model)
    visible = projected["fields"]["header.price_history"]["value"]
    assert len(visible) == 253
    assert visible[0] == {"date": history[-253]["date"], "close": history[-253]["close"]}
    assert len(model["fields"]["header.price_history"]["value"]) == 800


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


def test_research_core_database_path_is_role_bounded(monkeypatch) -> None:
    calls: list[tuple[list[str], int, bool, bool]] = []

    def fake_security_data(tickers, price_limit=756, *, include_news=True, include_company_markets=True):
        calls.append((list(tickers), price_limit, include_news, include_company_markets))
        return {
            "securities": [{"ticker": ticker, "asset_type": "stock", "sector": "Tech", "industry": "Hardware"} for ticker in tickers],
            "fundamentals": [{"ticker": ticker, "period_end": "2026-06-30", "metrics": {}} for ticker in tickers],
            "prices": [{"ticker": ticker, "date": "2026-08-28", "close": 100} for ticker in tickers],
            "news": [{"ticker": tickers[0], "title": "news"}] if include_news and tickers else [],
            "company_markets": [],
        }

    class FakeConnection:
        def execute(self, query, params=()):
            sql = " ".join(str(query).split())
            if "to_regclass" in sql:
                return _Rows([{"source_table": "research_source_observations", "fact_table": "fundamental_dimensional_facts"}])
            if "FROM public.security_master" in sql:
                return _Rows([{"ticker": ticker} for ticker in params[0]])
            if "FROM public.research_source_observations" in sql:
                assert params[0] == "AAPL"
                assert params[1] == ["P1", "P2", "P3", "P4"]
                return _Rows([])
            if "WITH recent_filings" in sql:
                assert params[1] == database.RESEARCH_CORE_MAX_FILINGS
                assert set(params[3]) == set(database.RESEARCH_CORE_XBRL_CONCEPTS)
                return _Rows([{"ticker": "AAPL", "concept": "GrossProfit", "filed_at": "2026-08-01",
                               "period_end": "2026-06-30", "id": 1, "value": 1, "dimensions": {}}])
            if "FROM public.documents" in sql:
                assert params[1] == database.RESEARCH_CORE_MAX_DOCUMENTS
                return _Rows([{"ticker": "AAPL", "document_type": "risk_factor", "content": "bounded"}])
            raise AssertionError(sql)

    @contextmanager
    def fake_connection():
        yield FakeConnection()

    monkeypatch.setattr(database, "DATABASE_URL", "postgresql://test")
    monkeypatch.setattr(database, "security_data", fake_security_data)
    monkeypatch.setattr(database, "postgres_connection", fake_connection)
    bundle = database.research_core_data("AAPL", peer_tickers=["P1", "P2", "P3", "P4", "P5"])

    assert calls == [
        (["AAPL"], 1260, True, False),
        (["P1", "P2", "P3", "P4"], 2, False, False),
        (["SPY", "QQQ", "XLK", "SOXX"], 756, False, False),
    ]
    assert bundle["fundamental_observations"] == []
    assert len(bundle["filing_facts"]) == 1
    assert bundle["_telemetry"]["paths"]["peers"]["ticker_count"] == 4


def test_core_read_model_does_not_echo_raw_document_content() -> None:
    bundle = {
        "securities": [{"ticker": "ACME", "asset_type": "stock", "company_name": "Acme", "sector": "Tech", "industry": "Hardware"}],
        "security_master": [], "source_observations": [], "filing_facts": [], "fundamental_observations": [], "news": [],
        "fundamentals": [], "prices": [{"ticker": "ACME", "date": "2026-08-28", "close": 100, "provider": "test"}],
        "filing_documents": [{"ticker": "ACME", "provider": "SEC", "document_type": "risk_factor", "external_id": "doc-1",
                              "title": "Risk", "source_url": "https://example.test/risk", "published_at": "2026-01-01",
                              "content": "x" * 50_000, "metadata": {"category": "Competition"}}],
    }
    result = build_shared_research_model("ACME", bundle=bundle)
    assert result["documents"] == [{"provider": "SEC", "document_type": "risk_factor", "external_id": "doc-1", "title": "Risk",
                                     "source_url": "https://example.test/risk", "published_at": "2026-01-01", "fetched_at": None}]
    assert "x" * 1000 not in str(result)


def test_research_core_cache_reuses_projection_and_serializes_heavy_builds(monkeypatch) -> None:
    main._RESEARCH_CORE_CACHE.clear()
    monkeypatch.setattr(main, "_RESEARCH_CORE_CACHE_MAX_ENTRIES", 3)
    active = 0
    maximum_active = 0
    calls = 0
    lock = threading.Lock()

    monkeypatch.setattr(main.database, "research_peer_tickers", lambda *_args: ["P1", "P2"])
    monkeypatch.setattr(main.database, "research_core_input_version", lambda ticker, _peers: f"v1:{ticker}")

    def fake_bundle(ticker, **_kwargs):
        nonlocal active, maximum_active, calls
        with lock:
            calls += 1
            active += 1
            maximum_active = max(maximum_active, active)
        time.sleep(.03)
        with lock:
            active -= 1
        return {"_telemetry": {"row_counts": {}, "primary_ticker": ticker}}

    monkeypatch.setattr(main.database, "research_core_data", fake_bundle)
    monkeypatch.setattr(main, "build_shared_research_model", lambda ticker, bundle: {"ticker": ticker, "fields": {"header.ticker": {"value": ticker}}})

    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(lambda ticker: main._cached_research_core(ticker), ["AAPL", "MSFT", "AMZN"]))
    assert {result[0]["ticker"] for result in results} == {"AAPL", "MSFT", "AMZN"}
    assert maximum_active == 1
    assert calls == 3

    first, status = main._cached_research_core("AAPL")
    assert first["ticker"] == "AAPL"
    assert status == "hit"
    assert calls == 3


def test_research_core_cache_is_bounded(monkeypatch) -> None:
    main._RESEARCH_CORE_CACHE.clear()
    monkeypatch.setattr(main, "_RESEARCH_CORE_CACHE_MAX_ENTRIES", 2)
    monkeypatch.setattr(main.database, "research_peer_tickers", lambda *_args: [])
    monkeypatch.setattr(main.database, "research_core_input_version", lambda ticker, _peers: ticker)
    monkeypatch.setattr(main.database, "research_core_data", lambda ticker, **_kwargs: {"_telemetry": {"primary_ticker": ticker}})
    monkeypatch.setattr(main, "build_shared_research_model", lambda ticker, bundle: {"ticker": ticker})
    for ticker in ("AAPL", "MSFT", "AMZN"):
        main._cached_research_core(ticker)
    assert len(main._RESEARCH_CORE_CACHE) == 2


def test_core_only_section_bypasses_full_portfolio_overlay_and_reports_timing(monkeypatch) -> None:
    model = {
        "ticker": "AAPL", "version": "v1", "generated_at": "now", "status": "PARTIAL", "coverage": .5,
        "fields": {"overview.description": {"key": "overview.description", "value": "Company description"}},
        "sections": {"overview": {"status": "PARTIAL", "coverage": .5}},
    }
    monkeypatch.setattr(main, "_cached_research_core", lambda _ticker: (model, "hit"))
    monkeypatch.setattr(main, "_selected_research_portfolio", lambda *_args: (None, []))
    monkeypatch.setattr(main, "get_profile", lambda _user: {"watchlist": []})
    monkeypatch.setattr(
        main, "consolidated_research_security_overview",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("full overlay must not run")),
    )
    captured: list[tuple[str, float, dict]] = []
    monkeypatch.setattr(main, "record_metric", lambda name, value, tags: captured.append((name, value, tags)))

    result = main.research_security_section(
        "AAPL", "overview", portfolio_id=None,
        user=AuthenticatedUser("research-user", "research@example.com"),
    )

    assert result["timing"]["source_path"] == "core_projection"
    assert result["timing"]["cache_status"] == "hit"
    assert result["research_capabilities"]["fields"]["overview.description"]["value"] == "Company description"
    assert captured[0][0] == "research.section.latency"


def test_research_and_portfolio_overlay_share_only_research_semaphore(monkeypatch) -> None:
    main._RESEARCH_CORE_CACHE.clear()
    active = 0
    maximum_active = 0
    lock = threading.Lock()
    monkeypatch.setattr(main.database, "research_peer_tickers", lambda *_args: [])
    monkeypatch.setattr(main.database, "research_core_input_version", lambda ticker, _peers: ticker)
    monkeypatch.setattr(main.database, "research_core_data", lambda ticker, **_kwargs: {"_telemetry": {"primary_ticker": ticker}})

    def fake_builder(ticker, **_kwargs):
        nonlocal active, maximum_active
        with lock:
            active += 1
            maximum_active = max(maximum_active, active)
        time.sleep(.02)
        with lock:
            active -= 1
        return {"ticker": ticker}

    monkeypatch.setattr(main, "build_shared_research_model", fake_builder)
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [
            executor.submit(main._cached_research_core, "AAPL"),
            executor.submit(main._bounded_portfolio_research, "MSFT", {"holdings": [{"ticker": "MSFT"}]}),
            executor.submit(main._cached_research_core, "AMZN"),
        ]
        [future.result() for future in futures]
    assert maximum_active == 1


def test_normal_ask_work_is_not_blocked_by_research_single_flight(monkeypatch) -> None:
    main._RESEARCH_CORE_CACHE.clear()
    research_started = threading.Event()
    release_research = threading.Event()
    monkeypatch.setattr(main.database, "research_peer_tickers", lambda *_args: [])
    monkeypatch.setattr(main.database, "research_core_input_version", lambda ticker, _peers: ticker)
    monkeypatch.setattr(main.database, "research_core_data", lambda ticker, **_kwargs: {"_telemetry": {"primary_ticker": ticker}})

    def slow_research(ticker, **_kwargs):
        research_started.set()
        assert release_research.wait(timeout=1)
        return {"ticker": ticker}

    monkeypatch.setattr(main, "build_shared_research_model", slow_research)
    with ThreadPoolExecutor(max_workers=3) as executor:
        research = executor.submit(main._cached_research_core, "AAPL")
        assert research_started.wait(timeout=1)
        ask = executor.submit(lambda: {"answer": "bounded Ask response"})
        assert ask.result(timeout=.1)["answer"] == "bounded Ask response"
        second_research = executor.submit(main._cached_research_core, "MSFT")
        assert not second_research.done()
        release_research.set()
        research.result(timeout=1)
        second_research.result(timeout=1)


def test_full_research_overviews_are_serialized_without_blocking_other_work() -> None:
    active = 0
    maximum_active = 0
    lock = threading.Lock()

    @main._serialized_research_overview
    def slow_overview(ticker: str) -> str:
        nonlocal active, maximum_active
        with lock:
            active += 1
            maximum_active = max(maximum_active, active)
        time.sleep(.03)
        with lock:
            active -= 1
        return ticker

    with ThreadPoolExecutor(max_workers=3) as executor:
        first = executor.submit(slow_overview, "AAPL")
        second = executor.submit(slow_overview, "MSFT")
        unrelated = executor.submit(lambda: "ask-ready")
        assert unrelated.result(timeout=.1) == "ask-ready"
        assert {first.result(timeout=1), second.result(timeout=1)} == {"AAPL", "MSFT"}
    assert maximum_active == 1

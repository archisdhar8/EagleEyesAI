from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

from backend import database, main
from backend.research_read_model import build_shared_research_model


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

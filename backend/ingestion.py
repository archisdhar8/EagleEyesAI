from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import math
import os
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

import pandas as pd
import requests
from dotenv import load_dotenv

from . import database
from .regimes import generate_and_store_regimes, month_ends
from .scenarios import refresh as refresh_scenarios


APP_DIR = Path(__file__).resolve().parents[1]
CACHE_ROOT = APP_DIR / "data"
PRICE_CACHE = CACHE_ROOT / "raw" / "polygon" / "prices_daily.parquet"
FRED_CACHE = CACHE_ROOT / "raw" / "fred" / "fred_observations.parquet"
FUNDAMENTALS_CACHE = CACHE_ROOT / "processed" / "sec_fundamentals.parquet"
NEWS_CACHE = CACHE_ROOT / "raw" / "news" / "news_raw.parquet"
RANKINGS_CACHE = CACHE_ROOT / "outputs" / "stock_rankings.csv"

POLYGON_BARS_URL = "https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/day/{start}/{end}"
POLYGON_NEWS_URL = "https://api.polygon.io/v2/reference/news"
FRED_URL = "https://api.stlouisfed.org/fred/series/observations"
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

ETF_TICKERS = {
    "SPY", "QQQ", "VTI", "IWM", "DIA", "BND", "AGG", "TLT", "SHY", "IEF",
    "XLB", "XLC", "XLE", "XLF", "XLI", "XLK", "XLP", "XLRE", "XLU", "XLV", "XLY",
}
HISTORY_START = date(2005, 1, 1)
ALFRED_SERIES = {
    "CPIAUCSL": "eop",
    "UNRATE": "eop",
    "T10Y2Y": "eop",
    "BAMLH0A0HYM2": "eop",
    "FEDFUNDS": "eop",
    "DCOILWTICO": "avg",
    "INDPRO": "eop",
    "PAYEMS": "eop",
}
ALFRED_DAILY_SERIES = {"T10Y2Y", "BAMLH0A0HYM2", "DCOILWTICO"}
FRED_SERIES = [
    "DGS3MO", "DGS2", "DGS10", "DGS30", "T10Y2Y", "T10Y3M",
    "CPIAUCSL", "CPILFESL", "PCEPI", "PCEPILFE", "T5YIE", "T10YIE",
    "PCE", "RSAFS", "PSAVERT", "UMCSENT", "UNRATE", "PAYEMS", "ICSA", "JTSJOL",
    "TOTALSL", "BUSLOANS", "DRCCLACBS", "BAMLH0A0HYM2", "MORTGAGE30US",
    "FEDFUNDS", "SOFR", "WALCL", "M2SL", "RRPONTSYD", "DCOILWTICO", "INDPRO",
]
SEC_TAGS = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "eps_diluted": ["EarningsPerShareDiluted"],
    "total_assets": ["Assets"],
    "total_liabilities": ["Liabilities"],
    "shareholder_equity": ["StockholdersEquity"],
    "operating_cash_flow": ["NetCashProvidedByUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment"],
    "shares_diluted": ["WeightedAverageNumberOfDilutedSharesOutstanding"],
    "total_debt": ["LongTermDebt", "LongTermDebtAndFinanceLeaseObligations"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue"],
}


load_dotenv(APP_DIR / "backend" / ".env", override=False)


def raise_provider_error(response: requests.Response) -> None:
    """Raise a useful HTTP error without including credential-bearing request URLs."""
    if response.ok:
        return
    detail = response.reason or "provider request failed"
    try:
        payload = response.json()
        detail = payload.get("error_message") or payload.get("error") or detail
    except (ValueError, AttributeError):
        pass
    raise RuntimeError(f"Provider HTTP {response.status_code}: {str(detail)[:500]}")


def request_with_retries(
    session: requests.Session, url: str, *, params: dict[str, Any], timeout: int = 30,
    attempts: int = 6,
) -> requests.Response:
    response: requests.Response | None = None
    for attempt in range(attempts):
        try:
            response = session.get(url, params=params, timeout=timeout)
        except requests.RequestException as exc:
            if attempt + 1 < attempts:
                time.sleep(min(30, 2 ** attempt))
                continue
            raise RuntimeError(f"Provider network request failed: {type(exc).__name__}") from None
        if response.status_code not in {429, 500, 502, 503, 504}:
            raise_provider_error(response)
            return response
        if attempt + 1 < attempts:
            retry_after = response.headers.get("Retry-After")
            delay = float(retry_after) if retry_after and retry_after.isdigit() else min(30, 2 ** attempt)
            time.sleep(delay)
    assert response is not None
    raise_provider_error(response)
    return response


def clean(value: Any) -> Any:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def finite_metrics(row: Any, columns: Iterable[str]) -> dict[str, float]:
    output: dict[str, float] = {}
    for column in columns:
        value = clean(getattr(row, column, None))
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            output[column] = float(value)
    return output


def asset_type(ticker: str) -> str:
    return "etf" if ticker.upper() in ETF_TICKERS else "stock"


def record_fetch(
    provider: str,
    request_key: str,
    status: str,
    *,
    as_of: str | None = None,
    source_url: str | None = None,
    payload_hash: str | None = None,
    error_message: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    with database.postgres_connection() as conn:
        conn.execute(
            """INSERT INTO public.provider_fetches(
            provider, request_key, status, as_of, source_url, payload_hash, error_message, metadata
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                provider, request_key, status, as_of, source_url, payload_hash,
                error_message, database._jsonb(metadata or {}),
            ),
        )


def run_recorded(provider: str, request_key: str, operation: Callable[[], int]) -> int:
    try:
        rows = operation()
        record_fetch(provider, request_key, "success", as_of=database.utc_now(), metadata={"rows": rows})
        print(f"{provider}: {rows} rows")
        return rows
    except Exception as exc:
        record_fetch(provider, request_key, "failed", error_message=f"{type(exc).__name__}: {exc}"[:1000])
        raise


def ranking_metadata() -> dict[str, dict[str, Any]]:
    if not RANKINGS_CACHE.exists():
        return {}
    frame = pd.read_csv(RANKINGS_CACHE)
    return {
        str(row.ticker).upper(): {
            "company_name": clean(getattr(row, "company_name", None)),
            "sector": clean(getattr(row, "sector", None)),
            "industry": clean(getattr(row, "industry", None)),
        }
        for row in frame.itertuples(index=False)
    }


def upsert_securities(conn: Any, tickers: Iterable[str]) -> None:
    metadata = ranking_metadata()
    values = []
    for ticker in sorted({str(item).strip().upper() for item in tickers if str(item).strip()}):
        details = metadata.get(ticker, {})
        values.append(
            (
                ticker, asset_type(ticker), details.get("company_name"),
                details.get("sector"), details.get("industry"),
            )
        )
    if not values:
        return
    with conn.cursor() as cursor:
        cursor.executemany(
            """INSERT INTO public.securities(ticker, asset_type, company_name, sector, industry)
            VALUES (%s,%s,%s,%s,%s)
            ON CONFLICT (ticker, asset_type) DO UPDATE SET
            company_name=coalesce(excluded.company_name, public.securities.company_name),
            sector=coalesce(excluded.sector, public.securities.sector),
            industry=coalesce(excluded.industry, public.securities.industry),
            active=true""",
            values,
        )


def copy_rows(conn: Any, sql: str, rows: Iterable[tuple[Any, ...]], progress_label: str) -> int:
    count = 0
    with conn.cursor().copy(sql) as copy:
        for row in rows:
            copy.write_row(row)
            count += 1
            if count % 100_000 == 0:
                print(f"{progress_label}: staged {count}")
    return count


def upsert_price_frame(frame: pd.DataFrame, provider: str = "polygon") -> int:
    if frame.empty:
        return 0
    with database.postgres_connection() as conn:
        upsert_securities(conn, frame["ticker"].astype(str).unique())
        conn.execute(
            """CREATE TEMP TABLE price_stage(
            ticker text, asset_type text, bar_date date, open double precision,
            high double precision, low double precision, close double precision,
            volume double precision, vwap double precision, transactions bigint
            ) ON COMMIT DROP"""
        )
        rows = (
            (
                str(row.ticker).upper(), asset_type(str(row.ticker)), clean(row.date),
                clean(row.open), clean(row.high), clean(row.low), clean(row.close),
                clean(row.volume), clean(row.vwap), clean(row.transactions),
            )
            for row in frame.itertuples(index=False)
        )
        count = copy_rows(
            conn,
            "COPY price_stage(ticker,asset_type,bar_date,open,high,low,close,volume,vwap,transactions) FROM STDIN",
            rows,
            "prices",
        )
        conn.execute(
            """INSERT INTO public.price_bars(
            security_id, provider, interval, ts, open, high, low, close, volume, vwap, transactions
            ) SELECT s.id, %s, '1d', p.bar_date::timestamptz, p.open, p.high, p.low,
            p.close, p.volume, p.vwap, p.transactions
            FROM price_stage p JOIN public.securities s
              ON s.ticker=p.ticker AND s.asset_type=p.asset_type
            ON CONFLICT (security_id, provider, interval, ts) DO UPDATE SET
            open=excluded.open, high=excluded.high, low=excluded.low, close=excluded.close,
            volume=excluded.volume, vwap=excluded.vwap, transactions=excluded.transactions,
            fetched_at=now()""",
            (provider,),
        )
    return count


def backfill_polygon() -> int:
    if not PRICE_CACHE.exists():
        raise FileNotFoundError(PRICE_CACHE)
    return upsert_price_frame(pd.read_parquet(PRICE_CACHE), "polygon")


def backfill_fred() -> int:
    if not FRED_CACHE.exists():
        raise FileNotFoundError(FRED_CACHE)
    frame = pd.read_parquet(FRED_CACHE)
    vintage = datetime.fromtimestamp(FRED_CACHE.stat().st_mtime, timezone.utc).date()
    with database.postgres_connection() as conn:
        conn.execute(
            """CREATE TEMP TABLE fred_stage(
            observation_date date, series_id text, value double precision
            ) ON COMMIT DROP"""
        )
        count = copy_rows(
            conn,
            "COPY fred_stage(observation_date,series_id,value) FROM STDIN",
            ((clean(row.date), str(row.series_id), clean(row.value)) for row in frame.itertuples(index=False)),
            "fred",
        )
        conn.execute(
            """INSERT INTO public.macro_observations(
            provider, series_id, observation_date, vintage_date, value, source_url,
            is_point_in_time, metadata
            ) SELECT 'FRED_CACHE', series_id, observation_date, %s, value,
            'https://fred.stlouisfed.org/', false,
            '{"warning":"Legacy cache is latest-known data, not a historical vintage"}'::jsonb
            FROM fred_stage
            ON CONFLICT (provider, series_id, observation_date, vintage_date) DO UPDATE SET
            value=excluded.value, fetched_at=now(), metadata=excluded.metadata""",
            (vintage,),
        )
    return count


FUNDAMENTAL_METRICS = [
    "revenue", "gross_profit", "operating_income", "ebitda", "net_income", "eps_diluted",
    "total_assets", "total_liabilities", "total_debt", "cash", "shareholder_equity",
    "operating_cash_flow", "capex", "free_cash_flow", "shares_diluted",
]


def backfill_fundamentals() -> int:
    if not FUNDAMENTALS_CACHE.exists():
        raise FileNotFoundError(FUNDAMENTALS_CACHE)
    frame = pd.read_parquet(FUNDAMENTALS_CACHE)
    with database.postgres_connection() as conn:
        upsert_securities(conn, frame["ticker"].astype(str).unique())
        conn.execute(
            """CREATE TEMP TABLE fundamental_stage(
            ticker text, asset_type text, period_end date, fiscal_period text,
            fiscal_year integer, metrics_text text, data_quality_score double precision
            ) ON COMMIT DROP"""
        )
        rows = (
            (
                str(row.ticker).upper(), asset_type(str(row.ticker)), clean(row.date),
                clean(row.fiscal_period), clean(row.fiscal_year),
                json.dumps(finite_metrics(row, FUNDAMENTAL_METRICS), separators=(",", ":")),
                clean(row.data_quality_score),
            )
            for row in frame.itertuples(index=False)
        )
        count = copy_rows(
            conn,
            "COPY fundamental_stage(ticker,asset_type,period_end,fiscal_period,fiscal_year,metrics_text,data_quality_score) FROM STDIN",
            rows,
            "fundamentals",
        )
        conn.execute(
            """INSERT INTO public.fundamental_periods(
            security_id, provider, period_end, fiscal_period, fiscal_year, metrics,
            data_quality_score, source_url
            ) SELECT s.id, 'sec_edgar_companyfacts', f.period_end, f.fiscal_period,
            f.fiscal_year, f.metrics_text::jsonb, f.data_quality_score,
            'https://data.sec.gov/submissions/'
            FROM fundamental_stage f JOIN public.securities s
              ON s.ticker=f.ticker AND s.asset_type=f.asset_type
            ON CONFLICT (security_id, provider, period_end, fiscal_period, fiscal_year)
            DO UPDATE SET metrics=excluded.metrics, data_quality_score=excluded.data_quality_score,
            fetched_at=now()"""
        )
    return count


def article_id(row: Any) -> str:
    identity = str(clean(getattr(row, "url", None)) or "|").strip()
    if identity == "|":
        identity = "|".join(
            str(clean(getattr(row, field, None)) or "")
            for field in ("source", "headline", "published_at")
        )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def upsert_news_frame(frame: pd.DataFrame, provider: str = "polygon_news") -> int:
    if frame.empty:
        return 0
    if "is_real_data" in frame:
        frame = frame[frame["is_real_data"].fillna(False)].copy()
    if frame.empty:
        return 0
    with database.postgres_connection() as conn:
        upsert_securities(conn, frame["ticker"].astype(str).unique())
        conn.execute(
            """CREATE TEMP TABLE news_stage(
            external_id text, ticker text, asset_type text, title text, source_url text,
            published_at timestamptz, content_hash text, metadata_text text,
            relevance_score double precision
            ) ON COMMIT DROP"""
        )
        rows = []
        for row in frame.itertuples(index=False):
            external_id = article_id(row)
            metadata = {
                key: clean(getattr(row, key, None))
                for key in (
                    "source", "summary", "event_type", "sentiment_label", "sentiment_score",
                    "catalyst_type", "risk_type", "management_tone", "regulatory_risk",
                    "legal_risk", "news_data_quality_score",
                )
            }
            rows.append(
                (
                    external_id, str(row.ticker).upper(), asset_type(str(row.ticker)),
                    str(clean(row.headline) or "Untitled news item"), clean(row.url),
                    clean(row.published_at), external_id, json.dumps(metadata, default=str),
                    clean(getattr(row, "relevance_score", None)),
                )
            )
        count = copy_rows(
            conn,
            "COPY news_stage(external_id,ticker,asset_type,title,source_url,published_at,content_hash,metadata_text,relevance_score) FROM STDIN",
            rows,
            "news",
        )
        conn.execute(
            """INSERT INTO public.documents(
            provider, document_type, external_id, title, source_url, published_at,
            content_hash, metadata
            ) SELECT %s, 'news', external_id, max(title), max(source_url),
            max(published_at), max(content_hash), max(metadata_text)::jsonb
            FROM news_stage GROUP BY external_id
            ON CONFLICT (provider, external_id) DO UPDATE SET
            title=excluded.title, source_url=excluded.source_url,
            published_at=excluded.published_at, metadata=excluded.metadata, fetched_at=now()""",
            (provider,),
        )
        conn.execute(
            """INSERT INTO public.document_securities(document_id, security_id, relevance_score)
            SELECT d.id, s.id, max(n.relevance_score)
            FROM news_stage n
            JOIN public.documents d ON d.provider=%s AND d.external_id=n.external_id
            JOIN public.securities s ON s.ticker=n.ticker AND s.asset_type=n.asset_type
            GROUP BY d.id, s.id
            ON CONFLICT (document_id, security_id) DO UPDATE SET
            relevance_score=excluded.relevance_score""",
            (provider,),
        )
    return count


def backfill_news() -> int:
    if not NEWS_CACHE.exists():
        raise FileNotFoundError(NEWS_CACHE)
    return upsert_news_frame(pd.read_parquet(NEWS_CACHE), "polygon_news")


def active_tickers() -> list[str]:
    with database.postgres_connection() as conn:
        rows = conn.execute(
            """SELECT ticker FROM public.holdings
            UNION SELECT unnest(watchlist) FROM public.investor_profiles"""
        ).fetchall()
    return sorted({str(row["ticker"]).upper() for row in rows} | {"SPY", "QQQ", "VTI", "BND"})


def refresh_polygon() -> int:
    api_key = os.getenv("POLYGON_API_KEY")
    if not api_key:
        raise RuntimeError("POLYGON_API_KEY is required")
    tickers = active_tickers()
    frames: list[pd.DataFrame] = []
    today = datetime.now(timezone.utc).date()
    with database.postgres_connection() as conn:
        latest_rows = conn.execute(
            """SELECT s.ticker, max(p.ts)::date AS latest
            FROM public.securities s LEFT JOIN public.price_bars p
              ON p.security_id=s.id AND p.provider='polygon'
            WHERE s.ticker = ANY(%s) GROUP BY s.ticker""",
            (tickers,),
        ).fetchall()
    latest = {row["ticker"]: row["latest"] for row in latest_rows}
    session = requests.Session()
    for ticker in tickers:
        start = (latest.get(ticker) + timedelta(days=1)) if latest.get(ticker) else today - timedelta(days=365 * 5)
        if start > today:
            continue
        response = session.get(
            POLYGON_BARS_URL.format(ticker=ticker, start=start.isoformat(), end=today.isoformat()),
            params={"adjusted": "true", "sort": "asc", "limit": 50000, "apiKey": api_key},
            timeout=30,
        )
        raise_provider_error(response)
        results = response.json().get("results", [])
        if not results:
            continue
        frames.append(
            pd.DataFrame(
                {
                    "ticker": ticker,
                    "date": [datetime.fromtimestamp(item["t"] / 1000, timezone.utc).date() for item in results],
                    "open": [item.get("o") for item in results], "high": [item.get("h") for item in results],
                    "low": [item.get("l") for item in results], "close": [item.get("c") for item in results],
                    "volume": [item.get("v") for item in results], "vwap": [item.get("vw") for item in results],
                    "transactions": [item.get("n") for item in results],
                }
            )
        )
    return upsert_price_frame(pd.concat(frames, ignore_index=True), "polygon") if frames else 0


def extend_polygon_history() -> int:
    api_key = os.getenv("POLYGON_API_KEY")
    if not api_key:
        raise RuntimeError("POLYGON_API_KEY is required")
    today = datetime.now(timezone.utc).date()
    tickers = sorted(set(active_tickers()) | ETF_TICKERS)
    session = requests.Session()
    frames: list[pd.DataFrame] = []
    skipped: list[str] = []
    clipped: list[str] = []
    for ticker in tickers:
        if ticker == "CASH":
            continue
        start = HISTORY_START if ticker in ETF_TICKERS else today - timedelta(days=365 * 10 + 3)
        response = session.get(
            POLYGON_BARS_URL.format(ticker=ticker, start=start.isoformat(), end=today.isoformat()),
            params={"adjusted": "true", "sort": "asc", "limit": 50000, "apiKey": api_key},
            timeout=30,
        )
        if response.status_code in {401, 403}:
            skipped.append(ticker)
            continue
        if response.status_code in {429, 500, 502, 503, 504}:
            response = request_with_retries(
                session,
                POLYGON_BARS_URL.format(ticker=ticker, start=start.isoformat(), end=today.isoformat()),
                params={"adjusted": "true", "sort": "asc", "limit": 50000, "apiKey": api_key},
            )
        else:
            raise_provider_error(response)
        results = response.json().get("results", [])
        if not results:
            continue
        first_bar = datetime.fromtimestamp(results[0]["t"] / 1000, timezone.utc).date()
        if first_bar > start + timedelta(days=45):
            clipped.append(f"{ticker}:{first_bar.isoformat()}")
        frames.append(
            pd.DataFrame(
                {
                    "ticker": ticker,
                    "date": [datetime.fromtimestamp(item["t"] / 1000, timezone.utc).date() for item in results],
                    "open": [item.get("o") for item in results], "high": [item.get("h") for item in results],
                    "low": [item.get("l") for item in results], "close": [item.get("c") for item in results],
                    "volume": [item.get("v") for item in results], "vwap": [item.get("vw") for item in results],
                    "transactions": [item.get("n") for item in results],
                }
            )
        )
    if skipped:
        print(f"polygon_history: entitlement unavailable for {','.join(skipped)}")
    if clipped:
        print(
            "polygon_history: requested start was clipped by available provider coverage for "
            + ",".join(clipped)
        )
    if not frames:
        raise RuntimeError("Polygon returned no extended historical bars")
    return upsert_price_frame(pd.concat(frames, ignore_index=True), "polygon")


def _chunks(values: list[date], size: int) -> Iterable[list[date]]:
    for index in range(0, len(values), size):
        yield values[index:index + size]


def parse_alfred_observations(
    series_id: str,
    vintages: list[date],
    observations: list[dict[str, Any]],
    aggregation_method: str,
) -> list[tuple[Any, ...]]:
    values: list[tuple[Any, ...]] = []
    for vintage in vintages:
        column = f"{series_id}_{vintage.strftime('%Y%m%d')}"
        cutoff = vintage - timedelta(days=550)
        by_month: dict[date, list[tuple[date, float]]] = {}
        for item in observations:
            raw = item.get(column)
            if raw in {None, "."}:
                continue
            observation_date = date.fromisoformat(item["date"])
            if observation_date > vintage or observation_date < cutoff:
                continue
            month = date(observation_date.year, observation_date.month, 1)
            by_month.setdefault(month, []).append((observation_date, float(raw)))
        for observation_month, monthly_values in sorted(by_month.items()):
            if aggregation_method == "avg":
                value = sum(item[1] for item in monthly_values) / len(monthly_values)
            else:
                value = max(monthly_values, key=lambda item: item[0])[1]
            values.append(
                (
                    "ALFRED", series_id, observation_month, vintage, value,
                    f"https://fred.stlouisfed.org/series/{series_id}",
                    json.dumps(
                        {
                            "source_frequency": "daily" if series_id in ALFRED_DAILY_SERIES else "monthly",
                            "stored_frequency": "monthly", "aggregation_method": aggregation_method,
                            "vintage_sampling": "month_end", "lookback_months": 18,
                        },
                        separators=(",", ":"),
                    ),
                )
            )
    return values


def parse_non_revised_monthly_proxy(
    series_id: str,
    observations: list[dict[str, Any]],
    aggregation_method: str,
    end: date,
) -> list[tuple[Any, ...]]:
    by_month: dict[date, list[tuple[date, float]]] = {}
    for item in observations:
        if item.get("value") in {None, "."}:
            continue
        observation_date = date.fromisoformat(item["date"])
        if observation_date > end:
            continue
        month = date(observation_date.year, observation_date.month, 1)
        by_month.setdefault(month, []).append((observation_date, float(item["value"])))
    values: list[tuple[Any, ...]] = []
    for observation_month, monthly_values in sorted(by_month.items()):
        if aggregation_method == "avg":
            value = sum(item[1] for item in monthly_values) / len(monthly_values)
        else:
            value = max(monthly_values, key=lambda item: item[0])[1]
        vintage_date = date(
            observation_month.year, observation_month.month,
            calendar.monthrange(observation_month.year, observation_month.month)[1],
        )
        if vintage_date > end:
            continue
        values.append(
            (
                "FRED_PIT_PROXY", series_id, observation_month, vintage_date, value,
                f"https://fred.stlouisfed.org/series/{series_id}",
                json.dumps(
                    {
                        "source_frequency": "daily", "stored_frequency": "monthly",
                        "aggregation_method": aggregation_method,
                        "point_in_time_method": "non_revised_market_series_month_end_proxy",
                    },
                    separators=(",", ":"),
                ),
            )
        )
    return values


def backfill_alfred_history() -> int:
    api_key = os.getenv("FRED_API_KEY")
    if not api_key:
        raise RuntimeError("FRED_API_KEY is required")
    today = datetime.now(timezone.utc).date()
    vintages = month_ends(HISTORY_START, today)
    session = requests.Session()
    values: list[tuple[Any, ...]] = []
    for series_id, aggregation_method in ALFRED_SERIES.items():
        if series_id in ALFRED_DAILY_SERIES:
            continue
        chunk_size = 48
        for vintage_chunk in _chunks(vintages, chunk_size):
            try:
                response = request_with_retries(
                    session,
                    FRED_URL,
                    params={
                        "series_id": series_id, "api_key": api_key, "file_type": "json",
                        "output_type": 2,
                        "vintage_dates": ",".join(item.isoformat() for item in vintage_chunk),
                        "observation_start": (vintage_chunk[0] - timedelta(days=730)).isoformat(),
                        "observation_end": vintage_chunk[-1].isoformat(),
                        "limit": 100000,
                    },
                    timeout=60,
                )
            except RuntimeError as exc:
                raise RuntimeError(
                    f"ALFRED {series_id} vintages {vintage_chunk[0]}..{vintage_chunk[-1]}: {exc}"
                ) from None
            observations = response.json().get("observations", [])
            values.extend(
                parse_alfred_observations(
                    series_id, vintage_chunk, observations, aggregation_method
                )
            )
    for series_id in sorted(ALFRED_DAILY_SERIES):
        response = request_with_retries(
            session,
            FRED_URL,
            params={
                "series_id": series_id, "api_key": api_key, "file_type": "json",
                "observation_start": (HISTORY_START - timedelta(days=730)).isoformat(),
                "observation_end": today.isoformat(), "limit": 100000,
            },
            timeout=60,
        )
        values.extend(
            parse_non_revised_monthly_proxy(
                series_id, response.json().get("observations", []),
                ALFRED_SERIES[series_id], today,
            )
        )
    if not values:
        raise RuntimeError("ALFRED returned no point-in-time observations")
    with database.postgres_connection() as conn:
        conn.execute(
            """CREATE TEMP TABLE alfred_stage(
            provider text, series_id text, observation_date date, vintage_date date,
            value double precision, source_url text, metadata_text text
            ) ON COMMIT DROP"""
        )
        count = copy_rows(
            conn,
            "COPY alfred_stage(provider,series_id,observation_date,vintage_date,value,source_url,metadata_text) FROM STDIN",
            values,
            "alfred",
        )
        conn.execute(
            """INSERT INTO public.macro_observations(
            provider, series_id, observation_date, vintage_date, value, source_url,
            is_point_in_time, metadata
            ) SELECT provider, series_id, observation_date, vintage_date, value,
            source_url, true, metadata_text::jsonb FROM alfred_stage
            ON CONFLICT (provider, series_id, observation_date, vintage_date) DO UPDATE SET
            value=excluded.value, source_url=excluded.source_url,
            is_point_in_time=true, metadata=excluded.metadata, fetched_at=now()"""
        )
    return count


def refresh_regime_labels() -> int:
    return generate_and_store_regimes()


def refresh_fred() -> int:
    api_key = os.getenv("FRED_API_KEY")
    if not api_key:
        raise RuntimeError("FRED_API_KEY is required")
    today = datetime.now(timezone.utc).date()
    with database.postgres_connection() as conn:
        latest_rows = conn.execute(
            """SELECT series_id, max(observation_date) AS latest
            FROM public.macro_observations WHERE series_id = ANY(%s) GROUP BY series_id""",
            (FRED_SERIES,),
        ).fetchall()
    latest = {row["series_id"]: row["latest"] for row in latest_rows}
    values: list[tuple[Any, ...]] = []
    session = requests.Session()
    for series_id in FRED_SERIES:
        start = (latest.get(series_id) - timedelta(days=120)) if latest.get(series_id) else date(1900, 1, 1)
        response = session.get(
            FRED_URL,
            params={
                "series_id": series_id, "api_key": api_key, "file_type": "json",
                "observation_start": start.isoformat(), "realtime_start": today.isoformat(),
                "realtime_end": today.isoformat(),
            },
            timeout=30,
        )
        raise_provider_error(response)
        for item in response.json().get("observations", []):
            if item.get("value") == ".":
                continue
            values.append(
                (
                    "FRED", series_id, item["date"], item.get("realtime_start", today.isoformat()),
                    float(item["value"]), f"https://fred.stlouisfed.org/series/{series_id}",
                )
            )
    with database.postgres_connection() as conn:
        with conn.cursor() as cursor:
            cursor.executemany(
                """INSERT INTO public.macro_observations(
                provider, series_id, observation_date, vintage_date, value, source_url,
                is_point_in_time, metadata
                ) VALUES (%s,%s,%s,%s,%s,%s,true,'{}'::jsonb)
                ON CONFLICT (provider, series_id, observation_date, vintage_date) DO UPDATE SET
                value=excluded.value, fetched_at=now()""",
                values,
            )
    return len(values)


def refresh_news() -> int:
    api_key = os.getenv("POLYGON_API_KEY")
    if not api_key:
        raise RuntimeError("POLYGON_API_KEY is required")
    rows: list[dict[str, Any]] = []
    since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    session = requests.Session()
    for ticker in active_tickers():
        response = session.get(
            POLYGON_NEWS_URL,
            params={
                "ticker": ticker, "published_utc.gte": since, "sort": "published_utc",
                "order": "desc", "limit": 50, "apiKey": api_key,
            },
            timeout=30,
        )
        raise_provider_error(response)
        for item in response.json().get("results", []):
            publisher = item.get("publisher") or {}
            rows.append(
                {
                    "ticker": ticker, "published_at": item.get("published_utc"),
                    "source": publisher.get("name") or "Polygon", "headline": item.get("title"),
                    "summary": item.get("description"), "url": item.get("article_url"),
                    "event_type": "other", "sentiment_label": "unknown", "sentiment_score": 0.0,
                    "relevance_score": 55.0, "catalyst_type": "none", "risk_type": "none",
                    "management_tone": None, "regulatory_risk": False, "legal_risk": False,
                    "news_data_quality_score": 60.0, "is_real_data": True,
                }
            )
    return upsert_news_frame(pd.DataFrame(rows), "polygon_news") if rows else 0


def normalize_sec_payload(ticker: str, payload: dict[str, Any]) -> pd.DataFrame:
    facts = payload.get("facts", {}).get("us-gaap", {})
    periods: dict[tuple[str, str | None, int | None], dict[str, Any]] = {}
    for metric, tags in SEC_TAGS.items():
        fact = next((facts[tag] for tag in tags if tag in facts), None)
        if not fact:
            continue
        preferred_units = ["USD/shares", "shares"] if metric in {"eps_diluted", "shares_diluted"} else ["USD"]
        units = fact.get("units", {})
        values = next((units[unit] for unit in preferred_units if unit in units), [])
        for item in values:
            if not item.get("end") or item.get("form") not in {"10-K", "10-Q", "20-F", "40-F"}:
                continue
            key = (item["end"], item.get("fp"), item.get("fy"))
            period = periods.setdefault(
                key,
                {
                    "ticker": ticker, "period_end": item["end"], "fiscal_period": item.get("fp"),
                    "fiscal_year": item.get("fy"), "metrics": {}, "filed": item.get("filed"),
                },
            )
            if not period.get("filed") or str(item.get("filed", "")) >= str(period["filed"]):
                period["metrics"][metric] = item.get("val")
                period["filed"] = item.get("filed")
    return pd.DataFrame(periods.values())


def upsert_sec_periods(frame: pd.DataFrame) -> int:
    if frame.empty:
        return 0
    with database.postgres_connection() as conn:
        upsert_securities(conn, frame["ticker"].astype(str).unique())
        for row in frame.itertuples(index=False):
            ticker = str(row.ticker).upper()
            conn.execute(
                """INSERT INTO public.fundamental_periods(
                security_id, provider, period_end, fiscal_period, fiscal_year, metrics,
                data_quality_score, source_url
                ) SELECT id, 'sec_edgar_companyfacts', %s,%s,%s,%s,%s,%s
                FROM public.securities WHERE ticker=%s AND asset_type=%s
                ON CONFLICT (security_id, provider, period_end, fiscal_period, fiscal_year)
                DO UPDATE SET metrics=excluded.metrics, fetched_at=now()""",
                (
                    row.period_end, clean(row.fiscal_period), clean(row.fiscal_year),
                    database._jsonb(row.metrics), None,
                    "https://data.sec.gov/api/xbrl/companyfacts/", ticker, asset_type(ticker),
                ),
            )
    return len(frame)


def refresh_sec() -> int:
    user_agent = os.getenv("SEC_USER_AGENT")
    if not user_agent or "@" not in user_agent:
        raise RuntimeError("SEC_USER_AGENT is required and must include a contact email")
    headers = {"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"}
    session = requests.Session()
    response = session.get(SEC_TICKERS_URL, headers=headers, timeout=30)
    response.raise_for_status()
    mapping = {
        str(item["ticker"]).upper(): str(item["cik_str"]).zfill(10)
        for item in response.json().values()
    }
    frames = []
    for ticker in active_tickers():
        cik = mapping.get(ticker)
        if not cik:
            continue
        response = session.get(SEC_FACTS_URL.format(cik=cik), headers=headers, timeout=30)
        if response.status_code == 404:
            continue
        response.raise_for_status()
        frame = normalize_sec_payload(ticker, response.json())
        if not frame.empty:
            frames.append(frame)
    return upsert_sec_periods(pd.concat(frames, ignore_index=True)) if frames else 0


def refresh_markets() -> int:
    payload = refresh_scenarios(force=True)
    contracts = payload.get("contracts", [])
    observed_at = payload.get("fetched_at", database.utc_now())
    with database.postgres_connection() as conn:
        for contract in contracts:
            provider = str(contract["provider"]).lower()
            market_id = conn.execute(
                """INSERT INTO public.prediction_markets(
                provider, external_market_id, canonical_question, canonical_scenario,
                title, source_url, metadata
                ) VALUES (%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (provider, external_market_id) DO UPDATE SET
                canonical_question=excluded.canonical_question,
                canonical_scenario=excluded.canonical_scenario, title=excluded.title,
                source_url=excluded.source_url, metadata=excluded.metadata, updated_at=now()
                RETURNING id""",
                (
                    provider, contract["id"], contract["title"], contract.get("scenario"),
                    contract["title"], contract.get("source"),
                    database._jsonb({"indicator": contract.get("indicator"), "event_id": contract.get("event_id")}),
                ),
            ).fetchone()["id"]
            conn.execute(
                """INSERT INTO public.prediction_market_snapshots(
                market_id, observed_at, probability, volume, open_interest, confidence, raw_payload
                ) VALUES (%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (market_id, observed_at) DO UPDATE SET
                probability=excluded.probability, volume=excluded.volume,
                open_interest=excluded.open_interest, confidence=excluded.confidence,
                raw_payload=excluded.raw_payload""",
                (
                    market_id, observed_at, contract["probability"], contract.get("volume"),
                    contract.get("open_interest"), contract.get("confidence"), database._jsonb(contract),
                ),
            )
    return len(contracts)


BACKFILL_PROVIDERS: dict[str, Callable[[], int]] = {
    "polygon": backfill_polygon,
    "fred": backfill_fred,
    "fundamentals": backfill_fundamentals,
    "news": backfill_news,
    "markets": refresh_markets,
}
REFRESH_PROVIDERS: dict[str, Callable[[], int]] = {
    "polygon": refresh_polygon,
    "fred": refresh_fred,
    "news": refresh_news,
    "sec": refresh_sec,
    "markets": refresh_markets,
    "regimes": refresh_regime_labels,
}
HISTORY_PROVIDERS: dict[str, Callable[[], int]] = {
    "polygon": extend_polygon_history,
    "alfred": backfill_alfred_history,
    "regimes": refresh_regime_labels,
}


def parse_providers(raw: str, available: dict[str, Callable[[], int]]) -> list[str]:
    if raw == "all":
        return list(available)
    requested = [item.strip().lower() for item in raw.split(",") if item.strip()]
    unknown = sorted(set(requested) - available.keys())
    if unknown:
        raise ValueError(f"Unknown providers: {', '.join(unknown)}")
    return requested


def show_status() -> None:
    with database.postgres_connection() as conn:
        counts = conn.execute(
            """SELECT
            (SELECT count(*) FROM public.price_bars) AS price_bars,
            (SELECT count(*) FROM public.macro_observations) AS macro_observations,
            (SELECT count(*) FROM public.fundamental_periods) AS fundamental_periods,
            (SELECT count(*) FROM public.documents WHERE document_type='news') AS news_documents,
            (SELECT count(*) FROM public.prediction_market_snapshots) AS market_snapshots,
            (SELECT count(*) FROM public.macro_regime_labels) AS macro_regimes"""
        ).fetchone()
        latest = conn.execute(
            """SELECT provider, status, fetched_at, metadata
            FROM public.provider_fetches ORDER BY fetched_at DESC LIMIT 10"""
        ).fetchall()
    print("Stored rows: " + ", ".join(f"{key}={value}" for key, value in counts.items()))
    for row in latest:
        print(f"{row['fetched_at'].isoformat()} {row['provider']} {row['status']} {row['metadata']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Idempotent provider ingestion for InvestmentDashboard")
    subparsers = parser.add_subparsers(dest="command", required=True)
    backfill_parser = subparsers.add_parser("backfill")
    backfill_parser.add_argument("--providers", default="all")
    refresh_parser = subparsers.add_parser("refresh")
    refresh_parser.add_argument("--providers", default="all")
    history_parser = subparsers.add_parser("history")
    history_parser.add_argument("--providers", default="all")
    subparsers.add_parser("status")
    args = parser.parse_args()

    if args.command == "status":
        show_status()
        return 0
    available = (
        BACKFILL_PROVIDERS if args.command == "backfill"
        else HISTORY_PROVIDERS if args.command == "history"
        else REFRESH_PROVIDERS
    )
    providers = parse_providers(args.providers, available)
    for provider in providers:
        run_recorded(provider, f"{args.command}:{provider}", available[provider])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import json
import math
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import requests

from . import database
from .scenarios import is_sports_market


POLYMARKET_SEARCH_URL = "https://gamma-api.polymarket.com/public-search"
MAX_TICKERS_PER_REFRESH = 15
MAX_MARKETS_PER_SECURITY = 5
NON_COMPANY_TICKERS = {
    "SPY", "QQQ", "VTI", "IWM", "DIA", "BND", "AGG", "TLT", "SHY", "IEF",
    "XLB", "XLC", "XLE", "XLF", "XLI", "XLK", "XLP", "XLRE", "XLU", "XLV", "XLY",
}

COMPANY_ALIASES = {
    "AAPL": ["apple"], "AMZN": ["amazon"], "CSCO": ["cisco"],
    "GOOG": ["google", "alphabet"], "GOOGL": ["google", "alphabet"],
    "META": ["meta", "facebook"], "MSFT": ["microsoft"], "MU": ["micron"],
    "NFLX": ["netflix"], "NVDA": ["nvidia"], "TSLA": ["tesla"],
}
CORPORATE_WORDS = {
    "inc", "incorporated", "corp", "corporation", "company", "co", "plc", "ltd",
    "limited", "holdings", "holding", "class", "common", "stock", "the",
}


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


def _yes_probability(market: dict[str, Any]) -> float | None:
    outcomes = [str(value).strip().lower() for value in _json_list(market.get("outcomes"))]
    prices = _json_list(market.get("outcomePrices"))
    index = outcomes.index("yes") if "yes" in outcomes else 0
    if index >= len(prices):
        value = market.get("lastTradePrice")
    else:
        value = prices[index]
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return None


def _aliases(ticker: str, company: str) -> list[str]:
    aliases = list(COMPANY_ALIASES.get(ticker.upper(), []))
    words = [
        word.lower() for word in re.findall(r"[A-Za-z0-9]+", company)
        if word.lower() not in CORPORATE_WORDS and len(word) >= 4
    ]
    if words:
        aliases.append(" ".join(words[:3]))
        aliases.append(words[0])
    if len(ticker) >= 3:
        aliases.append(ticker.lower())
    return list(dict.fromkeys(alias for alias in aliases if alias))


def _relevant(text: str, aliases: list[str]) -> bool:
    clean = text.lower()
    return any(re.search(rf"\b{re.escape(alias)}\b", clean) for alias in aliases)


def _evidence_type(text: str) -> str:
    clean = text.lower()
    if re.search(r"\b(?:earnings|revenue|eps|profit|quarterly results?)\b", clean):
        return "earnings"
    if re.search(r"\b(?:launch|release|ship|product|iphone|vehicle|drug)\b", clean):
        return "product"
    if re.search(r"\b(?:ceo|chief executive|leadership|acquire|acquisition|merger)\b", clean):
        return "corporate event"
    if re.search(r"\b(?:approve|approval|antitrust|regulator|lawsuit|ban)\b", clean):
        return "regulatory"
    return "business catalyst"


def _confidence(market: dict[str, Any]) -> float:
    bid = market.get("bestBid")
    ask = market.get("bestAsk")
    spread = 0.30 if bid is None or ask is None else max(0.0, _number(ask) - _number(bid))
    spread_score = max(0.0, 1.0 - spread / 0.30)
    activity = min(1.0, math.log1p(max(_number(market.get("volumeNum") or market.get("volume")), 0.0)) / math.log(100001))
    return round(max(0.05, min(1.0, spread_score * 0.70 + activity * 0.30)), 4)


def normalize_company_search(ticker: str, company: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    aliases = _aliases(ticker, company)
    matches: list[dict[str, Any]] = []
    for event in payload.get("events", []):
        if not event.get("active", True) or event.get("closed", False):
            continue
        event_title = str(event.get("title") or "")
        for market in event.get("markets", []):
            if not market.get("active", True) or market.get("closed", False):
                continue
            question = str(market.get("question") or event_title)
            combined = f"{event_title} {question}"
            if is_sports_market(combined, market) or not _relevant(combined, aliases):
                continue
            probability = _yes_probability(market)
            if probability is None:
                continue
            matches.append({
                "provider": "Polymarket",
                "id": str(market.get("id") or market.get("conditionId") or event.get("id")),
                "ticker": ticker.upper(),
                "title": question,
                "probability": round(probability, 4),
                "confidence": _confidence(market),
                "volume": _number(market.get("volumeNum") or market.get("volume")),
                "evidence_type": _evidence_type(combined),
                "source": f"https://polymarket.com/event/{event.get('slug') or market.get('slug', '')}",
                "closes_at": market.get("endDate") or event.get("endDate"),
                "token_ids": market.get("clobTokenIds"),
            })
    deduplicated = {item["id"]: item for item in matches}
    return sorted(
        deduplicated.values(),
        key=lambda item: (item["confidence"], math.log1p(max(item["volume"], 0.0))),
        reverse=True,
    )[:MAX_MARKETS_PER_SECURITY]


def _fetch_one(ticker: str, company: str) -> list[dict[str, Any]]:
    query = COMPANY_ALIASES.get(ticker.upper(), [company or ticker])[0]
    response = requests.get(
        POLYMARKET_SEARCH_URL,
        params={"q": query, "limit_per_type": 20},
        timeout=10,
    )
    response.raise_for_status()
    return normalize_company_search(ticker, company, response.json())


def refresh_company_markets(ticker_companies: dict[str, str]) -> dict[str, Any]:
    selected = {
        ticker.strip().upper(): company
        for ticker, company in ticker_companies.items()
        if ticker.strip()
        and ticker.upper() != "CASH"
        and ticker.upper() not in NON_COMPANY_TICKERS
        and " etf" not in f" {company.lower()}"
        and (ticker.upper() in COMPANY_ALIASES or company.strip().upper() != ticker.strip().upper())
    }
    selected = dict(list(selected.items())[:MAX_TICKERS_PER_REFRESH])
    found: list[dict[str, Any]] = []
    warnings: list[str] = []
    with ThreadPoolExecutor(max_workers=min(4, max(1, len(selected)))) as pool:
        futures = {pool.submit(_fetch_one, ticker, company): ticker for ticker, company in selected.items()}
        for future in as_completed(futures):
            ticker = futures[future]
            try:
                markets = future.result()
                found.extend(markets)
                if database.DATABASE_URL:
                    database.save_security_prediction_markets(ticker, selected[ticker], markets)
            except (requests.RequestException, ValueError) as exc:
                warnings.append(f"Polymarket company search unavailable for {ticker}: {type(exc).__name__}")
    return {"markets": found, "warnings": warnings, "searched": len(selected)}

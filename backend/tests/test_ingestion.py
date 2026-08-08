from backend.ingestion import (
    article_id, normalize_sec_payload, normalize_tiingo_prices, parse_providers,
)


class NewsRow:
    url = "https://example.com/article"
    source = "Example"
    headline = "A headline"
    published_at = "2026-08-07T00:00:00Z"


def test_article_id_is_stable() -> None:
    assert article_id(NewsRow()) == article_id(NewsRow())
    assert len(article_id(NewsRow())) == 64


def test_provider_parser_rejects_unknown_provider() -> None:
    available = {"polygon": lambda: 0, "fred": lambda: 0}
    assert parse_providers("fred,polygon", available) == ["fred", "polygon"]


def test_sec_normalization_uses_supported_forms() -> None:
    payload = {
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {"end": "2025-12-31", "fp": "FY", "fy": 2025, "form": "10-K", "filed": "2026-02-01", "val": 100},
                            {"end": "2025-12-31", "fp": "FY", "fy": 2025, "form": "8-K", "filed": "2026-02-02", "val": 999},
                        ]
                    }
                }
            }
        }
    }
    frame = normalize_sec_payload("TEST", payload)
    assert len(frame) == 1
    assert frame.iloc[0]["metrics"]["revenue"] == 100


def test_tiingo_normalization_preserves_adjusted_close() -> None:
    frame = normalize_tiingo_prices("aapl", [{
        "date": "2020-08-31T00:00:00.000Z", "open": 127.58, "high": 131.0,
        "low": 126.0, "close": 129.04, "adjClose": 125.88, "volume": 225702700,
    }])
    assert frame.to_dict("records") == [{
        "ticker": "AAPL", "date": frame.iloc[0]["date"], "open": 127.58,
        "high": 131.0, "low": 126.0, "close": 129.04,
        "adjusted_close": 125.88, "volume": 225702700, "vwap": None,
        "transactions": None,
    }]


def test_tiingo_normalization_drops_incomplete_bars() -> None:
    frame = normalize_tiingo_prices("SPY", [
        {"date": "2020-01-01T00:00:00Z", "close": 100, "adjClose": None},
        {"date": None, "close": 100, "adjClose": 100},
    ])
    assert frame.empty

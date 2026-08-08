from backend.company_markets import normalize_company_search, refresh_company_markets


def test_normalize_company_search_keeps_live_company_events_only() -> None:
    payload = {
        "events": [
            {
                "id": "apple-live", "slug": "apple-foldable", "title": "Apple foldable iPhone before 2027?",
                "active": True, "closed": False,
                "markets": [{
                    "id": "m1", "question": "Will Apple release a foldable iPhone before 2027?",
                    "active": True, "closed": False, "outcomes": '["Yes","No"]',
                    "outcomePrices": '["0.61","0.39"]', "bestBid": .60, "bestAsk": .62,
                    "volumeNum": 10000,
                }],
            },
            {
                "id": "apple-closed", "slug": "apple-old", "title": "Apple earnings beat?",
                "active": True, "closed": True,
                "markets": [{"id": "m2", "question": "Will Apple earnings beat?", "outcomePrices": '["1","0"]'}],
            },
            {
                "id": "unrelated", "slug": "other", "title": "Another company earnings beat?",
                "active": True, "closed": False,
                "markets": [{"id": "m3", "question": "Will another company earnings beat?", "outcomePrices": '[".5",".5"]'}],
            },
        ]
    }
    markets = normalize_company_search("AAPL", "Apple Inc.", payload)
    assert len(markets) == 1
    assert markets[0]["id"] == "m1"
    assert markets[0]["probability"] == .61
    assert markets[0]["evidence_type"] == "product"


def test_normalize_company_search_maps_earnings_without_affecting_macro() -> None:
    payload = {
        "events": [{
            "id": "nvidia-earnings", "slug": "nvidia-q3", "title": "Nvidia Q3 earnings",
            "active": True, "closed": False,
            "markets": [{
                "id": "m4", "question": "Will Nvidia revenue exceed expectations this quarter?",
                "active": True, "closed": False, "outcomes": '["No","Yes"]',
                "outcomePrices": '["0.25","0.75"]', "volumeNum": 5000,
            }],
        }]
    }
    markets = normalize_company_search("NVDA", "NVIDIA Corporation", payload)
    assert markets[0]["probability"] == .75
    assert markets[0]["evidence_type"] == "earnings"
    assert "scenario" not in markets[0]


def test_refresh_skips_etfs_and_unresolved_tickers(monkeypatch) -> None:
    searched = []
    monkeypatch.setattr(
        "backend.company_markets._fetch_one",
        lambda ticker, company: searched.append((ticker, company)) or [],
    )
    result = refresh_company_markets({"SPY": "S&P 500 ETF", "ZZZZ": "ZZZZ", "AAPL": "Apple Inc."})
    assert searched == [("AAPL", "Apple Inc.")]
    assert result["searched"] == 1

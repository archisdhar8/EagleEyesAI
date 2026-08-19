from backend.chat import _bounded_value, ask_gemini, retrieve_evidence


class _Response:
    status_code = 200

    def __init__(self, text: str, finish_reason: str):
        self.text = text
        self.finish_reason = finish_reason

    def json(self):
        return {
            "candidates": [{
                "finishReason": self.finish_reason,
                "content": {"parts": [{"text": self.text}]},
            }]
        }


def test_chat_continues_a_max_tokens_response(monkeypatch) -> None:
    responses = iter([
        _Response("The first part ends here", "MAX_TOKENS"),
        _Response("and this completes the answer. What to verify: freshness.", "STOP"),
    ])
    calls = []

    def fake_post(*args, **kwargs):
        calls.append(kwargs["json"])
        return next(responses)

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_MAX_CONTINUATIONS", "1")
    monkeypatch.setattr("backend.chat.requests.post", fake_post)
    answer, model = ask_gemini("What changed?", [], [])

    assert "The first part ends here" in answer
    assert "and this completes the answer" in answer
    assert len(calls) == 2
    assert calls[0]["generationConfig"]["maxOutputTokens"] == 3200
    assert calls[1]["generationConfig"]["maxOutputTokens"] == 1200
    assert calls[1]["contents"][-1]["role"] == "user"
    assert model


def test_chat_cleans_partial_answer_without_a_second_request(monkeypatch) -> None:
    calls = []

    def fake_post(*args, **kwargs):
        calls.append(kwargs["json"])
        return _Response("A completed evidence-backed sentence. An unfinished fragment [", "MAX_TOKENS")

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_MAX_CONTINUATIONS", "0")
    monkeypatch.setattr("backend.chat.requests.post", fake_post)
    answer, _ = ask_gemini("What changed?", [], [])

    assert len(calls) == 1
    assert answer.startswith("A completed evidence-backed sentence.")
    assert "unfinished fragment" not in answer
    assert "answer is incomplete" in answer.lower()


def test_prompt_bounding_preserves_nested_holding_records() -> None:
    evidence = {"data": {"summary": {"positions": [
        {"ticker": "BLK", "weight": .0118, "market_value": 39438.41, "sector": "Financials"},
        {"ticker": "COST", "weight": .021, "sector": "Consumer Staples"},
    ]}}}

    bounded = _bounded_value(evidence)

    positions = bounded["data"]["summary"]["positions"]
    assert positions[0]["ticker"] == "BLK"
    assert positions[0]["market_value"] == 39438.41
    assert isinstance(positions[0], dict)


def test_generic_chat_evidence_uses_bounded_price_history(monkeypatch) -> None:
    calls = []
    portfolio = {
            "id": "portfolio-61",
            "name": "Large", "updated_at": "2026-08-18", "holdings": [
                {"ticker": f"S{index}"} for index in range(61)
            ],
        }
    monkeypatch.setattr("backend.chat.database.get_portfolio", lambda portfolio_id, user_id: portfolio)
    monkeypatch.setattr("backend.chat.database.latest_portfolio_health", lambda user_id, portfolio_id: {
        "result": {"as_of": "2026-08-18", "health": {"score": 68},
                   "holdings": [{"ticker": f"S{index}"} for index in range(61)],
                   "actions": [], "changes": [], "warnings": []},
    })
    monkeypatch.setattr("backend.chat.database.load_profile", lambda user_id: {})
    monkeypatch.setattr("backend.chat.database.latest_scenario_snapshot", lambda: None)
    monkeypatch.setattr("backend.chat.database.latest_analysis", lambda user_id: None)
    monkeypatch.setattr("backend.chat.security_research", lambda tickers, price_limit=756: calls.append(
        (list(tickers), price_limit)
    ) or [])
    monkeypatch.setattr("backend.chat.macro_factor_dashboard", lambda: {"factors": []})
    monkeypatch.setattr("backend.chat.latest_macro", lambda: {"as_of": "2026-08-18"})

    evidence = retrieve_evidence("bounded-history-user", "Explain my portfolio", "portfolio-61")

    assert calls == [([f"S{index}" for index in range(12)], 260)]
    overview = next(row for row in evidence if row["label"] == "Full cached portfolio intelligence")
    assert len(overview["data"]["holdings"]) == 61

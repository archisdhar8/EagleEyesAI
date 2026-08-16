from backend.chat import ask_gemini


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
    monkeypatch.setattr("backend.chat.requests.post", fake_post)
    answer, model = ask_gemini("What changed?", [], [])

    assert "The first part ends here" in answer
    assert "and this completes the answer" in answer
    assert len(calls) == 2
    assert calls[0]["generationConfig"]["maxOutputTokens"] == 2200
    assert calls[1]["contents"][-1]["role"] == "user"
    assert model

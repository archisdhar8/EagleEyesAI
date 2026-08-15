from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException

from backend import auth


def test_auth_uses_stdin_curl_fallback_without_token_in_process_args(monkeypatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "publishable-key")
    monkeypatch.setattr(auth.httpx, "get", lambda *args, **kwargs: (_ for _ in ()).throw(httpx.ConnectError("dns")))
    captured = {}

    def run(args, **kwargs):
        captured["args"] = args
        captured["input"] = kwargs["input"]
        return SimpleNamespace(stdout='{"id":"user-1","email":"user@example.com"}\n200')

    monkeypatch.setattr(auth.subprocess, "run", run)
    user = auth.require_user("Bearer header.payload.signature")
    assert user.id == "user-1"
    assert captured["args"] == ["curl", "--config", "-"]
    assert "header.payload.signature" not in " ".join(captured["args"])
    assert "header.payload.signature" in captured["input"]


def test_auth_rejects_malformed_token_before_network(monkeypatch) -> None:
    monkeypatch.setattr(auth.httpx, "get", lambda *args, **kwargs: pytest.fail("network should not run"))
    with pytest.raises(HTTPException) as error:
        auth.require_user("Bearer bad token")
    assert error.value.status_code == 401

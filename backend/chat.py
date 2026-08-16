from __future__ import annotations

import os
import re
from typing import Any

import requests
from dotenv import load_dotenv

from . import database
from .analysis import latest_macro, macro_factor_dashboard, security_research
from .operational_monitoring import record_metric
from .resilience import RetryPolicy, TTLCache, retry_call


load_dotenv(database.ENV_PATH, override=False)

_EVIDENCE_CACHE = TTLCache(max_entries=128)
_GEMINI_POLICY = RetryPolicy(attempts=max(1, min(3, int(os.getenv("GEMINI_MAX_RETRIES", "2")))))


def _ticker_candidates(question: str, available: list[str]) -> list[str]:
    mentioned = set(re.findall(r"\b[A-Z]{1,5}\b", question.upper()))
    selected = [ticker for ticker in available if ticker in mentioned]
    return selected or available[:12]


def retrieve_evidence(user_id: str, question: str) -> list[dict[str, Any]]:
    cache_key = f"{user_id}:{' '.join(question.lower().split())[:300]}"
    cached = _EVIDENCE_CACHE.get(cache_key)
    if cached is not None:
        record_metric("chat.evidence_cache_hit")
        return cached
    portfolios = database.list_portfolios(user_id)
    profile = database.load_profile(user_id) or {}
    portfolio = portfolios[0] if portfolios else {"holdings": []}
    universe = list(dict.fromkeys(
        [item["ticker"] for item in portfolio.get("holdings", [])]
        + profile.get("watchlist", [])
    ))
    research = security_research(_ticker_candidates(question, universe))
    factors = macro_factor_dashboard()
    scenarios = database.latest_scenario_snapshot() or {"scenarios": [], "fetched_at": None}
    analysis = database.latest_analysis(user_id)
    evidence: list[dict[str, Any]] = [
        {"label": "Current portfolio", "as_of": portfolio.get("updated_at"), "url": None,
         "data": {"name": portfolio.get("name"), "holdings": portfolio.get("holdings", [])}},
        {"label": "Investor profile", "as_of": profile.get("updated_at"), "url": None,
         "data": {key: value for key, value in profile.items() if key not in {"llm_endpoint"}}},
        {"label": "Macro factor dashboard", "as_of": latest_macro().get("as_of"),
         "url": "https://fred.stlouisfed.org/", "data": factors},
        {"label": "Prediction-market scenario snapshot", "as_of": scenarios.get("fetched_at"),
         "url": None, "data": scenarios.get("scenarios", [])},
    ]
    for row in research:
        sources = [row.get("source"), row.get("latest_news", {}).get("source_url") if row.get("latest_news") else None]
        evidence.append({"label": f"{row['ticker']} validated research", "as_of": row.get("price_as_of") or row.get("fundamentals_as_of"),
                         "url": next((source for source in sources if source), None), "data": row})
    if analysis:
        evidence.append({"label": "Latest completed optimizer run", "as_of": analysis.get("created_at"),
                         "url": None, "data": {"alternatives": analysis.get("alternatives"), "warnings": analysis.get("warnings"), "model_diagnostics": analysis.get("model_diagnostics")}})
    result = evidence[:18]
    _EVIDENCE_CACHE.put(cache_key, result, ttl_seconds=45)
    return result


def _gemini_request(api_key: str, model: str, contents: list[dict[str, Any]], max_tokens: int) -> dict[str, Any]:
    def request_once() -> requests.Response:
        response = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
            json={
                "contents": contents,
                "generationConfig": {"temperature": 0.2, "maxOutputTokens": max_tokens},
            },
            timeout=(4, 24),
        )
        if response.status_code in {408, 429, 500, 502, 503, 504}:
            response.raise_for_status()
        return response

    try:
        response = retry_call(
            request_once,
            policy=_GEMINI_POLICY,
            retryable=lambda exc: isinstance(exc, (requests.Timeout, requests.ConnectionError, requests.HTTPError)),
            metric="gemini.chat",
        )
    except requests.RequestException as exc:
        raise RuntimeError("Gemini is temporarily unreachable; retry shortly. Your stored evidence was not changed") from exc
    if response.status_code >= 400:
        message = response.json().get("error", {}).get("message", "Gemini request failed")
        raise RuntimeError(message)
    return response.json()


def _candidate(payload: dict[str, Any]) -> tuple[str, str]:
    try:
        candidate = payload["candidates"][0]
        parts = candidate["content"]["parts"]
        text = "\n".join(part.get("text", "") for part in parts if part.get("text")).strip()
        if not text:
            raise KeyError("empty response")
        return text, str(candidate.get("finishReason") or "UNKNOWN").upper()
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("Gemini returned no answer") from exc


def ask_gemini(question: str, evidence: list[dict[str, Any]], history: list[dict[str, Any]],
               conversation_summary: str = "") -> tuple[str, str]:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured in backend/.env")
    indexed = [{"id": f"S{index + 1}", **item} for index, item in enumerate(evidence)]
    prior = [{"role": item["role"], "content": item["content"]} for item in history[-8:]]
    prompt = f"""You are the evidence-grounded research assistant inside EagleEyes AI.
Use only the supplied evidence. Cite factual claims inline as [S1], [S2], etc.
Never invent prices, probabilities, fundamentals, dates, scores, allocations, or source URLs.
Distinguish facts from model estimates and state when evidence is missing or stale.
Do not give a directive to buy or sell; explain tradeoffs and what the user should inspect.
Prediction markets may change scenario weights but never override quality, valuation, or risk controls.
Macro changes are not release surprises unless a source explicitly contains a consensus estimate.
When company and article evidence is supplied, separate company facts, reported management statements, and third-party interpretation.
Do not infer an industry pricing cycle from general company news. If specialized pricing, supply-chain, or consensus data is absent, say so explicitly.
For questions about when to sell, do not invent a sale date or price. Explain review triggers, upcoming catalysts, portfolio constraints, taxes, and evidence that would change the thesis.

Recent conversation: {prior}
Earlier conversation summary: {conversation_summary or 'No earlier summary yet.'}
Evidence: {indexed}
Question: {question}

Answer in no more than five concise paragraphs, then end with a short 'What to verify' sentence.
Do not add a sources list; the application manages source metadata separately."""
    contents: list[dict[str, Any]] = [{"role": "user", "parts": [{"text": prompt}]}]
    answer_parts: list[str] = []
    finish_reason = "UNKNOWN"
    # Gemini can return useful partial text with MAX_TOKENS. Continue it instead
    # of silently presenting the partial response as a finished answer.
    max_continuations = max(0, min(1, int(os.getenv("GEMINI_MAX_CONTINUATIONS", "1"))))
    for attempt in range(1 + max_continuations):
        payload = _gemini_request(api_key, model, contents, 2200 if attempt == 0 else 900)
        text, finish_reason = _candidate(payload)
        answer_parts.append(text)
        if finish_reason != "MAX_TOKENS":
            break
        contents.extend([
            {"role": "model", "parts": [{"text": text}]},
            {"role": "user", "parts": [{"text": "Continue exactly where the answer stopped. Do not repeat earlier text. Finish concisely and include the requested What to verify sentence."}]},
        ])
    answer = "\n\n".join(part for part in answer_parts if part).strip()
    if finish_reason == "MAX_TOKENS":
        answer += "\n\nThe model could not finish within the available response limit. Ask a narrower follow-up for the remaining detail."
    return answer, model

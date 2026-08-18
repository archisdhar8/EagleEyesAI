from __future__ import annotations

import json
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
_GEMINI_POLICY = RetryPolicy(attempts=max(1, min(2, int(os.getenv("GEMINI_MAX_RETRIES", "1")))))


def _ticker_candidates(question: str, available: list[str]) -> list[str]:
    mentioned = set(re.findall(r"\b[A-Z]{1,5}\b", question.upper()))
    selected = [ticker for ticker in available if ticker in mentioned]
    return selected or available[:12]


def retrieve_evidence(user_id: str, question: str, portfolio_id: str | None = None) -> list[dict[str, Any]]:
    cache_key = f"{user_id}:{portfolio_id or 'general'}:{' '.join(question.lower().split())[:300]}"
    cached = _EVIDENCE_CACHE.get(cache_key)
    if cached is not None:
        record_metric("chat.evidence_cache_hit")
        return cached
    portfolios = database.list_portfolios(user_id)
    profile = database.load_profile(user_id) or {}
    portfolio = database.get_portfolio(portfolio_id, user_id) if portfolio_id else {"holdings": []}
    universe = list(dict.fromkeys(
        [item["ticker"] for item in portfolio.get("holdings", [])]
        + profile.get("watchlist", [])
    ))
    # Chat only needs a recent trading year for its compact evidence summary.
    # The broader research/analysis workspaces retain their longer histories.
    research = security_research(_ticker_candidates(question, universe), price_limit=260)
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
    if portfolio_id:
        try:
            snapshot = database.latest_portfolio_health(user_id, portfolio_id)
        except Exception:
            snapshot = None
        if snapshot:
            overview = dict(snapshot.get("result") or {})
            evidence.append({"label": "Full cached portfolio intelligence", "as_of": overview.get("as_of"),
                             "url": None, "data": {
                                 "health": overview.get("health"), "holdings": overview.get("holdings"),
                                 "actions": overview.get("actions"), "changes": overview.get("changes"),
                                 "warnings": overview.get("warnings"),
                             }, "claim_type": "MODEL_OUTPUT"})
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
            timeout=(3, max(4, min(15, int(os.getenv("GEMINI_CHAT_TIMEOUT_SECONDS", "7"))))),
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


def _bounded_value(value: Any, depth: int = 0) -> Any:
    """Keep grounding useful while preventing oversized prompts from dominating latency."""
    if depth >= 4:
        return str(value)[:240]
    if isinstance(value, dict):
        return {str(key): _bounded_value(item, depth + 1) for key, item in list(value.items())[:24]}
    if isinstance(value, list):
        return [_bounded_value(item, depth + 1) for item in value[:8]]
    if isinstance(value, str):
        return value[:600]
    return value


def _clean_partial_answer(answer: str) -> str:
    """Never display a raw mid-token fragment when a provider exhausts its budget."""
    cleaned = answer.rstrip()
    boundary = max(cleaned.rfind("."), cleaned.rfind("!"), cleaned.rfind("?"))
    if boundary >= 20:
        cleaned = cleaned[:boundary + 1]
    return cleaned + "\n\nThe response was shortened to the completed evidence-backed points. Ask a focused follow-up for another detail."


def ask_gemini(question: str, evidence: list[dict[str, Any]], history: list[dict[str, Any]],
               conversation_summary: str = "") -> tuple[str, str]:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured in backend/.env")
    indexed = [_bounded_value({"id": f"S{index + 1}", **item}) for index, item in enumerate(evidence[:18])]
    prior = [{"role": item["role"], "content": str(item["content"])[:1200]} for item in history[-6:]]
    prompt = f"""You are the evidence-grounded decision-support assistant inside EagleEyes AI.
Use only the supplied evidence. Cite factual claims inline as [S1], [S2], etc.
Never invent prices, probabilities, fundamentals, dates, scores, allocations, or source URLs.
Every evidence item includes a claim_type. Explicitly distinguish verified facts, deterministic/model outputs,
market-implied expectations, user beliefs, and your own interpretation. Your prose is AI interpretation, not a financial fact.
State when evidence is missing, partial, stale, or unavailable; never interpret missing data as neutral.
Do not give a directive to buy or sell; explain tradeoffs and what the user should inspect.
Prediction markets may change scenario weights but never override quality, valuation, or risk controls.
Macro changes are not release surprises unless a source explicitly contains a consensus estimate.
When company and article evidence is supplied, separate company facts, reported management statements, and third-party interpretation.
Do not infer an industry pricing cycle from general company news. If specialized pricing, supply-chain, or consensus data is absent, say so explicitly.
For questions about when to sell, do not invent a sale date or price. Explain review triggers, upcoming catalysts, portfolio constraints, taxes, and evidence that would change the thesis.

Recent conversation: {json.dumps(prior, default=str)}
Earlier conversation summary: {conversation_summary or 'No earlier summary yet.'}
Evidence: {json.dumps(indexed, default=str)}
Question: {question}

Lead with a direct answer. Use only the evidence needed for this exact question; ignore unrelated optimizer, thesis, macro, or portfolio facts.
Then explain what matters, portfolio or thesis implications, uncertainty, and concrete next steps. When the question asks for a ranking or rebalance, provide the requested names in a readable numbered list and explain each one. Aim for 300–600 words when the evidence supports that depth; use concise headings and do not pad missing evidence.
End with one short 'What to verify' sentence. Finish sentences before adding more detail.
Do not add a sources list; the application manages source metadata separately."""
    contents: list[dict[str, Any]] = [{"role": "user", "parts": [{"text": prompt}]}]
    answer_parts: list[str] = []
    finish_reason = "UNKNOWN"
    # Gemini can return useful partial text with MAX_TOKENS. Continue it instead
    # of silently presenting the partial response as a finished answer.
    max_continuations = max(0, min(1, int(os.getenv("GEMINI_MAX_CONTINUATIONS", "0"))))
    first_budget = max(800, min(2200, int(os.getenv("GEMINI_CHAT_MAX_OUTPUT_TOKENS", "1600"))))
    for attempt in range(1 + max_continuations):
        payload = _gemini_request(api_key, model, contents, first_budget if attempt == 0 else 600)
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
        answer = _clean_partial_answer(answer)
    return answer, model


def draft_thesis_prose(evidence: dict[str, Any], starter: dict[str, str]) -> tuple[dict[str, str], str]:
    """Synthesize editable thesis prose without allowing the model to create financial facts."""
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash").strip()
    if not api_key:
        raise RuntimeError("AI synthesis is not configured")
    allowed_evidence = {
        "ticker": evidence.get("ticker"), "company": evidence.get("company"),
        "strengths": evidence.get("strengths") or [], "weaknesses": evidence.get("weaknesses") or [],
        "fundamental_trend": evidence.get("fundamental_trend") or {},
        "catalysts": evidence.get("catalysts") or [], "thesis_risks": evidence.get("thesis_risks") or [],
        "what_would_change_the_view": evidence.get("what_would_change_the_view"),
        "freshness": evidence.get("freshness") or {}, "field_coverage": evidence.get("field_coverage") or {},
    }
    prompt = f"""Create an editable investment-thesis prose draft from only the verified evidence below.
Return strict JSON with exactly four string keys: summary, base_case, bull_case, bear_case.
Write each case as a distinct short memo of 2–3 substantive paragraphs separated by blank lines. Each case must explain the outcome, why it could happen, the evidence or drivers that would confirm it, and what would weaken or disprove it. Do not return one-line cases or merely rename the same explanation three times.
Do not recommend buying or selling. Do not introduce any number, date, price, forecast, probability, threshold, or financial claim not explicitly present in the evidence.
Make missing information explicit instead of treating it as neutral. Distinguish a company-quality view from portfolio fit.
The user must review and explicitly save this draft; it is not a decision.

Verified evidence: {json.dumps(allowed_evidence, default=str)}
Fallback starter: {json.dumps(starter, default=str)}"""
    payload = _gemini_request(api_key, model, [{"role": "user", "parts": [{"text": prompt}]}], 900)
    text, _ = _candidate(payload)
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise RuntimeError("AI synthesis returned an invalid draft") from exc
    expected = {"summary", "base_case", "bull_case", "bear_case"}
    if set(parsed) != expected or not all(isinstance(parsed[key], str) and 2 <= len(parsed[key]) <= 4000 for key in expected):
        raise RuntimeError("AI synthesis returned an invalid draft")
    return {key: parsed[key].strip() for key in expected}, model


def classify_thesis_evidence(item: dict[str, Any], evidence_items: list[Any]) -> tuple[str, str, str | None, dict[str, str]]:
    """Classify a qualitative relationship without allowing the model to add facts."""
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash").strip()
    if not api_key:
        raise RuntimeError("AI qualitative monitoring is not configured")
    allowed = []
    for index, raw in enumerate(evidence_items[:8]):
        value = raw.model_dump(mode="json") if hasattr(raw, "model_dump") else dict(raw)
        allowed.append({"id": f"E{index + 1}", **value})
    prompt = f"""Classify how the supplied verified evidence relates to one saved investment-thesis item.
Return strict JSON with exactly: state, explanation, evidence_ids, evidence_relationships.
state must be one of SUPPORTS, WEAKENS, CONTRADICTS, UNCHANGED, UNRELATED, INSUFFICIENT_EVIDENCE.
Use only the supplied evidence. Do not add events, numbers, dates, probabilities, causes, forecasts, or financial facts.
If relevance or direction cannot be established from these facts, use INSUFFICIENT_EVIDENCE.
Prediction-market evidence is market-derived evidence, not ground truth. Low-quality or stale evidence cannot alone justify CONTRADICTS.
evidence_relationships must map every used evidence id to one allowed state so mixed evidence is preserved before summarization.
Keep explanation to one sentence and cite only supplied evidence ids. Do not recommend an investment action.

Saved item: {json.dumps({key: item.get(key) for key in ('id','description','category','importance','factor_type','evidence_mapping')}, default=str)}
Verified evidence: {json.dumps(allowed, default=str)}"""
    payload = _gemini_request(api_key, model, [{"role": "user", "parts": [{"text": prompt}]}], 500)
    text, _ = _candidate(payload)
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise RuntimeError("AI monitoring returned invalid structured output") from exc
    states = {"SUPPORTS", "WEAKENS", "CONTRADICTS", "UNCHANGED", "UNRELATED", "INSUFFICIENT_EVIDENCE"}
    ids = {item["id"] for item in allowed}
    if set(parsed) != {"state", "explanation", "evidence_ids", "evidence_relationships"} or parsed["state"] not in states:
        raise RuntimeError("AI monitoring returned invalid structured output")
    relationships = parsed["evidence_relationships"]
    if not isinstance(parsed["explanation"], str) or not isinstance(parsed["evidence_ids"], list) or not set(parsed["evidence_ids"]).issubset(ids):
        raise RuntimeError("AI monitoring returned invalid structured output")
    if not isinstance(relationships, dict) or not set(relationships).issubset(ids) or not all(value in states for value in relationships.values()):
        raise RuntimeError("AI monitoring returned invalid structured output")
    return parsed["state"], parsed["explanation"].strip(), model, relationships

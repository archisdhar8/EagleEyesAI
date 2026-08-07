from __future__ import annotations

import os
from typing import Any

import requests


SYSTEM_PROMPT = """You are a portfolio research narrator. Summarize only the supplied validated JSON.
Never add prices, facts, probabilities, returns, or recommendations that are absent from the input.
Clearly separate observed data from model estimates. Mention uncertainty and material tradeoffs.
Do not call any allocation the best portfolio and do not instruct the user to trade."""


def template_explanation(result: dict[str, Any]) -> str:
    scenario = max(result.get("scenarios", []), key=lambda item: item["probability"], default=None)
    balanced = next((item for item in result.get("alternatives", []) if item["name"] == "Balanced"), None)
    parts = ["This analysis compares transparent alternatives; it does not select a best portfolio or submit trades."]
    if scenario:
        prior_note = " and is substantially prior-driven" if scenario.get("is_prior") else ""
        parts.append(f"The highest-weight macro scenario is {scenario['label']} at {scenario['probability']:.0%}, with {scenario['confidence']:.0%} signal confidence{prior_note}.")
    if balanced:
        parts.append(f"The Balanced alternative models {balanced['expected_return']:.1%} annual return and {balanced['volatility']:.1%} volatility, with {balanced['turnover']:.1%} estimated one-way turnover.")
        parts.append(balanced["tradeoff"])
    parts.extend(result.get("warnings", []))
    return " ".join(parts)


def generate_explanation(result: dict[str, Any], provider: str, endpoint: str | None, model: str | None) -> dict[str, Any]:
    if provider == "disabled":
        return {"provider": "template", "text": template_explanation(result)}
    compact = {
        "macro": result.get("macro"), "scenarios": result.get("scenarios"),
        "alternatives": result.get("alternatives"), "warnings": result.get("warnings"),
        "data_lineage": result.get("data_lineage"),
    }
    try:
        if provider == "ollama":
            url = (endpoint or "http://127.0.0.1:11434").rstrip("/") + "/api/generate"
            response = requests.post(url, json={"model": model or "llama3.1:8b", "prompt": f"{SYSTEM_PROMPT}\n\n{compact}", "stream": False}, timeout=45)
            response.raise_for_status()
            text = response.json()["response"]
        else:
            url = (endpoint or "").rstrip("/") + "/chat/completions"
            if not endpoint:
                raise ValueError("An OpenAI-compatible endpoint is required")
            headers = {"Content-Type": "application/json"}
            if os.getenv("DASHBOARD_LLM_API_KEY"):
                headers["Authorization"] = f"Bearer {os.environ['DASHBOARD_LLM_API_KEY']}"
            response = requests.post(url, headers=headers, json={"model": model or "default", "temperature": 0.1, "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": str(compact)}]}, timeout=45)
            response.raise_for_status()
            text = response.json()["choices"][0]["message"]["content"]
        return {"provider": provider, "text": text}
    except (requests.RequestException, ValueError, KeyError, IndexError) as exc:
        return {"provider": "template", "text": template_explanation(result), "warning": f"Optional model unavailable ({type(exc).__name__}); used deterministic narrative."}


from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path
from typing import Any

import requests


APP_DIR = Path(__file__).resolve().parents[1]
CONTENT_DIR = APP_DIR / "content" / "learn"
CATALOG_PATH = CONTENT_DIR / "catalog.json"
MASTERY_THRESHOLD = 0.80


def load_catalog() -> dict[str, Any]:
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    validate_catalog(catalog)
    return catalog


def validate_catalog(catalog: dict[str, Any]) -> None:
    if not str(catalog.get("version", "")).startswith("learn-catalog-"):
        raise ValueError("Learning catalog version is missing")
    lessons = catalog.get("lessons") or []
    lesson_ids = {lesson.get("id") for lesson in lessons}
    source_ids = {source.get("id") for source in catalog.get("sources") or []}
    if not lessons or None in lesson_ids or len(lesson_ids) != len(lessons):
        raise ValueError("Learning lesson IDs must be present and unique")
    for module in catalog.get("modules") or []:
        if not module.get("content_version") or not module.get("outcomes"):
            raise ValueError(f"Module {module.get('id')} is missing outcomes or a content version")
        if any(lesson_id not in lesson_ids for lesson_id in module.get("lesson_ids") or []):
            raise ValueError(f"Module {module.get('id')} references an unknown lesson")
    for lesson in lessons:
        path = CONTENT_DIR / str(lesson.get("content_file", ""))
        if not lesson.get("content_version") or not lesson.get("concept_ids") or not lesson.get("source_refs"):
            raise ValueError(f"Lesson {lesson.get('id')} is missing versioned learning metadata")
        if not path.is_file() or CONTENT_DIR not in path.resolve().parents:
            raise ValueError(f"Lesson {lesson.get('id')} content is missing")
        if any(source_id not in source_ids for source_id in lesson["source_refs"]):
            raise ValueError(f"Lesson {lesson.get('id')} references an unknown source")
        quiz = lesson.get("quiz") or {}
        for question in quiz.get("questions") or []:
            options = question.get("options") or []
            if not options or question.get("correct") not in range(len(options)) or not question.get("explanation"):
                raise ValueError(f"Lesson {lesson.get('id')} has an invalid quiz question")


def catalog_payload(*, public_only: bool = False) -> dict[str, Any]:
    catalog = load_catalog()
    lessons = catalog["lessons"]
    if public_only:
        lessons = [lesson for lesson in lessons if lesson.get("public_preview")]
    allowed = {lesson["id"] for lesson in lessons}
    modules = []
    for module in catalog["modules"]:
        item = {**module, "lesson_ids": [lesson_id for lesson_id in module["lesson_ids"] if lesson_id in allowed]}
        modules.append(item)
    return {
        "version": catalog["version"],
        "preview_lesson_id": catalog["preview_lesson_id"],
        "modules": modules,
        "lessons": [{key: value for key, value in lesson.items() if key not in {"content_file", "quiz"}} | {
            "quiz_id": (lesson.get("quiz") or {}).get("id"),
            "quiz_question_count": len((lesson.get("quiz") or {}).get("questions") or []),
        } for lesson in lessons],
    }


def lesson_payload(lesson_id: str, *, public_only: bool = False, include_answers: bool = False) -> dict[str, Any]:
    catalog = load_catalog()
    lesson = next((item for item in catalog["lessons"] if item["id"] == lesson_id), None)
    if lesson is None:
        raise KeyError(lesson_id)
    if public_only and not lesson.get("public_preview"):
        raise PermissionError(lesson_id)
    path = CONTENT_DIR / lesson["content_file"]
    sources = {source["id"]: source for source in catalog["sources"]}
    quiz = lesson.get("quiz") or None
    if quiz and not include_answers:
        quiz = {
            "id": quiz["id"], "version": quiz["version"],
            "questions": [{"question": row["question"], "options": row["options"]} for row in quiz["questions"]],
        }
    return {
        **{key: value for key, value in lesson.items() if key not in {"content_file", "quiz", "public_preview"}},
        "content": path.read_text(encoding="utf-8"),
        "quiz": quiz,
        "sources": [sources[source_id] for source_id in lesson["source_refs"]],
    }


def quiz_definition(quiz_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    catalog = load_catalog()
    for lesson in catalog["lessons"]:
        quiz = lesson.get("quiz") or {}
        if quiz.get("id") == quiz_id:
            return lesson, quiz
    raise KeyError(quiz_id)


def grade_quiz(quiz_id: str, answers: list[int]) -> dict[str, Any]:
    lesson, quiz = quiz_definition(quiz_id)
    questions = quiz["questions"]
    if len(answers) != len(questions):
        raise ValueError(f"Submit exactly {len(questions)} answers")
    if any(not isinstance(answer, int) for answer in answers):
        raise ValueError("Quiz answers must be option indexes")
    score = sum(answer == question["correct"] for answer, question in zip(answers, questions, strict=True))
    percentage = score / len(questions) if questions else 0.0
    return {
        "module_id": lesson["module_id"], "lesson_id": lesson["id"], "content_version": lesson["content_version"],
        "quiz_id": quiz["id"], "quiz_version": quiz["version"], "score": score,
        "total_questions": len(questions), "percentage": round(percentage, 4),
        "mastery_eligible": percentage >= MASTERY_THRESHOLD,
        "feedback": [{"correct": answer == question["correct"], "correct_index": question["correct"], "explanation": question["explanation"]} for answer, question in zip(answers, questions, strict=True)],
    }


def calculate_lab(lab_id: str, inputs: dict[str, Any]) -> dict[str, Any]:
    def number(key: str, default: float, minimum: float = 0.0, maximum: float = 1_000_000_000.0) -> float:
        value = float(inputs.get(key, default))
        if not math.isfinite(value) or value < minimum or value > maximum:
            raise ValueError(f"{key} must be between {minimum:g} and {maximum:g}")
        return value

    if lab_id == "compound-growth":
        initial, monthly = number("initial", 1000), number("monthly", 200)
        years, annual_return = int(number("years", 20, 1, 60)), number("annual_return", .07, -.50, .50)
        monthly_rate = annual_return / 12
        periods = years * 12
        growth = initial * ((1 + monthly_rate) ** periods)
        contributions_growth = monthly * periods if abs(monthly_rate) < 1e-12 else monthly * (((1 + monthly_rate) ** periods - 1) / monthly_rate)
        final = growth + contributions_growth
        contributed = initial + monthly * periods
        result = {"final_value": round(final, 2), "contributed": round(contributed, 2), "modeled_growth": round(final - contributed, 2)}
        assumptions = ["Monthly contributions occur at period end", "Return is constant for illustration", "Taxes, fees, and volatility are excluded"]
    elif lab_id == "inflation":
        amount, years, rate = number("amount", 10000), int(number("years", 20, 1, 60)), number("inflation_rate", .025, 0, .25)
        result = {"future_purchasing_power": round(amount / ((1 + rate) ** years), 2), "nominal_amount": amount}
        assumptions = ["Inflation is constant for illustration", "Purchasing power is expressed in today's dollars"]
    elif lab_id == "fee-drag":
        initial, years = number("initial", 10000), int(number("years", 30, 1, 60))
        annual_return, low_fee, high_fee = number("annual_return", .07, -.50, .50), number("low_fee", .0005, 0, .10), number("high_fee", .01, 0, .10)
        low = initial * ((1 + annual_return - low_fee) ** years)
        high = initial * ((1 + annual_return - high_fee) ** years)
        result = {"low_fee_value": round(low, 2), "high_fee_value": round(high, 2), "difference": round(low - high, 2)}
        assumptions = ["Returns and expense ratios are constant", "No contributions, taxes, trading costs, or tracking differences"]
    elif lab_id == "drawdown-recovery":
        decline = number("decline", .30, 0, .95)
        result = {"decline": decline, "gain_required_to_recover": round(decline / (1 - decline), 4)}
        assumptions = ["Recovery is measured from the post-decline value", "Time, taxes, fees, and cash flows are excluded"]
    elif lab_id == "contribution-timing":
        monthly, years, delay = number("monthly", 200), int(number("years", 30, 1, 60)), int(number("delay_years", 5, 0, 30))
        rate = number("annual_return", .07, -.50, .50) / 12
        def annuity(months: int) -> float:
            return monthly * months if abs(rate) < 1e-12 else monthly * (((1 + rate) ** months - 1) / rate)
        start_now, delayed = annuity(years * 12), annuity(max(0, years - delay) * 12)
        result = {"start_now_value": round(start_now, 2), "delayed_value": round(delayed, 2), "modeled_difference": round(start_now - delayed, 2)}
        assumptions = ["Constant illustrative return", "Monthly contributions occur at period end", "Taxes, fees, and volatility are excluded"]
    elif lab_id == "diversification":
        count = int(number("positions", 5, 1, 100))
        largest = number("largest_weight", .40, 0, 1)
        average_correlation = number("average_correlation", .65, -1, 1)
        concentration = largest ** 2 + ((1 - largest) ** 2 / max(1, count - 1))
        result = {"positions": count, "largest_weight": largest, "concentration_index": round(concentration, 4), "average_correlation": average_correlation,
                  "interpretation": "concentrated" if largest > .25 or concentration > .20 else "moderately diversified" if average_correlation < .70 else "limited diversification"}
        assumptions = ["Remaining weight is evenly distributed", "Average correlation is illustrative and not a covariance model"]
    elif lab_id == "etf-overlap":
        first = {str(item).upper() for item in inputs.get("first_holdings", [])}  # type: ignore[union-attr]
        second = {str(item).upper() for item in inputs.get("second_holdings", [])}  # type: ignore[union-attr]
        union = first | second
        result = {"shared_holdings": sorted(first & second), "overlap_ratio": round(len(first & second) / len(union), 4) if union else 0.0}
        assumptions = ["Every supplied holding receives equal importance", "Production ETF overlap uses dated holding weights when available"]
    else:
        raise KeyError(lab_id)
    return {"lab_id": lab_id, "calculation_version": "learn-labs-v1", "inputs": inputs, "result": result, "assumptions": assumptions, "warning": "Educational illustration only; not a forecast or recommendation."}


def learning_tutor_answer(question: str, lesson: dict[str, Any], history: list[dict[str, Any]]) -> tuple[str, str, list[dict[str, Any]]]:
    sources = [{"id": f"L{index + 1}", **source} for index, source in enumerate(lesson["sources"])]
    source_metadata = [{"id": source["id"], "title": source["title"], "publisher": source["publisher"], "url": source["url"]} for source in sources]
    normalized = " ".join(question.lower().split())
    if re.search(r"\b(what|which|recommend|pick|best)\b.{0,45}\b(stock|etf|security|shares?)\b.{0,35}\b(buy|sell|own|choose|pick)?\b", normalized) or re.search(r"\b(buy|sell)\b.{0,35}\b(stock|etf|security|shares?)\b", normalized):
        citation = " [L1]" if sources else ""
        return (
            "I can explain how to research investments, but I can’t choose or recommend an individual security. "
            f"Use the lesson’s distinction between company evidence, valuation, and portfolio fit{citation}. "
            "Next, review the research checklist and compare evidence without treating the result as a trade instruction.",
            "learning-tutor-safety-v1", source_metadata,
        )
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured")
    prompt = f"""You are the learning tutor inside EagleEyes AI for a first-time investor age 18–30.
Use only the supplied lesson and sources. Explain rather than recommend. Cite factual claims as [L1], [L2], etc.
Never recommend a security, produce BUY/HOLD/SELL language, promise returns, invent current market data, or perform a new financial calculation.
If the question requires information outside the lesson, say what is missing and direct the learner to an authoritative source.

Lesson title: {lesson['title']}
Lesson content: {lesson['content']}
Sources: {sources}
Recent lesson conversation: {history[-6:]}
Question: {question}

Respond with a direct explanation, one simple example, one misconception or limitation, and a suggested next concept. Keep it under 350 words."""
    try:
        response = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
            json={"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.1, "maxOutputTokens": 900}},
            timeout=45,
        )
    except requests.RequestException as exc:
        raise RuntimeError("The learning tutor is temporarily unavailable") from exc
    if response.status_code >= 400:
        raise RuntimeError(response.json().get("error", {}).get("message", "The learning tutor request failed"))
    try:
        answer = "\n".join(part.get("text", "") for part in response.json()["candidates"][0]["content"]["parts"] if part.get("text")).strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("The learning tutor returned no answer") from exc
    if not answer:
        raise RuntimeError("The learning tutor returned no answer")
    return answer, model, source_metadata

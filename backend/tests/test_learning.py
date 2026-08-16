from __future__ import annotations

from fastapi.testclient import TestClient

from backend import database
from backend.auth import AuthenticatedUser, optional_user
from backend.learning import calculate_lab, grade_quiz, learning_tutor_answer, lesson_payload, load_catalog
from backend.main import app


USER_A = "00000000-0000-0000-0000-000000000001"
USER_B = "00000000-0000-0000-0000-000000000002"


def test_catalog_is_versioned_cited_and_internally_valid() -> None:
    catalog = load_catalog()
    assert catalog["version"] == "learn-catalog-v1"
    assert len(catalog["modules"]) == 3
    assert len(catalog["lessons"]) == 9
    assert all(row["outcomes"] and row["content_version"] for row in catalog["modules"])
    assert all(row["source_refs"] and row["eagleeyes_links"] for row in catalog["lessons"])


def test_public_learning_is_limited_to_the_approved_preview() -> None:
    with TestClient(app) as client:
        catalog = client.get("/api/learn/catalog")
        preview = client.get("/api/learn/lessons/why-invest")
        private = client.get("/api/learn/lessons/accounts-and-assets")
    assert catalog.status_code == 200
    assert [row["id"] for row in catalog.json()["lessons"]] == ["why-invest"]
    assert preview.status_code == 200
    assert "correct" not in preview.text
    assert private.status_code == 401


def test_signed_in_catalog_includes_progress_and_preferences() -> None:
    app.dependency_overrides[optional_user] = lambda: AuthenticatedUser(id=USER_A, email="test@example.com")
    with TestClient(app) as client:
        payload = client.get("/api/learn/catalog").json()
    assert len(payload["lessons"]) == 9
    assert payload["preferences"]["portfolio_context_enabled"] is False
    assert payload["progress"] == []


def test_learning_lab_golden_calculations() -> None:
    compound = calculate_lab("compound-growth", {"initial": 1000, "monthly": 0, "years": 1, "annual_return": .12})
    inflation = calculate_lab("inflation", {"amount": 100, "years": 1, "inflation_rate": .10})
    drawdown = calculate_lab("drawdown-recovery", {"decline": .50})
    overlap = calculate_lab("etf-overlap", {"first_holdings": ["AAPL", "MSFT"], "second_holdings": ["MSFT", "NVDA"]})
    assert compound["result"]["final_value"] == 1126.83
    assert inflation["result"]["future_purchasing_power"] == 90.91
    assert drawdown["result"]["gain_required_to_recover"] == 1.0
    assert overlap["result"] == {"shared_holdings": ["MSFT"], "overlap_ratio": .3333}
    assert compound["calculation_version"] == "learn-labs-v1"


def test_mastery_requires_completion_and_eighty_percent_quiz_score() -> None:
    with TestClient(app) as client:
        spoof = client.put("/api/learn/progress/why-invest", json={
            "module_id": "start-safely", "content_version": "2026.08.1",
            "status": "mastered", "completion_percentage": 1,
        })
        completed = client.put("/api/learn/progress/why-invest", json={
            "module_id": "start-safely", "content_version": "2026.08.1",
            "status": "completed", "completion_percentage": 1,
        })
        attempt = client.post("/api/learn/quizzes/why-invest-v1/attempts", json={"answers": [0, 1]})
    assert spoof.status_code == 422
    assert completed.status_code == 200
    assert attempt.status_code == 201
    assert attempt.json()["progress"]["status"] == "mastered"
    assert attempt.json()["progress"]["best_score"] == 1.0


def test_quiz_attempts_are_append_only_and_cross_user_progress_isolated() -> None:
    result = grade_quiz("why-invest-v1", [0, 1])
    database.save_learning_progress(USER_A, result["module_id"], result["lesson_id"], result["content_version"], "completed", 1)
    first = database.save_learning_quiz_attempt(USER_A, result, [0, 1])
    second = database.save_learning_quiz_attempt(USER_A, result, [0, 1])
    assert first["id"] != second["id"]
    assert len(database.list_learning_quiz_attempts(USER_A)) == 2
    assert database.list_learning_quiz_attempts(USER_B) == []
    assert database.list_learning_progress(USER_B) == []


def test_imported_quiz_attempt_identifier_is_idempotent() -> None:
    result = grade_quiz("why-invest-v1", [0, 1]) | {"attempt_id": "10000000-0000-4000-8000-000000000001"}
    first = database.save_learning_quiz_attempt(USER_A, result, [0, 1])
    second = database.save_learning_quiz_attempt(USER_A, result, [0, 1])
    assert first["id"] == second["id"]
    assert len(database.list_learning_quiz_attempts(USER_A)) == 1


def test_tutor_thread_ownership_is_enforced_by_database() -> None:
    thread = database.create_learning_tutor_thread(USER_A, "why-invest", "Compounding")
    database.save_learning_tutor_message(USER_A, thread["id"], "user", "Explain compounding")
    assert len(database.learning_tutor_messages(USER_A, thread["id"])) == 1
    try:
        database.learning_tutor_messages(USER_B, thread["id"])
    except KeyError:
        pass
    else:
        raise AssertionError("Another user was able to read the learning tutor thread")


def test_learning_tutor_refuses_stock_picking_without_calling_a_model() -> None:
    lesson = lesson_payload("fundamentals-and-valuation")
    answer, model, sources = learning_tutor_answer("Which stock should I buy?", lesson, [])
    assert "can’t choose or recommend" in answer
    assert "[L1]" in answer
    assert model == "learning-tutor-safety-v1"
    assert sources and sources[0]["url"].startswith("https://")

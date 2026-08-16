from __future__ import annotations

import argparse
import json
import os
import uuid
from collections import Counter
from typing import Any

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

from . import database
from .learning import lesson_payload, load_catalog


LESSON_ALIASES = {
    "what_is_investing": "why-invest",
    "what_youre_buying": "accounts-and-assets",
    "basics_of_risk": "risk-and-time",
    "risk_and_portfolio_thinking": "diversification-and-etfs",
    "costs_fees_tax_planning": "costs-rebalancing-and-declines",
    "what_moves_markets": "prices-and-expectations",
    "hype_vs_fundamentals": "fundamentals-and-valuation",
    "reading_market_signals": "macro-news-and-evidence",
}


def _table_exists(conn: psycopg.Connection, name: str) -> bool:
    return bool(conn.execute("select to_regclass(%s) is not null as present", (f"public.{name}",)).fetchone()["present"])


def _emails(conn: psycopg.Connection) -> dict[str, str]:
    return {str(row["email"]).strip().lower(): str(row["id"]) for row in conn.execute("select id,email from auth.users where email is not null").fetchall()}


def _legacy_rows(conn: psycopg.Connection) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    progress: list[dict[str, Any]] = []
    quizzes: list[dict[str, Any]] = []
    if _table_exists(conn, "user_progress"):
        columns = {row["column_name"] for row in conn.execute(
            "select column_name from information_schema.columns where table_schema='public' and table_name='user_progress'"
        ).fetchall()}
        rows = conn.execute("select * from public.user_progress").fetchall()
        if "progress_data" in columns:
            for row in rows:
                data = row.get("progress_data") or {}
                if isinstance(data, str): data = json.loads(data)
                for module_id, module in data.items():
                    for lesson_id in (module or {}).get("completed_lessons", []):
                        progress.append({"user_id": str(row["user_id"]), "module_id": module_id, "lesson_id": lesson_id})
        else:
            progress = [{"user_id": str(row["user_id"]), "module_id": row["module_id"], "lesson_id": row["lesson_id"]}
                        for row in rows if row.get("completed")]
    for table, final_quiz in (("lesson_quiz_scores", False), ("module_quiz_scores", True)):
        if not _table_exists(conn, table): continue
        for row in conn.execute(f"select * from public.{table}").fetchall():
            source_identity = row.get("id") or f"{row['user_id']}:{row.get('lesson_id')}:{row.get('attempted_at') or row.get('created_at') or row.get('score')}"
            quizzes.append({**dict(row), "final_quiz": final_quiz, "legacy_source": f"{table}:{source_identity}", "user_id": str(row["user_id"])})
    return progress, quizzes


def migrate(*, apply: bool = False) -> dict[str, int]:
    load_dotenv(database.ENV_PATH, override=False)
    old_url = os.getenv("FINLEARN_DATABASE_URL", "").strip()
    if not old_url:
        return {"source_unavailable": 1, "imported_progress": 0, "imported_quizzes": 0, "unmatched_users": 0, "skipped": 0}
    if not database.DATABASE_URL:
        raise RuntimeError("EagleEyes DATABASE_URL is required")
    if old_url == database.DATABASE_URL:
        raise RuntimeError("FINLEARN_DATABASE_URL must refer to the retired source, not EagleEyes")
    counts: Counter[str] = Counter()
    catalog = load_catalog()
    known_lessons = {lesson["id"] for lesson in catalog["lessons"]}
    with psycopg.connect(old_url, connect_timeout=10, sslmode="require", row_factory=dict_row) as old_conn, \
         psycopg.connect(database.DATABASE_URL, connect_timeout=10, sslmode="require", row_factory=dict_row) as new_conn:
        old_emails, new_emails = _emails(old_conn), _emails(new_conn)
        user_map = {old_id: new_emails[email] for email, old_id in old_emails.items() if email in new_emails}
        progress_rows, quiz_rows = _legacy_rows(old_conn)
    for row in progress_rows:
        new_user = user_map.get(row["user_id"])
        lesson_id = LESSON_ALIASES.get(row["lesson_id"], row["lesson_id"])
        if not new_user:
            counts["unmatched_users"] += 1; continue
        if lesson_id not in known_lessons:
            counts["skipped"] += 1; continue
        lesson = lesson_payload(lesson_id)
        counts["imported_progress"] += 1
        if apply:
            database.save_learning_progress(new_user, lesson["module_id"], lesson_id, lesson["content_version"], "completed", 1.0)
    for row in quiz_rows:
        if row["final_quiz"]:
            counts["skipped"] += 1; continue
        new_user = user_map.get(row["user_id"])
        lesson_id = LESSON_ALIASES.get(str(row.get("lesson_id") or ""), str(row.get("lesson_id") or ""))
        if not new_user:
            counts["unmatched_users"] += 1; continue
        if lesson_id not in known_lessons:
            counts["skipped"] += 1; continue
        lesson = lesson_payload(lesson_id)
        quiz = lesson.get("quiz") or {}
        total = int(row.get("total_questions") or len(quiz.get("questions") or []))
        score = int(row.get("best_score") or row.get("score") or 0)
        if not quiz or total != len(quiz.get("questions") or []):
            counts["skipped"] += 1; continue
        attempt_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"finlearn:{row['legacy_source']}"))
        if any(item["id"] == attempt_id for item in database.list_learning_quiz_attempts(new_user, lesson_id)):
            counts["skipped"] += 1
            continue
        result = {
            "module_id": lesson["module_id"], "lesson_id": lesson_id, "content_version": lesson["content_version"],
            "quiz_id": quiz["id"], "quiz_version": quiz["version"], "score": score, "total_questions": total,
            "percentage": min(1.0, max(0.0, score / total)),
            "attempt_id": attempt_id,
        }
        counts["imported_quizzes"] += 1
        if apply:
            database.save_learning_quiz_attempt(new_user, result, [-1] * total)
    return {"source_unavailable": 0, **{key: counts[key] for key in ("imported_progress", "imported_quizzes", "unmatched_users", "skipped")}}


def main() -> int:
    parser = argparse.ArgumentParser(description="Dry-run or import recoverable FinLearn progress into EagleEyes Supabase")
    parser.add_argument("--apply", action="store_true", help="Apply the verified email-matched import; default is dry-run")
    args = parser.parse_args()
    result = migrate(apply=args.apply)
    print(json.dumps({"mode": "apply" if args.apply else "dry-run", **result}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

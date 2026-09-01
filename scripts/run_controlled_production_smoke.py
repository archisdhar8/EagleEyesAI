#!/usr/bin/env python3
"""Small authenticated smoke suite for the owner-only production rollout.

It creates only synthetic chat/dashboard/job records for the supplied internal
account and cleans up chat/dashboard records on exit. It never refreshes a
provider, changes a portfolio, or invokes an administrative endpoint.
"""
from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from typing import Any

import httpx


PROMPTS = (
    ("portfolio_concentration", "Where is this portfolio most concentrated?"),
    ("company_comparison", "Compare AAPL and MSFT using current verified evidence."),
    ("macro_state", "What is the current macro state?"),
    ("prediction_relevance", "Which prediction-market developments are relevant to this portfolio?"),
    ("opportunity_ranking", "Rank the strongest research opportunities in this portfolio and explain the evidence limits."),
    ("scenario", "What happens to this portfolio in a rates-up growth-down scenario?"),
    ("mixed_domain", "How do the macro regime and current market state change the risks in this portfolio?"),
    ("visual", "Show the portfolio concentration visually."),
)


def find_values(value: Any, key: str) -> list[Any]:
    found: list[Any] = []
    if isinstance(value, dict):
        for current_key, current_value in value.items():
            if current_key == key:
                found.append(current_value)
            found.extend(find_values(current_value, key))
    elif isinstance(value, list):
        for item in value:
            found.extend(find_values(item, key))
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the controlled-production owner smoke suite.")
    parser.add_argument("--api-url", default=os.getenv("PRODUCTION_API_URL"))
    parser.add_argument("--token", default=os.getenv("PRODUCTION_OWNER_SMOKE_TOKEN"))
    parser.add_argument("--portfolio-id", default=os.getenv("PRODUCTION_OWNER_PORTFOLIO_ID"))
    parser.add_argument(
        "--gate", choices=("owner-self-test", "private-beta"), default="private-beta",
        help="Owner self-test skips durable heavy-job assertions because that topology has no worker.",
    )
    parser.add_argument("--keep-test-data", action="store_true")
    args = parser.parse_args()
    if os.getenv("RUN_CONTROLLED_PRODUCTION_SMOKE") != "1":
        raise SystemExit("Set RUN_CONTROLLED_PRODUCTION_SMOKE=1 to confirm synthetic production smoke writes.")
    if not args.api_url or not args.token or not args.portfolio_id:
        raise SystemExit("PRODUCTION_API_URL, PRODUCTION_OWNER_SMOKE_TOKEN, and PRODUCTION_OWNER_PORTFOLIO_ID are required.")

    headers = {"Authorization": f"Bearer {args.token}"}
    conversation_id: str | None = None
    dashboard_view_id: str | None = None
    report: dict[str, Any] = {"version": "controlled-production-owner-smoke-v1", "cases": []}
    with httpx.Client(base_url=args.api_url.rstrip("/"), headers=headers, timeout=30) as client:
        try:
            readiness = client.get("/api/health/readiness")
            readiness.raise_for_status()
            portfolios = client.get("/api/portfolios")
            portfolios.raise_for_status()
            assert args.portfolio_id in {str(row["id"]) for row in portfolios.json()}

            visual_response: dict[str, Any] | None = None
            for name, question in PROMPTS:
                request_id = f"production-smoke:{name}:{uuid.uuid4()}"
                response = client.post("/api/chat/messages", json={
                    "question": question,
                    "conversation_id": conversation_id,
                    "workspace": "portfolio",
                    "page_context": {"workspace": "portfolio", "portfolio_id": args.portfolio_id},
                    "request_id": request_id,
                })
                response.raise_for_status()
                payload = response.json()
                conversation_id = str(payload.get("conversation_id") or conversation_id or "") or None
                assert conversation_id, f"{name} did not persist a conversation"
                fingerprints = [value for value in find_values(payload, "input_fingerprint") if value]
                states = [str(value) for value in find_values(payload, "state")]
                assert (payload.get("message") or {}).get("structured_content"), f"{name} has no structured result"
                report["cases"].append({
                    "name": name, "status": "pass", "request_id": request_id,
                    "fingerprints": len(fingerprints), "current_read_models": states.count("CURRENT"),
                })
                if name == "visual":
                    visual_response = payload

            assert visual_response is not None
            draft_ids = [str(value) for value in find_values(visual_response, "resource_id") if value]
            assert draft_ids, "Visual request did not create a dashboard draft"
            draft_id = draft_ids[-1]
            saved = client.post(f"/api/dashboard/drafts/{draft_id}/save", json={"name": "Controlled production smoke"})
            saved.raise_for_status()
            dashboard_view_id = str(saved.json()["id"])
            reopened = client.get(f"/api/dashboard/views/{dashboard_view_id}")
            reopened.raise_for_status()
            assert str(reopened.json()["id"]) == dashboard_view_id
            report["cases"].append({"name": "dashboard_save_close_reopen", "status": "pass"})

            if args.gate == "private-beta":
                heavy = client.post("/api/chat/messages", json={
                    "question": "Run a five-year backtest of this portfolio against SPY.",
                    "conversation_id": conversation_id,
                    "workspace": "portfolio",
                    "page_context": {"workspace": "portfolio", "portfolio_id": args.portfolio_id},
                    "request_id": f"production-smoke:heavy:{uuid.uuid4()}",
                })
                heavy.raise_for_status()
                job_ids = [str(value) for value in find_values(heavy.json(), "job_id") if value]
                job_id = job_ids[0] if job_ids else None
                assert job_id, "Heavy request did not return a durable job reference"
                deadline = time.monotonic() + 180
                job: dict[str, Any] = {}
                while time.monotonic() < deadline:
                    job_response = client.get(f"/api/analytics/jobs/{job_id}")
                    job_response.raise_for_status()
                    job = job_response.json()
                    if job.get("status") in {"SUCCESS", "PARTIAL", "FAILED", "CANCELLED", "EXPIRED"}:
                        break
                    time.sleep(2)
                assert job.get("status") in {"SUCCESS", "PARTIAL"}, job
                assert job.get("worker_id") and job.get("result_reference")
                report["cases"].append({"name": "heavy_job_creation_completion", "status": "pass", "terminal_state": job["status"]})

                operations = client.get("/api/operations/metrics")
                operations.raise_for_status()
                health = operations.json()["analytics_jobs"]
                assert health["status"] == "healthy" and health.get("worker_heartbeat_age_seconds") is not None
                report["worker"] = health
            else:
                report["cases"].append({
                    "name": "heavy_jobs_disabled_by_topology",
                    "status": "pass",
                    "note": "Durable worker assertions are intentionally excluded from the owner self-test gate.",
                })
        finally:
            if not args.keep_test_data:
                if dashboard_view_id:
                    client.delete(f"/api/dashboard/views/{dashboard_view_id}")
                if conversation_id:
                    client.delete(f"/api/chat/conversations/{conversation_id}")

    report["ready"] = all(case["status"] == "pass" for case in report["cases"])
    print(json.dumps(report, indent=2))
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

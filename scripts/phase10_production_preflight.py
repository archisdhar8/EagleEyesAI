#!/usr/bin/env python3
"""Fail-closed preflight for EagleEyes controlled-production deployment.

The command is read-only: it inspects Git, configuration, and migration
metadata. It never applies migrations, writes to the database, or prints
secret values. Run once with ``--phase pre-deploy`` and again with
``--phase post-migration`` after the separately authorized migration step.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "supabase" / "migrations"
DEFAULT_MANIFEST = ROOT / "artifacts" / "phase10-production-identity-manifest.json"
CONFIRMATION_VALUE = "EAGLEEYES_CONTROLLED_PRODUCTION"

BASE_REQUIRED = (
    "PRODUCTION_API_URL", "PRODUCTION_FRONTEND_URL", "DATABASE_URL", "SUPABASE_URL",
    "SUPABASE_PUBLISHABLE_KEY", "CORS_ALLOWED_ORIGINS", "PRODUCTION_TARGET_ID", "EXPECTED_GIT_REVISION",
    "PRODUCTION_FRONTEND_SERVICE_ID", "PRODUCTION_API_SERVICE_ID",
    "PRODUCTION_BACKUP_ID", "PRODUCTION_BACKUP_VERIFIED_AT",
)
PRIVATE_BETA_REQUIRED = (
    "SENTRY_DSN", "PRODUCTION_ALERT_DESTINATION", "PROVIDER_INGESTION_SERVICE_IDS",
    "PRODUCTION_BACKUP_RESTORE_TESTED_AT", "ANALYTICS_WORKER_SERVICE_ID",
    "ANALYTICS_WORKER_CONCURRENCY", "ANALYTICS_WORKER_HEARTBEAT_MAX_AGE_SECONDS",
    "JOB_RECOVERY_SERVICE_ID", "JOB_RECOVERY_SCHEDULE",
    "READ_MODEL_RECONCILIATION_SERVICE_ID", "READ_MODEL_RECONCILIATION_SCHEDULE",
    "PROVIDER_INGESTION_SCHEDULE",
)
FLAG_NAMES = (
    "ASK_ROUTER_V2", "ASK_CAPABILITY_PLANNER_GEMINI", "ASK_GEMINI_ENRICHMENT",
    "PREDICTION_MARKET_ENRICHMENT_ENABLED", "CONVERSATIONAL_DASHBOARDS_ENABLED",
    "HEAVY_ANALYTICS_ENABLED", "SIMULATION_ENABLED", "OPTIMIZER_ENABLED",
    "BACKTESTING_ENABLED", "DEEP_COMPANY_RESEARCH_ENABLED",
)
HEAVY_FLAG_NAMES = (
    "HEAVY_ANALYTICS_ENABLED", "SIMULATION_ENABLED", "OPTIMIZER_ENABLED",
    "BACKTESTING_ENABLED", "DEEP_COMPANY_RESEARCH_ENABLED",
)
SELF_TEST_WORKFLOW_REQUIREMENTS = {
    ".github/workflows/ingest-daily.yml": ("schedule:", "backend.ingestion refresh --providers polygon,fred,news,regimes", "reconcile_read_models.py"),
    ".github/workflows/ingest-sec.yml": ("schedule:", "backend.ingestion refresh --providers sec", "reconcile_read_models.py"),
    ".github/workflows/ingest-markets.yml": ("schedule:", "backend.ingestion refresh --providers markets", "reconcile_read_models.py"),
    ".github/workflows/self-test-maintenance.yml": ("schedule:", "environment: production", "reconcile_read_models.py"),
}


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def configured(name: str) -> bool:
    value = os.getenv(name, "").strip()
    lowered = value.lower()
    return bool(value and "your-" not in lowered and "example" not in lowered and "changeme" not in lowered)


def parse_time(name: str) -> datetime | None:
    try:
        value = datetime.fromisoformat(os.getenv(name, "").strip().replace("Z", "+00:00"))
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def project_ref(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host.split(".", 1)[0]


def expected_migrations() -> dict[str, str]:
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(MIGRATIONS.glob("*.sql"))}


def load_manifest() -> tuple[dict[str, object], str | None]:
    path = Path(os.getenv("PRODUCTION_IDENTITY_MANIFEST", str(DEFAULT_MANIFEST))).expanduser()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}, None if isinstance(payload, dict) else "InvalidManifestRoot"
    except Exception as exc:
        return {}, type(exc).__name__


def text_value(value: object) -> str:
    return str(value).strip() if value is not None else ""


def self_test_topology_checks(manifest: dict[str, object]) -> dict[str, bool]:
    deployment = manifest.get("deployment") if isinstance(manifest.get("deployment"), dict) else {}
    services = deployment.get("services") if isinstance(deployment.get("services"), dict) else {}
    worker = services.get("worker") if isinstance(services.get("worker"), dict) else {}
    recovery = services.get("recovery") if isinstance(services.get("recovery"), dict) else {}
    reconciliation = services.get("reconciliation") if isinstance(services.get("reconciliation"), dict) else {}
    ingestion = services.get("ingestion") if isinstance(services.get("ingestion"), list) else []
    workflow_ids = {
        text_value(item.get("id")) for item in ingestion
        if isinstance(item, dict) and text_value(item.get("provider")) == "github_actions"
    }
    expected_ingestion_ids = {
        "github-actions:.github/workflows/ingest-daily.yml",
        "github-actions:.github/workflows/ingest-sec.yml",
        "github-actions:.github/workflows/ingest-markets.yml",
    }
    workflow_files_valid = all(
        (ROOT / relative).is_file()
        and all(token in (ROOT / relative).read_text(encoding="utf-8") for token in tokens)
        for relative, tokens in SELF_TEST_WORKFLOW_REQUIREMENTS.items()
    )
    render = (ROOT / "render.yaml").read_text(encoding="utf-8")
    return {
        "self_test_profile_declared": deployment.get("profile") == "owner_self_test",
        "self_test_manifest_deployable": manifest.get("self_test_deployable") is True,
        "self_test_worker_explicitly_disabled": worker.get("mode") == "disabled" and not text_value(worker.get("id")),
        "self_test_recovery_explicitly_disabled": recovery.get("mode") == "disabled" and not text_value(recovery.get("id")),
        "self_test_reconciliation_uses_github_actions": reconciliation.get("provider") == "github_actions" and text_value(reconciliation.get("id")) == "github-actions:.github/workflows/self-test-maintenance.yml",
        "self_test_ingestion_uses_github_actions": workflow_ids == expected_ingestion_ids,
        "self_test_workflow_contracts_valid": workflow_files_valid,
        "self_test_render_is_free_api_only": "plan: free" in render and "type: worker" not in render and "type: cron" not in render,
        "self_test_heavy_jobs_disabled": all(os.getenv(name, "").strip() == "0" for name in HEAVY_FLAG_NAMES),
    }


def required_check_names(gate: str, checks: dict[str, bool]) -> set[str]:
    common = {
        *(f"configured:{name}" for name in BASE_REQUIRED),
        *(f"flag_explicit:{name}" for name in FLAG_NAMES),
        "environment_is_production", "manifest_loaded", "manifest_schema",
        "manifest_environment_is_production", "explicit_production_confirmation",
        "clean_worktree", "manifest_requires_clean_worktree", "expected_revision_matches",
        "deployment_target_matches", "database_identity_verified", "database_host_matches",
        "database_name_matches_url", "supabase_identity_verified", "supabase_project_matches",
        "frontend_service_matches", "api_service_matches", "https_api", "https_frontend",
        "https_supabase", "cors_exactly_matches_manifest", "cors_contains_frontend",
        "cors_has_no_wildcard", "cors_has_no_localhost", "cors_credentials_disabled",
        "feature_flags_match_manifest", "backup_recent", "declared_pending_are_repo_migrations",
        "declared_pending_preserve_order", "database_read_succeeded",
        "connected_database_name_matches", "migration_checksums_match",
        "no_unknown_applied_migrations", "applied_migrations_are_prefix",
        "migration_state_matches_phase",
    }
    if gate == "owner-self-test":
        return common | {name for name in checks if name.startswith("self_test_")}
    return common | {
        *(f"configured:{name}" for name in PRIVATE_BETA_REQUIRED),
        "manifest_private_beta_deployable", "worker_service_matches",
        "recovery_service_matches", "reconciliation_service_matches",
        "ingestion_services_match", "worker_concurrency_bounded",
        "backup_restore_test_recorded",
    }


def migration_state(database_url: str) -> tuple[dict[str, str], str | None, str | None]:
    try:
        import psycopg
        with psycopg.connect(database_url, connect_timeout=15, sslmode=os.getenv("DB_SSLMODE", "require")) as conn:
            conn.execute("SET TRANSACTION READ ONLY")
            exists = conn.execute("SELECT to_regclass('public.app_schema_migrations') IS NOT NULL").fetchone()[0]
            if not exists:
                database_name = conn.execute("SELECT current_database()").fetchone()[0]
                return {}, str(database_name), None
            rows = conn.execute("SELECT version, checksum FROM public.app_schema_migrations ORDER BY version").fetchall()
            database_name = conn.execute("SELECT current_database()").fetchone()[0]
            return {row[0]: row[1] for row in rows}, str(database_name), None
    except Exception as exc:
        return {}, None, type(exc).__name__


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only controlled-production release preflight")
    parser.add_argument("--phase", choices=("pre-deploy", "post-migration"), default="pre-deploy")
    parser.add_argument(
        "--gate", choices=("owner-self-test", "private-beta"), default="private-beta",
        help="Owner self-test permits the zero-cost topology; private beta retains every operational gate.",
    )
    args = parser.parse_args()

    revision = git("rev-parse", "HEAD")
    dirty = bool(git("status", "--porcelain"))
    manifest, manifest_error = load_manifest()
    release = manifest.get("release") if isinstance(manifest.get("release"), dict) else {}
    database_identity = manifest.get("database") if isinstance(manifest.get("database"), dict) else {}
    supabase_identity = manifest.get("supabase") if isinstance(manifest.get("supabase"), dict) else {}
    deployment = manifest.get("deployment") if isinstance(manifest.get("deployment"), dict) else {}
    services = deployment.get("services") if isinstance(deployment.get("services"), dict) else {}
    cors_manifest = manifest.get("cors") if isinstance(manifest.get("cors"), dict) else {}
    manifest_flags = manifest.get("feature_flags") if isinstance(manifest.get("feature_flags"), dict) else {}
    checks = {f"configured:{name}": configured(name) for name in (*BASE_REQUIRED, *PRIVATE_BETA_REQUIRED)}
    checks.update({f"flag_explicit:{name}": os.getenv(name, "").strip() in {"0", "1"} for name in FLAG_NAMES})

    database_url = os.getenv("DATABASE_URL", "").strip()
    parsed_database = urlparse(database_url)
    frontend_url = os.getenv("PRODUCTION_FRONTEND_URL", "").rstrip("/")
    cors = {item.strip().rstrip("/") for item in os.getenv("CORS_ALLOWED_ORIGINS", "").split(",") if item.strip()}
    expected_cors = {str(item).strip().rstrip("/") for item in cors_manifest.get("allowed_origins", []) if str(item).strip()}
    ingestion_manifest = services.get("ingestion") if isinstance(services.get("ingestion"), list) else []
    expected_ingestion_ids = [text_value(item.get("id")) for item in ingestion_manifest if isinstance(item, dict)]
    runtime_ingestion_ids = [item.strip() for item in os.getenv("PROVIDER_INGESTION_SERVICE_IDS", "").split(",") if item.strip()]
    now = datetime.now(timezone.utc)
    backup_verified = parse_time("PRODUCTION_BACKUP_VERIFIED_AT")
    restore_tested = parse_time("PRODUCTION_BACKUP_RESTORE_TESTED_AT")
    checks.update({
        "environment_is_production": os.getenv("APP_ENV", "").strip().lower() == "production",
        "manifest_loaded": manifest_error is None,
        "manifest_schema": manifest.get("schema_version") == "eagleeyes-production-identity-v1",
        "manifest_environment_is_production": manifest.get("environment") == "production" and deployment.get("environment_marker") == "production",
        "manifest_private_beta_deployable": manifest.get("deployable") is True,
        "explicit_production_confirmation": os.getenv("PRODUCTION_RELEASE_CONFIRMATION") == CONFIRMATION_VALUE,
        "clean_worktree": not dirty,
        "manifest_requires_clean_worktree": release.get("clean_worktree_required") is True,
        "expected_revision_matches": bool(text_value(release.get("expected_git_revision"))) and os.getenv("EXPECTED_GIT_REVISION", "").strip() == revision == text_value(release.get("expected_git_revision")),
        "deployment_target_matches": bool(text_value(deployment.get("expected_target_id"))) and os.getenv("PRODUCTION_TARGET_ID") == text_value(deployment.get("expected_target_id")),
        "database_identity_verified": database_identity.get("identity_verified") is True,
        "database_host_matches": bool(text_value(database_identity.get("expected_host"))) and (parsed_database.hostname or "").lower() == text_value(database_identity.get("expected_host")).lower(),
        "database_name_matches_url": bool(text_value(database_identity.get("expected_name"))) and parsed_database.path.lstrip("/") == text_value(database_identity.get("expected_name")),
        "supabase_identity_verified": supabase_identity.get("identity_verified") is True,
        "supabase_project_matches": bool(text_value(supabase_identity.get("expected_project_ref"))) and project_ref(os.getenv("SUPABASE_URL", "")) == text_value(supabase_identity.get("expected_project_ref")).lower(),
        "frontend_service_matches": bool(text_value((services.get("frontend") or {}).get("id"))) and os.getenv("PRODUCTION_FRONTEND_SERVICE_ID") == text_value((services.get("frontend") or {}).get("id")),
        "api_service_matches": bool(text_value((services.get("api") or {}).get("id"))) and os.getenv("PRODUCTION_API_SERVICE_ID") == text_value((services.get("api") or {}).get("id")),
        "worker_service_matches": bool(text_value((services.get("worker") or {}).get("id"))) and os.getenv("ANALYTICS_WORKER_SERVICE_ID") == text_value((services.get("worker") or {}).get("id")),
        "recovery_service_matches": bool(text_value((services.get("recovery") or {}).get("id"))) and os.getenv("JOB_RECOVERY_SERVICE_ID") == text_value((services.get("recovery") or {}).get("id")),
        "reconciliation_service_matches": bool(text_value((services.get("reconciliation") or {}).get("id"))) and os.getenv("READ_MODEL_RECONCILIATION_SERVICE_ID") == text_value((services.get("reconciliation") or {}).get("id")),
        "ingestion_services_match": bool(expected_ingestion_ids) and all(expected_ingestion_ids) and runtime_ingestion_ids == expected_ingestion_ids,
        "https_api": urlparse(os.getenv("PRODUCTION_API_URL", "")).scheme == "https",
        "https_frontend": urlparse(os.getenv("PRODUCTION_FRONTEND_URL", "")).scheme == "https",
        "https_supabase": urlparse(os.getenv("SUPABASE_URL", "")).scheme == "https",
        "cors_exactly_matches_manifest": bool(expected_cors) and cors == expected_cors,
        "cors_contains_frontend": bool(frontend_url and frontend_url in cors),
        "cors_has_no_wildcard": "*" not in cors and cors_manifest.get("wildcard_allowed") is False,
        "cors_has_no_localhost": all("localhost" not in origin and "127.0.0.1" not in origin for origin in cors),
        "cors_credentials_disabled": cors_manifest.get("allow_credentials") is False,
        "feature_flags_match_manifest": all(os.getenv(name, "").strip() == text_value(manifest_flags.get(name)) for name in FLAG_NAMES),
        "worker_concurrency_bounded": os.getenv("ANALYTICS_WORKER_CONCURRENCY", "") in {"1", "2", "3", "4"},
        "backup_recent": bool(backup_verified and 0 <= (now - backup_verified).total_seconds() <= 86_400),
        "backup_restore_test_recorded": bool(restore_tested and restore_tested <= now),
    })
    checks.update(self_test_topology_checks(manifest))

    expected = expected_migrations()
    repo_order = list(expected)
    declared_pending = [str(item) for item in manifest.get("expected_pending_migrations", [])] if isinstance(manifest.get("expected_pending_migrations"), list) else []
    checks["declared_pending_are_repo_migrations"] = all(item in expected for item in declared_pending)
    checks["declared_pending_preserve_order"] = declared_pending == [item for item in repo_order if item in declared_pending]

    applied: dict[str, str] = {}
    actual_database_name: str | None = None
    db_error: str | None = "configuration_gate_failed"
    identity_gate = all(checks[name] for name in (
        "environment_is_production", "explicit_production_confirmation", "database_host_matches",
        "database_name_matches_url", "supabase_project_matches", "deployment_target_matches",
        "database_identity_verified", "supabase_identity_verified", "manifest_loaded", "manifest_schema",
    )) and configured("DATABASE_URL")
    if identity_gate:
        applied, actual_database_name, db_error = migration_state(database_url)
    applied_repo = [name for name in repo_order if name in applied]
    actual_pending = [name for name in repo_order if name not in applied]
    checksum_mismatches = [name for name in applied_repo if applied[name] != expected[name]]
    unknown_applied = sorted(set(applied) - set(expected))
    checks.update({
        "database_read_succeeded": db_error is None,
        "connected_database_name_matches": actual_database_name == text_value(database_identity.get("expected_name")),
        "migration_checksums_match": not checksum_mismatches,
        "no_unknown_applied_migrations": not unknown_applied,
        "applied_migrations_are_prefix": applied_repo == repo_order[:len(applied_repo)],
        "migration_state_matches_phase": (
            actual_pending == declared_pending if args.phase == "pre-deploy" else not actual_pending
        ),
    })

    required_for_gate = required_check_names(args.gate, checks)
    failed = sorted(name for name in required_for_gate if not checks.get(name, False))
    owner_self_test_required = required_check_names("owner-self-test", checks)
    owner_self_test_gaps = sorted(name for name in owner_self_test_required if not checks.get(name, False))
    private_beta_required = required_check_names("private-beta", checks)
    private_beta_gaps = sorted(name for name in private_beta_required if not checks.get(name, False))
    print(json.dumps({
        "version": "phase10-controlled-production-preflight-v2",
        "phase": args.phase,
        "gate": args.gate,
        "ready": not failed,
        "ready_for_owner_self_test": not owner_self_test_gaps,
        "ready_for_private_beta": not private_beta_gaps,
        "revision": revision,
        "dirty": dirty,
        "identity_manifest": {
            "loaded": manifest_error is None,
            "error_class": manifest_error,
            "schema_version": manifest.get("schema_version"),
            "self_test_deployable": manifest.get("self_test_deployable") is True,
            "deployable": manifest.get("deployable") is True,
        },
        "migration_summary": {
            "repository_count": len(repo_order), "applied_count": len(applied_repo),
            "pending": actual_pending, "declared_pending": declared_pending,
            "checksum_mismatches": checksum_mismatches, "unknown_applied": unknown_applied,
            "database_read_error_class": db_error,
        },
        "checks": checks,
        "failed_checks": failed,
        "owner_self_test_gaps": owner_self_test_gaps,
        "private_beta_gaps": private_beta_gaps,
        "secrets_printed": False,
        "mutations_performed": False,
    }, indent=2))
    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())

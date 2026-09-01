from __future__ import annotations

import json
from pathlib import Path

from scripts import phase10_production_preflight as preflight


ROOT = Path(__file__).resolve().parents[2]


def owner_manifest() -> dict[str, object]:
    manifest = json.loads(
        (ROOT / "docs/templates/owner-self-test-identity-manifest.json").read_text(encoding="utf-8")
    )
    manifest["self_test_deployable"] = True
    return manifest


def test_owner_self_test_topology_is_free_and_disables_heavy_jobs(monkeypatch):
    for name in preflight.HEAVY_FLAG_NAMES:
        monkeypatch.setenv(name, "0")

    checks = preflight.self_test_topology_checks(owner_manifest())

    assert checks
    assert all(checks.values()), checks


def test_owner_gate_does_not_require_private_beta_operations():
    checks = {"self_test_profile_declared": True}

    owner = preflight.required_check_names("owner-self-test", checks)
    private_beta = preflight.required_check_names("private-beta", checks)

    assert "configured:SENTRY_DSN" not in owner
    assert "configured:ANALYTICS_WORKER_SERVICE_ID" not in owner
    assert "backup_restore_test_recorded" not in owner
    assert "worker_service_matches" not in owner
    assert "self_test_profile_declared" in owner

    assert "configured:SENTRY_DSN" in private_beta
    assert "configured:ANALYTICS_WORKER_SERVICE_ID" in private_beta
    assert "backup_restore_test_recorded" in private_beta
    assert "worker_service_matches" in private_beta
    assert "manifest_private_beta_deployable" in private_beta


def test_private_beta_remains_the_default_preflight_gate():
    source = (ROOT / "scripts/phase10_production_preflight.py").read_text(encoding="utf-8")

    assert 'choices=("owner-self-test", "private-beta"), default="private-beta"' in source

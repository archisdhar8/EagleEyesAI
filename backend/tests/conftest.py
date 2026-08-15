from __future__ import annotations

import pytest

from backend import database
from backend.auth import AuthenticatedUser, require_user
from backend.main import app


@pytest.fixture(autouse=True)
def isolated_database(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DATABASE_URL", None)
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "test-dashboard.db")
    database.initialize()
    app.dependency_overrides[require_user] = lambda: AuthenticatedUser(id="00000000-0000-0000-0000-000000000001", email="test@example.com")
    yield
    app.dependency_overrides.clear()

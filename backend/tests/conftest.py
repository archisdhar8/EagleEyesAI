from __future__ import annotations

import pytest

from backend import database


@pytest.fixture(autouse=True)
def isolated_database(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DATABASE_URL", None)
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "test-dashboard.db")
    database.initialize()
    yield

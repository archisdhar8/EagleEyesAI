from datetime import datetime
from unittest.mock import Mock, patch

from backend import ingestion


def test_fred_refresh_uses_central_provider_date_at_utc_boundary(monkeypatch):
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            value = datetime(2026, 8, 12, 4, 30, tzinfo=ingestion.timezone.utc)
            return value.astimezone(tz) if tz else value.replace(tzinfo=None)

    connection = Mock()
    connection.execute.return_value.fetchall.return_value = []
    cursor = Mock()
    cursor_context = Mock()
    cursor_context.__enter__ = Mock(return_value=cursor)
    cursor_context.__exit__ = Mock(return_value=False)
    connection.cursor.return_value = cursor_context
    context = Mock()
    context.__enter__ = Mock(return_value=connection)
    context.__exit__ = Mock(return_value=False)
    response = Mock()
    response.json.return_value = {"observations": []}
    response.status_code = 200

    monkeypatch.setattr(ingestion, "datetime", FixedDateTime)
    monkeypatch.setattr(ingestion.database, "postgres_connection", lambda: context)
    monkeypatch.setenv("FRED_API_KEY", "fixture")
    with patch.object(ingestion.requests.Session, "get", return_value=response) as get:
        ingestion.refresh_fred()

    params = get.call_args_list[0].kwargs["params"]
    assert params["realtime_start"] == "2026-08-11"
    assert params["realtime_end"] == "2026-08-11"

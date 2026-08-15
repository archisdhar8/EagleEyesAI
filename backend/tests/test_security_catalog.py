from unittest.mock import Mock, patch

from backend.ingestion import refresh_security_catalog


def test_security_catalog_pages_common_stocks_and_labels_adrs(monkeypatch):
    cs = Mock()
    cs.ok = True
    cs.json.return_value = {"results": [{"ticker": "AAPL", "name": "Apple Inc.", "type": "CS", "active": True}]}
    adr = Mock()
    adr.ok = True
    adr.json.return_value = {"results": [{"ticker": "XYZ", "name": "Example ADR", "type": "ADRC", "active": True}]}
    connection = Mock()
    cursor = Mock()
    cursor_context = Mock()
    cursor_context.__enter__ = Mock(return_value=cursor)
    cursor_context.__exit__ = Mock(return_value=False)
    connection.cursor.return_value = cursor_context
    context = Mock()
    context.__enter__ = Mock(return_value=connection)
    context.__exit__ = Mock(return_value=False)
    monkeypatch.setenv("POLYGON_API_KEY", "fixture")
    monkeypatch.setattr("backend.ingestion.database.postgres_connection", lambda: context)
    with patch("backend.ingestion.requests.Session.get", side_effect=[cs, adr]):
        assert refresh_security_catalog() == 2
    rows = cursor.executemany.call_args.args[1]
    assert rows[0][0:2] == ("AAPL", "Apple Inc.")
    assert rows[0][6] == "core_us"
    assert rows[1][6] == "conditional_adr"

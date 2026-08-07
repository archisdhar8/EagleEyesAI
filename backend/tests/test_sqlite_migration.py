from backend.migrate_sqlite import stable_uuid


def test_legacy_ids_map_to_stable_distinct_uuids() -> None:
    assert stable_uuid("portfolio", 1) == stable_uuid("portfolio", 1)
    assert stable_uuid("portfolio", 1) != stable_uuid("portfolio", 2)
    assert stable_uuid("portfolio", 1) != stable_uuid("profile", 1)

from pathlib import Path

from backend.migrations import migration_checksum, migration_files


def test_initial_migration_is_discoverable() -> None:
    files = migration_files()
    assert files
    assert files == sorted(files)
    assert files[0].name == "202608070001_initial_schema.sql"


def test_migration_checksum_is_stable() -> None:
    path = Path(__file__).resolve().parents[2] / "supabase" / "migrations" / "202608070001_initial_schema.sql"
    assert migration_checksum(path) == migration_checksum(path)
    assert len(migration_checksum(path)) == 64

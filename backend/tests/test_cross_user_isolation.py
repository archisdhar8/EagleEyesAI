from __future__ import annotations

from pathlib import Path

import pytest

from backend import database
from backend.dashboard_workspace import compile_spec, deterministic_plan


USER_A = "00000000-0000-4000-8000-00000000000a"
USER_B = "00000000-0000-4000-8000-00000000000b"


def test_saved_layouts_and_ai_boards_are_owner_isolated() -> None:
    layout = database.save_terminal_layout(
        USER_A, "Private terminal", [{"id": "prices", "type": "price_board", "size": "wide"}]
    )
    assert [item["id"] for item in database.list_terminal_layouts(USER_A)] == [layout["id"]]
    assert database.list_terminal_layouts(USER_B) == []
    with pytest.raises(KeyError):
        database.delete_terminal_layout(layout["id"], USER_B)

    plan = deterministic_plan("Show my portfolio return")
    spec = compile_spec(plan)
    job = database.create_dashboard_job(USER_A, "Show my portfolio return")
    database.update_dashboard_job(
        job["id"], USER_A, state="COMPLETE", progress=100,
        plan=plan.model_dump(mode="json"), specification=spec, widget_results=[],
    )
    view = database.save_dashboard_view(USER_A, job["id"], "Private board")
    assert [item["id"] for item in database.list_dashboard_views(USER_A)] == [view["id"]]
    assert database.list_dashboard_views(USER_B) == []
    with pytest.raises(KeyError):
        database.get_dashboard_view(view["id"], USER_B)


def test_supabase_migrations_keep_rls_owner_contracts() -> None:
    root = Path(__file__).parents[2]
    dashboard_sql = (root / "supabase/migrations/202608090003_ai_dashboard_workspace.sql").read_text()
    terminal_sql = (root / "supabase/migrations/202608090006_market_workspace_reorganization.sql").read_text()
    revisions_sql = (root / "supabase/migrations/202608090011_ai_board_versions_and_revisions.sql").read_text()
    for table in ("dashboard_jobs", "dashboard_views", "dashboard_view_runs"):
        assert f"alter table public.{table} enable row level security" in dashboard_sql
    assert dashboard_sql.count("user_id = auth.uid()") >= 4
    assert "terminal_layouts_owner_all" in terminal_sql
    assert "using (user_id = auth.uid()) with check (user_id = auth.uid())" in terminal_sql
    assert "dashboard_view_revisions_owner_select" in revisions_sql
    assert "user_id = auth.uid()" in revisions_sql

-- Close inherited public-schema privileges without rewriting migration history.
revoke all on public.dashboard_view_revisions from anon;

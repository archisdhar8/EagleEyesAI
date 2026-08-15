revoke all privileges on table public.financial_goals from anon;
revoke all privileges on table public.goal_account_allocations from anon;
revoke all privileges on table public.terminal_layouts from anon;

comment on table public.financial_goals is
  'Authenticated, owner-scoped supporting planning goals. Anonymous access is explicitly revoked.';
comment on table public.terminal_layouts is
  'Authenticated, owner-scoped manual Advanced terminal layouts. Anonymous access is explicitly revoked.';

-- EagleEyes Phase 8: immutable decision context and append-only retrospective reviews.
create table if not exists public.decision_context_snapshots (
  id uuid primary key default gen_random_uuid(),
  decision_id uuid not null unique references public.investment_decisions(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  ticker text not null,
  decision_date timestamptz not null,
  snapshot jsonb not null,
  methodology_version text not null default 'decision-context-v1',
  captured_at timestamptz not null default now()
);

create table if not exists public.decision_retrospectives (
  id uuid primary key default gen_random_uuid(),
  decision_id uuid not null references public.investment_decisions(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  horizon_key text not null,
  window_start timestamptz not null,
  window_end timestamptz not null,
  structured_result jsonb not null,
  user_notes text not null default '',
  ai_summary text,
  ai_model text,
  summary_version text,
  reviewed_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  unique(decision_id,horizon_key,window_end)
);

create index if not exists decision_context_snapshots_user_idx on public.decision_context_snapshots(user_id,decision_date desc);
create index if not exists decision_retrospectives_user_idx on public.decision_retrospectives(user_id,reviewed_at desc);
alter table public.decision_context_snapshots enable row level security;
alter table public.decision_retrospectives enable row level security;
revoke all on public.decision_context_snapshots,public.decision_retrospectives from anon;
grant select,insert on public.decision_context_snapshots,public.decision_retrospectives to authenticated;
create policy decision_context_snapshots_owner_select on public.decision_context_snapshots for select to authenticated using(user_id=auth.uid());
create policy decision_context_snapshots_owner_insert on public.decision_context_snapshots for insert to authenticated with check(user_id=auth.uid() and exists(select 1 from public.investment_decisions d where d.id=decision_id and d.user_id=auth.uid()));
create policy decision_retrospectives_owner_select on public.decision_retrospectives for select to authenticated using(user_id=auth.uid());
create policy decision_retrospectives_owner_insert on public.decision_retrospectives for insert to authenticated with check(user_id=auth.uid() and exists(select 1 from public.investment_decisions d where d.id=decision_id and d.user_id=auth.uid()));
comment on table public.decision_context_snapshots is 'Immutable, bounded context captured when an explicit investment decision is recorded.';
comment on table public.decision_retrospectives is 'Append-only horizon reviews; prior completed reviews are never overwritten.';

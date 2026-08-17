-- EagleEyes Phase 4: immutable, owner-scoped thesis review history.
create table if not exists public.thesis_review_events (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  thesis_id uuid not null references public.investment_theses(id) on delete cascade,
  thesis_version integer not null check (thesis_version > 0),
  ticker text not null,
  baseline_review_at timestamptz not null,
  evaluated_at timestamptz not null,
  reviewed_at timestamptz not null,
  overall_status text not null check (overall_status in (
    'STABLE','STRENGTHENING','WEAKENING','MATERIAL_REVIEW_REQUIRED',
    'THESIS_BREAKER_TRIGGERED','INSUFFICIENT_EVIDENCE'
  )),
  requires_review boolean not null,
  monitoring_result jsonb not null,
  calculation_version text not null,
  created_at timestamptz not null default now()
);

create index if not exists thesis_review_events_user_thesis_idx
  on public.thesis_review_events(user_id,thesis_id,reviewed_at desc);
create index if not exists thesis_review_events_user_status_idx
  on public.thesis_review_events(user_id,overall_status,reviewed_at desc);

alter table public.thesis_review_events enable row level security;
revoke all on public.thesis_review_events from anon;
grant select,insert on public.thesis_review_events to authenticated;

create policy thesis_review_events_owner_select on public.thesis_review_events
  for select to authenticated using (user_id=auth.uid());
create policy thesis_review_events_owner_insert on public.thesis_review_events
  for insert to authenticated with check (
    user_id=auth.uid() and exists (
      select 1 from public.investment_theses t where t.id=thesis_id and t.user_id=auth.uid()
    )
  );

comment on table public.thesis_review_events is
  'Immutable user-confirmed thesis monitor states; editing a thesis does not move the evidence baseline.';

-- Immutable point-in-time evidence captured at user decision/review boundaries.
create table if not exists public.evidence_snapshots (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  entity_type text not null check (entity_type in ('SECURITY','MACRO','PORTFOLIO','MARKET')),
  entity_key text not null,
  baseline_type text not null check (baseline_type in (
    'LAST_THESIS_REVIEW','LAST_RESEARCH_REVIEW','LAST_DECISION','PREVIOUS_EARNINGS',
    'ONE_DAY','SEVEN_DAYS','THIRTY_DAYS','CUSTOM_DATE'
  )),
  baseline_ref text not null,
  as_of timestamptz not null,
  observations jsonb not null default '[]'::jsonb,
  methodology_version text not null,
  created_at timestamptz not null default now(),
  unique(user_id, entity_key, baseline_type, baseline_ref)
);

create index if not exists evidence_snapshots_user_entity_idx
  on public.evidence_snapshots(user_id, entity_key, as_of desc);

alter table public.evidence_snapshots enable row level security;
revoke all on public.evidence_snapshots from anon;
grant select,insert on public.evidence_snapshots to authenticated;

drop policy if exists "evidence_snapshots_owner_select" on public.evidence_snapshots;
create policy "evidence_snapshots_owner_select" on public.evidence_snapshots
  for select to authenticated using (auth.uid() = user_id);

drop policy if exists "evidence_snapshots_owner_insert" on public.evidence_snapshots;
create policy "evidence_snapshots_owner_insert" on public.evidence_snapshots
  for insert to authenticated with check (auth.uid() = user_id);

comment on table public.evidence_snapshots is
  'Immutable normalized evidence captured at user review and decision boundaries; no update/delete grants by design.';

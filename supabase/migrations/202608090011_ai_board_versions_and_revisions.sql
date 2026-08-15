alter table public.dashboard_jobs
  add column if not exists spec_version text not null default 'dashboard-spec-v1',
  add column if not exists layout_version text not null default 'dashboard-layout-v1',
  add column if not exists conversation_id uuid references public.chat_conversations(id) on delete set null;

alter table public.dashboard_views
  add column if not exists spec_version text not null default 'dashboard-spec-v1',
  add column if not exists layout_version text not null default 'dashboard-layout-v1',
  add column if not exists conversation_id uuid references public.chat_conversations(id) on delete set null;

alter table public.dashboard_view_runs
  add column if not exists spec_version text not null default 'dashboard-spec-v1',
  add column if not exists layout_version text not null default 'dashboard-layout-v1';

create table if not exists public.dashboard_view_revisions (
  id uuid primary key default gen_random_uuid(),
  view_id uuid not null references public.dashboard_views(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  revision_number integer not null,
  revision_type text not null check (revision_type in ('created','layout','renamed','duplicated','refreshed','prompt_revision')),
  prompt text,
  plan jsonb not null,
  specification jsonb not null,
  layout jsonb not null,
  diff jsonb not null default '{}'::jsonb,
  spec_version text not null,
  layout_version text not null,
  source_view_id uuid references public.dashboard_views(id) on delete set null,
  created_at timestamptz not null default now(),
  unique(view_id, revision_number)
);

create index if not exists dashboard_view_revisions_view_idx
  on public.dashboard_view_revisions(view_id, revision_number desc);

alter table public.dashboard_view_revisions enable row level security;
grant select, insert on public.dashboard_view_revisions to authenticated;
revoke update, delete on public.dashboard_view_revisions from authenticated, anon;
create policy dashboard_view_revisions_owner_select on public.dashboard_view_revisions
  for select to authenticated using (user_id = auth.uid());
create policy dashboard_view_revisions_owner_insert on public.dashboard_view_revisions
  for insert to authenticated with check (
    user_id = auth.uid() and exists (
      select 1 from public.dashboard_views v where v.id = view_id and v.user_id = auth.uid()
    )
  );

comment on table public.dashboard_view_revisions is
  'Immutable versioned snapshots and deterministic diffs for saved AI research boards.';

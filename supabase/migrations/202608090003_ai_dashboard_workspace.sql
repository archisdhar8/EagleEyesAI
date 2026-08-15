create table if not exists public.dashboard_jobs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  portfolio_id uuid references public.portfolios(id) on delete set null,
  source_view_id uuid,
  prompt text not null,
  state text not null default 'PLANNING' check (state in (
    'PLANNING','PLAN_VALIDATED','SPEC_COMPILED','FETCHING','CALCULATING',
    'WIDGETS_READY','NARRATING','COMPLETE','PARTIAL_SUCCESS','FAILED','CANCELLED','EXPIRED'
  )),
  progress integer not null default 0 check (progress between 0 and 100),
  plan jsonb,
  specification jsonb,
  widget_results jsonb not null default '[]'::jsonb,
  narrative text,
  warnings jsonb not null default '[]'::jsonb,
  error text,
  cancelled_at timestamptz,
  expires_at timestamptz not null default now() + interval '24 hours',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.dashboard_job_tasks (
  id uuid primary key default gen_random_uuid(),
  job_id uuid not null references public.dashboard_jobs(id) on delete cascade,
  task_key text not null,
  task_type text not null,
  depends_on text[] not null default '{}',
  required_for_narrative boolean not null default false,
  state text not null default 'PENDING',
  attempts integer not null default 0,
  calculation_version text not null,
  query jsonb not null default '{}'::jsonb,
  result jsonb,
  error text,
  started_at timestamptz,
  completed_at timestamptz,
  unique(job_id, task_key)
);

create table if not exists public.dashboard_views (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  name text not null,
  original_prompt text not null,
  plan jsonb not null,
  specification jsonb not null,
  layout jsonb not null default '[]'::jsonb,
  refresh_policy text not null default 'manual',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.dashboard_jobs
  add constraint dashboard_jobs_source_view_fk foreign key (source_view_id)
  references public.dashboard_views(id) on delete set null;

create table if not exists public.dashboard_view_runs (
  id uuid primary key default gen_random_uuid(),
  view_id uuid not null references public.dashboard_views(id) on delete cascade,
  job_id uuid references public.dashboard_jobs(id) on delete set null,
  user_id uuid not null references auth.users(id) on delete cascade,
  input_snapshot jsonb not null,
  widget_results jsonb not null,
  narrative text,
  lineage jsonb not null default '[]'::jsonb,
  warnings jsonb not null default '[]'::jsonb,
  model_versions jsonb not null default '{}'::jsonb,
  status text not null,
  created_at timestamptz not null default now()
);

create table if not exists public.dashboard_widget_cache (
  cache_key text primary key,
  task_type text not null,
  calculation_version text not null,
  result jsonb not null,
  lineage jsonb not null default '[]'::jsonb,
  effective_through timestamptz,
  expires_at timestamptz not null,
  created_at timestamptz not null default now()
);

create index if not exists dashboard_jobs_user_idx on public.dashboard_jobs(user_id, created_at desc);
create index if not exists dashboard_tasks_job_idx on public.dashboard_job_tasks(job_id, state);
create index if not exists dashboard_views_user_idx on public.dashboard_views(user_id, updated_at desc);
create index if not exists dashboard_runs_view_idx on public.dashboard_view_runs(view_id, created_at desc);
create index if not exists dashboard_cache_expiry_idx on public.dashboard_widget_cache(expires_at);

create trigger dashboard_jobs_updated_at before update on public.dashboard_jobs
for each row execute function public.set_updated_at();
create trigger dashboard_views_updated_at before update on public.dashboard_views
for each row execute function public.set_updated_at();

alter table public.dashboard_jobs enable row level security;
alter table public.dashboard_job_tasks enable row level security;
alter table public.dashboard_views enable row level security;
alter table public.dashboard_view_runs enable row level security;
alter table public.dashboard_widget_cache enable row level security;

grant select, insert, update, delete on public.dashboard_jobs, public.dashboard_job_tasks,
  public.dashboard_views, public.dashboard_view_runs to authenticated;

create policy dashboard_jobs_owner_all on public.dashboard_jobs for all to authenticated
using (user_id = auth.uid()) with check (user_id = auth.uid());
create policy dashboard_tasks_owner_all on public.dashboard_job_tasks for all to authenticated
using (exists (select 1 from public.dashboard_jobs j where j.id=job_id and j.user_id=auth.uid()))
with check (exists (select 1 from public.dashboard_jobs j where j.id=job_id and j.user_id=auth.uid()));
create policy dashboard_views_owner_all on public.dashboard_views for all to authenticated
using (user_id = auth.uid()) with check (user_id = auth.uid());
create policy dashboard_runs_owner_all on public.dashboard_view_runs for all to authenticated
using (user_id = auth.uid()) with check (user_id = auth.uid());

comment on table public.dashboard_widget_cache is
  'Server-managed deterministic result cache. No browser role receives direct access.';

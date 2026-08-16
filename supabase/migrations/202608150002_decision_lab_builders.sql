-- EagleEyes Decision Lab and allocation builders: additive immutable user-owned runs.

create table if not exists public.simulation_runs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  portfolio_id uuid references public.portfolios(id) on delete set null,
  input_snapshot jsonb not null,
  result_summary jsonb not null,
  model_version text not null,
  seed bigint not null,
  status text not null check (status in ('complete','failed','shadow')),
  created_at timestamptz not null default now()
);

create table if not exists public.allocation_builder_runs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  builder_type text not null check (builder_type in ('etf','stock')),
  request_snapshot jsonb not null,
  result jsonb not null,
  model_version text not null,
  created_at timestamptz not null default now()
);

create index if not exists simulation_runs_user_created_idx on public.simulation_runs(user_id,created_at desc);
create index if not exists allocation_builder_runs_user_created_idx on public.allocation_builder_runs(user_id,created_at desc);

alter table public.simulation_runs enable row level security;
alter table public.allocation_builder_runs enable row level security;

revoke all on public.simulation_runs,public.allocation_builder_runs from anon;
grant select,insert,delete on public.simulation_runs,public.allocation_builder_runs to authenticated;

create policy simulation_runs_owner_select on public.simulation_runs for select to authenticated using (user_id=auth.uid());
create policy simulation_runs_owner_insert on public.simulation_runs for insert to authenticated with check (user_id=auth.uid());
create policy simulation_runs_owner_delete on public.simulation_runs for delete to authenticated using (user_id=auth.uid());

create policy allocation_builder_runs_owner_select on public.allocation_builder_runs for select to authenticated using (user_id=auth.uid());
create policy allocation_builder_runs_owner_insert on public.allocation_builder_runs for insert to authenticated with check (user_id=auth.uid());
create policy allocation_builder_runs_owner_delete on public.allocation_builder_runs for delete to authenticated using (user_id=auth.uid());

comment on table public.simulation_runs is 'Immutable versioned Decision Lab inputs and summarized common-path simulation results.';
comment on table public.allocation_builder_runs is 'Immutable ETF and stock builder requests and deterministic results.';

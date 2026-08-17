begin;

create table if not exists public.model_portfolios (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  name text not null check (char_length(name) between 1 and 120),
  portfolio_type text not null check (portfolio_type in ('stocks','etfs','mixed')),
  status text not null default 'draft' check (status in ('draft','saved','converted')),
  candidate_universe jsonb not null default '{}'::jsonb,
  basket jsonb not null default '[]'::jsonb,
  configuration jsonb not null default '{}'::jsonb,
  comparison_results jsonb not null default '{}'::jsonb,
  backtest_results jsonb not null default '{}'::jsonb,
  simulation_run_id uuid references public.simulation_runs(id) on delete set null,
  converted_portfolio_id uuid references public.portfolios(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists model_portfolios_user_updated_idx
  on public.model_portfolios(user_id, updated_at desc);

alter table public.model_portfolios enable row level security;
revoke all on public.model_portfolios from anon;
grant select,insert,update,delete on public.model_portfolios to authenticated;

drop policy if exists model_portfolios_owner_select on public.model_portfolios;
drop policy if exists model_portfolios_owner_insert on public.model_portfolios;
drop policy if exists model_portfolios_owner_update on public.model_portfolios;
drop policy if exists model_portfolios_owner_delete on public.model_portfolios;

create policy model_portfolios_owner_select on public.model_portfolios
  for select to authenticated using (user_id=auth.uid());
create policy model_portfolios_owner_insert on public.model_portfolios
  for insert to authenticated with check (user_id=auth.uid());
create policy model_portfolios_owner_update on public.model_portfolios
  for update to authenticated using (user_id=auth.uid()) with check (user_id=auth.uid());
create policy model_portfolios_owner_delete on public.model_portfolios
  for delete to authenticated using (user_id=auth.uid());

comment on table public.model_portfolios is
  'User-owned research model portfolios. They remain separate from tracked holdings until explicit conversion.';

commit;

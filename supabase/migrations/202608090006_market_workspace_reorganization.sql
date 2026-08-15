alter table public.investor_profiles
  add column if not exists loss_capacity integer not null default 6 check (loss_capacity between 1 and 10),
  add column if not exists annual_income_need numeric not null default 0 check (annual_income_need >= 0);

alter table public.dashboard_preferences
  add column if not exists presentation_level text not null default 'detailed'
  check (presentation_level in ('simple','detailed','expert'));

create table if not exists public.financial_goals (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  name text not null,
  goal_type text not null default 'long_term_growth',
  target_amount numeric not null check (target_amount > 0),
  target_date date not null,
  current_value numeric not null default 0 check (current_value >= 0),
  annual_contribution numeric not null default 0 check (annual_contribution >= 0),
  priority integer not null default 3 check (priority between 1 and 5),
  inflation_adjusted boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.goal_account_allocations (
  goal_id uuid not null references public.financial_goals(id) on delete cascade,
  account_key text not null,
  allocation numeric not null check (allocation between 0 and 1),
  primary key (goal_id, account_key)
);

create table if not exists public.terminal_layouts (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  name text not null,
  widgets jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists financial_goals_user_idx on public.financial_goals(user_id, priority, target_date);
create index if not exists terminal_layouts_user_idx on public.terminal_layouts(user_id, updated_at desc);

drop trigger if exists financial_goals_updated_at on public.financial_goals;
create trigger financial_goals_updated_at before update on public.financial_goals
for each row execute function public.set_updated_at();
drop trigger if exists terminal_layouts_updated_at on public.terminal_layouts;
create trigger terminal_layouts_updated_at before update on public.terminal_layouts
for each row execute function public.set_updated_at();

alter table public.financial_goals enable row level security;
alter table public.goal_account_allocations enable row level security;
alter table public.terminal_layouts enable row level security;

grant select, insert, update, delete on public.financial_goals, public.goal_account_allocations, public.terminal_layouts to authenticated;

create policy financial_goals_owner_all on public.financial_goals for all to authenticated
using (user_id = auth.uid()) with check (user_id = auth.uid());
create policy goal_allocations_owner_all on public.goal_account_allocations for all to authenticated
using (exists (select 1 from public.financial_goals g where g.id=goal_id and g.user_id=auth.uid()))
with check (exists (select 1 from public.financial_goals g where g.id=goal_id and g.user_id=auth.uid()));
create policy terminal_layouts_owner_all on public.terminal_layouts for all to authenticated
using (user_id = auth.uid()) with check (user_id = auth.uid());

comment on table public.financial_goals is 'Secondary planning goals used to contextualize portfolio research and projections.';
comment on table public.terminal_layouts is 'User-owned manual Advanced terminal layouts; separate from AI-generated research boards.';

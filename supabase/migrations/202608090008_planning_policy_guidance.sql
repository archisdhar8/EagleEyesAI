alter table public.financial_goals
  add column if not exists funding_source text not null default 'New contributions',
  add column if not exists flexibility text not null default 'somewhat_flexible'
    check (flexibility in ('fixed','somewhat_flexible','very_flexible'));

create table if not exists public.investment_policies (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null unique references auth.users(id) on delete cascade,
  policy jsonb not null default '{}'::jsonb,
  status text not null default 'draft' check (status in ('draft','approved')),
  approved_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

drop trigger if exists investment_policies_updated_at on public.investment_policies;
create trigger investment_policies_updated_at before update on public.investment_policies
for each row execute function public.set_updated_at();

alter table public.investment_policies enable row level security;
grant select, insert, update, delete on public.investment_policies to authenticated;
revoke all privileges on public.investment_policies from anon;

create policy investment_policies_owner_all on public.investment_policies for all to authenticated
using (user_id = auth.uid()) with check (user_id = auth.uid());

comment on table public.investment_policies is
  'User-approved investment policy, research preferences, allocation ranges, and decision triggers.';

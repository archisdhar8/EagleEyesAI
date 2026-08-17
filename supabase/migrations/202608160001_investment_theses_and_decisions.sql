-- EagleEyes Phase 2: additive, user-owned thesis memory and append-only decisions.
-- Existing portfolios, watchlists, research snapshots, analyses, and simulation runs remain unchanged.

create table if not exists public.investment_theses (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  ticker text not null,
  summary text not null,
  base_case text not null default '',
  bull_case text not null default '',
  bear_case text not null default '',
  investment_horizon text not null default 'long' check (investment_horizon in ('short','medium','long','custom')),
  horizon_end_date date,
  review_date date,
  status text not null default 'DRAFT' check (status in ('DRAFT','ACTIVE','UNDER_REVIEW','CLOSED','ARCHIVED')),
  source_context jsonb not null default '{}'::jsonb,
  current_version integer not null default 1 check (current_version > 0),
  closed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create unique index if not exists investment_theses_one_open_idx
  on public.investment_theses(user_id,ticker)
  where status in ('DRAFT','ACTIVE','UNDER_REVIEW');
create index if not exists investment_theses_user_review_idx
  on public.investment_theses(user_id,status,review_date,updated_at desc);

create table if not exists public.thesis_assumptions (
  id uuid primary key default gen_random_uuid(),
  thesis_id uuid not null references public.investment_theses(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  description text not null,
  category text not null check (category in ('GROWTH','PROFITABILITY','MARGIN','VALUATION','BALANCE_SHEET','COMPETITIVE_POSITION','CAPITAL_ALLOCATION','DEMAND','MACRO','MANAGEMENT','REGULATORY','PORTFOLIO_FIT','CUSTOM')),
  importance text not null default 'MEDIUM' check (importance in ('LOW','MEDIUM','HIGH','CRITICAL')),
  status text not null default 'UNTESTED' check (status in ('UNTESTED','SUPPORTED','WEAKENING','BROKEN','NOT_MONITORABLE')),
  metric text,
  comparison_operator text check (comparison_operator is null or comparison_operator in ('>','>=','<','<=','=','!=')),
  target_value numeric,
  unit text,
  evidence_mapping jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check ((metric is null and comparison_operator is null and target_value is null) or (metric is not null and comparison_operator is not null and target_value is not null))
);

create table if not exists public.thesis_factors (
  id uuid primary key default gen_random_uuid(),
  thesis_id uuid not null references public.investment_theses(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  factor_type text not null check (factor_type in ('CATALYST','RISK','BREAKER')),
  description text not null,
  metric text,
  comparison_operator text check (comparison_operator is null or comparison_operator in ('>','>=','<','<=','=','!=')),
  threshold numeric,
  period_requirement text,
  unit text,
  evidence_mapping jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check ((metric is null and comparison_operator is null and threshold is null) or (metric is not null and comparison_operator is not null and threshold is not null))
);

create table if not exists public.thesis_versions (
  id uuid primary key default gen_random_uuid(),
  thesis_id uuid not null references public.investment_theses(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  version_number integer not null check (version_number > 0),
  snapshot jsonb not null,
  change_note text,
  created_at timestamptz not null default now(),
  unique(thesis_id,version_number)
);

create table if not exists public.investment_decisions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  ticker text not null,
  thesis_id uuid references public.investment_theses(id) on delete set null,
  thesis_version integer,
  decision_type text not null check (decision_type in ('WATCH','BUY','ADD','HOLD','REDUCE','SELL','AVOID')),
  decision_date timestamptz not null default now(),
  price_at_decision numeric,
  price_as_of timestamptz,
  price_source text,
  quantity numeric check (quantity is null or quantity >= 0),
  portfolio_context jsonb not null default '{}'::jsonb,
  user_confidence integer check (user_confidence is null or user_confidence between 1 and 5),
  investment_horizon text check (investment_horizon is null or investment_horizon in ('short','medium','long','custom')),
  notes text not null default '',
  source_context jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists thesis_assumptions_thesis_idx on public.thesis_assumptions(thesis_id,created_at);
create index if not exists thesis_factors_thesis_idx on public.thesis_factors(thesis_id,factor_type,created_at);
create index if not exists thesis_versions_thesis_idx on public.thesis_versions(thesis_id,version_number);
create index if not exists investment_decisions_user_ticker_idx on public.investment_decisions(user_id,ticker,decision_date desc);

alter table public.investment_theses enable row level security;
alter table public.thesis_assumptions enable row level security;
alter table public.thesis_factors enable row level security;
alter table public.thesis_versions enable row level security;
alter table public.investment_decisions enable row level security;

revoke all on public.investment_theses,public.thesis_assumptions,public.thesis_factors,public.thesis_versions,public.investment_decisions from anon;
grant select,insert,update,delete on public.investment_theses,public.thesis_assumptions,public.thesis_factors to authenticated;
grant select,insert on public.thesis_versions,public.investment_decisions to authenticated;

create policy investment_theses_owner_all on public.investment_theses for all to authenticated using (user_id=auth.uid()) with check (user_id=auth.uid());
create policy thesis_assumptions_owner_all on public.thesis_assumptions for all to authenticated using (user_id=auth.uid() and exists(select 1 from public.investment_theses t where t.id=thesis_id and t.user_id=auth.uid())) with check (user_id=auth.uid() and exists(select 1 from public.investment_theses t where t.id=thesis_id and t.user_id=auth.uid()));
create policy thesis_factors_owner_all on public.thesis_factors for all to authenticated using (user_id=auth.uid() and exists(select 1 from public.investment_theses t where t.id=thesis_id and t.user_id=auth.uid())) with check (user_id=auth.uid() and exists(select 1 from public.investment_theses t where t.id=thesis_id and t.user_id=auth.uid()));
create policy thesis_versions_owner_select on public.thesis_versions for select to authenticated using (user_id=auth.uid());
create policy thesis_versions_owner_insert on public.thesis_versions for insert to authenticated with check (user_id=auth.uid() and exists(select 1 from public.investment_theses t where t.id=thesis_id and t.user_id=auth.uid()));
create policy investment_decisions_owner_select on public.investment_decisions for select to authenticated using (user_id=auth.uid());
create policy investment_decisions_owner_insert on public.investment_decisions for insert to authenticated with check (user_id=auth.uid());

comment on table public.thesis_versions is 'Immutable complete thesis snapshots used to reconstruct original and revised investor reasoning.';
comment on table public.investment_decisions is 'Append-only user decisions; market price is captured only from deterministic stored price data when available.';

-- Additive Phase 3–5 integrity records. Existing holdings, boards, and immutable runs are untouched.
create table if not exists public.security_master (
  ticker text primary key,
  name text not null,
  exchange text,
  instrument_type text not null check (instrument_type in ('common_stock','etf','adr','otc','international','delisted','other')),
  currency text not null default 'USD',
  figi text,
  cusip text,
  active_from date,
  active_to date,
  active boolean not null default true,
  coverage_tier text not null check (coverage_tier in ('core_us','conditional_adr','conditional_otc','conditional_international','historical','unsupported')),
  provider_mappings jsonb not null default '{}'::jsonb,
  metadata jsonb not null default '{}'::jsonb,
  verified_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.security_coverage_snapshots (
  ticker text not null references public.security_master(ticker) on delete cascade,
  observed_at timestamptz not null default now(),
  adjusted_prices jsonb not null default '{}'::jsonb,
  fundamentals jsonb not null default '{}'::jsonb,
  classification jsonb not null default '{}'::jsonb,
  earnings jsonb not null default '{}'::jsonb,
  valuation jsonb not null default '{}'::jsonb,
  news jsonb not null default '{}'::jsonb,
  usable_history_months integer not null default 0 check (usable_history_months >= 0),
  missing_fields text[] not null default '{}',
  provider_lineage jsonb not null default '[]'::jsonb,
  primary key (ticker, observed_at)
);

insert into public.security_master(ticker,name,instrument_type,coverage_tier,active,provider_mappings,verified_at)
select distinct on (ticker) ticker,coalesce(company_name,ticker),
  case when asset_type='etf' then 'etf' else 'common_stock' end,
  'core_us',active,jsonb_build_object('securities_asset_type',asset_type),updated_at
from public.securities
where ticker is not null
order by ticker,updated_at desc
on conflict (ticker) do update set
  name=excluded.name,active=excluded.active,verified_at=excluded.verified_at,
  provider_mappings=public.security_master.provider_mappings || excluded.provider_mappings,
  updated_at=now();

create table if not exists public.investment_accounts (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  name text not null,
  account_type text not null,
  institution text,
  currency text not null default 'USD',
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.portfolio_transactions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  account_id uuid not null references public.investment_accounts(id) on delete cascade,
  external_id text,
  trade_date date not null,
  settlement_date date,
  transaction_type text not null check (transaction_type in ('buy','sell','deposit','withdrawal','dividend','income','fee','split','transfer_in','transfer_out')),
  ticker text,
  quantity numeric,
  price numeric,
  amount numeric,
  fee numeric not null default 0,
  currency text not null default 'USD',
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique(user_id,account_id,external_id)
);

create table if not exists public.account_valuations (
  user_id uuid not null references auth.users(id) on delete cascade,
  account_id uuid not null references public.investment_accounts(id) on delete cascade,
  valuation_date date not null,
  market_value numeric not null,
  cash_value numeric not null default 0,
  source text not null,
  metadata jsonb not null default '{}'::jsonb,
  primary key(account_id,valuation_date,source)
);

create table if not exists public.security_lots (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  account_id uuid not null references public.investment_accounts(id) on delete cascade,
  ticker text not null,
  acquired_at date not null,
  quantity numeric not null,
  cost_basis numeric,
  source_transaction_id uuid references public.portfolio_transactions(id) on delete set null,
  metadata jsonb not null default '{}'::jsonb
);

create table if not exists public.corporate_actions (
  id uuid primary key default gen_random_uuid(),
  ticker text not null,
  action_type text not null,
  effective_date date not null,
  ratio numeric,
  cash_amount numeric,
  provider text not null,
  source_url text,
  metadata jsonb not null default '{}'::jsonb,
  unique(ticker,action_type,effective_date,provider)
);

create table if not exists public.income_events (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  account_id uuid not null references public.investment_accounts(id) on delete cascade,
  ticker text,
  event_date date not null,
  event_type text not null,
  amount numeric not null,
  source_transaction_id uuid references public.portfolio_transactions(id) on delete set null,
  metadata jsonb not null default '{}'::jsonb
);

create table if not exists public.statement_reconciliations (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  account_id uuid not null references public.investment_accounts(id) on delete cascade,
  statement_date date not null,
  statement_market_value numeric not null,
  statement_cash numeric not null,
  reconstructed_market_value numeric not null,
  reconstructed_cash numeric not null,
  tolerance numeric not null,
  status text not null check (status in ('reconciled','difference')),
  differences jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists public.portfolio_performance_runs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  account_id uuid not null references public.investment_accounts(id) on delete cascade,
  period_start date not null,
  period_end date not null,
  time_weighted_return numeric,
  money_weighted_return numeric,
  inputs jsonb not null,
  result jsonb not null,
  calculation_version text not null,
  created_at timestamptz not null default now()
);

alter table public.security_master enable row level security;
alter table public.security_coverage_snapshots enable row level security;
alter table public.investment_accounts enable row level security;
alter table public.portfolio_transactions enable row level security;
alter table public.account_valuations enable row level security;
alter table public.security_lots enable row level security;
alter table public.corporate_actions enable row level security;
alter table public.income_events enable row level security;
alter table public.statement_reconciliations enable row level security;
alter table public.portfolio_performance_runs enable row level security;

revoke all on public.security_master,public.security_coverage_snapshots,public.corporate_actions from anon,authenticated;
revoke all on public.investment_accounts,public.portfolio_transactions,public.account_valuations,public.security_lots,public.income_events,public.statement_reconciliations,public.portfolio_performance_runs from anon,authenticated;

create index if not exists security_master_name_idx on public.security_master using gin(to_tsvector('english',name));
create index if not exists security_coverage_latest_idx on public.security_coverage_snapshots(ticker,observed_at desc);
create index if not exists portfolio_transactions_account_date_idx on public.portfolio_transactions(account_id,trade_date,id);
create index if not exists security_lots_account_ticker_idx on public.security_lots(account_id,ticker,acquired_at);
create index if not exists performance_runs_account_period_idx on public.portfolio_performance_runs(account_id,period_end desc);

comment on table public.security_master is 'Versioned research symbol scope and provider mappings; does not imply complete evidence coverage.';
comment on table public.portfolio_transactions is 'Immutable imported account ledger used for actual-performance reconstruction; current holdings snapshots remain separate.';

create schema if not exists extensions;
create extension if not exists pgcrypto with schema extensions;
create extension if not exists vector with schema extensions;

create or replace function public.set_updated_at()
returns trigger
language plpgsql
set search_path = public
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create table public.securities (
  id uuid primary key default gen_random_uuid(),
  ticker text not null,
  asset_type text not null default 'stock' check (asset_type in ('stock', 'etf', 'cash', 'fund', 'index')),
  company_name text,
  exchange text,
  sector text,
  industry text,
  currency text not null default 'USD',
  provider_ids jsonb not null default '{}'::jsonb,
  active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (ticker, asset_type)
);

create table public.portfolios (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  base_currency text not null default 'USD',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.holdings (
  id uuid primary key default gen_random_uuid(),
  portfolio_id uuid not null references public.portfolios(id) on delete cascade,
  security_id uuid references public.securities(id),
  ticker text not null,
  quantity numeric,
  weight numeric check (weight is null or (weight >= 0 and weight <= 1)),
  market_value numeric,
  cost_basis numeric,
  account_type text not null default 'taxable',
  acquisition_date date,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (quantity is not null or weight is not null or market_value is not null)
);

create table public.investor_profiles (
  id uuid primary key default gen_random_uuid(),
  portfolio_id uuid references public.portfolios(id) on delete cascade,
  name text not null default 'Primary profile',
  age integer check (age between 18 and 120),
  retirement_age integer check (retirement_age between 18 and 120),
  horizon_years integer check (horizon_years between 1 and 100),
  account_type text not null default 'taxable',
  annual_contribution numeric not null default 0,
  annual_withdrawal numeric not null default 0,
  target_value numeric,
  tax_rate numeric check (tax_rate is null or (tax_rate >= 0 and tax_rate <= 1)),
  risk_tolerance numeric check (risk_tolerance is null or (risk_tolerance >= 0 and risk_tolerance <= 10)),
  preset text not null default 'balanced' check (preset in ('growth', 'balanced', 'preservation', 'income')),
  restrictions jsonb not null default '[]'::jsonb,
  watchlist text[] not null default '{}',
  objective_weights jsonb not null default '{}'::jsonb,
  explanation_settings jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.provider_fetches (
  id bigint generated always as identity primary key,
  provider text not null,
  request_key text not null,
  status text not null check (status in ('started', 'success', 'failed', 'stale_fallback')),
  as_of timestamptz,
  fetched_at timestamptz not null default now(),
  expires_at timestamptz,
  source_url text,
  payload_hash text,
  error_message text,
  metadata jsonb not null default '{}'::jsonb
);

create table public.price_bars (
  id bigint generated always as identity primary key,
  security_id uuid not null references public.securities(id) on delete cascade,
  provider text not null,
  interval text not null default '1d',
  ts timestamptz not null,
  open numeric,
  high numeric,
  low numeric,
  close numeric not null,
  adjusted_close numeric,
  volume numeric,
  vwap numeric,
  transactions bigint,
  fetched_at timestamptz not null default now(),
  unique (security_id, provider, interval, ts)
);

create table public.macro_observations (
  id bigint generated always as identity primary key,
  provider text not null default 'FRED',
  series_id text not null,
  observation_date date not null,
  vintage_date date not null,
  value double precision,
  unit text,
  source_url text,
  fetched_at timestamptz not null default now(),
  unique (provider, series_id, observation_date, vintage_date)
);

create table public.prediction_markets (
  id uuid primary key default gen_random_uuid(),
  provider text not null check (provider in ('kalshi', 'polymarket')),
  external_market_id text not null,
  canonical_question text not null,
  canonical_scenario text,
  threshold_bucket jsonb not null default '{}'::jsonb,
  title text not null,
  source_url text,
  closes_at timestamptz,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (provider, external_market_id)
);

create table public.prediction_market_snapshots (
  id bigint generated always as identity primary key,
  market_id uuid not null references public.prediction_markets(id) on delete cascade,
  observed_at timestamptz not null,
  probability double precision not null check (probability between 0 and 1),
  bid double precision,
  ask double precision,
  volume numeric,
  open_interest numeric,
  order_book_depth numeric,
  confidence double precision check (confidence is null or confidence between 0 and 1),
  raw_payload jsonb not null default '{}'::jsonb,
  unique (market_id, observed_at)
);

create table public.scenario_snapshots (
  id uuid primary key default gen_random_uuid(),
  observed_at timestamptz not null default now(),
  model_version text not null,
  macro_prior jsonb not null default '{}'::jsonb,
  warnings jsonb not null default '[]'::jsonb,
  lineage jsonb not null default '{}'::jsonb
);

create table public.scenario_probabilities (
  snapshot_id uuid not null references public.scenario_snapshots(id) on delete cascade,
  scenario_key text not null,
  probability double precision not null check (probability between 0 and 1),
  confidence double precision not null check (confidence between 0 and 1),
  is_prior boolean not null default false,
  contributors jsonb not null default '[]'::jsonb,
  primary key (snapshot_id, scenario_key)
);

create table public.fundamental_observations (
  id bigint generated always as identity primary key,
  security_id uuid not null references public.securities(id) on delete cascade,
  provider text not null,
  metric text not null,
  period_end date not null,
  filed_at date,
  fiscal_period text,
  value numeric,
  unit text,
  form_type text,
  accession_number text,
  source_url text,
  fetched_at timestamptz not null default now(),
  unique nulls not distinct (security_id, provider, metric, period_end, filed_at, fiscal_period)
);

create table public.security_research_snapshots (
  id uuid primary key default gen_random_uuid(),
  security_id uuid not null references public.securities(id) on delete cascade,
  as_of timestamptz not null,
  model_version text not null,
  growth_rating double precision,
  valuation_score double precision,
  fundamental_score double precision,
  industry_score double precision,
  technical_score double precision,
  news_score double precision,
  final_score double precision,
  confidence double precision check (confidence is null or confidence between 0 and 1),
  data_quality text,
  metrics jsonb not null default '{}'::jsonb,
  scenario_sensitivities jsonb not null default '{}'::jsonb,
  risks jsonb not null default '[]'::jsonb,
  catalysts jsonb not null default '[]'::jsonb,
  lineage jsonb not null default '{}'::jsonb,
  unique (security_id, as_of, model_version)
);

create table public.documents (
  id uuid primary key default gen_random_uuid(),
  security_id uuid references public.securities(id) on delete set null,
  provider text not null,
  document_type text not null,
  external_id text,
  title text not null,
  source_url text,
  published_at timestamptz,
  fetched_at timestamptz not null default now(),
  content_hash text,
  storage_path text,
  metadata jsonb not null default '{}'::jsonb,
  unique nulls not distinct (provider, external_id)
);

create table public.document_chunks (
  id uuid primary key default gen_random_uuid(),
  document_id uuid not null references public.documents(id) on delete cascade,
  chunk_index integer not null check (chunk_index >= 0),
  content text not null,
  token_count integer,
  embedding extensions.vector,
  embedding_model text,
  embedding_dimensions integer,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (document_id, chunk_index)
);

create table public.analysis_runs (
  id uuid primary key default gen_random_uuid(),
  portfolio_id uuid references public.portfolios(id) on delete set null,
  profile_id uuid references public.investor_profiles(id) on delete set null,
  status text not null default 'completed' check (status in ('pending', 'running', 'completed', 'failed', 'infeasible')),
  model_version text not null,
  config_version text not null,
  input_snapshot jsonb not null,
  data_lineage jsonb not null default '{}'::jsonb,
  current_portfolio jsonb not null default '{}'::jsonb,
  alternatives jsonb not null default '[]'::jsonb,
  warnings jsonb not null default '[]'::jsonb,
  error_message text,
  created_at timestamptz not null default now()
);

create table public.chat_conversations (
  id uuid primary key default gen_random_uuid(),
  portfolio_id uuid references public.portfolios(id) on delete set null,
  title text not null default 'New research conversation',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.chat_messages (
  id uuid primary key default gen_random_uuid(),
  conversation_id uuid not null references public.chat_conversations(id) on delete cascade,
  role text not null check (role in ('user', 'assistant', 'system', 'tool')),
  content text not null,
  structured_content jsonb not null default '{}'::jsonb,
  model text,
  created_at timestamptz not null default now()
);

create table public.chat_message_evidence (
  id uuid primary key default gen_random_uuid(),
  message_id uuid not null references public.chat_messages(id) on delete cascade,
  document_chunk_id uuid references public.document_chunks(id) on delete cascade,
  source_url text,
  source_label text,
  as_of timestamptz,
  metadata jsonb not null default '{}'::jsonb,
  check (document_chunk_id is not null or source_url is not null)
);

create index holdings_portfolio_idx on public.holdings(portfolio_id);
create index holdings_ticker_idx on public.holdings(ticker);
create index profiles_portfolio_idx on public.investor_profiles(portfolio_id);
create index provider_fetches_lookup_idx on public.provider_fetches(provider, request_key, fetched_at desc);
create index price_bars_lookup_idx on public.price_bars(security_id, interval, ts desc);
create index macro_vintage_idx on public.macro_observations(series_id, observation_date, vintage_date desc);
create index market_snapshot_history_idx on public.prediction_market_snapshots(market_id, observed_at desc);
create index scenario_snapshot_observed_idx on public.scenario_snapshots(observed_at desc);
create index fundamentals_lookup_idx on public.fundamental_observations(security_id, metric, period_end desc);
create index research_lookup_idx on public.security_research_snapshots(security_id, as_of desc);
create index documents_security_idx on public.documents(security_id, published_at desc);
create index document_chunks_document_idx on public.document_chunks(document_id, chunk_index);
create index analysis_portfolio_idx on public.analysis_runs(portfolio_id, created_at desc);
create index chat_messages_conversation_idx on public.chat_messages(conversation_id, created_at);

create trigger securities_updated_at before update on public.securities
for each row execute function public.set_updated_at();
create trigger portfolios_updated_at before update on public.portfolios
for each row execute function public.set_updated_at();
create trigger holdings_updated_at before update on public.holdings
for each row execute function public.set_updated_at();
create trigger profiles_updated_at before update on public.investor_profiles
for each row execute function public.set_updated_at();
create trigger prediction_markets_updated_at before update on public.prediction_markets
for each row execute function public.set_updated_at();
create trigger conversations_updated_at before update on public.chat_conversations
for each row execute function public.set_updated_at();

alter table public.securities enable row level security;
alter table public.portfolios enable row level security;
alter table public.holdings enable row level security;
alter table public.investor_profiles enable row level security;
alter table public.provider_fetches enable row level security;
alter table public.price_bars enable row level security;
alter table public.macro_observations enable row level security;
alter table public.prediction_markets enable row level security;
alter table public.prediction_market_snapshots enable row level security;
alter table public.scenario_snapshots enable row level security;
alter table public.scenario_probabilities enable row level security;
alter table public.fundamental_observations enable row level security;
alter table public.security_research_snapshots enable row level security;
alter table public.documents enable row level security;
alter table public.document_chunks enable row level security;
alter table public.analysis_runs enable row level security;
alter table public.chat_conversations enable row level security;
alter table public.chat_messages enable row level security;
alter table public.chat_message_evidence enable row level security;

revoke all on all tables in schema public from anon, authenticated;
revoke all on all sequences in schema public from anon, authenticated;

comment on schema public is 'InvestmentDashboard application schema. Browser roles have no access until explicit authenticated policies are added.';

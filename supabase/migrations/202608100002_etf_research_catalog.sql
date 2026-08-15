-- Additive ETF research catalog and dated look-through analytics.
create table if not exists public.etf_catalog (
  ticker text primary key,
  name text not null,
  issuer text,
  asset_class text,
  category text,
  strategy text,
  benchmark text,
  expense_ratio numeric check (expense_ratio is null or expense_ratio >= 0),
  holdings_count integer check (holdings_count is null or holdings_count >= 0),
  inception_date date,
  primary_exchange text,
  currency text not null default 'USD',
  active boolean not null default true,
  provider text not null,
  source_url text,
  effective_at timestamptz not null,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.etf_exposures (
  fund_ticker text not null references public.etf_catalog(ticker) on delete cascade,
  exposure_type text not null check (exposure_type in ('sector','industry','country','asset_class','factor')),
  exposure_name text not null,
  weight numeric not null check (weight >= 0 and weight <= 1),
  as_of date not null,
  provider text not null,
  source_url text,
  metadata jsonb not null default '{}'::jsonb,
  primary key (fund_ticker, exposure_type, exposure_name, as_of)
);

create table if not exists public.etf_refresh_runs (
  id uuid primary key default gen_random_uuid(),
  provider text not null,
  run_type text not null check (run_type in ('catalog','holdings','exposures')),
  ticker text,
  status text not null check (status in ('started','success','partial','failed')),
  row_count integer not null default 0 check (row_count >= 0),
  started_at timestamptz not null default now(),
  completed_at timestamptz,
  error_message text,
  metadata jsonb not null default '{}'::jsonb
);

alter table public.etf_catalog enable row level security;
alter table public.etf_exposures enable row level security;
alter table public.etf_refresh_runs enable row level security;

revoke all on public.etf_catalog from anon, authenticated;
revoke all on public.etf_exposures from anon, authenticated;
revoke all on public.etf_refresh_runs from anon, authenticated;

create index if not exists etf_catalog_name_idx on public.etf_catalog using gin (to_tsvector('english', name));
create index if not exists etf_catalog_issuer_idx on public.etf_catalog(issuer, ticker);
create index if not exists etf_catalog_category_idx on public.etf_catalog(category, ticker);
create index if not exists etf_exposures_latest_idx on public.etf_exposures(fund_ticker, exposure_type, as_of desc);
create index if not exists etf_refresh_runs_latest_idx on public.etf_refresh_runs(run_type, started_at desc);

-- Phase 3/4 additive research and suitability storage.
alter table public.investor_profiles
  add column if not exists suitability_profile jsonb not null default '{"version":"suitability-v1"}'::jsonb;

create table if not exists public.fund_reference_data (
  ticker text primary key,
  expense_ratio numeric,
  provider text not null,
  source_url text,
  effective_at timestamptz not null,
  metadata jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

create table if not exists public.fund_holdings (
  fund_ticker text not null,
  constituent_ticker text not null,
  weight numeric not null check (weight >= 0 and weight <= 1),
  as_of date not null,
  provider text not null,
  source_url text,
  metadata jsonb not null default '{}'::jsonb,
  primary key (fund_ticker, constituent_ticker, as_of)
);

create table if not exists public.security_memberships (
  security_ticker text not null,
  collection_type text not null check (collection_type in ('sector','industry','index','theme')),
  collection_name text not null,
  weight numeric,
  as_of date not null,
  provider text not null,
  source_url text,
  metadata jsonb not null default '{}'::jsonb,
  primary key (security_ticker, collection_type, collection_name, as_of)
);

alter table public.fund_reference_data enable row level security;
alter table public.fund_holdings enable row level security;
alter table public.security_memberships enable row level security;

revoke all on public.fund_reference_data from anon, authenticated;
revoke all on public.fund_holdings from anon, authenticated;
revoke all on public.security_memberships from anon, authenticated;

create index if not exists fund_holdings_constituent_idx on public.fund_holdings(constituent_ticker, as_of desc);
create index if not exists security_memberships_collection_idx on public.security_memberships(collection_type, collection_name, as_of desc);

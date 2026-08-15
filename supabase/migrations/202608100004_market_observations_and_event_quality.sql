create table if not exists public.market_observations (
  id uuid primary key default gen_random_uuid(),
  ticker text not null,
  value numeric not null,
  observed_at timestamptz not null,
  retrieved_at timestamptz not null default now(),
  provider text not null,
  dataset text not null,
  latency_class text not null check (latency_class in ('live','delayed','end-of-day','cached','stale')),
  entitlement text not null default 'unknown',
  source_url text,
  metadata jsonb not null default '{}',
  unique(ticker, provider, dataset, observed_at)
);

create index if not exists market_observations_ticker_time_idx
  on public.market_observations(ticker, observed_at desc);

alter table public.market_observations enable row level security;
revoke all on public.market_observations from anon, authenticated;

alter table public.market_events add column if not exists event_status text not null default 'scheduled';
alter table public.market_events add column if not exists timing_status text not null default 'confirmed';
alter table public.market_events add column if not exists verified_at timestamptz;
alter table public.market_events add column if not exists timezone_name text not null default 'UTC';
alter table public.market_events add column if not exists dedupe_key text;

create index if not exists market_events_dedupe_idx on public.market_events(dedupe_key);

comment on table public.market_observations is
  'Normalized server-managed live, delayed, end-of-day, cached, and stale market observations with entitlement lineage.';

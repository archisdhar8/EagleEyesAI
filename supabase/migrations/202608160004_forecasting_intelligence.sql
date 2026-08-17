create table if not exists public.user_forecasts (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  event_key text not null,
  provider text,
  external_market_id text,
  title text not null,
  probability double precision not null check (probability between 0 and 1),
  reasoning text not null default '',
  market_probability_at_entry double precision check (market_probability_at_entry is null or market_probability_at_entry between 0 and 1),
  model_probability_at_entry double precision check (model_probability_at_entry is null or model_probability_at_entry between 0 and 1),
  forecast_horizon text,
  observed_at timestamptz not null default now(),
  created_at timestamptz not null default now()
);

create index if not exists user_forecasts_user_event_idx
on public.user_forecasts(user_id, event_key, observed_at desc);

create table if not exists public.forecast_resolution_events (
  id uuid primary key default gen_random_uuid(),
  event_key text not null,
  provider text,
  external_market_id text,
  outcome double precision not null check (outcome between 0 and 1),
  resolution_reference text,
  resolved_at timestamptz not null,
  recorded_at timestamptz not null default now(),
  unique(event_key, provider, external_market_id, resolved_at)
);

create index if not exists forecast_resolution_event_idx
on public.forecast_resolution_events(event_key, resolved_at desc);

create table if not exists public.forecast_records (
  id uuid primary key default gen_random_uuid(),
  target text not null,
  probability_source text not null check (probability_source in ('MARKET_IMPLIED','MODEL','COMPOSITE')),
  forecast_value double precision,
  probability_distribution jsonb,
  forecast_range jsonb,
  horizon text not null,
  input_data_as_of timestamptz not null,
  model_version text not null,
  methodology text not null,
  assumptions jsonb not null default '[]'::jsonb,
  data_coverage jsonb not null default '{}'::jsonb,
  features jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists forecast_records_target_idx
on public.forecast_records(target, input_data_as_of desc);

alter table public.user_forecasts enable row level security;
alter table public.forecast_resolution_events enable row level security;
alter table public.forecast_records enable row level security;

create policy user_forecasts_owner_select on public.user_forecasts
for select using (auth.uid() = user_id);
create policy user_forecasts_owner_insert on public.user_forecasts
for insert with check (auth.uid() = user_id);

revoke all on public.user_forecasts from anon, authenticated;
grant select,insert on public.user_forecasts to authenticated;
revoke all on public.forecast_resolution_events from anon, authenticated;
revoke all on public.forecast_records from anon, authenticated;

comment on table public.user_forecasts is
'Append-only user probability beliefs with contemporaneous market and model snapshots.';
comment on table public.forecast_resolution_events is
'Immutable resolved outcomes used to evaluate market, model, and user probability forecasts.';
comment on table public.forecast_records is
'Immutable typed model/market/composite forecast outputs with point-in-time inputs and methodology.';

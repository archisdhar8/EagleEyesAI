-- Additive server-owned operational telemetry. No private payloads or credentials belong here.
create table if not exists public.operational_events (
  id bigint generated always as identity primary key,
  metric_name text not null,
  metric_value double precision not null,
  tags jsonb not null default '{}'::jsonb,
  observed_at timestamptz not null default now()
);

create index if not exists operational_events_name_time_idx
  on public.operational_events(metric_name, observed_at desc);

alter table public.operational_events enable row level security;
revoke all on public.operational_events from anon, authenticated;

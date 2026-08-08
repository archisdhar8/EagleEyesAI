create table public.prediction_contract_series (
  id uuid primary key default gen_random_uuid(),
  canonical_key text not null unique,
  canonical_scenario text not null,
  indicator text not null,
  threshold_bucket jsonb not null default '{}'::jsonb,
  description text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.prediction_markets
add column if not exists series_id uuid references public.prediction_contract_series(id),
add column if not exists opens_at timestamptz,
add column if not exists resolution_at timestamptz,
add column if not exists resolved_outcome double precision
  check (resolved_outcome is null or resolved_outcome between 0 and 1);

create index prediction_markets_series_idx
on public.prediction_markets(series_id, closes_at desc);

create table public.prediction_market_calibration_runs (
  id uuid primary key default gen_random_uuid(),
  model_version text not null,
  horizon_months integer not null default 1 check (horizon_months > 0),
  data_cutoff date not null,
  sample_count integer not null default 0,
  genuine_market_sample_count integer not null default 0,
  brier_score double precision,
  calibration_error double precision,
  status text not null check (status in ('complete', 'insufficient_history', 'failed')),
  metrics jsonb not null default '{}'::jsonb,
  assumptions jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now()
);

create table public.model_promotion_decisions (
  id uuid primary key default gen_random_uuid(),
  model_version_id uuid not null references public.model_versions(id),
  decision text not null check (decision in ('promote', 'hold', 'reject', 'retire')),
  previous_status text,
  requested_status text,
  rationale text not null,
  gates jsonb not null default '{}'::jsonb,
  evidence jsonb not null default '{}'::jsonb,
  decided_by text not null,
  decided_at timestamptz not null default now()
);

create index model_promotion_decisions_model_idx
on public.model_promotion_decisions(model_version_id, decided_at desc);

create table public.model_monitoring_runs (
  id uuid primary key default gen_random_uuid(),
  model_version_id uuid not null references public.model_versions(id),
  analysis_run_id uuid references public.analysis_runs(id) on delete set null,
  status text not null check (status in ('healthy', 'warning', 'failed')),
  data_cutoff date not null,
  market_calibration_run_id uuid references public.prediction_market_calibration_runs(id),
  metrics jsonb not null default '{}'::jsonb,
  alerts jsonb not null default '[]'::jsonb,
  data_freshness jsonb not null default '{}'::jsonb,
  coverage jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index model_monitoring_runs_created_idx
on public.model_monitoring_runs(model_version_id, created_at desc);

-- Existing production versions predate the promotion ledger. Record their
-- explicit baseline adoption before enforcing the future promotion gate.
insert into public.model_promotion_decisions(
  model_version_id, decision, previous_status, requested_status, rationale,
  gates, evidence, decided_by
)
select id, 'promote', 'evaluation', 'production',
  'Grandfathered transparent v1/v2 baseline after stored walk-forward validation and leakage checks.',
  '{"bootstrap":true,"requires_recorded_validation":true}'::jsonb,
  '{"migration":"202608080002_market_monitoring.sql"}'::jsonb,
  'system-bootstrap'
from public.model_versions
where status='production'
and not exists (
  select 1 from public.model_promotion_decisions d
  where d.model_version_id=public.model_versions.id and d.decision='promote'
);

create or replace function public.enforce_recorded_model_promotion()
returns trigger language plpgsql as $$
begin
  if tg_op='INSERT' and new.status='production' then
    raise exception 'New model versions must be registered in evaluation before promotion';
  end if;
  if tg_op='UPDATE' and old.status is distinct from 'production' and new.status='production' then
    if not exists (
      select 1 from public.model_promotion_decisions
      where model_version_id=new.id and decision='promote'
        and requested_status='production'
    ) then
      raise exception 'Production status requires a recorded promotion decision';
    end if;
  end if;
  return new;
end;
$$;

create trigger model_versions_promotion_gate
before insert or update of status on public.model_versions
for each row execute function public.enforce_recorded_model_promotion();

create trigger prediction_contract_series_updated_at
before update on public.prediction_contract_series
for each row execute function public.set_updated_at();

alter table public.prediction_contract_series enable row level security;
alter table public.prediction_market_calibration_runs enable row level security;
alter table public.model_promotion_decisions enable row level security;
alter table public.model_monitoring_runs enable row level security;

revoke all on public.prediction_contract_series from anon, authenticated;
revoke all on public.prediction_market_calibration_runs from anon, authenticated;
revoke all on public.model_promotion_decisions from anon, authenticated;
revoke all on public.model_monitoring_runs from anon, authenticated;

comment on table public.prediction_contract_series is
'Canonical macro contract families that link related Kalshi and Polymarket markets across venues and expirations.';
comment on table public.prediction_market_calibration_runs is
'Point-in-time prediction-market scenario calibration against subsequently realized transparent macro regimes.';
comment on table public.model_promotion_decisions is
'Immutable human or system decisions required before a model version can become production.';
comment on table public.model_monitoring_runs is
'Automated post-ingestion health checks for calibration, covariance, walk-forward performance, stability, freshness, and coverage.';

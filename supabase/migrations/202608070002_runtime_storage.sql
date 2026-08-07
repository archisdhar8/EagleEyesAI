alter table public.portfolios
add column if not exists legacy_sqlite_id bigint unique;

alter table public.investor_profiles
add column if not exists legacy_sqlite_id bigint unique;

alter table public.scenario_snapshots
add column if not exists legacy_sqlite_id bigint unique,
add column if not exists raw_scenarios jsonb not null default '[]'::jsonb,
add column if not exists raw_contracts jsonb not null default '[]'::jsonb;

alter table public.analysis_runs
add column if not exists result_snapshot jsonb not null default '{}'::jsonb;

comment on column public.portfolios.legacy_sqlite_id is 'Source ID retained only for idempotent migration from the local v1 SQLite database.';
comment on column public.scenario_snapshots.raw_scenarios is 'Validated canonical scenario payload used by the v1 API.';
comment on column public.analysis_runs.result_snapshot is 'Immutable completed analysis response returned by the v1 API.';

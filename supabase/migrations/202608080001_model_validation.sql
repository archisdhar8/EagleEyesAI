create table public.model_versions (
  id uuid primary key default gen_random_uuid(),
  model_key text not null,
  version text not null,
  model_type text not null check (model_type in ('optimizer', 'regime_rules', 'regime_classifier')),
  status text not null default 'evaluation' check (status in ('production', 'evaluation', 'retired')),
  configuration jsonb not null default '{}'::jsonb,
  assumptions jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now(),
  unique (model_key, version)
);

create table public.validation_runs (
  id uuid primary key default gen_random_uuid(),
  analysis_run_id uuid references public.analysis_runs(id) on delete set null,
  model_version_id uuid not null references public.model_versions(id),
  validation_type text not null check (validation_type in ('portfolio_walk_forward', 'regime_classification')),
  status text not null check (status in ('complete', 'insufficient_history', 'failed')),
  data_cutoff date,
  configuration jsonb not null default '{}'::jsonb,
  aggregate_metrics jsonb not null default '{}'::jsonb,
  benchmark_comparisons jsonb not null default '[]'::jsonb,
  recommendation text,
  assumptions jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now(),
  unique (analysis_run_id, model_version_id, validation_type)
);

create index validation_runs_model_idx
on public.validation_runs(model_version_id, created_at desc);

create index validation_runs_analysis_idx
on public.validation_runs(analysis_run_id, created_at desc);

create table public.validation_folds (
  id uuid primary key default gen_random_uuid(),
  validation_run_id uuid not null references public.validation_runs(id) on delete cascade,
  fold_index integer not null check (fold_index >= 0),
  train_start date,
  train_end date not null,
  test_start date not null,
  test_end date not null,
  data_cutoff date not null,
  sample_counts jsonb not null default '{}'::jsonb,
  metrics jsonb not null default '{}'::jsonb,
  benchmark_metrics jsonb not null default '{}'::jsonb,
  diagnostics jsonb not null default '{}'::jsonb,
  leakage_check boolean not null,
  created_at timestamptz not null default now(),
  unique (validation_run_id, fold_index),
  check (train_end < test_start),
  check (test_start <= test_end),
  check (data_cutoff <= test_start)
);

create index validation_folds_run_idx
on public.validation_folds(validation_run_id, fold_index);

alter table public.model_versions enable row level security;
alter table public.validation_runs enable row level security;
alter table public.validation_folds enable row level security;

revoke all on public.model_versions from anon, authenticated;
revoke all on public.validation_runs from anon, authenticated;
revoke all on public.validation_folds from anon, authenticated;

comment on table public.model_versions is
'Immutable configuration and assumption registry for production and evaluation model versions.';

comment on table public.validation_runs is
'Saved aggregate results for portfolio walk-forward and regime-classifier evaluations.';

comment on table public.validation_folds is
'Point-in-time train/test folds with explicit cutoffs, diagnostics, benchmark metrics, and leakage checks.';

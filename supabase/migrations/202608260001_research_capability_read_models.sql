-- Additive Research capability storage.  Existing UI tables and provider data
-- remain untouched; every row keeps source/effective/retrieval lineage.

alter table public.fundamental_observations
  add column if not exists period_start date,
  add column if not exists fiscal_year integer,
  add column if not exists context_id text,
  add column if not exists statement text,
  add column if not exists metadata jsonb not null default '{}'::jsonb;

create table if not exists public.fundamental_dimensional_facts (
  id bigint generated always as identity primary key,
  security_id uuid not null references public.securities(id) on delete cascade,
  provider text not null,
  taxonomy text not null,
  concept text not null,
  context_id text not null,
  period_start date,
  period_end date not null,
  filed_at date not null,
  fiscal_year integer,
  fiscal_period text,
  form_type text not null,
  accession_number text not null,
  unit text,
  value numeric,
  dimensions jsonb not null default '{}'::jsonb,
  source_url text not null,
  fetched_at timestamptz not null default now(),
  metadata jsonb not null default '{}'::jsonb,
  unique(security_id, provider, accession_number, concept, context_id, unit)
);

create index if not exists fundamental_dimensional_facts_lookup_idx
  on public.fundamental_dimensional_facts(security_id, period_end desc, filed_at desc);
create index if not exists fundamental_dimensional_facts_dimensions_idx
  on public.fundamental_dimensional_facts using gin(dimensions);

create table if not exists public.research_source_observations (
  id bigint generated always as identity primary key,
  ticker text not null,
  provider text not null,
  dataset text not null,
  metric text not null,
  effective_at timestamptz not null,
  retrieved_at timestamptz not null default now(),
  value_numeric numeric,
  value_text text,
  value_json jsonb,
  source_url text,
  entitlement text not null default 'existing_configured_plan',
  metadata jsonb not null default '{}'::jsonb,
  unique(ticker, provider, dataset, metric, effective_at)
);

create index if not exists research_source_observations_lookup_idx
  on public.research_source_observations(ticker, metric, effective_at desc);

create table if not exists public.research_read_models (
  ticker text not null,
  portfolio_id uuid,
  as_of timestamptz not null,
  model_version text not null,
  payload jsonb not null,
  section_statuses jsonb not null,
  provider_lineage jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now(),
  primary key(ticker, portfolio_id, as_of, model_version)
);

create index if not exists research_read_models_latest_idx
  on public.research_read_models(ticker, portfolio_id, as_of desc);

alter table public.fundamental_dimensional_facts enable row level security;
alter table public.research_source_observations enable row level security;
alter table public.research_read_models enable row level security;

revoke all on public.fundamental_dimensional_facts from anon, authenticated;
revoke all on public.research_source_observations from anon, authenticated;
revoke all on public.research_read_models from anon, authenticated;
revoke all on sequence public.fundamental_dimensional_facts_id_seq from anon, authenticated;
revoke all on sequence public.research_source_observations_id_seq from anon, authenticated;

comment on table public.fundamental_dimensional_facts is
  'Inline XBRL facts with original context axes and filing lineage; Company Facts is not used as a dimensional substitute.';
comment on table public.research_source_observations is
  'Normalized Research-only provider facts including entitled Polygon reference, session, ownership, and filing-section data.';
comment on table public.research_read_models is
  'Versioned shared Research/Ask read model; calculations are produced by backend/research_metrics.py.';

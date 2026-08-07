alter table public.macro_observations
add column if not exists is_point_in_time boolean not null default true,
add column if not exists metadata jsonb not null default '{}'::jsonb;

create table public.fundamental_periods (
  id bigint generated always as identity primary key,
  security_id uuid not null references public.securities(id) on delete cascade,
  provider text not null,
  period_end date not null,
  fiscal_period text,
  fiscal_year integer,
  metrics jsonb not null default '{}'::jsonb,
  data_quality_score double precision,
  source_url text,
  fetched_at timestamptz not null default now(),
  unique nulls not distinct (security_id, provider, period_end, fiscal_period, fiscal_year)
);

create table public.document_securities (
  document_id uuid not null references public.documents(id) on delete cascade,
  security_id uuid not null references public.securities(id) on delete cascade,
  relevance_score double precision,
  primary key (document_id, security_id)
);

create index fundamental_periods_lookup_idx
on public.fundamental_periods(security_id, period_end desc);

create index document_securities_security_idx
on public.document_securities(security_id, document_id);

alter table public.fundamental_periods enable row level security;
alter table public.document_securities enable row level security;

revoke all on public.fundamental_periods from anon, authenticated;
revoke all on public.document_securities from anon, authenticated;
revoke all on sequence public.fundamental_periods_id_seq from anon, authenticated;

comment on column public.macro_observations.is_point_in_time is 'False for legacy final-vintage cache rows; true for dated FRED/ALFRED retrievals.';
comment on table public.fundamental_periods is 'One provider reporting period per security with source-aware metrics stored as JSON.';

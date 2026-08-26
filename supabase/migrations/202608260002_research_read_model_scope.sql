-- Global Research models have no portfolio id.  Use an explicit stable scope
-- key instead of relying on NULL behavior in a primary key.
alter table public.research_read_models drop constraint if exists research_read_models_pkey;
alter table public.research_read_models alter column portfolio_id drop not null;
alter table public.research_read_models add column if not exists scope_key text not null default 'global';
alter table public.research_read_models add primary key(ticker,scope_key,as_of,model_version);

drop index if exists public.research_read_models_latest_idx;
create index research_read_models_latest_idx
  on public.research_read_models(ticker,scope_key,as_of desc);

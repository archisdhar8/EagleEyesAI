create table if not exists public.market_events (
  id uuid primary key default gen_random_uuid(),
  provider text not null,
  external_id text not null,
  event_type text not null check (event_type in ('earnings','macro_release','company_catalyst','market_event')),
  title text not null,
  starts_at timestamptz not null,
  tickers text[] not null default '{}',
  source_url text,
  metadata jsonb not null default '{}',
  fetched_at timestamptz not null default now(),
  unique(provider, external_id)
);

create table if not exists public.user_attention_dismissals (
  user_id uuid not null references auth.users(id) on delete cascade,
  attention_key text not null,
  dismissed_until timestamptz,
  created_at timestamptz not null default now(),
  primary key(user_id, attention_key)
);

create table if not exists public.briefing_snapshots (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  briefing_version text not null,
  evidence_state text not null,
  result jsonb not null,
  effective_at timestamptz not null,
  created_at timestamptz not null default now()
);

create index if not exists market_events_starts_at_idx on public.market_events(starts_at);
create index if not exists market_events_tickers_idx on public.market_events using gin(tickers);
create index if not exists briefing_snapshots_user_idx on public.briefing_snapshots(user_id, created_at desc);

alter table public.market_events enable row level security;
alter table public.user_attention_dismissals enable row level security;
alter table public.briefing_snapshots enable row level security;

revoke all on public.market_events, public.briefing_snapshots from anon, authenticated;
revoke all on public.user_attention_dismissals from anon;
grant select, insert, update, delete on public.user_attention_dismissals to authenticated;

create policy user_attention_dismissals_owner_all on public.user_attention_dismissals for all to authenticated
using (user_id=auth.uid()) with check (user_id=auth.uid());

comment on table public.market_events is 'Server-managed earnings, macro release, and catalyst calendar used by deterministic Today briefings.';
comment on table public.briefing_snapshots is 'Immutable user-owned Today briefing results retained for validated stale-data fallback.';

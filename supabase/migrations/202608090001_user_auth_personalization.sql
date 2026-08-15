alter table public.portfolios add column if not exists user_id uuid references auth.users(id) on delete cascade;
alter table public.investor_profiles add column if not exists user_id uuid references auth.users(id) on delete cascade;
alter table public.analysis_runs add column if not exists user_id uuid references auth.users(id) on delete cascade;
alter table public.chat_conversations add column if not exists user_id uuid references auth.users(id) on delete cascade;

create index if not exists portfolios_user_idx on public.portfolios(user_id, updated_at desc);
create index if not exists profiles_user_idx on public.investor_profiles(user_id, updated_at desc);
create index if not exists analysis_user_idx on public.analysis_runs(user_id, created_at desc);
create index if not exists conversations_user_idx on public.chat_conversations(user_id, updated_at desc);

create table if not exists public.dashboard_preferences (
  user_id uuid primary key references auth.users(id) on delete cascade,
  overview_widgets text[] not null default array['portfolio','macro','scenarios','research','freshness']::text[],
  macro_widgets text[] not null default array['rates','inflation','growth','labor','credit']::text[],
  research_widgets text[] not null default array['market','scores','fundamentals','news','prediction_markets']::text[],
  focused_tickers text[] not null default '{}',
  density text not null default 'comfortable' check (density in ('compact','comfortable')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create trigger dashboard_preferences_updated_at before update on public.dashboard_preferences
for each row execute function public.set_updated_at();
alter table public.dashboard_preferences enable row level security;

grant select, insert, update, delete on public.portfolios, public.holdings,
  public.investor_profiles, public.chat_conversations, public.chat_messages,
  public.chat_message_evidence, public.dashboard_preferences to authenticated;
grant select on public.analysis_runs to authenticated;

create policy portfolios_owner_all on public.portfolios for all to authenticated
using (user_id = auth.uid()) with check (user_id = auth.uid());
create policy holdings_owner_all on public.holdings for all to authenticated
using (exists (select 1 from public.portfolios p where p.id = portfolio_id and p.user_id = auth.uid()))
with check (exists (select 1 from public.portfolios p where p.id = portfolio_id and p.user_id = auth.uid()));
create policy profiles_owner_all on public.investor_profiles for all to authenticated
using (user_id = auth.uid()) with check (user_id = auth.uid());
create policy analyses_owner_read on public.analysis_runs for select to authenticated
using (user_id = auth.uid());
create policy conversations_owner_all on public.chat_conversations for all to authenticated
using (user_id = auth.uid()) with check (user_id = auth.uid());
create policy messages_owner_all on public.chat_messages for all to authenticated
using (exists (select 1 from public.chat_conversations c where c.id = conversation_id and c.user_id = auth.uid()))
with check (exists (select 1 from public.chat_conversations c where c.id = conversation_id and c.user_id = auth.uid()));
create policy message_evidence_owner_all on public.chat_message_evidence for all to authenticated
using (exists (select 1 from public.chat_messages m join public.chat_conversations c on c.id = m.conversation_id where m.id = message_id and c.user_id = auth.uid()))
with check (exists (select 1 from public.chat_messages m join public.chat_conversations c on c.id = m.conversation_id where m.id = message_id and c.user_id = auth.uid()));
create policy dashboard_preferences_owner_all on public.dashboard_preferences for all to authenticated
using (user_id = auth.uid()) with check (user_id = auth.uid());

comment on table public.dashboard_preferences is
  'Per-user widget visibility, density, and research focus. Sensitive holdings remain server-side.';

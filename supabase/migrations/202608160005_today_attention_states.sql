create table if not exists public.attention_item_states (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  attention_item_id text not null,
  state text not null check (state in ('READ','DISMISSED','SNOOZED','RESOLVED')),
  snoozed_until timestamptz,
  note text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(user_id, attention_item_id)
);

create index if not exists attention_item_states_user_idx
on public.attention_item_states(user_id, updated_at desc);

create trigger attention_item_states_updated_at
before update on public.attention_item_states
for each row execute function public.set_updated_at();

alter table public.attention_item_states enable row level security;

create policy attention_item_states_owner_select on public.attention_item_states
for select using (auth.uid() = user_id);
create policy attention_item_states_owner_insert on public.attention_item_states
for insert with check (auth.uid() = user_id);
create policy attention_item_states_owner_update on public.attention_item_states
for update using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy attention_item_states_owner_delete on public.attention_item_states
for delete using (auth.uid() = user_id);

revoke all on public.attention_item_states from anon, authenticated;
grant select,insert,update,delete on public.attention_item_states to authenticated;

comment on table public.attention_item_states is
'Per-user Today workflow state keyed to deterministic attention IDs; underlying evidence is never copied or deleted.';

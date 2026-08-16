-- Versioned conversation categories, bounded memory summaries, and durable
-- links from chat messages to deterministic runs or saved research boards.

alter table public.chat_conversations
  add column if not exists workspace text not null default 'research',
  add column if not exists summary text not null default '',
  add column if not exists summary_message_count integer not null default 0;

alter table public.chat_conversations
  drop constraint if exists chat_conversations_workspace_check;
alter table public.chat_conversations
  add constraint chat_conversations_workspace_check
  check (workspace in ('research', 'portfolio'));

create index if not exists conversations_user_workspace_updated_idx
  on public.chat_conversations(user_id, workspace, updated_at desc);

create table if not exists public.chat_artifact_links (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  conversation_id uuid not null references public.chat_conversations(id) on delete cascade,
  message_id uuid references public.chat_messages(id) on delete cascade,
  artifact_type text not null check (artifact_type in ('simulation_run', 'analysis_run', 'dashboard_view', 'research_snapshot')),
  artifact_id text not null,
  label text not null,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique(conversation_id, artifact_type, artifact_id)
);

create index if not exists chat_artifact_links_conversation_idx
  on public.chat_artifact_links(conversation_id, created_at desc);

alter table public.chat_artifact_links enable row level security;
grant select, insert, update, delete on public.chat_artifact_links to authenticated;

drop policy if exists chat_artifact_links_owner_all on public.chat_artifact_links;
create policy chat_artifact_links_owner_all on public.chat_artifact_links
  for all to authenticated
  using (
    user_id = auth.uid()
    and exists (
      select 1 from public.chat_conversations c
      where c.id = chat_artifact_links.conversation_id and c.user_id = auth.uid()
    )
  )
  with check (
    user_id = auth.uid()
    and exists (
      select 1 from public.chat_conversations c
      where c.id = chat_artifact_links.conversation_id and c.user_id = auth.uid()
    )
  );

revoke all on public.chat_artifact_links from anon;

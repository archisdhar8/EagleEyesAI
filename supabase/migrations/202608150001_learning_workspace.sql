-- EagleEyes Learn: additive user-owned learning state in the current Supabase project.
-- Curriculum documents remain versioned in source control; these tables store only user activity.

create table if not exists public.learning_preferences (
  user_id uuid primary key references auth.users(id) on delete cascade,
  selected_path text,
  knowledge_level text not null default 'beginner' check (knowledge_level in ('beginner','developing','confident')),
  interests jsonb not null default '[]'::jsonb,
  portfolio_context_enabled boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.learning_progress (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  module_id text not null,
  lesson_id text not null,
  content_version text not null,
  status text not null default 'not_started' check (status in ('not_started','in_progress','completed','mastered')),
  completion_percentage numeric not null default 0 check (completion_percentage between 0 and 1),
  started_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(user_id,lesson_id,content_version)
);

create table if not exists public.learning_quiz_attempts (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  module_id text not null,
  lesson_id text not null,
  content_version text not null,
  quiz_id text not null,
  quiz_version text not null,
  score integer not null check (score >= 0),
  total_questions integer not null check (total_questions > 0),
  percentage numeric not null check (percentage between 0 and 1),
  answers jsonb not null,
  attempted_at timestamptz not null default now()
);

create table if not exists public.learning_tutor_threads (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  lesson_id text not null,
  title text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.learning_tutor_messages (
  id uuid primary key default gen_random_uuid(),
  thread_id uuid not null references public.learning_tutor_threads(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  role text not null check (role in ('user','assistant')),
  content text not null,
  source_references jsonb not null default '[]'::jsonb,
  retrieval_quality jsonb not null default '{}'::jsonb,
  model_version text,
  created_at timestamptz not null default now()
);

create index if not exists learning_progress_user_updated_idx on public.learning_progress(user_id,updated_at desc);
create index if not exists learning_quiz_user_lesson_idx on public.learning_quiz_attempts(user_id,lesson_id,attempted_at desc);
create index if not exists learning_threads_user_updated_idx on public.learning_tutor_threads(user_id,updated_at desc);
create index if not exists learning_messages_thread_created_idx on public.learning_tutor_messages(thread_id,created_at);

alter table public.learning_preferences enable row level security;
alter table public.learning_progress enable row level security;
alter table public.learning_quiz_attempts enable row level security;
alter table public.learning_tutor_threads enable row level security;
alter table public.learning_tutor_messages enable row level security;

revoke all on public.learning_preferences,public.learning_progress,public.learning_quiz_attempts,public.learning_tutor_threads,public.learning_tutor_messages from anon;
grant select,insert,update,delete on public.learning_preferences,public.learning_progress,public.learning_tutor_threads,public.learning_tutor_messages to authenticated;
grant select,insert on public.learning_quiz_attempts to authenticated;

create policy learning_preferences_owner_select on public.learning_preferences for select to authenticated using (user_id=auth.uid());
create policy learning_preferences_owner_insert on public.learning_preferences for insert to authenticated with check (user_id=auth.uid());
create policy learning_preferences_owner_update on public.learning_preferences for update to authenticated using (user_id=auth.uid()) with check (user_id=auth.uid());
create policy learning_preferences_owner_delete on public.learning_preferences for delete to authenticated using (user_id=auth.uid());

create policy learning_progress_owner_select on public.learning_progress for select to authenticated using (user_id=auth.uid());
create policy learning_progress_owner_insert on public.learning_progress for insert to authenticated with check (user_id=auth.uid());
create policy learning_progress_owner_update on public.learning_progress for update to authenticated using (user_id=auth.uid()) with check (user_id=auth.uid());
create policy learning_progress_owner_delete on public.learning_progress for delete to authenticated using (user_id=auth.uid());

create policy learning_quiz_owner_select on public.learning_quiz_attempts for select to authenticated using (user_id=auth.uid());
create policy learning_quiz_owner_insert on public.learning_quiz_attempts for insert to authenticated with check (user_id=auth.uid());

create policy learning_threads_owner_select on public.learning_tutor_threads for select to authenticated using (user_id=auth.uid());
create policy learning_threads_owner_insert on public.learning_tutor_threads for insert to authenticated with check (user_id=auth.uid());
create policy learning_threads_owner_update on public.learning_tutor_threads for update to authenticated using (user_id=auth.uid()) with check (user_id=auth.uid());
create policy learning_threads_owner_delete on public.learning_tutor_threads for delete to authenticated using (user_id=auth.uid());

create policy learning_messages_owner_select on public.learning_tutor_messages for select to authenticated
  using (user_id=auth.uid() and exists(select 1 from public.learning_tutor_threads t where t.id=learning_tutor_messages.thread_id and t.user_id=auth.uid()));
create policy learning_messages_owner_insert on public.learning_tutor_messages for insert to authenticated
  with check (user_id=auth.uid() and exists(select 1 from public.learning_tutor_threads t where t.id=learning_tutor_messages.thread_id and t.user_id=auth.uid()));
create policy learning_messages_owner_update on public.learning_tutor_messages for update to authenticated
  using (user_id=auth.uid() and exists(select 1 from public.learning_tutor_threads t where t.id=learning_tutor_messages.thread_id and t.user_id=auth.uid()))
  with check (user_id=auth.uid() and exists(select 1 from public.learning_tutor_threads t where t.id=learning_tutor_messages.thread_id and t.user_id=auth.uid()));
create policy learning_messages_owner_delete on public.learning_tutor_messages for delete to authenticated
  using (user_id=auth.uid() and exists(select 1 from public.learning_tutor_threads t where t.id=learning_tutor_messages.thread_id and t.user_id=auth.uid()));

comment on table public.learning_progress is 'Versioned private lesson progress; curriculum content remains in source control.';
comment on table public.learning_quiz_attempts is 'Append-only private quiz attempts used for deterministic mastery.';
comment on table public.learning_tutor_messages is 'Private lesson-grounded tutor history; never used as a source of calculated market data.';

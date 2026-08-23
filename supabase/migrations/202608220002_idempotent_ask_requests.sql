-- Durable idempotency and lifecycle state for one logical Ask turn.
CREATE TABLE IF NOT EXISTS public.ask_requests (
  request_id text PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  conversation_id uuid REFERENCES public.chat_conversations(id) ON DELETE CASCADE,
  question_hash text NOT NULL,
  state text NOT NULL CHECK (state IN ('RECEIVED','EXECUTING','EXECUTED','COMPLETED','PARTIAL','UNAVAILABLE','FAILED','PERSISTENCE_FAILED')),
  user_message_id uuid REFERENCES public.chat_messages(id) ON DELETE SET NULL,
  assistant_message_id uuid REFERENCES public.chat_messages(id) ON DELETE SET NULL,
  staged_result jsonb,
  response jsonb,
  error_class text,
  received_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz
);
CREATE INDEX IF NOT EXISTS ask_requests_user_updated_idx ON public.ask_requests(user_id,updated_at DESC);
ALTER TABLE public.ask_requests ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
  CREATE POLICY ask_requests_owner ON public.ask_requests FOR ALL TO authenticated
    USING (user_id=auth.uid()) WITH CHECK (user_id=auth.uid());
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
REVOKE ALL ON public.ask_requests FROM anon;
GRANT SELECT,INSERT,UPDATE,DELETE ON public.ask_requests TO authenticated;

-- Phase 10: additive, owner-scoped alert history and transparent decision preferences.
CREATE TABLE IF NOT EXISTS public.alert_preferences (
  user_id uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  delivery_mode text NOT NULL DEFAULT 'IN_APP_ONLY' CHECK (delivery_mode = 'IN_APP_ONLY'),
  threshold text NOT NULL DEFAULT 'MATERIAL' CHECK (threshold IN ('MATERIAL','CRITICAL_ONLY')),
  categories jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.alert_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  attention_item_id text NOT NULL, group_key text NOT NULL, alert_type text NOT NULL, materiality text NOT NULL,
  title text NOT NULL, summary text NOT NULL, payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  occurred_at timestamptz NOT NULL, supersedes_id uuid REFERENCES public.alert_events(id) ON DELETE SET NULL,
  status text NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','SUPERSEDED')),
  created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(user_id, attention_item_id)
);
CREATE INDEX IF NOT EXISTS alert_events_user_status_idx ON public.alert_events(user_id,status,occurred_at DESC);
CREATE INDEX IF NOT EXISTS alert_events_user_group_idx ON public.alert_events(user_id,group_key,occurred_at DESC);

CREATE TABLE IF NOT EXISTS public.decision_preferences (
  user_id uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  explicit_preferences jsonb NOT NULL DEFAULT '{}'::jsonb,
  accepted_preferences jsonb NOT NULL DEFAULT '{}'::jsonb,
  dismissed_inferences jsonb NOT NULL DEFAULT '[]'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE public.alert_preferences ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alert_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.decision_preferences ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
  CREATE POLICY alert_preferences_owner ON public.alert_preferences FOR ALL TO authenticated USING (user_id=auth.uid()) WITH CHECK (user_id=auth.uid());
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
  CREATE POLICY alert_events_owner ON public.alert_events FOR ALL TO authenticated USING (user_id=auth.uid()) WITH CHECK (user_id=auth.uid());
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
  CREATE POLICY decision_preferences_owner ON public.decision_preferences FOR ALL TO authenticated USING (user_id=auth.uid()) WITH CHECK (user_id=auth.uid());
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

REVOKE ALL ON public.alert_preferences, public.alert_events, public.decision_preferences FROM anon;
GRANT SELECT,INSERT,UPDATE,DELETE ON public.alert_preferences, public.alert_events, public.decision_preferences TO authenticated;

-- Deterministic portfolio health history and durable action workflow.
CREATE TABLE IF NOT EXISTS public.portfolio_health_snapshots (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  portfolio_id uuid NOT NULL REFERENCES public.portfolios(id) ON DELETE CASCADE,
  snapshot_date date NOT NULL,
  trigger text NOT NULL CHECK (trigger IN ('NIGHTLY','PORTFOLIO_CHANGE','MATERIAL_EVENT','MANUAL')),
  input_hash text NOT NULL,
  health_score double precision NOT NULL,
  health_band text NOT NULL,
  confidence text NOT NULL,
  coverage double precision NOT NULL,
  components jsonb NOT NULL,
  holding_metrics jsonb NOT NULL,
  changes jsonb NOT NULL DEFAULT '[]'::jsonb,
  warnings jsonb NOT NULL DEFAULT '[]'::jsonb,
  result jsonb NOT NULL,
  methodology_version text NOT NULL,
  effective_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(user_id,portfolio_id,trigger,input_hash)
);
CREATE INDEX IF NOT EXISTS portfolio_health_history_idx
  ON public.portfolio_health_snapshots(user_id,portfolio_id,effective_at DESC);

CREATE TABLE IF NOT EXISTS public.portfolio_action_items (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  portfolio_id uuid NOT NULL REFERENCES public.portfolios(id) ON DELETE CASCADE,
  source_key text NOT NULL,
  source text NOT NULL,
  action_type text NOT NULL CHECK (action_type IN ('REVIEW','REDUCE','ADD','HOLD','INVESTIGATE')),
  title text NOT NULL,
  reason text NOT NULL,
  payload jsonb NOT NULL,
  priority double precision NOT NULL,
  state text NOT NULL DEFAULT 'OPEN' CHECK (state IN ('OPEN','INVESTIGATING','ACCEPTED','SNOOZED','COMPLETED','DISMISSED')),
  active boolean NOT NULL DEFAULT true,
  snoozed_until timestamptz,
  note text NOT NULL DEFAULT '',
  first_seen_at timestamptz NOT NULL DEFAULT now(),
  last_seen_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(user_id,portfolio_id,source_key)
);
CREATE INDEX IF NOT EXISTS portfolio_actions_queue_idx
  ON public.portfolio_action_items(user_id,portfolio_id,active,state,priority DESC);

ALTER TABLE public.portfolio_health_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.portfolio_action_items ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
  CREATE POLICY portfolio_health_owner ON public.portfolio_health_snapshots FOR ALL TO authenticated
    USING (user_id=auth.uid()) WITH CHECK (user_id=auth.uid());
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
  CREATE POLICY portfolio_actions_owner ON public.portfolio_action_items FOR ALL TO authenticated
    USING (user_id=auth.uid()) WITH CHECK (user_id=auth.uid());
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
REVOKE ALL ON public.portfolio_health_snapshots, public.portfolio_action_items FROM anon;
GRANT SELECT,INSERT,UPDATE,DELETE ON public.portfolio_health_snapshots, public.portfolio_action_items TO authenticated;

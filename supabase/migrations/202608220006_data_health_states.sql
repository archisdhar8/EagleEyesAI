-- Owner-scoped proactive analytical readiness.  This stores compact health
-- metadata only; raw provider payloads remain in their normalized datasets.
CREATE TABLE IF NOT EXISTS public.data_health_states (
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  portfolio_id uuid REFERENCES public.portfolios(id) ON DELETE CASCADE,
  scope_key text NOT NULL,
  domain text NOT NULL CHECK (domain IN (
    'prices','fundamentals','fundamental_history','classifications','events','macro',
    'earnings_events','macro_events','company_catalysts','prediction_market_events',
    'market','prediction_markets','portfolio_history','score_history','cash_hurdle'
  )),
  status text NOT NULL CHECK (status IN ('CURRENT','PARTIAL','STALE','MISSING','FAILED')),
  coverage double precision,
  freshness text,
  last_successful_update timestamptz,
  failure_reason text,
  repair_action text,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(user_id,scope_key,domain)
);

CREATE INDEX IF NOT EXISTS data_health_states_portfolio_idx
  ON public.data_health_states(user_id,portfolio_id,domain,updated_at DESC)
  WHERE portfolio_id IS NOT NULL;

ALTER TABLE public.data_health_states ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
  CREATE POLICY data_health_states_owner ON public.data_health_states FOR ALL TO authenticated
    USING (user_id=auth.uid()) WITH CHECK (user_id=auth.uid());
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
REVOKE ALL ON public.data_health_states FROM anon;
GRANT SELECT,INSERT,UPDATE,DELETE ON public.data_health_states TO authenticated;

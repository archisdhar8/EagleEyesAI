-- Versioned capability-specific analytical read models and their upstream dependency versions.
CREATE TABLE IF NOT EXISTS public.analytical_dataset_versions (
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  portfolio_id uuid NOT NULL REFERENCES public.portfolios(id) ON DELETE CASCADE,
  dataset_type text NOT NULL,
  version text NOT NULL,
  effective_through timestamptz,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(user_id,portfolio_id,dataset_type)
);

CREATE TABLE IF NOT EXISTS public.capability_read_models (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  portfolio_id uuid NOT NULL REFERENCES public.portfolios(id) ON DELETE CASCADE,
  read_model_type text NOT NULL,
  schema_version text NOT NULL,
  calculation_version text NOT NULL,
  input_fingerprint text NOT NULL,
  read_model_state text NOT NULL CHECK (read_model_state IN ('CURRENT','STALE','BUILDING','FAILED','MISSING')),
  metadata jsonb NOT NULL,
  data jsonb NOT NULL,
  failure_class text,
  failure_at timestamptz,
  stale_reason text,
  calculated_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS capability_read_models_lookup_idx
  ON public.capability_read_models(user_id,portfolio_id,read_model_type,calculated_at DESC,created_at DESC);

ALTER TABLE public.analytical_dataset_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.capability_read_models ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
  CREATE POLICY analytical_dataset_versions_owner ON public.analytical_dataset_versions FOR ALL TO authenticated
    USING (user_id=auth.uid()) WITH CHECK (user_id=auth.uid());
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
  CREATE POLICY capability_read_models_owner ON public.capability_read_models FOR ALL TO authenticated
    USING (user_id=auth.uid()) WITH CHECK (user_id=auth.uid());
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
REVOKE ALL ON public.analytical_dataset_versions, public.capability_read_models FROM anon;
GRANT SELECT,INSERT,UPDATE,DELETE ON public.analytical_dataset_versions, public.capability_read_models TO authenticated;

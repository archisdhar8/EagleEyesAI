-- Phase 9 production hardening: capability read models may be scoped to a
-- portfolio, a company (company:MSFT), or a global domain projection.  The
-- original Phase 2 schema incorrectly required every scope to be a portfolio
-- UUID and therefore rejected Phase 6 company/global materializations.

ALTER TABLE public.analytical_dataset_versions
  ADD COLUMN IF NOT EXISTS scope_key text;
ALTER TABLE public.capability_read_models
  ADD COLUMN IF NOT EXISTS scope_key text;

UPDATE public.analytical_dataset_versions
SET scope_key = 'portfolio:' || portfolio_id::text
WHERE scope_key IS NULL;
UPDATE public.capability_read_models
SET scope_key = 'portfolio:' || portfolio_id::text
WHERE scope_key IS NULL;

ALTER TABLE public.analytical_dataset_versions
  DROP CONSTRAINT IF EXISTS analytical_dataset_versions_pkey;
ALTER TABLE public.analytical_dataset_versions
  ALTER COLUMN portfolio_id DROP NOT NULL,
  ALTER COLUMN scope_key SET NOT NULL;
ALTER TABLE public.capability_read_models
  ALTER COLUMN portfolio_id DROP NOT NULL,
  ALTER COLUMN scope_key SET NOT NULL;
ALTER TABLE public.analytical_dataset_versions
  ADD CONSTRAINT analytical_dataset_versions_pkey PRIMARY KEY(user_id,scope_key,dataset_type);

CREATE INDEX IF NOT EXISTS analytical_dataset_versions_portfolio_idx
  ON public.analytical_dataset_versions(user_id,portfolio_id,dataset_type,updated_at DESC)
  WHERE portfolio_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS capability_read_models_scope_lookup_idx
  ON public.capability_read_models(user_id,scope_key,read_model_type,calculated_at DESC,created_at DESC);
CREATE INDEX IF NOT EXISTS capability_read_models_portfolio_reconcile_idx
  ON public.capability_read_models(user_id,portfolio_id,read_model_type,calculated_at DESC)
  WHERE portfolio_id IS NOT NULL;

COMMENT ON COLUMN public.capability_read_models.scope_key IS
  'Authorization-neutral analytical scope such as portfolio:<uuid>, company:MSFT, or global:macro_state.';
COMMENT ON COLUMN public.analytical_dataset_versions.scope_key IS
  'Dependency-version scope matching capability_read_models.scope_key.';

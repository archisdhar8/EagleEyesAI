-- Phase 5 durable heavy analytics. Generated only; do not apply automatically.
CREATE TABLE IF NOT EXISTS public.analytical_jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  job_type text NOT NULL CHECK (job_type IN ('SIMULATION','OPTIMIZATION','BACKTEST','COMPANY_RESEARCH_BUILD','THESIS_MONITOR')),
  request_id uuid, user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  portfolio_id uuid REFERENCES public.portfolios(id) ON DELETE CASCADE,
  input_fingerprint text NOT NULL, schema_version text NOT NULL,
  calculation_version text NOT NULL, worker_version text NOT NULL,
  status text NOT NULL CHECK (status IN ('QUEUED','RUNNING','SUCCESS','PARTIAL','FAILED','CANCELLED','EXPIRED')),
  created_at timestamptz NOT NULL DEFAULT now(), started_at timestamptz, completed_at timestamptz,
  progress_stage text NOT NULL DEFAULT 'queued', progress_percent integer CHECK (progress_percent BETWEEN 0 AND 100),
  input_payload jsonb NOT NULL, result_reference text, result_payload jsonb,
  error_class text, safe_error_summary text, retry_count integer NOT NULL DEFAULT 0,
  max_retries integer NOT NULL DEFAULT 2 CHECK (max_retries BETWEEN 0 AND 10),
  deduplication_key text NOT NULL, expires_at timestamptz,
  worker_id text, lease_expires_at timestamptz, heartbeat_at timestamptz, next_attempt_at timestamptz,
  queue_wait_ms double precision, execution_ms double precision
);
CREATE UNIQUE INDEX IF NOT EXISTS analytical_jobs_active_dedupe_idx
  ON public.analytical_jobs(user_id,deduplication_key)
  WHERE status IN ('QUEUED','RUNNING','SUCCESS','PARTIAL');
CREATE INDEX IF NOT EXISTS analytical_jobs_claim_idx ON public.analytical_jobs(status,next_attempt_at,created_at);
CREATE INDEX IF NOT EXISTS analytical_jobs_lease_idx ON public.analytical_jobs(status,lease_expires_at);

CREATE TABLE IF NOT EXISTS public.analytical_job_attempts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), job_id uuid NOT NULL REFERENCES public.analytical_jobs(id) ON DELETE CASCADE,
  attempt_number integer NOT NULL, worker_id text, started_at timestamptz NOT NULL,
  completed_at timestamptz, status text NOT NULL, error_class text, safe_error_summary text,
  execution_ms double precision, UNIQUE(job_id,attempt_number)
);

ALTER TABLE public.analytical_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.analytical_job_attempts ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
  CREATE POLICY analytical_jobs_owner ON public.analytical_jobs FOR ALL TO authenticated
    USING (user_id=auth.uid()) WITH CHECK (user_id=auth.uid());
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
  CREATE POLICY analytical_job_attempts_owner ON public.analytical_job_attempts FOR SELECT TO authenticated
    USING (EXISTS (SELECT 1 FROM public.analytical_jobs j WHERE j.id=job_id AND j.user_id=auth.uid()));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
REVOKE ALL ON public.analytical_jobs, public.analytical_job_attempts FROM anon;
GRANT SELECT,INSERT,UPDATE ON public.analytical_jobs TO authenticated;
GRANT SELECT ON public.analytical_job_attempts TO authenticated;

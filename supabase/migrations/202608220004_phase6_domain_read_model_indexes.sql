-- Generated for Phase 6. Do not apply automatically.
-- Domain projections reuse capability_read_models with narrow scope ids such
-- as company:MSFT and global:macro_state; history remains append-only.

create index if not exists capability_read_models_domain_history_idx
  on public.capability_read_models(user_id, read_model_type, portfolio_id, calculated_at desc);

create index if not exists analytical_dataset_versions_domain_scope_idx
  on public.analytical_dataset_versions(user_id, dataset_type, portfolio_id, updated_at desc);

comment on index public.capability_read_models_domain_history_idx is
  'Phase 6 compatible-current/previous baseline selection for narrow company, macro, market, and prediction scopes.';

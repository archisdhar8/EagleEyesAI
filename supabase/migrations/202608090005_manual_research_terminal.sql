alter table public.dashboard_preferences
  add column if not exists terminal_widgets jsonb not null default '[
    {"id":"portfolio-return","type":"portfolio_return","size":"wide"},
    {"id":"macro-regime","type":"macro_regime","size":"small"},
    {"id":"scenario-map","type":"scenario_probabilities","size":"small"},
    {"id":"macro-indicators","type":"macro_indicators","size":"wide"},
    {"id":"price-board","type":"price_board","size":"wide"},
    {"id":"research-scores","type":"research_scores","size":"wide"}
  ]'::jsonb;

comment on column public.dashboard_preferences.terminal_widgets is
  'User-owned manual research terminal widget order, type, and size. Contains layout preferences only.';

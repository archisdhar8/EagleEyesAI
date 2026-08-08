create table public.macro_regime_labels (
  as_of_date date not null,
  model_version text not null,
  dominant_regime text not null check (
    dominant_regime in (
      'soft_landing', 'sticky_inflation', 'recession_cuts',
      'growth_reacceleration', 'oil_shock'
    )
  ),
  probabilities jsonb not null,
  inputs jsonb not null,
  confidence double precision not null check (confidence between 0 and 1),
  data_quality double precision not null check (data_quality between 0 and 1),
  is_point_in_time boolean not null default true,
  created_at timestamptz not null default now(),
  primary key (as_of_date, model_version)
);

create index macro_regime_labels_dominant_idx
on public.macro_regime_labels(dominant_regime, as_of_date desc);

alter table public.macro_regime_labels enable row level security;
revoke all on public.macro_regime_labels from anon, authenticated;

comment on table public.macro_regime_labels is
'Monthly macro regime probabilities calculated only from observations and vintages available on each as-of date.';

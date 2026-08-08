-- Remove prediction-market records contaminated by the v1 substring matcher.
-- In particular, `brent` previously matched `Brentford` and mislabeled soccer
-- contracts as Brent crude oil evidence.

delete from public.scenario_snapshots ss
where exists (
  select 1
  from jsonb_array_elements(coalesce(ss.raw_contracts, '[]'::jsonb)) contract
  where lower(coalesce(contract->>'title', '')) ~
    '(^|[^[:alnum:]_])vs([.]|[^[:alnum:]_]|$)|winner[[:space:]]*\?|(^|[^[:alnum:]_])(match|game|score|goal|goals|league|tournament|playoff|playoffs)([^[:alnum:]_]|$)'
);

delete from public.prediction_markets
where lower(title) ~
  '(^|[^[:alnum:]_])vs([.]|[^[:alnum:]_]|$)|winner[[:space:]]*\?|(^|[^[:alnum:]_])(match|game|score|goal|goals|league|tournament|playoff|playoffs)([^[:alnum:]_]|$)';

delete from public.prediction_contract_series series
where not exists (
  select 1 from public.prediction_markets market where market.series_id = series.id
);

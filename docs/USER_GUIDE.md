# EagleEyes AI — Complete App Description and User Guide

## 1. What EagleEyes is

EagleEyes is a private, market-first investment research workspace. It brings portfolio information, stock research, macroeconomic evidence, historical market states, prediction markets, scenario analysis, transparent portfolio modeling, and AI-generated research boards into one application.

It is built to help a self-directed investor answer questions such as:

- What kind of market environment are we in?
- Which economic forces matter most to my portfolio?
- How strong is the evidence for a company’s growth, valuation, and business quality?
- How did comparable securities behave during similar historical conditions?
- Is my portfolio concentrated or poorly diversified?
- What changes could reduce risk, and what would they cost?
- Where might the next contribution be directed without selling existing positions?
- What evidence supports a conclusion, and what could make it wrong?

EagleEyes is research and decision-support software. It does not connect to a brokerage, place orders, select tax lots, guarantee returns, or claim to produce a universally “best” portfolio.

## 2. Product structure

The application has six primary workspaces:

| Workspace | Purpose |
|---|---|
| **Home** | A concise, portfolio-linked market briefing and prioritized attention items. |
| **Plan** | Goals, investor profile, projections, investment policy, research preferences, and planning guidance. |
| **Portfolio** | Holdings, imports, allocation, portfolio status, and transparent change options. |
| **Explore** | Searchable stock research, market-environment research, scenarios, prediction markets, comparisons, and watchlists. |
| **Ask EagleEyes** | Natural-language questions that produce evidence-backed research boards. |
| **Advanced** | A manual research terminal plus model diagnostics, validation, and data lineage. |

The app defaults to a **Detailed** presentation. A persistent Simple/Detailed/Expert control changes how much explanation and technical evidence is visible without changing the underlying calculations.

## 3. Data, calculations, and AI boundaries

EagleEyes combines four layers of evidence:

1. **User information** — holdings, account types, cost basis, watchlist, restrictions, goals, risk preferences, and an approved investment policy.
2. **External and stored research data** — adjusted prices, SEC fundamentals, FRED/ALFRED macro data, news, Kalshi, Polymarket, and provider snapshots.
3. **Deterministic calculations** — returns, drawdowns, correlations, macro sensitivities, historical regimes, covariance estimates, projections, optimization, and validation.
4. **Optional Gemini interpretation** — intent planning and plain-language explanation of already validated results.

Gemini does not calculate prices, returns, probabilities, research ratings, rankings, correlations, sensitivities, taxes, projections, or portfolio allocations. Application code performs those operations and attaches sources, dates, assumptions, and calculation versions.

## 4. Accounts, privacy, and storage

Supabase provides email/password authentication and user-owned persistence. Row-level security separates each user’s portfolios, goals, policies, AI boards, terminal layouts, and analysis runs.

Supabase stores:

- Portfolios and holdings.
- Investor profile and goals.
- Investment policy and research preferences.
- Goal projections and portfolio analyses.
- Saved AI research boards and manual terminal layouts.
- Cached provider observations and historical snapshots.
- Research records, prediction-market snapshots, regime labels, validation folds, and monitoring results.

Sensitive holdings are not stored in ordinary browser storage. Browser storage is limited to device-level presentation preferences where appropriate.

## 5. Home

Home answers: **“What currently matters to this portfolio?”**

It intentionally avoids leading with a numeric macro score. Instead, it produces a short market-and-portfolio conclusion such as:

> Rates and credit conditions currently matter more to this portfolio than oil. Technology concentration is the largest portfolio-specific risk. No urgent allocation change is supported by the available evidence.

### Market and portfolio status

Home can summarize:

- Current market environment.
- Rates, inflation, growth, labor, credit, oil, and other relevant channels.
- Portfolio concentration and diversification.
- Data freshness and missing research coverage.
- Important portfolio-linked catalysts.

### Attention items

No more than three issues are prioritized. Examples include:

- A position or sector exceeds a policy threshold.
- A major holding is unusually exposed to current conditions.
- Correlations increased and diversification weakened.
- Research data required for a conclusion is stale.
- A material event affects a large holding.

Each item explains what changed, why it matters, affected holdings, confidence, freshness, and where to investigate it.

### Quick actions

Home links directly into the relevant stock, macro factor, portfolio analysis, AI board, or Advanced terminal widget.

## 6. Plan

Plan is a supporting workspace for personal context. It does not replace the market-first Home experience.

### Investor profile

The profile captures planning and model context such as age, retirement age, horizon, account type, contributions, withdrawals, tax rate, risk tolerance, loss capacity, income needs, watchlist, and exclusions.

### Multiple goals

The user can create separate goals for:

- Retirement.
- Home purchase.
- Education.
- Emergency reserve.
- Near-term income.
- Wealth preservation.
- General long-term growth.

Every goal includes:

- Target amount and target date.
- Current funded value.
- Annual contribution.
- Priority.
- Funding source.
- Fixed, somewhat flexible, or very flexible timing.
- Inflation-adjustment preference.
- Explicit account allocations.

Account allocation percentages prevent the same account value from being counted twice across multiple goals.

### Goal projections

Deterministic projections show:

- On-track range.
- Estimated goal-attainment frequency.
- Required annual and monthly contribution.
- Earliest plausible goal date.
- Nominal and inflation-adjusted outcomes.
- Effect of contributing an additional $300 per month.
- Consequences of using a lower-return/lower-risk assumption.
- Most influential assumptions and limitations.

These are modeled ranges, not guarantees.

### Personal investment policy

The user can save a draft or approve a plain-language Investment Policy Statement containing:

- Target allocation and acceptable ranges.
- Minimum cash reserve.
- Maximum single-stock and sector exposure.
- Rebalancing threshold and review frequency.
- Investment exclusions.
- Conditions that justify reviewing the strategy.
- Conditions that do not justify changing it, such as ordinary volatility or one unsupported headline.

Recommendations can then be checked against the approved policy instead of reacting to every market movement.

### Research customization

The user can adjust the relative emphasis placed on:

- Fundamentals.
- Growth.
- Valuation.
- Dividend/income characteristics.
- Macro resilience.
- Historical price behavior.

These preferences modify a transparent weighted research layer. They do not silently retrain or promote a personalized black-box model. Any experimental model must pass walk-forward validation and a recorded promotion decision.

### Guidance and monitoring

Plan includes three practical outputs:

1. **What should I do next?** — policy-checked research options with expected benefit, costs, taxes, risks, alternatives, consequence of doing nothing, confidence, missing information, review date, and reversal evidence.
2. **Next dollar guidance** — an illustrative destination for the next contribution based on underweights, concentration, account type, taxes, employer match, and goals.
3. **Decision triggers** — high-quality alerts for policy breaches, deteriorating goal outlook, insufficient reserves, stale data, tax-loss opportunities, or portfolio behavior inconsistent with the approved plan.

Routine price alerts and gamified “opportunity” prompts are intentionally excluded.

## 7. Portfolio

Portfolio is the saved source of truth used throughout the application.

### Holdings editor

Holdings can include:

- Symbol/ticker.
- Shares or units.
- Weight.
- Market value.
- Aggregate cost basis.
- Account type.
- Optional acquisition date.

The editor validates missing symbols, invalid numbers, duplicate tickers, incomplete sizing, and unsaved changes. After saving, new symbols are added to the research-ingestion workflow.

### Flexible portfolio import

The importer accepts CSV, TSV, semicolon-delimited, and pipe-delimited files. It recognizes common broker-export aliases including:

- `ticker`, `symbol`, `security`, `stock`, `instrument`, or `code`.
- `shares`, `quantity`, `qty`, or `units`.
- Decimal weights, percentage weights, or allocation columns.
- Market/current/position value.
- Cost basis, total cost, or book value.
- Account and acquisition-date variants.

Extra unrelated columns are ignored. The importer can derive market value from shares and price, interpret percentages, combine duplicate symbols, and warn when it must assign placeholder equal weights because no sizing information exists. Imports support up to 500 holdings.

### Portfolio status

The Portfolio workspace can show:

- Position, sector, and industry allocation.
- Concentration and diversification.
- Historical volatility and drawdown.
- Correlations and macro exposures.
- Known costs and approximate tax implications.
- Goal relevance when Plan data exists.

Historical performance reconstructed from today’s holdings is labeled:

> Hypothetical one-year return using current holdings and weights

It is not described as actual account performance because actual performance requires transaction history, historical positions, deposits, withdrawals, and distributions.

### Analysis and implementation paths

Portfolio analysis compares:

1. Current portfolio / do nothing.
2. Contributions-only adjustment.
3. Gradual transition.
4. Immediate transition.

Where appropriate, transparent Risk-Controlled and Balanced alternatives remain available. Each path can report target ranges, deltas, expected modeled benefit, volatility, drawdown, scenario outcomes, turnover, estimated taxes, goal effects, costs, risks, assumptions, and the consequence of doing nothing.

The optimizer returns conflicting constraints rather than silently relaxing them. It never submits trades.

## 8. Explore

Explore is the primary market and security research workspace.

### Stock Research

Stock Research replaces the old wide score table with a searchable research library.

Users can search by:

- Ticker.
- Company name.
- Sector.
- Industry.

Results can be filtered into word-based evidence buckets:

- **Leading evidence**.
- **Constructive evidence**.
- **Mixed evidence**.
- **Weak evidence**.
- **Limited evidence**.

Each security separately reports:

- Growth: Strong, Supportive, Mixed, Cautious, or Weak.
- Valuation: Strong, Supportive, Mixed, Cautious, or Weak.
- Business quality.
- Industry position.
- Historical price behavior.
- Relative position within the visible universe.
- Current price and one-year price context when available.
- Portfolio fit.
- Confidence and data quality.
- Primary risks.
- Evidence freshness.
- What would change the current view.

Exact 0–100 component scores are reserved for Expert view. Word buckets are comparative research summaries, not recommendations or probabilities of future gains.

The visible universe is disclosed and normally consists of current holdings, watchlist names, explicitly researched securities, and supported broad or sector ETFs. It is not automatically the entire stock market.

### Market Environment

Market Environment answers: **“What kind of market are we in?”**

It identifies the current broad market state from separate evidence about:

- Interest rates and the yield curve.
- Inflation.
- Economic growth.
- Labor and wages.
- Credit conditions.
- Oil and other market-observed macro series where available.

Each channel is labeled Rising, Falling, Broadly stable, or Awaiting trend, with the effective date, current observations, change from the preceding stored observation, and original FRED source.

The market identity is a research classification, not a market-timing instruction.

### Similar historical market states

The Market Environment page shows the number of monthly point-in-time observations assigned to each historical state and each state’s share of the classified history. This helps the user understand sample depth and how frequently a similar evidence configuration occurred.

Comparable states are not claimed to be identical events. Scenario-conditioned security performance lives in Scenarios, while fold-level validation and model diagnostics live in Advanced.

### Scenarios

Scenarios keeps different dimensions separate rather than forcing overlapping events into one 100% distribution:

- Economic conditions: expansion, slowdown, or recession.
- Inflation conditions: cooling, stable, or accelerating.
- Rate conditions: easing, stable, or tightening.
- Independent shocks: oil, credit, geopolitical, or other supported shocks.

This allows combinations such as recession plus accelerating inflation plus an oil shock.

Scenario research can show historical sample counts, conditioned security behavior, portfolio sensitivity, evidence confidence, and what could change the classification.

### Prediction Markets

Kalshi and Polymarket remain independent evidence sources.

- Related contracts describing the same event are grouped.
- Threshold contracts are displayed as one ladder or event family.
- Overlapping events are not treated as independent proof.
- Liquidity/activity, confidence, expiry, mapping, freshness, and source remain visible.

Prediction markets can influence scenario evidence but cannot override macro history, company quality, valuation, diversification, or hard portfolio constraints.

### Compare Stocks and Watchlist

Compare Stocks places covered securities side by side using strengths, weaknesses, valuation view, portfolio fit, risk, confidence, and freshness. Watchlist limits the research library to symbols saved in the user’s profile.

## 9. Ask EagleEyes

Ask EagleEyes turns a natural-language research question into an evidence-backed research board.

Example questions include:

- “Which holdings are most sensitive to inflation?”
- “Compare AAPL and MSFT on growth, valuation, drawdown, and portfolio fit.”
- “Which securities in my universe have historically moved with oil returns?”
- “What changes if growth slows while inflation accelerates?”
- “Can new contributions improve diversification without selling?”

### Processing pipeline

```text
Question
→ intent planner
→ validated DashboardPlan
→ deterministic widget compiler
→ execution dependency graph
→ approved data services and calculations
→ widget verification
→ progressive research board
→ narrative verification
```

The planner identifies the requested entities, factors, time range, comparisons, and outputs. Application code—not Gemini—selects approved widgets and calculations.

### Progressive and partial results

The board reports planning, validation, fetching, calculation, widget readiness, narration, completion, partial success, failure, cancellation, and expiry. Successful widgets remain visible when an optional task or narrative fails.

### Result integrity

Every numeric widget includes:

- Effective date.
- Provider and dataset lineage.
- Cache status.
- Calculation method and version.
- Units, frequency, period, and sample count where relevant.
- Data quality and appropriate confidence dimensions.
- Assumptions, warnings, and missing-data treatment.
- A collapsible “How this was calculated” explanation.

### Board management

Users can revise, cancel, rearrange, add approved widgets, save, reopen, refresh, rename, duplicate, discard, and delete boards. AI-generated boards remain separate from the manual Advanced terminal.

## 10. Advanced

Advanced contains the manual research terminal and technical audit evidence.

### Manual research terminal

Users can add, move, resize, remove, save, reopen, rename, duplicate, reset, and delete layouts containing widgets for:

- Portfolio return, allocation, and positions.
- Security prices and watchlists.
- Sector performance.
- Correlations and heatmaps.
- Macro observations and market prices.
- Yield curves, oil, and commodities.
- Scenario estimates and historical regimes.
- Kalshi and Polymarket search.
- Fundamentals, valuation, earnings, catalysts, and research rankings.
- Optimizer snapshots and data freshness.

The terminal and Ask EagleEyes share approved widgets, calculation services, and result formats, but they remain separate saved products.

### Model diagnostics

Expert evidence includes:

- Covariance shrinkage and conditioning.
- Effective rank and imputation fraction.
- Historical regime sample counts.
- Sector-proxy fallbacks and price coverage.
- Calculation assumptions and model versions.

### Validation

The walk-forward runner uses expanding historical windows and compares the transparent model with equal-weight and static-allocation benchmarks. It records out-of-sample performance, turnover, dates, eligible assets, regime sample depth, and leakage checks.

An experimental ML regime classifier is a challenger only. It cannot become the production model unless predefined calibration and loss improvements are demonstrated and a promotion decision is recorded.

### Data lineage

The lineage view displays stored record counts, effective dates, provider status, stale data, and proxy fallbacks so users can distinguish current facts from missing or outdated evidence.

## 11. Data providers

### Security prices

- Tiingo can provide longer adjusted-price history.
- Polygon supports recent price and market data.
- Corporate-action-adjusted history is preferred.
- Sector ETFs can provide transparent proxies when an individual security lacks sufficient history.

### Macroeconomic data

- FRED supplies current observations.
- ALFRED vintages support point-in-time historical classification and reduce look-ahead bias.
- Market-observed series such as oil and Treasury yields can be stored as non-revised proxies.

### Company research

- SEC Company Facts supplies primary public fundamentals where available.
- Stored company and industry evidence supports growth, valuation, business-quality, and industry research.
- News and catalysts are cached, dated, and treated as supporting evidence.

### Prediction markets

- Kalshi supplies public market-event data.
- Polymarket Gamma/CLOB interfaces supply eligible macro and company-event markets.

Provider data is cached and timestamped. A failed refresh preserves the latest validated snapshot and displays a stale-data warning.

## 12. Recommended workflows

### First setup

1. Sign in.
2. Open Portfolio and enter or import holdings.
3. Save the portfolio so research ingestion can begin.
4. Open Plan to add goals, constraints, and an investment policy if desired.
5. Open Explore → Stock Research and refresh evidence.
6. Review Explore → Market Environment and data freshness.

### Researching a stock

1. Open Explore → Stock Research.
2. Search by symbol, company, sector, or industry.
3. Read the overall word bucket and individual component buckets.
4. Check valuation, portfolio fit, confidence, freshness, risk, and reversal evidence.
5. Use Compare Stocks or Ask EagleEyes for a focused comparison.

### Researching the market

1. Open Explore → Market Environment.
2. Read the current market identity and individual macro trends.
3. Review historical state counts and sample depth.
4. Open Scenarios for historical security sensitivity.
5. Review Prediction Markets as a separate forward-looking evidence layer.

### Portfolio review

1. Confirm holdings, weights, cost basis, and accounts.
2. Review Home attention items.
3. Run Portfolio analysis.
4. Compare doing nothing, contribution-only, gradual, and immediate paths.
5. Inspect costs, taxes, turnover, risks, assumptions, and reversal evidence.
6. Use Advanced only when technical diagnostics are needed.

## 13. Important limitations

- EagleEyes is not a broker, fiduciary adviser, or trade-execution system.
- Historical relationships do not prove causation or guarantee persistence.
- Current-weight reconstructed performance is not actual account performance.
- The stock universe is disclosed and may not cover the full market.
- Prediction-market history is still accumulating.
- Some securities, macro series, company events, or news may have incomplete coverage.
- Modeled returns, scenarios, sensitivities, and projections are uncertain estimates.
- Tax estimates use aggregate inputs and omit tax-lot selection, wash sales, Social Security, RMDs, Roth conversions, and withdrawal sequencing.
- Personalized research weights are transparent preferences, not automatically promoted personalized ML models.
- No analysis submits a trade.

When evidence is missing, stale, weak, or statistically unstable, the correct result is an unavailable output or explicit warning—not an invented number.

## 14. Glossary

- **Adjusted price** — security price history adjusted for corporate actions such as splits and, depending on the provider, distributions.
- **Data quality** — completeness and freshness of the underlying observations.
- **Research confidence** — strength, coverage, freshness, and consistency of company evidence; not the probability a security will rise.
- **Scenario confidence** — strength and agreement of the historical, macro, and prediction-market evidence supporting a scenario.
- **Correlation** — historical co-movement from -1 to +1; not proof of causation.
- **Sensitivity** — estimated historical relationship between a security return and a specified factor change.
- **Drawdown** — decline from a prior peak to a later trough.
- **Point-in-time data** — information limited to what would have been available on a historical date.
- **Market state/regime** — a labeled configuration of macro evidence used to organize historical comparisons.
- **Covariance shrinkage** — stabilizing a noisy covariance matrix by pulling it toward a structured target.
- **Walk-forward validation** — repeatedly estimating a model on earlier data and evaluating it on later unseen data.
- **Evidence bucket** — a plain-language relative research category, not a recommendation or target price.

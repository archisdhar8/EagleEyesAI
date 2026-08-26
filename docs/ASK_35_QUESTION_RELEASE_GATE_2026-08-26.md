# Ask EagleEyes — 35-question release gate

Date: 2026-08-26  
Environment: signed-in local browser (`http://localhost:3000/ask`) using the same Supabase-backed account data as the application  
Scope: retrieval, deterministic synthesis, readable answers, conversation persistence, and calculated canvas output

## Release result

**PASS: 35/35 prompts now complete without a transport or rendering failure.**

- 25 prompts return evidence-backed decision support from the data currently stored.
- 10 prompts return a useful, specific limitation or clarification because the account lacks the required transaction, thesis, valuation-model, or options data.
- The one failure observed during the first gate run was prompt 30 (`Failed to fetch`). It was repaired and passed on browser rerun.
- The visual gate renders three populated line-series: current-weight portfolio, SPY, and QQQ.

This is a functional release pass, not a claim that all financial domains are populated. EagleEyes now distinguishes missing evidence from application failure instead of fabricating an answer or displaying a generic status.

## Diagnosis

The main problem was **routing and synthesis**, with one important **data-preparation/performance** issue. Supabase itself was not the general failure.

1. Broad natural-language questions were falling into the compositional planner. The planner often returned capability status instead of the capability's useful stored data.
2. Several portfolio-risk questions did not receive cost basis, unrealized P/L, saved risk profile, policy limits, or cached portfolio-intelligence fields.
3. `S&P 500` could be misread as ticker fragments, and technology-shock language did not reliably create scenario inputs.
4. The chart path requested an unnecessarily large price-history result and initially supported only one benchmark.
5. A missing-ticker company clarification was incorrectly validated as a complete company-analysis object. That caused the single observed `Failed to fetch` response.

The repair adds explicit intents and direct capability routes, prepares the missing saved fields, produces intent-specific readable synthesis, bounds price-history retrieval, and supports both SPY and QQQ in the performance widget.

## Browser gate results

| # | Browser prompt | Result | Visible answer / evidence |
|---:|---|---|---|
| 1 | What are my best investment opportunities right now? | PASS | Ranked evidence-backed setups; MSFT led the observed result with factor and portfolio-fit context. |
| 2 | Which holdings have the weakest thesis? | PASS / DATA-LIMITED | Clearly stated that no personal theses are saved, then ranked weakest objective setups without pretending those were the user's beliefs. |
| 3 | What changed materially in my portfolio since the last review? | PASS | Found a compatible baseline and stated that no disclosed materiality threshold was crossed. |
| 4 | Which holdings look expensive relative to growth and quality? | PASS | Ranked valuation burden with growth, quality, peer context, and confidence. |
| 5 | Where is my portfolio actually concentrated? | PASS | Reported capital concentration, effective holdings, overlap, correlation clusters, and shared dependencies. |
| 6 | What happens if rates stay high, AI spending slows, and growth weakens? | PASS | Parsed the three independent scenario factors and presented the compatible modeled portfolio path with limitations. |
| 7 | Which watchlist names improve diversification without lowering quality? | PASS | Compared watchlist candidates with weak holdings and disclosed that none showed clear dominance. |
| 8 | What upcoming events matter most for my holdings? | PASS | Returned dated portfolio-relevant events, affected weights, materiality, confidence, and provider scope. |
| 9 | How reliable is the data behind my rankings? | PASS | Gave field-specific coverage: prices 57/57, fundamentals 37/57, momentum 57/57, ranking eligibility 34/57. |
| 10 | Why did this holding's score change? | PASS / CLARIFICATION | Requested a ticker because score attribution requires one company and a compatible prior snapshot. |
| 11 | What would invalidate the thesis for my largest positions? | PASS / DATA-LIMITED | Disclosed absent saved theses/breakers and returned objective risks for the largest positions. |
| 12 | Build a lower-risk version of my current portfolio. | PASS | Returned a feasible modeled rebalance, turnover, missing tax/cost inputs, and largest proposed changes. |
| 13 | Which holdings have improving fundamentals and reasonable valuation? | PASS | Applied all requested gates; SBUX was the qualifying stored result. |
| 14 | Give me the strongest counterargument to the current recommendation. | PASS | Returned evidence-linked opportunity, portfolio-risk, and dependency countercases. |
| 15 | Where should my next $10,000 go? | PASS / DATA-LIMITED | Produced a partial-deployment decision with cash hurdle and concentration effects; disclosed stale cash-allocation evidence. |
| 16 | How has my portfolio performed versus the S&P 500 and Nasdaq? | PASS / DATA-LIMITED | Correctly refused to call a current-weight backtest actual account performance; identified the missing transaction/cash-flow ledger and queued SPY/QQQ comparison. |
| 17 | Which holdings contributed most to my gains and losses? | PASS | Rendered a readable unrealized P/L table. Top stored gains included PANW, AVGO, MSFT, AAPL, and GOOGL; losses included NKE, SPHY, CRM, META, and BND. |
| 18 | Am I taking more risk than necessary for my expected return? | PASS / DATA-LIMITED | Explained that an expected-return/efficient-frontier claim is unsupported, then showed saved tolerance, loss capacity, and largest risk concentrations. |
| 19 | How diversified is my portfolio across companies, sectors, and strategies? | PASS | Reported 25.4 effective holdings, largest weights, classified sectors, correlation clusters, dependencies, and classification gaps. |
| 20 | Are several of my holdings effectively the same bet? | PASS | Used the same portfolio-intelligence evidence to expose correlation and economic-dependency overlap. |
| 21 | What percentage of my portfolio could I lose in a major market decline? | PASS | Returned the compatible modeled loss distribution and disclosed adverse drawdown estimate of -40.3%, with non-guarantee caveats. |
| 22 | Which positions are too large relative to my risk tolerance? | PASS | Compared current positions with the approved 20% per-position policy maximum; none exceeded it and ETF look-through was flagged. |
| 23 | How much cash should I keep available? | PASS | Returned the saved $10,000 minimum, 10% target allocation, and saved withdrawal/income context. |
| 24 | What would happen if technology stocks fell 20%? | PASS | Mapped 26.3% classified technology exposure to an approximately -5.3% first-order portfolio effect and explained excluded spillovers/look-through. |
| 25 | Are my investment decisions outperforming a simple index fund after taxes and fees? | PASS / DATA-LIMITED | Named the exact missing dated cash flows, tax lots, fees, and benchmark method; did not fabricate after-tax alpha. |
| 26 | Which holdings still have a strong investment thesis? | PASS / DATA-LIMITED | Disclosed that no personal theses are saved and provided objective research prioritization instead. |
| 27 | What evidence would invalidate the thesis for each position? | PASS / DATA-LIMITED | Separated objective risks from missing personal breakers and identified what must be saved. |
| 28 | Which positions should I buy, hold, reduce, or exit? | PASS | Rendered a readable evidence-score/review-category/reason table and clearly labeled it a research queue rather than automatic trade instructions. |
| 29 | Is this a good time to add to a losing position, or would that be averaging down without justification? | PASS / CLARIFICATION | Requested the ticker and proposed size and listed the thesis, breaker, valuation, evidence-change, and policy tests required. |
| 30 | What price would make a stock attractive, fairly valued, or overvalued? | PASS AFTER REPAIR | Requests a ticker and the required valuation assumptions. The first run exposed and led to repair of the malformed clarification-render path. |
| 31 | What upcoming earnings, economic releases, or company events could affect my positions? | PASS | Returned the stored dated event calendar and clearly distinguished current prediction-market coverage from missing categories. |
| 32 | How much am I paying in option premiums, spreads, commissions, and time decay? | PASS / DATA-LIMITED | Explicitly named missing contracts, fills, quotes, commissions, marks, IV, and Greeks; no invented cost. |
| 33 | Are my options positioned with enough time to expiration for the expected move? | PASS / DATA-LIMITED | Explicitly named the missing option terms, catalyst date, IV, and expected-move horizon. |
| 34 | What are my expected return, maximum loss, breakeven, and exit plan for each trade? | PASS / DATA-LIMITED | Explicitly named missing legs, quantities, fills, expirations, prices, costs, thesis, and exit rules. |
| 35 | Show my portfolio performance versus the S&P 500 and Nasdaq as a line chart. | PASS / VISUAL | Opened the analysis canvas and rendered portfolio, SPY, and QQQ series with return summaries, dates, volatility, provider, method, and the hypothetical-backtest caveat. |

## Visual evidence

The final browser rerun displayed:

- Portfolio total return: 23.1%
- SPY comparison: 20.5%
- QQQ comparison: 25.2%
- Annualized volatility: 11.9%
- Three chart series with a common one-year daily window
- Provider: Polygon + Tiingo
- Calculation version: `ai-workspace-calculations-v1.4.0`
- Clear disclosure: the chart is how today's holdings and weights behaved historically, not the account's realized return

## Automated verification

- Focused Ask/routing/synthesis/dashboard tests: 73 passed
- Frontend build and UI contract tests: 82 passed
- TypeScript typecheck: passed
- Full backend suite: 659 passed, 9 skipped

## Remaining data work (not application failures)

1. Import a complete dated transaction and cash-flow ledger to calculate actual time-weighted or money-weighted performance and contribution.
2. Import realized tax lots, account tax rates, dividends, commissions, and slippage assumptions for after-tax/after-fee comparisons.
3. Save personal thesis claims, supporting evidence, and explicit breakers for thesis-strength and invalidation monitoring.
4. Add a versioned intrinsic-value model before presenting dollar target-price bands.
5. Import an options/trade ledger with contracts, legs, fills, quotes, Greeks, catalysts, and exit rules.

These gaps should remain visible as limitations until their underlying data contracts exist.

## Post-gate fallback upgrade

After the initial gate, every previously data-limited path was upgraded so a limitation is never the entire answer. The response now combines available evidence with a concrete next action:

- Portfolio performance shows a one-year current-weight table versus SPY and QQQ, including total/annualized return, volatility, maximum drawdown, and growth of $1, before requesting the transaction ledger needed for actual performance.
- Risk efficiency shows the same-window return, volatility, drawdown, and historical return/volatility ratio for the portfolio, SPY, and QQQ, plus the largest modeled risk contributors. It then asks whether the user's objective is lower drawdown, lower volatility, or a minimum return.
- After-tax/after-fee index comparison shows the gross historical gap versus SPY and QQQ and explains that the positive gap is the approximate maximum unobserved drag before the lead disappears. It then requests the missing ledger or explicit approximation inputs.
- Missing personal theses now produce objective evidence-strength or weakness rankings and ask for one ticker plus the user's ownership reason so reviewable thesis/breaker drafts can be prepared.
- Missing score-change ticker now lists available portfolio tickers and explains exactly which component deltas will be shown after selection.
- Missing thesis breakers now show objective risks for the largest holdings and ask for the ownership claim needed to draft editable operating, valuation/capital-allocation, and portfolio-risk breakers.
- Averaging-down review now lists the actual positions with negative stored unrealized P/L and asks for one ticker plus the proposed add size.
- Target-price review now shows a relative valuation table before asking for a ticker and valuation method (`earnings multiple`, `free-cash-flow yield`, or `DCF`).
- Options cost, expiry, and trade-plan paths now show formulas and paste-ready schemas. Structured follow-up replies retain the prior analytical intent instead of becoming generic stock lookups.
- A browser-tested option-cost follow-up calculated a supplied ticket as $1,680 premium notional, $100 full quoted-spread notional, $1.30 supplied commission, and -$14/day theta. The answer correctly labeled the result as arithmetic from user-supplied inputs that was not saved or market-verified.
- The plain-language prompt `Where should my next $10,000 go?` now routes to the cash-allocation analysis and returns the stored cash hurdle, candidate comparison, concentration effect, and sizing limitation.

The app still names genuinely absent data, but it now answers with the best defensible evidence or calculation first and asks one focused follow-up that can advance the analysis.

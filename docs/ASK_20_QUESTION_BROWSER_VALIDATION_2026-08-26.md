# Ask EagleEyes: 20-question browser validation

**Date:** August 26, 2026  
**Scope:** Ask EagleEyes only; Research is intentionally deferred to the next pass.  
**Test identity:** Existing signed-in local browser session (`archisdhar@gmail.com`) using the configured Supabase portfolio.  
**Code under test:** Exact checked-out/deployed revision, `main` SHA `959ed5ae8183c124446ba511ce804ac21e340ed8`.

## Executive status

The deployment infrastructure is healthy, but Ask EagleEyes is **not ready for usefulness sign-off**.

- Vercel `/ask`: HTTP 200.
- Render `/ready`: HTTP 200 with `{"status":"ready","storage":"supabase"}`.
- All 20 browser submissions completed without a network-level `Failed to fetch` error.
- Only **1 of 20** answers was genuinely useful, and it was explicitly partial.
- **3 of 20** were defensible abstentions for data the product does not currently store, but their explanations were too generic to help the user.
- **16 of 20** were unusable because of routing, composition, or presentation failures.
- **0 tables** and **0 charts** rendered.
- The direct table-and-chart request opened an empty Analysis canvas and asked what the widget should show even though the prompt had already specified it.
- For the 19 timed submissions, median latency was **3.684 s**, mean latency was **4.277 s**, range was **2.666–7.753 s**, and **13/19** completed under five seconds.

This is therefore not primarily a timeout problem. It is a capability-routing and answer-composition problem.

## Method

Each prompt was submitted in a fresh chat so previous context could not rescue or contaminate the result. For every result, the browser test inspected:

- the visible answer text;
- Latest evidence, Saved thesis, and Portfolio context;
- answer latency;
- rendered table count;
- rendered chart/canvas count.

The user supplied 19 analytical questions. A twentieth prompt was added only to test the user's explicit requirement for readable tables and charts:

> Show how my portfolio performed versus the S&P 500 and Nasdaq in a readable table and chart.

## Results

| # | Prompt | Time | Result | Table/chart | Finding |
|---:|---|---:|---|---|---|
| 1 | How has my portfolio performed versus the S&P 500 and Nasdaq? | ~8–11 s | **Fail** | 0 / 0 | Parsed `S&P` as securities `S` and `P`, then produced a fabricated-looking `S vs P` comparison instead of benchmark performance. |
| 2 | Which holdings contributed most to my gains and losses? | 3.684 s | **Fail** | 0 / 0 | Returned only `portfolio risk returned SUCCESS`; no holdings or contribution values. |
| 3 | Am I taking more risk than necessary for my expected return? | 7.753 s | **Fail** | 0 / 0 | Generic unsupported-claim message; no risk/return evidence or explicit missing-input explanation. |
| 4 | How diversified is my portfolio across companies, sectors, and strategies? | 2.684 s | **Fail** | 0 / 0 | Claimed no supported capability even though portfolio concentration/intelligence capabilities exist. |
| 5 | Are several of my holdings effectively the same bet? | 3.682 s | **Fail** | 0 / 0 | Returned only `portfolio risk returned SUCCESS`; no overlap, correlation, or dependency analysis. |
| 6 | What percentage of my portfolio could I lose in a major market decline? | 6.739 s | **Fail** | 0 / 0 | Generic unsupported-claim message; no scenario or drawdown framing. |
| 7 | Which positions are too large relative to my risk tolerance? | 3.689 s | **Fail** | 0 / 0 | Returned only `portfolio risk returned SUCCESS`; did not explain that a saved risk tolerance is required. |
| 8 | How much cash should I keep available? | 5.711 s | **Fail** | 0 / 0 | Generic unsupported-claim message; no cash-hurdle or liquidity framework. |
| 9 | What would happen if technology stocks fell 20%? | 2.675 s | **Fail** | 0 / 0 | Claimed no supported capability instead of running a sector shock/scenario analysis. |
| 10 | Are my investment decisions outperforming a simple index fund after taxes and fees? | 2.686 s | **Poor abstention** | 0 / 0 | Correct not to invent tax and fee data, but failed to identify the required ledger, tax lots, fees, benchmark, and time period or provide a supported pre-tax partial result. |
| 11 | Which holdings still have a strong investment thesis? | 3.679 s | **Fail** | 0 / 0 | Returned only `portfolio risk returned SUCCESS`; did not distinguish absent saved theses from objective company evidence. |
| 12 | What evidence would invalidate the thesis for each position? | 2.682 s | **Useful partial** | 0 / 0 | Correctly said no saved personal theses/breakers exist, then listed objective risks for the largest holdings. This was the only answer that directly helped the user. |
| 13 | Which positions should I buy, hold, reduce, or exit? | 6.729 s | **Fail** | 0 / 0 | Generic unsupported-claim message. A safe answer could still categorize positions for review without issuing trades. |
| 14 | Is this a good time to add to a losing position, or would that be averaging down without justification? | 2.683 s | **Fail** | 0 / 0 | Claimed no supported capability and did not ask which position or state the evidence needed to decide. |
| 15 | What price would make a stock attractive, fairly valued, or overvalued? | 3.692 s | **Fail** | 0 / 0 | Ran portfolio `valuation_ranking`, reported it failed, and did not ask for a ticker. |
| 16 | What upcoming earnings, economic releases, or company events could affect my positions? | 6.723 s | **Fail** | 0 / 0 | Generic unsupported-claim message. This is a wording-sensitive regression: a near-equivalent earlier prompt returned stored company-market events. |
| 17 | How much am I paying in option premiums, spreads, commissions, and time decay? | 6.734 s | **Poor abstention** | 0 / 0 | The product lacks the necessary options/trade ledger and Greeks, but the answer did not say that. |
| 18 | Are my options positioned with enough time to expiration for the expected move? | 3.700 s | **Fail** | 0 / 0 | Incorrectly routed to portfolio risk and returned only its SUCCESS status. |
| 19 | What are my expected return, maximum loss, breakeven, and exit plan for each trade? | 2.666 s | **Poor abstention** | 0 / 0 | The product lacks complete trade/option strategy terms, but the answer did not identify them or ask for them. |
| 20 | Show how my portfolio performed versus the S&P 500 and Nasdaq in a readable table and chart. | 2.673 s | **Fail** | 0 / 0 | Opened Analysis canvas, then asked `What should the new widget show?`; the requested performance comparison was already explicit. |

## Representative visible outputs

### Severe benchmark-routing error

Question 1 was rendered as:

> **S vs P — stored evidence comparison**
>
> On the currently stored evidence, P ranks ahead overall ...

The phrase `S&P 500` was treated as two ticker symbols. The visible answer was fluent enough to look credible, which makes this more serious than a clean abstention.

### Internal status leaked as the answer

Questions 2, 5, 7, 11, and 18 produced this pattern:

> **Answer**  
> portfolio risk returned SUCCESS.
>
> **Key evidence**  
> 1. `[MODEL_OUTPUT] portfolio risk returned SUCCESS.`

A successful canonical calculation is not itself a user answer. The renderer needs to extract and synthesize the relevant holdings, values, caveats, and next step.

### Generic unsupported-capability response

Questions 4, 9, 10, 14, and 19 produced this pattern:

> I can analyze this question only through EagleEyes' registered capabilities, but I don't yet have a supported capability for the requested analytical requirement. No unrestricted AI financial reasoning was used.

This is safe but not sufficiently specific. For unsupported domains, the response should name the exact missing data and ask for the smallest required clarification. For supported adjacent domains, it should return the supported portion and label the rest unavailable.

### The one useful partial answer

Question 12 correctly separated personal thesis evidence from objective risk evidence:

> No saved theses or personal breakers exist, so I cannot claim what would invalidate your thesis. These are objective, non-personalized risks for the largest positions.

It then surfaced concrete stored evidence, including modeled risk contribution and weak valuation scores for several large holdings. This is the pattern the other answers should follow: direct limitation, useful supported evidence, and no fabricated personalization.

### Visualization failure

Question 20 explicitly requested both a table and a chart. The response was:

> What should the new widget show?

The canvas displayed only `Start your analysis`; no widget was created.

## Confirmed and likely causes

These findings combine browser evidence with a read-only inspection of the deployed source.

1. **Naive uppercase-token extraction misreads benchmark names.** `backend/main.py` and `backend/ask_orchestration.py` extract short uppercase tokens with a broad regular expression. Without a benchmark alias guard, `S&P` becomes `S` and `P`.
2. **Canonical execution status is being used as narration.** The answer pipeline can fall through to a composed capability result such as `portfolio risk returned SUCCESS` instead of a domain renderer that turns the result payload into claims.
3. **Intent matching is brittle and phrase-dependent.** Semantically equivalent event/catalyst questions take different routes. This explains why an earlier event question worked while question 16 did not.
4. **Requirement resolution is too coarse.** Several questions that can be answered partially from portfolio intelligence, correlation, scenario, valuation, or cash evidence are labeled wholly unsupported.
5. **The visualization classifier loses the requested metric.** In `backend/dashboard_chat.py`, `table` is selected as the visualization before the question is mapped to a known widget kind; the combined performance/table/chart wording can then reach the generic `What should the new widget show?` branch.
6. **Options and after-tax trade attribution are real coverage gaps.** Supabase is storage, not a substitute for absent broker fills, tax lots, commissions, option contracts, Greeks, and strategy plans. These questions should abstain clearly until those datasets are integrated.

## Comparison with the previous 15-question pass

The previous report recorded 8 fully useful answers, 6 partially useful answers, and 1 correct clarification. This new set is materially worse: 1 useful partial, 3 generic but defensible abstentions, and 16 unusable answers.

The regression is not that the API stopped responding. The regression is that broader natural-language formulations are not reaching the same useful capabilities and renderers exercised by the earlier curated questions.

## Recommended repair order

1. Add benchmark aliases and ticker-extraction guards for `S&P 500`, `Nasdaq`, `Nasdaq 100`, `Dow`, and `Russell 2000`; add this exact question as a regression test.
2. Prevent status-only canonical results from being answerable output. Require a user-facing renderer or return a specific partial/unavailable response.
3. Add semantic intent coverage and exact regression tests for all 20 prompts, especially diversification, same-bet overlap, sector shock, cash, thesis strength, and upcoming events.
4. Make partial composition the default: answer the supported part, name unsupported fields, and never collapse the whole question into a generic rejection.
5. Repair visualization parsing so metric, benchmarks, requested table, and requested chart are preserved together; verify that a populated widget appears.
6. Add domain-specific missing-data responses for options, taxes, fees, and trade plans before attempting those calculations.
7. Re-run these 20 questions plus the earlier 15 as a single 35-question browser gate before Research work begins.

## Release judgment

Infrastructure status is green. Ask usefulness status is red.

The current build can be used for continued owner testing, but it should not be represented as a broadly capable synthetic portfolio assistant yet. The next work should be the Ask repair pass above, followed by the combined 35-question browser validation. Research UI work should come after that gate passes, unless the owner explicitly chooses to reprioritize it.

## Production-session limitation

The production URL was checked and healthy, but the available production browser tab was signed out and displayed the Supabase sign-in form. No credentials were guessed or extracted. The authenticated functional test therefore ran locally against the exact deployed code and the existing signed-in Supabase-backed test session. A final authenticated production smoke test remains pending after the owner signs into the production tab.

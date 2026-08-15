# Private personal beta

The current beta is intended for one invited owner using Supabase authentication.
It is a research sandbox: brokerage connection, trade execution, and public
registration are disabled.

## Verified locally

- Supabase accepts transactional writes.
- FRED, Tiingo, Polygon, SEC, Kalshi, Polymarket, and Gemini respond with the
  configured development credentials.
- Today selects one canonical adjusted bar per market session and prefers the
  newest validated session.
- The U.S. security catalog contains stocks, ADR classification, and a searchable
  ETF catalog. ETF constituent coverage remains issuer-dependent and carries a
  dated availability/freshness label.
- The full unit, build, type-check, and 11-workflow browser suites pass.

## Beta boundaries

- Keep signup invitation-only and do not enable trade execution.
- Fund holdings are complete only where an issuer or entitled provider returns
  a validated dated file. An unavailable issuer feed is displayed as unavailable,
  never inferred from a stale index list.
- A separate live second-user RLS smoke test requires a second safe test account;
  deterministic cross-user browser isolation is covered by the local suite.
- Run retention in preview mode until a current database backup is confirmed.
- The repository owner reviews, commits, and pushes changes from their own GitHub
  account.

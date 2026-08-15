# EagleEyes data retention

EagleEyes keeps immutable research runs, user portfolios, ALFRED point-in-time
vintages, and the canonical adjusted-price history. Retention targets only data
that can be reproduced or has already been archived.

## Default policy

- Keep Tiingo corporate-action-adjusted daily bars as the canonical long-term
  history.
- Archive older Polygon daily bars only when a Tiingo bar exists for the same
  security and session.
- Keep ALFRED/FRED vintages because point-in-time validation depends on them.
- Keep immutable dashboard runs, analysis runs, portfolios, plans, and user
  layouts.
- Remove expired widget-cache entries.
- Remove briefing snapshots older than 180 days; saved immutable research runs
  remain untouched.

## Safe operation

Preview the policy first:

```bash
.venv/bin/python -m backend.retention
```

The report includes the current database size and the number of rows eligible
for archival. No rows are changed in preview mode.

Before execution, take a Supabase backup or confirm that a current Pro backup is
available. Then run:

```bash
.venv/bin/python -m backend.retention --execute
```

The command writes eligible overlapping price rows to a Zstandard-compressed
Parquet archive under `data/archives/`, writes a SHA-256 manifest, verifies the
archive, and only then deletes those archived duplicates. Archive files are
local operational artifacts and are excluded from Git.

The August 11, 2026 preview found 18,930 overlapping provider rows and 208
expired widget-cache entries. That cleanup has intentionally not been executed.

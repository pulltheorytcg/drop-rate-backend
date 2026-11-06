# Protected daily Supabase→D1 operational shadow snapshot (NOT a live data switch)

**6 November 2026 — scheduled workflow proposal.** Scope: the already verified private operational 9-table D1 shadow; no new application tables, owner permissions, Auth credentials, pricing, media bytes, settlement transfers or production routing.

## Why / connections

The protected run [42283108326](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/42283108326) verified 1,184 original operational records once. An active store continues receiving new inventory, ownership, sales and refunds, so a frozen snapshot is insufficient for a future Cloudflare cutover.

The existing `.github/workflows/d1-operational-real-source-stage.yml` now also supports a controlled daily UTC 03:37 snapshot and a main-only manual run. Each run reads **one repeatable-read, read-only** PostgreSQL snapshot through its existing protected `production` credential, computes a deterministic SHA-256 generation, verifies source row-count identity and financial lineage, then `INSERT OR IGNORE`-stages the frozen generation in **private** `drop-rate-d1-operational-shadow-20261106`. It reads D1 back and verifies all nine original-table identity/hash receipts and per-owner/currency ledger sums exactly to the penny.

This does not implement an ongoing change-stream or atomic live dual-write: every successful generation is only a point-in-time checkpoint, and the next run might occur after source writes. Replays, true zero-gap tail/cutover and rollback are separate, unapproved gates.

## Security and release guards

- The live D1 stage is gated by `github.ref == 'refs/heads/main'` AND `push`, `schedule` or explicit `workflow_dispatch`. Pull requests run synthetic tests **only**. `environment: production` and no credentials on non-main branches.
- `concurrency` permits only one private operational writer, never cancels it mid-generation.
- Current per-run source/max D1 limits in `tools/d1_operational_source_stage.py`: **2,500** total writes, strict independent source-count floors and D1 exact schema check. A larger inventory or schema drift fails, never expands the daily write budget automatically.
- No `auth.users` secrets/session IDs or payment credentials are copied. Non-live mapping contains legacy UUIDs but no token or password.
- Repeating an unchanged source generation is idempotent. A changed source produces a **new immutable** D1 generation without updating the storefront/Shopify source pointer.
- Evidence receipts include counts/hashes only. No private row JSON in logs, GitHub artifacts or status descriptions.
- No D1 read switch, Supabase retirement, Stripe transfer or seller permission escalation can be triggered by this job.

## Tests, failure conditions and next gates

Synthetic regression covers duplicate entries, wrong-owner order allocation, ledger immutability and original-row hash parity; schedule contract tests cover main-only/protected secrets and no-cutover assertion. The protected live job also checks exact snapshot counts and ledger sums. Investigate missing/mutated source rows, unexpected D1 source schema, 2,500 write budget exceedance, owner ledger mismatch and protected credential errors as **Action Required**, never waive them.

Do not equate daily snapshots with a completed full migration. Before a live store switch, replace identity authentication, migrate the remaining PostgreSQL 148-relation/trigger/policy scope into deterministic FastAPI + D1, verify real media rights and bytes, ensure complete price history, implement verified transactional/CDC delta replay, rehearse rollback and perform final owner-consignor financial signoff.

# R2 physical offload — Stage 1: lossless reference-source backup

## Why this is not a deletion release

On 2 November 2026 the production Supabase Free PostgreSQL database measured
**392,613,011 bytes**, just **7,386,989 bytes** below Drop Rate's existing
400,000,000-byte bulk-import pause. This pause and the official 500 MB Free
quota are different limits. Neither is changed by this stage.

The R2 live catalogue and market publications are healthy and current, but
they are **projections**, not restorable copies of complete source tables.
For example, the published `reference_cards` identity/display projection omits
`finish`, `evidence` and `refreshed_at`. Source importers, exact matching and
price/rights validation still depend on Postgres. As of this audit:

| PostgreSQL relation | Total bytes | Stage 1 handling |
| --- | ---: | --- |
| `tcg.reference_cards` | 73,981,952 | Lossless R2 backup pilot; **retain SQL** |
| `tcg.reference_market_prices` | 43,917,312 | Current-price source; retain |
| `tcg.reference_catalogue_prices` | 39,829,504 | Current-price source; retain |
| `tcg.reference_image_mirrors` | 30,474,240 | Exact media/rights receipts; retain |
| `tcg.audit_events` | 103,235,584 | Immutable security/finance audit; retain |

These are storage footprints including indexes, **not** guaranteed reclaimed
amounts. Reference-card source SQL is used in 31 backend modules, the two
current-price tables in 20 and 19 respectively. Physical offload therefore
requires independent live-query and importer cutover work, not a `TRUNCATE`.

## New safe building block

`backend/app/reference_source_backup.py` exports a full, ordered PostgreSQL
`row_to_json` snapshot of **all 14 source columns** in `tcg.reference_cards`.
It checks the table's complete column list, bounds rows/bytes/line lengths,
rejects duplicate/out-of-order identities, and hashes the content and gzip.

The **manual** command `PYTHONPATH=backend python
backend/scripts/backup_reference_card_source.py` performs a local export and
typed PostgreSQL temporary-table restore **without any source mutation**.
Only an explicitly opted-in `--apply` with
`TCG_REFERENCE_SOURCE_R2_BACKUP_ENABLED=true`, configured private R2 and the
existing maintenance admin uploads an immutable archive. It downloads the
actual private R2 object, checks SHA-256/size, type-restores **every row** in
rolled-back PostgreSQL temp transactions, uploads a manifest, and verifies
that manifest's readback. It never exposes an R2 URL to the frontend and
never deletes reference records.

CI runs this exact code in disposable PostgreSQL 17.6 with 403 synthetic
source rows, a non-admin rejection, corrupt-object rejection, schema-drift
rejection, source-table digest parity and zero reclaim. The release is not
ready until this new CI and ordinary backend CI pass.

## Remaining offload gates (separate, explicitly reviewed stages)

1. Verify a real production source backup against the private R2 account and
   its manifest; record storage/readback/typed-restore receipts **without**
   exposing credentials or copying private user records.
2. Inventory all SQL readers, update jobs, triggers, foreign keys and
   Supabase migrations for each proposed source table. Maintain exact
   per-owner media, pricing-expiry and printing-identity behavior.
3. Add R2-first *write* and indexed *read* paths with immutable-generation,
   permissions and fallback tests for the selected source, not just R2 display
   snapshots. Prove full query parity and source-change invalidation in native
   PostgreSQL and against production read-only comparisons.
4. Explicitly approve any physical reclamation separately. Require a fresh
   full-source digest/row-count match under an exclusive database lock,
   demonstrated restoration, no active SQL dependencies, a reversible cutover
   and measured post-change database bytes. Source changes invalidate approval.

No financial, physical inventory, owner, order, historical audit, verified
market observation or media-rights record is a deletion candidate here. This
stage incurs no paid Supabase upgrade, does not raise the bulk-import guard,
does not change scheduled jobs or active application flags, and archives no
production bytes until separately enabled and run.

# Existing Lorcana shadow refresh — 8 November 2026

The protected live recheck of the 3,505-row Lorcana shadow failed because the current verified R2 manifest differs from the staged D1 generation. Historical parity cannot authorise current catalogue reads.

Extend the existing `d1_r2_real_shadow.py` importer and existing private D1 database. Validate the prior complete projection and its rollback hash, compare current source metadata and preserve all original stable identities. Removed identities or decreased counts require review. No duplicate database or replacement migration pipeline.

A refresh appends a new generation from the existing checksum-verified R2 export. Original rows remain unchanged. A daily persistent reservation permits one bounded refresh (maximum existing 8,000-row source bound). Partial uploads are read back exactly, validated and resumed; each statement retains the 100-bind cap. All rows are rehashed before a compare-and-swap advances the shadow pointer, followed by full second readback. Old generations remain available for rollback. Per-field change counts expose no reference names or original values.

A quota-deferred result publishes a pending parity status, never a success claim. A valid current generation is reverified read-only and does not consume another refresh allowance. This changes only isolated catalogue shadow data; no FastAPI serving route or physical inventory, prices, rights, Shopify or authentication changes.

Tests use synthetic SQLite/API doubles to prove exact source hashes, retained previous generation, no new database, interrupted-request resume, daily deferral, stable-ID removal rejection, wrong-source/credential checks and existing Yu-Gi-Oh quota behaviour. Production parity must be established by the protected workflow. Local Python 3.9 passes 28 importer/YGO tests; the existing shared-codec suite requires Python 3.12 (`zip(strict=True)`) and is covered by CI.

Rollback: retain/repoint the prior verified shadow generation under review or stop the staging job. Production reads are unchanged. The failed recheck did not mutate any D1 records.

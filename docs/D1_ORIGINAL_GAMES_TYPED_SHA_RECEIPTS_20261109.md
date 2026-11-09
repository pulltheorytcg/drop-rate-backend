# Original four TCGs — immutable verified per-relation R2 SHA release receipts

9 November 2026 · Release board [#1010](https://github.com/pulltheorytcg/drop-rate-backend/issues/1010)

## Build / why
The 69,867 live Pokémon, One Piece, Dragon Ball and Naruto cards are in the published immutable R2 legacy catalogue, **not yet proven in D1**. The D1 legacy writer is intentionally frozen on old generation 122500 / 79,186 rows / obsolete five-relation SHA256 constants. The current live Supabase R2 publication is generation **122674**, five relations totalling **79,357** original typed rows and manifest SHA256 `977c9d114cf1aa96225e14bf5f76144cfd60ad2d85dffd82987e1197fdd4ef35`. We must not invent new per-relation SHA values from counts.

The protected, read-only legacy source-preflight already verifies **all 161 immutable R2 parts** and every original identity/typed row; its artifact holds five computed per-relation source SHA256 hashes. This PR publishes each of those existing hashes as an immutable-commit-scoped GitHub status, **only after full source verification succeeds**. No new source read route, R2 object, D1 schema, import, or production traffic change.

## Connections
GitHub protected `main` OIDC → signed Railway R2 source-only export → read-only admin-RLS publication pin → full R2 bytes + per-part SHA and identity duplicate checking → nine original-game/language partition counts → five per-relation source hashes → separate `drop-rate-r2-original-<relation>-sha256` GitHub commit statuses and original aggregate parity status.

Each receipt's `description` contains the lowercase 64-character SHA-256 of the complete relation's canonical source rows, in the exact source order and JSON canonicalisation used in `tools/d1_legacy_r2_shadow.py`. The five fixed contexts cover `reference_cards`, `reference_sets`, `reference_sealed_products`, `catalogue_products` and `catalogue_product_profiles`. The status writes are GitHub **metadata only**, not Cloudflare writes.

## Failure points
Any malformed digest, different source generation/count/manifest, missing part, duplicate identity, different game/language split, incomplete source report, missing GitHub status permission, or status API error blocks the successful full-source audit. No SHA receipt is published from PR/fork jobs, fabricated fixtures, failed R2 source verification or a different unreviewed generation.

## Tests / safety
Existing R2 preflight and exporter synthetic tests and full backend CI remain mandatory. New offline assertion checks that per-relation publication is gated on the full R2 proof and no D1 credentials can reach the source-preflight job. Verify actual main commit statuses: all five SHA receipts must be present, successful, and bound to the exact same reviewed source proof as the aggregate. Only then open a **separate reviewed import repin** PR with the matching SHAs; maintain exact GitHub run+commit approvals, rollback, D1 capacity limits and Supabase as production authority until full migrated parity. Do not infer an imported row from a source checksum.

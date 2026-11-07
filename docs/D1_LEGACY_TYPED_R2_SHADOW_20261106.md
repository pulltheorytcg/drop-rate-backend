# Drop Rate complete legacy catalogue — type-preserving Cloudflare R2 to D1 shadow

**6 November 2026. Implementation stage, not completed production cutover.**

## What is being built and why

Import the original owner-free R2 *legacy* catalogue into an isolated, indexed Cloudflare D1 shadow. Unlike the R2-first game sources, its original five relations are **not all cards**:

| Original R2 relation | Source records | Identity preserved |
|---|---:|---|
| `reference_cards` | 69,697 | provider, system, language and printing `provider_id` |
| `reference_sets` | 1,472 | provider, system, language and set ID |
| `reference_sealed_products` | 3,893 | provider, system, language and sealed product ID |
| `catalogue_products` | 2,062 | original catalogue product UUID (including comics/manga) |
| `catalogue_product_profiles` | 2,062 | linked original catalogue UUID |
| **Total typed relation rows** | **79,186** | no false claim of 79,186 unique cards |

Source was independently verified in [PR #934](https://github.com/pulltheorytcg/drop-rate-backend/pull/934): active generation **122500**, complete **161 R2 parts**, **29,831,680 raw bytes**, SHA256 manifest `2dc9e6bd30d3508388d41513cfeb7a9b6d003dd6223a3f6a2d08c28b5aad7403` and individually verified checksums for all five original relations.

### Connections

- **R2** remains the original immutable catalogue data, artwork and historical source storage. No R2 writes.
- **Railway/FastAPI** provides only the fixed `/api/v1/internal/d1-shadow/legacy-d1/manifest` and `/part/{ordinal}` source endpoints, behind signed short-lived GitHub OIDC requiring the exact `d1-legacy-r2-shadow.yml` `main` workflow, `push`/`schedule` event and trusted repo IDs. Existing authorised maintenance actor, read-only PostgreSQL transaction and forced RLS remain enforced. No arbitrary object/key/source selector.
- **GitHub Actions** (trusted `main` only) can stage a source-verified generation in an isolated `drop-rate-d1-real-legacy-catalogue-shadow` via its separately scoped Cloudflare D1 token. Neither the token nor the private source data is sent to the browser.
- **D1** stores typed, original-source JSON payload alongside bounded indexed provenance fields and a SHA256 of the *complete original composite identity*. Its `legacy_generations`, `legacy_shadow_rows`, `legacy_daily_budget`, `legacy_active_generation`, `legacy_live_rows` do not include ownership or financial ledgers. Original R2 attributes are preserved rather than fabricating card numbers from comics/sets.

### Rollout and quota safety

1. Require all four previously staged *follow-on* R2-first partitions **sports, sports-heritage, figures and Magic (155,488 rows)** to be fully source-verified with active D1 pointers. Only then inspect real D1 disk headroom and reserve at least one unused D1 database slot for future operational services.
2. Wait until a later UTC date than the last follow-on D1 write receipt. Do **not** add 5,000 legacy rows to the same day's follow-on batch; the D1 Workers Free account row-write ceiling is shared across databases. Additional external account usage remains a potential blocker.
3. Re-download all immutable legacy R2 parts and reconstruct every source row, verifying original manifest, per-relation SHA256 and duplicate original identity keys. Any changed generation must be explicitly reviewed, not silently accepted.
4. Stage at most **5,000 new typed legacy relation rows per UTC day**. Insert an immutable daily receipt before the first item; a crash or duplicate run must not replay a same-day batch. Every retry re-reads all existing D1 rows and confirms every source field and identity matches.
5. Only after **all 79,186 original rows** match D1, calculate and compare the complete source projection SHA, check all five relation counts, atomically activate the **private D1 pointer**, then read and check everything again.
6. This does **not** change Shopify, production catalogue reads, existing Supabase authentication, physical inventory, individual founder/consignor ownership, commissions, sales or refunds. The original PostgreSQL live database remains authoritative for financial workflows until their separate deterministic transactional migration passes full tests.

**Source limitations:** No market observations, confirmed sold prices, RRP or Market Values are introduced by this import. A valid reference or product identity alone is not sufficient pricing evidence, and a source row is not a unique physical inventory item.

### Failure points

- Wrong original printing/language/set/provider, duplicated composite identity or source generation drift.
- Missing, altered or oversized part; mismatched original relation checksum or incomplete R2 assembly.
- Unsupported D1 database metadata, exhausted quota, insufficient Free-plan database slots or insufficient disk safety margin.
- Out-of-order importer execution competing with Yu-Gi-Oh! or follow-on rows on the same day.
- Incomplete D1 rows, changed staged source JSON, duplicate batch execution, partial snapshot activation.
- Invalid GitHub OIDC event/workflow identity or a maintenance actor without verified admin access.

All failures must fail closed, keep the last legitimate catalogue usable, and generate a traceable report without credentials.

### Tests and proof

- Offline tests for all **five distinct original relations**, including comics/manga and sealed, exact original source data/sha checks, staged row tamper, source-count/generation drift and duplicate same-day receipt. Verify first batch remains invisible, final batch becomes privately active, complete source per-relation counts are identical.
- Security tests for signed exact legacy D1 workflow identity, no cross-use of legacy source-only audit, Yu-Gi-Oh!, Magic and follow-on export routes, and forced PostgreSQL RLS.
- Protected main-branch workflow `d1-legacy-r2-shadow.yml` scheduled **06:13 UTC**. Report `drop-rate-d1-real-legacy-five-relation-parity` stays **pending** while waiting/partially staged, and becomes **success** only for all 79,186 verified D1 rows. No fabricated completion percentage.
- Cloudflare D1 Free limits: <https://developers.cloudflare.com/d1/platform/limits/> and <https://developers.cloudflare.com/d1/platform/pricing/>. Check live capacities with `d1-full-catalogue-capacity.yml`, which uses Cloudflare's supported read-only database `file_size` metadata.

## Remaining end-to-end cutover work

After each immutable source has full D1 parity: verify all catalogue search/index/query semantics for Pokémon, One Piece, Dragon Ball, Naruto, Yu-Gi-Oh!, Lorcana, Magic, Sports, figures, comics/manga, sealed products and related sets; compare search results and p50/p95 timing, control feature-flagged read shadow, demonstrate real rollback. Only **then** change live catalogue routing. Independent later stages replace Supabase Auth, ownership, multi-owner Shopify allocation, refunds, settlements, audit and price-history dependencies.

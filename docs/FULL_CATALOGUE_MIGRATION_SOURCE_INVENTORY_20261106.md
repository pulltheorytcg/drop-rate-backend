# Drop Rate full catalogue migration — measured source inventory and gates

**6 November 2026. Target: Cloudflare R2 immutable catalogue + Cloudflare D1 indexed reference read models. This is a catalogue migration, NOT a founder/consignor inventory or financial-ledger cutover.**

## Sources measured directly

### R2-first individual source publications (current, signed source IDs)

| Source partition | Rows | Original manifest SHA256 | Status |
|---|---:|---|---|
| mtgjson / MAGIC_THE_GATHERING / English | 153,662 | `be5af5e84d3a10bcac32a996f0dc8779fdf33c95fac89669381a8bbd32fcad28` | All 308 parts/source SHA verified; D1 staging not started |
| ygoprodeck / YUGIOH / English | 45,418 | `e85fb49e5cf81427cec68b24749de5e273845f1b2245536e4879ded0e4b0a9dd` | First 8,000 verified in isolated D1 on 6 Nov; rest scheduled at 03:17 UTC, up to 8k newly inserted/day |
| lorcast / DISNEY_LORCANA / English | 3,505 | `f0d3c6e6ca73fb559f39a9bfea98de0893b8d2b7026608b90870053d3d50d67c` | Exact full D1 SHA256 parity verified in isolated D1 |
| cardcollectorcapital / SPORTS_CARDS / English | 1,722 | `025043fb2594a98f18c070ecbdcdfa682b25a3447839ebca1cdfb84d33bdae1f` | R2 source published, D1 not verified |
| cardcollectorcapital_heritage / SPORTS_CARDS / English | 100 | `94f4c7af3097b439dafc2826d613e78fe2e6569f757ee11078bdda8123484146` | R2 source published, D1 not verified |
| reviewed_figures / FIGURES / Not applicable | 4 | `8bafa9e80735482c62dbb201ad26c21fa6c157c941d4e5c6edfc81a09f092d72` | R2 source published, D1 not verified |

**Six R2-first published partitions: 204,411 reference rows.** Each source key includes provider/system/language/printing; the count is **not** a verified market-price or unique-artwork coverage number.

### Existing owner-free legacy R2 catalogue

Existing active `tcg_private.live_catalogue_r2_publication`:
- generation = published_generation = **122500**
- schema `drop-rate-live-catalogue-v2`, **161 R2 parts**, **29,831,680 bytes**
- `reference_cards` **69,697** (Pokémon English/Japanese, One Piece English/Japanese, Dragon Ball Masters/Fusion English/Japanese and Naruto Bandai/Kayou)
- `reference_sets` **1,472**
- `reference_sealed_products` **3,893**
- `catalogue_products` **2,062** (including comics, manga, catalogue-level collectibles)
- `catalogue_product_profiles` **2,062** (linked product metadata)
- **79,186 total relation rows**; this includes different tables and should never be advertised as 79,186 unique cards.

Legacy `reference_cards` 69,697 and R2-first 204,411 total **274,108 source card/reference entries** across both families; this is a source-row planning total, **not a deduplicated canonical identity count**. The sealed/sets/products/profiles add **9,489 rows** across related relation types. Any duplicate or stale source keys must be reconciled separately before publicly displaying a “unique cards” metric. `catalogue_products` and profiles are two relations for 2,062 entries, not 4,124 independently sellable items.

### What is *not* covered by these source counts

A full *storefront* migration also needs separate audited cutovers for any catalogues not included in these snapshots (LEGO, independent book/comic ingestion or external new releases). A source presence/count is not proof of complete world-wide catalogue coverage. Card artwork, image rights, exact print/finish/grade and accepted market evidence need independent audits.

**Do not infer owner inventory from any source catalogue.** Founders, consignors, physical copies, purchase costs, balances, Shopify products and transactions remain separate in the live PostgreSQL database.

## Verified release gates

1. **Source proof:** validate every immutable R2 part and digest, source/publication counts, all five legacy relations and stable IDs. GitHub status `drop-rate-legacy-r2-source-parity`. The new legacy export is read-only, signed GitHub OIDC for exact workflow, verified maintenance admin RLS and fixed generation 122500. No dynamic R2 object paths.
2. **Capacity:** Cloudflare Workers Free D1: max **500 MB per D1 database**, **10 databases per account**, **100k row writes/day shared over account**, **5m row reads/day shared**. Each index adds row writes; a successful 8k *input row* receipt is not a guarantee of global quota headroom. Check actual row metrics and account-wide database list before new writes. Ref: https://developers.cloudflare.com/d1/platform/limits/ and https://developers.cloudflare.com/d1/platform/pricing/.
3. **D1 staging:** stage ONLY immutable approved source generations; daily bounded writes; prior-stage exact-key comparison on resume; source change or bad card ID aborts; fully verify every row and content projection SHA before an atomic private active pointer. **Account-wide daily scheduling** must prevent simultaneous YGO + Magic + legacy index imports from exhausting the free quota.
4. **Read cutover:** check exact-ID, set-page and text-prefix results, per-collection category counts (comic, manga, sealed, figures, sports) and p50/p95 from Railway; shadow actual traffic first. Require active D1 data for all segments and a tested fallback/rollback. Do not change storefront until complete parity.
5. **Pricing:** use only eligible `Market Value` based on permitted data, precise product identity and type-specific evidence. Never replace missing values with RRP, guide-only estimate or unverified eBay asking prices. Price-history R2 retention must remain append-only.
6. **Operational retirement:** Supabase/PostgreSQL remains authoritative for ownership, sign-in, orders/refunds/commissions, audit and settlements until the *separate* transaction + authentication migration reaches financial parity, concurrent webhook testing and rollback readiness. No deletion or billing upgrade is implied by this catalogue work.

## Status at creation

Legacy R2 source export and preflight code are prepared for CI. **No legacy D1 write**, Magic D1 write or full catalogue read cutover has happened. Yu-Gi-Oh! 8,000 staging is independently verified; more scheduled batches are *not* counted until proof artifacts confirm them.

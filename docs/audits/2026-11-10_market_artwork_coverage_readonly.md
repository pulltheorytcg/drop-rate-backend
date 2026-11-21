# Drop Rate — Market Value and Artwork Coverage Audit (READ-ONLY)

**Audited:** 10 November 2026 (UTC). **Source:** production Supabase project `ozrxenrdladkooixutmm`, project `pull-theory-dev`, connected Railway historical runtime logs, and main-branch application code. **Evidence status:** database metadata verified; R2 object reality NOT verified. **No writes:** no Supabase, R2, Railway, Shopify, n8n or D1 writes. D1 remains paused.

## Files attached

- [Full reference-by-set breakdown](./2026-11-10_reference_set_coverage.csv): 674 system/language/set groups, including 2,480 separately classified *digital* Pokémon TCG Pocket entries; 67,387 physical card references.
- [Tier 1 physical inventory by set](./2026-11-10_tier1_physical_set_coverage.csv): 68 set groups, 505 approved or Shopify-published CARD/SEALED physical inventory items.
- [20 unpriced Tier 1 examples](./2026-11-10_tier1_missing_price_20_samples.csv): read-only triage samples, **NOT** an upsert/backfill dry run.

## Definitions

1. **Tier 1:** physical CARD or SEALED inventory items with `inventory_items.status='APPROVED'` OR a `shopify_inventory_links.sync_state='PUBLISHED'` relation. 506 published inventory links include **504 CARD/SEALED items + 2 COLLECTION items**; 507 APPROVED inventory rows include **505 CARD/SEALED items + 2 COLLECTION items**. Tier 1 cards/sealed union is **505**, including one approved sealed item not yet linked to published Shopify. Collections are excluded from CARD/SEALED tier and should be handled separately. Overall physical inventory has 621 records, including drafts, inspection, withdrawn and comics.
2. **Current stored inventory value:** positive `inventory_items.market_value_minor` and `pricing_updated_at >= now()-interval '14 days'`. This is a **screening indicator only**, NOT proof that the provenance, condition, grade, language, finish or sold-comparable standard is met.
3. **Qualifying shared-reference quote (provisional):** in `reference_market_prices.quotes`, `physical_valuation_eligible=true`, `reference_language` matches reference language, positive `price_gbp_minor`, observation within 14 days. This counts **at least one** eligible finish and **does not yet certify every existing finish/variant or physical condition/grade**. `reference_catalogue_prices` `MIXED_LANGUAGE_REFERENCE`, model-derived values, asking guides and USD-only context are not used as strictly qualifying.
4. **Image metadata present:** source URL + `reference_image_mirrors` status VERIFIED, positive `size_bytes`, nonempty `object_key`. This **does not establish actual R2 HEAD/GET presence**, decoded pixel resolution, placeholder screening, language/finish visual match, or slab-specific media match. Strict image coverage is **not measured** pending object-level R2 audit.
5. **Digital exclusion:** `backend/app/reference_applicability.py` exact `POCKET_RELEASES` series/set-ID/title matching excludes 2,480 Pokémon Pocket references from *physical* pricing denominator. The full CSV preserves them visibly rather than deleting rows.

## Tier 1 — LIVE PRIORITY

| Game / type | Tier 1 physical items | Fresh stored value | Stale positive value | Missing positive value | Approved canonical image mirror *metadata* |
|---|---:|---:|---:|---:|---:|
| One Piece CARD | 266 | 134 | 6 | 126 | 257 |
| One Piece SEALED | 2 | 2 | 0 | 0 | 2 |
| Pokémon CARD | 202 | 82 | 1 | 119 | 179 |
| Dragon Ball Super CARD | 29 | 16 | 0 | 13 | 6 |
| Dragon Ball Fusion World CARD | 6 | 0 | 0 | 6 | 0 |
| **TOTAL** | **505** | **234** | **7** | **264** | **444** |

**Tier 1 diagnostic first failing gate (exactly one classification per inventory row):** 234 have fresh *stored* values (not variant-proven); 7 have stale positive values; **198** have no positive stored value and no provider mapping registered; **65** have no value and provider mappings awaiting review; **1** has no value even with a verified reference mapping. **These first-gate reasons do not prove the upstream provider lacks data.** No owner table was read to build this aggregate.

The live physical inventory has **12 distinct graded copies** (8 Tier 1). **Zero** have a verified positive-byte inventory-specific `media_object_mirrors` DB record. Seven of the 12 have an approved inventory-specific photo **asset**, but the presence of an approved asset is not the same as R2 mirror proof. A canonical *raw-card* image cannot satisfy a graded-slabs image requirement.

## Tier 2 — PHYSICAL LAUNCH-GAME REFERENCES

| Game | Physical card references | At least one eligible fresh GBP quote | Eligible stale | No eligible quote |
|---|---:|---:|---:|---:|
| Pokémon | 34,588 | 21,091 | 5 | 13,492 |
| One Piece | 9,007 | 0 | 0 | 9,007 |
| Dragon Ball | 16,626 | 0 | 0 | 16,626 |
| Naruto | 7,166 | 0 | 0 | 7,166 |
| **TOTAL** | **67,387** | **21,091** | **5** | **46,291** |

This is **31.3% provisional at-least-one-quote coverage**. **Complete finish/condition/grade coverage is not measured**. The raw `reference_cards` total is 69,867 including the 2,480 separately classified digital records.

**Observed exact-quote evidence**: eligible quote source `TCGDEX_CARDMARKET` (recorded GBP FX conversion); latest quote observed **2026-11-03 13:11 UTC**. The other sources often record `MIXED_LANGUAGE_REFERENCE`, `MIXED_NON_ENGLISH_REFERENCE`, `VARIANT_REFERENCE`, `US_CONTEXT_ONLY` or `physical_valuation_eligible=false`; these do not satisfy the strict physical-market-value contract.

**Mutually exclusive original 69,867-row reference first-gate diagnostic:**
- 27,240 price records with no quotes.
- 10,004 reference identities with no price row.
- 11,414 identities with only nonqualifying/indicative GBP guides.
- 113 records with no usable GBP conversion for the observed source price.
- 5 stale qualifying source quotes.
- 21,091 with at least one qualifying fresh source quote.

**Important:** 2,480 digital records are retained in the full source diagnostic and excluded from the physical count above.

## Tier 2 — IMAGE METADATA ONLY

| Game | Physical reference cards | Source URL + verified mirror DB metadata | Metadata gap |
|---|---:|---:|---:|
| Pokémon | 34,588 | 31,127 | 3,461 |
| One Piece | 9,007 | 9,007 | 0 |
| Dragon Ball | 16,626 | 16,626 | 0 |
| Naruto | 7,166 | 7,166 | 0 |
| **TOTAL** | **67,387** | **63,926** | **3,461** |

The all-reference row count is **66,251** mirror DB records, of which **66,247** show status VERIFIED and positive stored size; **4** are RETRY/SOURCE_UNAVAILABLE with **70 aggregated failure-count increments**. For all references (including digital), the unresolved DB-image-source cases are **3,616** no source URL and **4** RETRY; digital Pocket accounts for 159 no-image records, leaving 3,461 physical gaps. Distinct VERIFIED object keys **65,755**, yielding **492 additional DB pointers to already-used keys**; these may be legitimate shared images, not duplicate R2 objects. In DB metadata, minimum nonzero size 4,940 bytes and maximum 567,558 bytes. Image dimensions and actual object checks: **not measured**.

**No Cloudflare R2 listing/HEAD entitlement was exposed by the connected tools**, so actual objects, orphaned R2 keys, broken pointers, true duplicates and wrong-variant pixels cannot be reported. No objects deleted.

## Sealed and Tier 3

`reference_sealed_products` contains **3,893** source references. **2,749** have fresh positive stored `reference_sealed_market_prices.market_value_minor` and **1,144** do not; the source language is Unknown and exact product/condition evidence remains **not verified**.

Active R2-first publication registry: Disney Lorcana **3,519** records, Yu-Gi-Oh **45,419**, Magic/MTGJSON **153,680** records (published 9 Nov; this supersedes the older 153,679 checkpoint). Per-record strict GBP/variant and physical R2 image coverage: **not measured**. D1 remains paused. No fix authorised for Tier 3.

## Root causes and jobs requiring remediation

- **Missing source evidence / mapping:** 46,291 physical reference records have no eligible quote. The dominant stored-data first gates are no quotes, no price row, or only nonqualifying guide. Exact external provider nonexistence, true printing duplicates, grade-price feasibility: **not measured**.
- **eBay provider failure:** `tcg.market_ingestion_runs` has **32 FAILED runs**; latest **2026-11-10 01:54:02 UTC** with `PROVIDER_UNAVAILABLE`, HTTP **429**, `fetched_count=0`. Last SUCCEEDED group finished **2026-11-01 23:02:30 UTC**. The scheduled job's GitHub Actions run URL: **not measured** (evidence is Railway runtime and database run rows). Do not increase retries blindly while upstream rate/credits are exhausted.
- **TCGdex artwork repair:** Railway `reference-pricing-batch` logs from **2026-11-04** document two bounded runs (252 + 128 candidates), **380 HTTP 404 failures and 0 verified/updated**. Existing Python module `backend/app/pokemon_artwork_repair.py` already attempts high.webp, low.webp, high.png in bounded probes and rejects duplicate image SHA; do not replace missing artwork with placeholders.
- **Old Free-plan capacity gate:** Railway `drop-rate-api` logs on **2026-11-09** recorded `DATABASE_CAPACITY_WARNING`, `reason=BULK_REFRESH_DEFERRED_CAPACITY`, `free_limit_bytes=500000000`, `refresh_allowed=false` while database occupied ~428 MB. Supabase **Pro is now independently verified**. Whether this legacy capacity gate still blocks after upgrade: **not measured**; fix should inspect deterministic application logic and use actual plan-aware storage allocation before changing jobs.
- **Potential misleading coverage display:** `backend/app/catalogue_coverage.py` treats `MIXED_LANGUAGE_GUIDE` as a priced reference status, whereas founder policy requires exact-variant fresh market values, never guide/RRP as market value. Separate guide counts from eligible provenance and fix tests before production merge.

## Provider/rights decision gate (2026-11-10)

| Source / use | Documented limits / rights | Status for new price or image backfill |
|---|---|---|
| TCGdex (Pokémon identities/artwork, Cardmarket/TCGplayer quote wrappers) | API may expose images and cached prices; **commercial redistribution and per-image rights not independently verified**; published numeric request cap **not measured** | Stop new mirrors or derivative price reuse pending licensed terms |
| Bandai Official (One Piece, Dragon Ball artwork) | Bandai website restricts reproduction/display of copyrighted materials beyond personal use without prior consent: https://www.bandai.co.jp/en/site/notice/ | No new mirroring unless permission/approved rights evidence exists |
| Punk Records (One Piece) | Commercial card-art mirroring and API rate-limit terms **not verified** | Stop until rights reviewed |
| Naruto Card Game Archive | Commercial art/data reuse and API rate limits **not verified** | Stop until rights reviewed |
| Cardmarket direct and catalogue-derived guides | Prior written permission required for display of trading cards and prices on external sites: https://help.cardmarket.com/en/general-terms-and-conditions ; new API applications not currently accepted | Do not use as an unreviewed marketplace fallback |
| TCGplayer | API restricted to approved purposes; excludes unapproved combining pricing with third-party data, use in competing services: https://help.tcgplayer.com/hc/en-us/articles/360061115874-TCGplayer-API-Terms-Conditions | Exclude until express scope-authorisation confirmed |
| eBay Browse | Official published default **5,000 calls/day**, subject to actual key quota: https://developer.ebay.com/develop/api/buy/api_call_limits ; active listings not automatically sold-comparable market valuations | Restore rate/credit availability; do not relabel asking prices as sold |
| PokéWallet | Vendor claims commercial API use, free **100 requests/hour and 1,000/day**, paid options; upstream TCGplayer/Cardmarket price sublicensing **not independently verified**: https://pokewallet.io/api-docs | Do not buy, activate or backfill without approval/permission proof |
| CardTrader | Source for sealed/card-mapping indicative guides; commercial redistribution and applicable rate limits **not verified** | Review terms before further ingestion |
| YGOPRODeck (Yu-Gi-Oh) | 20 API req/s; explicitly requires card images to be locally stored/rehosted, but copyright ownership remains separate: https://ygoprodeck.com/api-guide/ | Tier 3 audit only; verify separate commercial display rights |
| Lorcast (Lorcana) | Recommend **50–100 ms** between API requests and >=24h caching; API file origin separate from request cap: https://lorcast.com/docs/api | Tier 3 audit only; commercial image rights unclear |
| MTGJSON (Magic) | MIT-licensed dataset; provides **no images**: https://mtgjson.net/faq/ | Catalogue data permitted within licence; artwork source must be independently approved |

Other source-specific API keys, provider cache licences, storefront sublicensing and commercial artwork proof are **not measured**.

## Platform, backup and safe repair boundary

- **Supabase Pro ACTIVE** confirmed by organisation API; project `ACTIVE_HEALTHY`.
- Supabase documents automatic Pro daily backups with seven-day retention: https://supabase.com/docs/guides/platform/backups . **The project-specific latest successful backup is NOT VERIFIED** because connected Supabase tools do not expose the actual backup inventory. **No bulk write until a named timestamped recovery point is confirmed.**
- Restoring an earlier database backup via **Dashboard > Database > Backups** replaces database state and can involve downtime / loss of changes after the snapshot. Prefer validating a restore to an isolated new project; R2 objects are NOT included in Supabase's DB backup.
- An object HEAD/list audit requires an existing approved read-only R2 credential and bounded audit job; after that, classify missing keys and image resolution/variant, then gather 20 sample candidates for each exact approved backfill.
- No backfill plan with approved rights and precise expected INSERT/UPDATE/SKIP exists yet. **An upsert dry run has not executed.** The 20-sample CSV is diagnostic, not a dry run. No proposed mutation SQL executed, no source generation overwritten, no price history pruned.
- Required next PRs (after approvals): 1) exact quote/condition/grade coverage reporting, 2) Pro-aware capacity gate fix and retryable allowed-provider adapters, 3) R2 HEAD/pixel/rights audit, 4) idempotent Tier 1 backfills with immutable price history; **each gated on backup+dry-run+approval**.
- Any SQL monitoring VIEW migration or scheduled/alert activation is a **production change** and needs founder approval before application. No table/view/trigger/RLS/Auth/owner/finance changes made.

## Before / after

**Before**: Tier 1 234/505 fresh stored values (not strictly provenance-certified); 444/505 approved canonical-image mirror *metadata*, 0/8 graded inventory-specific mirrors. Tier 2 21,091/67,387 physical references have at least one eligible fresh quote, 63,926/67,387 have source URL + verified mirror metadata. Tier 3 coverage unmeasured.

**After this audit**: SAME, because no production change was authorised or made. No claim of 100% coverage, no publication, no backup or restore, no D1 work.

## Decisions still required

1. **Confirm latest successful Supabase Pro backup**, with timestamp, and approve the restore procedure before any production data write.
2. **Confirm what licensed price sources may legally power Drop Rate's own marketplace pricing**, including TCGplayer/Cardmarket-derived third-party feeds. Existing cached data does not itself establish redisplay rights.
3. **Provide or approve a bounded read-only R2 HEAD/list and image pixel verification route** via protected existing CI credentials (no secrets exposed) before image repair.
4. **Approve a source-only reporting/monitoring migration and later production activation**, after its SQL plan, test receipt and zero-permission-escalation review.
5. **Approve each specific backfill only after its real dry run** reports exact INSERT/UPDATE/SKIP counts and 20 samples.

**PR intent:** evidence only for review. No live workflow or storage changes.

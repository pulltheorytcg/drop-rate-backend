# Drop Rate market-value and artwork coverage — production read-only baseline

Captured **10 November 2026** from Supabase project `ozrxenrdladkooixutmm`. **Do not interpret this audit as permission for any production write.** Supabase Postgres remains authoritative; R2 stores objects; D1 import remains paused. No financial, authentication, Shopify, Railway or n8n configuration changes.

## Validation definitions

- **Reference price evidence (Tier 2):** current GBP-normalised quote with `physical_valuation_eligible=true`, source `reference_language` equals the canonical card's language, positive `price_gbp_minor` and `observed_at` within 14 days. These are *row-level qualifying quote observations only*: finish/condition/grade coverage is not certified until required physical variants have been independently enumerated and matched.
- **Tier 1 stored-value evidence:** positive `tcg.inventory_items.market_value_minor` with `pricing_updated_at` within 14 days. Not equivalent to market-quote, finish, grade or condition certification.
- **Artwork database evidence:** usable HTTP `image_url`, mirror row status VERIFIED, nonempty R2 key and positive stored byte count; for owned inventory approved, rights-verified `media_assets` and `media_object_mirrors` metadata, inventory-specific when graded. Actual R2 HEAD/list, content digest, dimensions, placeholder detection, variant/language match and rights authorization **NOT VERIFIED**.
- **Tier 1 population:** approved, draft and inspection physical stock, plus any linked published Shopify items. Excludes four WITHDRAWN items; 506 PUBLISHED inventory links across 461 Shopify product IDs, and all correspond to existing physical inventory.

## Tier 1 (stored evidence, not certified price or physical R2 parity)

| Game/category | Live physical records | Fresh stored value | Stale stored value | Missing stored value | Approved mirror metadata |
| --- | ---: | ---: | ---: | ---: | ---: |
| One Piece CARD | 361 | 136 | 6 | 219 | 345 |
| Pokémon CARD | 212 | 82 | 1 | 129 | 182 |
| Dragon Ball Super CARD | 31 | 16 | 0 | 15 | 6 |
| Dragon Ball Fusion World CARD | 6 | 0 | 0 | 6 | 0 |
| One Piece SEALED | 3 | 3 | 0 | 0 | 3 |
| One Piece COLLECTION | 2 | 0 | 0 | 2 | 1 |
| Marvel COMIC | 1 | 0 | 0 | 1 | 0 |
| DC COMIC | 1 | 0 | 0 | 1 | 0 |
| **Total** | **617** | **237** | **7** | **373** | **537** |

**80** Tier 1 items have no approved rights-verified mirror metadata; **617** remain physically R2-unverified. **12 distinct** graded physical cards (8 Pokémon PSA, 3 One Piece PSA, 1 One Piece ACE); **7** have an approved inventory-specific source photo, **0** have a corresponding inventory-specific R2 mirror. Canonical raw artwork is **not** an acceptable graded/slab substitute.

## Tier 2 launch references

| Game | References | Fresh qualifying quotes | Stale eligible | Missing qualifying | URL+verified mirror metadata | DB mirror gap |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Pokémon | 37,068 | 21,091 | 5 | 15,972 | 33,448 | 3,620 |
| One Piece | 9,007 | 0 | 0 | 9,007 | 9,007 | 0 |
| Dragon Ball | 16,626 | 0 | 0 | 16,626 | 16,626 | 0 |
| Naruto | 7,166 | 0 | 0 | 7,166 | 7,166 | 0 |
| **Total** | **69,867** | **21,091** | **5** | **48,771** | **66,247** | **3,620** |

**Exact per-set evidence**: `docs/evidence/catalogue_coverage_per_set_20261110.csv`; **674** distinct system/language/set combinations; reconciles 69,867 rows exactly. Physical object existence remains unknown for the 66,247 mirror records. Those rows reference 65,755 distinct object keys (repeated references are not evidence of duplicate physical objects). Pokémon gap: 3,616 absent image URLs and four `RETRY/SOURCE_UNAVAILABLE` mirror records, with 70 cumulative failures.

### Exactly one provisional primary price cause per *uncovered reference*

| Primary cause, in deterministic precedence order | Records |
| --- | ---: |
| Price row present, `quotes=[]` | 27,240 |
| No matching provider price row | 10,004 |
| GBP amount exists but only mixed-language/indicative/non-eligible source quotes | 11,414 |
| Non-GBP original amount but usable GBP quote unresolved | 113 |
| Previously eligible GBP quote now older than 14 days | 5 |
| **Total not qualifying now** | **48,776** |

These are **database evidence categories**, not verified ultimate root causes. Provider identifier/finish mismatch, actual provider data absence, duplicate source identity and runtime rate limits require external read-only verification before a permanent cause is assigned. Neither `checked_at` nor stored scalar `market_value_minor` substitutes for an eligible variant-specific quote.

### Ingestion and failure evidence

- `tcg.market_ingestion_runs` (eBay source): 531 BLOCKED, 270 SUCCEEDED, 32 FAILED; latest FAILED 10 Nov 2026 01:54:02 UTC, `PROVIDER_UNAVAILABLE` HTTP **429**, 0 fetched, 0 inserted; latest succeeded 1 Nov 2026. Railway `reference-pricing-batch` deploy logs on 4 Nov explicitly say `eBay sold-data provider credit or rate limit was reached`. Provider job-specific GitHub Actions URL: **not measured** (Railway runtime logs, not Actions).
- Railway `reference-pricing-batch` artwork repair logs (4 Nov): initial `ModuleNotFoundError: No module named 'app'`, then a bounded 380-artwork source test reported **380 HTTP 404** and **0 verified**, not 380 missing R2 objects. Relevant code `backend/scripts/repair_pokemon_artwork.py`, `backend/app/pokemon_artwork_repair.py`.
- Railway operations monitor logs on 9 Nov still emitted `DATABASE_CAPACITY_WARNING`, `BULK_REFRESH_DEFERRED_CAPACITY`, with old 500,000,000-byte Free threshold. Supabase organisation **now reports Pro**. An obsolete application capacity guard is a candidate ingestion blocker; fix only after locating its actual code and proving read-only behaviour and backup state. The actual impact on import throughput is **not measured**.
- `tcg.catalogue_job_runs`: 19 `REFERENCE_PRICES` INCOMPLETE, last 8 Nov; `CARDMARKET_VALUES` last COMPLETE 8 Nov; `POKEWALLET_*` price jobs last COMPLETE 8 Nov. Per-run protected approval and provider terms still need inspection.

## Sealed and Tier 3

- Reference sealed products **3,893**; scalar fresh positive **2,749**, non-fresh/missing **1,144**. Provider CardTrader often labels the language `Unknown`. Strict condition/language/variant/physical eligibility not verified.
- Active R2-first publications at audit: **Lorcana 3,519**, **Yu-Gi-Oh! 45,419**, **Magic 153,680** (published 9 Nov at 20:38 UTC). Strict price, artwork, object existence, per-set distribution **NOT MEASURED**; these records are **not** in the original 69,867-row `reference_cards` relation. Tier 3 must remain report-only.

## Source and reproduction permission gate

| Source | What is represented | Current rate or terms status | Commercial use/mirroring status |
| --- | --- | --- | --- |
| TCGdex / TCGdex Cardmarket | Pokémon identity, artwork URLs, language-specific UK GBP reference | Public API; no independently verified hard per-user quota | Cached API metadata does not confer a blanket right to mirror/storefront-publish artwork |
| Cardmarket / CardTrader | Bulk singles/sealed asking/trend references, mixed-language guides | Provider entitlement and exact commercial API rate **not verified** | Cardmarket external price display requires written agreement; CardTrader market API permission to verify |
| TCGplayer | US-context price reference | Contractual API terms apply | Combining/commercial redistribution requires independent agreement; do not turn US-context-only into GBP physical value |
| eBay sold/market provider | Select owner-linked sold comps | **HTTP 429**; budget/credit limit actively reached | Stop on 429; Browse is active listings, not itself confirmed sold feed |
| Punk Records / Bandai Official | One Piece and Dragon Ball card identity/art | Specific rate quotas not measured | No blanket commercial reproduction grant demonstrated |
| Naruto Card Game Archive / Kayou | Naruto identity and image references | Quotas not measured | Commercial mirroring rights unclear; STOP |
| PokeWallet | Guide/reference quotes | Quotas not measured | Partner terms unclear; STOP |
| Lorcast / YGOPRODeck / MTGJSON | R2-first Lorcana, Yu-Gi-Oh and Magic metadata | Lorcast advises 50–100 ms request pacing and 24h caching; YGOPRODeck states 20 req/sec | Provider/card-art licensing requires independent review; MTGJSON dataset licence does not grant third-party art rights |
| Shopify CDN / founder media | Storefront media and first-party uploaded photos | Shopify policies apply | Distinguish Shopify CDN from owned R2 object; check media rights and owner-provided upload licence before mirroring |

No new scraping or licensing acceptance under this audit.

## Backup, operations and dry-run blockers

- Supabase organisation `plan=pro` CONFIRMED; project `ACTIVE_HEALTHY`.
- Exact most recent completed automated backup **NOT VERIFIED**; the available connector does not expose backup inventory. Daily Pro backups advertised by the platform do not replace verifying a particular actual recovery point.
- Physical R2 HEAD/list, orphan/duplicate-content audit, file dimensions/placeholder/variant validation **NOT MEASURED** (no bucket-scoped read-only object-list/HEAD action was available). No objects deleted.
- **No backfill dry-run**: specific approved source, deterministic mapping policy and actual R2 verification are not yet sufficient to truthfully output inserts/updates/skips for a safe batch. **No production writes**, Shopify/n8n/Railway configuration changes, catalogue snapshots, paid data-source expansions, D1 imports or owner/financial changes were made.
- A private PostgreSQL view exists as a **review-only SQL proposal** in `database/proposals/catalogue_coverage_monitoring_views_20261110.sql`, not a deployed migration. It separates evidence from proof and returns `NOT_VERIFIED` for physical R2 parity. Deploying it would require independently verified backup, migration testing/approval and explicit production change authorisation.

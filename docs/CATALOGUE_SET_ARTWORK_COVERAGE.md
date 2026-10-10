# Drop Rate — Set artwork completeness audit and approval workflow

**Baseline:** 10 October 2026. **Scope:** Existing catalogue source records released by this date, not necessarily unique physical set releases. All counts from live Supabase `tcg.reference_sets` compared with the checked-in `catalogue-title-art.js` mappings.

## What was missing from the earlier work

PR #577 corrected the appearance and prevented individual card-image previews in set tiles, but it did **not** finish the separate source/artwork backfill, cross-game coverage audit, governed backend resolver or maintenance API. The baseline grid showed `Eevee Grove (A3b)` with the generic Pokémon mark even though its distinct set logo exists in publisher material. This is a sourcing/coverage issue, not a failed image load.

## Measured baseline

| Source/system | Total reference set records | Exact-title logo mapping | Missing exact title logo |
| --- | ---: | ---: | ---: |
| Pokémon TCGdex, English | 220 | 159 | 61 |
| Pokémon TCGdex, Japanese | 186 | 0 | 186 |
| Pokémon CardTrader, unknown language | 459 | 0 | 459 |
| One Piece, all sources/languages | 201 | 2 | 199 |
| Dragon Ball Masters + Fusion World, all sources/languages | 302 | 0 | 302 |
| Naruto Kayou + Legacy, language unknown | 81 | 0 | 81 |
| **Total** | **1,449** | **161** | **1,288** |

The exact-title mapping count is based on 32 bundled publisher mappings (30 matched English Pokémon, two One Piece English/Japanese) and 157 supplied TCGdex logo URLs (129 matched live English records), with no cross-provider, game or language substitutions.

These are source rows, and some represent the same release from different providers. An 'unknown language' CardTrader row is **not** proof an official English or Japanese logo is absent. Set title artwork is navigation-only; it does not approve Shopify or inventory images.

## Implemented in this focused continuation

- `backend/app/static/title-art/set-artwork-registry.json` is an auditable read-only snapshot of the existing curated bundled images and existing TCGdex set-logo index, including source references and a manual review queue. It contains no card image fallbacks or new external image hosts.
- `backend/app/catalogue_set_artwork.py` resolves a set's title art using exact provider/game/language/set identity and a validated local or TCGdex logo URL. Output has `type`, `status`, `source`, `url` or `file`, and `title`, never an arbitrary card preview. Missing exact art remains `SET_LOGO_MISSING` and uses the existing game logo or Drop Rate brand glyph. The enum deliberately says `SOURCE_INDEXED`, **not** `RIGHTS_APPROVED`: provenance does not prove commercial reuse rights.
- `GET /api/v1/catalogue-browser/sets` adds that typed `artwork` contract, while `GET /api/v1/catalogue-browser/set-artwork-coverage` is founder-admin-only, reports exact vs fallback coverage, and returns a bounded review list. Every count uses source records without leaking seller ownership.
- The browser prefers the typed server art, validates the source and retains the existing safe local fallback only for stale cached/testing responses.
- The existing `refresh_catalogue_logos.py` now refreshes both the JS lookup and backend manifest from the same permitted TCGdex index. CI checks enforce exact parity. No new provider, database table, eBay expansion, background automation or storefront launch.
- Unit, UI and release tests cover missing/incorrect source, wrong language/provider, malicious external URL, metadata preservation, and mobile/desktop set tile identity. A real signed-in device acceptance remains a separate required step.

## Eevee Grove — verified distinction

- Exact record: Pokémon TCGdex English `A3b`, `Eevee Grove`, 26 June 2025, 107 cards.
- The TCGdex set index currently lists a null logo for that code, hence Drop Rate's valid **game-mark fallback**.
- An independent archival source identifies the official English *Eevee Grove* set logo, with image dimensions and provenance: https://bulbapedia.bulbagarden.net/wiki/File:A3b_Set_Logo_EN.png
- The Pokémon publisher confirms the set is a **Pokémon TCG Pocket digital expansion**, not a physical Pokémon TCG printed set: https://www.pokemon.com/uk/pokemon-news/the-latest-pokemon-tcg-pocket-expansion-eevee-grove-has-arrived
- The archival image is marked 'fair use', **not a reusable licence for this UK commercial marketplace**. It is in `pending_review`, not published. Verify an authorised first-party/permission-backed logo asset and the exact English printing before registering it. Never pull this single-card asset into Shopify or treat the digital cards as saleable physical stock.

## Remaining, *not* complete

1. **Artwork licensing and backfill:** obtain suitable and permitted exact logo assets for missing Pokémon (including Pocket) and official set art for One Piece, Dragon Ball and Naruto. Update asset metadata, verify exact game/set/language identity and evidence/rights; register reviewed assets in the authoritative sources registry. The current fallback stays until accepted.
2. **Admin triage UI:** the secured report endpoint now supports maintenance/reporting; a curator screen to approve/upload source assets is a later phase, not silently made public.
3. **Physical/digital separation:** define display/intake treatment for TCG Pocket digital-only sets before enabling any physical sale/valuation pathway. Do not quietly delete catalogue rows or fake valuations.
4. **Production acceptance:** CI + Railway deployment/readiness, admin coverage report access tests, and an actual mobile/desktop signed-in visual audit across Pokémon, One Piece, Dragon Ball and Naruto.
5. **OP17 quantity pooling:** GitHub issue #576 is a separate deterministic Shopify/Supabase sales-attribution task; it is **not** solved by this set artwork release.

## No data/security regressions allowed

RLS and founder authorization remain enforced on the admin endpoint. No existing set identifiers, ownership, values, prices, source histories, Shopify products/themes or live inventory are mutated. Provider terms and rate limits remain respected. Never label a provenance-verified third-party logo as permission-cleared unless approved under the documented image-rights process.

# Naruto verified sealed reference pilot — 15 October 2026

## Goal and source

Seller Hub has **zero Naruto sealed references** despite 7,166 independent Naruto card references. The founder requires no paid API, no scraping, and no fabricated products or prices. We manually verified **four authentic Kayou Naruto product models** using first-party manufacturer product pages. This is a bounded one-off factual product manifest, NOT an automated crawler, a copy of their commercial artwork, or a claim of complete worldwide Naruto sealed coverage.

| Manufacturer model | Set / edition | Retail package | Original source |
| --- | --- | --- | --- |
| NR-RDIV-Z001-NA | Heaven Scroll Series 1, Version A | Booster box: 24 packs × 8 cards | https://www.kayouofficial.com/en-US/series/series-5zdty4vj |
| NR-KP-DZJ-002A-NA | Earth Scroll Series 2, Version A | Booster box: 20 packs × 7 cards | https://www.kayouofficial.com/en-US/series/series-8idoe481 |
| NR-KP-CC-ZZZ-003A-NA | Chapter Jin Series 3, Version A | Booster box: 12 packs × 8 cards | https://www.kayouofficial.com/en-US/series/series-cv8e3pgi |
| NR-KP-RZSD-LH-001-NA | Ninja Age Premium Collector Box | Collection: 16 packs × 5 cards plus one promo | https://www.kayouofficial.com/en-US/series/series-0nyket49 |

The official publisher identifies the release **month** (Sep 2025 / Mar 2026 / Apr 2026 / Aug 2026), not the exact day. We store `release_month` as evidence and leave `reference_sets.release_date=NULL`, rather than invent the first of the month. Manufacturer `-NA` models are stable SKU identities, **not verified physical card language**; all four retain `language='Unknown'`. We do not fabricate separate loose-pack SKUs from the boxes.

## Architecture, permissions, and data scope

- The manifest is `backend/app/verified_kayou_sealed.py`, validated with exact immutable manufacturer model, hostname, source page and box card-count facts. It is not a new wholesale price provider.
- One-time admin-only execution through `backend/scripts/import_verified_kayou_sealed.py --actor-user-id <authorized-uuid> --apply`. Without `--apply`, the script is an offline dry run with **zero database or network access**.
- The transaction writes only the existing `tcg.reference_sets` and `tcg.reference_sealed_products` tables with `provider='Kayou Official'`, `system_code='NARUTO_KAYOU'`, `language='Unknown'`. Every `provider_id` equals the original published model; collisions on any source/packaging attribute **abort** rather than overwrite.
- No new pricing provider, schema, database migration, uploaded card, owner inventory, Shopify product, cost, sold/guide quote, background job, API credential or payout. All reference prices remain missing until authorised evidence is available.
- The official manufacturer pages contain artwork, but no right to redistribute their photo has been established. **No manufacturer images are copied, downloaded, hotlinked or removed from watermarks.** The Seller Hub shows an honest image-pending placeholder and a validated link to the corresponding manufacturer page. Product reference art ≠ a physical customer's approved listing image.
- The shared browser already resolves this family under the unified Naruto category. Non-CardTrader sealed references now display their actual source rather than `CardTrader sealed`. Adding a physical item still requires explicitly choosing its language, confirming exact sealed product and entering the existing Draft/inspection path.

## Failure points and testing

- SKU typo, phony manufacturer domain, invented date/pack count, invalid product type → reject manifest.
- Duplicate model in two products → reject both, no preferred order.
- Existing reference changed in database → guarded upsert refuses and rolls back all four entries.
- Previous records missing image or price → **remain missing**; no implicit image/price inheritance.
- Damaged/unverified real box → seller must choose language and confirm physical product, then manual review; no auto approval.
- Host spoofing, arbitrary URL in seller reference → validated exact publisher link only; no XSS or arbitrary internal fetch.
- CI tests in `tests/test_verified_kayou_sealed.py` and `tests/ui/catalogue-browser.cjs`, existing backend/UI and real Postgres workflows; dry-run and live idempotent readback must be recorded before calling the catalogue populated.

## Follow-up scope

Kayou Earth Scroll Series 1 source has an inconsistent model rendition across pages/search, so it is **excluded** rather than guessed. Other products, releases and Bandai Legacy sealed SKUs require similarly verified manufacturer models, separate regional variants and safe image/display rights. The four items are a narrow reliable start, not full Naruto catalogue completion.

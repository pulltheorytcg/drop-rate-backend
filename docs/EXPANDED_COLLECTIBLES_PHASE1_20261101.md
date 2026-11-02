# Expanded collectibles — phase 1, 1 November 2026

## Live deployment checkpoint — 2 November 2026

**Supabase schema deployed; provider imports, R2 figure publishing and
Shopify/App integration NOT deployed.** Dated checkpoints below document
earlier states, not the current production state.

- [Guarded dry-run](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/41495317302)
  and [production migration apply](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/41495891502)
  succeeded. All six expected versions are recorded (160 migrations in total);
  three old versions are history-only no-op baselines, two older SQL repairs
  were reviewed and checksum-pinned, plus the additive collectible schema.
- Post-deploy readback: ten new category codes, six new tables with forced RLS,
  validated Japanese One Piece source-language constraint and both dispatcher
  heartbeat functions. Original physical inventory, owners, orders, Shopify
  records and media were untouched. Figure-products count remains zero.
- Production `pg_database_size()` is **419,220,627 bytes** (~419.2 MB),
  **19,220,627 bytes beyond** the YGO importer stop at 400,000,000 bytes.
  Headroom before the Free plan's 500 MB database quota is only **80,779,373
  bytes**. Do **not** bypass this guard. R2 remains the destination for
  permissioned bulk assets; a future Supabase **Pro database** upgrade needs
  a separate cost/ROI decision, not more Supabase Storage buckets.
- [Source window 650/650/325](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/41496879400):
  100 MTG Foundations rows yielded **101** exact printing/finish references;
  100 eligible LEGO 2026 rows yielded **98** valid sets and **2 quarantines**;
  50 Yu-Gi-Oh TCG source cards yielded **154** exact printings. The LEGO
  preview now quarantines invalid rows instead of failing the whole batch,
  without loosening exact edition checks; new regression tests pass.
- [Tail window 750/750/375](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/41497113039):
  **21** Magic cards, **16** remaining eligible 2026 LEGO sets and **158**
  Yu-Gi-Oh exact printings from 50 more source cards. All previews reported
  zero Supabase/R2/Shopify writes, verified prices or image mirrors.
- [Draft PR #869](https://github.com/pulltheorytcg/drop-rate-backend/pull/869)
  remains unmerged. No Railway/App code rollout, public figure feed,
  newly imported owner inventory or Shopify catalogue launch. Commercial
  source rights, capacity, R2 readback and owner/Shopify sync remain gated.


## R2-input preparation checkpoint — 2 November 2026

- [Successful closed-Magic-metadata bundle run](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/41526033446)
  processed **all 771 MTGJSON Foundations (`FDN`) source card rows**
  into **1,179 unique UUID-plus-finish printing references**, with **zero
  quarantines**. A bounded set of eight immutable, content-addressed local
  metadata files and an integrity/index receipt were archived as a 7-day
  GitHub Actions artifact (expiration 9 November 2026). No provider image,
  unverified price, physical inventory, owner information or Shopify ID
  enters the payload. Each part has SHA-256 verification and a strict closed
  schema. This is an **R2-ready source-input bundle, not an R2 upload**.
- The source-data licence is [MTGJSON MIT](https://www.mtgjson.com/license/).
  That covers the selected metadata; it **does not** grant third-party Magic
  artwork redistribution rights. Any public reference feed must still pass
  image and pricing rights checks. Closed private R2 source archiving is
  separately flagged and already verifies actual remote upload/readback
  when deliberately invoked. No flag was enabled here.
- Existing Railway production service `drop-rate-api-live` has the
  configured Cloudflare-compatible object-storage variable **names** and
  current R2 catalogue publications show 69,697 reference cards.
  We did **not** read secret values, create a new bucket, add a service,
  change production flags or deploy this draft branch.
- An existing live reference-media refresh continues to report
  `BULK_REFRESH_DEFERRED_CAPACITY` with the same 419,220,627 database
  bytes. R2 archiving licensed metadata helps with bulk-storage cost, but
  does **not** remove the need for an indexed database footprint/capacity
  decision to activate new canonical records and app search.



## Verified starting point

Production had 69,697 shared reference cards. `YUGIOH`, `DISNEY_LORCANA`
and `RIFTBOUND` were already registered as systems, but had **zero** imported
references. R2 catalogue generation 122484 was current at the read-only check.
The latest scanned comic/Shopify repair remains separately gated; this work
must not change existing stock, owner allocations, scanner confidence or price
history. No new Railway service or paid subscription is introduced.

## The identity model

| Family | Master reference | Exact-match discriminator |
| --- | --- | --- |
| Yu-Gi-Oh!, Lorcana, Riftbound, Magic: The Gathering | existing `tcg.reference_sets` + `tcg.reference_cards` | game + language + exact set + card number + rarity + print/finish/art treatment; MTGJSON UUID **and each actual finish** |
| Football, NFL, basketball, baseball, hockey, motorsport | existing `reference_cards` plus `reference_card_product_details` | manufacturer + season + series + athlete + printed number + parallel + autograph/numbering |
| Funko Pop! / other figurines | new `tcg.reference_figure_products` | manufacturer + official item/SKU or GTIN + franchise + series + figure number + edition/exclusive variant |
| LEGO construction sets | existing `tcg.reference_sets` (themes) + `tcg.reference_sealed_products` (`LEGO_SET`) | exact set number **and edition suffix** + theme ID/name + release year + piece count |

The two reference families are **not** physical owner stock. Canonical
`tcg.catalogue_products` and `tcg.inventory_items` retain existing verified
ownership, price, shipping and Shopify publication gates. There is deliberately
no new `FIGURE`-to-physical-inventory shortcut, guessed shipping profile or
automatic Shopify product publication. That will be a separately tested phase.

## Real upstreams and permission gates

- **Yu-Gi-Oh!**: YGOPRODeck public v7 `cardinfo.php` and `cardsets.php`.
  Documented limit 20 requests/second; pilot uses two requests with normal
  caching. `card_sets` entries are distinct physical printings; passcode or
  name is insufficient. The source's `card_prices` are not verified sold
  transactions and its `card_images` do not prove exact-printing artwork.
  Provider documentation asks consumers to cache/re-host rather than hotlink;
  image rights must still be reviewed before R2 mirroring. See
  <https://api.ygoprodeck.com/api-guide/>.
- **Lorcana**: Ravensburger official card gallery and Lorcast's documented
  card/set API are candidate reference sources. Confirm redistribution/media
  terms before automated bulk import. Digital base art is not a foil proof.
  <https://cards.disneylorcana.com/en-US/>, <https://lorcast.com/docs/api/cards>.
- **Riftbound**: Riot's Riftbound developer documentation requires an approved
  app-specific API key or written licence for app assets and says third-party
  substitutes cannot be used. No fan-scraped artwork import or R2 copy.
  <https://developer.riotgames.com/docs/riftbound>.
- **Sports**: begin with official Topps/Panini checklists, then add other
  manufacturers through explicit adapters. Checklist rows provide *identity*,
  not validated resale value or imagery redistribution rights.
  <https://www.topps.com/pages/checklists>,
  <https://www.paniniamerica.net/resources.html>.
- **Figures**: official Funko product/item pages, then approved manufacturer
  catalogues for other figures. Do not assume an unrestricted bulk Funko API;
  product-page parsing and image reuse require a permitted provider method.
  Collect an exact manufacturer item ID, box number, barcode, series and
  exclusive/chase edition rather than fuzzy names.
- **Magic: The Gathering**: MTGJSON's per-set JSON files contain printing
  UUIDs, collector numbers, set codes, rarity and supported physical finishes.
  Its published MIT licence applies to the data/software, **not** automatically
  to Wizards/Scryfall card artwork. The new bounded pilot reads individual
  set JSON, skips digital-only rows and emits a separate source ID per finish;
  image and source prices are removed. Source: <https://mtgjson.com/license/>,
  <https://mtgjson.com/downloads/all-files/>.
- **LEGO**: Rebrickable's public downloadable `sets.csv.gz` and
  `themes.csv.gz` provide exact set numbers, theme IDs, years and piece counts;
  its API explicitly recommends CSV downloads for bulk catalogue work.
  **Commercial reuse/redistribution permission has not been established**;
  treat this as a read-only local preview until approved. Public source image
  URLs are discarded, as are unverified retail prices. Do not upload the
  raw CSV or derived catalogue to R2 or Shopify without permission.
  <https://rebrickable.com/api/>, <https://rebrickable.com/downloads/>.
- **Market values**: use independently permitted, source-attributed UK sold
  transactions and condition/grade-specific evidence. Active listings are
  asking evidence only. Existing market-history records remain immutable.
  hobbyDB/Pop Price Guide may offer a negotiated API; it is *not* configured.
  TCGplayer's API terms restrict competing uses and data combination; do not
  add it to Drop Rate without specific permission.

## Code included in phase 1

1. Additive migration `20261101205040_collectible_catalogue_expansion.sql`
   registers six sports, two figure categories, Magic and LEGO, typed sports-card attributes,
   figure model records, append-only figure sales/listing observations, nullable
   GBP value caches and an independent R2 publication cursor. Tables use forced
   RLS, `tcg_api` founder-admin writes and no physical ownership/Shopify fields.
2. `collectible_source_adapters.py` normalizes Yu-Gi-Oh!, Lorcana and official
   sports-checklist exact printings, plus manufacturer figure metadata.
   Lorcana remains preview-only pending terms verification. Source images
   remain unverified and market prices remain absent; contradictory identifiers
   are quarantined.
3. `pilot_yugioh_catalogue.py` is read-only by default. Explicit `--apply`
   additionally requires `TCG_EXPANDED_CATALOGUE_IMPORT_ENABLED=true`, the
   configured maintenance actor, a verified admin roster and a sub-400 MB DB.
   The batch is capped at 1,000 provider cards **and** 1,000 printings.
4. `collectible_reference_feed.py` has a separate, disabled-by-default
   authenticated figure lookup and founder-admin publication route. It splits
   closed public metadata into bounded, content-addressed R2 reference parts,
   verifies upload and actual download, then atomically publishes only the
   unchanged DB generation. Cold, stale or corrupt R2 data falls back to the
   authorised database query. No price is shown after expiry, and only a
   rights-approved private R2 media key can become a signed image URL.
5. Existing reference cards imported in future YGO/sports/Lorcana/Riftbound
   pilots will use the **existing** catalogue R2 publication path. The figure
   sidecar does not alter its schema, generation or query strategies.
6. `pilot_expanded_catalogues.py` stages **Magic** per-set MTGJSON and
   **LEGO** public Rebrickable CSV in bounded read-only previews (default 25,
   cap 100). Curated **Funko, Topps, Panini** official-source JSONL records
   are supported by exact-identity normalizers and manufacturer/host matching;
   there is no unapproved automated scrape. The pilot prints a deterministic
   normalized-metadata SHA-256 and source quarantine report, but never uploads
   R2, creates Supabase rows, mirrors images, invents GBP values or sends Shopify
   products. A new importer is not a live feed until separately gated R2
   publication, signed-in App lookup and SKU/physical stock integration pass.

### Additional live-source batch receipts (1 November, read-only)

| Source | Preview window | Valid exact references | Quarantined | Metadata SHA-256 |
| --- | --- | ---: | ---: | --- |
| MTGJSON `FDN` (Foundations) | first 25 of 771 card rows | **50 print+finish records** | 0 | `518c2a928307bd522d915f0410924e4b625356ea20f0062a0c1a0099ec2992f8` |
| Rebrickable LEGO, `year=2026`, building-set filter | first 25 of **766 eligible** records (of 1,568 source rows) | **25 buildable-set models** | 0 | `a84fb0bef666403a64c2efdcb0a89e5d10cda2220bb75063544a8c8682b3fbf8` |

Only normalized, closed metadata was hashed in memory. The MTG preview
serialized to 35,907 bytes and corrected LEGO to 18,773 bytes. Rebrickable's
raw `sets` file also includes zero-piece Gear merchandise, such as Jibbitz;
those and Gear/Books/Non-LEGO theme branches are **excluded before selection**.
Records with fewer than two recorded parts are held back for classification
review, even if some might be legitimate single-part packages. Zero data objects were
uploaded or externally written. LEGO source-data rights are an open gate.

Reproduction commands:

```sh
PYTHONPATH=backend python backend/scripts/pilot_expanded_catalogues.py --source magic --set-code FDN --limit 25
PYTHONPATH=backend python backend/scripts/pilot_expanded_catalogues.py --source lego --year 2026 --limit 25
PYTHONPATH=backend python backend/scripts/pilot_expanded_catalogues.py --source funko --input-jsonl authorized_funko.jsonl --limit 25
PYTHONPATH=backend python backend/scripts/pilot_expanded_catalogues.py --source topps --input-jsonl authorized_topps.jsonl --limit 25
PYTHONPATH=backend python backend/scripts/pilot_expanded_catalogues.py --source panini --input-jsonl authorized_panini.jsonl --limit 25
```

For Funko rows supply `system_code=FUNKO_POP`, `manufacturer=Funko`, a unique
official `provider_id`, `name`, and exact `source_url` on `funko.com`; optionally
`manufacturer_sku`, `barcode_gtin`, `figure_number`, franchise and variant.
For Topps/Panini rows supply `system_code` (one of six sports codes),
`manufacturer` (exactly `Topps` or `Panini`), official-host `source_url`,
`series`, integer `year`, `card_number`, `athlete`, and a declared `parallel`
(use `Base` for confirmed base printing); add team, league, serial print run,
autograph and memorabilia evidence only when supported by the checklist.
File format: **one JSON object per line**. These examples are **input
contracts, not permission to scrape**. Source/provider approvals and licenses
remain release prerequisites.

### Supabase capacity business case (updated 1 November)

- Production organisation is on **Supabase Free**; read-only query returned
  `pg_database_size()` **419,220,627 bytes** (~419.2 MB decimal) at the
  2 November live readback, versus the published Free plan's 500 MB database
  quota. This is *database size*, not Supabase Storage bucket usage or all
  disk/WAL bytes. One importer conservatively stops at **400,000,000 bytes**,
  so real catalogue SQL batches remain blocked by this safety guard.
- Largest live tables: `tcg.audit_events` **105,152,512 bytes**,
  `tcg.reference_cards` **77,152,256 bytes** (69,697 rows),
  `tcg.reference_market_prices` **58,867,712 bytes** and
  `tcg.reference_catalogue_prices` **44,638,208 bytes**. Roughly 100,000
  more reference-card rows at the current per-row average could add ~111 MB
  *for that table alone*, before sets, sports details, price evidence or indexes,
  beyond remaining ~80.8 MB database-quota headroom.
- **No case to increase Supabase Storage bucket capacity** for source files,
  product photographs or image history: put rights-cleared bulk media and
  immutable source metadata in Cloudflare R2. **Potential future case for
  Supabase Pro database disk** when the reviewed compact-reference projection
  exceeds remaining headroom, or query performance/availability benefits
  justify it. Current Pro starts at **$25/month** and lists 8 GB included DB
  disk, subject to plan and usage limits. There is **no plan upgrade now**.
- Keep read-only batches running and count distinct indexed rows by source.
  Before any real SQL batch, evaluate a source-specific DB growth forecast,
  the 400 MB importer guard, Free quota, business value from search/stock
  matching, and R2/API read-back parity. Do not bypass the guard to force data
  into Free or silently promote unlicensed LEGO/Funko imagery.

Sources: <https://supabase.com/pricing>,
<https://supabase.com/docs/guides/platform/database-size>.

### Source pilot receipt (read-only)

YGOPRODeck `format=tcg` at offset 0, limit 100: **100 card objects**, **270
distinct printing candidates** in **133 sets**; **one card quarantined** for
set-code conflict. No DB write, image mirror, verified market price or Shopify
product was made. A separate 10-card read returned 17 candidates in 10 sets.
Neither result claims complete catalogue coverage.

### Phase 2 staging receipt (1 November, subsequent review)

- The live database remains **unchanged** at 69,697 shared reference cards,
  1,472 reference sets and 14 pre-expansion system codes. A read-only size
  query returned **389,418,131 bytes** against the importer guard at
  **400,000,000 bytes** (approximately 10.6 MB available before that guard).
  No bulk import may be assumed safe merely because the count of missing cards
  is high. R2 snapshots reduce pressure but do not replace the small indexed
  database references needed by the current live API.
- A fresh read-only `--limit 25` YGOPRODeck request returned **25 card objects,
  94 exact printing candidates across 56 sets**, and **one set-code mismatch
  quarantined**. Zero database writes, market values, mirrored images or
  Shopify creations. Card names/prices were not used for loose joins. The
  55,201-byte closed source-input projection gave content SHA-256
  `813d3943953f9bbb33bf40f14c3951e400576e118a261bb26fac0de523e4ff57`;
  this digest is a **dry-run receipt, not an uploaded R2 object**.
- A separate, single-card **read-only Lorcast** lookup (`/v0/cards/1/207`)
  matched the existing exact Lorcana ID, English language, set and number.
  The normalizer included **no image or price**. Lorcana bulk import remains
  disabled pending explicit review of third-party/community-code terms.
- `tests/expanded_collectibles_postgres.py` now checks the actual migration
  and exercises reference write policies, figure R2 generation invalidation,
  append-only observation evidence and existing card upsert in a **new empty
  local PostgreSQL 17 database only**. The dedicated CI workflow never uses
  production credentials and has no R2/Shopify write access.
- A paid Supabase development branch was **not** created. If one is required
  for full production-schema migration replay, its current cost must be
  confirmed before provision. The separate production migration dry-run gate
  remains required before any real apply.
- To relieve near-term database pressure, the YGOPRODeck pilot can now
  optionally write a **private, immutable R2 source-input receipt** without
  inserting any SQL rows. This is not a new public catalogue endpoint:
  `--archive-private-r2` and
  `TCG_EXPANDED_CATALOGUE_R2_SOURCE_ARCHIVE_ENABLED=true` are both required,
  as is configured object storage. Only a closed projection of exact set and
  printing metadata is archived, with unverified image URLs, provider prices,
  owned stock and PII excluded. The existing R2 object writer verifies remote
  bytes after upload and the pilot reads the payload back again before
  reporting success. Default remains dry run. Do not activate the flag or
  mistake a source receipt for a customer-facing live reference manifest.

## Remaining production release gates — after live schema deployment

The additive database schema and guarded migration-history reconciliation are
**complete**. The former 154-version preflight reflects historical drift, now
resolved. CI pins reviewed historical SQL hashes, allows only explicit
history-only exceptions and fails closed if unexpected migrations appear.

1. Keep source previews bounded, reproducible and non-overlapping. Inspect
   quarantine reasons instead of correcting unknown identifiers automatically.
2. Obtain permitted commercial reuse rights for any LEGO, Funko, Topps/Panini,
   Lorcana and Riftbound data/images before cataloguing for customers.
   Verified GBP values require separately approved sold-sale evidence.
3. Estimate indexed per-source reference and price growth before importing.
   Do not bypass the 400 MB importer stop while the database is 419.2 MB.
   Supabase Pro database disk requires explicit ROI approval; no storage-bucket
   upgrade or other paid plan has been made.
4. Once capacity and source rights are approved, test a small replay-safe,
   deduplicated SQL batch, audit/quarantine results and the existing reference
   card R2 generation/readback. A stale R2 publisher is a hold.
5. After approved figure references exist, test independent authenticated
   figure feed, private R2 sidecar publication and remote readback. Flags
   `TCG_REFERENCE_FIGURES_ENABLED`,
   `TCG_REFERENCE_FIGURES_R2_DELIVERY_ENABLED`,
   `TCG_REFERENCE_FIGURES_R2_PUBLISH_ENABLED` stay false until verified.
6. Test false-positive joins, parallels, stale/missing values, image rights,
   outages, R2 corruption, webhook replay and founder/consignor ownership.
7. Separately deploy FastAPI/App and Shopify integrations only after
   signed-in search, owned-stock matching, pricing and settlement tests.
   Never turn a canonical reference into a sellable physical item by default.

Rollback is an application-code revert with publication flags false; keep
additive schema/history. Do not delete market evidence, R2 objects, inventory,
owner data or audit logs.

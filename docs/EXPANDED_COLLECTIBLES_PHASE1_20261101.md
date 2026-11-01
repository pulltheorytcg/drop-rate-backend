# Expanded collectibles — phase 1, 1 November 2026

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
| Yu-Gi-Oh!, Lorcana, Riftbound | existing `tcg.reference_sets` + `tcg.reference_cards` | game + language + exact set + card number + rarity + print/finish/art treatment |
| Football, NFL, basketball, baseball, hockey, motorsport | existing `reference_cards` plus `reference_card_product_details` | manufacturer + season + series + athlete + printed number + parallel + autograph/numbering |
| Funko Pop! / other figurines | new `tcg.reference_figure_products` | manufacturer + official item/SKU or GTIN + franchise + series + figure number + edition/exclusive variant |

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
- **Market values**: use independently permitted, source-attributed UK sold
  transactions and condition/grade-specific evidence. Active listings are
  asking evidence only. Existing market-history records remain immutable.
  hobbyDB/Pop Price Guide may offer a negotiated API; it is *not* configured.
  TCGplayer's API terms restrict competing uses and data combination; do not
  add it to Drop Rate without specific permission.

## Code included in phase 1

1. Additive migration `20261101205040_collectible_catalogue_expansion.sql`
   registers six sports and two figure categories, typed sports-card attributes,
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

### Source pilot receipt (read-only)

YGOPRODeck `format=tcg` at offset 0, limit 100: **100 card objects**, **270
distinct printing candidates** in **133 sets**; **one card quarantined** for
set-code conflict. No DB write, image mirror, verified market price or Shopify
product was made. A separate 10-card read returned 17 candidates in 10 sets.
Neither result claims complete catalogue coverage.

## Production release gates

1. Run PR CI, all relevant new and old reference/R2/auth/Shopify tests, and
   review migration SQL. Use the canonical Supabase migration dry-run path.
2. Apply the migration through the existing reviewed deployment workflow;
   read back new categories, table RLS and no changes to original row counts.
3. In the configured admin worker, run YGO `--limit 25` **without** `--apply`,
   inspect quarantine report, then consider one ≤1,000-printing batch under
   capacity guard. Capture exact inserted identities and source counts.
4. Check existing card R2 generation parity after each accepted card import;
   a delayed publisher is a hold, not a reason to bypass the R2 checks.
5. Only after permitted figure metadata is available, enable the independent
   figure API/publisher, run readback and signed-in lookup comparisons. Feature
   flags default `false`: `TCG_REFERENCE_FIGURES_ENABLED`,
   `TCG_REFERENCE_FIGURES_R2_DELIVERY_ENABLED`,
   `TCG_REFERENCE_FIGURES_R2_PUBLISH_ENABLED`.
6. Test false-positive joins, parallel separation, expired/unknown values,
   missing artwork, provider outage, R2 corruption, stale generation,
   repeated imports, duplicate observations and cross-owner boundaries.
7. Do not enable figure Shopify listing, auto-publish, image mirroring or new
   pricing schedules until their separate rights, physical-media, shipping and
   pricing gates have been implemented and verified.

Rollback is a normal code revert and feature flags `false`; keep additive
schema/history intact. Do not delete provider history, R2 objects or owner data.

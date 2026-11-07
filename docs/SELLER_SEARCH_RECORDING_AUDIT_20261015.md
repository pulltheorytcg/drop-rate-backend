# Seller Hub search visibility / reference accuracy — 15 October 2026

## Source: founder's 20:40 iPhone recording

The four-minute screen capture shows:
- No obviously discoverable **Sort** command within the two-column card grid. The legacy implementation hides it behind a small three-line menu despite backend sorts already existing.
- Naruto → Sealed products returns the generic `No matches` message.
- Dragon Ball cards with identical names/printed numbers are repeated, often with different event/booster release labels, artwork and provider reference suffixes. They are not necessarily duplicate physical items.
- Several sought-after One Piece/Dragon Ball variants remain unpriced. Missing images occur; One Piece SAMPLE overlays are publisher preview art, not seller-owned photographic media.

## Live read-only fact checks (no inventory writes)

- **Naruto**: 4,487 Bandai Legacy + 2,679 Kayou card references, across 38 and 43 release groups respectively, but **zero** Naruto `reference_sealed_products` rows and **zero** Naruto canonical sealed/collection products. CardTrader sealed reference adapter currently covers Pokémon, One Piece and Dragon Ball only. Do not invent Naruto booster packs or create physical listings from card-set names.
- **Dragon Ball Fusion World**: 827 English and 757 Japanese groups sharing set/name/printed number (1,584 groups; 884 + 798 additional art rows) have **different image URLs within every group**. No repeated same image URL was found across current Fusion World/Masters references. Provider `_pN` IDs and event/reprint release identities are distinct; do not delete/merge or automatically reuse a base-card price.
- **Pokémon image URLs**: 1,780 English and 9,124 Japanese TCGdex references lack a source image URL (10,904 total). No `image_reference` field supplies an alternate provider asset for these rows. One Piece, Naruto and Dragon Ball current reference images are non-null, but successful browser delivery and copyright-provided SAMPLE overlays are a separate concern.
- **Prices**: English One Piece has 107 `SecretRare` and 497 `SuperRare` entries with no cached direct positive price, and 16 `SEC` / 75 `SR` abbreviated entries also unpriced. Fusion World `_pN` entries have no source-authenticated rarity, so they are not safe to map by number alone. This PR cannot recover their values without exact external source evidence.
- Pricing-reference baseline remains **40,443/67,060 = 60.31%**; Supabase Free storage at 405,499,027 bytes and `>=400MB` capacity guard defers full refresh. No paid provider or scraping is allowed.

## Changes and connections

1. **Visible Sort + Filters controls**: Both Seller Hub and Founder HQ share `catalogue-browser.js`. A compact, mobile-friendly row shows the active sort clearly, and a dedicated Filters button, without needing the overflow menu. Existing backend sort options are exposed. Add whitelisted, parameterized `name_desc` and `oldest` to complete A–Z/Z–A, latest/oldest, Card Number and GBP reference value high/low. Sorting is server-side across matching catalogue references **before pagination** (the value-sort path already resolves shared references before pagination). Unknown prices always sort last.
2. **Dragon Ball printing clarity**: For Bandai reference IDs ending `_pN`, show `Printing variant pN` alongside card number, language and *actual provider release name*. Retain each variant's independent key, image, original provider identity and price. No speculative grade/rarity or merging.
3. **Naruto sealed empty state**: For Naruto + Sealed + no matching verified records, explain that sealed references are not indexed yet and offer **Browse Naruto cards**; no fake products or inventory generated. Further Naruto sealed sourcing requires a permitted, exact original product feed with language, product type, edition, pack quantity and artwork.

## Failure risks and testing

- UI sort lost between filter updates, or applied only to loaded first 40 results → regression with clicked sheet and outbound API `sort` query, server pagination and whitelisted SQL order; no browser-only sort.
- Wrong value range inherited from another art/edition → no source-price/cache/SQL product identity mutations. Distinct Bandai variants still render separately; explicit blank price is preserved.
- Misleading empty sealed results → conditional only for the Naruto family when sealed is selected and no other filters; clickable switch returns Naruto CARD rows.
- iOS action cut-off → 44px controls, flexible width wrapping, existing narrow mobile and desktop browser checks.
- Operational safety → no database schema changes, migrations, provider calls, paid sources, scraped sites, stock/ownership/financial mutations. Keep Supabase bulk-price import guard active.

### Remaining real work (not falsely claimed as repaired by this UI release)
1. Acquire **free, authorised, exact** evidence for Naruto sealed packaging; do not transform card sets into fake sealed items.
2. Restore real imagery through permitted sources, prioritising the 10,904 Pokémon cards with absent image IDs; use only exact language/set/printing images. Validate actual HTTP display separately from presence of URL.
3. Recover verified valuable parallel/SR/SEC quotations; keep missing price as unpriced until provenance and edition are confirmed. No bought API or scraping.

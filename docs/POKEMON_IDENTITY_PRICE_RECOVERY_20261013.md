# Pokemon identity and numeric-level price recovery

The verified pre-release baseline is **35,152 / 69,538** priced references.
Earlier repairs in this session added **1,180** source-supported guides.
Revision 17 addresses two further causes without purchasing another feed.

## Numeric level labels

Cardmarket names older Pokemon using a printed level, such as `Metagross Lv.58`,
while the reference checklist omits that numeric metadata. Remove only a terminal
numeric `Lv.1`–`Lv.999` label after attack-description handling. Preserve `Lv.X`,
edition, number and variant suffixes. Matching still requires a complete official
checklist and exactly one name in both full release checklists; different cards
or printings cannot be chosen by price.

Actual source replay identifies **987** additional catalogue-cache matches but
only **612** newly priceable references in the shared reader: DP1 90, DP2 97,
DP3 113, DP4 87, DP5 59, DP6 99, DP7 63, PL2 1 and PL4 3. The other matches
already have a detailed-provider value and are not counted as new coverage.

## Existing CardTrader product-ID links

The revision-16 read-only probe completed at **17:29:42 UTC**, making ten requests
and zero price/mapping writes. The existing connection supplied collector numbers
and explicit singleton Cardmarket IDs. Verified identity candidates included 207
XY promos, 90 BW promos, 239 Scarlet & Violet cards and 210 Sword & Shield cards.
These are identity candidates, not additional-value claims. The source contract
is https://www.cardtrader.com/docs/api/full/reference.

Use that existing connection to identify currently missing English Pokemon cards
across complete released checklists. Exact full set title, game, card name,
collector number and reference-ID suffix must agree. The provider's single-card
category must also match. Count every numbered blueprint, including unpriced or
unmapped duplicates. Require a singleton explicit cross-ID, exact matching
Cardmarket single name/category, and one reference claim per source product.
Reject conflicts with the existing matcher and cross-release reuse of an ID.

CardTrader supplies identity only. Price amounts and dates continue to come from
the existing first-party Cardmarket guide with ECB GBP conversion. Each quote
preserves the original reference identity, source product, mapping IDs and number
proof. It remains a mixed-language estimate with physical valuation disabled.
The shared reference cache/history is reused, with no new schema, provider
subscription, service, owner, seller-price or Shopify changes.

No more than 400 release reads are allowed per pass, three concurrently, using
the existing eight-second request timeout. Bootstrap uses three API reads.
Digital releases, incomplete checklists and sets already covered by the existing
matcher/detailed guide avoid extra card requests. A provider failure stops later
batches, reports an incomplete result and preserves prior bridge quotes with
their original timestamps. Expired evidence remains expired; failures never
freshen data. The previous diagnostic probe is replaced by this working mapping
step, so its eight source reads are not repeated separately.

Regression coverage includes actual promo identity examples, complete-checklist
gates, same-name/different-number cards, collector-number prefixes/suffixes,
duplicate/unmapped prints, wrong regions/categories, contradictory product IDs,
cross-release conflicts, persistence and partial-provider outage preservation.
Require full current-head CI, Railway readiness, completed revision-17 source
receipts and source-aware production readback. The bridge's aggregate price gain
is unknown until that readback; do not add candidate counts to the priced total.

Rollback through the normal PR path preserves immutable price history. The
baseline inventory fingerprint remains `820fee0063fe48d9e4a774b4b9f98301`
over 613 items (327 valued), covering owner, identity, Store Price and status.

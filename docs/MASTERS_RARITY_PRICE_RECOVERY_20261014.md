# Masters rarity pricing recovery — 14 October 2026

## Problem and repair

The live overnight revision-20 refresh completed without provider failures, but 27,380 of 67,058 physical card references still lacked a supported GBP guide. Masters accounts for 4,586 of these records. Cardmarket's daily export gives some distinct printing products identical names and omits rarity, so the existing name-only adapter correctly refuses to choose one.

The existing authenticated CardTrader connection supplies explicit collector numbers, rarity and Cardmarket product IDs. For example, Beyond Generations has separate blueprints 282434 (Special Rare, `BT24-013`) and 282431 (Super Rare, `BT24-013sr`) for SS2 Vegeta, Charging Rage. The official checklist separately identifies `BT24-013_PR` as Special Rare and `BT24-013` as Super Rare. A provider suffix is not interpreted as the meaning or order of an alternate art.

Revision 21 adds a Masters booster identity adapter. It requires the exact official release title, an independently corroborated English Cardmarket expansion, explicit matching number and rarity, three-way name agreement, and exactly one Cardmarket product ID. All printings count in collision checks, including unpriced/unmapped prints and missing rarity. Leader faces remain with the existing dedicated adapter. Unknown same-name collector numbers block matching, and repeated or contradictory source IDs fail closed.

Prices still come from the dated first-party Cardmarket export with ECB conversion. Every newly recovered quote carries the CardTrader blueprint/expansion/number/rarity plus the original reference identity and dates. It is a mixed-language reference guide with `physical_valuation_eligible=false`, `physical_language_confirmed=false` and `condition_specific=false`.

The source is bounded to 80 booster releases per pass, three concurrent reads with a pause between batches, and no further batches after a provider failure. Failed and deferred releases preserve previous quotes and timestamps. The existing daily worker and credentials are reused. No new service, subscription, provider integration or schema is introduced.

## Validation and release status

Identity and refresh tests cover actual same-name SR/SPR records, bare numbers, reprints, duplicate references, unmapped duplicates, unknown rarity/number suffixes, cross-ID reuse, wrong games/categories/releases/languages, mismatched names/IDs, leader exclusion, dated provenance and outage preservation. The full local backend suite passed before publication.

Production acceptance is pending the exact-head CI checks, successful Railway deployment, revision-21 receipt, independent source-aware catalogue coverage, Seller Hub catalogue readback, and unchanged inventory owner/status/Store Price fingerprint. Candidate matches are not counted as recovered prices before live verification.

Predeployment stock baseline: 614 rows, 327 stored positive values; fingerprint `de5af2619bdfbc03127b64c179df03c5`, computed as `md5(string_agg(concat_ws('|',id,owner_id,status,store_price_minor),E'\n' order by id))`.

This repair is not a claim that every remaining game/language/parallel has eligible source data. Production counts and remaining requirements will be recorded after the refresh.

## Source contracts checked

- [CardTrader API reference](https://www.cardtrader.com/en/docs/api/full/reference): read-only game/category/expansion/blueprint exports and explicit Cardmarket IDs.
- [CardTrader Special Rare example](https://www.cardtrader.com/en/cards/282434-ss2-vegeta-charging-rage-special-rare-beyond-generations): public collector number, rarity and related Super Rare blueprint, checked 14 October 2026.
- Cardmarket's existing `products_singles_13.json`, `products_nonsingles_13.json` and `price_guide_13.json` download contract.

A public TCGTracking metadata sample was inspected during discovery. It is not used by the production adapter or as a price source; runtime matches must be corroborated directly by the existing CardTrader API.

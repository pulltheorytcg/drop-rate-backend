# Masters rarity pricing recovery — 14 October 2026

## Problem and repair

The live overnight revision-20 refresh completed without provider failures, but 27,380 of 67,058 physical card references still lacked a supported GBP guide. Masters accounts for 4,586 of these records. Cardmarket's daily export gives some distinct printing products identical names and omits rarity, so the existing name-only adapter correctly refuses to choose one.

The existing authenticated CardTrader connection supplies explicit collector numbers, rarity and Cardmarket product IDs. For example, Beyond Generations has separate blueprints 282434 (Special Rare, `BT24-013`) and 282431 (Super Rare, `BT24-013sr`) for SS2 Vegeta, Charging Rage. The official checklist separately identifies `BT24-013_PR` as Special Rare and `BT24-013` as Super Rare. A provider suffix is not interpreted as the meaning or order of an alternate art.

Revision 21 adds a Masters booster identity adapter. It requires the exact official release title, an independently corroborated English Cardmarket expansion, explicit matching number and rarity, three-way name agreement, and exactly one Cardmarket product ID. All printings count in collision checks, including unpriced/unmapped prints and missing rarity. Leader faces remain with the existing dedicated adapter. Unknown same-name collector numbers block matching, and repeated or contradictory source IDs fail closed.

Prices still come from the dated first-party Cardmarket export with ECB conversion. Every newly recovered quote carries the CardTrader blueprint/expansion/number/rarity plus the original reference identity and dates. It is a mixed-language reference guide with `physical_valuation_eligible=false`, `physical_language_confirmed=false` and `condition_specific=false`.

The source is bounded to 80 booster releases per pass, three concurrent reads with a pause between batches, and no further batches after a provider failure. Failed and deferred releases preserve previous quotes and timestamps. The existing daily worker and credentials are reused. No new service, subscription, provider integration or schema is introduced.

## Validation and release status

Identity and refresh tests cover actual same-name SR/SPR records, bare numbers, reprints, duplicate references, unmapped duplicates, unknown rarity/number suffixes, cross-ID reuse, wrong games/categories/releases/languages, mismatched names/IDs, leader exclusion, dated provenance and outage preservation. The full local backend suite passed before publication.

Revision 21 is verified live: **595 additional priced references**, increasing Masters from **4,416 to 5,011/9,002** and the full catalogue from **39,678 to 40,273/69,538**. Physical missing references fell from **27,380 to 26,785/67,058**. All other game/language counts were unchanged in this pass.

- PR #638, deployed code `5ef49b444586a6465abf527ce313dbab13344100`; all four applicable CI workflows passed; 5,839 local tests passed.
- Railway deployment `99efc609-d787-438d-8888-f8ca95f1b4ca`: SUCCESS. Live readiness HTTP 200, database connected.
- Revision 21 COMPLETE at **2026-10-14 06:37:01.450618 UTC**. The identity adapter checked 31 booster releases with 34 requests, zero failures and zero cross-source/cross-release conflicts. 3,393 identities included previously covered cards; **595** were actual newly priced recoveries.
- The shared Seller Hub catalogue query returns SS2 Vegeta `BT24-013` Super Rare at **£0.17**, and `BT24-013_PR` Special Rare at **£12.17**, with distinct product IDs 762000 / 762001 and the original Cardmarket evidence date **2026-10-14 00:53:42 UTC**.
- Post-deployment inventory remains **614 / 327 stored positive values**, with the same owner/status/Store Price fingerprint below. These are catalogue reference guides, not newly verified valuations of particular physical copies.

Predeployment stock baseline: 614 rows, 327 stored positive values; fingerprint `de5af2619bdfbc03127b64c179df03c5`, computed as `md5(string_agg(concat_ws('|',id,owner_id,status,store_price_minor),E'\n' order by id))`.

## Revision 22 extension — production acceptance pending

Two-sided leader prints use both exact official filename/image identities, matching number/rarity, and the ordered full front/back names. Each quote retains both face IDs. CardTrader sometimes publishes a generic `Leader` type as rarity while its version explicitly says `Special Leader Rare`; only this exact documented combination establishes SLR. The `slr` number suffix never supplies rarity. A duplicated Collector Booster Foil printing still blocks its own rarity, even if it has no price or cross-ID.

Product claims are counted per paired printing, not per face; cross-source conflicts reject both faces. Existing ordinary guides retain their prior basis. Rarity changes invalidate these guides immediately in shared catalogue coverage, Seller Hub search and recognition, and block stale in-flight writes. The full local suite passes with the added leader cases (5,854 tests); real PostgreSQL CI also exercises rarity correction and the write/read guards before deployment.

The first PostgreSQL check exposed a related search bug: an official Masters parallel such as `BT24-013_PR` was excluded from an exact printed-number query `BT24 013`. Search now includes all exact-number Masters `_PR` printings while retaining their separate identities and values. Other games and different numbers remain excluded. PostgreSQL tests cover spaced, hyphenated, compact and name searches, plus value sorting and the adjacent-number negative case.

This repair is not a claim that every remaining game/language/parallel has eligible source data. Final production counts and remaining requirements will be recorded after the revision-22 refresh.

## Source contracts checked

- [CardTrader API reference](https://www.cardtrader.com/en/docs/api/full/reference): read-only game/category/expansion/blueprint exports and explicit Cardmarket IDs.
- [CardTrader Special Rare example](https://www.cardtrader.com/en/cards/282434-ss2-vegeta-charging-rage-special-rare-beyond-generations): public collector number, rarity and related Super Rare blueprint, checked 14 October 2026.
- Cardmarket's existing `products_singles_13.json`, `products_nonsingles_13.json` and `price_guide_13.json` download contract.

A public TCGTracking metadata sample was inspected during discovery. It is not used by the production adapter or as a price source; runtime matches must be corroborated directly by the existing CardTrader API.

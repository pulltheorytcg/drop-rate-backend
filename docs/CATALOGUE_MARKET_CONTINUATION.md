# Catalogue market continuation — 10 October 2026

## Handoff verified

The latest work chat left starter matching deploying and the detailed refresh incomplete. PR #566 deployed successfully as `2267946c8c3cc73e42113cab0f5eef1460f74e46`; Railway deployment `d6001a3d-c949-4254-8f10-8df8b347aa4c` reached SUCCESS. Its revision-6 reference receipt completed at 12:53:20 UTC without provider failures.

The 12:53:54 coverage receipt reports 29,851 priced card references out of 69,538, plus 2,725 priced sealed references out of 3,879. All references have identifying/source fields. These figures are independent of the 510 physical items (324 with market values). The last healthy Shopify heartbeat found no publication or selling-price candidates. A separate database comparison found no difference between linked recorded Shopify prices and approved inventory Store Prices; this alone is not a fresh remote Shopify read-back.

The user's agreed policy remains: refresh the whole reference database daily; synchronise approved For Sale stock promptly; preserve seller asking prices. Market values and seller Store Prices are separate. The Brand Redesign launch hold remains in place.

## Defects and repair

Dragon Ball Masters' official `Series 1` through `Series 9` booster titles failed a parser that accepted only letter/number prefixes. Later releases frequently have no Cardmarket `DBS Set` product even though ordinary booster/box products explicitly identify their expansion. Both omissions prevent trustworthy existing guides from reaching the shared catalogue.

The repair accepts the actual numbered booster-title form and identifies expansions from full ordinary booster/box titles and matching category IDs. Regional, collector, release-event and prerelease qualifiers are retained; they cannot silently become base releases. Every source identifying the same release participates in ambiguity detection, so contradictory expansion IDs block a match.

Fusion World supplemental references use explicit `MANGA BOOSTER NN [SBNN]` / `STORY BOOSTER NN [STNN]` labels with agreeing numbers and the provider's `[Fusion World]` marker. Single-card collector numbers must match exactly. Multiple cards or marketplace products, including unpriced candidates, still block a match. Supplemental and starter guides remain excluded from physical-copy valuations because finishes/reprints require their own evidence.

The coverage query previously counted bulk guides after an identity change even though the browser correctly hid them. It now applies the same identity check while retaining the record in the full denominator.

Reference revision 7 runs through the existing worker. Existing detailed Pokémon checks are reused; no cache reset or new worker is needed. Source dates, EUR/ECB provenance, immutable history, physical-copy safeguards, owner boundaries, seller prices and Shopify approval rules remain intact.

## Read-only replay

Replay inputs: all 17,889 English One Piece/Dragon Ball reference rows and Cardmarket's own game-13/game-18 singles, non-singles and price-guide exports. The Dragon Ball guide is dated `2026-10-10T02:49:01+02:00`; ECB conversion is 0.84763 GBP/EUR effective 9 October. The replay invokes the actual matcher and quote normaliser without writing the database.

| Reference group | Previous matches | Repaired matches | Additional priced references |
|---|---:|---:|---:|
| Dragon Ball Masters | 1,210 | 2,797 | 1,587 |
| Dragon Ball Fusion World | 631 | 730 | 99 |
| Total Dragon Ball | 1,841 | 3,527 | 1,686 |

Every prior match retains its marketplace product ID. All 1,686 additional matches have usable current GBP guides. The 99 supplemental guides are 52 Manga Booster 01 and 47 Manga Booster 02 references. Story Booster parsing is tested but no recovered live Story Booster guide is claimed.

Example: Manga Booster 01 Son Gohan : Childhood, official printing `583201:FB01-088_p2`, collector `FB01-088`, maps to Cardmarket product `831639`, expansion `6171`, foil trend EUR 0.05 / GBP 0.04. This is a labelled mixed-language reference, not an English Near Mint sold transaction or an instruction to sell at that amount.

## Validation and remaining gates

Local verification passed 4,995 backend tests and every dashboard suite, including 39 catalogue interaction scenarios. Added regressions cover numbered releases, packaging category errors, contradictory expansions, collectors/regional/event packs, supplemental code mismatches, wrong numbers, wrong games, duplicate/unpriced alternatives and physical-copy exclusions. The actual PostgreSQL maintenance test now verifies that an identity-changed guide disappears from both displayed price and priced coverage without removing the reference.

Before calling this release complete: require all checks on the exact PR head (including real PostgreSQL), observe Railway SUCCESS and readiness, read the revision-7 receipt and final coverage, compare owner/Store Price/status fields, verify unchanged prior market amounts and confirm Shopify processing. No signed-in real-iPhone acceptance has been performed during this continuation.

Large coverage gaps remain in ambiguous parallel/promo printings, Japanese One Piece/Fusion World and Naruto without a supported exact-source mapping. Digital Pokémon Pocket records are not physical cash-market cards. The eBay sold-feed quota is still an independent constraint. None of these is reported as zero value or as complete coverage.

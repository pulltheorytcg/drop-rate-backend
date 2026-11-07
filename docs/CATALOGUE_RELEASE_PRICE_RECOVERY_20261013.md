# Catalogue price recovery, 13 October 2026

The live baseline for this continuation is **33,972 / 69,538** references with a
positive GBP value or labelled source guide; **35,566** have none. Previous work
through PR #625 is already deployed. These counts include reference guides,
not solely exact-condition or independently verified sold valuations.

## Fix and connections

The existing daily Cardmarket import rejected real prices because release titles
differ between the official checklists and marketplace products. Add exact,
scoped aliases for the 16 Pokemon EX releases and five Dragon Ball release title
discrepancies. One Piece PRB01/02 have no marketplace Lots export rows; their
unambiguous full English booster/box names supply release identity instead.

These changes reuse the existing downloads, ECB FX, source quote tables, immutable
history and account-independent readers. Revision 14 triggers the normal worker.
No new service, paid provider, schema, owner, asking price, settlement or Shopify
publication changes. Newly recovered aliases/premium references cannot enter the
physical valuation fallback: their distinct match basis is not accepted there.

## Actual read-only replay

Replay used full current database checklists (23,770 English Pokemon, 13,362 English
Dragon Ball, 9,007 bilingual One Piece references), Cardmarket product exports
dated 13 October, source guides dated 12 October and ECB EUR/GBP **0.84478**.

| Family | Newly priceable references | Principal releases |
|---|---:|---|
| Pokemon | 416 | EX-era releases, principally EX11-16 |
| Dragon Ball | 300 | BT24: 68; BT25: 104; BT31: 124; The Awaking: 4 |
| One Piece | 42 | PRB01: 6; PRB02: 36 |
| Total | **758** | Expected source-supported candidates, pending live readback |

The updated Pokemon catalogue importer matches 10,458 total guides, up from
9,258, but **only 416** were previously unpriced in the combined shared reader.
Counting all 1,200 extra cache rows as newly valued cards would overstate progress.
Dragon Ball guide candidates include foil fields, not just normal trends.

TCGdex also confirms 15 `tcgp` digital releases containing **2,480** existing
references. They remain in the 69,538 total and are not counted as newly priced.
Coverage now explicitly reports `NOT_APPLICABLE_DIGITAL`, `non_physical_cards`
and a separate `physical_cards` total. ID and full provider title must agree;
missing artwork is supported, and broad A/B-prefix guessing is not used.
Source: https://tcgdex.dev/tcg-pocket and its `/v2/en/series/tcgp` response.

## Failure handling and acceptance

- Match exact provider/game/language/release. Preserve original identity in quotes.
- Multiple source expansions (including original vs alias disagreements), multiple
  cards/printings or duplicate market products still block a price.
- Regional packs, cases, promo packs and arbitrary title similarities do not match.
- Source outages preserve prior evidence; no fabricated floors, root-level
  TCGdex fallback, alternate-print borrowing, or owner-specific source values.
- Unit regressions exercise each alias, duplicate/region/language collisions and
  explicit N/A classification. Existing real PostgreSQL CI checks shared reads,
  immutable history, identity races and RLS; digital classification is also tested
  against actual SQL including a null-artwork reference and a wrong-title case.
- Before release: 613 physical inventory items, 327 valued; MD5 of ordered
  `[id, owner_id, catalogue_id, store_price_minor, status, sale_intent]` JSON arrays:
  `820fee0063fe48d9e4a774b4b9f98301`. Verify unchanged after the worker completes.
- Require full current-head CI, Railway terminal SUCCESS, revision 14 COMPLETE
  with no provider failures and live readback. The 758 are **not** a deployment
  claim. Revert the PR to roll back code; preserve historical observations.

## Remaining scope

This does not complete the user's requirement for all physical cards. Naruto
Bandai/Kayou (7,166 references) still lack a connected permitted quote feed and
verified language. Other gaps include independently unresolved alternate prints,
regional quotes and genuine upstream absence. Paid access or licensing has not
been purchased, and no absent value is presented as zero or inferred by AI.

## Verified release receipt

PR #627 merged as `99f8a18564df969deb3f8f93ce05dcc0f6788b3d`. All four
current-head GitHub workflows passed. Railway deployment
`02253a7a-5418-4d2c-a69e-8c0fbcf649ee` is SUCCESS; pre-deploy ran 5,658 tests
and `/health/ready` returned `ready` with a connected database. Revision 14
finished COMPLETE at **17:05:55 UTC**, with no provider failures.

Independent source-aware database readback confirms **34,730 / 69,538** card
references priced, an actual gain of **758**. There are **32,328** unpriced
physical references and **2,480** digital references. The original 613 physical
inventory items, 327 valued count and ownership/Store Price fingerprint above
are unchanged. These are reference-guide gains, not new sold-price valuations.

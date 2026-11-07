# Seller Hub manual-search valuation consistency — 12 October 2026

## Intent
Every authenticated founder and seller sees the same **stored GBP catalogue market reference** for the same exact printing/language/price basis. Ownership, acquisition costs, asking prices and settlement amounts remain completely separate. No price is invented for a card without an eligible source. The shared reference library has 69,538 cards; the verified audit found 31,537 with a positive GBP price or broad guide, with major unmapped-language/provider gaps.

## Corrected existing read paths
- The founder/owner canonical correction search now uses the same `tcg.catalogue_reference_value_v2` selector as the shared catalogue browser and scanner, rather than the older sold-only helper.
- For cards that exist only in the provider reference library, manual correction checks `reference_market_prices` and `reference_catalogue_prices`. Only exact provider+system+language+printing keys and a fresh, supported GBP source are accepted. Bulk catalogue quotes additionally require the full name/set/card number evidence to match.
- A verified provider-to-canonical link can reuse the same canonical valuation snapshot; a REVIEW/REJECTED/unlinked mapping cannot infer another copy's value.
- A broad Cardmarket or TCGdex value is visibly labelled **Shared guide**, not an exact graded/condition-specific valuation. A null quote remains unavailable, never £0. No automatic recommended retail price is calculated for an unmaterialized reference.
- Results require an owner-authorised recognition run before reference-library search; no other owner's inventory or price is queried. The scanner's existing reviewed materialisation and publication gates remain.

## Verification
- Backend tests cover source and identity checks, separate owners receiving identical quote/missing responses, unchanged admission fields and no user-supplied owner query values.
- The existing real PostgreSQL and restricted-auth/RLS tests, asset-version tests, and dashboard/mobile suites remain the release gates.
- The only data reads are existing sources. No migrations, data/provider writes, new provider, worker, n8n flow, Railway service, Shopify publication or finance/ownership changes.

## Not solved here
This is a **consistency and presentation repair**. It does not manufacture values for 38,001 currently unpriced card references. Japanese One Piece, Japanese Fusion World and both Naruto libraries still need licensed/permitted exact-price evidence, and some Pokémon/English references are ambiguous, unpriced or excluded. Current per-copy reference values require condition/grade matching; raw guides cannot price slabs. This change does not rebuild historical financial or market observation data.

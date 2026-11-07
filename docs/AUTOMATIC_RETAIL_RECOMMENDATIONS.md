# Automatic retail recommendations and portfolio coverage

## Purpose
The owner overview previously combined saved asking prices and old per-copy recommendation caches. The #609 shared-data selector fixed market values but did not select the matching recommended-retail output. A collection could therefore show a current shared market total alongside a very small total labelled as if it represented all store recommendations.

This correction reuses the current pricing algorithm's existing immutable shared snapshot. It does not introduce a new pricing algorithm, another price table, a provider integration, or a manually maintained owner-specific reference value.

## Data and user contract
- A current market value and its recommended retail come from the **same** eligible catalogue snapshot. Exact current printing identity, language, raw condition or grading company/grade, and sealed profile remain enforced.
- Existing freshness, source-validation, guide and mapping-revocation checks remain intact. A missing, invalid, stale or incompatible recommendation stays unavailable. Stored private asking prices and old per-copy caches are not fallbacks for a reference recommendation.
- The response-only recommended_retail_minor is refreshed from this shared snapshot, without writing inventory. Every authorized physical copy contributes once to the recommended total; coverage reports how many active copies have suitable recommendations.
- The overview's **Recommended retail** tile uses active_recommended_retail_minor, active_recommended_count and active_inventory_count. A nonempty unpriced collection says Unavailable; an empty collection may show zero. Guide-estimate counts remain explicit.
- **Saved asking prices** are shown separately with their own count and total. They are not described as live marketplace prices or mixed into the recommendation total. Legacy mixed aggregate fields are retained for API compatibility but are no longer the current overview tile's input.
- Details display the current automatic recommendation. An empty selling-price field may be prefilled from eligible current evidence. An existing chosen price is not overwritten. Opening the item or disclosure does not save, approve, publish or change sale intent.
- Changing raw condition clears an untouched automatically suggested price when its evidence no longer applies. A user-entered or previously saved asking price is preserved, with a condition-basis warning.

## Actual algorithm and automation
The existing drop-rate-market-v4 implementation is in pricing_engine.py, with exact sold selection in live_market_refresh.py and catalogue_valuations.py. It uses comparable physical profiles, recency/source weighting, robust median/outlier treatment and deterministic retail rules. The current default retail multiplier is 1.0 with the existing GBP 1.00 minimum listing price. An evidenced market guide below that floor remains its actual small reference value; only the recommendation uses the retail floor. Missing market evidence must never be assigned the floor merely to fill a blank.

The already-scheduled CATALOGUE_VALUES, REFERENCE_PRICES and CARDMARKET_VALUES jobs were confirmed completed on 12 October 2026. CATALOGUE_VALUES recalculates stored permitted evidence; it is not itself a new provider search. Daily job completion does not mean every exact printing has adequate or current evidence. The new view picks up newly eligible snapshots on subsequent reads; no new per-item price job or real-time browser subscription is introduced.

Automatic recommendations are separate from automatically altering chosen or published prices. This release does not enable auto-repricing, create owner policies, publish personal collection stock, or change Shopify/channel settings. Insufficient evidence, permitted-source coverage and upstream provider limits remain separate work.

## Security, testing and release
Callers still authorize physical rows before shared enrichment. The lookup is shared by reference identity, not by borrowing another owner's inventory cache. Cost, stored asking price, ownership, sale intent, historical snapshots and financial records remain unchanged. No production migration or backfill is required. #607 shared image transport, #608 collection-first admission and #609 reference selection remain supported.

Verification includes pure recommendation-provenance/null/stale tests; real restricted-role PostgreSQL and signed local-JWKS HTTP with 99-copy partial coverage, two owners and unchanged state after repeated reads; and actual overview/detail JavaScript in Chromium/WebKit using synthetic responses. Current page readback checks served bytes against reviewed source versions, readiness and anonymous denial. Synthetic auth/provider/browser data is not a normal production login or live sale. Exact-head CI and deployment evidence must be recorded separately in the PR release-verification comment.

Rollback is a reviewed application-code revert. Do not reverse historical records or change personal collection sale intent; there is no database rollback for this display/read correction.

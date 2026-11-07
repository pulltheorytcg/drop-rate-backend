# Shared inventory artwork and market evidence

## What changed
Both founder and seller inventory now resolve their current reference value and approved artwork through the same read-only FastAPI functions. Existing PostgreSQL catalogue identities, market snapshots and media records remain authoritative. No new database, provider, per-owner image copy, scheduled worker or migration is introduced.

The response lookup key is exact catalogue identity/printing plus language, raw condition or grading company/grade, and seal state. Owner access selects the physical copies a caller may see; it does not change the standard artwork or reference value. Acquisition cost, seller's store price, historical financial/pricing records and physical-copy ownership remain separate and unchanged.

## Market evidence
`inventory_reference_values.py` batches existing `catalogue_market_snapshots`, validating the current identity digest, method, physical basis, source mapping, original evidence timestamp and existing Cardmarket reference-current function. It never borrows another owner's inventory price, writes `inventory_items`, calls a provider on page load or causes Shopify publication.

Current per-item response values, seller home totals/top holdings, founder inventory market column/intelligence totals/top holdings and founder Business ownership views use the same selector. Current totals count physical RECORDS and explicitly report missing coverage; known cross-account duplicates are not implicitly reconciled. Reserved-stock inclusion retains each existing view's scope. No price is shown as zero because evidence is absent. Guide estimates remain labelled and counted; stale evidence is not reported as current.

States: AVAILABLE (matching supported sold basis), REFERENCE_ESTIMATE (eligible ungraded guide, not an exact-copy price), STALE (last evidence outside existing freshness limits), NEEDS_DETAILS, UNAVAILABLE. Original provider check time is shown; recalculating an old observation does not refresh it. Raw guides never substitute for slabs, sealed or worn raw stock. The normal exact sold path retains the five-comparable, GBP/UK, seven-day check and 90-day sale-age contract established by the existing snapshot writer.

Historical weekly-mover charts and immutable per-item pricing/financial snapshots are not rebuilt by this release. They retain their historical scope. This is a current-reference consistency fix, not universal catalogue price coverage or a new automatic pricing refresh scheduler.

## Images
`inventory_reference_media.py` is shared by the lists, details and authenticated image route. Approved catalogue art is selected independently of uploader owner; exact language/variant, rights and source state still apply. Pending catalogue artwork belongs in review tools rather than appearing as an uploader-only standard image. Pending/approved physical photographs remain visible only on their actual owner's physical item.

The common image route falls back to the existing exact reference-library resolver when no approved primary image is usable. No guess by name/card number, unconditional pending approval, untrusted redirect, publication permission or foreign slab photograph is introduced. Frontend direct sources keep the existing strict HTTPS/CDN allowlist; private proxies keep authentication, private/no-store and bounded fetch rules.

Some records genuinely have no resolved exact reference. The earlier PRB02 Bonney artwork used an OP07 base URL while the reference library contains a distinct PRB02 printing. P-001 also has several distinct printings. This patch must not mark those unresolved mappings verified or show a different printing simply to remove a placeholder. Catalogue-level correction after exact evidence review is still required; no image/provider mapping or Shopify media was mutated here.

## Tests and rollout
Pure selection tests cover cross-owner determinism, raw/graded/sealed, stale/future evidence, missing values, invalid source/identity/profile and guide labelling. Real PostgreSQL tests apply the existing market/media migrations and use restricted-role RLS with signed local-JWKS HTTP. They verify founder/seller equality, privacy, revoked access/maps, canonical-identity changes, pending art and unchanged stock/prices/history after reads. Outbound image bytes and the local issuer are fixtures, not a real production login.

Browser tests run actual seller detail and founder market-column code in Chromium and WebKit with synthetic responses across mobile/desktop and all five data states. Existing shared-image, import, collection, Business and seller persistence suites remain relevant regressions. Production GET-only readback verifies exact bundles/entrypoints, readiness and anonymous denial. A real signed-in production/device check is separate; no user's inventory is modified to manufacture it.

BUILD_STATUS records the feature; exact commit/checks/deployment, coverage measurements and remaining evidence gaps belong in the PR release-verification comment. Rollback is a reviewed code revert only. No historical valuation, balance, ownership, sale intent, pending import or Shopify data is backfilled.

# Live eBay UK market refresh — 9 October 2026

The founder requested every inventory market value be refreshed through the existing sold-market algorithm. The old five-sold batch only selected missing **Store Price**, leaving already-priced inventory on imported/floor snapshots. Catalogue references also read historical snapshots rather than the current one.

## Repair

- An opt-in task in the existing API service groups all active inventory by exact canonical and physical identity. Identical copies share a lookup, including across owners; each copy retains its owner and gets its own immutable pricing snapshot.
- Uses the existing Trawl `EBAY_GB`/GBP sold endpoint, at most one page for cards and two for an already verified booster pack. Five distinct exact sales in the past 90 days are required. The existing `drop-rate-market-v4` engine computes the value from those five observations, with its recency weighting, outlier checks and confidence rules. Shipping is recorded separately.
- Name, contiguous collector number, physical language, finish, condition, grade/company and special-print markers are checked. Unknown product types, unverified sealed types, ambiguous/missing print details and fewer than five sales remain pending. No new source mappings or identity approvals are made.
- Manual eBay pricing and stored-observation recalculation also use the same five-sale v4 policy; Cardmarket/reference imports cannot silently take over a current inventory valuation.
- Weekly movers require both the current and historical value to have a v4 eBay-backed snapshot with at least five sales, belonging to the same owner and catalogue product. Imported/floor/reference baselines cannot produce apparent gains or losses during the backfill. Until comparable history exists, weekly movement stays unavailable.
- Provider calls occur outside transactions. A session advisory lock prevents concurrent passes; writes recheck owner, version, physical identity and status. Sold/withdrawn/reserved items are not repriced. Current selling prices, Shopify listings, publication, ownership and finance are untouched.
- Imported/price-floor reference values are retired from the live market fields only when a historical snapshot exists to preserve them. No snapshot or observation is deleted. A successful exact-sold value updates market value and recommendation, never Store Price. The catalogue helper only exposes the current eBay-backed snapshot, preventing old imported prices from reappearing. Cardmarket browse-only values are explicitly labelled `Reference`.

## Operation and limits

`TCG_EBAY_MARKET_REFRESH_ENABLED` defaults false. `TCG_EBAY_MARKET_REFRESH_ACTOR_USER_ID` must be an active, authorized founder; verified again before writes. `TCG_EBAY_MARKET_REFRESH_MAX_GROUPS` defaults 500 (maximum 1,000); the pass scans at most 2,000 active copies. No new Railway service or n8n workflow.

The immutable `market_ingestion_runs` journal records the identity key, affected copies, exact comp count, updated/skipped counts, public provider credit metadata and next check time. Successful groups are due after 24 hours, insufficient/unsupported groups after 72 hours. The hourly loop resumes due groups after restarts without re-requesting recently checked groups. A provider/auth/quota error stops the pass and is durably recorded; no silent retry storm or paid upgrade. `429` pauses for 24 hours; other provider errors pause one hour. Free credit capacity may prevent a complete collection pass; this must be reported as partial coverage, not success.

The global multi-provider ingestion switch stays off. This task is narrowly enabled for the explicitly requested eBay valuation repair. It is independent of selling-price approval and cannot publish a price.

Provider contract checked against https://trawl.dev/docs on 9 October: successful responses include public credit headers; empty results are free, pages are charged against the existing account allowance, and `429` covers rate/credit limits. No credentials or raw responses are logged.

The first production pass confirmed the current account has a **250-credit monthly allowance**, with 228 remaining after ten identities (three updated, seven pending). Identical search requests across different finishes are now reused within one bounded pass; each finish still requires its own five matching sales. Cache hits record zero new credits. This cache expires at the end of the pass and never changes product matching or freshness.

The full production pass is enabled at a 500-group limit. Railway app sleeping is disabled on the existing API service so its hourly check loop can run between browser visits; no additional service or provider plan was purchased. Refreshes remain subject to the sold-data allowance and exact-comparable gates.

## Validation and rollback

Unit tests exercise exact printing/grade/language/bundle exclusions, future/stale records, use of v4 rather than an average, immutable provenance, copy deduplication and changed-inventory exclusion. Existing pricing tests and full backend suite must pass; release evidence belongs on the PR. Live verification must include persisted observations/snapshots and counts, not merely a healthy deployment.

Disable `TCG_EBAY_MARKET_REFRESH_ENABLED` to stop future passes. Previous snapshots remain available for an explicitly reviewed restoration; do not relabel imported prices as live eBay values. Revert application code and the reference helper independently if necessary. No blanket rollback update of inventory or financial history.

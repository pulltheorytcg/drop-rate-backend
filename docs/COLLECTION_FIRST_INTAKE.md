# Collection-first intake and explicit selling

## Scope and current evidence
User decision, 11 October 2026: scan the exact card/set/printing/language or slab, confirm once, and immediately see the physical copy in inventory. Saving is not publication. This note describes the implementation on its review branch; exact-head tests, merged commit, deployment, and production readback are recorded separately in the PR release comment. Do not call this complete merely because the document exists.

## Behaviour
- The existing scanner detail action is **Confirm & add**. It saves only the selected confirmed item, including its requested number of raw/sealed copies. Other uncertain scans do not block it. Batch confirmation saves eligible selections; rejected/conflicting identities stay in review. Matching thresholds and AI/certificate verification claims are not broadened by this change.
- Raw condition can be unknown while collecting. A supplied condition must remain valid and cannot coexist with slab fields. Sealed type and slab/certificate details retain their existing identity/physical constraints.
- Newly admitted scanner/manual/CSV copies explicitly start **DRAFT / PERSONAL_COLLECTION**, including verified sealed identities. Defaults no longer implicitly opt a collection into selling. Every physical copy retains its own ID, owner and source/retry history.
- Owner recognition admission obtains normalized language from the selected catalogue printing and rejects conflicting language. It does not guess an unknown language or alter the shared catalogue.
- Pricing is no longer awaited inside scan-admission transactions. Missing cost, price or valuation does not prevent collection admission. Valuation remains unavailable until established through the existing refresh path; no new background refresh job is promised or introduced.
- Owner/request advisory locks serialize concurrent retries before their receipt lookup. Saved successful items retain their response; failed/ambiguous requests retry the same key/body. Changing an idempotent payload is rejected. Existing slab certificate uniqueness applies across owners without exposing foreign holdings.

## Optional selling
The existing inventory details now contain a **List for sale** disclosure. Viewing/opening it does not change inventory or contact a marketplace. Existing listed/inspection items keep their management panel open. The seller supplies price and, for an ungraded Draft/Inspection card, condition here rather than needing it to save a collection.

The explicit existing approval-request operation can record condition and selling intent atomically with optimistic version checks. Unknown raw condition returns an actionable message while the existing inventory stays saved. Grade/seal conflicts, changing approved stock's condition, stale versions and foreign items remain blocked. Merely saving a proposed price preserves collection intent.

This is not a universal auto-approval release. Raw/slab selling review, current Near Mint selling scope, physical-photo/rights rules, acquisition/location completeness and deterministic publication checks remain. Eligible seller-held sealed items retain the previously authorised explicit Shopify listing route. Ready/approved stock must still pass actual channel checks; a saved selling request is not reported as published.

The existing explicit eBay consignor/sealed restrictions stay in place. Whatnot is labelled unavailable in this workflow; no connector is activated or tested by this release. Reassessing native-channel support is separate work, not a new seller connection added here.

## Existing data and safety
No existing import, Inventory ID, ownership, sale intent, finance, media record or Shopify link is backfilled. In particular, the previously overlapping founder/seller collection is not reconciled, imported again or published. Its explicit hold and duplicate-copy reconciliation remain separate work; this patch must not be used to claim they happened. Replays of an old saved receipt report the old saved state, not a fabricated personal-collection state.

No migration, membership changes, new Railway service or n8n workflow is required. Do not relax database guards/RLS or switch live channel flags. The patch preserves shared artwork delivery from #607.

## Tests and definition of done
- Actual scanner code in Chromium/WebKit: seller/founder raw/graded/sealed, missing condition/value, one-step independent save, unresolved neighbour, retry key/body preservation, mobile viewport and no price/sync requests. API responses are synthetic; this does not demonstrate camera accuracy.
- Signed JWT HTTP tests with a local test issuer and real restricted-role PostgreSQL: actual production physical-state migrations, optional values, canonical language conflicts, rejected candidate/foreign owner/expired/revoked sessions, concurrent replays, global graded-cert uniqueness, founder manual intake and absence of external listing or ledger writes. Certificate provider is stubbed; this is not a real Supabase user sign-in.
- Existing seller/import/DOM regressions and owner condition-on-selling transaction checks must remain green. No test is removed to meet the new behaviour.
- Read back the exact deployed scanner and owner-image assets, versioned owner entry, database readiness and anonymous denial. This is necessary but not sufficient for real-device acceptance.
- Physical-phone scan-to-saved-item and authorised real listing timing remain separate acceptance evidence under Phase 2 Manual section 2. Never create live stock or publish a listing just to manufacture that evidence.

Rollback: revert the application patch through a reviewed PR. New PERSONAL_COLLECTION records must stay personal; rolling back code does not authorize changing their intent. No database rollback or deletion is needed.

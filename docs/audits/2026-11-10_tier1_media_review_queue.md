# Drop Rate — Tier 1 media exceptions into the founder Action Required queue

**Recorded:** 10 November 2026, UTC. **Scope:** production Supabase `ozrxenrdladkooixutmm`, existing owner-scoped Action Required workflow, and Founders HQ at `/founders`. **No change** to product media, Market Values, ownership, store prices, R2 objects, Shopify, D1 or settlement funds.

## What and why

The first actual R2 byte audit (Railway deployment `bc923f69-c572-4b1a-89e3-819d4b8a37e9`) checked 100 physical CARD/SEALED items. 90 passed byte/SHA/size/pixel checks, but **none** received visual exact-identity certification. Of ten exceptions, one graded slab already had an open Action Required task; the other nine had no open media task and therefore no review assignment.

We recorded **nine owner-scoped, idempotent, high-priority Action Required items**, keyed by `TIER1_R2_AUDIT_20261110:<Inventory ID>`, with a human-review-only recommendation. An existing queue entry for the PSA 10 Swinub remains untouched, so **all ten** audited exceptions have open tasks. New action rows use `entity_type=INVENTORY_ITEM`, `owner_id=inventory_items.owner_id`; all 10 inventory items are APPROVED, Shopify PUBLISHED, and have an active owner membership. **No owner was reassigned.**

## Reconciled exceptions and human action

| Physical item / game | Audit exception | Human remediation |
|---|---|---|
| Charmeleon 012/094, Pokémon | Canonical image PENDING | Verify English reverse-holo exact printing and media rights before approving |
| Goomy 064/083, Pokémon | Canonical image PENDING | Verify Japanese variant/rights or capture authorised card photo |
| Mega Manectric 032/063, Pokémon | Canonical image PENDING | Verify Japanese holo printing/rights |
| Oricorio ex 018/094, Pokémon | Canonical image PENDING | Verify English holo printing/rights |
| Terapagos ex 630/742, Pokémon | Canonical image PENDING | Verify Japanese card/finish/rights |
| Latias ex 312/742, Pokémon | Approved canonical source marked DEAD | Replace dead URL using approved rights-cleared source or a physical photo; no placeholder |
| Vegeta BT18-035, Dragon Ball Super | CardTrader reference excluded from canonical R2 mirroring policy | Take permitted first-party photograph or obtain explicitly licensed exact-match artwork |
| Tien Shinhan FP-045, Fusion World | CardTrader reference excluded from canonical R2 mirroring policy | Take permitted first-party photograph or obtain explicitly licensed exact-match artwork |
| Trunks BT13-131, Dragon Ball Super | Existing R2 WebP below 350px minimum | Obtain higher-resolution approved exact-print image; do not upscale |
| Swinub 106/100 PSA 10, Pokémon | No verified inventory-specific slab R2 image; **already has queue task** | Photograph physical slab **front and back** and approve first-party photos; raw-card art is not a slab photo |

None of these nine received automatic image approval. Catalogue source `rights_status=VERIFIED` is not a substitute for human exact-card/variant approval, and `INTERNAL_REFERENCE_ONLY`/CardTrader listing media are not automatically eligible for Shopify or R2 storefront reproduction.

## Production data receipt

- Read-only target preflight: **9 of 9** unqueued exceptions were APPROVED, Shopify PUBLISHED, owner-membership active, and still matched their exact source/approval/mirror predicates; zero prior open media exceptions on those nine.
- One guarded `INSERT ... SELECT ... ON CONFLICT DO NOTHING` against `tcg.action_required_items`: **9 inserted** = 5 pending approvals, 1 dead source, 2 restricted sources, 1 low-resolution.
- Independent readback: exactly **9 OPEN** audit-tagged tasks, all owner-scoped to one owner; all **10 of 10** original exceptions have OPEN MEDIA tasks including the pre-existing slab task.
- Trigger audit: `tcg.action_required_items_audit` appended **9 INSERT events** in `tcg.audit_events`. No media records, ownership, prices, financial events, R2 objects or publication flags were touched.
- No account, authentication token, owner UUID, seller photo, provider key or raw object key was exported into the report.

## Founder UI implementation

Founders HQ `/founders` previously used only `/api/v1/inventory/readiness` for the visible 'Action Required' stock filters. It did **not** render the persisted Action Required queue. This PR adds an independent **Artwork and listing reviews** panel under the existing readiness section:

- Fetch `GET /api/v1/action-required?category=MEDIA&status=OPEN&limit=50` through existing session-aware `apiRequest`. The server verifies the logged-in user and owner membership using PostgreSQL RLS; it does not expose other owners' tasks.
- Show owner-specific total and the first 8 most urgent review tasks, with an optional expansion up to 50; use plain `textContent` for all titles/details/actions and a strict Inventory ID whitelist before enabling 'Find in inventory'.
- No resolve/dismiss/approve buttons: decisions still require actual review and their normal versioned workflow. Navigating to stock resets catalogue filters and searches only the exact Inventory ID.
- Do not block sign-in or inventory when the queue endpoint fails; show a small retry prompt. Increment request generation and clear the panel on logout to avoid stale session data appearing after account switches.
- Styles reuse the premium navy/white/blue/orange palette with mobile layout and keyboard focus indicators. The panel loads only for authorised Founders HQ pages and is not a public storefront widget.

## Connections, failures, testing and release gates

**Connections:** existing FastAPI `action_required` router, PostgreSQL owners/inventory tables and RLS, Founders HQ `index.html`/`app.js`, existing R2 audit evidence. No new migration, n8n workflow, provider adapter or architecture change.

**Failure modes:** missing account membership (API rejects), expired session (stale response ignored), malformed inventory code (find control omitted), malicious issue text (rendered as text, not HTML), too many tasks (bounded initial rendering), media API outage (founder inventory remains usable), stale/incorrect source metadata (human must verify before approving).

**Tests:** new jsdom `tests/ui/media-review-queue.cjs`, wired into the dashboard UI suite. It tests safe escaped display, matching stock action, invalid ID suppression, severity fallback, row bounds/expansion, empty/error states, logout clearing and required script/API wiring. Existing full `PYTHONPATH=backend pytest`, Node UI suite, source lint, n8n-image tests and Railway's unmodified pre-deploy/health checks must pass. After deployment, verify actual Founders HQ authenticated panel for the owner and a different founder not receiving these tasks. **Do not claim the UI is live before successful Railway deployment/readback.**

## Pricing and artwork release gates

The Pro capacity guard is live at 8GB with reversible `DROP_RATE_CATALOGUE_BULK_HOLD=true` blocking bulk catalogue/image/provider updates. Keep it enabled. eBay Browse supplies **active** listings only, not sold comparables. The existing 505-item conservative read-only price preview is INSERT 0/UPDATE 0/SKIP 505, not permission to fill prices from retail guides.

Image resolution and R2 proof remain distinct from exact artwork, commercial permissions and slab-photo verification. No missing artwork or Market Value was repaired by adding the exception queue.


## Final production UI release receipt — 10 November 2026

- [PR #1062](https://github.com/pulltheorytcg/drop-rate-backend/pull/1062) merged with reviewed commit `99086377638fb1e97f3d6ab88a29d669c86d3ca0`. All three GitHub Backend checks jobs passed: backend tests, dashboard UI/jsdom and pinned n8n-image validations.
- Live Railway API service `6aa92310-153f-4fc9-9e22-dc338282605b` deployment **`a382f089-db13-47d4-83a0-383919cf9a27` SUCCESS**, `2026-11-10T20:20Z`. Unchanged pre-deploy check results: **11,485 pytest passing, 32 optional skipped, 1 warning**; Stripe sandbox/financial checks passed. Startup completed, `/health/ready` returned HTTP **200**.
- Deployment startup logs confirm `CATALOGUE_OPERATOR_BULK_HOLD active`, Pro `database_limit_bytes=8000000000`, database `428158099` bytes, `CATALOGUE_BULK_REFRESH_DEFERRED`, `CATALOGUE_R2_REFERENCE_MEDIA_DEFERRED`, each `refresh_allowed=false` with reason `BULK_REFRESH_DEFERRED_OPERATOR_HOLD`. Independent archive and existing current R2 catalogue/market publications continued.
- Railway has **zero pending staged changes** after deployment. No change to marketplace pricing, R2 bytes, product images, order allocation, owner IDs, Shopify publications or D1.
- Database readback after deployment: nine audit-tagged HIGH media exceptions still OPEN, plus the pre-existing graded slab issue. Trigger audit has **9 INSERT events** for those exactly tagged owner-scoped tasks. The UI reads but never modifies them.
- **Limitation:** deployed code, full jsdom behavior, API health and PostgreSQL queue are verified; a logged-in browser UI readback and cross-founder visual isolation were **not** executed through a founder session in this tool context. Those remain manual acceptance checks. Do not call the actual images repaired. The ten tasks are available through the existing authenticated Action Required API for the correct owner.

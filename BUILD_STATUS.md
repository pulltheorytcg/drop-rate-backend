# Drop Rate — Live Build Status

## 2026-10-01 — Competitive Intelligence foundation in progress

- Founder-prioritised Competitive Intelligence is now a formal fifth intelligence/growth pillar rather than an informal future idea.
- Added deterministic source-policy, evidence-deduplication, corroboration and OBSERVE-only action primitives in `backend/app/competitive_intelligence.py`.
- A competitor observation cannot qualify by itself: the engine requires independent source evidence plus at least one non-competitor corroborating origin (Drop Rate/internal, market, social or official).
- Source preflight blocks unreviewed automated sources and any access-control bypass; competitor content is reference-only by default.
- Competitive Intelligence can only hand off proposals (content, CRO/SEO experiment, merchandising, acquisition review); it cannot publish, copy creative, change price, ownership or finance.
- Added `docs/COMPETITIVE_INTELLIGENCE.md` and regression coverage.
- Expanded the source-controlled n8n roadmap from 42 to **43** workflows with `competitive-intelligence` as sequence 43, authority OBSERVE, status PLANNED.
- No workflow JSON, external source adapter, database migration or production activation is included in this slice; the Phase 3 stability gate and per-source terms/rights review still apply.



## 2026-10-01 — Recognition quality benchmark foundation

- Started the recognition-refinement workstream without expanding the reference corpus or adding new recognition scope.
- Added a read-only human-labelled evaluation layer for VALIDATION and HOLDOUT examples only; TRAIN examples are explicitly rejected from benchmark claims.
- Metrics now cover exact precision/recall, unsafe exact decisions, top-1 accuracy, safe abstention/review rate, no-match/failure rate, P50/P95 latency, per-system breakdowns, risk-flag frequency and recurrent confusion pairs.
- Superseded learning labels are excluded; unreviewed AI output is never evaluation truth.
- Added a platform-admin, owner-scoped read-only endpoint at `/api/v1/recognition/learning/evaluation`.
- The evaluator cannot mutate recognition, inventory, ownership, pricing, settlements or Shopify state and cannot auto-promote weights, thresholds or models.
- Added regression tests and `docs/RECOGNITION_QUALITY_BENCHMARK.md`.
- This is permitted recognition-quality refinement under the Phase 3 interpretation; it is not reference-corpus expansion.
- Production deployment/benchmark read-back remains pending CI, review and merge.



## 2026-10-01 01:39 BST — 30 September → 1 October full catch-up reconciliation

A detailed evidence-backed worklog for the full period is now recorded in `docs/WORKLOG_2026-09-30_TO_2026-10-01.md`. This checkpoint reconciles the main chat, Work/Codex work, GitHub PR history and live Supabase/Shopify/Railway state rather than treating discussion as completion.

### Current production truth at the cutoff

- Supabase has **509 physical inventory items**, **507 Shopify inventory links**, **73 base tables in `tcg`**, **67,989 reference-card records** across **734 reference sets/language records**, and **2 canonical sealed-product records**.
- Exactly **2 FOR_SALE physical items remain unlinked**, both deliberately fail-closed One Piece raw-card evidence/media exceptions: `DON!! Card (Egghead)` and `Monkey.D.Luffy (Release Event Leader)`.
- Dragon Ball is now **35 / 35 FOR_SALE physical items linked and PUBLISHED**. Earlier intermediate notes showing eight unlinked Dragon Ball cards are superseded.
- Automation outbox health is clean at this checkpoint: **0 PENDING / DISPATCHING / DEAD_LETTER** events. The historical events have been deliberately SUPERSEDED rather than accidentally replayed.
- Action Required has **0 OPEN CRITICAL** items and **2 OPEN HIGH** items. Both HIGH items are exact graded-slab media tasks: Charizard V 019/189 PSA 9 needs exact approved slab FRONT + BACK; ACE cert 590532 has approved exact front media but still lacks the exact back image for record completeness.
- Railway still contains the documented seven-service production topology. `drop-rate-api-live`, the operations monitor, payout scheduler, n8n and reconciliation worker are healthy/SUCCESS at this cutoff; the two on-demand PSA/CardTrader prototype services remain sleeping rather than deleted.
- n8n production is healthy on **2.32.6** and the provisioner sees the source-controlled DR-00/01/02/90/91/92 definitions, but the latest startup still reports **0 draft workflows / 0 published workflows**. The automation control plane is therefore present without silently activating customer-impacting workflows.
- Shopify test orders #1003 and #1004 successfully proved the real checkout → webhook → exact physical Inventory ID → Sunny owner attribution → ledger path and were then intentionally cancelled/refunded. Canonical Postgres now records #1003 CANCELLED and #1004 REFUNDED with their exact physical items returned to inspection.
- Shopify's connected order-summary surface still displays #1003/#1004 as PAID/unfulfilled at this checkpoint. This is being treated as a channel-projection/final-financial-status reconciliation item; it does **not** override canonical Postgres order/ownership truth.

### Storefront and catalogue work completed on 30 September

- The Brand Redesign machine-verifiable launch gate passed and its source-controlled theme matched Shopify. It remains **UNPUBLISHED** at this cutoff because making it MAIN is a manual Shopify Admin action plus final real-device/browser smoke.
- Published raw duplicate pooling is complete for the identified backlog: **20 duplicate raw groups / 48 physical inventory links** were consolidated into correct customer-facing pooled products without deleting physical ownership/history.
- One Piece raw publication was reconciled and the Japanese Nami Round 1 promotional identity/media was corrected.
- Both founder-owned One Piece sealed products were published with sealed-specific metadata/shipping and surfaced through a top-level **Sealed** destination, One Piece submenu and a dedicated responsive homepage component.
- Premium Card Collection storefront imagery was upgraded to a 1600×1600 source and sealed-product media sizing/whitespace handling was refined through PRs #406, #408–#411.
- Storefront **Sell With Us** now reaches a real public Seller Hub self-registration path. It creates only a restricted CONSIGNOR/OWNER identity at the existing default commission and cannot grant Founder HQ/admin access.
- Public Seller Hub stale-invite reuse was fixed; the mobile storefront Sell placement was moved into the drawer/footer rather than crowding the header.

### Seller Hub work completed late 30 September / early 1 October

- The Seller Hub uses the exact approved integrated transparent logo with explicit image rendering, desktop-left/mobile-centred positioning, corrected spacing and cache busting.
- Profile/account settings are live: display name, optional unique username, read-only account context, verified email-change path and password change with current-password verification.
- Seller Hub password login now supports **email or username** while keeping Supabase Auth as credential authority.
- Username resolution is server-only, browser roles cannot call the resolver directly, invalid-login responses are generic, and database-backed throttling is 8 failures/identifier or 30/network identity per 15 minutes with only hashes stored.
- PR #431 is merged/deployed; migration `owner_username_login` is live; Railway deployment `784f5b11-54d6-4381-b03b-5a7f74c64c0f` succeeded after the recorded 2,138-test preflight.
- The earlier “Seller Hub header breathing-room refinement — production verification pending” line below is historical and superseded: PR #427 is merged.

### Recognition and Dragon Ball work completed

- PR #398 deployed the unseen-card reference library with **67,989 records** spanning Pokémon, One Piece, Dragon Ball Masters/Fusion World and Naruto sources.
- This is a reference/candidate library, not a claim of universal measured scanner accuracy. Exact fingerprints, physical language/finish and human-confirmed learning remain governed separately.
- Dragon Ball storefront media was upgraded away from tiny ~180×251 CardTrader preview derivatives to the largest exact original from the same trusted Blueprint where available.
- Exact Winner/Tournament Pack matching was hardened and official-reference fallback rules were added without weakening exact-print safeguards.
- **PR #394 remains OPEN** for the measured high-resolution/2160px replacement gate. Better originals are live; “true 4K” replacement coverage is **not yet complete** and AI upscaling is not accepted as canonical exact media.

### Work/Codex mobile-app work before the cutoff

- **PR #433 is DRAFT / OPEN**, branch `codex/seller-hub-ios`: native SwiftUI iPhone Seller Hub with full-screen rear-camera scanning, match review before draft inventory creation, portfolio images and Market Value/Store Price, TCG search/language filters, Keychain session storage, refresh, editable PSA/BGS/ACE/CGC label OCR, manual card correction and payload-bound save retries.
- The PR reports 2,143 backend tests passing locally, but this is **not a released app**. Physical iPhone proof, native CI, real-account smoke, Apple signing/TestFlight, interrupted-save recovery and complete native sales/payout/security surfaces remain.
- Android remains planned; no Android production implementation should be inferred from the iOS draft.

### Retained roadmap / do not lose these items

- Sealed scanner recognition and a much larger sealed catalogue/reference library.
- Sealed market-data ingestion plus deterministic Market Value / Recommended Retail / Quick-Sale / Target Acquisition pricing.
- Continue building the very large governed card reference corpus so cards can be recognised before they have ever existed in Drop Rate inventory.
- Complete Dragon Ball genuinely high-resolution exact-print media work.
- Finish iOS and build Android while keeping desktop Seller Hub first-class.
- Shopify buyer → verified Seller Hub account → purchased-card portfolio handoff, without rewriting historical sale/owner records.
- eBay expansion plus future Whatnot, Cardmarket and TCGplayer adapters with shared cross-channel stock protection/order reconciliation.
- The source-controlled 42-workflow n8n programme: inventory/intake, recognition, sealed, pricing/market data, Shopify, orders/refunds, ownership/settlement, consignments, cross-channel, customer portfolio, marketing, listing copy, SEO/CRO, creative/social, email, customer service, recommendations, intelligence, briefings, analytics, image quality, errors and hardware.
- Google Shopping should use Shopify's native Google & YouTube feed path first; n8n adds value around diagnostics/monitoring rather than duplicating the feed. Paid Shopping remains an explicit spend decision.
- Draft PRs #215/#216 remain non-production CRO/SEO and Content Machine foundations until real storefront signal justifies activation.


## 2026-10-01 — Seller Hub email-or-username login

- Added real **email or username** password sign-in for Seller Hub while keeping Supabase Auth as the credential authority.
- The browser now sends `identifier + password` to a dedicated FastAPI public session endpoint instead of assuming the identifier is an email address.
- Username-to-email resolution happens server-side through a SECURITY DEFINER PostgreSQL function that is executable only by `tcg_api`; browser `anon` / `authenticated` roles cannot call it.
- Unknown usernames still exercise the normal Supabase password-auth path with a synthetic email so public failures remain generic and do not disclose whether a username exists.
- Added shared PostgreSQL brute-force protection: 8 failed attempts per identifier or 30 per network identity inside 15 minutes; only SHA-256 hashes are stored, never raw usernames, emails, IPs or passwords.
- Successful session responses are marked `no-store`; invalid credentials return the same generic response for email and username login.
- Existing Google/Apple login, Supabase session refresh, Seller Hub owner-access checks and Founder HQ redirect behaviour remain unchanged.
- Added runtime `httpx` dependency declaration, regression tests and `docs/SELLER_HUB_USERNAME_LOGIN.md`.
- Production activation complete: PR #431 merged; the Supabase `owner_username_login` migration applied successfully; resolver/rate-limit functions exist with `tcg_api` execute access while `anon` and browser `authenticated` do not; the failure table has RLS enabled; at least one active seller currently has a username and the production resolver can resolve an active username server-side.
- Railway deployment `784f5b11-54d6-4381-b03b-5a7f74c64c0f` completed successfully; pre-deploy verification reported **2,138 tests passed** and the new container returned HTTP 200 from `/health/ready`.
- No real seller password was used during deployment verification, so credential-level live smoke testing remains naturally exercised by the next genuine Seller Hub login rather than by creating or altering a production account.


## 2026-09-30 — Seller Hub CSS cache-bust v12

- Bumped the Seller Hub stylesheet asset version to `owner-v12` so browsers immediately receive the deployed header-spacing and Profile-page styles instead of reusing the previous `owner-v11` cache.
- No UI logic, auth, database, ownership, pricing, settlement or payout behaviour changed.


## 2026-09-30 — Seller Hub profile & account settings

- Added a dedicated **Profile** view for restricted Seller Hub owners.
- Sellers can update their display name and claim an optional unique username; usernames are PostgreSQL-owned, lowercased, 3–30 characters and case-insensitively unique.
- Profile changes are owner-scoped through a SECURITY DEFINER database function and write `OWNER_PROFILE_UPDATED` audit events with old/new values.
- Added read-only seller account context: current email/verification state, seller type, membership date and commission rate.
- Added authenticated email-change flow through Supabase Auth; the UI makes clear that email changes only take effect after the configured verification flow completes.
- Added password-change flow that verifies the current password first, obtains a fresh Supabase session, then updates the password without storing credentials in Drop Rate.
- Added Profile access from the account chip and Seller Hub navigation; mobile navigation becomes horizontally scrollable so Profile and existing destinations remain usable without crushed tabs.
- No profile control can change owner type, founder slot, commission, inventory ownership, membership role, settlements or payout amounts.
- Added `docs/SELLER_HUB_PROFILE_SETTINGS.md` and regression coverage for database constraints, owner scoping, browser security and responsive access.
- Production activation complete: PR #428 merged; `owner_profile_settings` applied successfully in Supabase; `tcg_api` has EXECUTE while `anon` and browser `authenticated` do not; the case-insensitive username index is present; Railway deployment `a6827447-fb6d-42f3-8c83-2bbef058cd52` completed successfully; deployment preflight ran **2,131 tests** successfully and production readiness returned HTTP 200.
- Security follow-up: Supabase's security advisor currently reports **Leaked Password Protection Disabled**. The connected management surface does not expose a safe Auth-config mutation for this setting, so it was not silently changed; enable it in Supabase Auth settings when available.


## 2026-09-30 — Seller Hub header breathing-room refinement

- Reduced the signed-in desktop Seller Hub lockup from 254×68 px to 220×56 px so the approved logo has more vertical breathing room inside the 78 px topbar.
- Increased desktop topbar side padding from 28 px to 36 px and reduced the reserved brand width accordingly.
- Mobile true-centred logo sizing and all account/sign-out controls remain unchanged.
- No auth, ownership, inventory, pricing, order, settlement, payout or Shopify logic changed.
- Production verification pending CI, merge and Railway deployment.

## 2026-09-30 — Exact approved Seller Hub logo asset

- Verified the previous repository Seller Hub PNG was not the same file as the newly approved artwork: the approved attachment is **2048×682** and the older static export had different dimensions/proportions.
- Uploaded the exact user-approved transparent PNG unchanged to the connected Drop Rate Shopify CDN and wired Seller Hub auth/header branding to that permanent asset URL.
- The existing CSP already permits `cdn.shopify.com`, so no security-policy widening was required.
- Desktop remains left-aligned; mobile remains true-centred from PR #424; account/sign-out controls are unchanged.
- Regression tests now assert the production Seller Hub markup uses the approved CDN asset and no longer references the superseded local Seller Hub PNG.
- No auth, ownership, inventory, pricing, order, settlement, payout or Shopify commerce logic changed.
- PR #425 passed CI, merged, and Railway production deployment `35a709c5-ab1a-49de-b541-afbd3aca4cca` completed **SUCCESS** at commit `196b7a8e34f034b1a891118fc84909e77d73685c`.
- Shopify file read-back reports the approved logo **READY**, **2048×682**, **1,582,010 bytes**, matching the uploaded attachment's dimensions and byte size.
- End-user browser rendering remains to be visually smoke-checked on desktop/mobile after the next storefront click-through.

## 2026-09-30 — Seller Hub explicit logo rendering + mobile centring

- Replaced the Seller Hub logo's CSS background-span rendering with a real transparent `<img>` using the approved integrated **Drop Rate Seller Hub** asset.
- Desktop keeps the logo left-aligned at the start of the header.
- Mobile positions the logo at the true horizontal centre of the topbar while the existing account/sign-out controls remain on the right.
- Mobile logo width is constrained to avoid overlap with the unchanged account controls on narrow phones.
- Seller Hub login branding uses the same explicit image rendering so the asset cannot disappear because of background sizing/clipping.
- Cache-bumped Seller Hub CSS to `owner-v11` and the logo asset reference to `seller-hub-3`.
- Added regression coverage for explicit image rendering, desktop sizing, mobile centring and removal of legacy split branding.
- No auth, ownership, inventory, pricing, order, settlement, payout or Shopify logic changed.
- PR #424 passed CI, merged, and Railway production deployment `9c3a1024-6ba4-48a3-8cef-6521b42f284b` completed **SUCCESS** at commit `6892c352e349266df7cca9820a86ac6c07c922b3`.
- End-user desktop/mobile visual smoke remains pending the next real browser visit.

## 2026-09-30 — Public Seller Hub stale-invite fix

- Root cause found for storefront **Sell With Us** showing **“This invite cannot be used”**: a clean `/owner/join` visit could reuse an expired invite token from browser local storage.
- Public invite-free entry now accepts an invite token only when it is explicitly present in the URL; cached invite state is recovered only during an authentication callback.
- Genuine founder-issued invite links remain supported and continue using the existing invite redemption path.
- Cache-bumped `owner-join.js` so production browsers receive the fixed join logic immediately after deploy.
- Added regression coverage and updated the storefront Seller Hub contract documentation.
- No owner permissions, founder access, ownership, pricing, settlement, payout or Shopify order logic changed.
- PR #423 passed CI (**2,126 tests**) and Railway production deployment `00593bd1-a3aa-4ab4-be36-c306caf4f344` completed **SUCCESS** at commit `84afc34f63217691a9b35ad334259886eeb9d56c`.
- Shopify Admin read-back confirms **Sell With Us** points to the clean production `/owner/join` URL with no invite token attached.
- Supabase read-back confirms `tcg.self_register_owner(text,integer)` exists and remains server-only: `tcg_api` can execute; `anon` and browser `authenticated` cannot.
- End-user click-through remains the final smoke check for clearing the previously cached invite failure in a real browser.

## 2026-09-30 — Seller Hub brand lockup refinement in progress

- Replaced the previous Seller Hub artwork with the user-approved transparent **Drop Rate Seller Hub** integrated lockup.
- The Seller Hub header keeps the existing dark navy chrome and right-side account controls; no auth, ownership, inventory, pricing, settlement or navigation logic changes.
- The same dedicated Seller Hub lockup is used consistently for desktop header and Seller Hub authentication surfaces.
- Desktop/mobile logo dimensions were rebalanced for the integrated wide artwork and cache-busted so the old white-background asset cannot persist.
- Founder HQ branding remains separate and unchanged.
- Deployment remains pending CI and production read-back.

## 2026-09-30 — Seller Hub integrated brand lockup

- Replaced the Seller Hub's generic Drop Rate image + separately rendered product text with the approved integrated **Drop Rate Seller Hub** logo.
- Added source-controlled transparent asset `backend/app/static/brand-assets/drop-rate-seller-hub.png`.
- Removed the old topbar divider and separate `DROP RATE / Seller Hub / Inventory · Sales · Payouts` construction that caused the header to look misaligned.
- Seller Hub auth and signed-in header now share the same Seller Hub-specific visual identity; Founder HQ remains unchanged.
- Desktop topbar uses a 224 px-wide lockup; mobile uses a compact 154 px treatment so account/sign-out controls remain usable.
- Cache-bumped `owner-portal.css` to `owner-v9`.
- Regression tests verify the transparent PNG asset, absence of the legacy split lockup and responsive logo sizing.
- No auth, permissions, inventory, pricing, order, settlement or Shopify logic changed.

## 2026-09-30 — Seller Hub mobile placement refined

- Removed the **Sell** pill from the Brand Redesign mobile header; desktop retains **Sell With Us** in the header.
- Created a Brand Redesign-specific Shopify navigation menu copied from the current main menu, with **Sell With Us** added as a Seller Hub destination. Horizon's live `main-menu` is untouched.
- Brand Redesign now points its header menu at `brand-redesign-main-menu`; the Seller Hub menu item is hidden at desktop widths and therefore appears only in the mobile drawer.
- Added a compact Seller Hub footer callout that renders only below 750 px.
- All Seller Hub links use the existing verified production `/owner/join` flow. No auth, owner, inventory, pricing or settlement logic changed.
- Brand Redesign remains UNPUBLISHED until this UI refinement passes CI, theme sync and mobile/desktop preview read-back.

## 2026-09-30 — Storefront “Sell With Us” → Seller Hub production verification complete

- PR #414 is merged and deployed to `drop-rate-api-live` at commit `8e851f96e9aba1b747607e2881bebf9ebe357925`.
- Railway production deployment is SUCCESS; pre-start/runtime verification reported **2122 tests passed** and `GET /health/ready` = 200.
- Supabase migration `public_owner_self_registration` is applied in production (live migration version `20260930204126`).
- Live function grants are fail-closed:
  - `PUBLIC`: no EXECUTE;
  - `anon`: no EXECUTE;
  - Supabase `authenticated`: no direct EXECUTE;
  - `tcg_api`: EXECUTE.
- The self-registration function is SECURITY DEFINER but verifies the authenticated `auth.users` record, requires confirmed non-anonymous email, creates only `CONSIGNOR` + `OWNER` access at the existing 1000 bps / 10% default commission, and refuses conflicting roles.
- Founder/admin boundary was exercised against an existing PLATFORM_ADMIN founder identity: self-registration was rejected and created **0** owner/audit records.
- `Drop Rate — Brand Redesign` now contains the source-controlled `Sell With Us` desktop CTA / `Sell` mobile CTA linking to `/owner/join` on the production Seller Hub domain.
- Shopify runtime read-back:
  - Brand Redesign remains **UNPUBLISHED**;
  - `processing=false`, `processingFailed=false`;
  - `snippets/header-actions.liquid` checksum `7d4cfc59e588fd0a41ed414d9fa07b81`, 11504 bytes, updated 2026-09-30 20:45:13Z;
  - Horizon remains the **MAIN** theme.
- No external seller account was created during verification, preserving the no-external-owner-activation rule.
- Shopify catalogue after Phase-B pooling: **461 ACTIVE**, **0 DRAFT**, **46 ARCHIVED** products.
- Remaining human launch QA for this slice: visually open Brand Redesign on desktop/mobile and tap **Sell With Us**; confirm the hosted Supabase Auth redirect allow-list returns email/OAuth confirmations to `/owner/join`. The current connected Supabase tooling cannot read that hosted Auth allow-list, so it is not being changed blindly.
- Brand Redesign is still intentionally unpublished pending the full storefront launch gate.

## 2026-09-30 — Published raw-card pooling Phase B complete

- Production reconciliation is complete for **20 duplicate raw-card groups / 48 physical inventory links** exposed by Brand Redesign launch QA.
- Every affected physical Inventory ID remains independently owned and auditable in Postgres; only the customer-facing Shopify projection was consolidated.
- Redundant Shopify products were not deleted: they were set to quantity 0 and ARCHIVED so historical order references remain intact.
- Final production audit:
  - **0** remaining eligible raw-card groups split across multiple Shopify products;
  - **0** `(listing_key, allocation_priority)` collisions;
  - all **20** pooled anchor products read back ACTIVE with Shopify quantity exactly matching currently sellable physical-copy count and the expected deterministic `DRP-...` SKU;
  - **0 CRITICAL**, **0 SHOPIFY**, **0 SETTLEMENT**, and **0 SHOPIFY_ORDER_WEBHOOK_GAP** open Action Required items;
  - **0** unhealthy automation events in PENDING / DISPATCHING / DEAD_LETTER.
- Uta OP13-023 proved the historical-priority edge case: the refunded #1003 copy remains INSPECTION/ARCHIVED at historical priority 1, active pooled copies preserve 2/3/4, and the newly merged copy uses priority 5.
- The reconciliation changed no owner, acquisition cost, sale history, refund history, settlement history or canonical card identity.
- Brand Redesign remains UNPUBLISHED while the separate storefront **Sell With Us → Seller Hub** launch slice is completed and verified.

## 2026-09-30 — Storefront “Sell With Us” → Seller Hub self-registration in progress

- Added a customer-facing storefront conversion path so Brand Redesign can connect buyers directly to the restricted Drop Rate Seller Hub.
- Existing `/owner/join` was verified as invitation-only before this change; the storefront CTA is therefore paired with a real invite-free registration contract rather than linking customers to a dead-end token page.
- New self-registration remains fail-closed and role-safe:
  - requires an authenticated, non-anonymous Supabase user with a confirmed email;
  - creates `CONSIGNOR` ownership only;
  - creates `OWNER` membership only;
  - defaults commission to 1000 bps / 10%;
  - idempotently reuses an existing active OWNER/CONSIGNOR membership;
  - refuses to overwrite or downgrade PLATFORM_ADMIN / other conflicting access.
- The database, not browser-supplied email, verifies the authenticated user against `auth.users`.
- Founder HQ remains inaccessible to self-registered sellers; payout approval/execution and internal admin controls remain outside this flow.
- Existing founder-issued seller invitations remain supported.
- Brand Redesign header source now contains a prominent **Sell With Us** desktop CTA and compact **Sell** mobile CTA pointing to the Seller Hub join page.
- The production migration and Brand Redesign theme sync are now applied and verified; Brand Redesign remains intentionally UNPUBLISHED pending human launch smoke testing.
- See `docs/SELL_WITH_US_STOREFRONT.md`.

## 2026-09-30 — Published pool historical-priority edge case fixed

- First live Phase-B migration was deliberately limited to Uta OP13-023 after production deployment.
- Shopify read-back succeeded: the pooled anchor is ACTIVE at quantity 4 and the redundant individual product is ARCHIVED at quantity 0.
- The first database commit safely rolled back before mutation because the refunded #1003 physical copy correctly retained allocation priority 1 under the historical pool key; renumbering active members to 1..N would collide with the unique `(listing_key, allocation_priority)` constraint.
- Live Uta reconciliation was then completed without rewriting history: existing active pool priorities 2/3/4 were preserved and the newly consolidated physical copy received priority 5. The refunded INSPECTION/ARCHIVED copy remains priority 1 and auditable.
- Phase-B code is hardened accordingly: existing pool members keep their allocation priorities and newly merged members are assigned only after the maximum historical priority for that listing key.
- That regression fix subsequently passed CI and deployed; all remaining eligible published duplicate groups were then reconciled, as recorded above.

## 2026-09-30 — Published duplicate raw-card pooling Phase B in progress

- Brand Redesign production checkout QA exposed a catalogue projection gap rather than an order-allocation defect.
- Desktop grouped-copy order #1003 proved the pooled Shopify variant path end-to-end: Shopify payment/webhooks, exact physical allocation, Sunny ownership, SOLD transition, quantity decrement and ledger creation all succeeded.
- #1003 cancellation/refund then returned the exact sold card to INSPECTION, archived its physical Shopify link and created item + shipping reversal ledger entries. Shopify's refund transaction was still PENDING at the immediate read-back.
- Mobile Apple Pay order #1004 also completed successfully through Shopify Payments and the Drop Rate webhook/order/ownership/ledger path. Its later cancellation/refund returned the exact physical card to INSPECTION and archived that link.
- The mobile purchase exposed that the same Uta OP13-023 English Near Mint Foil identity was still split between an existing pooled product and individual ACTIVE products.
- Root cause: the original raw pooling release intentionally consolidated DRAFT duplicates only; a Phase-B migration for already-PUBLISHED duplicates had not yet been implemented.
- Strict production audit ultimately identified **20 published duplicate raw groups / 48 currently sellable physical cards** that meet the full safety gate: identity-confirmed, raw only, same canonical card/language/condition/price, cost + storage present, no reservations/listing membership, same Shopify location/publication and synced price parity.
- Added a PLATFORM_ADMIN-only published-pool plan/apply path that prefers an existing pool anchor, verifies live Shopify product/variant/inventory state, converts the anchor to the deterministic pooled SKU/quantity, archives redundant sellable products at quantity zero, repoints only current APPROVED/PUBLISHED physical links, preserves historical SOLD/ARCHIVED links and audit-logs every migrated Inventory ID.
- Remote compensation is included if the database commit fails. Graded inventory and ambiguous groups remain fail-closed.
- Those groups have now been reconciled with Shopify/Postgres parity verified; see the completion section above.
- See `docs/SHOPIFY_PUBLISHED_POOLING.md`.

## 2026-09-30 — Final storefront launch gate passed; manual Shopify theme publish remains

- Completed the final machine-verifiable launch gate for `Drop Rate — Brand Redesign`.
- Shopify theme state: UNPUBLISHED, processing=false, processingFailed=false.
- Verified all **27** source-controlled Brand Redesign theme files against Shopify; **0 content mismatches**.
- Latest full CI suite passed: **2110 tests**.
- Shopify catalogue state at gate:
  - **485 ACTIVE products**;
  - **485 ACTIVE + published-to-Online-Store products**;
  - **0 DRAFT products**;
  - **0 ACTIVE-but-unpublished products**;
  - **42 published collections**.
- Navigation read-back confirms top-level Shop All / Singles / Graded / Sealed plus Pokémon / One Piece / Dragon Ball, with One Piece → Sealed present and customer-account menu retaining Shopify-native Orders/Profile.
- `Sealed` smart collection is populated with 2 products; One Piece contains 270 products.
- Production inventory/link integrity:
  - **509 FOR_SALE physical inventory items**;
  - **507 Shopify-linked / 2 intentionally unlinked**;
  - **507 PUBLISHED non-test inventory links** backing **485 distinct Shopify products**;
  - **0 missing owners**, **0 synced-price mismatches**, **0 wrong sale-intent links**, **0 missing Shopify variant/inventory/location IDs**;
  - pooled identical physical copies intentionally share Shopify products/variants and remain individually owned in Postgres.
- Open operational blockers: **0 SHOPIFY** Action Required items and **0 SETTLEMENT** Action Required items.
- Reconciled 2 new `inventory.approved` outbox events for the already-published sealed products through the guarded audited supersede function. Outbox health returned healthy=true with pending/due/dispatching/dead-letter/stale all zero, and both automation alerts resolved.
- Railway launch read-back: `drop-rate-api-live` SUCCESS, scheduled `drop-rate-api` operations monitor SUCCESS, n8n SUCCESS.
- Final customer-path code contract remains covered by green tests: exact-copy cart quantity lock, grouped-copy PDP, Shopify-native checkout/account handoff, product-only partial-match search, collection facets/sort shell and current visual system.
- The connected Shopify API exposes `themePublish`, but the connector safety layer explicitly blocks making a theme MAIN. A direct publish attempt was refused for that reason. **The remaining launch action is a manual Shopify Admin Publish click for Brand Redesign.**
- Exactly 2 FOR_SALE cards remain intentionally unlinked after renewed evidence review:
  - Monkey.D.Luffy (Release Event Leader), #P: exact card identity is strongly corroborated, but public catalogues disagree on Normal vs Foil and no governed exact-print storefront media is attached. Do not guess the physical printing.
  - DON!! Card (Egghead), The Azure Sea's Seven: exact English identity is corroborated, but the stored exact image remains INTERNAL_REFERENCE_ONLY and currently available public image results include materially different Gold variants. Do not substitute a Gold image for the normal physical item.
- These two inventory exceptions do **not** block the storefront theme launch; they remain fail-closed until exact physical/media evidence is available.

## 2026-09-30 — Sealed artwork footprint matched to card grid

- Kept the custom `Keep it sealed.` homepage feature intact; only its media treatment changed.
- Homepage sealed media now uses the same solid `#f4f7fb` surface as standard product-card galleries instead of a separate gradient/ring treatment, so the Premium Collection white source matte blends consistently with the collection grid.
- Reused the existing Shopify featured images; no replacement image or Photoshop-derived asset was introduced.
- Normalised by visible artwork rather than file dimensions: current sealed products receive product-specific scale compensation for baked-in whitespace (Ace TS-02 1.42×, Premium Collection 1.28×), while future sealed products keep a conservative 1.12× default.
- The same scale rules apply to both standard collection/search cards and the homepage sealed feature, preserving consistent visual footprint across desktop and mobile.

## 2026-09-30 — Sealed media scale refinement

- Reused the existing Shopify product imagery for sealed products; no alternate or Photoshop-derived asset was introduced.
- Increased standard sealed-product grid scale from 82% to 94% so tins/collections occupy a visual footprint closer to normal card images while retaining `object-fit: contain`.
- Increased the custom homepage sealed feature from 82%/172 px to 94%/190 px on desktop, with proportional 92% sizing on tablet and mobile.
- Premium Card Collection retains the same high-resolution Shopify featured image and the same scoped background-blending treatment already used on collection cards, keeping homepage and browse presentation consistent.

## 2026-09-30 — Sealed media sizing + Premium Collection background normalization

- Normalized sealed product imagery in both the custom homepage feature and standard Shopify product-card galleries, so non-card-shaped sealed products do not visually overpower or undersize relative to trading-card products.
- Standard product grids now detect `product_type = Sealed TCG Product`, keep the same card frame, use the Drop Rate cool-grey media surface and scale the contained product artwork to 82% of the available media area.
- The homepage sealed feature uses a capped 82% / 172 px desktop media presentation, with smaller proportional tablet/mobile caps.
- Premium Card Collection -6 assort vol.1- keeps its 1600×1600 high-resolution source, but uses a scoped multiply blend against the cool-grey media surface so the source JPEG's hard white square no longer reads as a pasted-on white tile.
- The Premium Collection blend rule is product-specific; it does not alter colour handling for other sealed products.

## 2026-09-30 — Sealed homepage UI refinement

- Replaced the generic two-column Shopify product-list homepage treatment with a dedicated `dr-brand-sealed` component.
- Desktop sealed cards are compact horizontal cards with a capped ~210 px media column instead of large half-page product tiles.
- Tablet switches to a single compact row; mobile uses a proportional 118 px media column with tighter typography and metadata.
- Visual treatment matches the existing Drop Rate storefront system: cool-grey section surface, white cards, navy/ink typography, blue/cyan accents, subtle borders/shadows and rounded product surfaces.
- The section remains driven by the real `sealed` Shopify collection and supports up to four products without hard-coded product IDs.

## 2026-09-30 — Sealed storefront CRO pass

- Shopify `main-menu` now exposes `Sealed` as a top-level destination and as a One Piece submenu entry, both linked to the populated smart collection `/collections/sealed`.
- The source-controlled Brand Redesign homepage features the real `sealed` collection directly after Latest Drops; the initial generic product-list treatment was superseded by the compact custom `dr-brand-sealed` component.
- Premium Card Collection -6 assort vol.1- image quality was audited at 546x546 on the previous official Bandai asset; that low-resolution media was replaced on Shopify with a 1600x1600 product photograph for sharper collection/PDP rendering.
- Supabase media provenance keeps the superseded 546x546 Bandai asset as revoked history and records the active 1600x1600 storefront reference separately. No ownership, price, quantity, settlement or canonical sealed identity changed.
- Brand Redesign remains UNPUBLISHED; this change does not publish or replace the live theme.

## 2026-09-30 — Japanese Nami + sealed One Piece publication + outbox recovery complete

- Corrected Nami (Round 1 Promo) ST29-008 end-to-end from the previously incorrect English/base media path to the founder-confirmed Japanese ROUND1 promotional printing.
  - Supabase inventory and canonical catalogue language are Japanese.
  - card_printings identity status is VERIFIED with ROUND1 promo metadata.
  - exact Japanese provider mapping and identity-verification audit evidence are recorded.
  - prior English/base media records are revoked/rejected; the Japanese storefront media is the sole active approved canonical FRONT.
  - Shopify product is ACTIVE as `Nami (Round 1 Promo) · JP · ST29-008 · One Piece Promotion Cards · Foil · Near Mint`, with `Language:Japanese` tag/metafield and exact Japanese ROUND1 image.
- Published both founder-owned Japanese One Piece sealed products through the governed bootstrap -> bounded linked-draft reconciliation path:
  - `One Piece Tin Pack Set Vol. 2 -Portgas.D.Ace- · JP` at £27.30, inventory `INV-C03F9CCD386C4798A90A45CC5CB00619`.
  - `Premium Card Collection -6 assort vol.1- · JP` at £111.08, inventory `INV-5CD6E9E29B9B489D9D8B624A0D0E1609`.
  - bootstrap considered exactly 2 and linked 2/2 with 0 failures; reconciliation considered exactly 2 and published 2/2 with 0 blockers.
  - both are ACTIVE, quantity 1, vendor/game One Piece, product type `Sealed TCG Product`, language Japanese, seal status SEALED, and belong to both the `Sealed` and `One Piece` Shopify collections.
  - official product media is attached; product-specific sealed shipping profiles are active at 300 g for the Ace TS-02 tin and 100 g for the Premium Card Collection.
  - the old `SEALED_PUBLICATION_INPUTS_REQUIRED` HIGH Action Required items are RESOLVED after verified publication; the existing audit trigger records the resolution.
- Merged PR #403 to clean sealed listing titles/tags/metafields and PR #404 to keep sealed descriptions product-specific (no card-only Variant/Condition/Rarity fields; explicit seal status).
- Reconciled the automation outbox using the guarded audited supersede function:
  - all 13 remaining PENDING `inventory.approved` events referenced inventory that was already non-test PUBLISHED in Shopify.
  - marked those 13 SUPERSEDED, not DELIVERED or DEAD_LETTER, in accordance with `docs/AUTOMATION_EVENT_BACKLOG_RECONCILIATION.md`.
  - outbox health now reports healthy=true with pending=0, due=0, dispatching=0, dead_letter=0 and stale_dispatching=0; prior outbox Action Required alerts are resolved.
  - Railway scheduled `drop-rate-api` operations monitor is SUCCESS.
- Railway `drop-rate-api-live` is SUCCESS after the final sealed-description deployment; full backend pre-deploy suite reported 2108 passed.
- Exactly 2 FOR_SALE inventory items remain without Shopify links, both known One Piece raw-card media exceptions:
  - Monkey.D.Luffy (Release Event Leader), number P, English Foil.
  - DON!! Card (Egghead), The Azure Sea's Seven, English Normal.
- One-off catalogue-bootstrap / linked-draft reconciliation controls were returned to disabled after the sealed publication run.

## 2026-09-30 — One Piece raw publication reconciliation advanced

- Reconciled live production after the Dragon Ball completion run: all Dragon Ball FOR_SALE inventory is now Shopify-linked; the earlier BUILD_STATUS note showing 8 unlinked Dragon Ball items is superseded by this section.
- Started with 7 unlinked One Piece raw cards plus 2 One Piece collection/sealed products.
- Added and merged the narrow One Piece promotional-reference disclosure guard (PR #397) before publication; CI passed.
- Shopify catalogue bootstrap then considered exactly 5 eligible One Piece raw cards and linked 5/5 as non-test DRAFT products with 0 failures.
- Published the first import batch as exactly 4/4 and the second batch as exactly 1/1 through the bounded linked-draft reconciliation path; Shopify/Supabase read-back confirmed correct SKU, price, quantity and PUBLISHED link state.
- Newly published raw cards: Edward.Newgate ST15-002, Eustass\"Captain\"Kid P-003 participant promo, King OP17-064, I'll Feed on This Rage and Use It to Bring the World to Ruin!!! OP17-097, and Nami ST29-008 Round 1 Promo.
- The one-off Shopify catalogue-bootstrap and linked-draft reconciliation controls were returned to disabled after use.
- Exactly 4 FOR_SALE items remain unlinked: 2 One Piece raw cards and 2 One Piece collection/sealed products.
- Raw-card exceptions remain deliberately fail-closed:
  - Monkey.D.Luffy (Release Event Leader), collector number P: identity is confirmed, but current import metadata says Foil while external catalogue evidence for the standard English event leader is inconsistent with that variant; no approved storefront media is attached.
  - DON!! Card (Egghead), The Azure Sea's Seven: identity is confirmed, but the only stored image is INTERNAL_REFERENCE_ONLY rather than STOREFRONT_ALLOWED.
- Do not publish either raw exception by guessing or by copying arbitrary retailer/marketplace imagery. Require stronger exact-print evidence plus storefront-permitted media or a first-party physical capture.
- Next inventory-publication concern is the 2 sealed/collection products, after the two raw exceptions remain explicitly tracked as blocked.

## 2026-09-30 — Dragon Ball media cleanup wrapped to external-source boundary

- Rechecked the remaining Dragon Ball media backlog after the production original-size rollout.
- The storefront-quality regression itself is closed: all 25 currently published Dragon Ball products use the largest exact CardTrader Blueprint original available instead of the tiny preview derivative.
- There are still 8 unlinked FOR_SALE Dragon Ball units, but only 7 remain genuinely media-unresolved: Vegeta FB05-039 Tournament Pack 06 Winner now has an exact CardTrader Winner candidate in `PENDING_REVIEW`; its old `MEDIA_UNRESOLVED` item is resolved.
- The remaining 7 are six exact Masters pre-release printings plus Nappa FP-046 Tournament Pack 07. CardTrader cannot prove those exact printings: the Masters Blueprints are base-set images and CardTrader currently exposes Nappa as Tournament Pack 08.
- External identity checks confirm the special printings themselves exist, but those sources are not being copied into Shopify: TCGplayer's public terms restrict crawling/scraping and outside use of its content, and Bandai's public card-list image is the base card rather than proof of the stamped pre-release physical printing.
- The existing TCGGraph adapter is the clean no-photo fallback already present in the backend. It supports Dragon Ball Masters/Fusion World exact printings, exact line isolation, rights/provenance metadata and human approval before Shopify use.
- Production still does **not** have `TCG_TCGGRAPH_API_KEY`. No paid provider subscription, credential, or new recurring dependency was created during this cleanup.
- Until an approved storefront-permitted provider credential is configured, the 7 special-print items intentionally remain fail-closed rather than receiving visually similar or legally unclear images.

## 2026-09-30 — Dragon Ball storefront media quality upgraded

- Confirmed the quality fault was upstream media, not storefront CSS: all 25 published Dragon Ball products were using CardTrader `preview_` derivatives at roughly 180 x 251 px.
- Proved Shopify `fileUpdate(originalSource)` can replace product media in place without changing product/variant/inventory identity.
- Upgraded all 25 live Dragon Ball product images to the same exact CardTrader Blueprint's larger original; all 25 re-read as READY.
- Verified resulting dimensions range from 251 x 350 on older Masters cards to 1279 x 1782 on the strongest current source; Fusion World examples are typically 600 x 838 to 716 x 1000.
- Updated the 25 approved CardTrader media registry rows so Postgres now stores the original-size URL rather than the low-resolution preview derivative.
- True 4K is **not** claimed where the provider source is smaller. The long-term 4K rule is genuine 2160+ px long-edge source or first-party high-resolution capture/scan, not synthetic enlargement.
- CardTrader resolver hardening is being shipped in this slice so future exact Dragon Ball media automatically prefers the same Blueprint original URL.
- Added strict Fusion World Winner handling for provider `w` collector suffixes only when the local card explicitly proves the same Tournament Pack Winner version.
- Of the 8 remaining unlinked Dragon Ball cards, six pre-release Masters copies and Nappa Pack 07 remain fail-closed pending exact storefront-permitted media/physical capture; Vegeta FB05-039 Winner 06 now has an exact CardTrader Winner resolution path.


## 2026-09-30 — Phase 2 system map + efficiency audit refreshed

- Re-verified `docs/PHASE2_SYSTEM_MAP.md` against live Railway, Supabase and current Git state.
- Confirmed Railway still has 7 services. Core steady-state services remain FastAPI, operations monitor, payout scheduler and n8n.
- Preserved the prior founder-approved launch decision for the other three services: keep `psa-fetch-batch` as the working PSA cert/media prototype, keep `psa-cert-lookup-temp` for its current CardTrader discovery/probe role pending later rename/repurpose, and keep `shopify-reconciliation-worker` through launch as a recovery tool. No service was deleted.
- Confirmed 17 unlinked FOR_SALE units remain: 8 Dragon Ball cards, 7 One Piece cards and 2 One Piece collection/sealed products.
- Confirmed 2 OPEN HIGH `GRADED_SLAB_MEDIA_REQUIRED` and 2 OPEN HIGH `SEALED_PUBLICATION_INPUTS_REQUIRED` items remain.
- Confirmed the two `SHOPIFY_ORDER_WEBHOOK_GAP` records are DISMISSED with explicit historical-test resolution metadata; they refer to cancelled Shopify order #1001 and are not active publish blockers.
- Confirmed there are no OPEN CRITICAL Action Required items.
- Confirmed DR-02 source is merged but its production migration is still unapplied; dispatcher-heartbeat migration also remains deliberately unapplied.
- Confirmed production n8n remains at zero published workflows after the DR-01/DR-02 source deployments.
- No workflow, migration, publication, payout, service deletion or production data change was activated by this audit.
- Remaining Phase 2 publish proof is human/browser work: mobile + desktop smoke, Brand Redesign real test purchase, rollback confirmation, and the two timed efficiency tests.

## 2026-09-30 — n8n Wave B: DR-02 Shopify product updates built inactive

- Added inactive `DR02ShopifyProductUpdatesV1`, scheduled every 15 minutes once deliberately published.
- v1 scope is intentionally **Store Price reconciliation only**; canonical `store_price_minor` remains Postgres truth.
- Added narrow SECURITY DEFINER candidate/finalize functions for production, single-item, unreserved, PUBLISHED Shopify links only.
- Test-mode products, pooled variants, Personal Collection, non-APPROVED inventory and unchanged prices are excluded.
- FastAPI updates the exact Shopify variant, verifies returned variant identity and price, then revalidates link + inventory versions in Postgres before recording the sync.
- Partial failures or concurrent-state changes fail the workflow so DR-90 handles the exception; successful runs record DR-91.
- n8n contains no price-setting, ownership, inventory, Shopify GraphQL or finance business logic.
- Registry state for `shopify-product-updates` is now `BUILT_INACTIVE`.
- **Activation remains blocked:** migration application, DR-90/DR-91 publication/proof, deliberate Shopify automation enablement, and controlled no-op/duplicate/stale/API-failure/read-back tests.

## 2026-09-30 — DR-01 inactive command-route correction

- Found before activation: `DR01InventoryApprovedShopifyV1` still targeted the old automation-control URL after the signed Shopify command moved into the narrower automation-commands router.
- No production business action occurred because DR-01 V1 and DR-00 V2 were imported inactive.
- Added `DR01InventoryApprovedShopifyV2` with the correct `/api/v1/automation/commands/shopify/inventory-approved` path.
- Added `DR00IngressV3` at `/drop-rate/events-v3`, routing `inventory.approved` only to DR-01 V2.
- V1/V2 remain inactive audit history; the provisioner does not overwrite persistent workflow IDs.
- Activation gate now points only to DR-00 V3 + DR-01 V2.

## 2026-09-30 — operations-monitor Railway watch list repaired

- Railway `drop-rate-api` operations-monitor watch patterns now include the n8n runtime heartbeat checker/migration and dispatcher heartbeat checker/migration.
- This fixes the deployment sequencing gap where heartbeat monitor code could change without automatically rebuilding the cron service.
- The dormant dispatcher log now reports `installed=false` explicitly when its manual-gated migration is absent.
- No schedule, alert enablement, dispatcher activation, Shopify publication activation or database migration state changed.

## 2026-09-30 — dispatcher-heartbeat dormant migration guard

- Production operations-monitor cron exposed a sequencing bug: dispatcher-heartbeat monitoring was merged before its deliberately manual-gated Supabase migration was applied.
- The dispatcher checker now probes for the narrow heartbeat function before calling it.
- If the migration is absent **and alerts remain disabled**, the checker reports `AUTOMATION_DISPATCHER_HEARTBEAT_NOT_INSTALLED_DORMANT` and exits 0 so unrelated operations monitoring remains healthy.
- If dispatcher-heartbeat alerts are enabled while the migration is absent, the checker still fails closed.
- This does not apply the migration, create the dispatcher service, enable alerts or activate n8n workflows.

## 2026-09-30 — n8n Wave B: DR-01 Shopify product creation built inactive

- Restored the canonical `20260928183039_shopify_automation_publication` migration file to Git; production Supabase already reports that exact migration version/name as applied.
- Extracted one deterministic `publish_inventory_to_shopify(...)` service from the current single-item Shopify path so manual founder testing and automation use the same publication/read-back rules.
- Preserved current copy-group metadata sync after publication.
- Added signed FastAPI automation command `POST /api/v1/automation/control/shopify/inventory-approved`.
- Added inactive versioned ingress `DR00IngressV2` because the n8n provisioner intentionally does not overwrite persistent DR-00 V1.
- Added inactive `DR01InventoryApprovedShopifyV1`.
- DR-00 V2 accepts only a valid signed dispatcher envelope and currently routes only `inventory.approved`; unsupported events fail closed.
- DR-01 validates deterministic event identity/idempotency, calls FastAPI, requires verified Shopify success, then records durable success through DR-91. Workflow errors route to DR-90.
- n8n contains no ownership, readiness, Shopify product-building or financial business rules.
- Registry state for `shopify-product-creation` is now `BUILT_INACTIVE`.
- **Activation remains blocked:** DR-90/DR-91 publication/proof, the manual dispatcher-heartbeat migration gate, controlled DR-00 V2/DR-01 live test, duplicate/retry proof, and deliberate dispatcher webhook cutover are still required.

## 2026-09-30 — n8n Wave A control plane implementation closed

- **Wave A build scope is now implemented in source control:** registry, signed ingress, global error handling, reusable success receipts, Action Required integration, dead-letter/replay visibility, outbox backlog health, canonical n8n runtime heartbeat and dispatcher-process heartbeat.
- The **Action Required bridge does not need a separate n8n workflow**. DR-90 failure receipts are HMAC-signed into FastAPI, where deterministic backend logic writes deduped `N8N_WORKFLOW_FAILED` Action Required items. Backend/Postgres health monitors likewise open and resolve their own deduped exceptions.
- This keeps n8n as orchestration, FastAPI as deterministic business/control logic, and Postgres as durable truth.
- Canonical n8n heartbeat remains `DR92RuntimeHeartbeatV1`; the brief duplicate heartbeat stays tracked only as an inactive orphan until supported authenticated cleanup is available.
- PR #384 prepared dispatcher heartbeat monitoring without creating or activating a dispatcher Railway service.
- **Production activation is intentionally not complete:** the dispatcher-heartbeat migration remains behind the existing manual Supabase migration gate; DR-00/DR-90/DR-91/DR-92 remain inactive/unpublished until their activation proofs are deliberately executed.
- No historical backlog, business workflow, customer workflow or money movement was activated as part of Wave A.
- Next build wave is **Wave B — Core Commerce Operations**, starting from the current controlled Shopify/order/refund/allocation foundations and keeping all new n8n workflows inactive until their proof gates pass.

## 2026-09-30 — n8n Wave A: dispatcher heartbeat prepared

- Added private `tcg.automation_component_heartbeats` state plus narrow `SECURITY DEFINER` heartbeat write/check functions.
- The long-running automation dispatcher writes a `DISPATCHER` heartbeat at startup and periodically (default 30 seconds), including worker instance and component version.
- Heartbeat health is independent from outbox health: it can detect a dead dispatcher even while the queue is empty.
- Added `check_automation_dispatcher_heartbeat.py` to the existing combined operations monitor.
- **Dormant by default:** `TCG_AUTOMATION_DISPATCHER_ALERTS_ENABLED=false` until the dispatcher service is intentionally deployed.
- Once enabled, a missing/stale dispatcher heartbeat opens founder **CRITICAL `AUTOMATION_DISPATCHER_UNHEALTHY`** and fails the operations monitor; recovery resolves the alert.
- Default health threshold is 90 seconds and is bounded between 30 seconds and 15 minutes.
- No business state, outbox event state, inventory, Shopify, order, ownership, pricing, finance or settlement truth is mutated by the heartbeat monitor.
- This prepares the dispatcher for production but does **not** create/deploy a new Railway service. Any dispatcher service deployment still requires BUILD_STATUS documentation and explicit activation sequencing.
- Runbook: `docs/AUTOMATION_DISPATCHER_HEARTBEAT.md`.

## 2026-09-30 — inactive n8n orphan explicitly source-controlled

- Production n8n still contains one known inactive orphan, `DR92WorkflowHeartbeatV1`, imported briefly by superseded PR #381 before heartbeat consolidation.
- Canonical heartbeat remains `DR92RuntimeHeartbeatV1`; the orphan must never be activated, published, called or re-imported.
- The exact orphan JSON is retained under `automation/n8n/orphans/` so it is reviewable in Git without being copied into the n8n image or startup provisioning directory.
- Supported cleanup is currently blocked by the absence of an authenticated n8n API key/admin automation path and the absence of arbitrary Railway container exec. Direct SQLite editing is intentionally prohibited.
- Cleanup must use a supported authenticated n8n delete/archive operation, verify the exact orphan ID, and prove canonical DR-92 remains intact.
- Regression coverage guarantees the orphan stays inactive and outside the provisioner.

## 2026-09-30 — n8n heartbeat consolidation correction

- The canonical n8n heartbeat remains **DR-92 n8n Runtime Heartbeat** from PR #380.
- A second workflow-heartbeat implementation briefly merged in PR #381 duplicated DR-92's core purpose and introduced a variable-name collision in the combined operations monitor.
- The duplicate workflow, checker, wrapper, test and unapplied migration are removed before the duplicate database function reached production.
- `run_operations_monitor.py` is restored to one canonical `check_n8n_runtime_heartbeat.py` result and one `n8n_heartbeat_code` field.
- This keeps one 5-minute scheduled n8n liveness path: n8n → signed FastAPI heartbeat → private Postgres heartbeat state → independent operations monitor → dormant/armed Action Required.
- DR-91 remains the reusable durable success-receipt contract for real business workflows; it does not need a second heartbeat workflow to prove liveness.
- No production data was deleted and heartbeat alerting remains dormant by default.

## 2026-09-30 — n8n Wave A: source cutover verified + DR-92 runtime heartbeat built inactive

- Production `drop-rate-n8n-e840` is now repo-controlled through `Dockerfile.n8n`, still pinned to n8n 2.32.6 and using the existing persistent `/home/node/.n8n` volume.
- Railway deployment for merge `e1e1668` succeeded; startup detected DR-00/DR-90 as existing persistent workflows, imported DR-91 once as inactive, and n8n reported zero published workflows.
- Added DR-92 runtime heartbeat as the next Wave A control-plane component:
  - fixed 5-minute `n8n-runtime` heartbeat;
  - HMAC-authenticated FastAPI endpoint;
  - private/RLS-enabled latest-heartbeat table with no direct `tcg_api` table access;
  - duplicate/out-of-order beats cannot advance the stored heartbeat;
  - existing operations monitor checks freshness;
  - Action Required escalation is HIGH and deduped, but **dormant by default** until explicit activation proof.
- DR-92 cannot mutate inventory, ownership, price, settlement or customer state.
- Activation remains gated on migration deployment, one durable manual heartbeat, duplicate replay proof and stale→healthy alert lifecycle proof.

## 2026-09-30 — n8n Wave A: reusable durable success receipts

- Added inactive reusable n8n sub-workflow `DR91SuccessReceiptV1`.
- Parent workflows provide typed workflow/execution/idempotency/event metadata only after their governed action has completed and been verified.
- DR-91 validates identifiers, creates a `SUCCEEDED` receipt, HMAC-signs it and requires durable FastAPI acceptance.
- The FastAPI receipt control now uses the supplied **idempotency key** as `automation_runs.run_key`, rather than n8n execution ID. Separate n8n executions handling the same business event therefore collapse to one durable receipt.
- Execution ID remains stored in receipt result metadata for diagnostics.
- DR-90 failure receipts remain behaviorally compatible because their idempotency keys already include the failed execution identity.
- No parent workflow should treat “started” or “HTTP request sent” as success; DR-91 belongs after deterministic/read-back verification.
- No business truth is stored in n8n execution history; durable run truth returns to Postgres.

## 2026-09-30 — n8n Wave A: automation run schema aligned with control-plane receipts

- Pre-activation review found `tcg.automation_runs` still carried legacy-only checks: `job_type='INVENTORY_REVIEW'`, `initiated_by='AUTOMATION_SERVICE'`, and `run_key` length ≤96.
- The DR-90/DR-91 receipt control plane uses bounded `N8N:<workflow-key>` job types, `N8N` initiator and Drop Rate idempotency keys up to 255 characters; without a schema fix the first real receipt would fail.
- Added a narrow migration that:
  - preserves legacy `INVENTORY_REVIEW` / `AUTOMATION_SERVICE`;
  - permits only `N8N:[a-z0-9][a-z0-9-]{1,119}`;
  - permits initiator `N8N`;
  - widens only the run-key check from 96 to 255 characters.
- Existing owner FK and unique `(owner_id,job_type,run_key)` constraints remain unchanged.
- Production currently contains **0 automation_runs**, so no historical rows require conversion.
- This is a prerequisite for activating DR-90/DR-91; neither workflow should be considered proven until a real signed receipt succeeds after this migration.

## 2026-09-30 — n8n repo-controlled source cutover hardening

- Production n8n still runs stock pinned image `ghcr.io/n8n-io/n8n:2.32.6`; no source cutover has been performed yet.
- Repo `Dockerfile.n8n` uses the same pinned n8n version, preserving version parity for the eventual cutover.
- Startup provisioning is hardened before any production source switch:
  - require DR-00 webhook secret/runtime capabilities;
  - require DR-90 automation command secret + governed FastAPI control receipt URL;
  - create one-time persistent-volume rollback copy `database.sqlite.pre-drop-rate-provision-v1.bak` before imports;
  - refuse workflow JSON unless `active=false`;
  - import only missing stable IDs;
  - verify all expected version-controlled workflow IDs after import;
  - never wipe/recreate the n8n database or import credentials.
- Railway already wires `DROP_RATE_AUTOMATION_COMMAND_SECRET` by direct reference to `drop-rate-api-live.TCG_AUTOMATION_COMMAND_SECRET`, preventing secret drift without exposing the value.
- Railway already defines `DROP_RATE_API_AUTOMATION_CONTROL_URL`; no plaintext secret/config value is committed.
- Source cutover remains a deliberate production action after CI + persistent-state provisioning checks; no duplicate n8n service will be created.

## 2026-09-30 — n8n Wave A: guarded dead-letter recovery

- Added Founder HQ dead-letter visibility and replay architecture so terminal automation failures can be recovered without manual SQL.
- Normal transient failures still use the existing automatic retry/backoff budget first; this path applies only after an event reaches `DEAD_LETTER`.
- Added narrow `SECURITY DEFINER` functions:
  - `tcg.list_automation_dead_letters(limit,offset)` returns operational metadata only and excludes event payloads;
  - `tcg.replay_dead_letter_automation_event(event_id,actor_user_id,reason)` can replay **DEAD_LETTER only**.
- Replay is independently database-gated to an active FOUNDER `PLATFORM_ADMIN`, even though the FastAPI route also checks platform-admin access.
- Replay preserves event identity, owner, aggregate, payload, idempotency key **and existing attempt history**. It returns the event to `PENDING`, clears dead-letter lease state, marks `MANUAL_REPLAY_REQUESTED`, and raises the retry ceiling only enough to permit one additional claim.
- `DELIVERED` and `SUPERSEDED` history cannot be replayed by this path.
- Every replay requires an explicit reason and writes an `AUTOMATION_EVENT_REPLAY_REQUESTED` audit event with the authenticated actor and originating request ID.
- No inventory, Shopify link, order, price, ownership, finance, settlement or market-data row can be mutated by this recovery function.
- Runbook: `docs/AUTOMATION_DEAD_LETTER_RECOVERY.md`.

## 2026-09-30 — n8n Wave A: automation outbox health monitoring

- Historical pre-routing backlog has now been reconciled in production: **396 / 396** obsolete `inventory.approved` events are `SUPERSEDED`, with **396** matching audit events; inventory remains **509** and published Shopify inventory links remain **492**.
- Added a narrow `SECURITY DEFINER` automation-outbox health monitor; `tcg_api` still receives **no direct SELECT access** to `tcg.automation_events`.
- Health snapshot covers PENDING, due, DISPATCHING, DEAD_LETTER, expired leases and oldest-pending age. `SUPERSEDED` is terminal history and is intentionally excluded from unhealthy queue counts.
- The monitor has two explicit modes:
  - **observe/dormant** (default): report metrics and return success without opening incidents;
  - **alerting**: stale pending events, dead letters or stale leases create/update founder HIGH `AUTOMATION_OUTBOX_UNHEALTHY` Action Required items and cause the operations monitor to fail.
- Added `backend/scripts/check_automation_outbox_health.py` to the existing 30-minute operations monitor alongside payout heartbeat and Shopify order reconciliation.
- Alert activation is controlled by `TCG_AUTOMATION_OUTBOX_ALERTS_ENABLED`; pending-age threshold defaults to 30 minutes and is bounded 5 minutes–24 hours.
- No outbox event is deleted, ACKed, replayed, superseded or dead-lettered by the health monitor.
- Canonical workflow registry marks **error-exception-alerts** and **operational-monitoring** as `BUILT_INACTIVE`; they move to `PROVEN` only after deployment/live execution proof.

## 2026-09-30 — n8n Wave A: historical outbox backlog retirement

- Production currently has **396 PENDING `inventory.approved` automation events** created before n8n dispatcher activation.
- Read-only reconciliation proves **all 396 / 396 already have PUBLISHED Shopify inventory links**; none remains an actionable publication job.
- They must not be called DELIVERED because n8n never delivered them, and must not be called DEAD_LETTER because they did not fail.
- Added a fifth terminal/event state: **SUPERSEDED** with explicit `superseded_at` and `superseded_reason`.
- Added guarded `tcg.supersede_published_inventory_approved_events(...)`:
  - PENDING only;
  - `inventory.approved` only;
  - `INVENTORY_ITEM` only;
  - requires the same Inventory ID to already have a PUBLISHED Shopify link;
  - bounded/locked batch;
  - tcg_api-only execution;
  - per-event audit record.
- The function cannot mutate inventory, Shopify links, orders, pricing, ownership, finance or settlement state.
- After merge/migration, the 396 historical events can be honestly retired before the dispatcher is activated.
- Runbook: `docs/AUTOMATION_EVENT_BACKLOG_RECONCILIATION.md`.

## 2026-09-30 — n8n Wave A control plane: durable execution/error receipts

- First launch-grade n8n control-plane component is now in source control.
- Added signed FastAPI endpoint: `POST /api/v1/automation/control/receipt`.
- n8n receipts are authenticated with a dedicated `TCG_AUTOMATION_COMMAND_SECRET` / `DROP_RATE_AUTOMATION_COMMAND_SECRET` HMAC contract and a 5-minute replay window.
- Execution receipts are written to existing `tcg.automation_runs` using the existing unique `(owner_id, job_type, run_key)` constraint.
- Duplicate delivery of the same n8n execution is a pure no-op: it does not create a second run or bump the failure alert.
- FAILED receipts create a deterministic HIGH `N8N_WORKFLOW_FAILED` Action Required item; n8n cannot choose the severity/category/code itself.
- System-level failures without owner context fan out only to active FOUNDER owners. No customer/consignor owner is invented.
- Added inactive version-controlled workflow `DR90GlobalErrorV1`:
  - n8n Error Trigger;
  - normalise failed execution;
  - sign control receipt;
  - call FastAPI;
  - fail the error-workflow execution if FastAPI does not durably accept the receipt.
- DR-90 is explicitly forbidden from using itself as its own error workflow, preventing recursive alert storms.
- No inventory, ownership, price, Shopify publication, settlement or financial truth is mutated by this control-plane path.
- Activation remains gated on backend deployment + matching secrets + one synthetic failure + duplicate replay proof.

## 2026-09-30 — Founder override: n8n becomes a parallel pre-launch operating-system workstream

- The business goal is now explicit: Drop Rate should be able to **run, operate and make money with minimal founder intervention beyond physical stock acquisition, strategic decisions and packing/dispatch**.
- The earlier “one small boring n8n workflow first, advanced automation later” sequencing is superseded as the final delivery strategy.
- New strategy: **build broad before launch; activate narrow based on proof**.
- n8n remains the orchestration layer only:
  - PostgreSQL/Supabase = durable business truth;
  - FastAPI = deterministic rules/permissions;
  - AI = interpretation/generation/prioritisation;
  - n8n = event routing, scheduling, retries, provider coordination, notifications and closed-loop orchestration.
- The full **42-workflow programme** is now a parallel pre-launch workstream rather than a post-launch-only backlog.
- Added `docs/N8N_LAUNCH_OPERATING_SYSTEM.md` with the launch architecture, authority model, intelligence loop, control plane and pre-launch build waves.
- Added `automation/n8n/workflow-registry.json` as the canonical source-controlled registry for all 42 workflow families.
- Every registry entry requires:
  - idempotency;
  - version-controlled workflow JSON;
  - deterministic backend contract;
  - duplicate-delivery test;
  - failure/retry test;
  - error routing/observability;
  - provider terms/rate-limit review where applicable.
- Launch-critical target is no longer “one workflow works”; it is a **well-oiled automation control plane plus broad prebuilt workflow coverage**, with production activation gated by evidence.
- The existing 396 PENDING `inventory.approved` outbox events are treated as a historical backlog and must not be accidentally consumed by the first activated gateway. Backlog disposition/replay must be deliberate.
- Next implementation wave: **Control Plane** — global error workflow, Action Required bridge, execution receipts, dead-letter/replay visibility, dispatcher backlog monitoring and workflow heartbeat.

## 2026-09-30 — PSA credential hardening

- The retained PSA cert-lookup Function uses PSA's current documented Public API endpoint/auth contract, but production retest returned **HTTP 403** because no PSA-specific credential is configured.
- The old Function incorrectly referenced `TCG_PARSE_API_KEY`, an unrelated provider secret. That fallback is removed.
- The PSA Function now requires a dedicated `PSA_PUBLIC_API_TOKEN` and returns `503 PSA_PUBLIC_API_TOKEN_REQUIRED` until a valid official bearer token is configured.
- No slab-media exception is closed from a failed lookup. Charizard V PSA 9 cert 62398872 remains `GRADED_SLAB_MEDIA_REQUIRED`.
- Once a valid PSA token is available, configure it only on the PSA lookup service, redeploy, then verify a known-good cert plus 62398872 before scanner integration.

## 2026-09-30 — Sealed catalogue + scanner architecture clarified

- Sealed inventory is now explicitly defined as a **first-class canonical product family**, not one generic row per TCG set.
- Initial priority sealed formats are:
  - **Elite Trainer Boxes (ETBs)**;
  - **Booster Boxes / Displays**;
  - **Single Booster Packs**.
- A TCG set is the parent release; each official sealed SKU under it is a separate canonical sealed product. Example: one set can have a standard ETB, Pokémon Center ETB, booster box, single pack, sleeved booster and booster bundle, each with different identity/market data.
- Future scanner modes are now **Raw Card / Graded Slab / Sealed Product**.
- Sealed recognition must combine packaging OCR, set/product text, barcode/product code, pack count, official reference images, language and region; low-confidence results fail closed.
- The sealed catalogue must become a governed corpus large enough to recognise sealed products that have never previously been scanned by a Drop Rate user.
- Sealed products get exact-SKU market-data mappings and their own pricing normalization; booster-box pricing must not be derived by simply multiplying single-pack value.
- Language and region remain distinct. Different-language/region sealed products are not automatically interchangeable.
- Real packed dimensions/weight, seal condition and shipping profile remain required publication inputs where applicable.
- Full design: `docs/SEALED_PRODUCT_CATALOGUE_SCANNER_ARCHITECTURE.md`.
- Implementation remains behind the current Phase 2 storefront stability gate, but sealed recognition/catalogue expansion should be a high-priority workstream once that gate reopens.

## 2026-09-30 — Founder HQ proxy-image viewport loading

- After the Shopify CDN + TCGdex direct-image optimisations, the remaining provider images still use the authenticated FastAPI proxy by design.
- Founder HQ previously started every proxy request as soon as a visual-grid card was rendered, including cards well below the viewport.
- Proxy-only inventory images now begin fetching only when their card is within roughly **320px of the viewport**, using `IntersectionObserver`.
- Browsers without `IntersectionObserver` fall back to the existing immediate proxy behavior.
- A one-shot guard prevents duplicate proxy downloads if multiple visibility/error signals occur.
- Direct Shopify/TCGdex images keep native lazy loading; their proxy fallback still starts immediately only if the direct image actually fails.
- This reduces initial backend/provider image bursts without changing media rights, approved hosts, inventory truth or security controls.

## 2026-09-30 — Scanner language recognition added to deferred architecture

- The approved future scanner architecture now includes **automatic language recognition** for **English, Japanese, Chinese and Korean** across both Raw Card and Graded Slab modes.
- Detection must combine physical OCR/script evidence, collector/set metadata, canonical/provider evidence and grader certificate fields where available; artwork alone is not sufficient.
- Language output is confidence-scored and human-confirmed when uncertain. Conflicting or low-confidence evidence must fail closed into Action Required rather than being guessed.
- Chinese should retain room for Simplified/Traditional script detail even if the first UI groups both under Chinese.
- Confirmed language is stored on the physical Inventory Item and feeds exact-print matching, pricing, Shopify metadata/filters and pooling/cross-channel eligibility.
- Different-language physical copies must never be pooled as interchangeable stock.
- This remains deferred behind the Phase 2 storefront stability gate alongside the PSA/ACE/CGC/TAG/BGS graded-slab scanner implementation.

## 2026-09-30 — PSA certificate lookup compatibility repair

- Phase 2 review confirmed the retained `psa-fetch-batch` Railway service is important graded-card infrastructure, but a live exact-cert check returned **HTTP 403** for PSA cert 62398872.
- Root cause: the Railway Function still uses an obsolete PSA API shape: `https://api.psacard.com/cert/{cert}` with `X-PSA-API-KEY`.
- PSA's current official Public API documents `https://api.psacard.com/publicapi/cert/GetByCertNumber/{cert}` with `Authorization: bearer <access token>`.
- The Railway Function source is being brought into GitHub at `ops/railway/psa-fetch-batch/index.tsx` and updated to the current documented contract.
- The utility remains read-only: provider cert evidence only, no inventory identity mutation, media approval, Shopify publication or Action Required resolution.
- The function now supports `?cert=<number>` for one exact lookup as well as the retained diagnostic batch.
- After merge, deploy this exact source back to the existing `psa-fetch-batch` service and re-test cert 62398872. If the existing token is expired/invalid, do not invent a workaround; refresh the PSA access token through the official account flow.
- `GRADED_SLAB_MEDIA_REQUIRED` closes only if the exact cert returns exact permitted slab media; a successful cert lookup without scans is not sufficient.

## 2026-09-30 — Founder HQ stacked inventory-filter correctness

- Repo hygiene review found PR #230 still contained one unique unsuperseded bug fix.
- The location-aware Founder HQ `loadInventory` override omitted `sale_intent`, so combining **Personal Collection** with a storage-location filter could silently drop the Personal Collection scope and show the wrong inventory.
- The fix forwards `sale_intent` alongside search/status/brand/issue/location filters.
- The composed dashboard DOM test proves `sale_intent=PERSONAL_COLLECTION` and `unlocated=true` coexist in the real overridden request and that Clear Filters/global search reset the collection scope.
- No backend, ownership, inventory, pricing, Shopify or settlement mutation is involved.

## 2026-09-30 — Founder HQ TCGdex direct-image fast path

- Post-deploy coverage audit of PR #344 found only **10 / 490 displayed inventory images (2.0%)** currently have a Shopify CDN URL, so the first fast path was correct but too narrow to materially solve the measured grid latency alone.
- TCGdex accounts for **195** selected Founder HQ inventory images. Its current API documentation explicitly supports direct card-image URLs and recommends the **low-quality WebP** variant when displaying many small images in a grid.
- The direct-browser fast path is therefore expanded only to **Shopify CDN + TCGdex**:
  - TCGdex `high.webp` grid URLs are converted to `low.webp`;
  - the authenticated bounded proxy remains automatic fallback;
  - official One Piece, CardTrader, OPTCG API, TCGGraph and unknown hosts remain proxy-only unless their display terms are separately confirmed.
- Current production data indicates **202 / 490 displayed inventory images (~41.2%)** can use the direct path after this change.
- No wildcard direct-provider path is introduced.

## 2026-09-30 — Phase 2 audit consolidated onto current main

- Phase 2 remains the active operating layer on top of the storefront-first manual. Brand Redesign remains unpublished until the full launch gate passes.
- Added `docs/PHASE2_EFFICIENCY_AUDIT.md`, `docs/PHASE2_SYSTEM_MAP.md` and the verified `docs/STOREFRONT_ROLLBACK.md`.
- Machine-side efficiency evidence is now explicit:
  - normal inventory/readiness APIs are generally sub-second;
  - exact supported-card recognition latency is dominated by the vision stage, not Postgres/scoring;
  - inventory-image proxy responses were observed around 1.5–2.8s; PR #344 is merged and deployed with the Shopify-CDN-first optimisation.
- Historical Shopify test order #1001 is fully reconciled:
  - no local order was fabricated;
  - PR #338 prevents a processed unpaid cancellation from reopening forever;
  - the two old HIGH `SHOPIFY_ORDER_WEBHOOK_GAP` rows were guardedly dismissed with audit records;
  - production now has **0 OPEN Shopify webhook-gap alerts**.
- Media exception lifecycle is corrected by PR #340. The three stale Dragon Ball `MEDIA_UNRESOLVED` rows were guardedly resolved after verifying exact eligible media + published physical links. Production now has exactly **8 OPEN `MEDIA_UNRESOLVED` rows**, matching the eight genuine Dragon Ball exact-print blockers.
- Current Action Required OPEN census: **37 total / 0 CRITICAL**:
  - HIGH: 2 `GRADED_SLAB_MEDIA_REQUIRED`, 2 `SEALED_PUBLICATION_INPUTS_REQUIRED`;
  - MEDIUM: 25 `MEDIA_REVIEW_REQUIRED`, 8 `MEDIA_UNRESOLVED`.
- PSA certificate/media capability is retained. `psa-fetch-batch` is the actual working PSA cert/media prototype; the misleadingly named `psa-cert-lookup-temp` currently contains a CardTrader Dragon Ball probe and should be renamed/repurposed later rather than silently deleted.
- PR #342 merged the deferred multi-grader **Raw Card / Graded Slab** scanner architecture for **PSA, ACE, CGC, TAG and BGS/BVG/BCCG**. Implementation remains frozen until the storefront stability gate explicitly reopens recognition/Seller Hub work.
- Production n8n audit confirms **n8n 2.32.6 / 0 draft workflows / 0 published workflows / 0 active workflows**. There is no hidden UI-only workflow drift. No n8n error workflow is configured yet; that becomes a hard prerequisite before the first real production workflow is activated.
- Rollback plan is now verified: Shopify reports Horizon as MAIN and Brand Redesign as UNPUBLISHED; Shopify's `themePublish(id: ID!)` contract is schema-valid. Emergency rollback is republish Horizon, verify Horizon=MAIN, then run the minimal recovery smoke. Theme publishing itself requires an authorized operator in Shopify Admin.
- Remaining human-only Phase 2 gates are unchanged: real-phone card scan timing, full mobile smoke, full desktop smoke and one controlled Brand Redesign purchase with confirmation + exact owner/inventory attribution.
- Stability threshold before reopening deferred scope remains: 72h Brand Redesign MAIN without rollback, 5 genuine paid non-founder orders, zero attribution/allocation/oversell/settlement errors, zero CRITICAL Action Required for 72h, no unresolved post-launch webhook gap, and one outside-person purchase test.

## 2026-09-30 — Founder HQ inventory image latency fast path

- Phase 2 production timing found inventory image responses frequently taking roughly **1.5–2.8 seconds** even while ordinary inventory/readiness metadata APIs remain sub-second.
- Root cause: Founder HQ visual inventory always fetched `/api/v1/inventory/{id}/image`, causing FastAPI to re-download and stream the remote image for every card render; the global authenticated response policy is also `Cache-Control: no-store`.
- The safe optimisation is **Shopify-CDN-first, authenticated-proxy fallback**:
  - the inventory API exposes a direct URL only when the selected media asset already has a strict HTTPS Shopify CDN URL;
  - Founder HQ loads that CDN image directly and lazily;
  - if the CDN request fails, the existing authenticated bounded/allowlisted FastAPI proxy is used automatically;
  - non-Shopify provider/source URLs continue through the existing proxy and are not exposed as the direct fast path.
- CSP is widened only for Shopify CDN hosts; provider hotlinking/privacy boundaries are unchanged.
- Existing proxy SSRF/content-type/size/redirect protections remain intact.
- This is a measured Phase 2 efficiency fix, not new Seller Hub/recognition feature scope.

## 2026-09-30 — Media Action Required lifecycle correction

- Phase 2 queue review found three stale OPEN `MEDIA_UNRESOLVED` rows for Dragon Ball cards that later obtained exact media and were published: BT18-067, BT18-138 and BT13-142.
- Root cause is in import enrichment state transition: moving from `PENDING` to `PENDING_REVIEW` or `REFERENCE_READY` did not close the older `MEDIA_UNRESOLVED` Action Required item.
- The lifecycle is being corrected so `MEDIA_UNRESOLVED` remains open only while media is genuinely `PENDING`; once exact media advances, the obsolete blocker is resolved before any current review state is maintained.
- No media is auto-approved, no ambiguous card is unblocked, and the eight genuinely unresolved Dragon Ball exact-print exceptions remain fail-closed.
- The three historical stale rows still require one controlled lifecycle reconciliation after deployment; they are not being deleted directly from Postgres.

## 2026-09-30 — Phase 2 Shopify #1001 reconciliation fix

- Phase 2 launch-gate review confirmed historical Shopify test order #1001 was PENDING/unpaid, cancelled on 24 September, had a successfully processed `orders/cancelled` webhook, created no local `tcg.orders` row, left no reservation, and was followed by successful order #1002 on the same Sunny-owned Seel inventory.
- The two HIGH `SHOPIFY_ORDER_WEBHOOK_GAP` rows are founder-scoped fan-out of that one historical order, not two missing sales.
- Reconciliation is being tightened so a remote-only unpaid order with Shopify `cancelled_at` plus a PROCESSED `orders/cancelled` webhook is treated as terminally acknowledged; paid-like orders remain CRITICAL and missing-create pending orders remain HIGH.
- This lets the monitor resolve #1001 durably instead of relying on a manual dismissal that the next 30-minute reconciliation run would reopen.

## 2026-09-30 — Phase 2 pooled storefront copy correction

- Phase 2 stale-PR audit found PR #317 contained unique customer-facing safety behaviour not present on current `main`; it was preserved rather than discarded.
- Two live Dragon Ball quantity-2 pooled products were verified to still use single-copy wording and expose one physical member's internal Inventory ID. Both Shopify descriptions were corrected in place without changing status, quantity, SKU or price.
- Current pooled-publication code is being hardened so future pooled offers rewrite and verify pooled-safe copy while still DRAFT, before activation.
- PR #311 was also preserved and merged because its Brand Redesign PDP source change was still unique: internal inventory references are removed from the PDP and pooled stock can display `N in stock`.

## 2026-09-30 — Consolidated checkpoint: 29 September → 30 September 01:52 BST

**PRODUCTION VERIFIED / STOREFRONT CATALOGUE LIVE / BRAND REDESIGN THEME STILL UNPUBLISHED —** this section is the authoritative handover for all work completed since the Claude storefront-first operating manual was adopted on 29 September 2026. Historical entries below are retained as an audit trail; where an older count conflicts with this section, this section is the current state.

### Current production state

- **Shopify products:** 470 ACTIVE, 470 Online Store-published, 0 DRAFT, 22 ARCHIVED.
- **Supabase inventory:** 509 physical inventory items with `sale_intent='FOR_SALE'`.
- **Published ownership links:** 492 physical inventory rows are linked to PUBLISHED Shopify inventory; those 492 physical rows intentionally collapse to **470 distinct live Shopify products** because interchangeable raw duplicates are pooled as Shopify quantity while Supabase still owns exact Inventory ID / Owner / Cost / Condition / Language / Location / settlement attribution.
- **Unlinked FOR_SALE inventory:** 17 total: 8 Dragon Ball raw cards, 7 One Piece raw cards and 2 One Piece sealed/collection products.
- **Linked Shopify drafts:** 0. The legacy linked-draft backlog has been fully drained or deliberately converted into explicit unlinked Action Required exceptions.
- **Theme state:** `Drop Rate — Brand Redesign` is still **UNPUBLISHED**. `Horizon` is still Shopify **MAIN**. Product publication and theme publication are separate launch gates.
- **Action Required:** 42 OPEN, 0 CRITICAL. HIGH = 2 `GRADED_SLAB_MEDIA_REQUIRED`, 2 `SEALED_PUBLICATION_INPUTS_REQUIRED`, 2 `SHOPIFY_ORDER_WEBHOOK_GAP`. MEDIUM = 25 `MEDIA_REVIEW_REQUIRED`, 11 `MEDIA_UNRESOLVED`.
- **n8n:** foundation remains intentionally production-dormant; the storefront-first freeze has not been lifted for advanced automation/marketing.
- **eBay / new channel expansion:** still frozen for new scope under the operating manual.

### 1. Immediate reliability work required by the Claude manual — COMPLETE

The manual required six operational fixes before new storefront expansion. They were completed in the required order rather than bypassed:

1. **Independent payout-scheduler heartbeat** — PR #255 added the >90-minute deterministic heartbeat, founder-only CRITICAL Action Required alert, automatic recovery resolution, restricted `SECURITY DEFINER` execution and a standalone monitor path. The Railway scheduler-start-command incident from 28 September had already been corrected; the independent check prevents the scheduler from being the only component responsible for detecting its own failure.
2. **Shopify ↔ Drop Rate order reconciliation** — PRs #256/#258 added the read-only two-way reconciliation, payment/webhook-aware classification, fail-closed pagination/error handling and founder Action Required alerts without auto-fabricating missing orders.
3. **Cron/RLS reconciliation correction** — PR #269 fixed false remote-only alerts caused by owner-scoped RLS when the cron ran as `tcg_api`; the fix used a narrow read-only `SECURITY DEFINER` function rather than weakening RLS. PR #271 aligned migration history to the production-applied version. PR #275 recorded the successful production monitor run: heartbeat healthy, Shopify remote=2/local=1/matched=1/remote-only=1/local-only=0, with the expected cancelled test-order webhook gap retained.
4. **Railway dead-service cleanup** — the unused `drop-rate-api` service was repurposed as the internal operations monitor; the accidental duplicate heartbeat service was removed. The historical zero-change staged patch was investigated and documented as non-actionable rather than fabricating an origin.
5. **`sale_intent` contract** — PR #259 documented FOR_SALE vs PERSONAL_COLLECTION, owner scope, status separation, idempotency/versioning, withdrawal behaviour and explicit relisting semantics.
6. **Recognition image-retention decision** — PR #260 documented the current ephemeral raw-recognition-image policy and explicitly deferred any future raw-image retention until a privacy/storage/rights review. No silent storage expansion was introduced.

PR #262 then recorded the resulting operations-monitor topology/status. The manual's instruction to do these reliability items before storefront expansion was therefore followed.

### 2. Storefront built in the manual's required order — COMPLETE THROUGH ENGINEERING, THEME PUBLICATION STILL GATED

The required order was `Collection/Browse → grouped-copy PDP → Shopify-native cart/checkout → simple name/collector-number search → Shopify-native customer accounts/orders`. That order was followed:

- **Collection / browse:** PR #263 introduced the first real-data responsive browse/game/set routes on the unpublished Brand Redesign theme.
- **Grouped-copy PDP:** PRs #264/#265 added deterministic grouping by Supabase `catalogue_id`, exact-copy sibling metadata and a bounded grouped-copy selector without changing owner attribution.
- **Exact-copy cart / Shopify checkout:** PR #266 locked customer quantity for unique physical-copy lines while preserving Shopify's native cart form, remove action and checkout.
- **Search v1:** PR #272 kept search Shopify-native and product-only, added last-term partial matching and customer-visible card/set/collector-number context. No AI/custom search index was introduced.
- **Customer accounts/order history:** PR #273 verified Shopify New Customer Accounts remain native and separate from Founder HQ / Seller Hub auth; guest checkout remains available.
- **Launch engineering QA:** PRs #276/#278 documented product/media/SKU/oversell/grouped-handle/search/account structural QA and kept theme publication gated on real visual preview.

This means the **base-commerce engineering sequence is complete**, but the Brand Redesign theme itself is still unpublished pending final preview/smoke approval.

### 3. Search & Discovery filters, set hygiene and browse structure — COMPLETE FOR CURRENT CATALOGUE

- PR #302 records the approved Shopify-native filter order: **Set → Price → Rarity → Variant → Availability → Condition → Language → Grading Company → Grade**.
- Filter values remain inventory-driven; empty languages/grades are not hard-coded merely to make them appear.
- PR #288 canonicalized the known One Piece set-label alias `Carrying on His Will` → `Carrying On His Will` at import intake so duplicate-looking filter values are not reintroduced.
- PR #303 completed mobile facet polish while preserving Shopify Search & Discovery: desktop facets expanded, mobile drawer facets collapsed by default unless active, with tighter mobile spacing.
- Dragon Ball products now use the same `drop_rate` metafields as Pokémon/One Piece, so Dragon Ball does **not** have a duplicate custom filter system.

### 4. Storefront visual system and mobile QA — COMPLETE FOR THE CURRENT DRAFT THEME, FINAL FULL-SMOKE STILL REQUIRED

The Brand Redesign theme was aligned to the current Drop Rate navy/blue/cyan/white/cool-grey visual system rather than the old colour direction:

- PR #289 — collection/browse visual alignment.
- PR #290 — PDP and grouped-copy visual alignment.
- PR #291 — exact-copy cart visual alignment.
- PR #292 — Shopify-native search visual alignment.
- PR #293 — native account/header visual alignment.
- PR #295 — homepage source-control/visual alignment.
- PR #297 — active global brand-layer cleanup so old late CSS overrides stopped flattening the newer components.
- PR #299 — active global theme settings/header/footer source-control and colour alignment.
- PR #301 — final machine-verifiable storefront gate.
- PR #303 — user-recording-driven mobile polish: card symmetry, browse-button positioning, removal of accelerated checkout from browse cards, rotating homepage spotlight, mobile facet behaviour, Copy 1/Copy 2 labels for grouped physical listings.
- PR #304 — status sync after the mobile QA polish and Search & Discovery configuration.

On 30 September, direct visual QA from the user's Shopify preview also produced these additional refinements on **Brand Redesign only**:
- `Fresh finds. New favourites.` and collection/header copy received a subtle optical left inset so headings do not feel flush to the viewport edge.
- Collection headers were made self-contained rather than relying on a homepage-only `.dr-wrap` declaration.
- card-number/set subtitle text is kept to one line with ellipsis so a long set name cannot push one product's purchase buttons lower than its neighbours.
- Nico Robin ACE 10 cert 590532 retains the exact authenticated ACE image file; only that product's gallery presentation is visually scaled inside the existing frame so the slab occupies a similar footprint to PSA slabs without altering the slab image itself.
- the exact runtime changes to `templates/index.json`, `dr-brand-discovery.liquid`, `dr-brand-collection.liquid`, `dr-card-title.liquid` and `_product-card-gallery.liquid` are source-controlled in the checkpoint PR rather than being left as Shopify-only drift.

### 5. Shopify catalogue publication and raw-quantity architecture — MAJOR MILESTONE COMPLETE

The starting point on 29 September was a large legacy linked-DRAFT backlog. We did **not** simply bulk-activate it.

- PRs #306/#307 created and production-verified a **read-only linked-draft readiness audit** so the backlog became an explicit work queue.
- PR #308 added controlled, resumable linked-draft reconciliation with exact identity, language, pricing, condition/grade, media, inventory, SKU, collection and compensation gates.
- Raw duplicate architecture was corrected so interchangeable raw cards appear as Shopify **quantity**, while Supabase remains the master record for every physical copy and owner:
  - PR #310 — DRAFT-only pooled raw inventory architecture.
  - PR #315 — fixed the production audit-permission blocker with narrowly scoped protected audit writers rather than granting broad table access.
  - PR #316 — safely published consolidated raw pools with re-lock/revalidation, remote Shopify verification, all-member transactional publication and compensation on DB failure.
- PR #318 fixed the `inventory_id` audit alias bug found during publication; failed attempts compensated back to DRAFT and did not falsely commit publication state.
- PR #319 changed the drain to DRAFT-only selection with bounded concurrency <=4 so it stopped reprocessing already-complete links.
- PR #320 recorded the production publication completion state after the main backlog drain.

The catalogue has since advanced further to the current verified state of **492 published physical links / 470 distinct live Shopify products / 0 drafts**.

### 6. Sealed-product safety contract — IMPLEMENTED, TWO CURRENT ITEMS INTENTIONALLY BLOCKED

The two One Piece sealed/collection items were not forced through card-oriented logic:

- PR #279 widened Media Intake to CARD/SEALED/COLLECTION.
- PR #281 recorded the production deployment/read-back.
- PR #282 enforced physical capture-context rules: sealed requires `SEALED_PRODUCT`, graded requires `GRADED_SLAB`, raw cards require the approved raw capture contexts.
- PR #283 recorded deployment verification.
- PR #284 defined the sealed Shopify contract: Sealed TCG Product type/tags/collection rules and `SEALED_PRODUCT` shipping key.
- PR #286 recorded production completion of that contract.

The current two sealed One Piece items remain deliberately unlinked because they still require exact physical package evidence, language/region confirmation, packed weight/dimensions and a real sealed shipping profile; the Portgas.D.Ace tin also still needs seal-status evidence. No guessed shipping dimensions or stock-facing media have been fabricated.

### 7. Graded-card publication and exact slab handling — COMPLETED WHERE EVIDENCE EXISTS

The graded-media path was tightened rather than bypassed:

- PR #324 allows exact inventory-bound official grading-provider slab media only for graded inventory that is already `VERIFIED_GRADED`, `OFFICIAL_PROVIDER`, `GRADED_SLAB`, APPROVED and VERIFIED. This does not create a general provider-media bypass for raw/sealed inventory.
- Exact PSA front/back media allowed the relevant Luffy/Galarian Obstagoon/Mega Charizard graded listings to advance through the normal backend publication path.
- Charizard V PSA 9 was permitted to use the correct current card-art image under an explicit founder media exception because PSA cert 62398872 confirms identity/grade but provides no slab scan; the exact-slab replacement Action Required remains open.
- Nico Robin OP01-017 ACE 10 cert **590532** now uses the exact ACE front slab. On 30 September the founder explicitly approved storefront publication with the exact ACE front while retaining the missing-back Action Required. The backend recorded the graded review/audit state and the normal reconciliation worker published it at **£51.61**.
- That publication moved Shopify from 469 ACTIVE / 1 DRAFT to the current **470 ACTIVE / 0 DRAFT** state. The original ACE image remains unmodified; only Brand Redesign presentation scale was adjusted for visual consistency.

### 8. Dragon Ball/CardTrader backlog — 27/35 PHYSICAL ITEMS LIVE, 8 EXACT-PRINT EXCEPTIONS REMAIN

The Dragon Ball work was undertaken as a **narrow storefront-unblocking backlog fix**, not as a new market-data expansion. It respected the manual freeze by reusing the existing import/media/Shopify pipelines and keeping all provider decisions fail-closed.

Merged work:
- PR #326 — read-only CardTrader API client + fail-closed exact-media resolver for Dragon Ball Super Masters / Fusion World; provider media starts PENDING and cannot infer physical language.
- PR #327 — one-shot backlog runner, probe/read-only by default, explicit apply required.
- PR #328 — normalized CardTrader's live `{"array":[...]}` response wrappers and blueprint-keyed marketplace payloads.
- PR #330 — normalized `&` vs `and` set aliases while retaining exact set/printing gates.
- PR #331 — hardened promo-name/pre-release comparison without weakening collector-number or physical-language gates.
- PR #332 — required exact Fusion World Tournament Pack version proof.
- PR #333 — allowed a very narrow Masters-only bare numeric collector suffix fallback when set/name/language/finish **and provider rarity** all agree.
- PR #334 — recorded the verified Dragon Ball publication result.

Production result:
- **27 / 35 physical Dragon Ball FOR_SALE items are published**, represented by **25 Shopify products** because two pairs are intentionally pooled as quantity-2 listings.
- The final ordinary Masters cards resolved safely: BT18-067 Krillin, BT18-138 Reaper's Cunning and BT13-142 Dark King Mechikabura.
- Exactly **8** remain unlinked:
  - Dawn of the Z-Legends pre-release: BT18-004, BT18-018, BT18-025, BT18-043, BT18-044.
  - Supreme Rivalry pre-release: BT13-131.
  - Nappa FP-046 imported as Tournament Pack 07, while CardTrader exposes Pack 08.
  - Vegeta FB05-039 imported as Tournament Pack -Winner- 06, while CardTrader exposes ordinary Pack 06.
- These are deliberately blocked on exact-print proof/media. Similar base-set/promo art was not substituted.
- Bandai's official database was used only as identity/reference evidence during investigation; because its site prohibits unauthorized image/data reproduction, it was **not** turned into a storefront-image provider.

### 9. Dragon Ball storefront merchandising/navigation — COMPLETE FOR CURRENT LIVE INVENTORY

Before 30 September, Dragon Ball products existed but did not have Pokémon/One Piece-equivalent browse structure. This has now been corrected on the Brand Redesign storefront:

- Dragon Ball top-level navigation now includes **Shop All Dragon Ball, Singles, Graded Cards, Series and Sets**.
- Series routes: **Dragon Ball Super Masters** and **Dragon Ball Super Fusion World**.
- Current set/promo routes: **Beyond Generations, Dawn of the Z-Legends, Perfect Combination, Power Absorbed, Prismatic Clash, Supreme Rivalry, Three Glorious Fighters, Tournament and Championship Promos, Wish For Shenron**.
- All 13 newly created Dragon Ball collection routes were verified as published to the Online Store.
- Dragon Ball uses the same existing Set/Price/Rarity/Variant/Availability/Condition/Language/Grading Company/Grade filter contract as the rest of Drop Rate.
- Current Dragon Ball inventory is English; grader/grade filter values will remain empty until graded Dragon Ball stock exists rather than being hard-coded.

### 10. Storefront title/SEO presentation cleanup — COMPLETE FOR IDENTIFIED DUPLICATION

To improve grid symmetry without sacrificing search identity:
- 3 Dragon Ball visible titles were shortened first: Son Goku : DA, Vegeta (Mini) : DA and Tien Shinhan.
- A subsequent store-wide audit identified 37 affected One Piece presentation titles where collector number/source wording was duplicated in the visible name and the separate card-number/set subtitle.
- **40 visible Shopify product titles in total** were cleaned without changing canonical Supabase card identity.
- Meaningful distinctions such as Reprint, Alternate Art, Parallel, Zoro Deck, 3rd Anniversary and Premium Card Collection were retained where useful.
- Collector number, set, language, rarity/variant and full searchable identity remain in the `drop_rate` metafields/backend data. A post-change audit checked all 40 affected Shopify products: 39 already retained the collector number in their explicit SEO title; Nico Robin ACE 10 was the only exception, so its SEO title was explicitly corrected to `Nico Robin OP01-017 ACE 10 | One Piece | Drop Rate`. The cleanup changed presentation copy, not canonical identity.
- The card subtitle now uses one-line ellipsis so long set names do not create uneven purchase-button rows.

### 11. Rights, provenance and provider safeguards — FOLLOWED

- We did not assume scraping permission.
- CardTrader was integrated through its authenticated API.
- TCGGraph exact-listing rights policy was narrowed in PR #321 to product-sale listing use only, with PENDING human review, exact-match gates and no social/generic SEO/AI-training reuse.
- PR #322 added provider-exact identity fallback only when one language returns a unique deterministic exact printing; zero/multiple/API-error cases fail closed.
- Provider media never silently overrides physical language, condition, grade, ownership or price.
- Bandai images were not reused after the provider's reproduction restriction was identified.
- Historical observations/audit history were not destructively rewritten.

### 12. Security, audit and failure behaviour preserved

Across the 29–30 September work:
- Supabase/Postgres remains the source of truth for physical inventory, ownership and financial attribution.
- Shopify remains the storefront/cart/checkout/customer surface.
- FastAPI remains the deterministic rule layer.
- n8n was not used as a database or as a substitute for business rules.
- RLS was not weakened to make cron jobs easier; narrow `SECURITY DEFINER` functions were used where required.
- publication paths verify Shopify remotely before committing PUBLISHED state.
- failed publication/pooling operations compensate back to safe Shopify state.
- pooling never discards physical Inventory IDs or owners.
- graded/high-value/ambiguous exact-print cases remain human-review/fail-closed.
- migrations were version-controlled; historical migration rows were not destructively rewritten.
- secrets were kept in Railway and were not printed during CardTrader probing.
- tests/docs/status were kept with the implementation PRs; the current direct Brand Redesign visual tweaks are being brought back into GitHub in this checkpoint PR so there is no runtime-only theme drift.

### 13. Claude operating-manual compliance audit

**Followed:**
- storefront-first priority;
- immediate reliability fixes before storefront expansion;
- required storefront build order;
- no destructive production/data-history changes;
- one concern per implementation PR, with superseded attempts closed rather than force-pushed into history;
- schema changes through versioned migrations;
- Supabase source of truth / FastAPI deterministic logic;
- no AI/provider silent override of identity/ownership/price;
- no new external owner/consignor activation;
- no broad eBay expansion;
- no autonomous merchandising/SEO/marketing automation before storefront launch;
- human exception handling for ambiguous/high-risk items;
- live Horizon left untouched while Brand Redesign was iterated as the launch candidate.

**Narrow exceptions to the freeze, consistent with the manual's bug/storefront allowance:**
- CardTrader/TCGGraph work was limited to resolving the already-existing storefront publication backlog and exact-media/identity defects; it was not a new pricing-provider or cross-channel expansion.
- sealed-media and graded-slab changes were fixes to existing publication paths, not new product-scope expansion.
- pooling was required to correct the storefront representation of already-owned duplicate raw inventory before launch.

**Still frozen until storefront milestone is explicitly reopened:**
- new recognition capabilities beyond existing correctness fixes/corpus work;
- new Seller Hub features;
- new market-data providers/pricing expansion;
- new automation/outbox event types and autonomous n8n growth;
- eBay/cross-channel expansion;
- autonomous SEO/CRO/marketing experimentation.

### 14. Overall milestone position after this work

- **Milestone 1 — three-founder inventory/ownership:** internal architecture, owner-safe inventory and ownership tracking are effectively complete, but the final release proof still requires onboarding the genuine third founder and repeating cross-owner production isolation verification. No external owner/consignor activation has been silently opened.
- **Milestone 2 — approved inventory → Shopify → sale → correct owner attribution:** technically far advanced. Real Shopify sale/refund/restock and deterministic settlement reporting already exist; the 29–30 September work has now made the catalogue/storefront side launch-ready at 470 live products. Remaining production proof is the final Brand Redesign launch smoke plus real multi-owner/same-card attribution under the pooled model and eventual live Stripe payout cutover. Automatic money movement remains intentionally locked behind verified settlement controls.
- **Milestone 3 — automated valuation/recommended pricing:** infrastructure exists, but provider-by-provider production market-data activation remains intentionally gated. The CardTrader work in this checkpoint was exact identity/media support for storefront backlog, not a reopening of automated pricing-provider expansion.
- **Consignment:** core architecture/status model exists in the wider roadmap, but full customer-facing consignment rollout remains after the storefront/current commerce milestone.
- **Seller Hub:** the existing deployed seller-safe surfaces remain, but the requested future flow — Shopify signup/purchase → Seller Hub invitation → purchased cards automatically added to portfolio — remains intentionally deferred under the storefront-first freeze.
- **AI listings/customer service/SEO/marketing:** not reopened. No autonomous CRO/A/B-testing, AI marketing, social publishing or large-scale SEO automation has been activated before the base storefront goes live and proves stable.
- **n8n:** the signed-event/outbox foundation from 28 September remains dormant by design; no new event types/workflows were added during this storefront-first period.
- **eBay/cross-channel:** deployed groundwork remains production-dormant and no new expansion was performed during the freeze.
- **Recognition:** correctness/bug fixes already shipped are preserved, but new recognition feature scope remains frozen until storefront milestone reopening.

### 15. Remaining work / next exact order

1. **Final authenticated Brand Redesign smoke QA** — complete a full mobile and desktop pass through homepage → collection → filters/sort → PDP/grouped copies → exact-copy cart → native checkout entry → search/no-result → customer account/order-history handoff, including the 30 September spacing/title/Nico-image polish.
2. **Publish Brand Redesign theme only after that smoke is approved.** Horizon remains MAIN until then.
3. **Immediately run post-publication live smoke/reconciliation**: navigation, filters, cart stock, checkout handoff, account/login, exact-copy/pooled stock behaviour, Shopify↔Supabase ownership/link parity.
4. **Resolve the 17 unlinked FOR_SALE items without guessing:**
   - 8 Dragon Ball exact-print media exceptions;
   - 7 One Piece raw cards requiring exact physical language/media/variant proof;
   - 2 sealed One Piece items requiring exact package media + language/region + packed dimensions/weight + sealed shipping profile/seal-status evidence.
5. **Resolve the two expected Shopify webhook-gap HIGH alerts** or formally close them when their known test-order status is reconciled.
6. **Graded media follow-up:** obtain exact replacement slab/back evidence for the two remaining `GRADED_SLAB_MEDIA_REQUIRED` exceptions where possible; do not substitute another slab.
7. **GitHub housekeeping:** close stale open PRs that have been superseded by merged production work (#309, #311–#314, #317, #325) after confirming none contains unique unmerged content.
8. Once Brand Redesign is live and stable, **explicitly reopen the manual's deferred workstreams** in priority order rather than automatically resuming all of them at once.
9. **Deferred graded-slab scanner architecture — APPROVED BACKLOG:** when recognition/Seller Hub scope is explicitly reopened, add a scanner choice for **Raw Card / Graded Slab** across Founder HQ and the future Seller Hub/mobile app. Graded Slab mode must detect the grader, read the certificate/serial, route through a grader adapter, verify the exact graded identity where permitted, store grader + grade + cert directly on the physical Inventory Item, attach exact official slab media where permitted/available, and require human confirmation before commit. Initial grader targets are **PSA, ACE, CGC, TAG and BGS/Beckett**. PSA has an official cert API and is the first full automation target; TAG should support certificate/QR → DIG report verification, TAG Score and grader-specific digital evidence through a permitted integration path; ACE/CGC should use provider verification only through permitted machine access; BGS remains adapter-ready but automatic lookup must stay disabled unless Beckett provides/approves machine access rather than bypassing its verification protections. Preserve BGS half grades/subgrades including 9.5 and Black Label 10, and preserve TAG's provider-specific score/metrics as evidence rather than flattening them into the core grade. Full design: `docs/GRADED_SLAB_SCANNER_ARCHITECTURE.md`.


## 2026-09-30 — Founder-requested post-storefront roadmap additions

**ROADMAP RECORDED / NOT YET COMPLETE —** the following founder-requested capabilities must remain visible in the build plan. They are not considered completed by the current storefront milestone and should be scheduled explicitly after the Brand Redesign launch is stable, unless a blocking bug requires earlier work.

### Sealed-product commerce and intelligence

- **Publish sealed products to Shopify:** complete the physical-input gate for current and future sealed inventory, including exact package media, language/region, seal status, packed weight/dimensions, shipping profile, pricing and Shopify collection/product presentation. Do not guess shipping dimensions or reuse card-oriented media rules.
- **Sealed-product scanning/recognition:** extend intake so the platform can recognise sealed boxes, booster boxes, tins, collections and other supported sealed products from images/scans. Recognition must remain confidence-scored and fail closed for ambiguous/high-value products.
- **Sealed-product market valuation:** extend the pricing/market-data layer so sealed products have deterministic market value, recommended retail, quick-sale and acquisition-price outputs using permitted provider data. Sealed valuation must remain separate from raw/graded-card assumptions where liquidity, pack count, product configuration or region materially differ.

### Seller Hub / mobile application

- **Seller Hub as full desktop + mobile product:** turn Seller Hub into a complete responsive desktop experience plus purpose-built iOS and Android apps, usable end-to-end on a phone rather than relying on a partial mobile web workflow.
- The native mobile app should continue to use the existing FastAPI/Supabase backend rather than becoming a separate source of truth.
- Core mobile flows should include camera/scanner intake, inventory management, pricing/value views, Action Required, sales/channel state, portfolio, payouts/settlements and account/profile operations.

### Multi-channel commerce expansion

- **Connect Whatnot, Cardmarket and TCGplayer** as additional sales channels alongside Shopify and the existing dormant eBay groundwork.
- Each channel must use a replaceable adapter and backend API contract; n8n must not own inventory truth or allocation logic.
- Cross-channel stock must remain Inventory-ID/owner aware and idempotent so one physical item cannot be oversold across Shopify/eBay/Whatnot/Cardmarket/TCGplayer.
- Channel expansion remains gated behind provider/platform terms, available official APIs/authorised integrations, credentials, webhook/order support and seller-account approval. Do not assume scraping or unsupported automation is permitted.

### Shopify customer → Seller Hub conversion

- **Offer Seller Hub signup to Shopify customers:** when a customer provides an email by creating a Shopify account or making a purchase, present a clear invitation to create a Drop Rate Seller Hub account and explain the value proposition.
- After a customer explicitly signs up/links the account, eligible purchases should be associated with that Seller Hub identity and purchased cards should be added to their portfolio automatically without transferring physical ownership records incorrectly.
- Customer/storefront auth must remain separate from founder/admin permissions; do not silently create privileged Seller Hub accounts from checkout alone.
- Consent, email matching/account linking, duplicate-account handling, refunds/returns and privacy rules must be defined before automatic portfolio import is enabled.

### Founder Dashboard + Seller Hub simplification

- **Simplify both Founder Dashboard and Seller Hub:** reduce complexity, duplication and unnecessary controls so routine inventory/sales work is fast and obvious on desktop and mobile.
- Prioritise common actions, clear status, search/filtering, compact card grids, Action Required exceptions and context-aware controls rather than exposing internal system complexity.
- Keep founder/admin-only capabilities clearly separated from seller/consignor/customer-safe functionality.

### Hardware / scanner / printer integration

- **Allow sellers/founders to connect supported printers and scanners** from Seller Hub / Founder Dashboard.
- Support direct card intake from compatible scanners/cameras into the normal inventory/recognition pipeline rather than creating a separate unmanaged import path.
- Add a Device Bridge / local connector architecture for hardware that requires local desktop/mobile access.
- Printer support should cover useful operational workflows such as labels, inventory IDs, order/pick labels or other approved fulfilment outputs.
- Hardware integrations must preserve authenticated user/owner context, audit events, duplicate protection and explicit device permissions.


### Recognition corpus / massive canonical card database

- **Build a large governed recognition corpus so the scanner can recognise cards that have never previously been scanned by Drop Rate.**
- The corpus must be organised around canonical card/printing identity rather than a loose image folder. Each supported printing should be capable of carrying:
  - game/line;
  - set/expansion;
  - canonical card name;
  - collector number;
  - rarity;
  - variant/parallel/promo/event printing;
  - language;
  - foil/finish;
  - provider/reference IDs;
  - permitted reference media/fingerprints;
  - image hashes/visual embeddings where appropriate;
  - human-confirmed corrections;
  - confidence/evidence history.
- Initial supported families remain Pokémon, One Piece, Dragon Ball, Naruto and Riftbound, with future games added through modular adapters/corpus packs.
- The scanner must not depend only on examples already seen by Drop Rate. Recognition should compare a new scan against the broader corpus plus deterministic metadata/provider evidence.
- High-value, promo, parallel, pre-release, winner, event, graded or otherwise ambiguous exact printings must remain fail-closed and go to Action Required when evidence is insufficient.
- Human-confirmed corrections should improve future recognition, but only confirmed outcomes may enter the governed learning loop.
- Raw recognition images remain subject to the existing retention/privacy/rights policy. The corpus should prefer durable fingerprints/embeddings/reference metadata where rights/storage policy permits rather than becoming an uncontrolled image archive.
- n8n may orchestrate corpus ingestion/enrichment jobs, but canonical identity, mappings, fingerprints and recognition state belong in Supabase/object storage/FastAPI rather than inside n8n.

### Dragon Ball storefront media quality / high-resolution image programme

- **Audit every live Dragon Ball storefront image for quality, exact-print correctness and resolution.**
- Current Dragon Ball CardTrader images are materially lower quality than the Pokémon/One Piece catalogue and must be treated as an interim source where no better legitimate exact-print media exists.
- Target high-resolution / approximately 4K-quality presentation where a legitimate exact-print source or first-party capture is available.
- Do not upscale with generative reconstruction that changes card text/artwork/printing details. Any enhancement must preserve the exact source image faithfully.
- Prefer, in order where permitted and exact:
  1. first-party high-resolution physical capture;
  2. official grading-provider slab scan for graded cards;
  3. rights-cleared/permitted exact-print provider media;
  4. existing lower-resolution provider media only as a temporary fallback.
- Add an image-quality audit/remediation queue for low-resolution, incorrect crop/aspect, missing slab back, wrong printing and replacement-available cases.
- Extend the same quality standard to other games when poorer legacy media is found; Dragon Ball is the first priority.

### Planned n8n automation programme

n8n remains the orchestration layer only. Supabase/Postgres remains the source of truth and FastAPI remains the deterministic business-rule layer. AI may assist inside workflows but must not silently alter canonical identity, ownership, price, settlement or financial truth.

Planned automations/workflows:

1. **New card intake** — react to new founder/seller inventory and call the normal backend intake pipeline with owner context, Inventory ID, media state and next required step.
2. **Bulk card import** — orchestrate Collectr/CSV/bulk imports, deduplication, deterministic physical-quantity expansion and exception routing.
3. **AI card identification** — send captured/scanned cards through recognition and route low-confidence/high-value results to Action Required.
4. **Recognition corpus enrichment** — after human confirmation, add governed metadata/fingerprints/corrections to the canonical recognition corpus so future unseen-card scans improve.
5. **Sealed-product recognition** — process booster boxes, tins, decks, collections and other sealed products through a sealed-specific identification pipeline.
6. **Inventory status changes** — react to APPROVED/LISTED/RESERVED/SOLD/RETURNED etc. and trigger only valid downstream workflows.
7. **Market-data ingestion** — periodically request permitted pricing/sales data from configured provider adapters.
8. **Market-data normalisation** — normalise source/currency/shipping/condition/grade/language/sold-vs-listed/timestamp/provenance.
9. **Pricing recalculation** — call FastAPI pricing rules when meaningful new evidence arrives; produce Market Value, Recommended Retail, Quick-Sale and Target Acquisition prices.
10. **Sealed-product valuation** — run sealed-specific price/market workflows with region/configuration/liquidity-aware inputs.
11. **Shopify product creation** — once backend readiness passes, create the Shopify product/media/metafields/collections/SEO/inventory linkage.
12. **Shopify product updates** — synchronise legitimate backend changes without making Shopify the master record.
13. **Shopify order processing** — consume verified webhooks idempotently and reconcile order state against Supabase.
14. **Multi-owner order allocation** — route sold line items through deterministic Inventory → Owner → Fees/Commission → Net Proceeds allocation.
15. **Refunds/returns/cancellations** — reverse the correct inventory/financial state and return items to inspection when required.
16. **Founder/consignor settlement preparation** — generate deterministic settlement reports, balances, commissions, deductions and amount owed.
17. **Payout monitoring** — watch scheduler health, payout requests, reconciliation and discrepancies; create Action Required exceptions rather than silently moving money.
18. **Consignment submissions** — intake customer submissions and initialise the SUBMITTED → RECEIVED workflow.
19. **Consignment processing** — orchestrate RECEIVED → INSPECTION → APPROVED → LISTED and exception handling.
20. **Consignment sale/settlement updates** — update consignor visibility for sale, commission, amount owed and settlement state.
21. **Cross-channel publishing** — controlled publishing to Shopify/eBay/Whatnot/Cardmarket/TCGplayer through replaceable channel adapters.
22. **Cross-channel inventory protection** — on sale/reservation, immediately reserve/zero/withdraw the same physical stock from other channels.
23. **Cross-channel order reconciliation** — compare channel orders/listings against Drop Rate and alert on mismatches without fabricating financial state.
24. **Shopify customer → Seller Hub invitation** — after customer account creation/purchase/email capture, send a clear invitation explaining Seller Hub and its value.
25. **Purchase → Seller Hub portfolio** — after explicit account linking, add eligible purchased cards to the customer's portfolio and handle refunds/returns safely.
26. **New-stock marketing triggers** — detect grails, significant new inventory, set drops and noteworthy restocks.
27. **Price-movement/trending triggers** — surface meaningful market moves/trends as internal events using deterministic thresholds before AI interpretation.
28. **AI product listing copy** — generate titles/descriptions/SEO/tags/alt text only from confirmed database facts.
29. **SEO maintenance** — identify weak/missing metadata, internal-linking gaps, collection/set content gaps and indexing issues.
30. **SEO/CRO experimentation** — after sufficient traffic, propose/run controlled A/B tests for collection layouts, CTA copy, product-card layout and conversion flow with measurable rollback-safe results.
31. **AI creative generation** — Event → AI brief → Higgsfield/Banana Pro → creative/caption/CTA → approval.
32. **Social publishing** — publish approved social content on schedule and record source event/inventory/campaign linkage.
33. **Customer email lifecycle** — welcome, post-purchase, back-in-stock, portfolio onboarding, relevant recommendations and lifecycle follow-up.
34. **AI customer service** — resolve routine order/product/policy questions using live permitted context; escalate disputes/refunds/financially sensitive issues.
35. **Recommendations** — recommend relevant cards/products from real catalogue/inventory/purchase/portfolio data rather than generic AI guesses.
36. **Inventory intelligence** — surface ageing stock, low stock, high-value inventory, fast sellers, slow movers, liquidity issues and acquisition opportunities.
37. **Founder/seller daily briefing** — summarise sales, valuation changes, Action Required, consignments, inventory and operational exceptions.
38. **Analytics automation** — maintain sales/channel/inventory/owner performance datasets and surface meaningful changes automatically.
39. **Image-quality audit automation** — detect low-resolution images, incorrect crops/aspect, missing slab backs and replacement-available media; Dragon Ball is first remediation target.
40. **Error/exception alerts** — API failures, Shopify sync failure, provider failure, duplicates, missing owner, webhook gaps, settlement discrepancies, recognition uncertainty and other operational faults into Action Required.
41. **Hardware workflow triggers** — receive scanner/device captures into the normal intake/recognition path and send approved printer jobs for labels/fulfilment.
42. **Operational monitoring** — heartbeat/health checks for n8n, backend jobs, payouts, marketplace integrations and other critical scheduled workflows.

Preferred automation activation order after storefront launch:
**inventory/intake → Shopify/order/reconciliation → pricing/market data → Seller Hub/customer portfolio → consignments → cross-channel → customer lifecycle → SEO/CRO → AI marketing/social.**

### Additional deferred product/workstream items already discussed

- **Third-founder completion:** onboard the genuine third founder and repeat production cross-owner isolation verification to finish the final Milestone 1 release gate.
- **Real multi-owner commerce proof:** production-test a same-order/multi-owner or pooled-stock sale through allocation, refund and settlement reporting.
- **Live payout cutover:** keep automatic money movement locked until settlement/reconciliation is fully production-proven and explicitly approved.
- **Consignor portal/full consignment rollout:** submissions, status tracking, listed stock, sales, commission, amount owed and settlement visibility.
- **Seller Hub portfolio:** inventory value, top-valued cards, weekly movers, sales/channel state, payout tracking and portfolio performance.
- **Shopify-customer portfolio ownership experience:** customers who buy from Drop Rate should be able to claim/link purchases into Seller Hub after explicit signup.
- **Mobile-first scan experience:** full-screen camera, rapid capture, batch totals, manual capture fallback, correction flow and unresolved queue.
- **Desktop/mobile UX simplification:** fewer internal/technical controls, compact grids, better defaults, clear common actions and a strong Action Required workflow.
- **Device Bridge:** local desktop/mobile bridge for supported scanners, label printers and other hardware that browsers cannot securely access directly.
- **One-click cross-listing:** once channels are authorised, list eligible stock to selected marketplaces while backend ownership/inventory remains authoritative.
- **Channel dashboard:** seller-facing visibility of Shopify/eBay/Whatnot/Cardmarket/TCGplayer state without exposing unsafe channel controls.
- **Recommendations and collection intelligence:** customer-facing recommendations plus founder-facing acquisition/stock intelligence.
- **Native notifications:** mobile push/email/in-app notifications for sales, payouts, price movement, Action Required and significant inventory events.
- **AI product listings:** controlled generation of product copy after canonical identity/pricing/media are confirmed.
- **AI customer service:** routine support automation with human escalation.
- **SEO programme:** collection/set/card metadata, internal linking, structured content and Search Console-style issue handling based on real database facts.
- **CRO programme:** controlled A/B testing only after enough real traffic/conversion data exists.
- **AI marketing programme:** new grails, new inventory, price movements, trending cards, new sets, major sales, low stock and collection drops.
- **Analytics/optimisation:** founder dashboards for revenue, profit, inventory turn, owner performance, channel performance and campaign attribution.
- **Data/provider expansion:** additional legitimate market/reference providers only after source-by-source terms, rights, API quality and economics are reviewed.
- **Recognition performance:** parallelism, fingerprint caching, short-circuiting, per-stage timing and corpus-quality metrics after the storefront freeze is explicitly reopened.
- **Counterfeit/risk review:** retain a human-review path for suspicious cards/products rather than treating AI confidence as authenticity proof.
- **Backups/dev-prod/security hardening:** maintain separate environments, RLS/RBAC, secure secrets, webhook verification, audit logs, recovery/backups and controlled migrations as the platform grows.

### Sequencing note

These items are now part of the official roadmap but **do not override the current storefront-first launch gate**. Immediate order remains: final Brand Redesign smoke QA → publish Brand Redesign → post-launch verification → resolve remaining storefront inventory exceptions. After that, explicitly reopen deferred workstreams in controlled phases rather than building all roadmap items simultaneously.


## 2026-09-30 — Dragon Ball publication final production verification

**PRODUCTION VERIFIED —** the CardTrader Dragon Ball backfill/publication pass is complete for every exact printing the current permitted provider data can prove. Production now has **27 / 35 Dragon Ball physical FOR_SALE items published**, represented by **25 live Shopify products** because two duplicate physical copies are intentionally pooled into quantity-2 listings.

The final three ordinary Masters cards with CardTrader bare numeric collector-number suffixes are live after the narrow rarity-guarded matcher was deployed: BT18-067, BT18-138 and BT13-142. The production safety rules remain fail-closed and do not extend that suffix fallback to Fusion World or promo cards.

Exactly **8 Dragon Ball physical items remain intentionally unlinked**:
- Dawn of the Z-Legends pre-release: BT18-004, BT18-018, BT18-025, BT18-043 and BT18-044.
- Supreme Rivalry pre-release: BT13-131.
- Fusion World promos: Nappa FP-046 imported as Tournament Pack 07 and Vegeta FB05-039 imported as Tournament Pack -Winner- 06.

CardTrader does not provide exact-print proof for those eight. Production diagnostics show FP-046 only as Tournament Pack 08 and FB05-039 only as ordinary Tournament Pack 06; the six Masters pre-release records only resolve to ordinary base-set blueprints without pre-release evidence. The system therefore correctly refuses visually similar substitute art. Each unresolved printing has an OPEN `MEDIA_UNRESOLVED` Action Required record and requires an exact permitted provider source or first-party physical-card capture before normal Shopify bootstrap/publication.

Shopify production is now **469 ACTIVE products / 469 Online Store-published products**, with **1 DRAFT** product (the known Nico Robin OP01-017 ACE 10 review hold) and **22 ARCHIVED** zero-stock/redundant shells. No duplicate Shopify product shells exist for the eight unresolved Dragon Ball cards.

## 2026-09-30 — CardTrader Masters bare collector-number suffixes

**SOURCE-CONTROL PR IN PROGRESS —** final production diagnostics found three ordinary Masters
cards that are present on CardTrader with exact set/name/language/rarity/image evidence, but
CardTrader stores their collector numbers as bare numeric suffixes rather than full BT codes:
BT18-067 -> 067, BT18-138 -> 138 and BT13-142 -> 142. A narrow matcher is being added for
Masters `BTxx-yyy` only; it requires the numeric suffix and explicit provider rarity to agree.
Fusion World/promos cannot use the fallback.

The main Dragon Ball publication pass is already live: 24 physical Dragon Ball items map to
22 ACTIVE Shopify products, including two correct quantity-2 pooled listings. Shopify reports
466 ACTIVE products and 466 Online Store-published products after this release. Eleven
Dragon Ball items remain unlinked while exact-print media is unresolved; this fix targets
only the three ordinary Masters cards within that exception set.

## 2026-09-29 — Fusion World tournament-promo proof

**SOURCE-CONTROL PR IN PROGRESS —** a production CardTrader Blueprint diagnostic showed that
the local tournament-promo cards live under provider expansion `Fusion World Promos` (3678),
not `Tournament & Championship Promos` (4300). The resolver is being narrowed to that
production mapping while requiring the local Tournament Pack label to agree with the Blueprint
version. This allows exact Pack 07 matches but deliberately blocks Nappa FP-046 (local Pack 07,
provider Pack 08) and Vegeta FB05-039 (local Winner 06, provider ordinary Tournament Pack 06).
No inventory/media mutation occurred during the diagnostic.

## 2026-09-29 — CardTrader printing safeguards rebased on current main

A clean follow-up hardens the production-tested Dragon Ball matcher without relaxing identity:
Collectr promo-name suffixes may be removed only from the name comparison, collector number
remains mandatory, and a local pre-release card may fall back to a base expansion only when
the Blueprint version itself explicitly proves a pre-release printing. Current CardTrader data
does not provide that proof for the six outstanding pre-release copies, so they remain blocked.
This branch is rebased on current `main` after the earlier PR conflicted with concurrent
CardTrader/status changes.

## 2026-09-29 — Dragon Ball CardTrader set-alias verification

Production CardTrader diagnostics confirmed the Fusion World local set `Tournament and Championship Promos` maps to provider expansion `Tournament & Championship Promos` (ID 4300). The adapter now normalizes ampersand/word-`and` equivalence while retaining exact set matching.

CardTrader diagnostics also confirmed the six local pre-release cards (five Dawn of the Z-Legends + one Supreme Rivalry) only appear under ordinary base-set blueprints with no pre-release marker in CardTrader's blueprint metadata. Those six are therefore explicitly left unresolved rather than receiving the normal-print image. No production inventory/media mutation occurred during these diagnostics.

## 2026-09-29 — CardTrader production response wrapper fix

The first production Dragon Ball CardTrader probe authenticated successfully enough to reach provider endpoints but exposed a live response-shape difference: `GET /games` returns `{"array": [...]}` for this account, while `GET /expansions` returns the documented bare list. Marketplace products are also keyed by Blueprint ID per CardTrader's API reference. A focused client compatibility fix now normalizes these shapes and keeps unknown/missing wrappers fail-closed. No Dragon Ball inventory or media was mutated by the failed probe.

## 2026-09-29 — Dragon Ball CardTrader one-shot backfill runner

**SOURCE-CONTROL PR IN PROGRESS —** a dedicated management runner now exists for the 35-card Dragon Ball backlog. It reuses the existing import-enrichment core rather than duplicating identity/media business rules. The runner defaults to read-only `probe` mode and requires explicit `apply` mode before any enrichment mutation.

The current production batch is `8f10fd72-b3d9-475a-9598-ce21503ffd98` and contains 29 Dragon Ball Super Masters + 6 Dragon Ball Super Fusion World FOR_SALE items. The founder explicitly confirmed all 35 physical copies are English. Production `drop-rate-api-live` now has `TCG_CARDTRADER_API_TOKEN` configured and the token deployment succeeded. The next execution sequence is: CI/merge runner → one-shot worker probe against representative Masters/Fusion World cards → if exact provider payloads validate, apply existing enrichment to all 35 → human review exact CardTrader media candidates → normal Shopify bootstrap/publication.

## 2026-09-29 — CardTrader Dragon Ball exact-media Route B

**SOURCE-CONTROL PR IN PROGRESS / PRODUCTION TOKEN NOT YET CONFIGURED —** the catalogue is now at **464 PUBLISHED physical inventory links / 444 distinct live Shopify products**. The 20-link difference remains intentional pooled raw quantity. Shopify has one remaining production DRAFT product: Nico Robin OP01-017 ACE 10. There are 44 unlinked FOR_SALE items: 35 Dragon Ball, 7 One Piece raw and 2 sealed One Piece.

The 35 Dragon Ball cards are split into 29 Dragon Ball Super Masters and 6 Dragon Ball Super Fusion World. They already have sale price, Near Mint condition and registered storage location. Their remaining common blockers are confirmed physical language plus exact permitted storefront media.

A read-only CardTrader provider path is being added as Route B so these cards do not depend on the paid TCGGraph subscription. CardTrader's official API exposes Games, Expansions, Blueprints and Blueprint `image_url` values, and its terms explicitly permit API use for inventory management on other sales channels. The adapter is fail-closed: Masters/Fusion World isolation, exact expansion, exact normalized name, collector-number evidence, supported normal/foil family, unique Blueprint and a CardTrader-owned HTTPS image host are all mandatory. Missing/ambiguous evidence creates no media.

CardTrader is **not** used to infer the language of Drop Rate's physical copy. The existing import enrichment default-language flow remains the deterministic way to record a founder/admin-confirmed batch language. CardTrader provider media is inserted only as `PENDING`, never auto-approved or auto-published.

Production currently has no `TCG_CARDTRADER_API_TOKEN`. After CI/merge/deploy, the external cutover gates are: configure a CardTrader Bearer token from the CardTrader account settings, confirm the physical language of the 35 Dragon Ball copies, run enrichment, review exact media candidates, then use the normal Shopify bootstrap/publication pipeline.

Charizard V 019/189 PSA 9 is now ACTIVE using its current correct card-art image under an explicit founder media override because PSA cert 62398872 returns the correct MINT 9 identity but no provider slab scans. The exact-slab replacement Action Required remains open. Both Luffy slabs (ST10-006 PSA 9 English and P-001 [25th] PSA 10 Japanese) are PUBLISHED with exact PSA front/back media and verified graded audit history. Nico Robin ACE 10 cert 590532 now has the exact ACE front-slab image registered, approved, Shopify-ready and attached as the draft's featured image; identity/language and founder graded-review state remain intentionally unresolved.

## 2026-09-29 — Official graded-slab bootstrap gate

**SOURCE-CONTROL PR IN PROGRESS —** catalogue bootstrap currently excludes cert-linked grading-provider slab media because the inventory-media branch only accepts `FIRST_PARTY_CAPTURE`. This blocked the already founder-verified Monkey D Luffy P-001 Japanese PSA 10 even though exact PSA cert 165543324 FRONT/BACK media is approved, rights-verified and Shopify-ready.

The bootstrap media gate is being narrowed to also accept an exact `INVENTORY_ITEM` asset only when the inventory is a graded card, both grader and grade are present, `condition_review_status='VERIFIED_GRADED'`, `source_type='OFFICIAL_PROVIDER'`, and `capture_context='GRADED_SLAB'`. Raw-card and sealed-product rules are unchanged; official provider media does not become a general storefront-media bypass.

Production also advanced Monkey.D.Luffy ST10-006 English PSA 9 to `VERIFIED_GRADED` from explicit founder approval and published its existing £35 Shopify draft successfully. PSA cert lookup confirmed Charizard V Darkness Ablaze 019/189 cert 62398872 as MINT 9 but returned no provider slab images, so that listing remains blocked on exact slab media rather than using a substitute.

## 2026-09-29 — Shopify publication remainder census (461/509 live)

Production is now at **461 PUBLISHED physical inventory links out of 509 FOR_SALE inventory items**. Three additional items were safely promoted in the latest controlled reconciliation pass: Seel 021/094 English raw, Galarian Obstagoon 209/193 Japanese PSA 10, and Mega Charizard X ex 223/193 Japanese PSA 10. The two graded cards were explicitly founder-approved and recorded as `VERIFIED_GRADED` with exact FRONT/BACK graded-slab evidence before publication. Seel's legacy `test_mode=true` link was explicitly promoted to a normal production DRAFT link with its own audit event before the normal reconciler published it. The linked-draft worker was returned to `ENABLED=false` and `APPLY=false` immediately after the run.

The exact **48 remaining** items are:
- **3 linked graded Shopify drafts** — Nico Robin OP01-017 ACE 10 (no trusted slab media yet), Monkey.D.Luffy ST10-006 PSA 9 (front/back media ready; founder graded review still required), and Charizard V 019/189 PSA 9 (no trusted slab media yet).
- **1 unlinked graded item** — Monkey D Luffy P-001 [25th] Japanese PSA 10; identity and front/back slab media are already ready, but founder `VERIFY_GRADED` is still required before Shopify bootstrap/publication.
- **42 unlinked raw cards** — 29 Dragon Ball Super Masters, 6 Dragon Ball Super Fusion World, and 7 One Piece. All already have sale price, Near Mint condition and storage location. Their common blockers are identity/language confirmation and storefront-eligible exact media.
- **2 unlinked sealed One Piece products** — Premium Card Collection -6 assort vol.1- and Tin Pack Set Vol. 2 -Portgas.D.Ace-. Both require first-party exact package photo, language/region confirmation, real packed weight/dimensions and a verified sealed-product shipping profile. The Ace tin additionally has no recorded `seal_status` yet.

TCGGraph storefront-media policy is deployed and the provider-exact language/identity fallback is merged, tested and deploying. Production currently has **no `TCG_TCGGRAPH_API_KEY` configured**, so the 35 Dragon Ball/Fusion World cards cannot yet execute that provider path. TCGGraph account/subscription cost is an external commercial dependency and must not be purchased automatically.

HIGH-priority Action Required rows now exist for both sealed products and all four remaining graded items, separating founder-review-ready slabs from slabs that still need exact physical media.

## 2026-09-29 — Provider-exact import identity fallback

**SOURCE-CONTROL PR IN PROGRESS / REQUIRES TCGGRAPH KEY FOR PRODUCTION USE —** import enrichment is being extended so unmarked-language cards do not need a blanket batch language. If normal import evidence cannot confirm identity, the backend may probe TCGGraph across the supported candidate languages and accept `PROVIDER_EXACT` only when exactly one language returns the same deterministic exact printing. Zero matches, multiple language matches, any provider/API error, or a concurrent inventory change fails closed.

This path records the provider identity evidence in `identity_verification_events`; it does not approve media, condition, grading or Shopify publication. It is intended to remove the identity/language blocker from the 35 currently unsynced Dragon Ball Super / Fusion World raw cards once a production TCGGraph API key is configured. Production currently has no `TCG_TCGGRAPH_API_KEY` on the API or reconciliation worker, so no provider calls or identity mutations can occur yet.

## 2026-09-29 — TCGGraph exact-listing storefront media policy

**SOURCE-CONTROL PR IN PROGRESS / NO PRODUCTION MEDIA PROMOTION YET —** current TCGGraph terms were re-verified after their 28 September 2026 update. They expressly permit API-returned card data/images to be displayed inside paid products and cached, while leaving underlying publisher artwork rights with the publishers. Drop Rate's TCGGraph adapter is being narrowed to the same product-sale-only use boundary already used by the storefront media system: exact TCGGraph images may be eligible for the Shopify listing advertising the sale of that exact physical card under the project's UK CDPA 1988 s63 basis, but not for social media, generic SEO artwork, merchandise, AI training or unrelated marketing.

The change does **not** auto-approve media, relax exact-print matching or bypass physical-photo policy. TCGGraph assets remain `PENDING`; exact game/line/language/name/collector-number/finish matching remains fail-closed; graded, high-value, condition-sensitive and sealed inventory still require first-party physical evidence where the existing policy says so. Only human-approved, rights-verified, source-active exact matches may advance to Shopify Files. This is intended to unblock the 35 currently unsynced Dragon Ball Super / Fusion World raw cards without weakening publication controls.

## 2026-09-29 — Linked-draft drain throughput hardening

- Production publication canary passed end-to-end: Shopify ACTIVE, Supabase link PUBLISHED, matching SKU/price/stock/media and a deterministic DRAFT→PUBLISHED audit event.
- A 25-candidate production pass completed with 25/25 reconciliation results PUBLISHED and zero blockers; because the legacy selector also included already-PUBLISHED links, only 16 of those candidates advanced new draft links.
- A larger sequential drain proved unnecessarily slow because it revalidated completed links before reaching outstanding drafts.
- Source fix: launch-drain candidates are now DRAFT-only and independent items run with bounded concurrency capped at four and by the DB pool size. Per-item identity, language, price, stock, media, collection, ownership-state, audit and compensation gates are unchanged.
- Production cutover is complete and verified. The optimized DRAFT-only/concurrency-4 worker published the remaining ordinary catalogue backlog across both import batches. Final production parity is **458 PUBLISHED physical inventory links / 438 distinct live Shopify products**, with the 20-link difference explained by the 15 pooled raw listings. Shopify now has exactly **6 DRAFT products** matching Supabase: **5 graded cards held for founder `VERIFY_GRADED` review** plus **1 deliberate test-mode Seel**. The 20 redundant pre-pooling individual product shells remain ARCHIVED at quantity 0 to prevent double-selling. Reconciliation switches were returned to `ENABLED=false` and `APPLY=false` after the run. Two deterministic Collectr price overrides were repaired and audited before shutdown: Galarian Obstagoon PSA 10 £40 and Monkey D. Luffy ST10-006 PSA 9 £35.

## 2026-09-29 — Linked-draft publication audit alias fix

- Standard linked-draft reconciliation was observed in production compensating products back to DRAFT after Shopify activation because the loaded item exposed `id` while the audit commit expected `inventory_id`.
- No failed item was committed as PUBLISHED; compensation returned affected products to DRAFT.
- The reconciliation worker was paused before continuing the catalogue.
- Fix: explicitly select `i.id as inventory_id` in the loader, with regression coverage and documentation before the worker is resumed.


_Last updated: 30 September 2026, 01:52 BST_

This file is the persistent source of truth for project progress. A feature counts as **Completed** only after merge, production deployment and production verification where applicable.

## Current progress

- **Full Drop Rate roadmap:** ~65% overall. The core marketplace/MVP path is further ahead at ~82%; the lower full-roadmap number still includes customer storefront work, AI listings, customer service, SEO, marketing, native mobile and the majority of production n8n workflows. The n8n delivery foundation is now implemented in code but intentionally dormant.
- **Milestone 1 — Inventory / ownership foundation:** ~99% for the internal founder build and ~96% against the final three-founder milestone. RBAC, admin-route hardening, dedicated OWNER onboarding, owner-safe inventory/finance APIs, the restricted owner portal, media/condition workflows and inventory-image delivery are deployed. The genuine second-account cross-owner isolation gate has passed; the remaining release gate is onboarding the genuine third founder and repeating production isolation verification.
- **Internal commerce / founder finance foundation:** ~92%; Stripe Connect sandbox transfer/reversal is proven, payout preferences are live and the scheduled payout-request worker is deployed, while real-money execution remains intentionally locked
- **Milestone 2 — Shopify sale attribution:** ~92% technically complete; first real paid sale and full refund/restock path are production-verified, deterministic settlement reporting exists, seller-facing restricted finance views are deployed, and payout control is automated up to REQUESTED state. Multi-owner/same-card production attribution and live Stripe payout cutover remain.
- **Milestone 3 — Automated market valuation/pricing:** ~80% technically complete; provider ingestion remains intentionally gated until source-by-source production approval/validation
- **Customer storefront / Shopify UX:** base-commerce engineering/data-contract QA and the source-controlled visual pass are complete on the unpublished Brand Redesign theme across global shell, homepage, browse, grouped-copy PDP, exact-copy cart/checkout handoff, search and Shopify-native customer accounts. Brand Redesign remains unpublished and the source-controlled overlay now contains **25 files**, including the native facet files changed during mobile QA, with Shopify/runtime parity verified before merge. The live Horizon theme remains untouched. Overall storefront milestone remains IN PROGRESS for the repeat mobile preview smoke, desktop preview smoke and subsequent publication. See `docs/STOREFRONT_LAUNCH_QA.md`.
- **Native Founder app — iOS + Android:** blueprint added. The app will share the FastAPI/Supabase backend with Founder HQ but be a purpose-built camera-first mobile client, not a webview wrapper. Initial priority is Scan → exact-print recognition → inventory/media/condition → Action Required; later phases add sales, consignments, push notifications and Device Bridge printing/scanner workflows.
- **Seller Hub / mobile seller operations:** now materially deployed rather than merely blueprinted. Restricted-owner onboarding, seller-safe inventory/finance views, continuous mobile scanning, batch value totals, match correction, top-valued cards, weekly movers, payout tracking, Shopify/eBay channel visibility, Collectr post-import enrichment, Action Required exceptions and sealed-product media handling are live. Remaining product work is real-world mobile scan tuning, seller-controlled channel actions, third-founder production verification and broader production data-provider coverage.

## 29 September 2026 — pooled raw Shopify inventory architecture

**SOURCE-CONTROL PR IN PROGRESS / NO PRODUCTION POOL MUTATION YET —** The storefront inventory model is being corrected before the remaining Shopify draft backlog is published. Interchangeable raw copies will be represented as Shopify quantity while Supabase continues to own exact physical Inventory ID, owner, acquisition cost, condition, language, location and settlement attribution.

Phase A is intentionally limited to raw duplicate products that are still Shopify DRAFT. The existing shopify_inventory_links schema already permits several physical inventory rows to point at the same Shopify variant, and the production Shopify order processor already allocates quantity deterministically across those physical rows. The new pooling path therefore reuses the existing exact-owner/order/refund logic rather than introducing a parallel allocation system.

Phase A fail-closed requirements are: CARD, ungraded, APPROVED, FOR_SALE, identity-confirmed, language/condition/cost/storage/price present, one shared offer price, no reservation or marketplace-listing membership, and DRAFT/non-test Shopify links only. It chooses one deterministic draft product as the pool anchor, assigns a stable pool SKU, sets Shopify quantity to physical eligible count, zeros/archives redundant draft products, repoints each exact physical link to the anchor variant with deterministic allocation priority, and audit-logs every link mutation. A per-pool PostgreSQL advisory lock and best-effort Shopify compensation protect concurrent/error paths.

Read-only production sizing before implementation: **27 DRAFT raw duplicate groups / 61 physical cards**; **15 groups / 35 physical cards are fully ready now**; 12 groups remain blocked on identity/language readiness; no ready group has a price mismatch.

The old linked-draft reconciliation worker remains **APPLY=false**. Do not bulk-publish the remaining raw duplicate drafts as separate products and undo them later. Published duplicate products require a separate Phase B legacy-variant drain/alias migration so in-flight Shopify orders cannot lose attribution.

Target storefront model after the staged migration: one canonical Shopify product per exact card printing, with sellable offer variants such as English Near Mint quantity N, Japanese Near Mint quantity N, and unique graded variants quantity 1. Shopify Plus is not required. **Drop Rate — Brand Redesign** remains the future MAIN theme and its existing native buy-button logic already hides quantity at stock 1 and exposes Shopify quantity above 1.

See `docs/SHOPIFY_RAW_POOLING.md`.

## 29 September 2026 — controlled Shopify linked-draft launch reconciliation

**SOURCE-CONTROL PR IN PROGRESS / DISABLED BY DEFAULT —** A one-off, resumable
reconciliation worker has been added for the legacy Collectr-linked Shopify draft backlog.
It operates only on already-linked, non-test Shopify products and never creates replacement
products. Exact import identity, per-set language evidence, deterministic price overrides,
existing condition/graded-photo policy, exact Shopify product/variant/SKU, positive stock,
remote image presence and browse collection membership are all enforced before activation.

The worker regenerates Shopify title/description/SEO/tags/metafields from corrected backend
data, publishes Shopify first, and only then marks the corresponding
`shopify_inventory_links` row `PUBLISHED`. A database failure after remote activation
triggers best-effort compensation back to Shopify `DRAFT`. Existing Shopify imagery is
used only as a remote-presence gate for this controlled legacy reconciliation; no fake
`media_assets` or rights claims are created and the standard ongoing media/publish
pipeline is unchanged. Production execution remains pending dry-run validation.

## 29 September 2026 — Shopify linked-draft readiness audit

**DEPLOYED / VERIFIED / READ-ONLY —** PR #306 is merged and deployed to production. Founder HQ now exposes a separate readiness
summary for Shopify-linked `DRAFT` products. This reuses the existing identity, approval,
cost, language, condition/grade, price, location and media gates so the 369-product draft
backlog can be worked safely without bulk activation. The audit performs **zero Shopify
network calls and zero publication actions**; it does not infer missing language, confirm
identity, alter price/quantity or change remote product status. Dashboard output separates
unsynced inventory from already-linked Shopify drafts and exposes their core/media blocker
counts. Production deployment `abf12ed481f8c7e7f0e16270da312c6f78d71a00` passed **1,904 tests** and Railway's `/health/ready` check returned HTTP 200.

The post-deploy inventory baseline is **369 linked Shopify drafts**. After reconciling the already-verified Seel 021/094 English image from Shopify `READY` back into the media registry and approving its previously recorded founder physical review, **1 draft is now core-ready and media-ready** while remaining unpublished. Current linked-draft blockers are: 368 approval status, 368 identity confirmation, 367 card language, 5 graded slab verification and 2 store price. Storefront publication remains gated on refreshed mobile QA followed by desktop QA.

## 29 September 2026 — storefront mobile launch-QA polish

**RUNTIME DEPLOYED / SOURCE CONTROL MERGED / RE-PREVIEW REQUIRED —** review of the real mobile preview recordings found several presentation issues that did not invalidate the base-commerce path but should be fixed before publication. The unpublished `Drop Rate — Brand Redesign` theme now:
- reserves a fixed two-line title footprint on product cards and anchors browse-card purchase actions so long titles do not break grid symmetry;
- removes accelerated checkout from collection/home browse cards while retaining the native PDP/cart/checkout path;
- turns the three-card homepage display into an interactive/automatic spotlight rotation; the active card's product name, price and link move with the front card, tapping a rear card promotes it, manual interaction pauses auto-rotation, and reduced-motion preference disables automatic movement;
- keeps desktop vertical facets expanded but starts mobile drawer facets collapsed unless that facet already has an active value; mobile facet spacing is tightened without replacing Shopify-native Search & Discovery filtering;
- labels grouped physical listings as `Copy 1`, `Copy 2`, etc. while preserving condition/language/grader/grade/price and exact-copy selection behavior.

The runtime edits are confined to the unpublished theme. No live Horizon, product price, inventory quantity, ownership, cart identity or checkout mutation is included. Three native Horizon files that are now intentionally changed by Drop Rate (`blocks/filters.liquid`, `snippets/list-filter.liquid`, `snippets/price-filter.liquid`) are added to the overlay so this behavior is source-controlled rather than existing only in Shopify.

**Language facet finding:** Shopify has one correctly tagged English product, `Seel · EN · 021/094 · Phantasmal Flames`, but it is DRAFT. The current customer-visible ACTIVE catalogue is Japanese, so Shopify correctly exposes Japanese but not English as a live Language value. Filter values remain inventory-driven; do not hard-code empty English/Korean/Chinese values merely to make them appear. English should appear automatically when an ACTIVE collection product carrying `drop_rate.language=English` exists.

**Next gate:** repeat the mobile preview through homepage → collection → filters/sorting → PDP/grouped copies → exact-copy cart → checkout entry → search/no-result → customer account. If that pass is clean, continue immediately with desktop QA. **Do not publish yet.**

## 29 September 2026 — storefront final machine-verifiable gate

**Machine-verifiable storefront gate: COMPLETE / TWO EXTERNAL GATES REMAIN —** the
unpublished `Drop Rate — Brand Redesign` theme is now fully aligned across the active
global brand layer, Shopify current settings/header/footer, homepage, collection/browse,
grouped-copy PDP, exact-copy cart, search and native customer-account chrome. The
source-controlled overlay now contains **22 files**, and the newly added settings/header/
footer files were deployed only after their pre-write Shopify checksums matched the values
captured before CI. Post-write read-back confirms those files match GitHub byte-for-byte;
the previously deployed 19 files had already been independently parity-verified.

Shopify runtime/config checks also pass:
- `Drop Rate — Brand Redesign` remains **UNPUBLISHED**.
- `Horizon` remains **MAIN** and its last update remains
  **24 September 2026 17:17:28 UTC**.
- customer accounts use **NEW_CUSTOMER_ACCOUNTS**; login links are visible, accounts are
  optional and login is not required at checkout, so guest checkout remains available;
- the homepage's four configured feature products are ACTIVE and its Trading Cards,
  Pokémon, One Piece, Graded Cards and four set destinations all resolve with products;
- the `Sealed` collection remains exactly **0 products**, so its count-gated browse link
  stays hidden;
- the old yellow/teal/cream palette is no longer present in the active source-controlled
  brand/component layer. Preset-only Horizon values are not treated as active Brand
  Redesign styling.

Current publication gates:
1. **Shopify Search & Discovery is installed and configured** with the approved native
   filter order: Set, Price, Rarity, Variant, Availability, Condition, Language, Grading
   Company and Grade. Facet values remain inventory-driven.
2. **Visual smoke is in progress through user-supplied preview recordings.** The first
   mobile recording pass verified the base commerce path and exposed presentation issues
   that were fixed in PR #303. A refreshed mobile pass is now required, followed by the
   desktop pass, before publication.

Do **not** publish Brand Redesign or reopen deferred recognition/seller/market-data/
automation scope until the refreshed mobile and desktop storefront gates are intentionally cleared.**

## 29 September 2026 — active global theme settings + footer

**Storefront global shell settings: DEPLOYED / BROWSER QA PENDING —** QA found that, after the active
`dr-brand-system` fix, Brand Redesign's Shopify-managed current palette/footer JSON still
contained legacy teal/cream values. `config/settings_data.json`, `header-group.json` and
`footer-group.json` are now source-controlled and only active colour values are aligned to
the current Drop Rate navy/ink/blue/cool-grey/white system. The existing
`drop-rate-brand-logo.png`, logo sizes, `main-menu`, announcement/footer copy, block IDs
and layout settings are unchanged. No live Horizon, product, price, inventory, ownership,
cart or checkout mutation is included. Completion requires CI, deployment of the exact
three files to the unpublished Brand Redesign theme and source/runtime parity.**

## 29 September 2026 — active global brand layer

**Storefront global brand CSS: DEPLOYED / BROWSER QA PENDING —** QA found the live unpublished theme renders
`dr-brand-system` after `drop-rate-global-styles`. That active runtime snippet still
contained legacy yellow/teal purchase actions and late overrides that flattened the newer
product-card, facet and PDP presentation. The snippet is now source-controlled and narrowed
to current Drop Rate global primitives (navy/ink/blue/cyan/cool-grey/white), gallery media,
product-card purchase controls, focus/header and footer basics. Component-specific
browse/PDP/cart/search styling remains owned by `drop-rate-global-styles`. No product,
price, inventory, ownership, checkout behavior or live Horizon theme change is included.
Completion requires CI, deployment to the unpublished Brand Redesign theme and full
source/runtime parity.**

## 29 September 2026 — homepage visual alignment

**Storefront homepage design/source control: DEPLOYED / BROWSER QA PENDING —** the four custom Brand Redesign
homepage sections are now mirrored in GitHub and aligned to the same current Drop Rate
navy/blue/cyan/cool-grey/white visual system as browse, PDP, cart, search and account.
The older yellow/teal hero/set accents are removed. Native Shopify behavior is preserved:
discovery search remains a product-only GET to `routes.search_url`, product and collection
choices remain theme-editor settings, and no pricing, inventory, ownership, merchandising
decision or checkout rule is moved into Liquid. The live Horizon theme remains untouched.
Completion requires CI, deployment to the unpublished Brand Redesign theme, source/runtime
parity and desktop/mobile preview QA.**

## 29 September 2026 — customer account/header visual alignment

**Storefront account/header presentation: DEPLOYED / BROWSER QA PENDING —** Shopify's native customer account
surface and cart header actions now use the current Drop Rate white/ink/blue/cyan visual
tokens. The `<shopify-account>` component remains the customer auth/order-history surface;
Founder HQ/Seller Hub auth remains separate, guest checkout stays available, and no custom
login or checkout path is introduced. No customer record, product, price, inventory,
ownership, order or live Horizon theme change is included. Completion requires CI,
deployment to the unpublished Brand Redesign theme, source/runtime parity and preview QA
of signed-out/signed-in account handoff on desktop/mobile.**

## 29 September 2026 — search visual alignment

**Storefront search presentation: DEPLOYED / BROWSER QA PENDING —** Shopify-native product search now uses
the current Drop Rate white/cool-grey/blue visual system while preserving the already-tested
v1 search contract: product-only results, last-term partial matching and unavailable
products last. The search field, focus state, help text and no-results state were restyled;
no custom search backend, AI index, query semantics, product data or live Horizon theme
change is introduced. Completion requires CI, deployment to the unpublished Brand Redesign
theme, source/runtime parity and desktop/mobile search/no-result preview QA.**

## 29 September 2026 — cart visual alignment

**Storefront exact-copy cart presentation: DEPLOYED / BROWSER QA PENDING —** the cart now aligns to the
current Drop Rate navy/blue/cyan visual system while preserving Shopify-native commerce.
Customer-safe copy metadata uses compact blue/cyan states, the one-physical-copy lock is
more explicit, and the native checkout CTA is styled in the current blue brand action.
The physical Inventory ID contract, fixed quantity behavior, remove action, exact Shopify
variant and native cart/checkout flow are unchanged. No product, price, inventory quantity,
ownership, order or live Horizon theme change is included. Completion requires CI,
deployment to the unpublished Brand Redesign theme, source/runtime parity and
desktop/mobile cart→checkout preview smoke.**

## 29 September 2026 — PDP visual alignment

**Storefront PDP/grouped copies: DEPLOYED / BROWSER QA PENDING —** the next storefront-first presentation
slice aligns the product page to the current Drop Rate navy/blue/cyan system. The card
heading, deterministic facts panel, one-copy purchase note, grouped-copy selector and
primary add-to-cart action now use white/cool-grey surfaces with explicit blue selected-copy
states instead of the older cream/yellow treatment. Exact sibling handles, current-copy
selection, Shopify variant identity, native buy buttons and accelerated checkout structure
are unchanged. No product, price, inventory quantity, ownership, order or live Horizon
theme change is included. Completion requires CI, deployment to the unpublished Brand
Redesign theme, byte-for-byte source/runtime parity and desktop/mobile preview QA.**

## 29 September 2026 — collection visual alignment

**Storefront collection design: DEPLOYED / BROWSER QA PENDING —** the first visible theme pass after the
storefront engineering gate is now source-controlled. The collection hero, browse chips,
product-card chrome and Shopify-native filter surfaces are aligned to the current Drop Rate
Seller Hub palette: deep navy, blue/cyan accents, cool grey background and white cards,
replacing the older cream/beige treatment on this surface. The browse route also wires the
existing `Sealed` smart collection behind a product-count gate, so it remains invisible
until real sealed inventory is publishable. No live Horizon theme, product status, price,
inventory quantity, ownership or checkout behavior is changed. Completion requires CI,
deployment to the unpublished `Drop Rate — Brand Redesign` theme, source/runtime parity,
and desktop/mobile preview QA.**

## 29 September 2026 — storefront set-facet canonicalization

**Storefront facet data hygiene: COMPLETE —** Shopify collection filtering is already
enabled in the unpublished Brand Redesign template, and all 95 ACTIVE products carry the
core `drop_rate` metafields needed for customer filters. QA found one duplicate-looking
Set value: `Carrying on His Will` versus the canonical `Carrying On His Will`.
The historical one-off migration for this label had already run before a later Collectr
import recreated the provider casing. The import boundary is therefore being hardened with
a narrow known-alias canonicalization rule rather than generic title-casing. Unknown set
labels remain unchanged. This work changes display metadata only; it does not change
catalogue IDs, card numbers, variants, languages, ownership, prices, inventory quantities
or publication state. Completion requires CI, production deployment, a one-row source-of-
truth backfill, Shopify metafield resync and verification that the live Set facet value is
no longer duplicated.**

## 29 September 2026 — sealed Shopify product contract

**Sealed Shopify representation: COMPLETE / PUBLICATION STILL FAIL-CLOSED —** PR #284
ports the sealed-storefront contract onto current `main` without losing the newer media
hardening. `SEALED`/`COLLECTION` inventory now plans as Shopify product type
`Sealed TCG Product`, tag `Sealed Product`, required collections `Sealed` + game,
sealed-specific customer/SEO copy, and shipping key `SEALED_PRODUCT`; it no longer
inherits raw-card tags or the raw-card `Trading Cards` collection requirement. The existing
Shopify `Sealed` smart collection is present and deterministically keys on
`Sealed Product`.

GitHub **Backend checks** passed for PR #284, including the regression proving sealed
publication completeness fails closed when the real sealed shipping profile is absent.
Railway production deployment `a585b073-cba1-4760-b1e2-962f3bf5de16` completed
**SUCCESS** from merge commit `c6f97a53ac3b13a660c5c5d9f8a95f4dd5697210`; the
production pre-deploy suite reported **1,883 passed**, and `/health/ready` returned
**200 OK**.

Post-deploy production read-back confirms only `RAW_CARD` and `GRADED_CARD` shipping
profiles exist. There is still no `SEALED_PRODUCT` profile, so no package weight,
dimensions or carrier assumptions were guessed. Both current sealed One Piece inventory
items remain **DRAFT / FOR_SALE**, identity-unconfirmed and without a Shopify inventory
link/product GID. No schema, inventory, ownership, price, media, Shopify product or live
theme mutation occurred. Sealed publication remains blocked until the normal
identity/seal/media gates and a verified sealed shipping profile are complete.**

## 29 September 2026 — sealed capture-context queue hardening

**Sealed media context validation: COMPLETE —** PR #282 closes the remaining safety
condition recovered from superseded PR #253 without bringing forward that PR's stale broad
query change. Media Intake now counts approved first-party physical images only when their
capture context matches the workflow: sealed/collection requires `SEALED_PRODUCT`, graded
cards require `GRADED_SLAB`, and raw cards accept only `RAW_UNSLEEVED`,
`PENNY_SLEEVE` or `TOP_LOADER`. The supported route filter remains explicitly bounded
to `CARD`, `SEALED` and `COLLECTION`, with existing `require_user` / `_founder`
owner scoping unchanged.

GitHub **Backend checks** passed for PR #282, including the regression proving a
wrong-context raw-card FRONT remains queued for a sealed item while the same approved asset
under `SEALED_PRODUCT` clears the one-FRONT requirement. Railway production deployment
`6745ac08-dcaa-4a1d-900a-da5804b9cd89` completed **SUCCESS** from merge commit
`c7061496615fba7655d77550a6c0daac0c7d7bd1`; the production pre-deploy suite reported
**1,881 passed**, and `/health/ready` returned **200 OK**.

Post-deploy production read-back confirms both current sealed One Piece items remain
**DRAFT / FOR_SALE** with **0 inventory media** and **0 FIRST_PARTY_CAPTURE media**, so the
hardening caused no inventory, ownership, pricing, identity, media-rights or Shopify
publication mutation. No schema change was required because `media_assets.capture_context`
already existed.**

## 29 September 2026 — sealed media intake queue fix

**Sealed storefront media intake: COMPLETE —** PR #279 widened the existing
`/api/v1/shopify/media-assets/intake-queue` candidate filter from CARD-only to
`CARD`, `SEALED` and `COLLECTION` while preserving the deterministic physical-photo
policy. GitHub **Backend checks** completed successfully for head
`6e9b2a33587c06392d3c867b23bb088e167cd330`. Railway production deployment
`30c91562-c6ae-4fe6-a77c-0560fc328eb2` completed **SUCCESS** from merge commit
`65fa522146417056a37d4d900b60e94e81ebea8e`, and its configured
`/health/ready` check returned **200 OK**.

Production read-back confirms both current sealed One Piece inventory items now satisfy
the exact owner/status/sale-intent/product-type candidate contract and still have zero
physical media rows, so both correctly remain capture work rather than being silently
excluded:

- `INV-5CD6E9E29B9B489D9D8B624A0D0E1609` — Premium Card Collection -6 assort vol.1-
- `INV-C03F9CCD386C4798A90A45CC5CB00619` — One Piece Tin Pack Set Vol. 2 -Portgas.D.Ace-

Both remain **DRAFT**, `FOR_SALE`, unconfirmed for identity and un-published. The route
remains behind `require_user` and resolves the requesting founder through `_founder`,
then scopes both inventory and media reads by owner. No schema, ownership, price,
inventory status, identity confirmation, seal decision, media-rights decision or Shopify
publication was changed by this completion proof.**

## 29 September 2026 — storefront launch engineering QA

**Base-commerce engineering QA: COMPLETE / PUBLICATION PENDING —** the unpublished
`Drop Rate — Brand Redesign` theme is healthy and all **14/14** source-controlled theme
files match Shopify byte-for-byte. Shopify reports **95 ACTIVE / 95 Online Store-published**
products and 369 intentionally unpublished products. A full sweep of the 95 published
products found **0** physical-copy invariant failures: one variant per listing, SKU =
Inventory ID, quantity 1, oversell DENY and available-for-sale true. All **95/95** have
READY featured media. Grouped-copy QA checked **14 products / 28 sibling references** with
zero broken references. Search passed collector-number, card-name, Pokémon-name and
no-result cases. Shopify New Customer Accounts remain optional with guest checkout.
The native cart checkout action is intact. QA also removed unfinished empty Sealed
navigation from the unpublished runtime theme and restored source-control parity.
Detailed evidence is in `docs/STOREFRONT_LAUNCH_QA.md`. The only remaining v1 storefront
gate is authenticated desktop/mobile visual preview and cart→checkout browser smoke before
theme publication. The live Horizon theme has not been changed.**

## 29 September 2026 — storefront search v1 slice

**Customer storefront / simple search: ENGINEERING QA COMPLETE / VISUAL QA PENDING —** Shopify-native product search is now
explicitly configured for product-only results, last-term partial matching and unavailable
products last. The unpublished Brand Redesign search input uses TCG-specific name/set/
collector-number language and reuses the compact storefront card grid. Live connected-store
checks confirmed free-text matches for `OP16-071`, **Benevolent King** and **Eiscue ex**.
No custom search backend, AI index, schema, product data, price, ownership or live-theme
publication was added. CI is green; connected-store name/collector-number/no-result checks passed. Remaining gate: authenticated visual/result QA on the unpublished theme.**

## 29 September 2026 — storefront customer account / order surface

**Customer storefront / account & order history: ENGINEERING QA COMPLETE / VISUAL QA PENDING —** Shopify is
already configured for OPTIONAL **New Customer Accounts**, with storefront/checkout login
links enabled and login not required at checkout. The unpublished Brand Redesign header
uses Shopify's native `<shopify-account>` component; Shopify therefore remains the
customer identity and order-history surface for v1. The account action has no dependency
on `/owner`, Founder HQ, Supabase customer auth, owner/consignor identity or a custom
Drop Rate order-history API. Guest checkout remains available. The exact header account
snippet is mirrored under `storefront/theme/**` with contract tests enforcing the
customer-vs-owner auth boundary. No customer/account record, product, price, inventory,
ownership, ledger, settlement or live-theme publication was changed. Remaining gate is
normal browser/mobile visual QA as part of the unpublished-theme launch review.**

## 29 September 2026 — storefront exact-copy cart slice

**Shopify-native cart / checkout presentation: ENGINEERING QA COMPLETE / BROWSER QA PENDING —** the unpublished Brand
Redesign cart now recognises Drop Rate physical products by their `inventory_id`
metafield, shows concise card/set/condition/language details and locks the customer-facing
quantity control to one physical copy while preserving Shopify's existing cart form,
remove action and native checkout. Representative live variants are also verified with
Shopify `inventoryPolicy=DENY` and quantity 1, so the storefront presentation matches the
platform stock invariant. No price, stock quantity, ownership, order, ledger, settlement
or live-theme publication changed. GitHub CI is green and the complete 95-product Shopify sweep passed the physical-copy inventory contract. Remaining gate: authenticated browser cart→checkout handoff/visual QA on the unpublished theme.**

## 29 September 2026 — storefront grouped-copy PDP slice

**Customer storefront / PDP grouped copies: ENGINEERING QA COMPLETE / VISUAL QA PENDING —** exact physical copies are now
grouped by Supabase `catalogue_id`, not fuzzy card text. The guarded Shopify publish path
now refreshes derived `copy_handles` metadata for published siblings and keeps a hard
20-handle Shopify Liquid safety limit. The unpublished Brand Redesign product template
renders available sibling copies with thumbnail, condition/grade, language and exact price,
while the Shopify-native buy button remains attached to the selected physical product.
Seven current canonical groups (14 active products) were backfilled and representative
One Piece/Pokémon pairs were verified in Shopify with shared metadata, quantity 1 and
`availableForSale=true`. No price, status, quantity, ownership, ledger or live-theme
publication was changed. Theme/runtime files match the GitHub overlay byte-for-byte.
GitHub backend/theme contract CI is green. Connected-store QA verified 14 grouped products and 28 sibling references with zero broken/unpublished handles. Remaining gate: desktop/mobile visual QA and exact-copy browser handoff.**

## 29 September 2026 — storefront launch structural QA

**Base storefront engineering QA: PASSED / VISUAL + SEARCH & DISCOVERY FACET QA PENDING —**
the unpublished Brand Redesign theme has been checked against the connected Shopify
catalogue without publishing it. Current verified launch data:
- 95/95 ACTIVE Shopify products have a featured image;
- 95/95 have the customer-safe language plus condition or graded metadata required by the
  theme's metafield/tag fallback contract;
- every active product has one priced SKU and one exact Drop Rate Inventory ID;
- all 16 set routes currently hard-coded into Pokémon/One Piece browse navigation have at
  least one ACTIVE product;
- all homepage hero/discovery/spotlight product handles resolve to ACTIVE stock with
  quantity 1;
- search by collector number `OP16-071` returns the expected two-copy active group;
- empty Dragon Ball, Naruto, Riftbound and Sealed destinations are not exposed by the
  current browse strip;
- an unfinished Sealed-navigation runtime drift was removed and the affected unpublished
  theme files restored to GitHub parity.

The required `drop_rate` product metafield definitions for Set, Language, Condition,
Rarity, Variant, Grading Company and Grade exist in Shopify. The remaining facet gate is
merchant-side Shopify Search & Discovery configuration/visual verification because that
storefront-filter selection is not exposed through the connected Admin API. The live
`Horizon` theme remains untouched.**

## 29 September 2026 — storefront Milestone 1 browse slice

**Customer storefront / collection-browse milestone: ENGINEERING QA COMPLETE / VISUAL QA PENDING —** the first real-data
browse slice has been written to Shopify's **UNPUBLISHED**
`Drop Rate — Brand Redesign` theme; the live `Horizon` theme was not modified.
At verification time Shopify contained 464 catalogue products: 95 ACTIVE and 369 DRAFT.
The browse implementation uses existing real smart collections (Pokémon 202, One Piece
262, Singles 457, Graded 7), hides empty game destinations, preserves two-column mobile
density, displays product counts, adds TCG metadata badges with metafield/tag fallbacks,
and provides game/set browse routes. Exact changed theme files are now mirrored under
`storefront/theme/**` and were verified byte-for-byte against the unpublished Shopify
theme. No product status, price, ownership, inventory quantity or live theme publication
was changed. Connected-store QA confirmed empty game destinations remain hidden and removed an unfinished empty Sealed-navigation runtime drift; the runtime theme is again byte-for-byte aligned with GitHub. Remaining gate: authenticated desktop/mobile visual preview before publication.**

## 29 September 2026 — recognition image-retention decision

**Recognition source-image retention: DOCUMENTED / CURRENT POLICY UNCHANGED —** raw
recognition source pixels remain ephemeral during the storefront-first feature freeze.
This is now explicitly a temporary policy, not a permanent architecture decision.
Recognition continues to retain hashes, dimensions, derived fingerprints, observations,
candidate evidence and human feedback, but historical verified scans cannot be
re-fingerprinted from original pixels under the current design. Any future source-image
retention requires a separately reviewed privacy/storage/rights design after recognition
development is deliberately re-opened; no raw-image persistence was added in this PR.**

## 29 September 2026 — inventory sale-intent contract

**`sale_intent` documentation: COMPLETE —** `docs/SALE_INTENT.md` now defines the
existing two-state contract: `FOR_SALE` and `PERSONAL_COLLECTION`. The document
separates commercial intent from workflow status, records SOLD/RESERVED restrictions,
optimistic-version/idempotency behavior, founder/owner scoping, audit events, channel
withdrawal semantics and the rule that returning to `FOR_SALE` never silently republishes
a listing. No schema or runtime behavior changed. Production snapshot on 29 September
2026: 509/509 inventory items are `FOR_SALE`; 0 are `PERSONAL_COLLECTION`.**

## 29 September 2026 — reconciliation migration history alignment

**Migration history alignment: COMPLETE IN REPO / NO SCHEMA CHANGE —** Supabase production
records the already-applied RLS-safe reconciliation migration as
`20260929021203_shopify_reconciliation_rls_read`. The live function definition matches
the merged migration SQL. The repository filename has therefore been renamed from
`20260929022000_...` to `20260929021203_...` so version-controlled history matches
production without deleting, rewriting or re-applying any Supabase migration row.

## 29 September 2026 — Shopify order reconciliation hardening

**Shopify ↔ Drop Rate order reconciliation: COMPLETE —** the corrected 30-minute
production operations monitor completed successfully at **2026-09-29 02:30 UTC**. The
heartbeat step remained healthy and reconciliation reported `remote_count=2`,
`local_count=1`, `matched_count=1`, `remote_only_count=1`,
`remote_anomaly_count=1`, `local_only_count=0`, `resolved_alerts=2`; both monitor
steps exited 0. This proves the RLS-safe order-read function now sees Shopify test order
#1002 / `8488435581275` correctly while preserving the known cancelled #1001 /
`8488414282075` webhook-gap proof case. Supabase verification shows the two false
CRITICAL #1002 alerts are RESOLVED and the two expected HIGH #1001 founder alerts remain
OPEN. No order, inventory, ownership, ledger, settlement or payout record was reconstructed
or rewritten. The migration history is aligned in repo as
`20260929021203_shopify_reconciliation_rls_read`.**

## 29 September 2026 — verified 24-hour build delta

**Production application head is healthy —** deployed application commit `b3d29745d6` ("Fix seller portal runtime error and polish Seller Hub branding") is healthy. Documentation-only build-status commits may sit ahead of that application SHA on `main`. Railway deployment `324e7d2d-e8d0-487e-b29d-c3188aef2836` completed **SUCCESS**, production pre-deploy passed **1,847 tests**, and `/health/ready` returned **200 OK**. This section summarises the merged work in the preceding 24-hour window; prepared-but-dormant infrastructure is called out separately rather than counted as live automation.

### Recognition, media and mobile scanning
- **Recognition v1.5 / v1.5.1 shipped:** persistent exact-print visual retrieval, provider challengers, stronger One Piece ROUND1 recovery and fail-closed handling for unmapped printings. External/provider identities may challenge a local candidate but still cannot silently create canonical identity.
- **Inventory-image delivery hardened:** founder/seller card art loads through authenticated backend media paths rather than direct browser hotlinks; verified OPTCG images were added to the allowed resolution path and graded cards without real slab media are visibly flagged.
- **Dragon Ball exact-media adapter hardened:** TCGGraph Masters vs Fusion World line mapping is explicit, exact-print checks are stricter and TCGGraph media remains **PENDING / INTERNAL_REFERENCE_ONLY** until separate storefront-rights approval. Production still has no TCGGraph API key, so this remains a prepared fallback rather than live automatic Dragon Ball imagery.
- **Seller scan → inventory flow deployed:** restricted owners can use the same recognition engine, confirm/correct a match and add a physical card to their own inventory. Seller-created items remain **DRAFT** with `identity_confirmed=false` until Drop Rate verification.
- **Restricted-owner recognition access fixed:** the seller scanner now reaches the recognition APIs without inheriting Founder-only permissions.
- **Mobile batch scanner deployed:** full-screen camera, running card count/value, unresolved-card retention, manual "Capture now" fallback, catalogue/card-number correction search and idempotent batch intake.
- **Continuous scanner v2 deployed:** camera remains open between cards, latest-match card is shown inline with market value, one-tap Fix/Remove is available, duplicate auto-capture suppression is short-lived, success/review feedback is visible, and auto-scan pauses while a correction is open. Seller assets were cache-busted to avoid stale Safari behaviour.
- **Mobile production bugs fixed:** malformed Inventory/Channels pagination bind placeholders were causing seller-facing 500s; both were corrected. The mobile scanner also previously hid its manual shutter, which is now always available as a fallback.

### Seller Hub, onboarding and owner-safe operations
- **Owner Portal v2 / Seller Hub deployed:** seller-first navigation, mobile bottom navigation, owner-safe overview/inventory/sales/payouts/settlements, visual inventory cards and safe image handling. Founder-only acquisition-cost, storage, purchase-lot, internal-note and provider-control fields stay hidden.
- **Seller onboarding completed:** branded seller invite flow, restricted OWNER membership creation, commission display/acknowledgement, secure invite preview/redemption and invite-contract fixes are merged. Invite email delivery infrastructure exists; sender-domain/production email configuration remains a separate operational setup item.
- **Seller Hub branding corrected:** Founder HQ artwork and warning-style "restricted owner" language were removed from seller-facing surfaces, and the top bar was rebuilt into one deliberate Drop Rate Seller Hub lockup.
- **Seller portal runtime crash fixed:** the production `replaceChildren` null crash in the Channels empty-state path was fixed and the shared empty renderer was hardened.
- **Portfolio intelligence added:** seller dashboard now shows **Top Valued Cards**, **Weekly Top Movers** using real historical pricing snapshots, and a prominent **Next Payout** tracker that distinguishes scheduled requests from estimates based on currently cleared/unreserved balance.
- **Channels workspace added:** seller-safe Shopify/eBay link state, channel price, last sync/verification, errors and live eBay listing links are visible. A Whatnot adapter slot is shown as **PLANNED**; no fake publish/pause controls were added. Postgres remains the inventory source of truth.

### Collectr import and enrichment
- **Collectr import path production-verified against real portfolio data:** snapshot/delta reconciliation prevents unchanged rows from being duplicated, physical quantity expansion remains deterministic and imports still create one physical Inventory ID per unit.
- **Post-import enrichment pipeline deployed:** committed imports can be enriched in restart-safe bounded chunks through identity validation, exact media resolution, provisional benchmark pricing and Action Required exception creation.
- **Explicit unmarked-language control added:** imported rows with explicit `(JP)`/language evidence continue to win; a founder can optionally choose a default language for otherwise unmarked rows instead of Drop Rate silently inferring one.
- **English Pokémon exact-media support added through TCGdex:** exact set/card-number/finish matching is required. Japanese Pokémon and Japanese One Piece retain their existing exact-provider paths.
- **TCGGraph fallback integrated safely:** supported exact matches can be stored as internal reference media, but they do not become storefront-approved merely because a provider returned an image.
- **General Action Required queue deployed:** unresolved identity, media, physical-photo and pricing exceptions are durable, owner-scoped and deduplicated rather than disappearing into logs.
- **Recent import/resume UX added:** Founder HQ can see recent import batches, enrichment counts and resume interrupted enrichment instead of relying on browser memory.
- **`import.committed` automation event added:** successful import commit now emits a durable automation-outbox event, ready for n8n routing when the dispatcher/workflow is deliberately activated.

### Sealed products
- **Sealed-product media architecture deployed for the two current One Piece sealed products:** **Premium Card Collection – 6 assort vol.1** and **Tin Pack Set Vol. 2 – Portgas.D.Ace** are the current exact products in scope; `CANONICAL_PRODUCT` reusable media scope and `SEALED_PRODUCT` first-party capture context are now part of the media model.
- **Exact physical packaging photo policy added:** current `COLLECTION` / `SEALED` inventory requires the exact physical front packaging photo rather than borrowing ordinary card-art logic. Region/language remains unknown where the Collectr row does not prove it.
- **Seller/Founder/Shopify media paths updated:** sealed products now enter Media Intake, first-party sealed photos can render in Seller Hub, and Shopify readiness/bootstrap understands canonical sealed media without conflating it with `CANONICAL_CARD`.
- **Rights boundary preserved:** official Bandai imagery may be used as identity evidence, but is not silently copied into storefront media where reuse rights are not established.

### Shopify, multi-owner commerce and finance hardening
- **Multi-owner Shopify order/refund support merged:** the previous order-level single-owner assumption was removed. Each physical allocation now carries its own owner context through reservation, paid-order snapshots, ledger entries, cancellation release and refunds. Shipping remains allocated deterministically per order item/owner.
- **Commerce torture/retry suite added:** high-volume deterministic tests now cover penny conservation, weighted allocation, rounding boundaries, malformed Shopify payloads, replay/deduplication, cross-channel retries and transaction boundaries.
- **Personal Collection sale intent deployed and production-verified:** `FOR_SALE ↔ PERSONAL_COLLECTION` is now a separate owner-intent dimension; moving an item to personal collection withdraws availability without rewriting ownership or lifecycle history.
- **Shopify catalogue bootstrap hardened:** image-backed approved/draft inventory can create Shopify drafts, missing Store Price no longer blocks safe draft linking, startup failures are surfaced, and catalogue bootstrap now runs through audited RLS context.
- **Shopify catalogue population materially advanced:** the store reached **464 draft products**, with **457/464 carrying images** at the verified checkpoint. Base catalogue grouping was **Trading Cards 464 / Pokémon 202 / One Piece 262**. Products remained Draft rather than being silently published, preserving launch control while taxonomy, media and storefront work continue.
- **Storefront development theme started:** an unpublished development theme now carries the first CRO/navigation pass — search-first navigation, game shortcuts, trust messaging, denser product grids, filter/chip patterns, quick-add concepts and mobile two-column browsing. The live theme was intentionally left unchanged; product-page/cart CRO, analytics, full SEO, deeper collection hierarchy and launch QA remain unfinished.
- **Founder workspace/Shopify access fixes deployed:** Founder HQ filtering/access regressions and Shopify test-sync shipping-profile initialization were corrected.
- **Payout scheduler incident resolved:** Railway start-command handling was corrected and a controlled run completed successfully with normal hourly scheduling restored.

### Milestone 1 / ownership and security
- **Second-account production isolation gate passed:** a genuine second founder account was tested under restricted OWNER semantics in rollback-only production probes. Cross-owner inventory/finance visibility was zero and cross-owner mutation was blocked. The reciprocal owner check behaved correctly; live memberships were restored after the probe.
- **Ownership reassignment defense verified:** application inventory patch schemas do not accept `owner_id`, owner mutations bind to the authenticated owner, and `tcg_api` cannot directly update `inventory_items.owner_id`.
- **Milestone 1 is still not being called 100% complete:** the remaining gate is onboarding/verifying the genuine third founder account in production.

### n8n and automation foundation
- **Durable automation foundation merged:** transactional `automation_events` outbox, lease/retry/dead-letter semantics, HMAC-signed event envelopes and Railway-ready dispatcher code are version-controlled.
- **DR-00 signed event ingress added:** Railway-private webhook delivery validation, signature/replay protection contract and pinned n8n image CI are in place.
- **n8n provisioning/runtime hardened:** reproducible provisioning files and CI version checks are merged; unsafe external-image/runtime boundaries were tightened.
- **Important status:** this automation foundation is still intentionally **production-dormant** where noted. It is prepared infrastructure, not evidence that all n8n workflows are active.

### Product/UX blueprints added
- **Storefront + Founder HQ UX blueprint added:** collection-led Shopify structure, TCG-native filtering, graded-card presentation, customer search/discovery, Founder workflow improvements and governed AI merchandising/CRO boundaries are documented.
- **Native iOS + Android Founder app blueprint added:** same FastAPI/Supabase backend, camera-first workflow, not a webview wrapper. Planned phases include scanning, media/condition, Action Required, sales, consignments, notifications and later Device Bridge printing/scanner support.
- **Governed AI CRO/SEO experimentation blueprint added:** Postgres owns experiment truth, FastAPI owns eligibility/statistical decisions, Shopify renders validated variants and n8n will eventually orchestrate low-risk experiment loops with rollback. Pricing/ownership/finance/legal/payment behaviour remain outside autonomous AI authority.
- **Claude production safety contract added:** external AI assistance is explicitly constrained so deterministic business rules, ownership, pricing and finance cannot be silently overridden.

### Immediate next build priorities after this 24-hour push
1. Run real-world iPhone batch scans against a mixed stack and tune trigger sensitivity/latency from actual production behaviour.
2. Finish physical media capture for the two sealed One Piece products and verify their Shopify-ready images end-to-end.
3. Onboard the genuine third founder and repeat the production owner-isolation test.
4. Run the controlled multi-owner / same-card Shopify sale + refund attribution test.
5. Add real seller-controlled channel actions only after the existing Shopify/eBay publisher paths are safely owner-scoped; keep Whatnot as an adapter-ready future channel.
6. Continue permitted provider onboarding so Dragon Ball/other games gain exact reference coverage without scraping or weakening rights controls.


## Original business milestone status

| Milestone | Current status | Remaining to call it complete |
|---|---|---|
| **1 — Three founders can log in, add physical cards, assign ownership/cost/condition/grade/location, search inventory and see exactly what they own** | **~96% overall / ~99% core inventory engine** | Restricted OWNER onboarding + owner-safe inventory/finance portal are deployed, and the genuine second-account cross-owner production isolation gate has passed. Final gate is onboarding the genuine third founder and repeating the live isolation verification. |
| **2 — Approved card syncs to Shopify, sells, and sale is attributed to the correct owner** | **~92%** | Single-owner real sale/refund is proven and restricted seller proceeds/settlement views are deployed; still need multi-owner/same-card production test and live payout cutover |
| **3 — Market data automatically updates valuation and recommended pricing** | **~80%** | Deterministic pricing + snapshots + provisional pricing exist; final provider permissions, eBay sold access/Marketplace Insights, stronger Cardmarket/eBay evidence automation and scheduled production refresh remain |


## 28 September 2026 — Personal Collection + owner-isolation production verification

**Personal Collection sale intent: PRODUCTION-VERIFIED —** `FOR_SALE ↔ PERSONAL_COLLECTION` is now a separate owner-intent dimension rather than another inventory lifecycle status. A controlled production verification used the existing archived single-item Shopify test inventory only: the physical Inventory ID, owner, acquisition cost, storage location and catalogue identity remained unchanged; moving to `PERSONAL_COLLECTION` wrote a dedicated `SALE_INTENT_CHANGED` audit event; there were zero active pooled memberships and zero live/uncertain eBay links; the remote Shopify product was confirmed at quantity 0 and changed from ACTIVE to DRAFT; returning the item to `FOR_SALE` wrote the reverse audit event and did **not** reactivate or restock Shopify. The item finished back in `FOR_SALE` / `INSPECTION`, while the archived Shopify product remained DRAFT with zero inventory.

**Milestone 1 owner isolation: SECOND-ACCOUNT PRODUCTION GATE PASSED / THIRD FOUNDER STILL OUTSTANDING —** production currently has two active founder owners. Using the genuine second founder account inside a rollback-only production security probe, its membership was temporarily evaluated as restricted `OWNER`: RLS exposed exactly one owner row, zero of Founder 1's 509 inventory items, zero Founder 1 order items/ledger rows/payout requests, and a cross-owner inventory UPDATE affected zero rows. The reciprocal probe evaluated Founder 1 as restricted `OWNER` and exposed its own 509 inventory rows, one order item and five ledger entries while allowing its own-row update. The restricted account also failed the platform-admin check as expected. All role changes and mutation probes were transactionally rolled back; the live second founder membership remains `PLATFORM_ADMIN`.

**Ownership reassignment defense: VERIFIED —** the application inventory patch schema does not accept `owner_id`, every founder inventory mutation binds the requested Inventory ID to the authenticated current owner, and `tcg_api` has no UPDATE privilege on `inventory_items.owner_id`. A rollback-only production probe attempting to change another founder's `owner_id` was rejected by column privilege. Platform admins intentionally retain broad internal visibility for Founder HQ/system workflows, so route-level owner binding remains an important second boundary.

**Remaining Milestone 1 gate:** onboard the real third founder account and perform the same live login/isolation check. No placeholder owner or invented physical stock will be created to manufacture this result.

## 28 September 2026 — repository re-baseline after n8n foundation

**Build-order correction: ACTIVE — n8n work is now treated as prepared infrastructure, not the current product phase.** The automation outbox/dispatcher, Railway-private webhook validation and version-controlled n8n image/provisioning foundation are merged, but advanced workflows remain gated. Product work returns to the original milestone sequence: close Milestone 1 multi-owner verification first, then finish the controlled Shopify/multi-owner sale loop, then production market-data/pricing automation. Consignment, AI listings, customer service, SEO, marketing and advanced n8n orchestration remain later phases.

**GitHub/main health: GREEN —** latest main CI after PR #220 passes both backend tests and the pinned n8n Docker image build/version check. PR #218 fixes the restricted OWNER invite creation 500; PR #217 permits dispatcher delivery to exact Railway-private HTTP hosts while continuing to reject unsafe public HTTP/lookalike URLs; PRs #219–#220 add reproducible n8n provisioning and CI validation without switching the live n8n service source.

**Open-PR hygiene:** PRs #215 (CRO/SEO experiment foundation) and #216 (Content Machine foundation) are intentionally not part of the current milestone and must not be merged until their known correctness/schema issues are fixed and the build reaches those phases. PRs #136 and #166 are older/superseded candidates and should be reviewed/closed rather than allowed to distort current build status.

**Immediate engineering priority:** prove Milestone 1 with a genuine second restricted OWNER account and cross-owner isolation across inventory, orders/finance, payouts/Stripe and Founder-HQ denial. Then run the controlled multi-owner/same-card sale attribution test for Milestone 2. Recognition/media correctness work continues only where it blocks those controlled inventory/Shopify tests; broad recognition expansion, storefront CRO/content and n8n workflow families do not take precedence over these gates.

## Current stage

## 28 September 2026 — AI experimentation / CRO / SEO blueprint

**AI experimentation engine: BLUEPRINTED — Drop Rate will treat CRO/SEO as a governed closed-loop optimization system rather than one-off AI copy generation. Postgres will own experiment truth; FastAPI will own experiment eligibility/statistical decisions; Shopify theme/app-extension surfaces will render validated variants; Shopify Web Pixels/customer events will provide behavior measurement; n8n will orchestrate hypothesis generation, launch, monitoring, rollback and rollout. AI may eventually autonomously launch and act on approved low-risk experiment classes, but arbitrary pricing, scarcity claims, ownership/finance, legal/privacy, checkout/payment behavior and unsupported factual claims remain outside autonomous authority. SEO experiments use page/template cohorts or sequential tests with stable public URLs and no crawler-specific cloaking. Detailed design lives in `docs/N8N_AUTOMATION_FOUNDATION.md` and `docs/STOREFRONT_AND_UX_BLUEPRINT.md`.**


## 28 September 2026 — Recognition v1.5.1 provider-challenger recovery

**Recognition v1.5.1: DEPLOYED — PR #213 / `5b507ed9` fixes a structural bias where provider-only exact-print candidates could be discovered and persisted but could not challenge a surviving local catalogue candidate in the resolver/UI. Strong unmapped provider printings can now surface as top evidence or runner-up challengers and force `NEEDS_REVIEW`; they remain non-confirmable until mapped to a real Drop Rate catalogue ID, so external data still cannot silently create canonical identity. Low-confidence collector-number OCR is now removed from One Piece provider retrieval when confidence is below 0.55, or below 0.85 with a strong ROUND1 marker, allowing name + gameplay stats + visual evidence to recover from tiny-number OCR errors. The number remains preserved as conflicting evidence for review. Engine version bumped to v1.5.1 so old image hashes do not replay stale v1.5.0 decisions. Full GitHub Backend checks passed and Railway deployment `770d79e1-665b-4212-ab46-4a8e61a1dde1` succeeded.**

**ROUND1 real-scan diagnosis: VERIFIED — production history showed three distinct Nami failure modes: (1) with clean ST29-008 OCR the local Round 1 catalogue candidate scored ~97.2% but exact-printing stayed fail-closed because provider artwork was ambiguous; (2) with tiny-number OCR `P-0?3`, the correct ST29-008 provider identity was present but buried among generic Nami candidates; (3) with OCR `OP02-036` at 0.78 confidence, provider retrieval anchored too strongly on the wrong number. v1.5.1 directly addresses (2) and (3) without weakening the exact-print confirmation gate.**

**Nami ST29-008 Round 1 external identity: CORROBORATED / MEDIA STILL UNRESOLVED — TCGplayer product 707242 and independent market references identify the Round 1 Promo as ST29-008, Yellow, cost 3, power 1000. No market-source mapping is being silently inserted through privileged SQL; the existing governed mapping API requires REVIEW → explicit verification. No marketplace photo or ordinary/full-art ST29-008 image has been attached as canonical media. `ST29-008_p1` remains explicitly NOT the Round 1 printing.**

## 28 September 2026 — n8n foundation + Dragon Ball adapter hardening

**n8n automation foundation: MERGED / PRODUCTION-DORMANT — PR #211 / `727f6819` adds a transactional `tcg.automation_events` outbox, lease/retry/dead-letter semantics, HMAC-SHA256 signed event envelopes, a Railway-ready dispatcher worker and the first domain event contract `inventory.approved`. GitHub Backend checks passed and the main API deployment succeeded. The database migration is intentionally NOT applied yet, no automation-dispatcher Railway service exists, no n8n webhook/secret is configured, and no Shopify/social action is enabled. Activation gate: create a signed n8n Event Gateway, verify signature/replay protection, apply the migration deliberately, deliver a development event, prove duplicate delivery is safe, then create the dispatcher service. Architecture/workflow plan: `docs/N8N_AUTOMATION_FOUNDATION.md`.**

**Dragon Ball TCGGraph hardening: DEPLOYED — PR #210 / `37591e59` fixes the adapter so Drop Rate's `Dragon Ball Super` maps to TCGGraph `line=masters` while `Dragon Ball Super Fusion World` maps to `line=fusion-world`; returned provider records must match the expected line. TCGGraph-derived images no longer auto-enter APPROVED/STOREFRONT_ALLOWED state: new matches remain PENDING + INTERNAL_REFERENCE_ONLY until exact-print and separate storefront-rights review. This is a correctness/rights hardening step only: production still has 0/33 Dragon Ball reference images because no production provider key is configured and current Dragon Ball physical languages remain unconfirmed.**

**Payout scheduler cron incident: RESOLVED — root cause was Railway Dockerfile Start Command exec-form handling. The old override `PYTHONPATH=backend python backend/scripts/run_payout_scheduler.py` was treated as a literal executable name and failed before Python started. Railway service config now uses `python /app/backend/scripts/run_payout_scheduler.py`, while `Dockerfile.scheduler` provides `PYTHONPATH=/app/backend`. PR #212 / `d1f8dc6e` added safe startup diagnostics; PR #214 / `47178e43` forced a fresh scheduler snapshot after the config correction. A controlled verification run at 2026-09-28 04:12:30 UTC completed SUCCESS, checked one owner, created zero payout requests, reported NO_BALANCE once and zero errors. Normal hourly schedule `0 * * * *` has been restored. No payout amounts, eligibility rules, Stripe state or money-movement logic were changed.**


## 29 September 2026 — Railway immediate-fix cleanup

**Dead-service cleanup: COMPLETE —** the previously unused Railway `drop-rate-api`
service has been repurposed as the internal 30-minute operations monitor rather than
deleted. The accidental duplicate `drop-rate-payout-heartbeat` service created during
the fix session has been removed. Production now has four services: the repurposed
operations monitor, `drop-rate-api-live`, the hourly payout scheduler and n8n.

**Historical empty staged patch: INVESTIGATED / NO RECOVERABLE ORIGIN —** Railway's
available API does not expose historical patch-content or origin metadata, so the
27 September zero-change patch cannot be attributed after the fact. It is no longer the
active patch. During this audit Railway created a fresh zero-change patch
(`changes: []`); the discard operation returned success but Railway's status API may
continue to display the empty shell. It carries no resource change and no deployable
configuration. Do not treat an empty patch as pending product work.

**Migration-history note —** Supabase currently records two historical migration-ledger
entries named `payout_scheduler_heartbeat` from the heartbeat rollout. The SQL itself is
idempotent and the live function is singular/correct. In accordance with the non-destructive
migration-history rule, those historical ledger rows have not been deleted or rewritten;
Claude should treat this as an audit note, not a schema repair request.

## 29 September 2026 — payout scheduler heartbeat hardening

**Payout scheduler heartbeat alerting: IN PROGRESS — production plumbing is now in place
and verified except for the first scheduled execution of the final combined operations
monitor after its networking correction.** PR #255 shipped the 90-minute deterministic
heartbeat, founder-only CRITICAL Action Required alerting, automatic recovery resolution,
failure-path coverage and a locked-down `SECURITY DEFINER` function executable only by
`tcg_api`. The migration is applied in production. A temporary independent SFO heartbeat
cron executed successfully at **2026-09-29 01:01 UTC** and reported the latest hourly
payout scheduler run healthy (`SUCCESS`, finished **01:00:26 UTC**). The final monitor
now lives on the repurposed Railway `drop-rate-api` service, runs
`backend/scripts/run_operations_monitor.py` every 30 minutes, has outbound IPv6 enabled,
and the redundant temporary heartbeat service has been removed. The final service remains
**IN PROGRESS**, not Completed, until one real scheduled run of that exact combined monitor
successfully completes after the IPv6 correction. No payout eligibility, amount, approval,
Stripe state or money-movement rule changed.**

## 28 September 2026 — recognition + image corpus checkpoint

**Recognition v1.5.1 / exact-printing retrieval: DEPLOYED — mobile/desktop scan intake, multi-signal evidence, exact-printing candidate handling, persistent recognition-reference fingerprint infrastructure, fail-closed promo/parallel handling, confidence-aware provider retrieval and unmapped-provider challenger surfacing are now in the live codebase. The system no longer treats card identity and exact physical printing as the same confidence problem. TCGAutomate remains the external benchmark; printer/device integration is intentionally later than recognition correctness.**

**Founder inventory image delivery: DEPLOYED — Founder HQ now loads eligible artwork through an authenticated Drop Rate backend proxy instead of direct browser hotlinks. The proxy validates image responses, supports source fallback ordering and prefers INVENTORY_ITEM media over CANONICAL_CARD media. Latest live deployment after the graded-card UI change is SUCCESS.**

**Card-by-card media audit: ACTIVE / HIGH COVERAGE — live inventory is 509 physical items / 462 unique catalogue entries. 420/462 unique entries currently have active front-image coverage: Pokémon 198/198, One Piece 222/231, Dragon Ball Super 0/28 and Dragon Ball Super Fusion World 0/5. One Piece language mismatches are 0 and all earlier guessed `Bandai Official Cardlist` rows have been removed/replaced. The remaining One Piece gaps are exact special-print/product cases and are deliberately unresolved rather than receiving approximate art.**

**Graded-media rule: DEPLOYED — graded inventory now distinguishes canonical reference artwork from the actual slab photo. INVENTORY_ITEM slab media takes precedence; canonical art is only fallback/reference. Founder HQ visibly marks graded items with canonical art but no slab photo as `Reference art · slab photo required`. Current graded inventory: 8 items, 0 slab-front photos, 7 canonical references, 1 canonical exact-image gap. Certificate numbers are still absent from the imported graded rows and should be captured when slab media is added.**

**Nico Robin correction: VERIFIED — ACE 10 Nico Robin OP01-017 Premium Card Collection - ONE PIECE FILM RED Edition was previously mapped to `OP01-017_p2`, which is the English 1st Anniversary Set artwork. Independent product-level verification confirmed the correct FILM RED printing is `OP01-017_p1`; the live media row has been corrected.**

**Storefront + Founder UX benchmark: BLUEPRINTED — `docs/STOREFRONT_AND_UX_BLUEPRINT.md` now defines the Shopify customer experience, autonomous merchandising/management model, TCG-native search/filtering, grouped-copy UX, graded PDP requirements, AI listing boundaries and Founder HQ workflow improvements. RandCards is the customer-storefront inspiration benchmark for collection-led shopping, live stock/condition clarity, set discovery and graded-card presentation; TCG Automate is the operations benchmark for scan/batch speed, quick corrections, card search, repricing, cross-listing and device workflows. Drop Rate must learn from those patterns without copying their design or brand, and exceed both through exact-print recognition, multi-owner/consignor accounting, auditable settlements and consumer recognition features.**

**Native mobile product direction: BLUEPRINTED — Founder HQ is planned to become a first-class iOS + Android app using the same backend and permissions as web, with inspiration from modern TCG collection/market apps such as Collectr, Pulse TCG and HoloDex while remaining operationally focused. It will be camera-first, support scan/intake, inventory, media/condition, pricing evidence, Action Required, sales, consignments, notifications and later Device Bridge printing/scanner workflows. The web dashboard remains the dense desktop control centre; mobile is purpose-built rather than a shrunken web UI.**


**Shopify ↔ eBay cross-channel inventory v1: DEPLOYED / PRODUCTION-DORMANT — PR #143 merged as `52dd8937`; controlled single-item eBay publishing, exact Inventory ID/SKU linkage, signed `ORDER_CONFIRMATION` intake, Shopify→eBay withdrawal, eBay→Shopify zeroing with remote verification, deterministic eBay channel pricing, audited eBay fee/postage reconciliation, return-to-INSPECTION isolation and safe re-listing are now deployed. GitHub CI and Railway pre-deploy both passed **563 tests**; Railway deployment `e3f6bade-f6e5-4c0a-a192-5b06340431a5` succeeded and `/health/ready` returned **200**. Production Supabase migrations `20260926144848_ebay_cross_channel_v1` and `20260926144947_index_ebay_cross_channel_fks` are applied. Live eBay tables remain empty and eBay publication is explicitly disabled. The remaining external blocker is seller-authorised eBay OAuth plus the seller's payment/fulfilment/return policy IDs, merchant inventory location and enabled order-confirmation notification subscription; no live eBay listing has been fabricated or published.**

**eBay seller OAuth connection v1: DEPLOYED / AWAITING RUNAME — PR #145 merged as `3688ea02`; Founder HQ now has a secure Connect eBay seller flow using eBay's Authorization Code Grant, 10-minute single-use CSRF state, encrypted refresh-token storage in Supabase with a separate Railway encryption key, and live discovery/selection of immediate-payment, fulfilment, return policies and enabled inventory locations. GitHub CI and Railway pre-deploy both passed **572 tests**; Railway deployment `87e5aeb8-5406-4b04-86d6-f4abe003bb73` succeeded and `/health/ready` returned **200**. Production publishing remains disabled. The only current manual prerequisite is the Production OAuth RuName generated in the eBay Developer Portal and configured with Drop Rate's callback URL; no seller refresh token or listing has been created yet.**

**Physical identity + language review v1: DEPLOYED — the verification queue now combines physical identity, EN/JP language evidence and optional registered location in one audited, version-protected review step. Identity confirmation fails closed while language is unknown or conflicts with the canonical card.**

**Founder media intake v1: DEPLOYED — founder-owned JPG/PNG/WebP card photos can now use Shopify staged uploads, explicit rights confirmation, governed media approval and the existing fail-closed Shopify media readiness gate. The first authenticated `write_files` scope + real-image upload remains a manual production verification.**

**Controlled commerce verification: ACTIVE — first real paid Shopify sale and full £5.48 refund/restock are production-verified; Finance Reconciliation v1 + Owner Settlement Report v1 are deployed, #1002 has exactly one £0.36 payment fee and explicit £0 postage reconciled, and a founder-only bounded batch fee-sync path is now live. External bank notification on 26 Sep confirms the #1002 refund is now on its way to the customer account. Shopify order remains REFUNDED; do not cancel it yet. Final fee/reconciliation completion is still to be verified before any cancellation decision.**

**Provider-independent sold-history evidence status v1: DEPLOYED — confirmed inventory can now report how many exact immutable SOLD observations Drop Rate already owns, dedupe the same external sale across multiple access paths, select the newest 5–10 exact comps, and recommend a refresh only when fewer than 5 usable sales exist or the newest evidence is stale. No provider call or Store Price write occurs in this status path. PR #125 / `386b466` is production-verified with 474 tests and `/health/ready` 200.**

**Provisional Store Price backfill: DEPLOYED/APPLIED — 506 previously-unpriced active items received auditable provisional Store Prices from the original dated Collectr Market Price export. Collectr values are treated as USD and normalized to GBP through the existing ECB historical FX model; 2026-09-20 observations use the previous available ECB business-day rate (2026-09-18), and 2026-09-24 observations use that day's ECB rate. Existing Store Prices were not overwritten. Live state after backfill: 507/509 active items priced; 2 remain unpriced because they only contain currency-ambiguous Price Override values. Every backfilled item received an immutable pricing snapshot; auto-publish remains false and sold-history evidence is still required for robust final pricing. PR #127 introduced the provisional workflow; PR #129 corrected USD→GBP normalization. Production baseline: 486 tests passing.**

**£1 minimum Store Price rule: DEPLOYED/APPLIED — Store Price is now commercially floored at £1.00 while Market Value remains evidence-derived and may legitimately be below £1. Manual intake/edit, provisional pricing, eBay sold pricing and the database constraint all enforce the floor. 363 live items were raised to exactly £1 with 363 immutable `store-price-floor-v1` snapshots; 362 of those retain a true Market Value below £1. Live state: 507/509 active items priced, 0 below the floor, 363 exactly at £1. The robust engine explicitly treats eBay UK and Cardmarket as the UK/EU pricing anchors; Collectr/TCGplayer are supporting confidence evidence and cannot set the displayed UK Market Value by themselves. PR #131 / `3728199`; production baseline 494 tests passing.**

**Shopify Store Price resync v1: DEPLOYED — founder-owned DRAFT/PUBLISHED Shopify links can now receive price-only updates when Drop Rate Store Price differs from the last synced price. Shopify I/O occurs outside DB transactions, exact remote variant/price is verified, local state is re-locked/version-checked before synced_price_minor changes, and SOLD/ARCHIVED/ERROR links are excluded. No quantity, SKU, cost, shipping, publication or inventory-state changes are performed by price resync. PR #128 / `68c98fa`. Current live eligible Shopify links have no price drift. The only drift is the archived Seel test link, which intentionally preserves the historical £0.49 Shopify price while the current inventory Store Price is now £1.00.**

**Dashboard inventory intelligence v1: DEPLOYED — the founder Dashboard now shows total Inventory Market Value, total Store Price value, Top 5 highest-value products and genuine 7-day Market Value movers. Movement is calculated only from immutable historical pricing snapshots; the UI explicitly stays empty until a real 7-day baseline exists rather than fabricating change from the initial backfill. Live production snapshot: 509 active items; 506 have Market Value totalling £979.57; 507 have Store Price totalling £1,281.88. The oldest current pricing snapshot is 25 Sep 2026 23:25 UTC, so there is not yet a genuine 7-day comparison baseline. Commit `ee5c9f2` is production-verified.**

**Audited exact-import identity confirmation v1: DEPLOYED — original import evidence may confirm identity only when source name, set, collector number, compatible finish and one explicit EN/JP marker all exactly agree with the current record. The second locked phase re-validates the evidence and writes an `IMPORT_EXACT` verification event; it never pretends an inferred match was a physical review. Live state: 97/509 active items are confirmed (96 Japanese, 1 English). The remaining 412 unconfirmed items all still have unknown physical language, so they remain fail-closed for human/physical verification rather than being bulk-confirmed. Commit `b881f1e` is production-verified.**

**Batch founder media intake v1: DEPLOYED — Settings can now validate and upload a founder-owned image batch sequentially against the live media queue. Raw equivalent copies share one canonical FRONT capture; graded cards require item-specific FRONT + BACK. Duplicate live sides fail closed in both API logic and database unique indexes. The two production uniqueness indexes are verified present. Current live media registry contains 0 assets, so no stock is being treated as media-ready without evidence. Commit `942d6d9` is production-verified.**

**Shopify readiness funnel v1: DEPLOYED — the Dashboard separates deterministic sellability blockers from governed media blockers. As of the Media & Condition rollout, raw cards also require photo-backed Near Mint verification and graded cards require slab verification before they can count as sellability-ready. The endpoint remains founder-scoped, read-only, makes zero Shopify network calls and has no publication action; final Shopify completeness remains a separate fail-closed check.**

**Mobile founder media capture station v1: DEPLOYED — the single-card founder media flow now supports rear-camera capture on compatible phones, shows the exact selected queue identity + required side, adds Previous/Next queue navigation with no API side effects, clears stale file/alt-text state when changing cards, and advances after a completed queue item disappears. Existing rights confirmation, duplicate-side protection, governed upload/approval/sync flow and final Shopify publication gates remain unchanged. PR #138 / `7244ecb`; GitHub CI and Railway pre-deploy both passed 517 tests and production `/health/ready` returned 200.**

**Media & Condition workflow v1: DEPLOYED — every physical card Inventory ID now requires its own FRONT + BACK photos; raw capture records whether the card is unsleeved, in a penny sleeve or in a top loader, while graded inventory uses a graded-slab context. Canonical/reference media can no longer satisfy a card's sellability media gate. Raw cards require human photo-backed `VERIFIED_NEAR_MINT`; graded cards require `VERIFIED_GRADED`; below-NM cards remain auditable and are blocked from Shopify. Reshoots reopen the exact evidence side. Media management now lives in a dedicated Media & Condition workspace rather than Shopify Settings, with a simplified founder navigation and cleaner desktop/mobile UI. Existing 509 inventory records were deliberately left `NOT_REVIEWED`; no condition status or media was fabricated. PR #139 / `6d2da16`; GitHub CI and Railway pre-deploy both passed **526 tests**, production `/health/ready` returned 200, and post-migration RLS/security checks found no new condition-review security warning.**

**Founder dashboard anime/TCG redesign v2: DEPLOYED — the founder workspace now uses the established Drop Rate compass/card/ribbon brand language with deep navy, turquoise, gold and orange/red rather than the previous grey/lime admin styling. Dashboard hierarchy is simplified around command-centre hero → KPIs → portfolio/readiness → action required; Inventory prioritises the stock table and moves Storage Locations/Purchase Lots into expandable utility drawers. Desktop navigation is a branded left rail, mobile remains compact, and Media & Condition shares the same visual system. Stylesheet cache-busting was added so stale browser assets cannot mask the redesign. PR #140 / `3fb1e6a`; GitHub CI and Railway pre-deploy both passed **531 tests** and production `/health/ready` returned 200.**

**Founder UI + Sales Analytics v3: DEPLOYED — the recreated brand mark/wordmark has been removed in favour of the user's uploaded Drop Rate logo artwork, with only a subtle `FOUNDER HQ` label beneath it. The same logo artwork is reused on the dashboard hero card backs and the buggy orbit/spinner effect has been removed. Media & Condition now uses a compact refresh action and an aligned Evidence Registry grid. Sales now has founder-scoped deterministic date-range analytics from Postgres/ledger data with Europe/London business-day boundaries: All time, Today, Yesterday, Last 7 days, This week, This month, This quarter, This year and custom dates; KPIs include Total Sales, Net Revenue, Net Profit, Orders, Items Sold and Average Order Value, with refunds, fees, postage, materials, COGS and adjustments included and profit left pending while Shopify reconciliation is incomplete. PR #141 / `7f09c14`; GitHub CI and Railway pre-deploy both passed **537 tests**, deployment `29dd8ac7-0d10-4219-9383-33a439e7830b` succeeded and production `/health/ready` returned 200.**

The latest pass exposed an important process improvement: we were testing individual features well, but not performing a sufficiently explicit system-level regression/review after every cluster of changes. From this point forward, every material feature is subject to a repeatable quality gate covering code tests, failure-path review, database invariants, migration reproducibility, production deployment/health and live-data verification.

The current backend is intentionally fail-closed: identity confirmation is required before pricing/listing, Shopify bulk publishing is disabled, market-data persistence is disabled, and no automatic money movement is enabled.

The next Shopify checkpoint is to re-check the external Shopify Payments refund settlement for #1002, use the new batch fee-sync path to verify final fee completion/idempotency, then verify the first founder media upload in production. The £0.36 payment fee and legitimate £0.00 postage are already reconciled. Operational inventory cleanup continues in parallel.

## Production-verified foundation

### Architecture / infrastructure
- private GitHub repository + branch / PR / CI workflow
- Railway production deployment
- Supabase/PostgreSQL master database
- FastAPI deterministic business layer
- Supabase authentication
- audit logging
- optimistic version protection
- browser security headers
- single-founder scope for current phase
- provider adapters separated from deterministic pricing logic
- n8n intentionally not used as database or core business-logic layer; durable outbox + signed dispatcher foundation is merged, with production activation deliberately gated until a verified n8n Event Gateway exists
- `database/migrations/**` is the canonical version-controlled migration directory
- legacy `migrations/**` is frozen historical material; new migrations must not be added there
- Supabase-native migration history is the authoritative applied-migration ledger

### Inventory
- canonical catalogue separated from physical inventory
- unique physical Inventory IDs
- search / filters / pagination
- Action Required workflow
- acquisition cost/date with unknown cost preserved as NULL
- Purchase Lots, fees, shipping and landed-cost allocation
- raw-card TCGplayer condition scale
- sealed/unsealed inventory state
- grading company / grade / certificate
- language
- registered Storage Locations + stock audit
- manual single-item intake
- manual intake idempotency now validates payload identity: same key + same payload replays; same key + different payload returns conflict
- unified CSV import framework
- Collectr / eBay Purchases / HoloDex / Generic CSV presets
- conservative catalogue matching with REVIEW state for ambiguous rows
- raw import provenance and SHA-256 duplicate-file protection
- manual import REVIEW-row resolution
- approval/readiness workflow
- persisted JSON/JSONB is decoded consistently at the asyncpg connection boundary
- PostgreSQL now enforces physical-state invariants regardless of write path
- SOLD/historical mutation failures are returned as safe conflict responses rather than generic server errors

### Purchase lots / storage
- deterministic total landed cost = purchase price + fees + shipping
- equal/manual allocation support
- penny-perfect allocation
- registered `storage_location_id` is now the canonical approval/readiness location gate; the legacy text `location` field is synchronized from the registered location
- unnecessary `DELETE` permission on purchase lots was removed from the application role
- missing application-role UPDATE grants for newer inventory fields were fixed, including storage, purchase-lot, seal-state and pricing-output fields

### Internal commerce / founder finance
- internal orders and physical order items
- acquisition-cost snapshot at sale time
- SOLD inventory state
- append-only owner financial ledger
- revenue / COGS / gross profit / net profit
- payment/platform fees
- shipping income / shipping cost
- refund/return foundation
- deterministic penny-perfect allocation
- pending / available / reserved / paid-out balances
- payout request + cancellation workflow
- Finance Reconciliation v1: typed Shopify transaction-fee import, zero-safe postage reconciliation, RLS-protected/audited reconciliation metadata, refund-driven fee invalidation and founder Sales controls
- founder-only bounded batch fee reconciliation: pending Shopify fee records can be checked in batches without holding a database transaction open across Shopify API I/O; per-order blocked/pending states remain fail-closed and visible
- Owner Settlement Report v1: read-only owner-scoped settlement aggregation showing gross proceeds, explicit external deductions/adjustments, net owner proceeds, effective COGS, owner profit, reconciliation state and pending/available funds
- no automatic money movement
- manual/off-platform sale support before Shopify
- duplicate/repeated actions protected by source/reference uniqueness and idempotent paths

### Founder seller portal
Production navigation is split into:

- **Dashboard**
- **Inventory**
- **Sales**
- **Reports**
- **Balance**
- **Settings**

Existing working inventory/finance components were reorganised rather than rewritten. URL hashes such as `#inventory` and `#balance` are supported.

## Access-control boundary — Founder HQ vs seller/consignor portal

**Founder HQ is an internal administrative product.** It is intended only for the primary platform administrator and any explicitly invited trusted admin/staff accounts. External sellers and consignors must never receive Founder HQ access merely because they own inventory.

Account permission and physical inventory ownership are separate concepts:

- **PLATFORM_ADMIN / trusted internal admin:** full Founder HQ access across all owners, inventory, company-wide sales/analytics, market-data controls, Shopify/eBay/Stripe integrations, payout approval, owner assignment, commission settings, audit views and global configuration.
- **SELLER / CONSIGNOR user:** owner-scoped portal only. May view their own submitted/approved/listed/sold inventory, own sale proceeds, deductions/commission, settlement status and payout history/preferences. Permitted edits must be explicit and narrow (for example profile/payout settings and future listing-price requests); no global settings or other-owner records.
- **Server-side enforcement required:** hidden navigation is not security. Every seller-facing API/query must be owner-scoped through database/RLS + FastAPI authorization. Cross-owner reads/writes, owner reassignment, commission edits, settlement adjustments, payout approval, integrations and global analytics remain admin-only.
- **Separate shell recommended:** build a dedicated seller/consignor dashboard rather than reusing Founder HQ with merely hidden tabs. This reduces accidental privilege leakage and keeps the UX focused on each owner's own stock and money.
- **Action Required:** design the role/permission schema and invitation/onboarding flow before enabling any non-admin user accounts.

## Market-data infrastructure

### Core market framework
- provider-neutral source mappings
- supported source slots: eBay, Cardmarket, TCGplayer, Collectr
- VERIFIED mapping gate before automatic ingestion
- immutable historical market observations
- observation deduplication by `(source, source_record_key)`
- source / condition / grade / language / seal-state normalization fields
- GBP-normalized values + FX provenance fields
- provider-neutral adapter registry
- immutable market-ingestion run history
- provider health/status API
- deterministic pricing engine remains separate from provider access
- no raw provider response can silently overwrite Store Price
- UK pricing guardrail requires UK/EU anchor evidence for trusted displayed Market Value
- TCGplayer / Collectr remain supporting evidence rather than sole UK Market Value anchors

### Market hardening completed in this chapter
- Parse authentication verified with the current production key
- safe provider error messages do not expose credentials or raw response bodies
- smoke/provider diagnostics are authenticated and non-persistent
- provider calls no longer hold a PostgreSQL transaction open while waiting on external HTTP
- real ingestion was refactored to avoid the same idle-in-transaction failure class
- diagnostic run timestamps use the database clock
- diagnostic run logging persists correctly
- Parse snapshot pinning is optional; current canonical releases can be used deliberately
- eBay retrieval queries were broadened while post-retrieval identity acceptance remains strict
- title matching tolerates punctuation / seller word order without weakening hard card/variant/grade identity checks
- real production ingestion is **explicitly gated off by default**; presence of a Parse key alone cannot enable persistence
- provider probe counts the provider-specific result collection instead of the largest array in the response
- eBay finish matching now rejects explicit Foil listings for Normal targets plus Non-Holo/Non-Holofoil and Non-Foil contradictions, preventing those titles from contaminating pricing evidence

### Final cross-provider live validation
Final production probe on 23 September 2026:

| Source / endpoint | Result | Interpretation |
|---|---:|---|
| eBay UK active | **72 listings** | ✅ live provider access working |
| eBay UK sold | **0 listings** | ⚠️ isolated upstream sold-search issue; Drop Rate receives an empty provider array before matching |
| TCGPlayer search | **10 cards** | ✅ live provider access working |
| Collectr search | **30 items** | ✅ live provider access working |
| Cardmarket search | earlier probe: **29 results** | ✅ provider previously validated; final run did not emit a response-shape line and should be rechecked before production ingestion |

Important conclusions:
- Drop Rate's provider plumbing is working; the system is not generally blocked on market APIs.
- eBay's active path works, while the Parse/eBay UK sold path currently returns an empty `items` array before Drop Rate filtering.
- Cardmarket is the strongest currently validated UK/EU pricing-anchor candidate, but production ingestion remains gated until source access/terms and live contract are approved.
- TCGPlayer and Collectr can provide supporting/global evidence after source-specific ingestion re-validation.
- eBay sold should be treated as an independent provider issue rather than blocking the rest of the platform.

### Pricing engine
- robust source-level weighted pricing rather than simple average
- sold vs active-listing weighting
- recency weighting / half-life logic
- comparability by condition / grading / language / seal state
- outlier handling
- volatility and confidence calculation
- source-count and evidence-quality weighting
- outputs:
  - Market Value
  - Recommended Retail
  - Quick-Sale Price
  - Target Acquisition Price
- immutable pricing snapshots
- pricing policy configuration
- high-value / low-confidence / volatile-price review guards
- batch and single-item recalculation API
- pricing history API
- latest pricing outputs visible in Settings
- **Store Price is never silently overwritten by pricing calculation**
- graded-card comparison now treats grading company + grade as the condition dimension rather than incorrectly requiring a raw marketplace condition too
- current pricing algorithm version after that correction: `drop-rate-market-v4`

## Current live inventory readiness

Production checkpoint on 24 September 2026:

- physical inventory items: **509**
- status: **508 DRAFT / 1 INSPECTION**
- unknown acquisition cost: **0**
- missing condition: **10**
- missing storage location: **507** (Baltoy is in `ROOM-BOX`; approved Seel test candidate is in `ROOM-BOX/BINDER-01`)
- missing Store Price: **508**
- identity not yet confirmed: **508**
- missing owner: **0**
- missing catalogue reference: **0**
- duplicate Inventory IDs: **0**
- language: **1 English / 96 Japanese / 412 unknown/review required**
- portfolio acquisition cost basis: **£951.83 total (£1.87 per physical unit)**
- largest known cleanup group: **178 Phantasmal Flames items**

Acquisition cost is now populated for the current imported portfolio. Future unknown costs must still remain NULL until deliberately assigned.

### Language evidence correction — production verified

A production audit found that all **413** rows previously marked English had been changed from `NULL → English` in one unsupported bulk operation. None of those 413 source records contained explicit English evidence, while all **96 Japanese** rows contained explicit JP/Japanese evidence.

The unsupported English backfill was therefore rolled back fail-closed:
- inventory: **0 English / 413 unknown / 96 Japanese**
- affected catalogue identities: **373** changed from English to unknown
- audit trail: **413 inventory + 373 catalogue** English→NULL events under migration request `migration:20260924220735_revert_unsupported_english_language_backfill`
- current Collectr importer already sends missing language to REVIEW and does **not** infer English
- Shopify links/listings/reservations remained **0** throughout the correction

The first physical test candidate, Baltoy `INV-041416049F4249C6BB29A846E29DDC37`, remains **DRAFT**. Near Mint condition and physical location `ROOM-BOX` are retained, but identity confirmation was revoked after the imported `Ninja Spinner 046/083 + English` combination failed external identity validation. Its Store Price remains NULL and it has not been published to Shopify.

The controlled Shopify candidate Seel `INV-06F489A853594CDC80E418271933D044` has now completed the first production-verified **paid sale + full refund/restock** lifecycle:
- canonical identity: **Seel / Phantasmal Flames / 021/094 / Normal / English**
- physical condition: **Near Mint**
- registered storage: **ROOM-BOX/BINDER-01**
- acquisition cost snapshot: **£1.87**
- Store Price / sale price: **£0.49**
- Shopify order: **#1002**
- original Shopify Payments transaction: **SUCCESS / £5.48 / not test mode**
- original shipping charged: **£4.99**
- exact Shopify Inventory ID/SKU link: verified
- exact order-item allocation to this physical Inventory ID: verified
- original ledger: **£0.49 SALE_REVENUE + £4.99 SHIPPING_REVENUE**
- full refund webhook verified: **−£0.49 REFUND + −£4.99 SHIPPING_REFUND**
- Drop Rate order state: **REFUNDED**
- physical inventory state: **INSPECTION** (never auto-returned to APPROVED)
- Shopify inventory link state: **ARCHIVED**
- Shopify stock after return handling: **0 available / 0 committed / 0 on hand**
- refund events: **1**
- total ledger entries for the sale/refund lifecycle: **5** (sale + shipping revenue + item refund + shipping refund + payment fee)
- Shopify Payments refund transaction was still **PENDING settlement** at the latest check; do **not** cancel #1002 until that external refund state is re-verified
- exactly one Shopify Payments fee is recorded: **−£0.36 PAYMENT_FEE**; actual postage is explicitly reconciled at **£0.00** because the test order was not shipped. Fee reconciliation remains incomplete while Shopify's REFUND transaction is still externally pending
- Shopify delivered `orders/paid` before `orders/create`; the late create initially failed, then the event-ordering/idempotency path was hardened and deployed so paid-before-create and semantic duplicate paid events fail closed/no-op correctly

## Supabase live checkpoint

Current production data after the latest hardening + language pass:

- project: `pull-theory-dev`
- region: `eu-west-2`
- PostgreSQL: **17.6**
- physical inventory: **509**
- market observations: **0**
- pricing snapshots: **0**
- market ingestion/diagnostic runs: **25**
- audit events: **3,591**
- Shopify inventory links: **1 total / 0 active sellable** (Seel link is ARCHIVED after refund)
- marketplace listings: **0**
- active reservations: **0**
- physical identity confirmation events: **3**
- Shopify orders: **1**
- Shopify order-item links: **1**
- refund events: **1**
- financial ledger entries: **5**
- Shopify webhook events: **5**
- RLS remains enabled across operational business tables; `tcg.schema_migrations` is the known exception and currently grants only `SELECT` to `tcg_api`
- provider diagnostics have **not** polluted market observations, pricing snapshots or inventory values

Supabase security advisor status:
- database/security configuration reviewed during this chapter
- leaked-password protection is still disabled and remains a **manual pre-launch Auth setting** to enable in Supabase
- `tcg.schema_migrations` currently has RLS disabled; current grants were checked and only `tcg_api` has `SELECT`. Do not enable RLS blindly without a migration-tooling policy.
- currently-unused-index notices are expected on newly created / low-row-count modules and are not being removed prematurely

## Regression / hardening work completed

The following areas were reviewed and defects found were corrected:

### Authentication / security
- authenticated dashboard/API routes verified in production
- owner/catalogue integrity checked in live inventory
- RLS coverage reviewed
- provider credentials kept out of logs and API responses
- historical/immutable mutation errors normalized safely
- application-role privileges reviewed and tightened

### Inventory / imports
- unknown acquisition cost remains NULL
- inventory-code uniqueness verified
- manual intake idempotency strengthened against key reuse with different payloads
- import REVIEW resolution completed
- JSONB decode path fixed for import commit and generalized at DB connection boundary
- physical-state database invariants added/verified
- live inventory contains zero physical-state invariant violations
- unsupported historical English-language backfill identified from audit history and rolled back to unknown without altering the 96 evidence-backed Japanese items
- Baltoy physical verification trail preserved as CONFIRMED then REVOKED after catalogue/language conflict discovery; physical condition and storage remain intact

### Purchase lots / storage
- approval/readiness now requires the canonical registered Storage Location, matching the Shopify test-sync gate
- application-role UPDATE permissions corrected for newer columns
- purchase-lot DELETE privilege removed

### Finance
- append-only / uniqueness protection reviewed
- SOLD-state protections reviewed
- refund/payout/ledger foundations retained
- database conflict failures no longer fall through as generic 500s where historical mutation is rejected
- explicit `SHIPPING_REFUND` ledger type added; full Shopify shipping refunds no longer remain as false retained revenue
- refund handler caps shipping reversal at recorded shipping revenue and allocates it deterministically/penny-perfect across order items
- full refund with restock verified in production: Seel moved SOLD → INSPECTION, Shopify link ARCHIVED and Shopify available stock forced to 0
- finance dashboard now distinguishes **shipping paid by the customer** from **actual postage cost**
- unknown Shopify/payment fees and postage cost display as **Pending**, not £0.00
- profit remains **Pending** with a provisional figure until fee/postage entries actually exist
- owner settlement reporting keeps **net owner proceeds** separate from **owner profit** so acquisition cost is never incorrectly withheld from owner proceeds
- first live `Sync fees` and `Set postage` attempts returned HTTP 500 because the generic finance audit trigger assumed an `id` column; `order_item_reconciliations` is keyed by `order_item_id`
- production migration `20260925144808_fix_order_item_reconciliation_audit_trigger` now uses a dedicated audited trigger keyed by `order_item_id`; RLS and finance rules were not weakened, PUBLIC execute was revoked, and regression coverage was added
- post-hotfix live retry verified both reconciliation endpoints at HTTP 200; payment fee ledger now contains exactly one −£0.36 entry and £0 postage is explicitly reconciled without a fake zero-value ledger row
- settlement adjustments are explicit signed ledger components; pending vs available cash remains separate from reconciliation readiness
- returned-to-stock items use effective COGS £0 for that realised sale because the physical asset has returned to inventory

### Market / pricing
- provider transaction boundary fixed in smoke tests and real ingestion
- ingestion-run logging fixed
- flexible-but-strict eBay identity matching added
- explicit finish-negation guards added: Normal cannot accept Foil, Holo/Holofoil cannot accept Non-Holo/Non-Holofoil, and Foil cannot accept Non-Foil
- provider-response diagnostics added
- production-ingestion safety gate added
- guarded Shopify single-item readiness now exposes exact blockers and uses the same eligibility function as the actual publish action
- registered storage location is enforced consistently by approval/readiness and Shopify sync
- Shopify 2026-07 inventory quantity payload fixed (`changeFromQuantity`, no obsolete `ignoreCompareQuantity`)
- Shopify inventory activation fixed to avoid conflicting `available` + `onHand` arguments
- unpaid checkout reservations are tracked on exact physical Shopify links/inventory state, not in finance orders
- `tcg.orders` again rejects PENDING rows at the database constraint level; unpaid checkout state stays outside finance records
- first real paid order #1002 verified exact Inventory ID → SOLD → order item → COGS snapshot → sale/shipping ledger
- paid-before-create webhook ordering and semantic duplicate paid handling hardened after Shopify delivered #1002 events out of order
- graded comparable-condition bug fixed
- cross-provider live access validated as recorded above

### Deployment / reproducibility
- Railway production service remains `drop-rate-api-live`
- latest production deployment is **SUCCESS** on commit `72b789a9fd8a3d4c4a1d4f7f31e650cdae002c1f`; `/health/ready` returned **200 OK**
- PR and post-merge GitHub CI are green for the latest hardening commits
- Railway production has a **pre-deploy compile + pytest gate**; the missing `pytest-asyncio` dependency was fixed after deployment logs exposed 43 silently skipped async tests
- Railway now installs pinned **Node 22.23.3 LTS** alongside Python through `RAILPACK_PACKAGES`, so frontend/static checks run in the production pre-deploy gate too
- current Railway regression result: **444 passed, 0 skipped**; `/health/ready` returned **200 OK** after deployment
- live database integrity checks: **0 duplicate Inventory Codes, 0 language mismatches, 0 confirmed-without-evidence, 0 active-reservation/state mismatches**
- migration history reconciled through `20260925162748_shopify_shipping_profiles`, including Finance Reconciliation v1, the reconciliation-specific audit-trigger hotfix and deterministic Shopify shipping profiles
- `database/migrations/**` is now the only canonical location for new migration files
- Railway `Wait for CI` still reads **OFF** (`checkSuites=false`) after two attempted staged updates; treat this as an external Railway/GitHub-integration permission/configuration blocker until the setting can be re-authorised and verified
- the guarded Supabase migration workflow is merged (`workflow_dispatch`, dry-run by default, explicit apply mode). Its required GitHub secrets and first production dry-run still need to be verified before the next schema change
- no unintended staged Railway configuration remains

## Quality / regression gate

A feature is not considered complete merely because its unit tests pass. For material changes, the following gates are now mandatory:

1. **Design review:** what is changing, why it belongs, dependencies, failure modes and exact test plan are recorded before implementation.
2. **Automated regression:** targeted tests plus the full backend suite must pass.
3. **Security / integrity review:** RLS/permissions, ownership boundaries, idempotency, concurrency and immutable/audit behaviour are checked where relevant.
4. **Migration review:** every database change has a version-controlled migration in `database/migrations/**`; production migration history must match the repository.
5. **Production deployment:** Railway deployment succeeds and health/readiness is verified.
6. **Live invariants:** production queries verify counts, uniqueness, state transitions and cross-table relationships after deployment or data mutations.
7. **Failure testing:** deliberate bad inputs, duplicate events, stale versions, unavailable records and provider failures are tested before a feature is treated as safe.
8. **Release decision:** any unresolved critical integrity issue keeps the feature gated, even when CI is green.

Current production regression baseline: **448 passed, 0 skipped** in Railway pre-deploy; GitHub PR and main-branch CI are green. Live inventory integrity currently reports zero duplicate Inventory Codes, zero active reservation/state mismatches and one archived Shopify link for the refunded Seel test item now in INSPECTION.

GitHub status checks can be required on protected branches, but the current integration cannot read classic branch protection for this private repository, and the GitHub rulesets endpoint reports that private-repo rulesets require GitHub Pro (or a public repository). Treat branch protection as a manual/account-plan check before multi-contributor development. Railway's own `Wait for CI` setting is also currently off, so the pre-deploy test gate is intentionally retained as defence-in-depth.

## Shopify product completeness contract

A Shopify product is not considered publishable merely because a product/variant exists. The backend must treat **product completeness as a deterministic publication gate**. Products remain `DRAFT` until every required field below has an approved source, passes validation and is written successfully.

| Shopify field | Source / rule |
|---|---|
| Title | Deterministic backend template from canonical card identity + explicit language + card number + variant + condition/grade. Never AI-invented. |
| Description | Structured facts from Supabase; AI may polish wording, but validators must prevent invented set/rarity/condition/grade/language/price claims. |
| Media | Approved media pipeline only; provenance and source rights must be stored. See media strategy below. Missing required media blocks publication. |
| Category | Deterministic Shopify taxonomy mapping by product type/game. |
| Price | `store_price_minor` from Drop Rate only. Shopify never becomes pricing source of truth. |
| Inventory | Exact sellable physical quantity from Drop Rate. Single-item listing = 1; no overselling. |
| Shipping | Deterministic owner-scoped shipping profile. RAW_CARD / GRADED_CARD weight is configured once, written to Shopify `InventoryItem.measurement.weight`, then read back and verified. Missing profile blocks publication; no AI assumptions. |
| Variants | Unique/physical-item listings use one controlled variant unless a deliberate pooled-listing model says otherwise. Language/condition/grade must never be silently collapsed. |
| Product metafields | Exact Drop Rate identifiers and structured card facts. Inventory ID is mandatory for single-item listings. Ownership remains backend-private and is not customer-facing. |
| Search engine listing | Deterministic handle plus validated SEO title/meta description generated from real database facts. |
| Status | `DRAFT` until completeness gate passes; only then `ACTIVE`. |
| Publishing | Publish only to explicitly configured publication/channel after all gates pass. Bulk publishing stays separately controlled. |
| Sales | Shopify records checkout/order facts; Drop Rate resolves each sale back to exact physical Inventory ID and owner. |
| Product organisation | Deterministic product type, vendor, normalized collections and tags from game/set/variant/language/status rules. |
| Theme template | Explicit product template selected by product type/listing model; never Shopify default by accident. |

### Media strategy — avoid manually scanning the whole inventory

The system should support two media classes:

1. **Canonical/licensed reference media** for ordinary raw cards where a permitted provider supplies reusable card imagery. The source URL/provider/license/provenance must be recorded against the canonical CARD. One approved canonical image can serve multiple equivalent physical copies.
2. **Physical-item media** for high-value, graded, unusual-condition, signed, altered, sealed or otherwise item-specific inventory. These items should require actual front/back/item photography before publication.

The intended operational workflow is **batch capture, not manual scanning**:
- camera/phone capture station
- Inventory ID / QR or barcode associates each shot with the exact item
- automatic crop/deskew/background cleanup
- AI may help detect front/back, orientation and image quality
- human review only for low-confidence/image-quality exceptions
- approved files stored once and referenced by the backend
- Shopify receives only media that has passed provenance + quality checks

Do **not** assume card-image reuse from eBay, Collectr, TCGplayer, Cardmarket or other providers is permitted. Reuse only when provider terms/licensing explicitly allow it. If no permitted canonical media exists, the item remains DRAFT until approved physical media is captured.

### Product completeness release rule

Before activation/publication, the backend must verify at minimum:
- canonical identity confirmed
- language explicit
- condition/grade valid
- registered physical location
- acquisition cost known
- Store Price known
- exact SKU / Inventory ID
- media policy satisfied
- shipping profile resolved (`RAW_CARD` or `GRADED_CARD`) with an approved positive weight/unit
- Shopify `requiresShipping=true` and remote weight/unit exactly match the Drop Rate shipping profile
- required metafields present
- title/description/SEO validators pass
- product type/vendor/collections/tags/template resolved
- Shopify quantity matches backend sellable quantity
- publication target configured
- no duplicate active Shopify link for the physical item

Any failed check leaves the product DRAFT and creates an Action Required reason rather than guessing.

### Shipping specification implementation

- production registry: `tcg.shopify_shipping_profiles`
- supported v1 forms: `RAW_CARD`, `GRADED_CARD`
- owner/profile key is immutable; updates use optimistic versioning
- profiles are RLS-protected and audit logged
- Shopify 2026-07 inventory input writes `requiresShipping=true` plus `measurement.weight`
- draft and final verification read the remote weight back before publication is treated as complete
- optional Shopify package GID can be stored, but v1 only treats surfaces that can be remotely verified as hard completeness evidence
- no default weight has been seeded; zero profiles currently exist until the founder explicitly configures them
- migration `20260925162748_shopify_shipping_profiles` was applied early during preflight because the migration file contained its own transaction; the empty backward-compatible schema was verified and the Supabase migration ledger was then reconciled to the canonical merged file without rerunning `CREATE TABLE`

## Storefront / UX issues now explicitly tracked

These are now first-class roadmap items rather than informal design ideas:

1. **No custom Drop Rate Shopify theme yet:** the Shopify integration/backend is mature, but the customer storefront remains largely generic/unbuilt.
2. **Duplicate physical-copy clutter risk:** multiple Inventory IDs for the same canonical card must not flood collection pages; solve this at the storefront presentation layer without weakening ownership accounting.
3. **TCG-native search gap:** customers need card-number, set-code, rarity, language, printing, condition and grade search—not generic ecommerce search alone.
4. **Graded product presentation:** actual slab front/back + grader + grade + certificate should be primary customer evidence.
5. **Autonomous merchandising:** New Drops, Grails, Graded, Fresh Japanese Stock, movers, low-stock and set collections should be database-driven rather than manually curated.
6. **Autonomous Shopify operations:** creation, price/stock/media sync, collections, SEO, archive/restore, drift detection and safe retries should be automated through backend rules.
7. **Founder HQ throughput:** evolve toward TCG Automate-level batch speed while retaining Drop Rate's stricter exact-print evidence, owner attribution and auditability.
8. **Mobile-first store + operations:** storefront collection/search/PDP and Founder HQ scan/intake need purpose-built mobile layouts.
9. **Performance at scale:** design now for 5,000–50,000+ cards with dense grids, pagination/virtualisation, image delivery and indexed search.
10. **AI authority boundary:** AI may generate content and suggestions but cannot silently change identity, owner, price rule, settlement or publication gates.
11. **Native app parity:** mobile workflows must use the same backend truth, permissions and audit rules as Founder HQ while being purpose-built for camera-first operational use.

Detailed implementation blueprint: `docs/STOREFRONT_AND_UX_BLUEPRINT.md`.

## Known remaining items

These are **not blockers to the current backend foundation**, but remain explicit work:

1. **GitHub branch protection:** verify `main` requires pull requests + passing CI before the project expands to multiple contributors.
2. **Railway Wait for CI:** `checkSuites` remains false despite two attempted updates; re-authorise/check the Railway GitHub App permissions and verify the toggle persists.
3. **Supabase migration delivery:** guarded workflow is merged; configure/verify its two GitHub secrets and run a production dry-run before the next schema change.
4. **eBay UK sold via Parse:** provider returns an empty list; investigate separately or use an alternative official/permitted source path.
5. **Cardmarket production ingestion:** re-probe/contract validation plus source-access/terms approval before persistence.
6. **Collectr production adapter:** diagnostic search is live, but the production detail/graded-price contract must be re-validated before enabling ingestion.
7. **TCGPlayer production ingestion:** supporting evidence only; validate the exact live detail/pricing endpoints before enabling persistence.
8. **Supabase leaked-password protection:** enable manually before launch.
9. **One Piece catalogue naming:** verify and normalize `Carrying On His Will` vs `Carrying on His Will` carefully.
10. **Packaged One Piece inventory:** confirm physical `seal_status` before provider matching/pricing.
11. **Operational inventory cleanup:** live snapshot on 26 Sep: 509 active items; 97 identities confirmed (96 Japanese, 1 English) and 412 remain unconfirmed. All 412 remaining unconfirmed records have unknown physical language; 410 are card-language blockers and the other 2 are non-card records, so no language is being guessed. **0 active items are missing a registered storage location**. 507/509 have Store Price; 506/509 have Market Value; acquisition costs remain complete. Current total Store Price value is £1,281.88 and Market Value is £979.57. The verification screen handles identity + language + optional location together so physical evidence is captured once; future unknown costs must still remain NULL.
12. **Shopify settlement enrichment:** Finance Reconciliation v1 + Owner Settlement Report v1 are deployed and #1002 fee/postage reconciliation is live-verified. Founder batch fee reconciliation is now deployed; next re-check the externally pending refund/final fee-complete state, then later add permitted shipping-provider cost ingestion.
13. **Refund settlement follow-up:** Shopify accepted the £5.48 refund for #1002, but the external refund transaction was still pending at the last check; verify completion before any further order action.
14. **Shopify shipping profile configuration:** registry and hard publication gate are live. RAW_CARD is configured at 40g for Royal Mail Tracked 48 using a 110x145x21mm package; Settings now exposes the package facts and audited £0.83 material total (£0.75 packaging + £0.08 top loader). GRADED_CARD is active at 120g for Royal Mail Tracked 48 using the founder-supplied 116x164x25mm, 33g box. Packaging is £1.20 per order; see `docs/GRADED_CARD_FULFILMENT_RESEARCH.md`. Because 25mm is the exact Large Letter ceiling, every sealed package must pass a thickness gauge.
15. **Shopify media readiness:** completeness/media registry remains fail-closed. Founder Media Intake v1 plus batch capture are healthy in production. Settings verifies Shopify `write_files`, creates short-lived staged upload targets, uploads image bytes directly to Shopify, requires explicit founder rights confirmation, and reuses the audited create → approve → sync workflow. Batch capture is sequential and duplicate live sides are database-enforced. Live registry currently has 0 media assets. The immediate operational opportunity is the 96 approved/core-ready cards (93 raw, 3 graded) that can move forward once their required media is captured and approved. Manual next check: confirm `write_files` is granted and complete one real founder image upload/batch.

## Stripe Connect payout foundation — 26 Sep 2026

- **Phase 1 deployed (PR #151 / `789896e`):** Stripe Connect Express account mapping, Stripe-hosted onboarding, transfers-capability readiness, signed/idempotent webhook intake, founder payout approval queue and immutable PREPARED payout execution records. Railway deployment `f406de9b-ba43-42da-8a40-320169ff9988` passed 594 tests and `/health/ready` returned 200.
- **Deterministic authority remains Drop Rate:** Shopify/eBay order allocation, refunds, fees, postage and owner balances are computed in PostgreSQL/FastAPI before Stripe can be involved.
- **Fail-closed approval:** incomplete KYC, payouts disabled, transfers inactive, unreconciled marketplace costs or owner balance shortfalls block approval.
- **No automatic money movement:** `TCG_STRIPE_PAYOUT_EXECUTION_ENABLED=false`. The backend contains no Stripe Transfer/Payout execution endpoint in Phase 1.
- **Live connected-account creation remains locked:** `TCG_STRIPE_CONNECT_LIVE_ENABLED=false`.
- **Production DB migrations applied:** `20260926180043_stripe_connect_payout_phase1`, `20260926180715_index_stripe_payout_connected_account`, `20260926181040_harden_stripe_payout_control`.
- **Provider credential blocker:** ChatGPT's Stripe plugin OAuth callback is currently broken/uninstalled, so no Stripe secret or webhook signing secret has been retrieved through the plugin. Production currently has 0 connected accounts, 0 Stripe payout executions and 0 Stripe webhook events. Do not paste Stripe secrets into chat.
- **Phase 2 gate:** confirm a permitted platform-balance funding path because Shopify customer receipts do not automatically fund the Stripe platform balance; then test Transfer → connected balance → bank payout → webhook → refund/reversal handling before enabling real money.

See `docs/STRIPE_CONNECT_PAYOUTS.md`.

## Consignor commission — 26 Sep 2026

- **10% default deployed (PR #153 / `1ccdb06`):** every future `CONSIGNOR` owner defaults to **1000 bps = 10.00%** commission; `FOUNDER` owners are enforced at **0%**.
- **Commission basis:** item net sale after item-level discounts; shipping revenue is excluded.
- **Historical integrity:** `commission_bps_snapshot` and `commission_minor` are frozen on each immutable order item, so later rate changes cannot rewrite old sales.
- **Ledger:** commission is an explicit append-only `COMMISSION` deduction, separate from marketplace/payment/postage/material costs. Partial/full item refunds append proportional `COMMISSION_REVERSAL` entries.
- **Payout effect:** owner available balance is computed from the complete ledger, so Stripe payout requests automatically use the post-commission amount.
- **Live transactional test passed:** £90.00 net sale → £9.00 commission → £81.00 owner ledger; 50% refund restored £4.50 commission → £40.50 ledger; full refund restored remaining £4.50 → £0.00. Transaction rolled back and left 0 test rows.
- **Regression/deploy:** GitHub and Railway both passed **604 tests**; Railway deployment `35215d97-67f5-4008-a76b-ebb5d128a403` succeeded and `/health/ready` returned 200.
- **Production state remains clean:** 0 real consignor commission ledger rows exist because there are currently 0 consignor owners. Existing founder commission remains 0%.

## Milestone 1 checklist

| Requirement | Status |
|---|---|
| Login/authentication | ✅ Complete |
| Physical inventory model | ✅ Complete |
| Ownership | ✅ Complete |
| Manual add inventory | ✅ Complete |
| Import inventory files | ✅ Complete |
| Manual import REVIEW resolution | ✅ Complete |
| Search/filter inventory | ✅ Complete |
| Acquisition cost model | ✅ Complete |
| Purchase provenance / cost lots | ✅ Complete |
| Card condition | ✅ Complete |
| Sealed/unsealed state | ✅ Complete |
| Grade/certificate | ✅ Complete |
| Language | ✅ Complete |
| Controlled physical locations | ✅ Complete |
| Stock audit/location counts | ✅ Complete |
| Approval/readiness workflow | ✅ Complete |
| Core regression / hardening pass | ✅ Complete |
| Production inventory data cleanup | 🚧 Operational task for next session |
| Leaked-password Auth setting | 🚧 Manual pre-launch action |

## Build roadmap

| Phase | Area | Status |
|---|---|---|
| 1 | Architecture / documentation | ✅ Core complete; documentation maintained continuously |
| 2 | Database / authentication | ✅ Core complete; one manual pre-launch Auth setting remains |
| 3 | Founder account / inventory / ownership | ✅ Technical foundation complete; audited identity + language + location review workflow deployed; operational data cleanup remains |
| 4 | Inventory dashboard functionality | ✅ Core complete; portfolio valuation, Top 5 value ranking, genuine weekly movers, Shopify readiness and dedicated Media & Condition workspace deployed |
| 4.5 | Founder dashboard UX/navigation | ✅ Structural seller portal live; visual polish can continue incrementally |
| 5 | Shopify integration | 🚧 Guarded product sync + verified webhooks + exact-item paid-sale + full refund/restock path production-verified; per-Inventory-ID front/back media, photo-backed NM/slab condition gates, deterministic product-completeness/media/shipping gates and Shopify readiness are deployed; bulk publishing remains locked; first live photo/condition batch + refund settlement follow-up remain |
| 6 | Orders / allocation / settlements | 🚧 Exact Shopify/eBay ownership attribution + deterministic settlement reporting are deployed; Stripe Connect sandbox transfer/reversal is verified; payout preferences + hourly scheduled REQUESTED-worker are live; real execution remains locked; multi-owner production verification remains |
| 6.5 | RBAC / seller & consignor portal | 🚧 Dedicated OWNER onboarding and restricted `/owner` inventory/sales/balance/settlement/payout/Stripe self-service are deployed. Next: genuine two-account cross-owner isolation proof, then controlled first seller/consignor onboarding |
| 7 | Market-data infrastructure | 🚧 Framework + multi-provider live access validated; production persistence intentionally gated |
| 8 | Pricing engine | 🚧 Deterministic engine live; trusted live evidence + scheduled execution remain |
| 9 | AI card identification | 🚧 Recognition v1.5 is deployed: mobile capture, multi-signal evidence, exact-print candidate logic and persistent visual-reference infrastructure are live. Remaining: finish exact reference corpus, harden exact-print confidence across promos/parallels/graded cards, complete Dragon Ball media coverage and expand evaluation dataset |
| 10 | Consignment | 🚧 Payout/commission foundation deployed: 10% consignor commission, Stripe Connect readiness and payout approval control exist; consignor onboarding/intake portal remains to build |
| 11 | AI product listings | ⬜ Not started |
| 12 | AI customer service | ⬜ Not started |
| 13 | SEO | ⬜ Not started |
| 14 | AI marketing | ⬜ Not started |
| 15 | n8n orchestration | ⬜ Advanced workflows not started |
| 16 | Analytics / optimisation | 🚧 Founder sales analytics, inventory value intelligence, Top 5 value cards and genuine 7-day mover framework are deployed. Broader marketplace/product/marketing optimisation remains |

## Immediate work order

### Next session — recognition/media closeout + multi-owner release gate
0. Resolve the **ROUND1 candidate-universe mismatch** exposed by the scanner audit: independently verified references distinguish ROUND1 Nico Robin (EB03-054) from ST29-009 Nico Robin (Promotion Pack EX Vol.4). Confirm the exact physical scan and ensure the correct ROUND1 printing can exist as a viable candidate even when OCR reads a conflicting number.
1. Resolve the **9 remaining One Piece image gaps** only with exact product/printing evidence; do not substitute base art for ROUND1, release-event, regional, anniversary or stamped versions.
2. Complete **Dragon Ball image coverage (33 unique cards across Masters + Fusion World)** through a permitted exact-print provider. TCGGraph adapter exists but production access is not configured yet.
3. Capture real **FRONT + BACK slab photos for all 8 graded items** and record certificate numbers where available. Physical slab media becomes the customer-facing primary image; canonical art remains recognition/reference evidence.
4. Build/refresh verified recognition fingerprints only from exact-print media that has passed the trust gate; do not train on merely visible reference art.
5. Run the genuine **second OWNER cross-isolation test** and then a controlled multi-owner/same-card sale attribution test.
6. Re-check Shopify #1002 final refund-fee settlement/idempotency before any cancellation action.

### Next session — inventory operations + controlled verification
1. ✅ Seel 021/094 selected, physically verified, priced and published through the guarded single-item path.
2. ✅ Shopify product sync verified: exact SKU/Inventory ID, ACTIVE product, publication and quantity handling.
3. ✅ Real paid Shopify order #1002 verified: exact physical Inventory ID attribution, SOLD state, £1.87 COGS snapshot, £0.49 sale revenue and £4.99 shipping revenue.
4. ✅ Shopify 2026-07 inventory API incompatibilities and paid-before-create webhook ordering defects found in live testing and hardened.
5. ✅ Full **£5.48 refund + restock** verified: −£0.49 item refund, −£4.99 shipping refund, order REFUNDED, physical item INSPECTION, Shopify link ARCHIVED and available stock 0.
6. **Next check (26 Sep):** verify the Shopify Payments refund transaction has finished settling before taking any further order action. Do not cancel #1002 merely because it is fully refunded; first confirm the final Shopify refund/order state.
7. ✅ **Finance Reconciliation v1 deployed:** typed Shopify transaction-fee ingestion, auditable reconciliation metadata, explicit £0 postage support, refund invalidation and Sales-tab controls are live.
8. ✅ **Finance Reconciliation v1 live-verified on #1002:** retry returned HTTP 200 for both actions; exactly one **−£0.36 PAYMENT_FEE** was recorded, postage was explicitly reconciled at **£0.00** using `TEST-NOT-SHIPPED`, and reconciliation audit INSERT/UPDATE events were written against the correct `order_item_id`. Fee reconciliation remains intentionally incomplete while Shopify's REFUND transaction is still PENDING.
9. ✅ **Owner Settlement Report v1 deployed:** Reports now show gross proceeds, deductions, signed adjustments, net owner proceeds, effective cost basis, owner profit, reconciliation state and pending/available funds without moving money.
10. Re-check the Shopify Payments refund settlement, then use the deployed batch fee-sync control to verify final fee completion, duplicate reconciliation idempotency and #1002's final settlement row.
11. ✅ **Shopify deterministic shipping-spec engine deployed:** owner-scoped RAW_CARD/GRADED_CARD registry, fail-closed completeness gate, Shopify weight write/read-back verification and Settings controls are live.
12. ✅ **RAW_CARD shipping configured:** 40g operating weight, 110x145x21mm package, 27g empty package and Royal Mail Tracked 48. Packaging cost is £0.75 per order. GRADED_CARD is configured and active at 120g using the 116x164x25mm, 33g box with £1.20 packaging allocated once per order.
13. ✅ **Founder Media Intake v1 deployed:** Shopify Settings now supports founder image selection, physical-vs-canonical scope, front/back side, alt text and explicit rights confirmation; the backend validates Shopify `write_files` and issues no-store staged upload targets so image bytes go directly to Shopify. GitHub CI and Railway pre-deploy both passed **436 tests** and the production readiness healthcheck returned 200. First authenticated scope + real-image upload remains manual verification.
14. ✅ **Physical identity + language review v1 deployed (PR #113 / `eb1381f`):** the founder verification queue exposes identity/language/location progress; confirmation can set English/Japanese and optional registered location in the same locked/versioned transaction; unknown language or a canonical-language mismatch blocks confirmation rather than guessing. Railway pre-deploy passed **439 tests** and `/health/ready` returned 200.
15. ✅ **Founder batch Shopify fee reconciliation deployed (PR #116 / `296be5f`):** pending fee records can be checked in bounded founder-only batches; Shopify network I/O runs outside database transactions, writes are revalidated/idempotent, and blocked/unsettled orders remain visible rather than being marked complete.
16. ✅ **eBay finish identity edge cases hardened (PR #117 / `72b789a`):** contradictory Foil/Non-Holo/Non-Foil wording now fails closed. The stale predecessor PR #56 was closed as superseded after its useful protections were verified on current `main`.
17. ✅ **Ready-to-Sell Inventory Ops v1 deployed (PR #119 / `995f466`):** Inventory rows now show visible core-readiness progress/blockers; Storage Locations has an owner-scoped, idempotent `Assign unlocated` action that never moves SOLD/RESERVED stock; future imports preserve explicit EN/JP evidence found at the end of either card titles or set names while keeping the original set identity stable and failing closed on conflicts. GitHub CI passed and Railway production pre-deploy passed **448 tests**; `/health/ready` returned 200.
18. ✅ **Dashboard Inventory Intelligence v1 deployed (`ee5c9f2`):** portfolio Market Value / Store Price totals, Top 5 highest-value products and real 7-day movers are live. Current live totals are £979.57 Market Value and £1,281.88 Store Price value; movers intentionally remain empty until a genuine seven-day baseline exists.
19. ✅ **Audited exact-import identity + batch founder media deployed (`b881f1e`, `942d6d9`):** exact original-import identity evidence is revalidated under lock and audited; media batches are rights-gated, sequential and duplicate-side protected. Live state is 97 confirmed identities, 412 still correctly fail-closed for unknown physical language, and 0 media assets.
20. ✅ **Shopify Readiness Funnel v1 deployed (PR #137 / `ff452d4`):** Dashboard distinguishes deterministic sellability blockers from media blockers without Shopify network calls or publication actions. The later Media & Condition release strengthened this gate with photo-backed condition verification.
21. ✅ **Mobile Founder Media Capture Station v1 deployed (PR #138 / `7244ecb`):** phone-friendly rear-camera capture, exact selected-card/side context, safe Previous/Next navigation and conditional queue advance are live. GitHub CI and Railway pre-deploy passed **517 tests**; `/health/ready` returned 200.
22. ✅ **Media & Condition v1 deployed (PR #139 / `6d2da16`):** every physical card requires exact FRONT + BACK evidence plus capture context; raw cards must be human-verified Near Mint and graded cards must have slab verification. Canonical media cannot bypass physical evidence. UI moved into its own streamlined workspace. **526 tests** passed in GitHub and Railway and production readiness returned 200.
23. **Next inventory-to-Shopify action:** photograph and condition-review a small first batch from the 96 cards that had already cleared identity/approval/cost/price/location gates. They are intentionally not sellability-ready until the new photo-backed condition gate is passed. Keep the remaining 412 unknown-language records in Verify.

### Next major engineering milestone — Shopify
Build the complete controlled sale loop:

`Approved inventory → Shopify product/SKU → Shopify checkout/order → webhook verification → physical Inventory ID → owner attribution → deterministic fees/proceeds → refund/cancellation handling → auditable settlement report`

Required controls:
- Shopify webhook signature verification
- webhook/event idempotency
- duplicate-order protection
- no ownership inference from Shopify alone
- backend/Supabase remains source of truth
- failure/exception queue for sync and order-allocation problems

### Market work after/alongside Shopify
- re-validate Cardmarket detail/pricing contract and source permission
- re-validate Collectr production adapter contract
- validate TCGPlayer detail/pricing support path
- keep eBay active as listing/liquidity context
- solve eBay sold independently rather than blocking the wider provider model
- only then enable persisted observations and automatic pricing runs source by source

## Major deferred decisions / features

- native iOS/Android Founder app is now a defined product phase: shared FastAPI/Supabase backend, camera-first recognition/intake, inventory, media/condition, Action Required, sales, consignments, push notifications and later scanner/printer Device Bridge; see `docs/STOREFRONT_AND_UX_BLUEPRINT.md`

- customer-facing Shopify theme/storefront is now a defined major build phase: custom Shopify Online Store 2.0 theme in GitHub, TCG-native search/filtering, collection/product-card system, raw/graded PDPs, grouped physical-copy presentation, database-driven merchandising, AI listing copy and later Scan to Find / Scan to Sell; see `docs/STOREFRONT_AND_UX_BLUEPRINT.md`

- multi-user owner onboarding remains gated until owner-safe portal APIs and two-owner isolation tests pass; Founder HQ is now explicitly PLATFORM_ADMIN-only and a separate `/owner` portal boundary is deployed
- consignor intake/onboarding portal remains to build on top of the deployed 10% commission + Stripe Connect payout foundation
- automated media intake/product-enrichment follows the controlled Shopify sale loop; AI identification comes after core commerce/pricing reliability
- the future iOS-assisted scan-to-list workflow is specified in `docs/MOBILE_CARD_CAPTURE_BLUEPRINT.md`: camera identification, explicit confirmation, manual card-number recovery, physical inventory creation and guarded Shopify publication through the backend
- AI marketing, SEO automation and advanced n8n orchestration come after inventory, Shopify, settlement and market pricing foundations
- value-weighted Purchase Lot allocation waits for reliable market reference values
- no automatic money movement until settlement reporting is thoroughly verified

## Stripe Connect + scheduled payout control plane — 26 Sep 2026

- ✅ Stripe Connect test recipient onboarding is live in Founder HQ **Balance**; the verified test account reports READY, payouts enabled and transfers ACTIVE.
- ✅ Consignor commission baseline is deterministic at **10% (1000 bps)**. Live database finance probes verify £100 gross → £10 commission → £90 owner proceeds.
- ✅ Stripe sandbox money movement was exercised end-to-end: £100 test funding → £90 Connect transfer → idempotent transfer replay → £90 reversal → idempotent reversal replay → funding refund. Production payout execution remains locked.
- ✅ Owner payout preferences are live: Manual, Daily, Weekly, Every 2 weeks and Monthly, with Europe/London schedule calculation, version protection, RLS and audit logging.
- ✅ Scheduled payout request worker deployed (PR #168) with database-level cycle idempotency and atomic re-checks for owner activity, Stripe readiness, current preference version, available ledger funds and existing payout reservations.
- ✅ Dedicated Railway cron service `drop-rate-payout-scheduler` deployed using `Dockerfile.scheduler` (PRs #169–#170), scheduled **hourly** with no Stripe secret. The worker only creates REQUESTED payout rows and cannot move money.
- ✅ Payout-preference API auth bug fixed in PR #171: route now uses the actual `AuthenticatedUser.user_id` field. Latest production deployment passed **640 tests** and `/health/ready` returned 200.
- ✅ A real sandbox preference is now saved as **DAILY**. The scheduler sees **1 eligible schedule candidate**; no scheduled payout request exists yet because there is currently no due eligible balance.
- 🔒 Automatic Stripe execution remains disabled until scheduled-request behavior is observed against real eligible balances and the approval/execution policy is intentionally promoted.
- 🧪 **Stripe sandbox → live cutover TODO:** current schema permits only one connected Stripe account per owner. Before real onboarding, migrate the mapping so one TEST and one LIVE Connect account can coexist (unique by owner + livemode), preserve the sandbox account/history, add an admin-only disconnect/reset control, then create a separate live Connect account using real KYC/bank details. Do not overwrite the sandbox account or reuse test data for live payouts.

## RBAC access-control foundation — 26 Sep 2026

- ✅ PR #172 deployed: application permission is now separate from inventory ownership.
- ✅ Membership roles are now `PLATFORM_ADMIN` and `OWNER`; the least-privilege default is `OWNER`.
- ✅ Existing founder membership migrated from legacy `FOUNDER` permission to `PLATFORM_ADMIN` with an audit event.
- ✅ Current production state has **1 active PLATFORM_ADMIN membership and 0 OWNER memberships**.
- ✅ PLATFORM_ADMIN can resolve all active owners through the role-aware owner RLS boundary; OWNER remains limited to its explicitly linked owner.
- ✅ Founder invite creation is PLATFORM_ADMIN-only and redeemed founder invitations receive PLATFORM_ADMIN explicitly.
- ✅ `GET /api/v1/access/me` exposes the authenticated access context and whether Founder HQ is allowed.
- ✅ Reusable FastAPI `require_platform_admin()` guard is deployed for privileged-route hardening.
- ✅ Architecture documented in `docs/ACCESS_CONTROL_MODEL.md`: Founder HQ is internal/admin-only; future sellers/consignors use a separate restricted owner portal.
- ✅ Production deployment `1a386c6b-74f5-4ca5-b3f4-fffcc6f3baf1` passed **646 tests** and `/health/ready` returned 200.
- 🔒 No OWNER account should be invited until the privileged-route audit is complete and the separate owner portal has owner-safe APIs.

## Security / authentication hardening — 26 Sep 2026

- ✅ Legacy migration metadata is now infrastructure-only (PRs #173–#174): `tcg.schema_migrations` has forced RLS, application-role privileges revoked and an explicit deny-all `tcg_api` policy. Only the postgres migration authority retains access.
- ✅ Supabase password requirements are configured to **12+ characters** with lowercase, uppercase, number and symbol requirements.
- ⚠️ Supabase **Leaked Password Protection** cannot be enabled on the current plan. It is recorded as a Pro-plan pre-public-launch hardening requirement; do not upgrade solely for this toggle unless/when the wider plan benefits justify it.
- 🔒 Before external seller/consignor launch, require MFA for `PLATFORM_ADMIN` accounts and retain email verification, rate limits and session controls.
- ✅ Google + Apple OAuth frontend support deployed in PR #176. Buttons are shown only when Supabase reports the provider enabled; OAuth authentication never grants Founder HQ permission by itself.
- ⏳ Google provider still requires its real OAuth client ID/secret + production origin/callback configuration in Google/Supabase.
- ⏳ Apple provider still requires Apple Developer Services ID/key/client-secret configuration. Web OAuth secret rotation must be operationally tracked.
- ✅ Founder HQ now checks `GET /api/v1/access/me` and opens only when `founder_hq_allowed=true`.
- ✅ PR #175 made the internal control-plane routers PLATFORM_ADMIN-only.
- ✅ PR #177 replaced remaining legacy `FOUNDER` permission checks with the central PLATFORM_ADMIN guard.
- ✅ PR #178 completed the mixed-route audit: owner-safe reads/self-service remain scoped; inventory mutations, purchase lots, finance reconciliation/manual sales, refund creation, Shopify controls and eBay seller/OAuth controls are admin-only; signed external provider callbacks/webhooks remain outside user-session RBAC.
- ✅ PR #179 deployed a separate `/owner` portal shell. PLATFORM_ADMIN redirects to Founder HQ; only `OWNER` + `OWNER_PORTAL` may enter; unlinked users fail closed. It intentionally exposes no inventory/finance business modules yet.
- ✅ Latest production deployment `49eb4fbb-1154-4512-a01d-8dee2d16430d` passed **667 tests** and `/health/ready` returned 200.
- ✅ Current production memberships remain **1 PLATFORM_ADMIN / 0 OWNER**, so no external seller has been exposed to unfinished portal functionality.
- ➡️ Next security slice: dedicated owner-safe API contracts + two-owner cross-isolation tests, then OWNER invitation/onboarding, then owner portal inventory/sales/balance/payout modules.

## Seller / consignor portal + scheduler verification — 26 Sep 2026

- ✅ PR #180 deployed dedicated read-only owner APIs: `/api/v1/owner/overview` and `/api/v1/owner/inventory`, with explicit safe field allowlists, owner_id defence-in-depth and fail-closed ambiguous membership handling.
- ✅ PR #181 deployed the read-only `/owner` inventory dashboard with owner-scoped inventory counts, market/store value, card search, status filters and pagination. Acquisition cost, internal notes, storage locations, purchase-lot data and provider IDs remain excluded.
- ✅ PR #182 deployed a separate restricted OWNER invitation flow:
  - PLATFORM_ADMIN-only create/revoke
  - email-locked invites
  - verified Supabase JWT email used at redemption
  - creates physical owner type `CONSIGNOR`
  - creates access role `OWNER`
  - default commission 1000 bps / 10%
  - hashed invite tokens + audit logging
  - email/password + Google/Apple-compatible `/owner/join` onboarding
- ✅ Founder invite redemption is now also bound to the verified JWT email instead of trusting a browser-supplied email.
- ✅ PR #183 deployed dedicated owner-safe finance reads for summary, sales, settlements and payout history. Seller proceeds come from the append-only ledger; acquisition cost/company profit/customer-address/provider-secret fields are excluded.
- ✅ PR #185 deployed restricted owner Sales, Balance & payouts and Settlements dashboard views, including transparent commission/deductions, reconciliation state, payout history and owner-controlled payout cadence.
- ✅ PR #186 deployed OWNER Stripe Connect self-service for account status/create/onboarding/sync only. Payout queue approval/rejection/execution remain admin-only. OWNER Stripe return/refresh URLs are forced to trusted `/owner` origin.
- ✅ PR #184 added durable `tcg.payout_scheduler_runs` operational logging so every scheduler run has an auditable SUCCESS/FAILED record even when Railway omits short-lived cron stderr.
- ✅ Scheduler networking now has outbound IPv6 enabled.
- ✅ PR #187 added scheduler image compile validation and triggered a clean scheduler-specific Railway build.
- ✅ A real scheduled verification run completed at **2026-09-26 23:20:31 UTC** with **SUCCESS**: checked=1, created=0, duplicate=0, no_balance=1, stripe_not_ready=0, errors=0. This is the expected outcome with £0 available balance.
- ✅ Scheduler restored to **hourly** (`0 * * * *`) after the 5-minute verification; active deployment `57b468c0-e58f-4ed2-b138-90c3c52336f0` is SUCCESS.
- ✅ Current GitHub main baseline: **707 tests passed**.
- 🔒 Production still has no external OWNER membership yet; first external onboarding remains gated on the real two-account cross-owner isolation proof.
- ➡️ Next release gate: create one controlled restricted OWNER test account, assign isolated test inventory/financial fixtures, prove Owner A cannot read/write Owner B across inventory, orders, ledger, payouts, Stripe and Founder HQ routes, then remove or retain the account as an approved sandbox owner.

## Completion rule

- **Coding only:** In Progress.
- **PR open / CI green:** In Progress.
- **Merged but not deployed:** In Progress where deployment is applicable.
- **Production deployment + health verification successful:** Completed.
- **External provider limitation:** recorded explicitly; does not silently count as platform failure.

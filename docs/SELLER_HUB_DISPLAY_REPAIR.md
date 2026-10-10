# Seller Hub display repair — 8 October 2026

## Findings and scope

The browser image policy omitted `www.dbs-cardgame.com` and `narutocardgame.gg`, despite both supplying existing catalogue artwork. It also omitted `cardtrader.com` and its `www` redirect used by approved inventory media. Read-only checks returned HTTP 200 image responses from all three providers. The narrow image-host additions leave script, connection, framing and media approval rules intact.

Catalogue results now return a same-product approved canonical image as a fallback when provider artwork fails. Empty provider URLs also fall back correctly. The UI tries each distinct allowed URL once, then shows the existing image placeholder. No unverified artwork is approved or promoted to a storefront.

Market data is a separate coverage limitation. Existing canonical products return saved reference prices through the current query, while unmapped reference printings have no verified price link. The inspected unvalued seller item has no saved market observations or media; its absence is real. Names/card numbers alone cannot safely link parallel artwork or valuations. This repair does not invent prices, reuse a box price for a pack, merge inventory, or mark those mappings verified.

The owner overview now reports valued and unvalued active-item counts. A wholly unvalued collection says “Value pending” instead of £0. Partial totals explicitly report missing coverage; an empty collection still totals £0. Inventory and product details explain pending values. Stored prices, pricing rules, ownership, RLS, history and publication gates are unchanged.

## Verification and rollback

- Targeted Python checks passed (70 cases); the full browser interaction suite passed, including distinct image fallback, unsafe URL rejection, pending versus priced details and empty/partial/unvalued overview cases.
- Read-only production query verification returned existing market values and approved images without modifying data. Three source image downloads returned HTTP 200 and image content types.
- CI, release and authenticated device validation remain separate gates; this document does not claim them before completion.
- Revert this PR to restore the previous response/UI/header behaviour. No migration or data rollback is needed.


## 10 October 2026 — Single title per Seller Hub tab

**Problem:** The shared `owner-page-header` showed `Inventory` and a lengthy explanation before the inventory panel independently rendered `Inventory` and a second explanation. This wasted vertical space, especially on phone screens. The same duplicate-title pattern appeared on Sales, Settlements and Scan.

**UI resolution:** Every tab has one authoritative page-level heading. `activateOwnerView` hides the shared top header on content-led Search, Inventory, Scan, Sales, Channels and Settlements tabs, leaving each tab's native title/controls. Inventory keeps one concise instruction and product/copy count in the same compact panel header; its redundant collection kicker is removed. Channels receives one compact section-leading `Channels` heading because its channel cards otherwise lack a title. Home, Payouts, Profile, Settings and More retain their shared heading, as they have no duplicate top-level title. Distinct subordinate sections (e.g. Payout History or Synced Inventory within Channels) retain descriptive headers.

**Scope and safety:** HTML/CSS and navigation only. No change to product identity, inventory ownership, Shopify pooling, valuations, pricing, settlement, RLS, authentication, login, or channel sync. The existing nav selection, deep-links and profile/settings paths continue functioning.

**Tests:** JSDOM exercises all 11 tabs, verifying exactly one visible top-level title and preserved original active panel. Chromium at 430px and desktop verifies the duplicate global header is actually invisible (including CSS author overrides), inventory title appears once, search controls remain visible, no horizontal overflow or excessive top padding. Versioned CSS and JS URLs force client refresh together.

**Rollback:** Revert the CSS/HTML/JS commit only if a content-led tab loses its title, while leaving DB, Shopify and the independent OP17 inventory migration untouched.


## 10 October 2026 — Collectr-style instant camera on Scan

**What is built:** When a signed-in Seller Hub user **clicks** the left-hand **Scan** tab or a "Scan" quick action, `activateOwnerView` opens the existing Drop Rate full-screen camera **in that same click event**, requesting the rear camera immediately. There is no intermediate "Open live camera" button to press. Auto-scan, RAW/GRADED/SEALED modes, QR/torch/switch-camera controls, manual capture, review, approvals and reference identification all remain handled by the original `DropRateScanner.Scanner` (not duplicated in the navigation layer).

**Why:** The older flow rendered a static Scan workspace first and waited for the network recognition readiness check. That broke the quick, camera-first collecting experience. Camera permission must be requested from a user action rather than waiting on API fetches.

**Connections:** `owner-portal.js` now passes an explicit user-click flag from Scan navigation/quick actions into `window.ownerRecognitionLaunchCamera()` in `owner-recognition.js`. The function invokes `ownerScanStartCamera` synchronously (no awaited API calls), and shared `scanner-flow.js` requests `getUserMedia`, starts the already-built scan overlay and preserves queued copies when reopening. `ownerRecognitionEnter` continues checking recognition service status independently; low-confidence results still need human confirmation. No changes to Shopify, database, market pricing, product ownership or automatic publishing.

**Potential failures and behaviour:** On first use, the browser's own camera permission dialog may appear and cannot be bypassed. Denied/unavailable hardware leaves a labelled photo-picker in the scanner without repeated automatic prompts. An already open scanner is reused rather than opening a second stream. Changing tabs, logout, browser visibility loss or navigating away stops the camera; late permission grants are stopped instead of reopening a hidden scanner. Loading a deep-linked `#scan` page never starts recording without a direct Scan click. Clicking Scan again starts the rear camera; unsaved items remain available under Next/Review. The existing camera button inside Scan remains as a fallback on devices without modal camera support.

**Tests:** New JSDOM integration tests simulate the exact Seller Hub click, verify that `getUserMedia` happens before recognition API readiness completes, rear-facing preference, zero-camera deep-link restoration, duplicate-click suppression, alternate Scan quick action, denial with gallery fallback, switching camera, exit cleanup and late async grants. Existing `scanner-flow.cjs` adds regression for queued unsaved scan preservation on direct launch. CI runs JS syntax, full backend, dashboard UI, PostgreSQL and browser fixtures. Production health and signed-in iPhone/desktop visual acceptance are separate release gates.

**Rollback:** Revert only the navigation/recognition/shared-scanner UI changes if the permission gesture is blocked in a browser. The underlying manual camera launch remains available and no physical inventory or Shopify data changes.

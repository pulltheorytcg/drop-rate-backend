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

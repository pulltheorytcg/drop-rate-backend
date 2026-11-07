# Drop Rate Auction Lens — UK buyer foundation (7 November 2026)

**State: IN REVIEW — code foundation only; NOT LIVE, no auction/video capture, no provider connection.**

## What we are building and why

A buyer-initiated companion that can identify a precise collectible from an approved auction stream, attach an eligible and current UK Market Value, and show the **all-in GBP bid** compared against that value. The buyer keeps full control of bidding. This addresses the UK collector's need to factor in delivery, buyer charges and exact-print value while watching live Whatnot or eBay auctions.

The existing [live auction proposal](LIVE_AUCTION_SCANNER_PROPOSAL.md) and reference image IMG_5034.jpeg are the product basis. The illustration does **not** prove automatic capture or an iPhone cross-app overlay. No original test video was located in the connected project files/Drop Rate Drive during this work; video recognition has not been benchmarked.

## Architecture and what this first change does

Future permitted flow:
user-selected source + consent -> locally cropped frame -> stable scene / exact reference lock -> bounded existing recognition logic -> source-rights-approved, unexpired UK Market Value from FastAPI/PostgreSQL -> deterministic comparison -> small buyer panel.

- **Implemented in this PR:** \`app.auction_lens_uk.compare_uk_auction\`, a pure deterministic GBP comparison. Inputs are an active auction lot, its current bid observation, all named incremental charges, confirmed recognition key / scene generation, supported UK Market Value with proof of currency, region, eligibility, evidence date, expiry, and display permission; explicit around-market tolerance and quote-age limit. Outputs are under/around/over or a fail-closed abstention with no exposed comparison value.
- **Not implemented:** an API endpoint, new table, streaming video, extension, OCR, scraping, Whatnot integration, eBay API request, notifications, bidding, pricing-source calls, checkout or any production flag. No change to Shopify, owners, inventory, R2, n8n or settlements.
- A reference match must be exact for language, printing/finish, grade and product type when material. The session layer must separately verify each generation; the calculation module deliberately cannot establish those facts itself.
- Known costs use integer pence, not floating-point estimates. Unknown shipping, buyer fees, taxes or other charges must be represented by \`None\` and withhold a bargain badge. Zero must be explicitly verified, not defaulted.
- All displayed comparisons require a genuine \`MARKET_VALUE\` with active \`AVAILABLE\` status, \`GBP\`, UK market region, positive value, source, verified eligibility, explicit display rights and unexpired evidence. Expired prices, asking prices, guides and unpriced reference data are not treated as current market value.
- The +/− threshold for “around market” is deliberately an explicit caller-provided basis-point policy; it is **not** an agreed trading recommendation.

### UK-specific display contract

Display in **GBP (£)**, using pence internally; show auction end / evidence dates in **Europe/London** with DST handling while retaining offset-aware UTC timestamps internally. Calculate \`all_in = bid + incremental UK delivery + verified buyer fees + applicable VAT/import costs + additional direct charges\`. Cross-border shipments must not be assumed domestic or duty-free. Reuse existing cached reference valuations; **never hit an external price API per video frame**.

The eBay Browse API can discover live \`AUCTION\` listings and return bid context when access/terms permit. Its active prices are not sold-market evidence. Whatnot capture/monitoring and any live feed require platform permission covering the actual use; browser or device capture consent alone does not confer that right.

Sources:
- https://developer.ebay.com/develop/api/buy
- https://developer.ebay.com/api-docs/buy/api-offer.html
- https://developer.chrome.com/docs/extensions/reference/api/tabCapture
- https://legal.whatnot.com/
- https://www.ebay.co.uk/help/policies/member-behaviour-policies/user-agreement?id=4259

## Dependencies and order

1. **Current foundation (this PR):** logic and offline tests only. Do not enable in UI before eligible current market evidence exists. The 7 November BUILD_STATUS records all 59,693 legacy market price rows expired by 4 November; revalidate current eligible price coverage independently before live exposure. Do not silently refresh, extend expiry or backfill a fake minimum.
2. **Approved-footage benchmark:** obtain owner-controlled/otherwise rights-cleared videos; sample blurred, moving, mirrored, misprint, slab, sealed, manga and multi-item scenes. Start with verified English raw Pokémon exact prints, not all catalogue types simultaneously. Record false matches, abstentions, scene resets, latency and provider calls. Never infer accuracy from mocked tests.
3. **Permitted capture desktop pilot:** Chrome user-activated tab capture or owned-video upload, local crop, no audio, visible stop/pause, no persistent frame storage by default, small non-obstructing panel. Connect through authenticated FastAPI with bounded calls and generation checks. Streaming a third-party auction is blocked until source permissions are documented.
4. **UK eBay auction-discovery adapter:** only using official/permitted access, EBAY_GB context, current bid / itemEndDate / explicit shipping; show pricing age and unknown fees. No automatic bidding and no sold-price inference. This is a separate adapter from video capture.
5. **Phone delivery:** screenshot/share or second-screen on iPhone first; separately assess Android MediaProjection + overlay and iOS feasibility. No promise of an always-on Whatnot iPhone overlay.

## Failure points and tests

Current \`tests/test_auction_lens_uk.py\` exercises all-in pence math, under/around/over, missing costs, US/non-GBP prices, expired/stale evidence, unlicensed displays, unconfirmed print, scene-generation switches, ended auctions, stale bids and invalid types. Run \`PYTHONPATH=backend python -m pytest -q tests/test_auction_lens_uk.py\` as well as normal repo CI, and record results before merge.

Future acceptance also needs genuine video tests (not currently established), stop/revocation, security and privacy review, current condition/grade/finish matching, no value carried into a new lot, no writes to owner/stock, no automatic bids, and measured median/p95 result time against the earlier proposal's **under 2s / under 4s targets**. Those targets remain unverified.

**Release/rollback:** keep this draft and unmerged until tests/review. The module is not wired into routes, so rollback is removing this branch/PR; do not deploy, activate n8n or update provider credentials as part of this work.


## 7 November — Shazam-style live loop and iOS 27 experimental capture source

- Added \`mobile/src/lib/auctionLensStream.ts\`: on-device scene scheduler, ~4 crop samples/second, three stable hashes to trigger at most one bounded inference per unchanged lot, immediate prior-value invalidation on scene/capture change, delayed-result generation checks, explicit new-lot handling, stop/pause/revocation, and local current-value expiry display guard. Recognition and display permission remain backend responsibilities; **there is no implemented frame resolver/API bridge yet.**
- Added 10 focused Vitest tests and an independent TypeScript/CI workflow. [Run 42392833981](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/42392833981) passed. On that same code revision, the full [Mobile app checks run 42392833974](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/42392833974) failed three **existing** \`tests/hub.test.ts\` role/entry tests; the PR did not modify Hub or that test. Baseline attribution and full-suite release gate remain open.
- Added unlinked \`mobile/experimental/auction-lens-ios27/DropRateAuctionScreenProbe.swift\`: system picker, user-confirmed region, audio disabled, on-device crop, hash and JPEG callback, no network/file writes. **Not compiled, not autolinked, not a live feature.** Xcode 27 SDK, physical iPhone, native authentication and secure background-processing are future gates. Apple's [current iOS sample](https://developer.apple.com/documentation/screencapturekit/capturing-screen-content-on-ios) requires iOS 27+ and remains marked preliminary.
- [PalletTrade's UK App Store release history](https://apps.apple.com/gb/app/pallettrade/id6760375576) describes a new PiP result mode; this is competitor UX evidence, not proof of its underlying recording or model architecture. Do not copy PiP via a fake video call.
- **Provider gate:** The [Whatnot UK Terms effective 1 June 2026](https://legal.whatnot.com/) prohibit automated use and certain monitoring/copying/competitive applications without the necessary permission (section 19). [eBay UK User Agreement](https://www.ebay.co.uk/help/policies/member-behaviour-policies/user-agreement?id=4259) similarly restricts unpermitted automated extraction. Do not point capture at those production services without a documented acceptable route. Validate first with company-owned or otherwise authorised video, not competitor stream scraping.
- Latency claims remain **unverified**. Three 250ms-interval samples can initiate one lookup approximately 0.5s after a clear first frame, but provider/network latency and real-world accuracy are unknown. Target the prior <2s median/<4s p95 as provisional acceptance hypotheses; seek ~1s when proven, not promised.

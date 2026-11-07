# Drop Rate Auction Lens — UK buyer foundation (7 November 2026)

**Latest state: IN REVIEW — a disabled, authenticated local-video pilot API and test screen now exist. There is NO live auction feed, production deployment, signed iPhone app, automatic OCR or system-wide overlay.**

## What we are building and why

A buyer-initiated companion that can identify a precise collectible from an approved auction stream, attach an eligible and current UK Market Value, and show the **all-in GBP bid** compared against that value. The buyer keeps full control of bidding. This addresses the UK collector's need to factor in delivery, buyer charges and exact-print value while watching live Whatnot or eBay auctions.

The existing [live auction proposal](LIVE_AUCTION_SCANNER_PROPOSAL.md) and reference image IMG_5034.jpeg are the product basis. The illustration does **not** prove automatic capture or an iPhone cross-app overlay. No original test video was located in the connected project files/Drop Rate Drive during this work; video recognition has not been benchmarked.

## Architecture and what this first change does

Future permitted flow:
user-selected source + consent -> locally cropped frame -> stable scene / exact reference lock -> bounded existing recognition logic -> source-rights-approved, unexpired UK Market Value from FastAPI/PostgreSQL -> deterministic comparison -> small buyer panel.

- **Implemented in this PR:** \`app.auction_lens_uk.compare_uk_auction\`, a pure deterministic GBP comparison. Inputs are an active auction lot, its current bid observation, all named incremental charges, confirmed recognition key / scene generation, supported UK Market Value with proof of currency, region, eligibility, evidence date, expiry, and display permission; explicit around-market tolerance and quote-age limit. Outputs are under/around/over or a fail-closed abstention with no exposed comparison value.
- **Later pilot addition (see latest section):** an authenticated read-only API and browser-based owned-video lab have been added, disabled by default. Still not implemented: live third-party stream capture, native-to-Expo bridge, automatic OCR, PiP, bidding, provider requests or any production activation. No change to Shopify, owners, inventory, R2, n8n or settlements.
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

**Release/rollback:** keep this draft and unmerged until tests/review. The pilot route is registered but gated by an explicit default-off environment flag. Rollback is a code revert; do not deploy, activate n8n, change source permissions or update provider credentials as part of this work.


## 7 November — Shazam-style live loop and iOS 27 experimental capture source

- Added \`mobile/src/lib/auctionLensStream.ts\`: on-device scene scheduler, ~4 crop samples/second, three stable hashes to trigger at most one bounded inference per unchanged lot, immediate prior-value invalidation on scene/capture change, delayed-result generation checks, explicit new-lot handling, stop/pause/revocation, and local current-value expiry display guard. Recognition and display permission remain backend responsibilities; **this earlier status is superseded below: the client-to-FastAPI pilot resolver now exists, but native background capture remains unconnected.**
- Added 10 focused Vitest tests and an independent TypeScript/CI workflow. [Run 42392833981](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/42392833981) passed. On that same code revision, the full [Mobile app checks run 42392833974](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/42392833974) failed three **existing** \`tests/hub.test.ts\` role/entry tests; the PR did not modify Hub or that test. Baseline attribution and full-suite release gate remain open.
- Added unlinked \`mobile/experimental/auction-lens-ios27/DropRateAuctionScreenProbe.swift\`: system picker, user-confirmed region, audio disabled, on-device crop, hash and JPEG callback, no network/file writes. **Not compiled, not autolinked, not a live feature.** Xcode 27 SDK, physical iPhone, native authentication and secure background-processing are future gates. Apple's [current iOS sample](https://developer.apple.com/documentation/screencapturekit/capturing-screen-content-on-ios) requires iOS 27+ and remains marked preliminary.
- [PalletTrade's UK App Store release history](https://apps.apple.com/gb/app/pallettrade/id6760375576) describes a new PiP result mode; this is competitor UX evidence, not proof of its underlying recording or model architecture. Do not copy PiP via a fake video call.
- **Provider gate:** The [Whatnot UK Terms effective 1 June 2026](https://legal.whatnot.com/) prohibit automated use and certain monitoring/copying/competitive applications without the necessary permission (section 19). [eBay UK User Agreement](https://www.ebay.co.uk/help/policies/member-behaviour-policies/user-agreement?id=4259) similarly restricts unpermitted automated extraction. Do not point capture at those production services without a documented acceptable route. Validate first with company-owned or otherwise authorised video, not competitor stream scraping.
- Latency claims remain **unverified**. Three 250ms-interval samples can initiate one lookup approximately 0.5s after a clear first frame, but provider/network latency and real-world accuracy are unknown. Target the prior <2s median/<4s p95 as provisional acceptance hypotheses; seek ~1s when proven, not promised.


## 7 November — current owned-video pilot, server/API gates and verification

**What is now built (in PR #983 only, not deployed):**

1. \`backend/app/auction_lens_api.py\`: a disabled-by-default, authenticated FastAPI \`POST /api/v1/auction-lens/pilot/resolve\`. The Supabase JWT is verified by the existing \`require_user\` dependency; \`user_connection(readonly_snapshot=True)\` establishes PostgreSQL owner context and \`current_owner\` requires one active membership. The route accepts a **single cropped image** and the observed card metadata from company-owned or otherwise expressly authorised video, never a live Whatnot/eBay URL. It returns a bounded identity decision with the same scene generation or a fail-closed \`CHECK_VERSION\`; no recognition receipts, inventory, pricing, media or ledger writes.
2. \`backend/app/auction_lens_pilot.py\`: exact-print logic restricted to **English, raw Pokémon** in this first cohort. An accepted identity requires one approved and rights-verified matching canonical media asset, a fingerprint similarity ≥0.94, an independent visual margin ≥0.07, and corroborating **name, set, collector number, language and finish**. Lookalikes, raw/slab confusion, reverse-holo ambiguity and source rights loss abstain. These are conservative initial parameters, **not empirically calibrated confidence scores**.
3. \`mobile/src/lib/auctionLensResolver.ts\`: one authenticated, abortable request per stable scene, token supplied through an explicit trusted callback, never read from native screen capture. It won't send frames when unsigned-in, stopped or blurred, nor display USD, stale generation or unverified values.
4. \`backend/app/static/auction-lens-lab.html\`, \`.css\`, \`.js\`: original branded browser test interface at \`/auction-lens-lab\`. It loads a local video via a browser-only Blob URL, lets the user confirm the product crop and visible metadata, sends only a JPEG crop, shows exact-match/abstention and reports measured request latency. No video/audio file is uploaded or retained. Its use is limited by the same default-off pilot feature flag, and only this route gets a \`media-src 'self' blob:\` CSP exception.
5. \`mobile/experimental/auction-lens-ios27/DropRateAuctionScreenProbe.swift\`: unlinked, **uncompiled** native feasibility source from the earlier milestone. It has NOT been connected to the iPhone app or backend session, and iOS PiP is not implemented.

**Two independent flags, both OFF unless separately authorised by the operator:**
- \`TCG_AUCTION_LENS_AUTHORISED_PILOT_ENABLED=true\`: permits local, explicitly authorised test-video crop recognition on a controlled deployment. Never set in the public production environment solely to test third-party streams.
- \`TCG_AUCTION_LENS_UK_SOLD_DISPLAY_RIGHTS_APPROVED=true\`: **separate and stronger rights gate**. Must remain OFF until evidence/licences and physical valuation eligibility are verified. Even when ON, the buyer must explicitly confirm **Near Mint**, and the backend's existing \`REFERENCE_VALUES_SQL\` / \`resolve_reference_value\` must return current, exact-copy \`CATALOGUE_EBAY_V4\` eligible UK sold Market Value. No guide, RRP or active asking-price substitution; missing or expired values remain hidden.

**Pilot workflow once a controlled environment is actually available:**
1. Sign into the **same** trusted Drop Rate browser tab; enable the pilot flag only in an explicitly authorised test environment after source review. Open \`/auction-lens-lab\`.
2. Upload a **locally recorded/rights-cleared video file**, not a URL or screen capture of a restricted service. Adjust crop until only the visible product remains; the crop preview shows what would be transmitted.
3. Enter the visible English Pokémon name/set/number/finish. This is a **manual corroboration step for the first benchmark**, not Shazam-style automatic OCR. Leave condition unconfirmed unless visually and physically substantiated; unconfirmed or unlicensed Market Value is absent.
4. Tick footage permission and Start; try New lot, seek, pause, blur, identical-print repeated lots and Stop. Record identity, errors, abstentions and wall-clock request timings in the acceptance log, without attaching unredacted personal captures.
5. Do **not** call it “live” until a verified native Expo bridge, physical iPhone background capture, source approval, secure native token transport, price rights and measured end-to-end recognition have all passed.

**Test evidence:**
- [Auction Lens focused mobile CI 42394867726](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/42394867726): TypeScript typecheck, video-lab syntax and 15 focused client tests passed.
- [Full mobile run 42394867734](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/42394867734): **all 51 tests passed**, including seven revised current role-boundary tests. Its overall job **failed** at \`expo install --check\` because eight pre-existing Expo packages do not match the SDK's now-recommended patch versions. Do not mask the check or silently change 8 dependencies and the lockfile inside an auction feature patch.
- Backend: tests in \`tests/test_auction_lens_api.py\`, \`tests/test_auction_lens_pilot.py\`, \`tests/test_auction_lens_uk.py\`, \`tests/test_auction_lens_lab.py\`; normal full-CI must pass on the **latest commit** before any merge. The first full run caught five new/baseline-fixture issues; their repairs must be read back in a subsequent CI receipt. Prior green tests on older commits are not release evidence.

**Measured performance criteria (targets, not current results):** Aim for median <2s/p95 <4s from a stable clear crop to final result; strive toward ~1s once actual devices and corpus support it. Benchmark 30-minute thermal/battery behaviour on a physical supported iPhone; publish exact-print precision **with** abstention/coverage and latency distributions, testing mirrored/slab/finish/lookalike/no-match footage before widening the pilot. Three 250ms crop samples mean approximately 0.5s startup from first clear frame **before** processing and network time; the 15 mocked client tests are not proof of one-second live recognition.

**Future architecture/release dependencies:** iOS 27 final SDK and Apple Developer signed native build; explicit capture selection, background lifecycle and credential-safe transport; native Vision OCR/local visual index; no fabricated iPhone arbitrary cross-app overlay or misuse of PiP; Whatnot/eBay commercial monitoring permission; an approved data rights record for UK sold-price display; updated tests and staged release/rollback. Manual test videos can be selected locally but have not been retrieved or evaluated in this work session.


### Final pilot safety refinements (7 November, still unmerged)

- A stable scene request waits at most **100 ms** for an available shared lookup slot, then holds the read-only index/database path to a **2.5-second** deadline. On a slow/hung query the endpoint returns \`CHECK_VERSION\`, with no copied old price; a follow-up request can acquire a released slot. These are bounded failure limits, not a claim that normal recognition finishes in under 2.5 seconds or under one second.
- An eligible UK sold-price response includes \`evidenceAtMs\`, \`basis\` and \`expiresAtMs\`. The expiration is the **earlier** of the latest observation check + 7 days or oldest accepted sale + 90 days, matching the existing deterministic valuation freshness criteria. The lab renders the evidence date in Europe/London and never converts a guide to Market Value. Tests cover the earlier expiry.
- The local-video source is explicitly chosen as \`OWN_VIDEO\` or \`EXPLICITLY_AUTHORISED_VIDEO\`, with separate consent confirmation. Source selection is a user declaration, **not proof** of Whatnot/eBay permission. No live stream host or tab URL is accepted.
- Full backend [GitHub Actions 42395101285](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/42395101285) passed **11,009 backend tests (32 skipped)** on an earlier code head after fixing the five prior static/fixture failures. That run preceded the final timeout, expiry and source-provenance adjustments; **the exact final PR head still requires passing CI**.

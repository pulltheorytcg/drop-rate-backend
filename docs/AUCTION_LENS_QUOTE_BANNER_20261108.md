# Drop Rate Auction Lens — UK quote and compact banner foundation
Status: **stacked draft, not merged, not deployed** · 8 November 2026

Parent development PR: [#983](https://github.com/pulltheorytcg/drop-rate-backend/pull/983). This change deliberately depends on its disabled authenticated local-video pilot; it is **not** a separately deployed new auction platform.

## 1. What is being built and why

Connect the first user-approved minimal banner to a real deterministic backend result. It has **the card crop on the left**, actual approved Drop Rate logo, exact card identity, observed GBP bid, complete all-in GBP cost, eligible UK Market Value and a small over/under badge. No modal, large result dashboard, speculative price or fake drop-rate emblem.

The original prototype showed illustrative example prices. Here, only an authenticated, currently recognised **English/raw Pokémon** card and actual approved UK sold evidence can populate the values. When evidence is missing, the correct screen is **NO CURRENT VALUE**, not a made-up reference price.

## 2. Connections and boundaries

- **Source:** user-selected local video or explicitly permitted footage. No Whatnot/eBay URL capture, overlay injection, stream scraping, screen recorder or bidding workflow. Local image crop stays ephemeral; only a cropped JPEG is sent when the user starts recognition.
- **Client scene loop:** \`mobile/src/lib/auctionLensStream.ts\` samples ≤4fps and requests only after three stable crops, one attempt per lot/generation; old results never repaint a new lot.
- **Authenticated backend:** existing \`/api/v1/auction-lens/pilot/resolve\` verifies the Supabase JWT and current owner's membership, only under \`TCG_AUCTION_LENS_AUTHORISED_PILOT_ENABLED=true\`. The response remains read-only.
- **Exact card:** existing verified fingerprint-index and independently confirmed printing; Japanese, graded, other games and unknown finishes abstain pending separate coverage.
- **Valuation:** only \`_eligible_uk_value\` may attach a current GBP sold Market Value, behind the independent \`TCG_AUCTION_LENS_UK_SOLD_DISPLAY_RIGHTS_APPROVED=true\` flag and explicit raw Near Mint confirmation. **Never trust a client-provided Market Value.** Expired/reference-guide/RRP/asking values cannot enter the comparison.
- **Quote:** new optional \`quote\` object contains a *manually observed*, recent current bid and independent integer-pence shipping, buyer fees, import tax, other costs, status and UK currency. \`auction_lens_quote.compare_verified_quote\` calls the already existing pure \`auction_lens_uk.compare_uk_auction\`. Missing costs **stay null**, never £0. A result with unknown fees or a stale bid has no over/under numeric badge.
- **Banner:** \`backend/app/static/auction-lens-lab.{html,css,js}\` displays the actual project asset \`/assets/brand-assets/storefront-logo.png\`, with the cropped card left. The lab remains an offline test interface. It clears thumbnail and prices immediately on seek, pause, new lot, crop/identity/quote change, source-permission revocation and stop.
- **Native contract:** \`mobile/src/lib/auctionLensResolver.ts\`, \`auctionLensStream.ts\`, \`auctionLensBanner.ts\` share typed price and comparison fields, defend against mismatched market totals and expired values. They are pure components; **no signed native iOS capture or floating iPhone overlay is claimed**.

## 3. Failure modes and required testing

- **Stale answer:** generation mismatch, late API response, paused/ended footage or aborted capture: no old card or price may survive.
- **Wrong print:** similar artwork, finish variant, language or grade mismatch: withhold all deals.
- **Bad quote:** missing shipping/fees/import tax/other charges; stale or future bid observation; ended listing; USD/non-GBP; invalid pence, negative amounts, boolean money: no deal.
- **Bad market evidence:** expired UK sales, Cardmarket guides, asking listings, revoked display rights or uncertain condition: no Market Value or under/over verdict.
- **Privacy:** crop first and transmit only the card region. No video/audio file persistence, no screenshots in GitHub logs and no server-side card inventory/owner/finance mutation.
- **Concurrency:** one bounded recognition request per stable lot, HTTP 429/timeout fail closed, no background detached requests.
- **Brand:** inspect on 320px, 390px and landscape iPhone as well as desktop; use approved Drop Rate imagery and colours (\`#071b3f\` navy, \`#ff9a52\` accent), no generated placeholder logo.

Focused checks: \`pytest -q tests/test_auction_lens_quote.py tests/test_auction_lens_api.py tests/test_auction_lens_quote_banner.py\`, \`node --check backend/app/static/auction-lens-lab.js\`, and \`npm --prefix mobile test -- auction-lens\` plus mobile typecheck. Full repo GitHub CI must pass. Those are **source and simulated-data tests**, not measured real-video accuracy.

## 4. Launch limitations and next stages

1. Resolve the parent PR #983 mergeability and complete all CI on a refreshed main; do not cherry-pick manually without auditing conflicts.
2. Add independent labelled, authorised video with accurate metadata and review; use QA PR #987 to measure exact-print precision, abstention/coverage, median and p95 latency. Target roughly 1s recognition when actual evidence supports it; never promise that from mocks.
3. Build automatic OCR/printing extraction with bounded fallback and exact identity gates. Manual video-lab inputs are **temporary pilot corroboration**.
4. Design a server-owned, revocable short-lived live session and quote refresh path for updating bids *without* re-running recognition. Persist only minimum session metadata with owner RLS and audit; no raw frames. This is **not** part of this low-risk slice and requires migration/volume/security review before implementation.
5. Implement iPhone capture via a supported system-approved mechanism and the correct signed native extension/bridge, complete device/thermal/background tests, then validate what presentation mechanisms are permitted. A concept image is not proof that a global floating banner is supported by iOS or auction-platform rules.
6. Keep the pilot and UK sold display-rights flags **off** until the permission and data gates are actually satisfied. No Railway deployment or third-party auction connection in this PR.

## Rollback

Revert this stacked PR. No database migrations, environment variable changes, external API billing, Shopify, inventory, owner or settlement writes.

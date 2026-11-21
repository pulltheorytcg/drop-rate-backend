# eBay UK 50-day catalogue first-pass: quota and variant safety

Status: **review-only, NOT deployed**. Lovable Collectible Market Scout has exhausted current build credits. This PR improves Railway-side matching and prepares conservative batch planning; it does not assume that the unpublished Lovable API is available.

## Verified baseline (2026-11-13, Supabase Pro)
- tcg.reference_cards: 69,867 rows.
- tcg.reference_sealed_products: 3,893 rows.
- Combined raw count: 73,760 (not deduplicated distinct price identities).
- tcg.reference_market_prices: 59,863 rows, of which 32,510 have non-null market values.
- tcg.reference_sealed_market_prices: 3,889 rows, of which 2,749 have non-null market values.

Do not equate catalogue record totals with unpriced products. Count canonical printing+condition+language+grade pricing identities, current evidence status and staleness separately. Never overwrite stronger evidence with asking quotes.

## 50-day feasibility
Assuming 73,760 first-pass identities, 50 days requires **1,476 distinct products/day**. eBay's published default Browse limit for all methods except getItems is **5,000 calls/day**, with a separate getItems limit. Actual application allowances can differ. Other Drop Rate traffic consumes the shared credentials' quota.

Using a conservative 4,000-call planning allowance after a 1,000-call reserve, 50 days requires **2.71 or fewer calls/product on average**. At 3 calls/product it takes about **56 days**. At 6 it takes about **111 days**. These are rough first-pass throughput estimates, NOT complete Market Value coverage. Searches can have no exact comparable or no sold-price evidence.

The pure Python planner in ebay_batch_budget.py takes real remaining quota, already-used calls, reserved capacity and measured calls/item. It does NOT fetch the quota or schedule real API requests.

## To activate production daily passes safely
1. Verify real eBay Developer Analytics quota and independent method buckets; do not assume unlimited calls.
2. Publish and validate Lovable's read-only candidate endpoint, or use the current Railway official eBay Browse adapter directly. Reuse existing OAuth credentials rather than establishing new parallel secrets.
3. Add a single durable scheduled Railway runner with account-wide call ledger, category/identity cursor, Supabase Pro job receipts and advisory locking. Per-instance in-memory counters are NOT a global quota.
4. Prioritise missing values, then oldest data; deduplicate same print+language+grade and avoid repeat searches on copied inventory.
5. Source active Browse asking prices only as context; never relabel as actual SOLD evidence. Reuse Railway v4 pricing engine and approved append-only Supabase observations.
6. Run read-only pilot and measure exact-match rates before approving any controlled writes. Keep Shopify and existing prices unchanged.
7. Report daily products scanned, accepted/needs-review/rejected candidates, quota used, retry outcomes, source freshness and projected remaining days.

## Game and collectible treatment safety
- Pokémon SIR/SAR, IR, secret, gold, rainbow, full art, shadowless, 1st Edition, promos and holo treatments remain distinct.
- One Piece manga rare, SP, parallel/alt-art, SEC, SR, treasures and promos are distinct.
- Dragon Ball SCR/SPR/SR; Yu-Gi-Oh QCR/prismatic/collector/secret; Lorcana enchanted; Magic etched/borderless/showcase/serialized; Riftbound and Naruto parallels are not globally interchangeable abbreviations.
- Sealed pack vs box vs display vs case and factory sealed vs opened, weighed, repacked or empty remain different.
- Comics series/issue/cover/printing/grade, manga ISBN/volume/language/omnibus and Funko number/chase/exclusive/signed/box condition remain separate identity checks.

The new safety helper detects game-scoped treatments and exposes explicit conflicts. The existing live sold-match function now rejects explicit treatment conflicts. Missing marketing terms alone are review signals, NOT a reason to invent a verified exact match.

## Rogue asking-price diagnostics
The independent asking_price_diagnostics helper analyses only unique, independently vetted exact GBP ACTIVE offers from distinct sellers. It prevents one seller from dominating the reference and excludes statistical extremes with an explicit audit trail; all results retain market_value_gbp=null and verified_sold_count=0. A £700 rogue asking price must not turn a £50 product into a £700 Market Value. The current v4 pricing engine already has separate median/MAD outlier filtering for admitted observations.

## Current release blockers
- Lovable build credits exhausted; cannot complete Lovable API changes in this turn.
- Actual account-specific remaining quota has not been verified.
- Review/CI/live controlled pilot and durable scheduled-worker integration remain outstanding; this PR stages helpers and matching hardening, not a live automatic daily production batch.

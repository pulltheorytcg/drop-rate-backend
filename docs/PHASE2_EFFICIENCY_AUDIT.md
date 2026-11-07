# Drop Rate — Phase 2 Efficiency & Simplicity Audit

_Original audit: 30 September 2026. Catalogue follow-up: 2–3 October 2026._

## Executive result

The system is technically capable, but the full Phase 2 human-efficiency claim is **not yet verified**.

What can be measured from production today shows:
- ordinary founder/dashboard API reads are generally sub-second;
- recognition resolution is the clearest measured latency hotspot;
- some inventory-image responses are also materially slower than normal API reads;
- the catalogue/publication backend is no longer the dominant blocker;
- the real-phone start-to-live card test and real Brand Redesign purchase test still require a human/device and must not be replaced by a synthetic claim.

This audit deliberately separates **machine-side evidence** from the two manual tests required by the operating manual.

## 1. Production complexity baseline

At the start of this audit:
- Railway: 7 services;
- Supabase: 68 base tables in `tcg`;
- Shopify: 470 ACTIVE products;
- physical FOR_SALE inventory: 509;
- published physical Shopify links: 492;
- unlinked FOR_SALE: 17;
- Brand Redesign: unpublished;
- verified real external-customer sales: still not established.

The audit initially proposed deleting two sleeping services because they had no inbound Railway dependencies. The founder correctly flagged the intended graded-card certificate/media capability, so the deletion was cancelled before application. A code inspection then showed the services are not equivalent: `psa-fetch-batch` is a working PSA cert/media batch prototype, while `psa-cert-lookup-temp` is currently a CardTrader Dragon Ball discovery probe despite its name. Sleeping/no inbound dependency is expected for on-demand utilities and is not sufficient evidence for retirement.

## 2. Machine-side latency evidence

Production Railway HTTP logs were sampled from real application use across 27–30 September.

### Recognition

Observed `POST /api/v1/recognition/resolve` HTTP completions included:
- **5.100 s**
- **12.413 s**
- **21.672 s**

The database contains fuller per-run timing evidence. The two most recent supported One Piece v1.4.2 runs that executed the complete provider/candidate path took **11.965 s** and **21.358 s** end to end.

Stage timing shows where the time went:

| Stage | 11.965s run | 21.358s run |
| --- | ---: | ---: |
| OpenAI vision observation | 8.659s | 18.728s |
| Provider discovery | 1.370s | 0.562s |
| Provider-image visual work | 1.532s | 1.718s |
| Catalogue lookup | 113ms | 65ms |
| Learning hints | 63ms | 60ms |
| Learning visual | 53ms | 37ms |
| Final deterministic resolve/scoring | 1.14ms | 0.62ms |

The vision observation consumed roughly **73%** and **88%** of those two complete-path runs. Catalogue lookup and deterministic scoring are not the current bottleneck.

Two newer v1.5.1 runs completed in **4.775s** and **5.090s**, but both images were poor/unknown-game inputs and exited before the full provider/candidate path. They are encouraging for the early-exit path but are **not** valid evidence that an exact supported-card scan now completes in ~5 seconds. A real supported-card v1.5.1 phone test is still required.

This makes the optimization priority much more specific: measure and reduce vision-stage latency first, then provider-image work. Do not add database/infrastructure complexity to solve a bottleneck that the evidence does not place in Postgres or deterministic scoring.

### Typical founder/dashboard reads

Recent observed medians:
- `/api/v1/inventory/brands`: ~119 ms
- `/api/v1/pricing/inventory`: ~119 ms
- `/api/v1/inventory/intelligence`: ~244 ms
- `/api/v1/shopify/readiness`: ~237 ms
- `/api/v1/inventory`: ~481 ms
- `/api/v1/inventory/state`: ~554 ms
- `/api/v1/inventory/market-values`: ~590 ms

These are not instant, but they are not currently the main reason a card scan feels slow.

### Inventory images

A number of inventory image responses were observed around **1.5–2.8 s**, while others were in the ~100–400 ms range.

Code inspection found the concrete reason: Founder HQ always routed the visual inventory grid through the authenticated FastAPI image proxy, which re-downloaded and streamed the remote asset on each card render. PR #344 now carries the narrowly scoped fix: use a strict Shopify-CDN direct/lazy fast path when an existing verified media row already has a Shopify CDN URL, with automatic fallback to the existing authenticated proxy. Provider/source URLs remain proxy-only.

This is a measured optimization of the existing Founder HQ path, not new Seller Hub/recognition scope.

## 3. Card start-to-live test

Required manual path:

`physical card → mobile scan → exact-print match → confirm identity → set condition/price → Shopify live`

### What is verified now

Machine-side evidence confirms:
- recognition can resolve a request successfully;
- inventory/readiness APIs are functioning;
- controlled Shopify publication paths exist and the current catalogue has 0 linked drafts;
- publication retains deterministic owner/Inventory ID attribution;
- ambiguous identity/media cases correctly stop rather than guess.

### What is not yet verified

A true Phase 2 result still needs, on a real phone:
- elapsed wall-clock time;
- number of screens;
- number of taps;
- time spent waiting for recognition;
- time spent on identity/condition/price confirmation;
- time until Shopify is verified live.

No synthetic benchmark should be substituted for that test.

### Current optimization hypothesis

Based on production timing alone, recognition/provider resolution is the first place to investigate if the real-phone test exceeds the target. UI/API metadata reads are secondary.

## 4. Customer purchase test

Required manual path:

`homepage → find a specific card → PDP/grouped copy → cart → checkout → confirmation → Drop Rate owner attribution`

### What is verified now

- Shopify native cart/checkout architecture exists.
- Historical paid test order #1002 successfully created a Drop Rate order and exact physical inventory/owner attribution, then refund/cancellation handling was exercised.
- That historical test was on the old launch context and does **not** satisfy the Phase 2 Brand Redesign purchase gate.

### What is not yet verified

The final measurement needs Brand Redesign itself and a real customer-style journey:
- elapsed time;
- clicks/taps;
- search/browse friction;
- checkout completion;
- confirmation email;
- Founder HQ/Seller Hub visibility;
- exact owner allocation.

## 5. Concrete issues found by this audit

### Pooled public copy — fixed

The stale-PR review found two live Dragon Ball quantity-2 pooled products still used single-copy wording and exposed one member's internal Inventory ID.

Actions completed:
- both Shopify descriptions corrected without changing quantity, SKU or price;
- PR #311 preserved/merged for the Brand Redesign PDP stock/internal-ref fix;
- PR #337 ported the missing pooled-description hardening onto current main;
- CI passed and production deployment succeeded.

### Historical #1001 webhook gap — resolved and protected from reopening

#1001 was an unpaid PENDING test order that was cancelled, had a successfully processed `orders/cancelled` webhook, left no reservation/local sale, and was followed by successful #1002.

PR #338 changes reconciliation so a cancelled unpaid remote-only order with processed cancellation evidence is terminally acknowledged. Paid-like remote-only orders remain CRITICAL; uncancelled pending orders with missing create proof remain HIGH.

The two founder-scoped HIGH rows for #1001 were then dismissed through a guarded production reconciliation only after verifying: no local order exists, the cancellation webhook is PROCESSED, and no reservation remains. Audit events record the resolution and no synthetic order was created. Production now has **0 OPEN `SHOPIFY_ORDER_WEBHOOK_GAP` items**.

### PSA certificate/media capability — retained and reclassified accurately

`psa-fetch-batch` is a real PSA certificate lookup prototype. Its current code fetches seven hardcoded PSA certs and returns normalised cert identity, grade, language/printing and front/back image URLs. It should remain available as proof of the slab-verification/media path, then be refactored into a parameterised adapter after the storefront milestone.

`psa-cert-lookup-temp` is **not currently a PSA cert service**. Its present Function code probes CardTrader games/expansions for Dragon Ball. It is retained for now rather than destructively removed, but should be renamed or repurposed later so the infrastructure map matches reality.

PSA image publication must remain rights-aware: cert verification/data lookup is a separate question from whether a particular PSA-hosted image may be republished on the storefront.

### Action Required queue — stale media lifecycle corrected and reconciled

Phase 2 review found 11 OPEN `MEDIA_UNRESOLVED` rows even though only 8 Dragon Ball exact-print exceptions were genuinely unresolved.

The three stale rows were:
- BT18-067 Krillin;
- BT18-138 Reaper's Cunning;
- BT13-142 Dark King Mechikabura.

PR #340 fixes the lifecycle bug so moving beyond unresolved media closes the obsolete `MEDIA_UNRESOLVED` state. The three historical rows were then resolved through a guarded, audited production reconciliation only after verifying each canonical card has eligible exact media and at least one PUBLISHED physical Shopify link.

Production now has exactly **8 OPEN `MEDIA_UNRESOLVED` rows**, matching the eight true Dragon Ball exact-print exceptions.

### Multi-grader slab scanner — architecture recorded, implementation still deferred

PR #342 merged the future **Raw Card / Graded Slab** scanner architecture for Founder HQ and the future Seller Hub/mobile app.

The common grader-adapter plan covers:
- PSA;
- ACE;
- CGC;
- TAG;
- BGS / BVG / BCCG.

The slab flow is cert/QR-first: detect grader → read certificate/serial → provider verification where permitted → deterministic exact catalogue match → preserve grader/grade/cert on the physical Inventory Item → attach exact permitted slab media → human confirmation.

PSA is the first full automation target because an official cert API exists. TAG's cert/QR + DIG report model is explicitly supported in the design. ACE/CGC/BGS remain adapter-gated where machine access is not yet documented/permitted; reCAPTCHA or similar controls must not be bypassed.

Implementation remains behind the Phase 2 storefront stability gate.

### n8n production state — verified empty

A read-only Railway inspection of the production n8n service confirmed:
- n8n **2.32.6**;
- startup processed **0 draft workflows and 0 published workflows**;
- no active workflow exists;
- no error workflow is configured.

So the Phase 2 version-control rule is not currently being violated by an invisible live workflow. The first real production workflow still needs to prove the required pattern: exported JSON in GitHub, signed/idempotent ingress, safe retry behaviour, and an n8n error workflow before activation.

## 6. Simplicity conclusions

The product does not need another infrastructure layer before launch.

The useful simplifications are:
- distinguish genuinely obsolete services from low-frequency on-demand capabilities before removing anything;
- close/supersede stale PRs only after preserving unique behavior;
- keep one authoritative operations monitor;
- keep n8n dormant until one low-risk workflow proves the pattern;
- do not build a custom Google Shopping feed;
- optimize measured recognition/image bottlenecks instead of adding general-purpose services;
- retire the one-shot Shopify reconciliation worker later if launch stability proves it is no longer useful.

## 7. Launch stability definition

Brand Redesign is considered **stable enough to reopen deferred workstreams** only after all of the following are true:

1. Brand Redesign has remained MAIN for at least **72 consecutive hours** without a checkout-blocking rollback.
2. At least **5 genuine paid non-founder customer orders** have completed successfully.
3. Those orders contain **zero owner-attribution, physical Inventory ID allocation, oversell or settlement discrepancies**.
4. There have been **zero CRITICAL Action Required items for 72 consecutive hours**.
5. No post-launch Shopify order remains with an unresolved webhook/reconciliation gap.
6. At least one outside person who did not build the platform has completed the purchase path and their usability findings have been recorded.

Passing this bar does not reopen everything automatically. It permits an explicit review to reopen **one frozen workstream at a time**.

## 8. Remaining Phase 2 human checks

Before theme publication:
- full mobile Brand Redesign smoke on a real phone;
- full desktop Brand Redesign smoke;
- real Brand Redesign test purchase and confirmation/owner-attribution verification;
- measure the real card scan-to-live path and count taps/screens;
- measure the customer find-to-checkout path and count clicks.

Those are the only efficiency/publish-gate checks in this audit that cannot be honestly completed from backend/store data alone.

## 2–3 October 2026 — Catalogue search follow-up

The user's reopened hub usability work exposed avoidable browse-query work: full reference-library materialization, catalogue-wide pricing before ordinary pagination, and waiting for game metadata before product retrieval. A bounded application query/client change reduces measured warm database medians by 61–83% across six browse journeys. Nineteen read-only comparisons retain full results, order, prices and ownership quantities. See `docs/CATALOGUE_BROWSER_PERFORMANCE.md` for samples, method and limits. This supplements the machine-side audit; it does not substitute for the two manual end-to-end timing tests.

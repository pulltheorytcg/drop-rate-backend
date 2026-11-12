# Pricing Engine Autonomy & Live Health Tracker — 12 November 2026

Status: **development PR; no automatic Market Value publication activated**.

## What this builds
The founder requested an autonomous engine and a **live health tracker instead of manual five-sale entry**. This first safe step makes existing pipeline health visible in the settings screens that founders actually use:
- /owner#settings → Pricing engine health, available only to verified founders.
- /founders#settings and /app#settings → the same health widget in the older Founder HQ shell.
- A new authenticated GET /api/v1/pricing/health endpoint.
- Browser auto-refreshes every 60 seconds while the view is visible; manual Refresh now works too.
- Endpoint reads a single PostgreSQL read-only transaction under the existing authenticated founder-roster predicates (business_allowed). No service-role bypass, no new DB table, no schema migrations.

The engine, owners, grades, inventory, Store Prices and Shopify publishing are unchanged.

## What the dashboard displays
- Distinct counts of active physical inventory, items with **stored** Market Values, items updated within 7 days, and missing values. Stored-value coverage is **not** the same as current sale-verified coverage.
- Historical eBay SOLD observations, qualifying UK normalized sold evidence, new records in the last 24 hours, most recent observation ingestion, and latest eBay ingestion run result.
- Cardmarket historical price guides, their ingestion freshness and last run (context only, not a sold-price source).
- Official eBay Browse (asking price context only) and authenticated eBay Product Research (human research; unattended collector not verified).
- Legacy refresh and new market ingestion flags, bulk-refresh hold state, and explicit issue codes for missing fresh sold evidence, stale Cardmarket context, failed eBay jobs, disabled ingestion, bulk hold, and coverage gaps.
- Sources and redacted run summaries only; no provider errors, personal data, request contents or credentials.
- A readout for whether market ingestion is disabled or bulk operations are held. The UI never offers unsafe "turn on scraping" or "publish Market Value" buttons.

## Read-only production baseline (independently checked)
- 617 active items; 244 stored values (39.5%); 73 updated in the preceding week.
- 1,083 eBay SOLD observations, 5,238 Cardmarket PRICE_GUIDE observations.
- No new records in the last 24h from either source.
- Zero eBay SOLD rows carry the existing normalized UK paid-price provenance revision.
- Latest eBay scheduled job activity ended FAILED on 10 Nov; historical SUCCEEDED runs from 1 Nov.
- These counts do not establish that any live stored Market Value has 5 exact verified and permitted UK paid-price comparisons.
- Time-stamped figures change and must always be obtained through the new endpoint, not hardcoded into the app.

## Why not silently enable automated sales scraping?
The official eBay Browse API supplies **asking prices** rather than verified completed-sale transactions. The founder's signed-in eBay Product Research Cloud Browser session is unavailable from this Chat session; being signed in also does not authorize copying its browser credentials to Railway or unattended extraction. Our previously used Trawl paid scraping service is declined and its last refresh failed/was held.

Autonomous prices **must** be sold-backed and identity-verified, not filled with price guides, retail prices or AI guesswork. The existing FastAPI deterministic pricing rules remain the only calculation engine. Current automatic Market Value publication is therefore **not ready**.

## Autonomy release stages
1. **Now:** One live health dashboard, no user data entry, polling every minute; no running provider calls or unsafe price publication.
2. **Next:** Independently confirm a permitted automated completed-sale data channel and provenance sufficient for raw, graded and language-specific exact matches. Do not bypass quotas/terms.
3. **After approved source:** Ingest append-only, deduplicate source IDs, classify by exact card identity/condition/grade/variant/language, maintain independent source timestamps and permission status. Reuse existing normalizer, sold-only pricing engine, idempotent worker/orchestration and publish Market Value independently of Store Price.
4. **Pilot:** 1 raw Pokémon, 1 One Piece, 1 PSA graded, mixed-owner order safety, and both low/high-liquidity outlier cases. Measure verified Market Value coverage before/after; only then widen.
5. **Ongoing:** Flag provider failures, low matching confidence, insufficient sold comps, stale evidence, identity mismatches, artwork problems, and pricing/settlement anomalies in Action Required without silent retries or customer-facing estimates.

## Failure and permission testing
- True/false founder business entitlement, no seller exposure and no cross-owner facts.
- SQL uses RLS-bound read-only snapshot; no INSERT, UPDATE, DELETE, schema or provider calls.
- Ineligible eBay sales are excluded from "qualifying" even if newly imported.
- If a whole legacy feed is freshly imported, 24h total may rise but the overall price-source status must still be BLOCKED when qualified paid-price records remain zero.
- Cardmarket PRICE_GUIDE, eBay Browse asking context and stale sales can never trigger an "operational" label.
- Client: no unsafe innerHTML, no stale data crossing logout or account switch, visible founder-only panel, 60s polling and manual refresh, no secret provider errors.
- Full Python, JS, Postgres, and existing pinned n8n CI before merge. No Cloudflare migration, no paid scraper subscription, no new DB changes.

Rollback: remove/revert this PR; original pricing, price history, ownership, storefront and settlement modules remain untouched.


## Catalogue-wide health (separate from owned stock)
The founder health widget also reads the **existing** authenticated
\`/api/v1/catalogue-browser/coverage\` result, at most every 10 minutes per
visible founder session. The server already coalesces the expensive exact
reference aggregation with a 120-second cache. The dashboard shows
\`summary.physical_cards.priced / total\` as *catalogue reference pricing*,
**clearly labelled guide-inclusive, not completed-sale proof**. No independent
or competing source valuation query is introduced. On provider/coverage timeout,
the instant physical-inventory and source-health panel remains usable.
Reference coverage is not a count of owned physical inventory and does not
indicate that each raw/graded/finish variant is valued. Never merge these
totals or represent catalogue guide coverage as physical UK sold Market Values.

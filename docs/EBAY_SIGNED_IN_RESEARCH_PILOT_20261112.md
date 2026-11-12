# Drop Rate — signed-in eBay UK Product Research pilot
**12 November 2026 · DRAFT / NOT DEPLOYED**

## Scope and architecture
The founder approved using the signed-in droprate_tcg eBay account to research UK completed-sale prices. This PR adds a small **human-assisted, offline** bridge into existing sold-price matching. It is **not** an automated browser collector, and it cannot read eBay cookies from Railway. The stack remains Railway/FastAPI, Supabase Pro, GitHub and Shopify. No Cloudflare migration, new service, schedule or paid scraper.

The existing exact-print matcher is reused. A founder opens the generated sold-search URL in their normal signed-in eBay browser. For accepted Best Offers, use Seller Hub > Research > Product Research to confirm the **actual paid price**, not the original asking price. Official documentation: https://www.ebay.co.uk/help/selling/selling-tools/product-research?id=4853

## What is built
- backend/app/ebay_signed_in_research.py — sale search-link builder and read-only preview for up to 100 reviewed records.
- backend/scripts/ebay_signed_in_research_preview.py — private JSON manifest preview CLI.
- tests/test_ebay_signed_in_research.py — price evidence validation and failure tests.

No automated eBay HTTP access, browser sessions/cookies, credential retention, database insert, market-value publication, inventory change, Shopify write or settlement activity.

## Founder workflow
1. Sign in to eBay as droprate_tcg in the normal browser and navigate to Seller Hub > Research > Product Research.
2. Pick one confirmed physical card identity from Drop Rate: exact game, set, number, variant, language and condition (or grader/grade).
3. Use the CLI-generated sold-search URL in that signed-in browser, then consult Product Research to check actual paid prices where a Best Offer may be involved.
4. Manually review a small number of exact, item-level sales. Don't invent missing eBay item IDs, prices, countries, condition or dates. If only an aggregate is shown, it cannot count as five independent sales.
5. Create a private local JSON file with top-level "target" and "sales" arrays; do not put credentials, cookies, seller/buyer names, private profiles or raw HTML into the manifest. Never commit private manifests.

### Synthetic, one-row manifest example (NOT a real sale)
    {
      "target": {
        "game": "Pokemon", "name": "Seel", "set_name": "Phantasmal Flames",
        "card_number": "021/094", "variant": "Normal", "language": "English",
        "condition": "Near Mint", "grading_company": null, "grade": null
      },
      "sales": [{
        "source": "EBAY_PRODUCT_RESEARCH", "sale_price_basis": "ACTUAL_PAID_PRICE",
        "item_id": "123456789012",
        "title": "Pokemon Seel 021/094 Phantasmal Flames Near Mint",
        "sold_at": "2026-11-11", "price_gbp": "5.00",
        "shipping_gbp": null, "currency": "GBP", "item_country": "GB",
        "condition_raw": "Near Mint", "set_name": "Phantasmal Flames",
        "card_number": "021/094", "variant": "Normal", "language": "English"
      }]
    }

Run from the repo root:

    PYTHONPATH=backend python backend/scripts/ebay_signed_in_research_preview.py --manifest /private/reviewed-sales.json --read-only

Output is a safe summary with the browser search link and accepted/excluded counts, not raw eBay IDs or individual sale prices. With five exact records and at least one recent sale, it reports a **candidate median item-price**, not a publishable Market Value. Human-transcribed records cannot silently become verified price evidence.

## Failure points
- Browser context inaccessible: generate link only, do not claim account access.
- Unknown Best Offer amount or regular sold-listing asking price: reject as unconfirmed.
- Wrong printing, set, grade, condition, language, variant, currency or UK location: reject.
- Duplicate item IDs: remove rather than inflate the price sample.
- Stale (>90 days), future or no sale in the last 14 days: no candidate.
- Date-only research: preserve day precision; do not invent precise transaction times.
- Missing item-level identifier or only aggregate/guide data: no independent comparables.
- Browser account/permissions limit: stop, do not circumvent account checks or blocks.

## Tests and release gate
Run: PYTHONPATH=backend pytest tests/test_ebay_signed_in_research.py -q

Then full repository CI. Tests cover search URL, identity matching, GBP and UK guards, actual-price claims, Best Offer/active-listing exclusion, duplicates, condition, set, grade, printing, date-only recency and no-write behavior. Only a follow-up, human-reviewed PR could ingest independently verified transactions into existing append-only Supabase observation records. It must preserve source provenance, RLS, history, ownership, Store Price and existing pricing gates, with backup/rollback and live acceptance evidence.

**At authoring:** no full CI pass, eBay browser readback, production write or Railway deployment has been claimed.

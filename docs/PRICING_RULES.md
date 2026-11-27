# Pricing rules

These are owner decisions recorded on 27 Nov 2026. They are the single reference for which price appears where. Code that shows or totals a price must follow this table.

| # | Surface | Rule |
|---|---|---|
| 1 | **Stock Market Value** (inventory, owner portal, founder portfolio) | See [Rule 1](#rule-1-stock-market-value). |
| 2 | **Catalogue browse value** (all cards) | See [Rule 2](#rule-2-catalogue-browse-value). |
| 3 | **US prices** (TCGplayer, including via TCGCSV) | Never part of any UK value, including as Drop Rate daily-model peers. They may be stored and shown as labelled context. |
| 4 | **Expired values** (sold over 90 days, guides over 7 days) | No current value and never totalled. Shown as **"Last known £X · date"**. Stored inventory values past the window are cleared on the next live refresh; snapshots and history are kept. |
| — | **Store Price** (Shopify) | Always set by the owner. Never automatic, and never changed by any rule above. |

## Rule 1: stock Market Value
1. **UK sold.** Five exact-printing UK eBay sold prices, all within the last 90 days. For slabs, the sales must also be verified.
2. **Otherwise, a labelled estimate.** If there are not five such sales, use a Cardmarket EU guide converted at the ECB rate, labelled **"Estimate · Cardmarket EU guide"**.
   - It applies only to raw cards in Near Mint or with no recorded condition. Graded, worn and sealed items never get a guide.
   - It counts towards totals, which report it separately as "of which estimates £X".
   - It never produces a retail recommendation.
   - Catalogue-wide guide ranges are shown for display only and do not count in totals.

## Rule 2: catalogue browse value
The first available value is shown:
1. UK sold evidence.
2. The UK asking median: live UK eBay delivered asks from 3 or more independent sellers, exact printing, NM raw, at most 3 days old.
3. Cardmarket EU: the 7-day sales context, or otherwise the guide, labelled as an estimate.
4. Unavailable.

The internal Drop Rate model never supplies a displayed value.

## Where it is enforced
- **Backend resolver:** `backend/app/inventory_reference_values.py` (`resolve_reference_value`, `reference_totals`).
- **Browse aliases:** `backend/app/catalogue_display_prices.py` (`shared_prices`) and `backend/app/inventory_catalogue_reference.py` (`catalogue_guide`, method `CARDMARKET_CATALOGUE_GUIDE`).
- **Front-end gate:** `backend/app/static/reference-value-display.js`.
- **Browse order:** `backend/app/static/catalogue-browser.js` (`marketPrice`).
- **US exclusion:** `backend/app/drop_rate_daily_model.py` (`_peer`).
- **Stale clearing:** `backend/app/live_market_refresh.py`.
- **Health page wording:** `backend/app/pricing_health.py`.

## Known gaps
- **UK asking prices:** nothing collects them on a schedule. Until that is set up, browse step 2 is rarely available.
- **`/pricing/inventory` reads the stored `inventory_items.market_value_minor` column**, not this resolver. Rule 4 clearing keeps that column honest, but a full switch to the resolver is still to do.

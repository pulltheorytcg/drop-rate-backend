# Pricing rules

These are owner decisions. They are the single reference for which price appears where. Code that shows or totals a price must follow this document.

## Owner decision of 28 Nov 2026: asking average and Cardmarket first

The owner's words: "we have the eBay browse API set up, we need to have the average price of advertised cards, we then compare with cardmarket too, pricing should be logical too, so if 9 sellers are selling a card at £40 but one person is selling for £200 that shouldn't change the average price we sell at which would be £40 too". Asked which evidence comes first: "Average asking + cardmarket first". It applies to every category: cards, comics and manga.

The order this sets, for stock and for the catalogue:

1. **UK eBay asking average, checked against Cardmarket.** The middle price of what UK sellers are asking now. One seller counts once, and a price far from the rest is dropped, so one £200 listing among nine at £40 leaves £40. Where Cardmarket has the product, the two are compared and a large disagreement is held for review instead of shown.
2. **Cardmarket**, downloaded daily, where there is no usable asking average.
3. **UK sold prices**, where neither exists.

Store Price (Shopify) is unchanged: always set by the owner, never automatic.

### What is live, and what is not yet

| Part | State |
|---|---|
| Asking average with outlier removal (`reference_asking_estimator.py`) | Live. Three or more independent UK sellers, raw Near Mint, delivered price, valid three days. |
| Scheduled collection of asking prices (`reference_asking_schedule.py`) | Live from 28 Nov 2026. Hourly, approved stock first, then the highest-value catalogue cards. |
| Asking average shown ahead of a fresh Cardmarket guide | **Not yet.** `add_asking_estimates` still fills only cards with no guide or an expired one. |
| Cardmarket comparison for every game | **Not yet.** `estimate_uk_eu_market` compares only Pokémon priced through TCGdex. |
| Asking average as stock Market Value | **Not yet.** Stock still follows Rule 1 below. |
| Comics and manga | **Not yet.** They show only UK sold values; the eBay asking range is display context. |
| Cardmarket for Magic, Yu-Gi-Oh! and Lorcana | **Not yet.** Cardmarket publishes the files; nothing imports them. |

Until a row above says live, the rules of 27 Nov below are what the code does.

### Limits to know

- eBay allows 5,000 Browse calls a day and the collector caps itself at 2,000. A card costs one search plus up to six listing reads, so about 300 cards a day. That covers stock; it cannot cover a 70,000-card catalogue, which is why Cardmarket is step 2.
- An asking average needs three independent UK sellers. Rare cards with fewer listings fall to step 2.

## Rules of 27 Nov 2026 (still what the code applies where the table above says "not yet")

| # | Surface | Rule |
|---|---|---|
| 1 | **Stock Market Value** (inventory, owner portal, founder portfolio) | See [Rule 1](#rule-1-stock-market-value). |
| 2 | **Catalogue browse value** (all cards) | See [Rule 2](#rule-2-catalogue-browse-value). |
| 3 | **US prices** (TCGplayer, including via TCGCSV) | Never part of any UK value, including as Drop Rate daily-model peers. They may be stored and shown as labelled context. |
| 4 | **Expired values** (sold over 90 days, guides over 7 days) | No current value and never totalled. Shown as **"Last known £X · date"**. Stored inventory values past the window are cleared on the next live refresh; snapshots and history are kept. |
| — | **Store Price** (Shopify) | Always set by the owner. Never automatic, and never changed by any rule above. |

Rules 3 and 4 are unchanged by the 28 Nov decision.

### Rule 1: stock Market Value
1. **UK sold.** Five exact-printing UK eBay sold prices, all within the last 90 days. For slabs, the sales must also be verified.
2. **Otherwise, a labelled estimate.** If there are not five such sales, use a Cardmarket EU guide converted at the ECB rate, labelled **"Estimate · Cardmarket EU guide"**.
   - It applies only to raw cards in Near Mint or with no recorded condition. Graded, worn and sealed items never get a guide.
   - It counts towards totals, which report it separately as "of which estimates £X".
   - It never produces a retail recommendation.
   - Catalogue-wide guide ranges are shown for display only and do not count in totals.

### Rule 2: catalogue browse value
The first available value is shown:
1. UK sold evidence.
2. The UK asking median: live UK eBay delivered asks from 3 or more independent sellers, exact printing, NM raw, at most 3 days old.
3. Cardmarket EU: the 7-day sales context, or otherwise the guide, labelled as an estimate.
4. Unavailable.

The internal Drop Rate model never supplies a displayed value.

## How an eBay listing is matched to a card

`reference_asking_estimator._matches` decides. A listing must be a single raw card, fixed price, located in the UK, with a known delivered price, and must match the card's name, collector number, release, finish and Near Mint condition. From 28 Nov 2026:

- **Language.** An English card accepts a listing that names no language, unless the title carries a Japanese release code (sv2a, s12a). Any other language must be named. A listing naming a different language is rejected.
- **Release.** The seller's set specific must contain the release ("SV: Scarlet & Violet 151" for 151). For One Piece and Fusion World, the complete number in the title (OP16-064) names the release when the listing gives no set. A specific naming another release rejects the listing. Dragon Ball Masters keeps whole-name matching.
- **Collector number.** Padding and punctuation are ignored (010/025 is 10/25). A specific giving a different number rejects the listing.
- **Grading, bundles and condition** are read from the title, eBay's condition and the specifics that state them, not from every specific joined together. "Not specified" in a grading field is a raw card; a company, grade or certificate number is a slab.

## Where it is enforced
- **Asking collection:** `backend/app/reference_asking_schedule.py` (what and when), `reference_asking_backfill.py` (calls, quota, writes), `reference_asking_estimator.py` (matching, median, outliers).
- **Backend resolver:** `backend/app/inventory_reference_values.py` (`resolve_reference_value`, `reference_totals`).
- **Browse aliases:** `backend/app/catalogue_display_prices.py` (`shared_prices`) and `backend/app/inventory_catalogue_reference.py` (`catalogue_guide`, method `CARDMARKET_CATALOGUE_GUIDE`).
- **Asking display:** `backend/app/reference_asking_display.py` (`add_asking_estimates`).
- **Front-end gate:** `backend/app/static/reference-value-display.js`.
- **Browse order:** `backend/app/static/catalogue-browser.js` (`marketPrice`).
- **US exclusion:** `backend/app/drop_rate_daily_model.py` (`_peer`).
- **Stale clearing:** `backend/app/live_market_refresh.py`.
- **Health page wording:** `backend/app/pricing_health.py`.

## Known gaps
- The "not yet" rows in the table above.
- **Cardmarket is daily only by accident.** The bulk price job is scheduled weekly and stays current because one release fails its check and the job retries hourly. It needs its own daily schedule.
- **`/pricing/inventory` reads the stored `inventory_items.market_value_minor` column**, not the resolver. Rule 4 clearing keeps that column honest, but a full switch to the resolver is still to do.
- **Switch off:** set `TCG_EBAY_ASKING_SCHEDULE_ENABLED=false` on `drop-rate-api-live` to stop the hourly collection. Stored asking prices then expire within three days.

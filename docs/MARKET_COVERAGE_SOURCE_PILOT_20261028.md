# 89% reference pricing: source evaluation and Decodo pilot

Date: 28 October 2026. Status: **Decodo acquisition client and pilot implemented; live collection awaits a credential**.

## Verified baseline

Read-only live database snapshot: 2026-10-28T19:39:19.17738+00:00.
Coverage logic: deployed main commit `cfc964d05d355aa919608b2d19a57338f1e3822d`, `backend/app/catalogue_coverage.py`, with the exact digital-release predicate from `reference_applicability.py`.

**43,279 of 67,065 physical card references (64.53%)** have a current supported reference value or explicitly labelled mixed-language guide. The exact 89% threshold is **59,688**, leaving **16,409** additional references required.

This is reference-price availability, not a claim that all those values are exact UK completed sales, condition-specific valuations or inventory selling prices. Digital TCG Pocket references and sealed products remain separately reported; no records were removed to improve the percentage.

| Game | Language | Physical references | Priced / guide | Missing |
| --- | --- | ---: | ---: | ---: |
| DRAGON_BALL_SUPER_FUSION_WORLD | English | 4,365 | 1,407 | 2,958 |
| DRAGON_BALL_SUPER_FUSION_WORLD | Japanese | 3,229 | 399 | 2,830 |
| DRAGON_BALL_SUPER_MASTERS | English | 9,002 | 5,725 | 3,277 |
| NARUTO_BANDAI_LEGACY | Unknown | 4,487 | 0 | 4,487 |
| NARUTO_KAYOU | Unknown | 2,679 | 0 | 2,679 |
| ONE_PIECE_CARD_GAME | English | 4,527 | 2,336 | 2,191 |
| ONE_PIECE_CARD_GAME | Japanese | 4,480 | 2,156 | 2,324 |
| POKEMON_TCG | English | 21,290 | 20,765 | 525 |
| POKEMON_TCG | Japanese | 13,006 | 10,491 | 2,515 |

All missing English references plus Japanese Pokemon total 11,466. Even perfect recovery of that group produces 54,745/67,065 = **81.63%**, still 4,943 short. Japanese One Piece, Japanese Fusion World and the two existing Naruto games therefore determine whether 89% is attainable. If Naruto remains entirely unavailable, all but 211 non-Naruto references must be priced. Advertised provider catalogue totals cannot establish this.

The latest inspected scheduled source receipts were 19:00–19:02 UTC: One Piece used ten free requests and added two eligible values; Dragon Ball used eighteen with no eligible additions; Japanese Pokemon used seven and found four identities but no supported positive trend. These are existing scheduled-job results, not gains from this source audit. Trawl's recorded free allowance is exhausted; its existing pause is retained.

## Decodo assessment

The founder specifically requested Decodo for recent eBay sold data. A bounded acquisition client and diagnostic runner are implemented. It is not yet an activated production price feed.

- [Web Data API pricing](https://decodo.com/web-data-api/pricing): free and $19/month plans allow 10 requests/second. The advertised 200 requests/second begins at $999/month. No plan was purchased.
- [Billing reference](https://help.decodo.com/docs/web-data-api-billing): request cost depends on plan, proxy pool and JavaScript. At free/$19 rates, premium plus JavaScript is $1.50 per 1,000 successful requests. A single-page pass over 23,786 missing references would consume about $35.68 at that rate, before pagination or detail pages; this is a request-charge illustration, not a subscription quote or recovery forecast.
- [API introduction and usage policy](https://help.decodo.com/docs/web-data-api-introduction): the current interface is `https://data.decodo.com/v1/scrape` with a Web Data API bearer key; legacy tokens differ. Decodo limits this product to publicly accessible data and places website-term compliance on the customer. Post-login/authenticated content is unsupported.
- [eBay UK User Agreement, section 3](https://www.ebay.co.uk/help/policies/member-behaviour-policies/user-agreement?id=4259): automated scraping and commercial use require prior express eBay permission. Buying scraper infrastructure does not establish those rights.
- [eBay Product research](https://www.ebay.co.uk/help/selling/selling-tools/product-research?id=4853): public completed-search results and the actual accepted Best Offer price differ. A crossed-out asking price is not acceptable as a realised sale.
- [Decodo's eBay guide](https://decodo.com/blog/how-to-web-scrape-ebay) describes sold/completed search filters, but it is not a licence to access or republish eBay data.

Live Railway variable names were inspected without reading secret values: no Decodo-named credential is configured on the API service. No eBay access permission or licensed Decodo eBay sold-data agreement was found in the reviewed project material. Do not infer absence from an account outside the reviewed resources.

**Current execution blocker:** configure a free-plan Web Data API credential securely. The founder explicitly instructed proceeding with Decodo at up to 10 requests/second and handling the eBay permission request separately. This supersedes the earlier project-level prior-permission gate for this work; it does not establish a provider licence. No additional permission checkbox or invented approval requirement is implemented. Login gates, unsupported responses and hidden sale prices still stop or exclude evidence on technical/data-quality grounds.

## Other sources found

| Source | Potential fit | Access and unresolved limitation |
| --- | --- | --- |
| [Valo.Data](https://valotcg.com/developers/api/one-piece) | Promising Japanese One Piece lead; advertises separate parallels and EN/FR/JA catalogue | [Free Sandbox](https://valotcg.com/developers/pricing) offers 1,000 credits/month for non-commercial evaluation; commercial Starter is €19/month. Free omits Cardmarket/TCGplayer IDs. Exact sample recovery and current dates are untested. Its published October 19 example is too old for our seven-day freshness rule on October 28. |
| [Valo coverage](https://valotcg.com/developers/coverage) | Pokemon and English Masters/Fusion also listed | Fusion World is English; Naruto Mythos is a different game from our Bandai Legacy and Kayou records. It does not demonstrate recovery of those gaps. Confirm full retention terms before production use. |
| [JustTCG](https://justtcg.com/pricing) | Pokemon including Japanese, English One Piece and Fusion | Free is non-commercial; commercial Starter is $19/month plus applicable tax. No key configured or missing-card success rate verified. |
| [TCG API](https://tcgapi.dev/games/) | Advertises Masters, Fusion, One Piece and Japanese Pokemon | [Commercial Pro](https://tcgapi.dev/pricing) is $49.99/month. Its tiny Naruto catalogue does not establish Legacy/Kayou coverage. [Cancellation data-deletion terms](https://tcgapi.dev/legal/licensing/) need reconciliation with our audit-history requirements. |
| [Flipzi](https://flipzi.io/api/pricing) | Cardmarket-based comparison candidate | Free evaluation; commercial Basic €19.99/month excluding VAT. Prior project's small public evaluation did not establish new eligible UK prices. Claimed Naruto coverage is not evidence for our 7,166 missing records. |
| [TCGTracking](https://tcgtracking.com/tcgapi) / [TCGCSV](https://tcgcsv.com/) | Public bulk exports and product identifiers | Public accessibility is not a downstream commercial licence. Existing TCGCSV integration remains disabled pending rights evidence. |
| [TCGGraph](https://tcggraph.com/games/dragon-ball-super) | English Dragon Ball candidate | Its documented English catalogue does not resolve Japanese Fusion. Existing keyless adapter is not a connected source. |

These are provider claims reviewed on October 28, not measured match rates. Public explorer access failed, so no candidate is labelled tested against all 36 selected references. Paid upgrades remain unjustified until an exact-card pilot succeeds.

## Pilot deliverables and sequence

The companion JSON contains **36 currently unpriced references**, four deterministically selected from each of nine game/language groups. The SQL orders by a stable hash within each group. This is a diagnostic sample, not a statistical estimate of whole-catalogue coverage.

1. Configure the Decodo credential and run the prepared acquisition pilot. Keep provider terms and any later permission correspondence in the source record. Stop on authentication gates rather than supplying eBay sessions.
2. Put the chosen provider's credential in the existing secret manager. Do not include credentials in SQL, manifests, screenshots, PRs or chat. Start on an available free evaluation allowance; no recurring subscription is authorised by this document.
3. Run the 36-reference sample first: one in-flight request, at most one request/second or the lower permitted rate; at most two search pages per reference and 200 outbound requests including bounded retries/detail lookups. The implemented client caps requests at 10/second and 200/run; the CLI defaults to 1/second and 72/run. A single sequential pilot may run below its configured ceiling.
4. Log response status, billed requests, returned items, identity matches, eligible sold observations and rejection reasons separately. Provider success or HTTP 200 is not coverage gain. Stop on 401/403, login/challenge pages, quota exhaustion or schema drift; honour Retry-After for 429 and cap retries.
5. Review all accepted sample matches, then enlarge the same-language hard groups only if there is valid incremental evidence. Produce a measured cost per newly supported reference before considering bulk rollout.

## Observation and pricing contract

Retain only the data necessary for price evidence: provider, original marketplace, listing/event identifier, permitted source URL, title or identity evidence, sold date, retrieval time, original amount/currency, shipping and its known/unknown state, sold/unsold state, price basis, language, set, number, variant, condition, grading company and grade. Exclude buyer identities, addresses and account/session data.

An ended listing is not necessarily sold. A search result may be a related card, bundle, proxy, damaged item or slab. Reject unresolved language, parallel, condition and grade matches; canonical numbers alone are insufficient. Do not convert a base card into a parallel, raw into graded, or English into Japanese. Naruto's current Unknown language needs resolution before an exact-language match.

Reject unknown accepted Best Offer amounts. Missing price or no qualifying sale stays missing. Multi-quantity listings need event-level evidence; a repeated listing ID is not proof of another sale. Use an idempotent provider/event identity and preserve raw observations according to the granted retention policy.

Convert currency through the existing dated FX path and preserve the original amount. Use the existing deterministic robust pricing rules; do not set market value to the last sale alone. Low-sample or high-dispersion evidence enters Action Required. Imported data must not change ownership, publish stock or overwrite historical observations.

## Implementation boundaries and failure tests

The independent acquisition client returns the existing sold-client payload shape, with Decodo provenance. The pilot deliberately makes no database writes and does not claim that search results are verified mappings. After live payload and exact-card validation, connect it to append-only observations and existing normalisation/pricing services. n8n can schedule that API later; it must not contain matching or valuation rules. See [the runnable pilot](DECODO_EBAY_PILOT.md).

Before production activation, test: valid sold evidence; unsold completed listing; hidden Best Offer; wrong language/parallel/set; mixed raw and graded; lots and proxies; stale or future timestamps; currency/decimal parsing; unknown shipping; duplicate pages and repeated jobs; 429/5xx and bounded retries; auth/challenge response; malformed schema; credit cap; partial-run recovery; absent secrets; zero observations; replay without duplicate writes. Confirm access controls, secret redaction and unchanged inventory ownership.

## Validation performed

- Executed the deployed coverage SQL read-only against Supabase and captured the result.
- Executed the missing-reference selection read-only in the same statement/snapshot.
- Checked exact 89% integer arithmetic, 36 distinct reference identities, nine groups of four, and exclusion of already-priced and digital references.
- Checked live Railway variable names only and current GitHub/deployment identity during the audit.
- Added the bounded Decodo acquisition client, a plan-first CLI pilot and transport/parser tests using synthetic fixtures. No paid subscription, live scrape, database import or schedule has been activated. HTML compatibility and resulting coverage must still be measured against actual responses.

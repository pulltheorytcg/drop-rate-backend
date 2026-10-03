# Catalogue search performance — 2 October 2026

## Result

Ordinary card searches now select their result page before calculating reference values. The database can push filters into the released reference-card query rather than materializing the entire wide reference library. Direct game/search entry starts the product query independently of the game directory.

The changes retain exact printing/link logic, release-date gates, owner scoping, media permissions, prices, stable sorting and pagination. Price sorts still calculate values before paging so a cheap first page cannot hide more valuable results.

## Measured comparison

Read-only production `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` measurements compare the pre-change application at `f58f2f0f680a466569ad92ee360626ca2e12f952` with this query revision. Each median uses three warm runs per version, alternating which version goes first. No database settings, indexes, schemas or data were modified.

| Journey | Before, median | After, median | Reduction |
| --- | ---: | ---: | ---: |
| Game directory | 539.0 ms | 198.5 ms | 63.2% |
| Combined Naruto sets | 493.7 ms | 193.7 ms | 60.8% |
| Luffy name search | 510.7 ms | 87.4 ms | 82.9% |
| OP12-106 exact-number search | 529.2 ms | 98.1 ms | 81.5% |
| Exact grail printing | 517.4 ms | 185.8 ms | 64.1% |
| Pokémon first page | 724.0 ms | 224.9 ms | 68.9% |

These are database execution times, not full HTTP, mobile-network, image-download or user-task times. The measurement session uses an empty owner UUID to avoid conflating result retrieval with one person's inventory. The first cold directory sample took 3,615.7 ms; it is excluded from the warm comparison. Small repeated samples show a measured improvement, not a production latency guarantee.

The previous ordinary product query called `recognition_catalogue_reference_value` for all 463 canonical catalogue records, even when opening a single unmapped reference. A Luffy page now priced only its six linked canonical rows in the inspected plan; the exact-number and featured-reference plans required no canonical pricing calls. The top-page selection also eliminates the large pre-pagination window sort; ordinary browse no longer spills that sort before picking 41 rows.

## Correctness evidence

- Sixteen read-only full-row/order comparisons returned identical JSON for games, combined Naruto sets, name/number/key queries, first/next pages, name/number/value sorting, sealed products, empty watchlist, literal SQL-like search text, not-owned and empty-owned results.
- Three additional comparisons used an existing owner with inventory, selected internally without exposing their identity. Owned, not-owned and value-descending responses were identical, including 46 owned copies in each relevant 41-row page.
- Existing API tests continue to enforce current membership/founder roster access and owner-only inventory counts. No owner IDs are accepted from browser query parameters.
- 2,401 backend tests and all dashboard suites pass. Twenty catalogue UI scenarios include slow/failed metadata not blocking products, newer search results surviving late responses, reference unavailability, logout/navigation cancellation and idempotent intake retry.
- UI readiness is established through automated fixtures; this does not complete the manual's physical-card-to-Shopify or real-customer purchase timing tests.

## Implementation and rollback

### 3 October continuation verification

The interrupted patch was reconciled with production commit
`335d2d529aec02ab6867eb61bb59c1e9deead886`, retaining PR #506's filter navigation,
sheet dismissal and expired-session fixes. Its catalogue SQL is identical to
the original benchmark baseline. All 19 full-row and ordered-result comparisons
were rerun against the current 68,151-reference database in one read-only
statement; every comparison matched. This includes owned/not-owned filters and
value sorting using an existing owner's inventory, without exposing owner IDs
or writing test stock.

Three fresh alternating warm runs confirmed:

| Query | Before runs (ms) | After runs (ms) | Median reduction |
| --- | --- | --- | --- |
| Luffy search | 499.519, 499.916, 504.978 | 85.659, 88.604, 85.134 | 82.9% |
| Pokémon browse | 737.560, 732.980, 715.213 | 224.051, 223.705, 225.376 | 69.4% |

The combined source passes all 2,401 backend tests and the complete dashboard
suite (33 scanner, 20 catalogue, 37 workspace/session and 6 collector-journey
scenarios, plus founder workspace/accounts). These include uncertain-save
retries with the same idempotency key and the previously deployed filter fixes.
The backend tests required the normal runner outside the restricted sandbox,
which stalled asynchronous worker wakeups. The live browser shows the shared
sign-in page but has no authenticated session; real-account and physical-phone
acceptance remain open. CI and deployment evidence are recorded on the release PR.

`reference_base` projects only needed columns and permits PostgreSQL to inline it. Exact canonical links remain globally resolved under their existing full-identity rules. Non-price sorts select an ordered page, preserve its global ordinal, and use the canonical product's language for that page's price lookup. Price-sort behavior remains unchanged.

The client starts product retrieval without awaiting `/games`; slow or failed metadata cannot block an otherwise working search, replay it, replace newer results or restore a closed session. The frontend asset version is 7 in both hubs.

Application-only rollback: restore `335d2d529aec02ab6867eb61bb59c1e9deead886` (the current production version, including PR #506). There are no migrations, new services, cache invalidation dependencies or production writes.

## Reproduction

Generate SQL with `app.catalogue_browser.product_query`, `GAMES_SQL` and `SETS_SQL` at the before and after revisions. Bind identical owner/filter/sort/limit/offset values, use the same database snapshot for row comparisons, and compare `jsonb_agg(to_jsonb(row))` from materialized before/after query results. Keep ordering and the `ordinal` field in the comparison. Collect `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` plans sequentially after warming the data; alternate before/after order. Use an empty owner for anonymous aggregate timings and a separately authorized owner for ownership parity. Never create inventory to benchmark browsing.

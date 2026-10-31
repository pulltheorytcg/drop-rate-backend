Warning: truncated output (original token count: 58092)
Total output lines: 1822

## 31 October 2026 — Shopify Seller Hub launch-list contact mirror (prepared; disabled)

Added a consent-scoped customer contact mirror to the existing Seller Hub
waitlist. A distinct explicit disclosure/version gates export. Old prelaunch
opt-ins remain `NOT_REQUESTED` in Supabase, with no automatic Shopify sharing.
Server-side `customerSet` upserts by email and `tagsAdd` appends the
`Drop Rate Seller Hub - Launch List` segment without overwriting existing
customer tags, profiles or general marketing subscription preferences.
Postgres leases, retries and acknowledgement tokens keep the mirror safe when
Shopify is unavailable; Supabase stays the consent record. No launch emails,
theme publication or early seller-account marketing enrolment are enabled.

**Activation blocked:** Installed Shopify app's active version lacks
`write_customers`; updating its permissions/protected-customer-data approval
and the explicit `TCG_SHOPIFY_WAITLIST_SYNC_ENABLED=true` rollout remain
separate steps after code/CI and migration verification. See
[Seller Hub contact sync](docs/SELLER_HUB_LAUNCH.md#optional-shopify-customer-contact-mirror).

## 31 October 2026 — Seller Hub prelaunch registration (release in progress)

Built the existing Railway/FastAPI public landing at `app.droprate.co.uk`
(host-aware root and explicit `/seller-hub` route) with approved Drop Rate
Seller Hub artwork, prelaunch feature descriptions, a consent-based launch
list, and a clearly separate link to existing early seller account creation.
Invitation-token onboarding, founder root on the Railway origin, Seller Hub
auth and all commerce paths are retained.

Canonical Supabase migration `20261031190234_seller_hub_launch_waitlist`
creates a unique opt-in table with forced RLS, no direct `anon`/`authenticated`
or `tcg_api` table privileges, and a private validated/idempotent registration
function. No customer credentials or inventory are collected. Actual launch
emails remain off until sender, unsubscribe and delivery gates are approved.
No new Railway service, checkout change, store publication, n8n automation,
owner grant, stock or financial mutation is included. See
[the launch runbook](docs/SELLER_HUB_LAUNCH.md). CI, migration, production
deployment, Squarespace subdomain, Shopify live Sell With Us link and mobile
visual checks must be verified separately before claiming launch-list go-live.

## 30 October 2026 — Resumable R2 reference image migration

The existing API can now run the exact-reference image copier continuously in
bounded batches of 20, with four downloads at once and a single-writer advisory
lock. Both worker and apply flags are required. Every object is read back and
hashed before its current provider/printing/source link is recorded. Restarts
resume from durable mirror rows; failed sources back off. Signed R2 delivery
already exists in the catalogue UI, with original-source fallback.

The existing host scope covers Pokemon/Dragon Ball/One Piece. Naruto and the
CardTrader-sourced Pokemon images require the separate host-policy extension.
No success or bulk completion is claimed until deployed counts are read back.

## 30 October 2026 — R2 value-sort publication repair

Production generation 121595 has 161 independently verified objects but is not
published: seven parity cases pass and the value-sort query times out. The reader
now supplies the complete Railway-indexed R2 candidate population directly to
the live price/owner joins, avoiding repeated joins across five source arrays.
Canonical valuation uses the existing authorised resolver before the array-only
planner settings. No prices, ownership rules or pagination order are weakened.
Native PostgreSQL parity and deployed publication readback remain required.
See [the migration record](docs/R2_LIVE_CATALOGUE_20261030.md).

## 30 October 2026 — Complete R2 catalogue delivery prepared

PR #799 passed CI, was merged, and deployed with build enabled and delivery off.
Its first publication validation timed out because JSON row counts produced a
nested-loop plan. The follow-up adds statement-scoped planner settings and a
70,000-card/50,000-price PostgreSQL regression. No incomplete publication was
activated; API health and ordinary catalogue reads remain available.
The second attempt verified all 161 objects but still hit a JSONB query timeout.
The follow-up uses compact column bindings and hash joins; a production read-only
plan completed in 2.71 seconds. Delivery remains gated on final live parity.

The new whole-catalogue R2 path covers games/sets, card browsing and searches,
sealed products and comic/manga catalogue identities. A private generation
record invalidates old objects atomically on source edits; complete verified
publications feed the existing SQL rules and live owner/pricing overlays.
Source rows, inventory, Store Prices, Shopify and archive automation are retained.
This delivery change does not itself reclaim Supabase disk space.

Local SQL parity and failure/access-control checks pass on PGlite PostgreSQL
18.6. Native PostgreSQL 17 CI, migration, deployment and production readback
remain release gates. Both new feature flags default false. See
[scope, rollout and verification](docs/R2_LIVE_CATALOGUE_20261030.md).

## 29 October 2026 — Pricing repair deployed; later Masters aliases and accurate coverage readback

PR #781 is merged and both API/worker deployments reached SUCCESS. The live
860-request continuation is `503d9c3f-b368-498c-89b7-6ffef19be279`; inspect
its durable receipt before acting. At 08:01:47 UTC it was running at 280 calls
with zero accepted prices. Inventory remains 616 unchanged rows.

Five later Masters releases now have exact official short-name aliases,
bringing the reviewed map to eleven releases. Local focused validation passes
383 tests; this extension requires normal CI before the next run. Do not
replace the active pinned worker to apply it midway through execution.

The new [coverage SQL](docs/evidence/market_coverage_20261029.sql) counts valid
asking estimates without double counting existing guides. Verified coverage
is 43,454/67,066 (64.7929%), target 59,689, gap 16,235. Read the
[full deployment, evidence and continuation handoff](docs/REFERENCE_ASKING_DETAIL_RECOVERY.md).
The existing hourly continuation task has been updated; source limits,
printing identity, daily budgets and physical inventory protections remain.

## 29 October 2026 — Full details verified; final normalization and resumed allowance

The repaired worker completed a second 100-call verification slice with 42
searches, 58 full listing details and zero accepted prices. Actual details
confirm missing language/finish evidence and some condition conflicts. The
daily ledger is 1,140/2,000; the next continuation has at most 860 calls.

Final normalization fixes accept explicit Non-Holofoil and deduplicate equal
item-specific values while preserving contradictions. Unresolved suffixed
Masters printings are excluded before search, and the bounded receipt shows
different actual rejection reasons. All 348 focused tests pass locally; normal
CI must pass on this final head before execution. Prior head passed 8,269
backend tests and all six other applicable checks and deployed successfully.

Coverage remains 43,454/67,066 (gap 16,235 to 89%); no gain is claimed from
requests or tests. Resume run `d5722b11-ec47-4a16-b075-6cc05d5f2054` using the
same English/apply scope. Full evidence and cursor are in
[the detail recovery runbook](docs/REFERENCE_ASKING_DETAIL_RECOVERY.md).

## 29 October 2026 — Live detail canary completed; printing-specific follow-up

The repaired worker completed a 40-request canary: 26 searches, 14 actual
listing details, zero provider failures and zero accepted prices. It exposed
unresolved Masters promotional identifiers and a negative grading sentinel.
The follow-up skips unresolved specials before search, accepts the explicit
ungraded wording and retains more useful detailed rejection evidence.

Local focused validation now passes 322 tests. The previous head passed all
applicable CI including 8,264 backend tests and deployed to the dedicated
worker. The follow-up requires its own CI before execution. Today's durable
ledger is 1,040/2,000 requests. Coverage remains 43,454; an independently added
reference makes the current denominator 67,066 and the remaining gap 16,235.
See [the live receipt](docs/REFERENCE_ASKING_DETAIL_RECOVERY.md).

## 29 October 2026 — Recover complete listing evidence after zero-yield batch

The first cloud run finished at 00:36 UTC with 1,000 charged searches, 513
summaries and zero accepted prices. It preserved its cursor and quota ledger.
Last verified coverage remains **43,454/67,065 (64.7939%)**, gap **16,234**.

The follow-up reads complete official eBay item details, structured condition
descriptors and Bandai's documented former Masters game name. Discovery no
longer requires language in the title; exact-language and printing checks
remain. Search and detail requests share the same durable limits and pacing.
`--max-queries 1000` caps total Browse calls, including details, so fewer than
1,000 distinct cards may be checked. No arbitrary values are introduced.

Six verified Masters releases also accept their official short set names.
Local focused validation passed 317 tests. Normal CI, reviewed deployment and
live readback remain required; no new price gain is claimed from code alone.
See [detail recovery and live continuation](docs/REFERENCE_ASKING_DETAIL_RECOVERY.md).

## 29 October 2026 — First 1,000-check batch running in the cloud

Resolved the laptop command-session dependency by launching the existing
pricing operator in a dedicated Railway worker, pinned to the tested release.
Deployment `c40c993b-1335-4582-83f3-ea6d46224834` succeeded; durable run
`ce1f435a-3a1c-4a94-889d-8fe887da7147` started at 00:16:32 UTC in apply
mode for at most 1,000 English checks. At 00:17:42 UTC it had reserved 55
requests and collected 54, with zero accepted estimates so far.

The worker has no scheduler, automatic restart or public endpoint. Progress
and quota reservations persist in PostgreSQL; the stable run ID prevents a
new batch on an accidental restart. Existing API/storefront services were not
reconfigured. See [the cloud runner receipt and recovery procedure](docs/REFERENCE_ASKING_CLOUD_RUNNER.md).
The run is active; no final result or coverage increase is claimed yet.

## 28 October 2026 — Larger reference-pricing batches

PR #778 implements 1,000–2,000 eligible eBay Browse checks per run, with a
2,000-request global UTC-day budget. Candidate scans use 100-row pages and a
20,000-reference ceiling. Quota is refreshed every 100 attempts; a durable
reservation marker preserves the 500-request provider headroom across restarts
and UTC-day changes. Collection remains sequential at one request per second
and stops after 45 minutes with a resumable cursor.

Validation at commit `7fdd4fa41239aa0d2e2d60240c51933fb5bf49b9`: all three
applicable workflows passed, including **8,169 backend tests** (18 skipped),
dashboard/n8n checks, shared-inventory consistency and the real PostgreSQL
500-to-2,000 migration/concurrency/permission contract. Independent review found
stale quota reuse across invocations; the implementation now carries a global
reservation anchor across runs and conservatively accounts for legacy receipts.

Applied `20261028235621_reference_asking_budget_2000.sql`. All three existing
run records and 30 charged requests have the identical before/after ledger
snapshot `e3e748c71f7561ad6371a27e7eb6fb03`; no asking prices were added.
The migration preserves history, audits and RLS. Exact identity, language,
shipping and seller requirements remain unchanged. Larger batches are search
capacity, not a guarantee of accepted prices.

The planned first 1,000-check live batch has **not started**. The local operator
session disconnected; the cloud connector can manage deployment but does not
provide an authenticated command runner. Inspect the durable run ledger before
launching or resuming. Last verified catalogue coverage is
**43,454/67,065 (64.79%)**, leaving **16,234** records to reach 89%.

## 28 October 2026 — Recovered pricing rollout and Black Bolt source matching

PRs #774, #775 and #776 are merged and live. The latest code deployment is
`89ed3d11e501364e2cede8f26e1d4d04dee478d2`; readiness is healthy.
All four applicable final CI workflows passed, including 8,147 backend tests
(18 skipped), dashboard checks, artwork preservation and the real PostgreSQL
repair rollback contract.

Corrected all 174 Japanese Black Bolt collector fractions from /174 to /086
with 174 immutable old/new audit records and an importer guard against the
stale upstream API. A scoped five-request dry run then five-request apply
recovered **92** eligible Cardmarket catalogue guides. Exact full-set printing
checks rejected 80 ambiguous fractions and two missing guide prices.

Coverage is **43,454/67,065 (64.79%)**, up from 43,362 (64.66%). The 89% target
is **not met**: **16,234** additional records are still needed. Three bounded
eBay pilots used 30 Browse searches and accepted zero asking estimates;
shorter retrieval queries recovered listings while identity/language checks
remained strict. All 616 physical inventory records have an identical
before/after snapshot, including ownership, costs and selling prices.

Receipts, primary evidence and remaining source/mapping constraints:
[SV11B live recovery](docs/SV11B_NUMBER_RECOVERY.md) and
[asking-price pilots](docs/REFERENCE_ASKING_BACKFILL.md).

## 28 October 2026 - Current-listing estimates and bounded backfill

Recovery validation: all eight GitHub workflows passed on `999c6530`, including
8,104 backend tests (18 skipped), dashboard UI and both native PostgreSQL
contracts. The deployment tool applied `20261028224708_reference_asking_prices`;
readback confirms forced RLS and no direct anon/authenticated access. Deployment and three bounded live batches are complete; the asking pilots
accepted zero estimates. The separate reviewed SV11B repair recovered 92
existing-source guides, as recorded in the latest section above.

The 22:04 UTC read-only audit measured **43,362 / 67,065 (64.66%)** supported
references/labelled guides; **16,326** additional records are needed for the
**59,688** threshold. No coverage gain is attributed to this implementation.

Adds a separate, explicitly labelled eBay asking-price estimate for missing
catalogue references. Exact identity, language, raw NM/Mint condition, finish,
three independent sellers, known delivery costs, robust statistics and a
three-day expiry are required. Postage uses the configured shop postcode as a
delivery benchmark, never a customer's checkout quote. Existing physical-card
valuations, store prices and settlements retain their current rules.

The operator backfill is explicit and resumable, with durable request
reservations, provider quota checks, a 500/day application-side ceiling,
database-capacity checks, immutable evidence and atomic cache/audit writes.
There is no new Railway service, subscription or unattended schedule.
Reference-only coverage remains available separately from coverage including
asking estimates. Migration, final CI, deployment and live batch results are
recorded in the associated PR before reporting this as active.

See [current-listing rollout](docs/REFERENCE_ASKING_BACKFILL.md) and
[database contract](docs/REFERENCE_ASKING_DATABASE_CONTRACT.md).

## 28 October 2026 - Decodo eBay acquisition pilot prepared

Verified **43,279 / 67,065 (64.53%)** at 19:39 UTC; **16,409** additional
references are required for 89%. Added a separate Decodo Web Data API client,
a 36-reference diagnostic manifest, reproducible read-only coverage SQL and a
plan-first CLI. The client caps requests at 10/second and 200/run; the CLI starts
at 1/second and 72/run and stops on provider, access-gate or schema errors.

The founder instructed proceeding with Decodo while handling the eBay permission
request separately. The remaining execution input is `TCG_DECODO_API_KEY`.
No live scrape, new valuation, database write, subscription or schedule has been
activated. Search results remain evidence for review until exact matching and
live payload validation justify production imports.

See [pilot usage and validation](docs/DECODO_EBAY_PILOT.md) and the
[source evaluation](docs/MARKET_COVERAGE_SOURCE_PILOT_20261028.md).

## 28 October 2026 — One Piece numbered-title recovery under verification

The current measured coverage remains **43,277 / 67,065 (64.53%)**, requiring
**16,411** additional supported prices for the 89% goal. Fresh One Piece bulk
exports do not add safe candidates under the existing exact matchers.

A narrowly scoped English base-title matcher accepts the provider's documented
own-number suffix only with agreeing Cardmarket title/URL and base-version
evidence. Existing collision, release, rarity, quota and write protections
remain. Local tests pass after correcting a workspace-only transport dependency;
normal CI and live source/deployment verification remain required. No new
coverage is attributed to this candidate change. See the
[matching contract](docs/ONE_PIECE_NUMBERED_NAME_RECOVERY_20261028.md).

## 28 October 2026 — 89% physical-card pricing goal and importer recovery

The founder's current coverage target is **89%**, using the unchanged full
physical-reference denominator and supported dated price/guide rules. The
10:07:18 UTC production receipt records **43,269 / 67,065 (64.52%)**, requiring
**16,419** additional priced references to reach the exact **59,688** threshold.
The 61-reference gain since yesterday belongs to existing scheduled work.

This repair lets expired positive detailed caches re-enter One Piece/Dragon
Ball source checks, revisits the Japanese Pokémon adapter's own older guides,
and accepts the provider's documented negative Cardmarket-only set IDs. Exact
release/collector/printing gates remain unchanged. Bounded rejection diagnostics
and an opt-in three-call source probe separate provider shape from real quote
coverage. PokéWallet's last-price-change timestamp remains distinct from the
successful fresh observation date; failed calls never renew evidence.

The local focused suites and native PostgreSQL persistence checks passed.
Normal exact-head CI, deployment and live source/coverage verification remain
required and are recorded in the associated PR. These code and reporting
changes alone do not establish any new priced references or meet the target.
See the [recovery contract](docs/PRICING_89_PERCENT_RECOVERY_20261028.md) and
[measured baseline](docs/evidence/pricing-89-baseline-20261028.json).

## 27 October 2026 — Ordinary eBay discovery works; publication-date alias repair

PR #768 deployed successfully as `19c140e50a09cf38d6ae3d8f755fcc94fe4757b7`.
All three normal CI jobs passed, with **7,657 backend tests**. At 22:00 UTC the
ordinary ISBN lookup found two source offers in seven Browse calls, including
the independently checked New paperback at **£13.20** with free quoted postage.
Both exact returned photos decoded under the production image policy.

Independent source-page review found that the cheaper candidate declares
`Date of Publication: 2007-09-03`, conflicting with the canonical 2003 year.
The matcher had checked only `Publication Year`. Activation is held while the
equivalent date fields are added to the same conflict gate and diagnostics.
The new offer has no conflicting date; absent date metadata remains distinct
from a stated conflicting date. No prices, media or catalogue records were
written. See the [ordinary lookup and source review](docs/evidence/book-ebay-normal-search-date-review-20261027.json)
and [exact returned photo checks](docs/evidence/book-ebay-normal-search-images-20261027.json).

## 27 October 2026 — Live eBay book offer verified; discovery expansion pending

PR #767 is deployed as `cd23bce9ac2c03bb60e65debbb17573f71f23f8e`.
All three applicable checks passed, and normal Railway gates passed **7,640
tests**. The official Browse probe accepted Naruto volume 1, ISBN
9781569319000, at **£5.03** in Good condition with zero quoted postage.
Its returned listing photo decoded in Chromium and visibly matches the title
and volume. This is an ACTIVE asking-price reference, not a sold market value.

The normal first-ten-result search omitted that offer. Its three selected
details were correctly rejected for a conflicting publication year, no explicit
physical binding, or missing ISBN. A fifty-result GTIN check returned only
fifteen results and still omitted the reviewed offers; exact ISBN13 and ISBN10
keyword checks returned thirty-five and thirty-three and found both. The next
release uses one documented ISBN keyword query and progressive detail checks
within the same seven-call bound. Display remains disabled pending its normal
live lookup. No catalogue, inventory,
market, media or financial records were written. See the
[actual offer and discovery receipt](docs/evidence/book-ebay-discovery-gap-20261027.json)
and [returned photo check](docs/evidence/book-ebay-naruto-image-delivery-20261027.json).
The [search comparison](docs/evidence/book-ebay-isbn-search-comparison-20261027.json)
records the source discovery gap without treating summary prices as quotes.

## 27 October 2026 — eBay book identifier compatibility follow-up

PR #766 is deployed successfully on API release
`27d746c03ebe203e2458d159cb073ffe67932ef9`. Public health and assets match the
reviewed release, and all four previously blocked covers load using its actual
image policy. All seven PR workflows passed; Python CI and Railway each passed
7,550 tests, with 18 optional skips and one warning.

The first live Naruto probe confirmed official Browse access with four calls,
ten summaries and three examined details. None exposed an ISBN through the
initially supported fields, so no quote was accepted and the display stayed
disabled. The temporary probe command was removed after the run.

The follow-up reads documented nested PRODUCT identifiers/aspects and supports
a conditional COMPACT identity check tied to the same item and seller revision.
It ranks the ten returned summaries before spending at most three detail slots.
Normal requests remain bounded to seven Browse calls, and explicit pinned-item
diagnostics require at most two. Conflicts still reject the quote; no sold or
physical values are created. Activation requires a usable live source result.
See [the contract](docs/BOOK_EBAY_LISTING_CONTEXT_20261027.md) and
[the first source result](docs/evidence/book-ebay-first-production-probe-20261027.json).

## 27 October 2026 — Book image redirects and eBay asking-price context

The remaining artwork audit found an actual browser policy failure: four of
twelve sampled medium Open Library covers redirect through Internet Archive.
The corrected image policy loads all four in a real Chromium before/after
comparison (zero before, four after). Other resource policies remain unchanged;
this sample is not an assertion of full catalogue coverage.

An opt-in, authenticated catalogue endpoint and display now provide exact-ISBN
active eBay listing context through the official Browse API. Prices are labelled
asking prices, with source condition, links and postage information. Matching
listing photos can replace a failed source image and remain labelled references.
The integration is bounded, cached, read-only and independent of sold pricing.
It defaults off pending the bounded production provider probe. No book sold
values, inventory values, physical printing status or approved media are created.

See [the feature contract](docs/BOOK_EBAY_LISTING_CONTEXT_20261027.md) and
[the real cover redirect check](docs/evidence/book-cover-redirect-browser-20261027.json).
The associated PR records normal CI, deployment, provider and activation results.

## 27 October 2026 — Comic/manga cover references and ISBN price matching repair

The new book catalogue contained metadata without an artwork display path for
its Open Library imports. This release adds a separate, attributed community
cover reference in catalogue browsing, book selection, saved collections and
the founder inventory grid. It verifies the exact unchanged import and provider
mapping before returning a direct, lazy source image. Existing publisher/copy
images keep priority; community references do not become approved media,
recognition evidence, physical-printing proof or R2/Shopify assets.

A read-only run of the new helper over all current source rows accepted 1,540
edition references: 767 manga, 547 other comics, 130 Marvel and 96 DC. There are
1,541 Open Library-sourced editions; the 1,542 mapping count includes a mapping
to an already publisher-sourced edition. The known wrong-language/wrong-volume
cover on OL9465913M is excluded. These are eligible source lookups, not a claim
that 1,540 images have loaded or are correct. Six bounded source checks returned
five decodable JPEGs and one 404; four images agreed with the visible title and
volume, and the fifth produced the exclusion. The UI labels community images
as cover references and handles missing images without another-edition guesses.

Book sold-price matching now recognises an exact hyphenated ISBN without
mistaking it for a multi-volume range or a publication year. Wrong/extended identifiers, real bundles,
different printings, duplicate sales and condition/grade mismatches remain
rejected. The actual v4 price calculation produces the same result for plain
and formatted ISBNs in the five-sale regression. This repair does not create
book prices or change the valuation policy.

The 19:49 UTC live readback still contains zero book market observations and
zero positive shared book snapshots. The latest recorded provider usage is
zero remaining out of 250, with its recorded reset on 1 November; subsequent
provider responses are 429 and the existing pause next checks at 20:34 UTC on
27 October. Imported editions remain STRUCTURED. No source retry, invented
printing verification, retailer-price substitution or production data write
was used to fill missing values.

Integrated focused artwork/market tests passed 85 checks; the full JavaScript
DOM command passed, including five new cover behavior groups. The release also
refreshes the founder catalogue script version and keeps attribution compact.
Normal protected-branch CI and deployment verification remain the release gates;
their exact results are recorded on the associated pull request. See the
[cover contract](docs/BOOK_COMMUNITY_COVER_REFERENCES_20261027.md) and
[dated source/provider evidence](docs/evidence/comic-manga-artwork-values-20261027.json).

## 27 October 2026 — Founder import migration installed and rebuild enabled

The import-specific connector blocker is resolved. After a fresh read confirmed
the function and ledger entry were still absent, the exact reviewed migration
from [PR #760](https://github.com/pulltheorytcg/drop-rate-backend/pull/760) was
installed through the governed Supabase migration tool as
`20261027192257_founder_import_preview_rebuild`. The 19:23:15 UTC preflight
readback verifies unchanged role attributes, table and column privileges,
RLS, private-schema permissions, import policies and candidate audit trigger.
The function identity read at 19:23:30 UTC confirms the reviewed body SHA-256
`2b4bc9cd72b3246992b7304befd58322ebbfdf4bd939493530904b3267b83db7`,
owner `postgres`, fixed `search_path=pg_catalog`, two-second lock timeout and
execution restricted to `postgres` and `tcg_api`. Advisor findings are unchanged.

The migration blob is identical at the reviewed PR head, its merge, the deployed
API release and current main. All four original PR workflows passed, including
the native PostgreSQL 17.6 rebuild suite; no replacement migration or broader
database permissions were introduced.

`TCG_IMPORT_PREVIEW_REBUILD_ENABLED=true` is configured. Targeted API deployment
`20131280-07c8-474e-8932-2a0df29baf71`, on the already successful release
`fb19e7e8477779577736d90e745ddc171374627a`, reached **SUCCESS at
19:26:37.659 UTC**. Its normal predeploy suite passed **7,256 tests, 18 skipped,
1 warning** in 23.99 seconds at 19:25:56.352; the new runtime logged
`GET /health/ready` **200 OK at 19:26:32.903 UTC**. This is a deployed and enabled
capability, with authenticated founder acceptance still outstanding. No production
batch was rebuilt, no historical import was replayed and no inventory copy was
created. The live founder UI check needs the originating browser session and
original source file; deployment readiness alone does not establish that result.

The normal DR94 media command returned HTTP 200 at 19:00:04.503 UTC; storage
health returned 200 at 19:00:24.483 and heartbeat at 19:00:34.195. This verifies
the scheduled command response, not new image counts or durable receipt fanout.
The current mirror registry still contains 401 verified entries; the latest
mirror verification is dated 26 October at 23:18 UTC.
The production eligibility query at 19:30:30 UTC returned zero eligible approved assets
awaiting mirrors. DR93/94 validate command responses without invoking DR91, so
these successful schedules do not establish production receipt fanout. See the
[runtime readback](docs/evidence/runtime-continuation-readback-20261027.json).
The weekly Drive copy remains disabled pending its existing OAuth and bounded
live-copy requirements. Catalogue coverage is not changed by this migration.

An independent read-only catalogue checkpoint at 19:34:16 UTC reports
43,208/67,065 physical references with supported values or labelled guides
(64.43%), retaining exact Pocket exclusions, seven-day price-row eligibility
and identity gates. That is 73 more
than the 12:04 checkpoint under existing background jobs; 17,151 additional
priced references are needed for 90%. Artwork URL presence is 60,283/67,065
(89.89%); measured core fields, artwork URL and value together are 38,992/67,065
(58.14%). URL presence is not load or printing verification. The 19:36:26 book
readback still has 785 comics and 805 manga, with no positive shared market
snapshots and no verified product profiles. Database size is 370,740,371 bytes.
See the [dated catalogue evidence](docs/evidence/catalogue-continuation-readback-20261027.json).

See the [activation evidence](docs/evidence/import-preview-rebuild-activation-20261027.json)
and [current completion sequence](docs/DROP_RATE_COMPLETION_PLAN_20261027.md).

## 27 October 2026 — Automation database repair and live heartbeat recovery

Supabase SQL reads are responding again. The reviewed automation migration from
[PR #762](https://github.com/pulltheorytcg/drop-rate-backend/pull/762) is installed
as `20261027173335_automation_control_runtime_repair`. Catalogue readback at
17:57:21 UTC verifies both control functions against their reviewed body hashes,
signatures, owners, settings and restricted execution grants. Table privileges,
RLS and required index shapes are unchanged. The import migration has a separate
remaining connector failure, described below.

The API remains on `fb19e7e8477779577736d90e745ddc171374627a`, deployment
`a91487a5-7e2b-42d8-809b-0439fdb01562`, which reached SUCCESS at 17:05:20 UTC
after **7,256 passed, 18 skipped, 1 warning** and readiness 200. The earlier
Railway BuildKit failure did not recur. Native PostgreSQL 17.6 regressions also
passed with the captured production audit function and schema details overlaid
in disposable local databases. Those checks used synthetic data and did not
execute production business writes.

Heartbeat recovery is **Live verified**: the first accepted scheduled execution
was `41` at 17:45:34 UTC; the durable row advanced to execution `43`, count `3`,
received at 17:55:34.490942 UTC. The ordinary R2 storage-health schedule then
returned HTTP 200 at 18:00:23 UTC, followed by heartbeat HTTP 200 at 18:00:34.
DR91 publication was independently verified at 17:55:12 UTC with a verified
SQLite backup on successful n8n deployment
`d20f969c-e663-4f84-b1ba-8546f908dfa2`; its one-time publication flag is cleared.
DR94 approved-media publication was verified at 18:02:25 UTC, with another
verified backup, on n8n deployment `73b85d89-b5a5-4931-bd16-eef34757c1cc`
(SUCCESS at 18:02:42.855). Independent metadata confirms all five DR90–94
definitions are active/published and match source. All six one-time boot
mutation flags were cleared with `skipDeploys:true`. The first normal DR94
opportunity is 19:00:03 London time (UTC on this date); its scheduled execution
and live receipt fanout have not yet been observed.

The R2 source archive is complete: fourteen reviewed files, 6,228,589 source
bytes, with the earlier 14:14:49 UTC `BYTES_VERIFIED` receipt. A fresh, deduplicated
cache checkpoint from the current deployment's 17:05–17:26 UTC warming logs is
**100 sets / 14,297 references / 855,888 compressed bytes**. This is partial
reference-input coverage, not the whole catalogue or additional database space.

Founder preview rebuilding remains **Deployed, not enabled**. Two resumed
governed import-migration attempts returned `Invalid or expired requestState`.
The 17:57:21 UTC catalogue/ledger read confirms its function and migration are
absent; the final migration list contains 136 entries, including only the
automation repair of the two pending migrations. Existing advisor warnings are
unchanged. `TCG_IMPORT_PREVIEW_REBUILD_ENABLED` remains false; no further retry
or import replay was made. Weekly Drive transfer also remains disabled: native n8n
Google OAuth is absent, and real receipt acceptance plus a bounded actual
create/download/readback remain activation requirements. Existing source holds,
historical imports, catalogue coverage counts and customer records are preserved.

See the [recovery evidence](docs/evidence/automation-import-recovery-20261027.json)
and [current completion sequence](docs/DROP_RATE_COMPLETION_PLAN_20261027.md).

## 27 October 2026 — R2 source archive and n8n runtime inspection

The founder authorized addressing the remaining work one item at a time.
The first bounded release adds a private, hash-pinned archive of fourteen
recovered book source/audit artifacts (6,228,589 source bytes), preserving the
1,495 historical imports, 909 deferred records and 57 exact review holds.
Every upload and the final manifest require actual remote-byte verification.
The existing catalogue worker can run this after pricing with daily success
and hourly failure bounds; its flag defaults off.

A separate optional n8n startup inspector reads stored/published workflow
metadata and Google Drive credential id/name/type only. It never reads tokens,
changes stored workflows or publishes schedules. Source DR92/DR93 now link the
existing error handler; actual stored definitions still require verification.

Implementation/offline checks are complete for these bounded components;
current-head CI, deployment, flag activation and runtime/storage readback are
separate pending gates. Full R2 catalogue delivery, broad artwork migration and
weekly Drive transfer are not claimed complete. See the
[completion sequence](docs/DROP_RATE_COMPLETION_PLAN_20261027.md) and
[source archive contract](docs/R2_CATALOGUE_SOURCE_ARCHIVE_20261027.md).

## 27 October 2026 — Recovered book pipeline and historical comic image correction

The interrupted final workspace is recovered: all code, workflow, tests and
data match their saved checksums (20 of 21 manifest files; only the runbook had
subsequent completion documentation). Existing PR #751 now carries the final
book import safeguards, exact review registry, original subject audit, immutable
snapshots and all 30 committed production receipts. No import is replayed.

The continuation preserves a review hold by ISBN or source ID, rechecks old
cached reviews, and adds an offline integrity gate over the already imported
1,495-edition cohort. All 909 additional candidates remain deferred after a
focused review found six possible form conflicts. The image route also stops
rejecting the five identified historical publisher comic references merely
because their exact release date is NULL; strict past-year and existing
publisher/identity/digest checks still apply.

Release state: **LIVE**. PR #751 merged as
`e79ca7efadf6aa396e214ce93864052f6c43c472`. All seven current-head workflows
passed: 7,047 backend tests plus the dedicated 80-case import/artwork suite
with isolated PostgreSQL enabled. Railway deployment
`39868c24-1d43-431d-a665-c3dcd06598a3` is **SUCCESS** at 12:50:44 UTC; its
normal predeploy suite passed 7,047 tests, startup completed, and the new
runtime logged readiness **200 OK at 12:50:41 UTC**.
See the [release receipt](docs/evidence/catalogue-recovery-release-20261027.json).

Detailed Supabase SQL reads stalled in this continuation. The last exact
coverage checkpoint remains 12:03–12:04 UTC, and no newer percentage is claimed.
No live authenticated owner image request is claimed; the actual SQL and all
five reviewed identities passed the focused SQL/route tests.
No provider, quota, scheduler revision, schema, inventory, ownership, market
value or Store Price is changed by this code release. Auction scanning remains
design only. See [recovered handover](docs/CATALOGUE_RECOVERY_20261027.md),
[file integrity](docs/evidence/book-recovery-file-integrity-20261027.json) and
[deferred review](docs/evidence/book-deferred-review-20261027.json).

## 27 October 2026 — Card fixes live; 1,495 book editions imported

PR [#752](https://github.com/pulltheorytcg/drop-rate-backend/pull/752) is merged as
`7f98b9c803daec7bad8a404000f0ed2cac8e6f89`. All four current-head workflows
passed, including **6,985 backend tests**. Railway deployment
`ad845201-ebaf-4d56-aa9c-1953742c2ea8` is **SUCCESS**; its normal predeploy
suite passed the same tests and the new runtime logged readiness **200 OK at
12:15:22 UTC**.

The release preserves reviewed M1S artwork through provider refreshes and adds
bounded exact-number recovery for explicitly truncated Dragon Ball searches.
Existing source permissions, quotas and scheduler revision remain unchanged.

Already committed and independently read back: **92 Japanese Pokémon artwork
repairs**, **one exact VIZ manga cover**, and **1,495 comic/manga metadata imports
in 30 batches**. All three durable run receipts are COMPLETE. Live totals at
12:03–12:04 UTC: **785 comics + 805 manga = 1,590 editions**, **43,135 / 67,065
physical cards priced or carrying labelled guides (64.32%)**, and **38,919
(58.03%)** with basic identity, artwork URL and a supported value/guide together.
Physical artwork URL coverage is **60,283 / 67,065 (89.89%)**. The 90% pricing
goal remains unmet by **17,224 references**.

**Books still have zero positive shared market snapshots** and zero VERIFIED
profile identities. Metadata growth is not complete artwork/printing/value
coverage. Inventory remains 616 rows; the completed imports preserved its
full-row checksum. Database size at readback is 370,625,683 bytes, writable and
below the unchanged 400,000,000-byte guard.

**Remaining release blocker:** the coding workspace disconnected before the
final book subject-preservation/57-hold-registry patch and review datasets were
uploaded. Draft PR [#751](https://github.com/pulltheorytcg/drop-rate-backend/pull/751)
preserves the earlier version. Recover final local files before releasing that
pipeline; do not rerun the already committed 1,495 imports. Another 909 novel
records were staged, not imported. GitHub/Supabase/Railway connections still work.

The live auction scanner is **design and research only, not implemented**.
See [current production checkpoint and resume order](docs/CATALOGUE_RECOVERY_20261027.md),
[machine-readable evidence](docs/evidence/catalogue-recovery-readback-20261027.json)
and [scanner proposal](docs/LIVE_AUCTION_SCANNER_PROPOSAL.md).

## 27 October 2026 — Catalogue scheduling fixes deployed and verified

PR [#749](https://github.com/pulltheorytcg/drop-rate-backend/pull/749) is merged
as `674bcb56d4df35420e6bba3c6b01c6bffa16f72a`. Railway API deployment
`95ca326e-10cb-4030-8a55-262be89b6fde` reached **SUCCESS**; public readiness
returned **HTTP 200**, with the database connected. All **6,924 backend tests**
passed locally and during deployment; all eight GitHub workflows passed on the
corrected PR head.

Existing hourly price jobs now precede daily metadata, provider failures record
INCOMPLETE, and discovery receipts distinguish newly added set identities from
refreshes. The prepared TCGCSV importer rejects additional variant collisions
and reports verified committed writes rather than attempted writes.

TCGCSV remains **disabled**, with zero source-tagged price rows. Its upstream
commercial permission is unresolved; free access and passing technical checks
do not clear that hold. The existing approved-source jobs remain active. The
hourly **Drop Rate Catalogue Watch** now explicitly carries the source hold and
committed-count rule; the separate archive watch is unchanged.

The live database readback at **10:25 UTC** contained a **10:07 UTC** coverage
receipt: **43,033 / 67,065 physical cards (64.17%)**. This is 71 more covered
references than the previous handover, from existing imports before this release.
The user's 90% target remains unmet: **17,326** additional supported values or
labelled guides are required. The 2,480 digital Pocket references remain excluded.

A separate **10:32 UTC** intersection query found **38,819 / 67,065 (57.88%)**
with basic identity fields, an artwork URL and a supported value/guide on the
same record. This is core data presence, not full image/printing verification.

Artwork URLs remain missing for **7,033 / 69,545** references. Approved R2 media
has **401 verified mirrors and zero eligible backlog**; the broad reference-image
mirror count remains zero. Comics/manga remains at **95 editions (37 comics,
58 manga)**. Neither category has a positive shared catalogue market snapshot;
**0%** of these imported editions has identity, cover and supported value complete.
R2 history
has **39,542 verified rows across 20 archives**. Database size is **357,608,595
bytes**, writable and below the unchanged 400,000,000-byte guard.

Four of the ten previously pending Fusion SB01 guides were filled by the existing
importer; six remain. Railway's approval step declined the separate one-off
preview, reporting that approval was not granted. The normal predeploy checks
were restored before the successful scheduler release. No manual price addition
or new-feed activation is claimed for this continuation.

See [verified production checkpoint and resume order](docs/CATALOGUE_CONTINUATION_20261027.md)
and [source rules and automation runbook](docs/FREE_CATALOGUE_AUTOMATION.md).

## 26 October 2026 — Catalogue recovery deployed and verified

The live implementation pass added **480 supported card values/guides**, restored
**3,331 missing artwork links**, expanded comic/manga edition metadata from
**48 to 95**, and cleared the approved R2 queue: **401 verified mirrors, zero
eligible backlog**. Actual catalogue-query signing and private image delivery
passed HTTP/WebP/SHA-256 verification.

Final physical-card pricing coverage is **42,962 / 67,065 (64.06%)**. The user’s
90% target is **not achieved**: 17,397 additional supported values are required.
Coverage includes explicitly labelled marketplace guides, not just
condition-specific UK sold comparables. The 2,480 documented Pokémon Pocket
digital references remain excluded consistently. Sealed guides cover
2,740 / 3,890 (70.44%).

Artwork URLs are populated for **62,512 / 69,545 references**; **7,033 remain
blank**. Every newly repaired image was decoded and verified, but this does not
assert that every pre-existing external URL loads. The 95 book editions contain
reviewed factual metadata; comprehensive books, covers and values remain open.

PRs #736–#747 implement source-date preservation, bounded hourly refresh order,
exact display/mapping repairs, reviewed book imports, safe R2 backfill, exact
Hidden Fates/Generations/OP-16/Fusion guides and explicit V1 foil selection.
The final backend suite passed **6,880 tests**, dashboard checks and n8n build;
independent reviews cleared source/variant and operator safeguards.

The final foil import committed **36 of 46 previewed guides** before the
existing provider `SHARED_QUOTA_LOW` guard stopped it. Ten SB01 guides remain
unapplied. Their identities and durable complete/incomplete receipts are saved
in the implementation report. No quota bypass or paid feed was introduced.

Normal deployment `cef03cbd-f59b-4815-abbc-22b9cc19abf6` is **SUCCESS**, readiness
**HTTP 200**, with the original predeploy checks restored and no one-off import
command. All 616 inventory rows retain their full-row checksum. Current prices,
ownership and Store Prices remain authoritative in Supabase.

Private R2 history contains **39,045 verified rows across nine archives**.
Database size is **356,215,955 bytes**, below the unchanged refresh guard.
Recurring DR94 remains inactive pending actual scheduler/error-routing proof;
the broad reference-image cache remains source-permission gated.

See [production receipts, final counts and resume order](docs/CATALOGUE_COMPLETION_RUN_20261026.md)
and [machine-readable checkpoint](docs/CATALOGUE_COMPLETION_COUNTS_20261026.json).

## 26 October 2026 - R2 history archival live verified

PR #734 is merged as 8f5bf7955bf8a825c1df999cd70649783153c36a. All six
CI workflows passed, including 6,493 backend tests, dashboard/browser checks,
and real PostgreSQL 17 archive/concurrency/security/rollback tests. Migration
20261026204421_reference_history_r2_archive is registered in Supabase; permission
readback confirms forced RLS, no anonymous execution, no API receipt-table access
and no general API TRUNCATE grant. No new security advisor finding was introduced.

Copy-only deployment 3a27785b-bd0c-403e-b93f-50ad2d1010d5 reached SUCCESS;
HTTP readiness returned 200. At 20:50:21 UTC the downloaded R2 snapshot passed
full typed restoration for all 33,702 rows. Supabase still retained the identical
count and content root before cleanup was enabled.

Cleanup deployment 6cb32a73-5d43-4335-a57f-22ebf2dfc4ff reached SUCCESS with
readiness 200. Durable receipt committed at 20:53:36 UTC: 33,702 rows archived,
54,050,816 bytes reclaimed. Archive ID is r2-reference-history-
2881bf674573c9e2f42dd0c60e485a9d670f8812ca199db8035b365486763b37
(join the wrapped line); its suffix is the canonical full-row content root.
The history relation fell from 54,083,584 to 32,768 bytes. Immediate database
readback was 353,127,571 bytes, below the unchanged 400,000,000-byte refresh guard.
All 616 inventory rows retained checksum b37b9df22b5ca5b6a525bc5a684d9d3c.
A new REFERENCE_PRICES job was RUNNING at 20:53:55 UTC, proving the capacity
blocker cleared; this does not assert that every provider or pricing gap is fixed.

Both archive flags are enabled on the API service. Each attempt still downloads,
restores and verifies before guarded cleanup; failures preserve the live history.
The worker attempts at startup and at most hourly per process. Current prices,
ownership, acquisition costs, Store Prices and settlements are not archival targets.
Supabase remains their authority; previous Drive archives remain retained.

Cloudflare's private bucket has public URL disabled, no custom domain and no
completed-object expiry. A one-image approved-media signed bridge probe succeeded,
increasing verified mirrors from 2 to 3; the one-shot flag was reset. Recurring
DR94 remains off pending stored-workflow validation, DR90 routing and actual n8n
execution proof. Broad reference-image caching remains source-permission gated.
The R2 image CSP defect is fixed for either independent delivery switch.

Latest pre-resumption coverage was 42,482 / 67,065 physical references (63.34%),
including explicitly labelled guides. The 90% user target and 95% software target
remain unmet. Live R2 price-cache delivery, a history-reading API for R2 archives,
missing artwork/source permissions and the full comics/manga import remain
separate unfinished work. Do not describe archiving as new pricing coverage.

See [archive, recovery and live evidence](docs/R2_HISTORY_ARCHIVE_20261026.md).

# Build status

## 24 October 2026 - Pricing recovery (live verified, PR #699)

PR #699 is merged as 7b22901e0b90ad4d377a00048bbae6d9c30a0159.
Railway deployment 0b08188e-f4dd-4597-80f6-0510a6773123 reached SUCCESS at
17:34:07 UTC; public readiness is HTTP 200 with the database connected, one
running replica and no active failures. All five final PR workflows passed,
including restricted-role PostgreSQL checks. The full local Python suite and
all 6,307 Railway predeploy tests passed.

Recovered 80 previously unpriced Fusion references: 56 starter records and
24 records in other releases with escaped names. The guarded backfill used
exact reference identities, current Cardmarket source data and verified ECB
conversion; it committed exactly 80 new immutable history records. All guides
remain labelled mixed-language reference context, ineligible for physical-copy
valuation. No inventory, ownership, Store Price or Shopify changes.

Catalogue coverage is now 40,628 / 67,065 physical references (60.58%), up from
40,548. English Fusion coverage is 1,319 / 4,365. The overall 95% target is not
met: 26,437 physical references still lack supported values or labelled guides.
Missing source access, exact variant mappings and absent quotes remain explicit.

Verified private archival preserved all 35,802 preceding history rows and
reclaimed 56,606,720 bytes. Typed restore, full-field/quote digests, private
upload, complete download SHA-256 and ZIP CRC passed. Inventory and al…33092 tokens truncated…til coverage read-back is satisfactory.
- The first shared pass checked all 463 canonical products but only produced three values: 330 legacy products have no canonical language although their exact sold evidence has one. Keep canonical identity unchanged and use the independently verified observation language as an explicit valuation basis; conflicting known languages still fail. Also recognize the existing exact sealed-pack ingestion rule. Revision 2 rechecks the prior pass.
- The corrected sealed import completed 703 sets / 3,878 products. Its price pass checked 3,414 supported packaging references and priced 2,403 (2,134 Pokémon, 269 One Piece), with zero provider failures; unmatched/unsupported references remain unknown.
- The real PostgreSQL fixture now has an unspecified canonical language and no inventory table, verifies the English quote basis, and proves the canonical language stays null. No bulk identity correction is performed.

## 9 October 2026 — Inventory-independent catalogue valuations

- Daily canonical valuation now reads public exact eBay observations and successful provider-check receipts, not physical inventory or owner pricing policies. Every canonical product is checked; five matching recent sales feed the existing v4 engine, with separate physical bases and immutable catalogue snapshots.
- The reference helper uses the shared catalogue snapshot and checks current printing identity, language and original provider freshness. Selling/removing the last held copy no longer removes a valid catalogue value. Recalculation does not refresh the provider timestamp.
- Public Cardmarket feed fixtures also confirm its Pokémon Display and One Piece Preconstructed Decks labels; explicit packaging equivalents avoid guessing categories. The guide revision triggers a corrected pass after the cross-ID repair.
- Release uses additive schema first, deployment and verified CATALOGUE_VALUES receipt second, then the reference-helper migration. Actual PostgreSQL checks prove valuation with no inventory table, retry/identity/language/freshness guards and forced RLS. Current-head CI and live read-back remain gates.

## 9 October 2026 — Live provider cross-ID contract correction

- PR #552 deployed successfully as `1a42ef8` on `ab9869e7-585d-4de2-9a61-1045f4e8cddc`; full backend/UI and PostgreSQL persistence CI passed and the evidence migration is applied. Existing 11,910 public quotes were retained in immutable history.
- The live sealed pass exposed zero cross-IDs from the older scalar example. Current CardTrader documentation specifies `card_market_ids` arrays. Revision 4 accepts one unambiguous positive ID, supports the old scalar form and rejects multiple/conflicting/malformed IDs. The earlier revision remains journalled.
- Added current-contract fixtures and ambiguity checks. Actual sealed price coverage still requires post-deploy read-back; no catalogue or inventory identity is inferred from a name.

## 9 October 2026 — Catalogue-wide price evidence extension

- Audited v4, actual provider evidence, catalogue scope and channel behavior; see [valuation review](docs/CATALOGUE_VALUATION_REVIEW.md). Daily reference work now includes Japanese Pokémon, exact-variant TCGplayer US context and ID-matched Cardmarket packaging guides. These remain separate from physical five-sale eBay UK values and seller Store Price.
- Full-reference coverage receipts make unmapped/unsupported/stale evidence visible; append-only quote history preserves provenance and deduplicates retries. Bounded daily-slot continuation avoids reprocessing completed parts of the first fill. No paid plan or new service is added.
- PR #551 is deployed as `bb7dabf`, Railway deployment `299992fa-c3a6-46ea-9748-b830c9200c0c` SUCCESS. Its immediate approval trigger passed full backend/UI and PostgreSQL CI. Brand Redesign remains unpublished.
- This extension still requires current-head CI, migration, deployment and live coverage read-back before release completion. eBay capacity and exact mappings remain real coverage gaps, not zero values.

## 9 October 2026 — Immediate approved-stock Shopify trigger

- The founder requested prompt Shopify sync when a seller approves stock for sale, while keeping Brand Redesign unpublished. Successful approval/edit/For-sale transactions now wake the existing sync worker after commit; it re-reads exact inventory/owner/version through the existing publication gates. No new service, queue type, schema change or eBay publication is introduced.
- Coalesced signals preserve approvals arriving during a pass. The existing minute sweep recovers after restarts or other-replica writes. Draft, personal, sold, unapproved and archived stock retain their existing boundaries; provider processing is asynchronous, not instant.
- Focused tests cover committed versus failed transactions, idle wake-up, in-flight wake-up, duplicate signals and disabled workers. Current-head CI, deployment and live read-back remain release gates.

## 9 October 2026 — Recurring refresh deployed and checked

- PRs #548 and #549 are merged. Live API commit `c269f6d`, deployment `4a3e46b4-dc01-4c12-b0df-466f12c404c3`, reached SUCCESS at 15:23 UTC after 2,712 tests and all original financial/social pre-deploy checks. Current-head GitHub backend/UI and PostgreSQL integration passed. The original pre-deploy command is restored; no staged infrastructure changes remain.
- Both recurring jobs are enabled on the existing always-on API, using the authorized founder actor. Daily source/price work is due at 03:00 Europe/London; eligible inventory and asking-price sync checks run each minute. Existing publication and seller-sync switches are enabled. No new Railway service, n8n scope or paid provider plan was added.
- Both required migrations are applied. Forced RLS on sealed references/operational receipts and denied anonymous/authenticated execution of the existing price functions were read back. Shopify recorded a COMPLETE heartbeat at 15:21 UTC with zero publication candidates, zero price candidates and zero failures; this verifies an idle pass, not a manufactured new live publication.
- The initial source catch-up remains in progress. Masters completed 90 sets / 9,002 references (previously 8,982), and official OP16 completed 155 references. Interrupted source attempts remain journalled and resume after backoff; a transient TCGdex request stopped its first pass after 306 sets / 27,884 records, with the next two public set endpoints subsequently responding 200. No full-source completion is claimed.
- Signed-in Search verified 23/23 available Seel images and labelled Cardmarket reference values; One Piece sets show exact-set card previews. Inventory is still 510 copies, 512 media assets and 505 published links, with no inventory changes since 08:01 UTC. Store-price reconciliation has zero due changes.
- Corrected sealed importer started at 15:28 UTC. The first read-back showed 920 products across 210 provider sets, all 920 with artwork URLs, spanning Pokémon, One Piece, Masters and Fusion World. Live Sealed search returned Elite Trainer Boxes and cases with 30 nearby images loaded; six below-fold images remained lazy. Physical language remains unconfirmed and reference-only sealed prices remain pending. This is measured partial coverage while the initial import continues.
- Our eBay UK v4 coverage remains 156/510 copies. Exhausted free Trawl credits block further supported refreshes until renewal/approved capacity; 269 copies also lack five exact sold matches, and three need identity/taxonomy work. Cardmarket references are separate from inventory valuation; TCGplayer is not an active quote feed. No paid upgrade is authorized.

## 9 October 2026 — Live refresh activation corrections

- PR #548 is deployed as `9079848` (deployment `5eaab097-e5d8-4de4-a441-afdf0de7751e`, SUCCESS); 2,711 backend tests, all UI suites and actual PostgreSQL/RLS CI passed. The additive daily-maintenance migration is applied and the two new jobs are enabled. Reference imports began on production; these are live observations, not a claim of full source completion.
- The first live pass exposed prefixed CardTrader category names (for example `Pokémon Booster Box`) missing from older fixtures. Importer revision 2 normalizes only the matching game prefix, retains exact category matching, excludes accessories and separates shared-game Fusion World expansions from Masters. Revisioned receipts permit this corrected importer to run without rewriting the prior failed attempt.
- Existing Shopify publication/seller-sync switches are now enabled for the requested automatic pipeline. The first check identified an unapplied existing dependency, `20260930124000_shopify_price_reconciliation.sql`. No new copies or price candidates were eligible. Added real PostgreSQL coverage of that dependency's selection, stale-version rejection, finalization and audit before applying it live.
- A bounded read-only provider taxonomy probe ran alongside all original pre-deploy checks; the original pre-deploy configuration has been restored. No credentials were logged. Remaining gates are current-head CI, dependency migration, corrected sealed import and durable Shopify heartbeat.

## 9 October 2026 — Daily catalogue and eligible Shopify sync

- User explicitly requested daily cards/sets/values and automatic customer-inventory Shopify updates. Added opt-in tasks to the existing API: reference imports/price cache due at 03:00 Europe/London and eligible Shopify checks each minute. No new service, n8n workflow or paid subscription.
- Added CardTrader sealed packaging references, separate from canonical inventory, with explicit game/category scope, required physical language during draft intake, exact-reference image delivery and no auto-approval. Real migration/query/RLS and publication-selection integration is included.
- Source and job receipts, restart checks, advisory locks, bounded batches and retry backoff make results observable. Daily Cardmarket references stay separate from the existing eBay UK inventory algorithm; its exhausted sold-data quota remains a limitation.
- Shopify reuses exact Inventory ID/owner/version publication and price-sync rules. All 505 currently approved For-sale copies are already linked/published; three drafts and two inspection copies remain outside automatic publication. Market refresh never sets an asking price.
- PR #547 is live as `cae67e3` on deployment `6e450418-5d8b-4614-8edf-0ccd4ed03d06` SUCCESS. Signed-in browsing now shows Seel reference prices across multiple sets and all 23 available Seel images; the visible sealed tab returns the three existing products, including OP17 at £8.66. Wider sealed imports and recurring jobs require this release's migration, CI and activation/read-back. See [daily maintenance](docs/DAILY_CATALOGUE_MAINTENANCE.md).

## 9 October 2026 — Catalogue speed and price-request repair

- Fixed the unencoded browser market-price POST body, which the real hub transport forwarded directly to fetch. Existing source/finish/freshness rules and eBay valuation gates remain intact.
- Added bounded account-lifetime artwork reuse, direct delivery for known restricted official artwork, nearby-image loading, and immediate recent catalogue rendering with background revalidation. First-load phone latency is not claimed to be zero.
- Added visible Cards / Sealed products controls and exact-set, language-safe card previews when set logos are unavailable. Only three sealed products currently exist; worldwide sealed coverage remains incomplete.
- Focused backend tests and 31 catalogue UI scenarios pass; the paginated preview query ran read-only against production. Full suites, current-head CI and live deployment verification remain release gates. See [catalogue loading repair](docs/CATALOGUE_LOADING_REPAIR.md).
- Previous artwork release is complete: PR #546 / `1a914fa`, production deployment `9945c126-3e5b-42e2-aab8-f462858aa08c` SUCCESS after 2,704 tests. The audited repair restored all 3,981 targeted Japanese links, the original pre-deploy configuration was restored, and signed-in English/Japanese One Piece images loaded. Inventory identities, ownership, Store Prices and media registry fingerprints were unchanged.

## 9 October 2026 — Catalogue artwork import repair

- Traced 3,981 missing Japanese One Piece images to the lightweight provider index. All 26 affected full pack records passed source validation. Future imports now read exact-print artwork; sparse imports retain existing artwork and provenance only for unchanged identities.
- Added a bounded, explicit, admin-only reference artwork backfill and disposable PostgreSQL persistence checks. The repair has no inventory, valuation, canonical media approval or publication writes.
- Corrected misleading image placeholders and bumped both app shells' catalogue script version. Signed-in desktop inspection confirmed existing Pokémon and Dragon Ball images load; some Pokémon records have no source artwork. No iPhone-wide reproduction is claimed.
- Reproduced the blank English One Piece grid: official images send `Cross-Origin-Resource-Policy: same-site`. Added authenticated exact-reference image delivery using the existing scanner image loader, bounded fetching, normal catalogue access checks and cleanup on account/navigation changes. No arbitrary client URLs are fetched.
- The full backend and UI suites pass locally. Current-head CI, the one-off live backfill, configuration restoration and post-deploy read-back remain release gates at this checkpoint. See [catalogue artwork repair](docs/CATALOGUE_ARTWORK_REPAIR.md).

## 9 October 2026 — Comparable weekly history

- The full eBay refresh exposed a reporting error: weekly movers could compare new sold values with old import/floor snapshots. Restrict both ends to v4 eBay-backed evidence with five sales, matching snapshot owner and catalogue. Historical rows remain untouched; insufficient comparable history shows no movement.
- Expanded the real PostgreSQL integration to prove imported, floor, Cardmarket, insufficient-sale and wrong-owner baselines are excluded while a valid older eBay snapshot produces a mover. It also checks the current-snapshot gate and owner-scoped portfolio totals.
- PR #544 is live as `604cc461f7d4e06562ff5f65f0984309227e55f3` on deployment `536193f3-a8e3-4c65-ab32-abed35b60c5f`. The 500-group pass stopped safely on HTTP 429 after the provider reported zero remaining monthly credits. Across both passes, 380 identities / 427 copies were checked and 155 copies updated. Including the already-valued OP17 pack, 156 of 510 copies now have eBay values; 269 lack five exact sales, three need print/sealed identity details, and 82 unvalued copies remain unchecked. This is partial coverage, not completion of every price.
- Read-back retained all 510 inventory rows and the exact owner/Store Price/status fingerprint `731a328f655ed1023fb2ebbe14f0f3f4`. Historical snapshots increased from 871 to 1,026 and observations from six to 646. No historical row was deleted. The partial verified portfolio totals 81,209p; this is not a complete collection valuation.
- The existing API no longer sleeps between visits so the refresh loop can continue. Provider checks pause for 24 hours after the cap; the Free account resets on 1 November. A provider upgrade requires explicit spending approval and does not guarantee five exact sales for sparse prints. No subscription was purchased.

## 9 October 2026 — Live refresh release and provider capacity

- PR #543 merged as `ea36320601b6cc5f5a0990368be2e163ec4f24eb`; production deployment `350b2453-d2dd-4d9f-9171-46e1aaca2d57` reached SUCCESS after 2,683 tests. The real PostgreSQL integration and full UI suite passed. Migration/read-back confirmed current-snapshot lookup and server-only function access; readiness returned 200 and deployed catalogue JavaScript matched Git.
- The bounded ten-identity live pass updated three graded copies through v4, retaining their exact five sold records. Seven identities remained pending, including two unverified sealed types. The provider reports Free-tier capacity of 250 monthly credits, with 228 remaining. Full-inventory coverage is not yet complete.
- The follow-up reuses identical searches across finishes within a pass while validating each finish separately. It reduces credit use without changing the algorithm, identity gates or source. No provider upgrade or additional purchase was made. Full-pass results remain to be verified.

## 9 October 2026 — Live eBay UK inventory valuation repair

- The founder explicitly requested all market values use our sold-market algorithm. Found the old batch only selected missing Store Price; 506 copies were still on imported/floor snapshots, two had v4 values and two had no value.
- Added a bounded task in the existing API: exact physical grouping, five recent eBay UK sales, existing v4 calculation, immutable observations/snapshots and durable refresh attempts. It preserves Store Price, ownership, publication and history. Old benchmark values cease to count as live market values.
- Current-snapshot catalogue lookup and visible Cardmarket reference labels prevent source confusion. No new providers, services, n8n workflows or automatic selling-price changes.
- Focused matching/transaction tests and the full backend suite pass locally. Current-head CI, production release, refresh coverage and provider quota evidence are still required before claiming completion. See [Live eBay market refresh](docs/LIVE_EBAY_MARKET_REFRESH.md).


## Read this with the full history

The complete build log through the marketing installation checkpoint is preserved unchanged in [BUILD_STATUS.history-through-20261004.md](BUILD_STATUS.history-through-20261004.md). Its Git blob is `bf3fa9436687cae18357ca2b124bbc9dff35174e`, identical to BUILD_STATUS.md at production commit `a0432bb82694868026c804d5b0af57cda9c128bd`. No historical entry was deleted or rewritten; the archive remains at repository root so its relative links keep their original meaning.

This page records current continuation checkpoints, not a replacement for the full backlog, CLAUDE.md, the master project instructions, or either operating manual. Read the historical log and relevant docs before resuming another area. Old unresolved work is not implicitly complete.

## 8 October 2026 — Catalogue market release and sealed-comparable repair

- PR #541 is live as `ade06f8` on API deployment `ae2816c0-564a-4618-bca0-dc72f8c5545d`, which passed 2,647 backend tests and readiness. Its final reference basis is Cardmarket EUR via TCGdex, with historical GBP conversion and explicit finish mapping.
- Recovered one previously unvalued, confirmed Seel Normal inventory item from its exact Cardmarket reference using `drop-rate-market-v4`. Added immutable observation/snapshot evidence and checked the inventory version/owner/identity. Market value is 3p; Store Price remains £1 and automatic publication is blocked. No ownership, ledger or media changes occurred.
- The read-only sealed probe found actual multi-pack lots passing the single-pack matcher. Tightened set-code, quantity, language and sealed-state exclusions and expanded the bounded query to two pages. The five exact sold-comparable minimum and owner/version guards remain intact. Diagnostic results were not written as prices. See [sealed market repair](docs/SEALED_MARKET_REPAIR.md).

## 8 October 2026 — Seller Hub catalogue market data repair

- Connected the existing TCGdex card-detail prices omitted by checklist imports. English Pokémon raw references now use explicit finish/product IDs, dated ECB conversion and a PostgreSQL cache; product details show finish prices and their source/date. Broad references show a range where finishes differ.
- Price requests run after card rendering, retain recent values during provider outages, reject stale search/session responses and leave open intake forms intact. Forced RLS and existing browser access checks remain in place. This display cache does not write inventory prices, approve mappings/media, change ownership or publish stock.
- Added a bounded read-only sealed-provider diagnostic. Full backend and UI suites pass; live public-provider checks returned real Seel and Umbreon quotes. The additive cache migration, RLS/role checks and normal/value-sorted database read-back are verified. Other games, Japanese/graded cards and missing sealed evidence remain separate coverage work. Current-head CI, deployment and HTTP read-back remain release gates at this checkpoint. See [market reference repair](docs/SELLER_HUB_MARKET_REFERENCES.md).

## 8 October 2026 — Game navigation and appearance settings

- Replaced the dashboard colour-selector row with real game catalogue shortcuts. All games resets previous filters; normal Search navigation retains them.
- Moved colour themes into More → Settings → Appearance for sellers and founders, preserving the saved device preference. Added seller Settings routing and mobile touch targets; no changes to inventory, finance, identity or permissions.
- The new integration test loads both real script bundles and verifies catalogue requests, Settings navigation, theme persistence and filter reset. Local UI and focused backend checks pass. CI/deployment/device validation remain distinct release gates. Details: [Collector Hub design](docs/COLLECTOR_HUB_DESIGN.md#8-october-2026--separate-game-navigation-from-appearance).

## 8 October 2026 — Seller Hub image and valuation display

- Fixed the image policy for the existing Dragon Ball, Naruto and CardTrader hosts, including CardTrader's observed `www` redirect. Added same-product approved artwork fallback and cache-version updates.
- Diagnosed missing valuation coverage separately: stored prices still return, but unlinked catalogue references and the inspected unvalued seller item have no verified market value. Owner totals now expose coverage and show “Value pending” when all active items are unvalued; no prices or ownership were changed.
- Targeted backend checks and the full browser interaction suite passed. Current-head CI, deployment and live-header verification are remaining release gates at this checkpoint. See [Seller Hub display repair](docs/SELLER_HUB_DISPLAY_REPAIR.md).

## 8 October 2026 — Storefront mobile arrow rendering

- Updated the unpublished **Drop Rate — Brand Redesign** theme (`202073866587`) to render the homepage diagonal arrows as a shared decorative SVG. This prevents iPhone emoji substitution while preserving the diagonal direction, inherited link colours, relative icon size and existing spacing.
- Covered hero CTA/featured caption, discovery search/game links, editorial CTA and set links. No changes to link destinations, settings, merchandising, products, checkout or backend services; Horizon remains the live theme.
- Shopify accepted all five files with no user errors. A separate read-back matched every deployed file byte-for-byte to the implementation. The nine existing homepage/brand tests passed, as did Shopify Liquid validation for all five changed files (existing cross-section CSS warnings only; the repository is a partial theme overlay).
- Browser visual verification was blocked by the storefront password screen. No real-device or authenticated desktop visual pass is claimed. This icon repair does not satisfy or reopen the broader publication gate.
- Implementation and rollback notes: [Storefront launch QA](docs/STOREFRONT_LAUNCH_QA.md#8-october-2026--mobile-diagonal-arrows).

## 5 October 2026 — Gunko post metrics baseline (read-only)

- PR #525 merged as `14722ade1f93667a1730275206087b07e168c4f7` and added a strictly read-only Buffer metrics reader for the two already-delivered Gunko pilot posts. It has no post mutation, schedule, database write or recurring analytics job.
- Fresh API deployment `505da5fb-2ae6-4594-902a-d5ad059ead2b` passed **2,560 tests** and readiness 200. Its bounded live probe read the exact Instagram/TikTok post IDs and channel identities already recorded by the publishing pilot.
- Instagram metrics were available with `metricsUpdatedAt=2026-10-05T00:03:34.559Z`; Buffer reported Reactions 0, Comments 0, Engagement Rate 0, Views 0, Shares 0, Saves 0, Follows 0 and Reach 0.
- TikTok metrics were available with `metricsUpdatedAt=2026-10-05T00:06:35.657Z`; Buffer reported Reactions 0, Comments 0, Engagement Rate 0, Video Views 0, Shares 0 and Reach 0, plus provider values **Watch Time (min) 0.02** and **Avg. Watch Time (sec) 1.89**. Preserve those provider labels/units as returned; do not derive extra conclusions from the early baseline.
- The temporary metrics diagnostic was removed after the read. The live API pre-deploy command is back to the normal compile/test/Stripe self-test chain, with no staged Railway changes. Recurring metrics collection/analysis remains off.

## 5 October 2026 — YouTube video pilot contract prepared (not live)

- PR #526 merged as `06886af5bb812619d5c818bd5417484fd95d2f38`; API deployment `03005678-d39f-4b6c-9a58-29d655d5e12b` reached SUCCESS after **2,589 tests** and readiness 200. The release emitted no Buffer readiness/metrics/publish diagnostic lines; the contract is inactive validation code only.\n- Added a separate fail-closed contract for the future YouTube Shorts pilot after channel readiness was verified. It is intentionally **not** a FastAPI route and contains no Buffer credential or GraphQL mutation, so it cannot publish.
- The future approved asset must be one HTTPS Shopify Files `video/mp4`, exact 9:16, at most three minutes, with exact SHA-256/byte count plus affirmative approved-audio/narration/caption declarations. The contract binds the verified Buffer organization/channel IDs and founder approval metadata.
- Added pure construction of the future immediate/automatic Buffer YouTube input and deterministic channel/post validation. Subscriber notifications are disabled for the bounded pilot; public/not-for-kids and AI-disclosure fields are explicit rather than provider defaults.
- Media preflight streams the file without redirects, caps the pilot at 512 MiB, requires exact MIME/length/hash and an MP4 `ftyp` marker. It does not pretend to infer narration/caption quality from bytes; the exact hash binds runtime bytes to the human-approved media revision.
- Tests cover strict manifest parsing, approval/URL/aspect/duration/audio/caption gates, exact provider input, channel binding, media integrity and YouTube delivery URLs, plus an explicit no-route/no-Buffer-mutation assertion. See [YouTube video pilot contract](docs/YOUTUBE_VIDEO_PILOT_CONTRACT.md).
- Still blocked: no approved narrated/captioned MP4 has been supplied. Do not add/activate the live route or n8n YouTube publishing workflow until that exact asset and its title/description/category are approved.

## 5 October 2026 — Buffer YouTube channel readiness verified

- PR #521 merged as `29a089b61d123888bdd4097b32fdc93800484f2d` with a read-only Buffer YouTube readiness probe. Clean API deployment `f25b668f-3bbd-46b7-b937-688475273b1f` passed **2,550 tests** and readiness 200 before the live diagnostic.
- The first config-only redeploy did not prove that the newly configured probe executed, so no readiness claim was made from it. PR #522 merged as `2ff4689e4d97070d9b37997593d7037c6470cdaf` to flush operator evidence; fresh source deployment `2132c13b-d699-4afa-ad87-1d449f668146` then passed **2,550 tests**, ran the read-only Buffer channels query and returned readiness 200.
- Buffer returned exactly one YouTube channel for organization `6ac1a59ca59739d7c3e08601`: channel `6ac1a694ea19ca0bde6c8ba3`, service `youtube`, provider-returned name/display name `Drop Rate ` (trailing space preserved), timezone `Europe/London`. It is not disconnected, locked or queue-paused, and `scheduleUpdates` is allowed. The readiness result is **READY** with no blockers.
- No Buffer mutation occurred: no post was created, edited, queued, scheduled or deleted, and no database write or recurring n8n schedule was introduced. Future YouTube identity must bind to the exact channel ID/organization ID rather than the mutable display name.
- Immediately after evidence capture, the temporary diagnostic was removed from Railway: the original API pre-deploy command was restored, the temporary timeout was cleared to the default, and no staged changes remain.
- YouTube delivery is **not** yet proven. Publishing remains blocked until an explicitly approved narrated/captioned video is bound to a separate immutable YouTube pilot manifest and the live path passes provider delivery read-back plus intentional duplicate-trigger replay without a second upload. See [YouTube publishing readiness](docs/YOUTUBE_PUBLISHING_READINESS.md).

## 4 October 2026 — Gunko social publishing pilot completed

- PR #519 merged as `5191cba757382618ae8ed2335a1997f371f2625d`. The subsequent bounded live Gunko pilot completed through the real n8n → signed FastAPI → Buffer path for Instagram and TikTok. This is execution evidence for the explicitly approved one-off pilot, not activation of the general six-agent or recurring marketing system.
- API deployment `e79cb45d-ed35-420f-8667-caf81fa60102` reached SUCCESS after **2,539 tests** and readiness 200. Read-only n8n deployment `4fc66826-3262-4c92-87a0-6211e71c5372` then returned `READY` for both intended Buffer accounts, including the hosted-image validation that had previously blocked publication.
- Real publish deployment `4a4d523b-6e37-442a-8bf5-273614363eb3` submitted the approved manifest `880123ba424f5a109a023be5f385b160208e53b51897957e2811cf9da2aac94d`. Instagram @dropratetcg produced Buffer post `6ac29d1f6ae9cbb01a564d9f`; TikTok @dropratetcg produced Buffer post `6ac29d1ffe1389e4133cde22`. A separate real status read-back on n8n deployment `603f2c64-2164-41cf-b1b2-deaa4b9fe004` returned `DELIVERED` for both with platform URLs.
- Idempotency is live-verified for this pilot. Intentional repeat publish deployment `85abd755-81d2-4355-9a4e-8a907c4e2f4f` returned `DELIVERED`, `replayed: true` and the **same post IDs/URLs**. PostgreSQL then still contained exactly **2 intents, 2 claims, 2 submissions and 2 observations**—one per channel—with **0 Action Required** items for this pilot. No duplicate provider submissions or journal records were created.
- Cleanup is complete. n8n's temporary pre-deploy command was removed and its timeout restored; `TCG_APPROVED_SOCIAL_PILOT` was cleared after the replay. Cleanup API deployment `4bc47f07-0379-49b0-b6fd-ddf2bccc32b3` reached SUCCESS, again passed 2,539 tests and returned readiness 200. Daily/recurring publishing and the generic preparation specialists remain off.
- Verification boundary: delivery was re-read from Buffer and recorded in PostgreSQL, but independent public visual/audio inspection of the returned social URLs was not completed, so `public_visibility_verified` remains false. The Umbreon/Goku price posters remain pending source/FX checks, and YouTube still requires the approved narrated/captioned video. This pilot does **not** prove general campaign intake, autonomous content production, arbitrary-post approval or daily scheduling.

## 4 October 2026 — Colour metadata compatibility (live-test repair)

- PR #518 merged as `d21706869daff13e5974fd29127ccb61b5e563d8`; Backend `37222469633` and Marketing integration `37222469535` passed. API deployment `08fe2c4e-b248-412f-9c38-ce2e36839223` reached SUCCESS after 2,533 tests and readiness 200.
- The actual n8n check on deployment `a5291b63-49ef-4db7-b133-2f7f6e2c1e9a` then returned PILOT_MEDIA_COLOUR_METADATA_CHANGED for both channels. It did not publish. The conservative validator rejected colour/EXIF metadata before reaching pixel comparison; no claim of exact live pixel verification yet.
- Replace blanket ICC/EXIF rejection with bounded real colour management: valid embedded profiles are converted to sRGB and the resulting pixels must equal the exact approved SHA-256. Harmless EXIF with identity orientation is allowed; changed orientation, invalid/oversized profiles, nonstandard unprofiled gamma, altered pixels and prior size/format/alpha/frame checks still fail closed. No name-only profile trust or pixel tolerance.
- The selected source PNG contains no colour profile, and local sRGB-to-sRGB conversion preserves every pixel of both publication copies. Added six metadata/transform regressions. Manifest hash, media, caption, accounts and approval are unchanged. Current-head CI and next live check remain separate gates. See [Colour-profile validation](docs/SOCIAL_PILOT_COLOUR_VALIDATION.md).

## 4 October 2026 — Live connection reached; lossless media repair

- PR #517 merged as `fbf4033ffacb2857cf6d72c50bdbe45bed3c7c6c`. The actual n8n runner now reaches signed production FastAPI commands and Buffer's two expected accounts. On deployment `6cad92a0-8a72-4279-92c6-6c200ae4e00e`, the check returned BLOCKED / PILOT_MEDIA_CHANGED for Instagram and TikTok. This is evidence that channel validation passed, not successful publication. No publish operation was selected and prior journal reads contained no claims.
- Aligned the disposable operator process with its tested env-access/crypto settings and the existing public HTTPS API URL. Persistent n8n configuration/workflows and the volume are unchanged. Multiple settings were aligned together; do not infer a single root cause from the old generic diagnostic.
- The prior JPEG file-byte fingerprints did not match the CDN response. Added lossless PNG copies with exact dimensions and SHA-256 of every decoded RGB8 pixel. Compression/text metadata can differ; even a one-value pixel change is rejected. ICC/EXIF changes, unexpected transparency, animation, excessive dimensions/bytes and invalid images fail closed. No perceptual tolerance or skipped approval check.
- Same selected Gunko design, same caption/accounts/pilot ID, new format-only manifest revision: `880123ba424f5a109a023be5f385b160208e53b51897957e2811cf9da2aac94d`. Previous `2b0560...` revision is retained in Git history, not silently accepted. No existing publication intent/claim is overwritten. Both PNGs are hosted on the existing verified Drop Rate Shopify Files CDN, without product/theme changes.
- Fixed diagnostic classification to read actual n8n resultData.error, not guard strings embedded in the dumped workflow source. Earlier HASH_NOT_CONFIGURED classification is not conclusive root-cause evidence.
- Code, exact workflow revision, adapter/media tests, actual n8n CI fixture, docs and status are in the same repair PR. Deployment, exact live pixel read-back and delivery still require execution. See [Lossless pilot media](docs/SOCIAL_PILOT_LOSSLESS_MEDIA.md). Keep publishing/daily schedules off until the read-only check reports READY; remove the temporary operator command after the pilot.

## 4 October 2026 — Pilot runtime diagnosis (continuation)

- PR #516 merged as `dc57859c84d5e947121004161f6bd6fa07eabb12` after Backend checks `37219010958` and Marketing integration `37219010950` passed. Existing API deployment `f2bbf92c-3c2b-4da8-8725-ad390cc0e403` and n8n deployment `79c9d5cf-9b60-4ca6-8d05-cf2b891956b5` reached SUCCESS. API pre-deploy passed 2,501 tests and readiness returned 200.
- Read-only live check first failed before runner output with shell-style assignments in the Docker exec command. Using explicit `env NAME=value ... node ...` started the runner, but it returned RUN_UNVERIFIED. No successful live preflight or social delivery is claimed by those results; no publish operation was selected.
- Added fixed phase and allowlisted failure categories to the existing pilot runner. Raw stdout/stderr, environment values, signatures, provider messages and URLs remain excluded from diagnostic output. This does not change the approved manifest, HMAC, submission, duplicate protection, or production n8n database.
- Tests exercise the actual JavaScript classifier, known failures, unknown input, and redaction. Existing actual n8n check/submit/status fixture remains the integration gate. Live retry is check-only until verified readiness; inspect the durable journal before any publishing recovery.
- See [Pilot runtime diagnostics](docs/SOCIAL_PILOT_RUNTIME_DIAGNOSTICS.md). Current-head CI/deployment and the next actual run are separate gates. Preserve the earlier healthy deployment, remove temporary operator commands after testing, and leave daily scheduling off.

## 4 October 2026 — Approved Gunko publishing pilot (implementation checkpoint)

- The founder approved the latest posters for an immediate one-off n8n publishing test. Start with the Gunko story on Instagram and TikTok. The price posters still need separate source/FX checks; YouTube needs the approved narrated/captioned video, not a substituted silent slideshow. No daily activation.
- Recovered exact latest Gunko image, preserved the whole design in Instagram's 4:5 navy-padded JPEG and TikTok's same-ratio JPEG, and hosted both on the verified Drop Rate Shopify Files CDN. No product/theme changes. The manifest stores original and hosted hashes, exact captions, channel identities and approval source.
- Added a narrow signed FastAPI command with check/publish/status, exact manifest binding and expiry. It verifies actual channels and media bytes, then uses immediate automatic Buffer submission. Existing PostgreSQL automation_runs provides append-only intent/claim/submission/observation records; no new migration, database or service.
- Stable unique claims prevent duplicate/ambiguous retries. Provider failures become UNKNOWN and require reconciliation; failed records create owner-scoped Action Required. No caller-supplied media/copy/provider URLs and no broad publishing permission.
- Committed the actual inactive manual n8n export and explicit temporary-database runner. It is packaged separately, never invoked by normal startup, and does not alter persistent n8n workflows or enable the six preparation agents. This tests the publishing leg using approved assets, not autonomous research/design.
- Added adapter, signed-route, real PostgreSQL journal and network-isolated actual n8n fixture tests. Initial local adapter tests passed 27 cases; current-head CI, deployment, live preflight, real submission and separate delivered/public-visibility evidence remain required. The accompanying PR must record actual results rather than infer them from source or deployment success.
- Technical/approval details, sources, operating sequence and rollback: [Approved social pilot](docs/APPROVED_SOCIAL_PILOT.md). Remove any temporary n8n operator command and disable its API publication flag after the test. Preserve all journal/history and provider content.

## Verified installation — PR #514, 4 October 2026

- PR #514 merged as `a0432bb82694868026c804d5b0af57cda9c128bd` after Backend checks `37206549614` and Marketing integration `37206549593` passed.
- Supabase migration `20261004133308_marketing_specialists_v1` is applied. Marketing job/run tables have forced RLS; the latest read-only check returned zero jobs and zero runs.
- API deployment `f93752ea-4f97-4d40-9bd9-2496685a177c` and n8n deployment `eb2e1e84-3c29-469e-afb5-9b877b3a37bc` reached SUCCESS. API pre-deploy passed 2,453 tests and readiness returned 200. n8n logged all seven inactive imports while preserving previous workflows.
- Installed roles: research, briefs, copywriting, design instructions, deterministic blocked publishing, and supplied-metrics analysis, plus the preparation coordinator.
- Both specialist flags remain absent/default-off. Installation is not a real model run. Research still consumes supplied evidence; design does not render finished media; social management does not collect metrics or send replies.
- Final installation evidence is on PR #514. Earlier draft/not-deployed entries in the history describe older checkpoints.

## Marketing terminal attention repair — released PR #515

- PR #515 merged as `bd9be18373a42343bb0fadec8046bcc6f9ef660a`. API deployment `6a412a5c-7898-48e1-9917-b64158072b97` and n8n deployment `c6968707-c2d6-417d-8bef-d39a8380970f` succeeded; API pre-deploy passed 2,465 tests and readiness returned 200. Final evidence is on PR #515.
- Branch: `fix/marketing-run-attention-20261004`. The prior runtime could save FAILED/UNKNOWN/NEEDS_REVIEW without a corresponding Action Required item. Stale RUNNING recovery was also silent.
- Added actor-scoped Action Required creation in the same database transaction as a terminal marketing state. Owner identity comes from verified platform-admin membership, not model output or caller metadata. The existing OWNER entity and AUTOMATION category are used; no schema change.
- A stable per-persisted-run dedupe key and ON CONFLICT DO NOTHING prevent duplicate or reopened resolved alerts. Alert text/metadata contain identifiers and fixed status only, not provider/model/source text. An alert failure rolls back the state transition.
- Added focused unit checks and extended the existing local-only PostgreSQL smoke for failure/review states, no success/media-wait alerts, actor isolation, duplicate/late results, resolved-alert replay and transactional rollback. Those isolated checks passed; no production marketing job was implied.
- This repair does not fix the shared accountless DR90 control route, provide external email/Slack delivery, or add a background watchdog. Abandoned runs are discovered only when the existing claim path executes. Details: [Marketing run attention](docs/MARKETING_RUN_ATTENTION.md).

## Remaining general marketing gates

- The six-agent preparation chain still needs one actual authenticated job, saved-output reuse and live error visibility. The previously safety-blocked broad live-probe harness is not present and must not be recreated as a workaround.
- The approved single-image pilot above is a distinct, manually initiated publishing test. It does not complete generic asset revision approval, automatic content creation, arbitrary campaigns, recurring scheduling or YouTube production.
- Rejected Buffer validation drafts remain excluded. Never substitute them for the approved media. Earlier design feedback alone was not final publication approval.
- Current chat discovery exposes no Buffer actions despite the earlier custom plugin. The existing Railway Buffer credential is preserved; unattended backend access uses a runtime reference, not a key copied to chat. The pilot does not depend on the chat plugin.
- Railway's coding agent hit its existing usage limit; no increase is authorised or applied. Direct repository/infra tools are separate from that agent. No new services, public n8n endpoint, paid plan, stock, ownership, pricing, settlement or live money changes are included.

## Standing controls

PostgreSQL is authoritative; FastAPI enforces business rules; n8n coordinates. Keep authentication, signed commands, RLS, immutable history, provider terms, approval and duplicate protection. No recurring marketing release is implied. Unique unmerged work in #512/#513 is preserved; neither is silently superseded. Other frozen workstreams remain governed by the manuals and their explicit user decisions.

Rollback after a repair release is a code revert to the previous successful API build with flags disabled. Preserve marketing jobs/results, Action Required history, n8n's persistent volume and prior social content; never reset or delete them as a shortcut.


## Seller comics/manga intake and reference pricing revision 19 — 2026-10-13

User explicitly requested the remaining price recovery plus adding Marvel/DC comics, graded comics and manga to Seller Hub. Implemented an owner-bound book form from Inventory and Scan: publisher/series, issue or volume, edition/year, printing, cover/artist, language and ISBN/barcode; raw book condition or grader/grade/certificate; optional cost, selling price and copy notes. Each new copy is an unconfirmed PERSONAL_COLLECTION DRAFT. Seller-entered identities are NEEDS_REVIEW, never automatically verified or published. Existing canonical COMIC tables support both comics and manga; manga and other-comic system registry rows are additive. Restricted insert policies allow only self-attributed unreviewed book identities. Existing owner RLS, admin-only identity updates and certificate uniqueness remain enforced. Inventory detail exposes book metadata without another submitter's user ID. No automated book certificate lookup, photo recognition or book pricing provider is claimed.

Pricing revision 19 preserves the printed Pokémon delta symbol while normalising Cardmarket's redundant “δ Delta Species” label, and corroborates the exact XY Kalos Starter Set from its three published theme-deck names. Complete-checklist, exact-release and ambiguity checks still apply; these are reference guides, never automatic physical-copy or Store Price changes. Offline replay found 150 newly matched positive Delta Species guides and 34 Kalos identities; production net coverage must be read after deployment.

Validation: unit/contract suite and existing dashboard tests; signed local-JWKS HTTP with actual PostgreSQL physical guards, restricted role, owner isolation, concurrent replay, edition separation and duplicate slab protection; real Chromium/WebKit book form checks at 390/1440 px with intercepted fixture API calls. CI and production verification are required before reporting the feature live. Migration: database/migrations/20261013222139_seller_comics_manga.sql (filename generated by Supabase CLI).

Live verification completed: PR #633 merged as `dc3f8951ac4913af53aa1a0ad93c23f6bb5bea13`; all nine applicable CI workflows passed, with 5,776 local backend tests passing. Railway deployment `153c2c40-94f4-41ef-9c0a-87d50428f907` succeeded. Seller Hub HTML and four book/inventory/portal assets returned HTTP 200 and matched the committed bytes; readiness is healthy and the book intake endpoint rejects unauthenticated writes with HTTP 401. Supabase applied `seller_comics_manga` as `20261013224334`; migration staging records that version instead of replaying the canonical file. No production book or physical copy was created for testing. The fresh 614-item/327-valued stock baseline and ownership/Store Price/status fingerprint were unchanged across deployment. Details: [live book intake receipt](docs/SELLER_BOOKS_LIVE_RESULTS_20261013.md).

Reference revision 19 completed at **2026-10-13 22:49:51.645823 UTC** with zero provider failures. Source-aware coverage rose by **176** to **39,204/69,538** card references, for **5,232** recovered across these passes. English physical Pokémon is **20,648/21,290 (97.0%)**. **27,854 physical references remain without eligible prices**, plus 2,480 digital Pocket records where physical resale pricing is not applicable. Automatic book market pricing is not included. The remaining exact identities and source-evidence requirements are documented in the [updated pricing receipt](docs/PRICING_RECOVERY_LIVE_RESULTS_20261013.md); no claim of complete pricing is made.

## Comic and manga grading choices — 2026-10-13

User clarified the required Seller Hub choices: **CGC for Marvel, DC and other comics; CGC or BGS for manga**. Replaced the generic grading dropdown with category-specific choices and bumped the book script version. A company change clears the old grade/certificate, including switching BGS manga to a comic, so certificate data cannot silently move to a different company. Existing records and the general intake API remain compatible. Extended the existing browser and disposable PostgreSQL fixtures for both manga graders and certificate handling; 49 focused unit/contract checks and JavaScript/Python syntax checks passed locally. This changes entry options, not market-data provider connections or grading authentication.


### 30 October 2026 — R2 catalogue, current prices and artwork

- PRs 814–816 repair publication value-query transport and authenticated
  reference-image leases. Production delivery is gated by all eight parity cases.
- Add independent, content-verified R2 copies of the four shared price caches,
  with atomic freshness invalidation and bounded default/search/owned/sealed
  page delivery. Existing SQL still validates exact identity and expiry.
- Extend private reference image coverage to existing Naruto and CardTrader
  sources with matching application and RLS policies. No owner data is exported,
  no source rows are deleted, and no store/Shopify media approvals change.
- Local unit and disposable SQL checks cover corrupted/partial uploads,
  generation races, owner separation, stale prices and authenticated image
  receipts. Production publication and copy progress still require readback.


### 30 October 2026 — R2 production readback and safe value routing

- Market publication verified: 91,054 records, 366 parts, 103,799,009 raw bytes;
  price generation 1 published at 14:15:14 UTC. Both market feature gates enabled.
- Keep full-catalogue value sorting on its existing SQL query. Remove the large
  R2 array transport and diagnostic EXPLAIN that stalled a production connection.
  Compare every catalogue identity before publishing; report SQL value delivery
  explicitly alongside the seven R2 page/navigation comparisons.
- Market publication precedes catalogue proof. Only the offline source baseline
  has a 30-second comparison budget; live request limits stay unchanged.
- Canonical migration filenames match the production registry, including the
  CardTrader filename fix. One stalled read-only connection was cleared; the
  waiting migration completed and no lock queue remained.
- Whole-catalogue delivery remains pending the new production parity readback.
  Artwork copying continues automatically; no source catalogue or inventory rows
  were deleted.

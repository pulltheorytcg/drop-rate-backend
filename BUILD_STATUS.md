# Build status

## 21 October 2026 — Comic/manga catalogue and saved artwork (release pending)

The missing saved-book artwork is traced to receipt-only inventory reads and a
14-edition catalogue. This change adds a reviewed 32-edition batch (46 publisher
editions total), shares edition artwork with saved inventory, restores a unique
barcode-matched legacy cover on read, and adds Choose cover for existing copies.
The second legacy copy lacks variant/barcode evidence and requires that choice.
Identity approval, ownership, physical copies, pricing and public listings are
unchanged. CI, seed application, deployment and live readback are pending; see
[scope, evidence, tests and rollback](docs/BOOK_CATALOGUE_LIBRARY_20261021.md).

## 18 October 2026 — Default-camera book handoff (live verified, PR #693)

The new phone recording loaded current assets but all eight comics entered the
Cards-only API/schema, returning NONE/UNKNOWN before any publisher lookup. The
default Auto camera now returns typed book evidence from the same vision request,
uses the existing private book receipt/review, and includes compatible reviewed
publisher artwork immediately. Explicit legacy comic observations get a bounded
book-reader fallback. Mixed queues keep card/book types and removal behavior.
Stored market values are checked automatically; missing data offers sold-listing
comparison. Numeric book values are still blocked: zero production book snapshots,
no verified book identities and the current eBay/Trawl HTTP 429 pause through
18 October 17:39:35 UTC. No provider/config/schema or production data changes.
All six final PR workflows passed, including 6,196 Python tests, the full Node
suite (64 scanner cases), PostgreSQL receipt/RLS/retry/quota checks and Chromium/
WebKit at 390/1440 widths. Final mobile Auto/book/artwork screenshots were inspected.
Railway c69c96da-0209-4665-975d-0ee200e5449e reached SUCCESS at 15:34:05 UTC
with main 7558fd27; predeploy passed all 6,196 tests. Live readback at 15:34:29 UTC
verified all four book-auto-v6 asset hashes, owner/founder entrypoints, healthy
readiness and anonymous receipt/cover 401. All three main workflows passed,
including production readback. Fresh phone OCR accuracy remains unmeasured;
the eight recorded failures are routing regression fixtures, not new model results.
See [scope, evidence, limitations and rollback](docs/BOOK_AUTO_ROUTING_20261018.md).

## 18 October 2026 — Automatic book artwork selection (Live verified, PR #691)

Follow-up to the founder's Collectr/card-flow request: matched publisher artwork
and its metadata are selected automatically, with a one-tap Add and optional
Change cover. The prior separate cover-confirmation step is removed. Selection
uses the existing verified, non-conflicting candidates and does not claim visual
proof or invent unknown printing, condition or value. Background results preserve
edits; pending saves retain the original artwork receipt and idempotency key.
The Add action stays visible while optional fields scroll. All six PR workflows
passed, including 6,180 Python tests, the full Node suite, PostgreSQL ownership/
artwork/retry checks and Chromium/WebKit at 390/1440 widths. Final default/alternative
cover screenshots were inspected. Railway 8d7cc901-ced5-4121-8d20-c4aa3c7b0f37
reached SUCCESS at 14:58:45 UTC with main fc439fe6; predeploy passed 6,180 tests.
Live readback at 14:58:58 UTC verified all four book/scanner asset hashes,
owner/founder book-cover-v5 URLs, healthy readiness and anonymous receipt/cover 401.
No production data, schema or provider changes. Fresh scans use the new default;
earlier saved copies are not rewritten. Physical-phone recognition timing remains
unmeasured, and unavailable publisher artwork is not invented.
See [scope, checks and rollback](docs/BOOK_DEFAULT_ARTWORK_20261018.md).


## 18 October 2026 — Continuous capture and progressive book review (live, PR #689)

Follow-up to the founder's 14:58 recording: capture now queues beyond two active
reads, with an integrated 44px remove control. Book OCR returns before publisher
research; two bounded background lookups preserve user edits and pending saves.
Owner-scoped original-photo receipts claim research once and recover disconnected
responses without another paid lookup. Existing hourly caps remain unchanged.
Nineteen reviewed publisher references bypass repeat web searches, including
verified covers for Amazing Spider-Man #528/#795, Spectacular #11/#114 and Batman
#463. Marvel image formats, its older image host and same-issue canonical slug
handling are repaired. No universal artwork or measured phone-speed claim.
All six PR workflows passed: 6,178 Python tests, complete Node UI suite with 63
scanner scenarios, PostgreSQL owner/digest/concurrency checks and Chromium/WebKit
at 390/1440 widths. Final mobile queue screenshots were inspected. Railway
3b0dd56c-26e1-4e77-96de-9abf6af1060c reached SUCCESS with main cfbcb756 at
14:32:24 UTC. Owner/founder entrypoints and all four scanner/book assets match
the release; readiness is healthy and anonymous book receipt/cover reads return
401. No schema, production data or configuration changes. Physical-phone
recognition timing after release remains unmeasured.
See [scope, sources, checks and rollback](docs/BOOK_SCAN_QUEUE_20261018.md).

## 18 October 2026 — Book recognition and scan removal repair (live, PR #687)

The founder's 14:10 iPhone recording and eight owner-scoped recognition receipts
from 13:08–13:16 UTC exposed two skipped publisher lookups for unreadable issues,
four publisher candidates with no artwork, and book thumbnails forced to camera
photos. Research now accepts the cover when the issue is unreadable, with uncertain
OCR separated from confirmed fields. Added DC's official archive to the existing
publisher research, exact-issue bounded metadata cover recovery, source-bound
preview delivery, and metadata prefill even when a cover cannot be inspected.
Recognised books show a compact confirmation; optional copy details stay optional.
Queued scans have accessible remove controls, including during recognition and
inside book review. Late responses cannot resurrect removed scans. Uncertain saves
retain their original retry; dismissing a saved scan never deletes inventory.

Verified: all 6,172 Python tests in CI and production predeploy, 85 focused
Python cases, 56 scanner interactions and the complete Node UI suite. All six
PR workflows passed, including PostgreSQL RLS/retry and Chromium/WebKit browser
checks at 390/1440 widths. No production dependency changed.
Fetched/decoded the official DC Batman #463 cover and visually matched the supplied
recording. Some Marvel publisher pages return HTTP 403; no bypass, substitute artwork
or universal book coverage is claimed. Main b3819857 deployed successfully as
Railway c4c41407-aee4-49c9-9751-96fd9d9e5c99. Owner/founder entrypoints and all
four scanner/book assets match the release; readiness is healthy and anonymous
book artwork/inventory reads return 401. Physical-phone recognition remains
unverified after release.
See [scope, source evidence and rollback](docs/BOOK_SCAN_REPAIR_20261018.md).

## 18 October 2026 — Verified storage recovery and safe book rescans

Archived/restored/verified all 50,378 reference-history rows in the private Drop
Rate Drive, then used the existing atomic full-content guard to reclaim 77.05 MB.
Production is writable at 328.61 MB; current-price and inventory fingerprints are
unchanged. Bulk imports are below the 400 MB guard again; weekly timing is unchanged.
Fixed host-timezone sensitivity in the disposable archive verifier. Released the
book rescan fix so failed/new photo reads cannot retain the prior identity, artwork
or value. Added browser regression cases and a bounded read-only artwork review
through the existing CardTrader connection. No source backfill is claimed before
matching/visual verification. See [receipts and phone check](docs/CATALOGUE_RECOVERY_20261018.md).
All six PR #683 workflows passed, including the forced PostgreSQL retry race and
Chromium/WebKit rescan cases. Main 88971bec deployed successfully as Railway
52e920cc-f008-490c-8644-c23bac3a76f7. Follow-up PR #684 retained all 2,137 public
source records below the log-ingestion limit. Verified and applied 540 missing
English Pokémon images across ten releases; all ten now have zero artwork gaps.
PR #685 fixed explicit gender/Prism source labels and restored three dated,
mixed-language guide references. Latest main 4a3cfe56 deployed successfully as
cf4b00cd-2915-410c-8299-3b13f08291fc with 6,161 production predeploy tests passing;
readiness and exact book-script bytes match. The original predeploy was restored.
Remaining Pokémon image gaps: 10,364; physical reference/guide coverage:
40,446/67,060 (60.31%). Exact eBay sold access and the physical comic phone test
remain pending. See [source proofs and rollback](docs/evidence/catalogue-recovery-20261018/README.md).

## 17 October 2026 — Simple collection journey (live, PR #682)

Home now leads with the collection; selling/payout panels move to More → Selling.
Search and scan use Add to collection with optional raw condition and quantity,
plain status labels and separate selling controls. Book confirmation keeps optional
copy details out of the main path and can show the chosen catalogue cover.
Source identity, owner isolation, immutable retry, sealed/slab constraints and
Draft PERSONAL_COLLECTION admission remain. No invented price or artwork:
read-only coverage remains 40,443/67,060 physical references, 10,904 Pokémon image
URLs missing and bulk pricing paused at 405.66 MB. An opt-in four-call CardTrader
artwork probe provides evidence only. No new service, schema, paid source, live
stock write or Shopify theme publication. See [scope and gaps](docs/SIMPLE_COLLECTION_JOURNEY_20261017.md).
All eight PR workflows and four post-merge workflows passed. Main bfb1f688 deployed
successfully as Railway 81a81489-b08a-480d-8bf9-874a2929a862; readiness, owner HTML,
13 exact changed asset hashes, founder bundle versions and anonymous 401 were
verified. The public artwork probe was read-only and the original predeploy was
restored. Final receipts are recorded in PR #682; physical-phone timing is pending.

## 17 October 2026 — Pending import corrections and clean session reset (PR #681)

Fixed the import-review dead end for unrecognised condition/grade and incomplete
slab details through the existing owner-only confirmation route. Explicit card
corrections preserve original CSV evidence, Collectr quantity identity, unrelated
review issues and Draft-only admission. Duplicate slab certificates across a
multi-copy row are rejected. Closing/leaving/signing out clears the upload form
and hidden results; editing a search removes stale selectable matches. Mobile
review controls are contained, including a light native-control palette for Safari.
Local Python/DOM, signed HTTP, PostgreSQL/RLS and responsive browser checks pass.
Final deployment and asset readback receipts are tracked in
[PR #681](https://github.com/pulltheorytcg/drop-rate-backend/pull/681).
No live customer import, stock rewrite, market-price change, migration or service.
See [scope and verification](docs/IMPORT_PENDING_REVIEW_REPAIR_20261017.md).

## 17 October 2026 — Beginner book research and cover confirmation (PR #678)

The real-book recording showed OCR followed by manual edition research. The book
scanner now prepares publisher-sourced suggestions and cover choices through the
existing recognition service. Supported details prefill a compact confirmation
screen; ambiguous covers remain choices and unknown printing stays optional.
An explicitly selected publisher cover follows the saved draft copy through an
owner-bound, identity-checked reference receipt. No market values, identity/media
approvals, stock publication or financial actions are inferred. Full local Python
suite: 6,124 passing; 50 scanner interactions passing. All six PR workflows passed,
including real PostgreSQL owner isolation and Chromium/WebKit phone/desktop checks.
The configured provider returned the exact known One Piece ISBN and matching VIZ
cover; the release probe initially rejected VIZ's valid `/paperback` URL alias.
The corrected probe accepts that specific print alias and additionally requires
the exact expected image and a visual match. Deployment and live readback receipts
are maintained in [PR #678](https://github.com/pulltheorytcg/drop-rate-backend/pull/678).
See [implementation and release scope](docs/BOOK_RESEARCH_REVIEW_20261017.md).

## 17 October 2026 — Comics/manga live scanner repair (live, PR #677)

The reported iPhone flow was a form launcher: Comics / Manga closed the live scanner and opened a separate photo picker. It now selects a live `COMIC` mode using the same camera stream, shutter, gallery, auto-scan/removal gate and results tray. The existing book recognition endpoint reads the capture immediately; book review reuses that response and cover, and only an explicit book intake receipt marks the scan as added. Unknown identity/copy/price fields, owner guards, immutable save retry and the card/book intake boundary remain enforced. Released via main bd03cc8 and successful Railway deployment 84326318-f91b-414c-8148-204691ee8c54. The 50 scanner interactions, focused Python checks, Chromium/WebKit, PostgreSQL, full CI and live readback passed. See [scanner repair](docs/LIVE_BOOK_SCANNER_20261017.md).

## 17 October 2026 — Publisher covers for 14 books; explicit market-price status (live, PR #676)

Released on main e28d022 through successful Railway deployment 32474dea-b3b5-4e39-87bb-bdcb6ce78798. All seven PR workflows passed; deployed owner/founder browser asset v21 matched the reviewed bytes, readiness was healthy, anonymous artwork access was denied, and production counts remained 14 catalogue books / 614 physical copies / 0 physical books / 50,378 retained reference-history rows. Full release receipt is in PR #676.

All 14 starter editions now have reviewed publisher cover references, including Marvel issue 112985. Search and details use the existing authenticated, bounded thumbnail transport, exact identity/language/source matching and approved-media priority. VIZ's missing Content-Type on the Jujutsu Kaisen JPEG is handled only after decoding a valid raster from a trusted publisher path. Book prices explicitly remain pending: production has 0 verified printings/physical book copies, and the eBay/Trawl HTTP 429 cooldown ends 17 October 17:00:42 UTC. PriceCharting cannot be adopted without redistribution permission and exact edition evidence. Added completed/sold comparison links; no numeric prices, media approvals, inventory/Shopify writes, new provider or paid plan. Both shells load browser asset v21. Local exact-identity/auth/SSRF/raster and UI checks pass; all 14 public covers were decoded through the thumbnail transport. See [artwork and price evidence](docs/BOOK_ARTWORK_AND_PRICE_STATUS_20261017.md).

## 16 October 2026 — Publisher-backed starter book catalogue (live, PR #675)

Released via main 1bda587 and successful Railway deployment c341d9f2. Production readback confirmed 14 entries, unchanged 614 physical copies and 50,378 retained history rows. Added 14 real English-language edition references: One Piece 1–3, Naruto 1–3, Dragon Ball Z 1, Hunter x Hunter 1, Jujutsu Kaisen 1, Death Note 1; Absolute Batman 1–2, Absolute Superman 1, Ultimate Spider-Man (2024) 1. Publisher URLs, release dates and ten ISBNs are recorded in the reviewed manifest. The append-only seed reuses the existing manual identity algorithm, rejects collisions and is idempotent. Records remain STRUCTURED; unknown physical printing/cover, condition, grade, stock and market values are not inferred. Catalogue selection prefills the existing book intake for explicit review/save. Cover URLs are recorded as pending-rights provenance, with publisher links; existing approved-media gates remain intact. No Shopify products, new services, schema, provider subscriptions or refreshes. See [starter catalogue](docs/BOOK_CATALOGUE_STARTER_20261016.md).

## 16 October 2026 — Comic/manga scanner and exact-book market values (release verification pending)

Seller Hub now connects the existing book intake to camera/gallery evidence recognition (up to three photos), with explicit field confirmation and draft save. Added an exact-printing branch to the existing UK sold/v4 pipeline, immutable book identity digests, shared inventory/catalogue values and a read-only form lookup. Uncertain identity, mismatched editions/grades, unverified book profiles and signed/restored/qualified copies cannot inherit a standard value. No new service/schema, asking-price update or Shopify publication. Production has zero canonical books and the existing sold provider is paused after HTTP 429 until 17 October 17:00 UTC; **no new live book prices or real-photo accuracy are claimed**. See [design, failure cases and verification](docs/BOOK_SCANNER_MARKET_VALUES_20261016.md).

## 16 October 2026 — Comics/Manga first-class sections (CI and unpublished theme verification pending)

Extended the existing **13 October owner-entered comics/manga** foundation, without new schema or reinventing intake. Supabase currently has **zero** comic/manga canonical product records, so we created no artificial products, costs, market values or owned stock. The owner-scoped catalogue browser will add **Comics** (Marvel, DC, Other) and **Manga** as separate browse families; actual approved canonical `COMIC` profiles appear automatically once entered, and zero-inventory groups offer the already-secure manual book intake. Generic card/SEALED intake remains blocked for books. Added full JSDOM category navigation tests, owner RLS/type SQL tests, and Safari versioned JS.

In the verified **Drop Rate Shopify** account, created two smart category collections (**Comics** `/collections/comics`, GID `684163105115`; **Manga** `/collections/manga`, GID `684163137883`), exact tag rules `Drop Rate:Comics` / `Drop Rate:Manga`. Both correctly contain **zero products**, with no false stock or sale price. The unpublished Brand Redesign theme GitHub overlay includes homepage discovery and collection-nav links. **Do NOT claim this preview is live until remote theme file upload/checks succeed; never publish Horizon automatically.** The existing Shopify publication pipeline still excludes `COMIC` by design. See [book release plan](docs/COMICS_MANGA_BROWSE_RELEASE_20261016.md). Next price/provider work remains separate.

## 16 October 2026 — Seller Hub homepage 104-item financial-metric clarity (CI/release pending)

Audited the founder's 125s iPhone video and live owner-scoped Supabase data: **104 original physical inventory items = 101 cards + 3 sealed; 102 DRAFT / 2 APPROVED**. Only **one live guide-based GBP market reference (£0.03)** qualifies for the portfolio metric; deterministic **£1.00 recommended retail** applies to just that one. **Two actual owner-saved £10 asking prices total £20.00**; all 101 singles have no recorded Store Price. The old Home KPI placed the £1 automatic recommendation in the headline and relegated the actual £20 Store Prices to small text, leading to confusion. The new Home shows **Saved Store Prices £20.00 (2/104)**, keeps £1 as a separate clearly labelled guide-based suggestion, labels £0.03 as a **partial** market total (1/104), and accurately distinguishes **101 cards + 3 sealed products**. Zero valued/saved counts show `Unavailable`/`Not set` rather than zero portfolio worth. Added isolated JSDOM/home UI and owner-scope tests; no actual price, owner, stored asking or archive changes. Evidence limitations: **64 REVIEW media/identity mappings** (58 JP One Piece, 6 JP Pokémon), **24 Japanese OP16** owned numbers absent from the indexed JP reference catalogue, and stale Eevee/OP17 snapshots; no licence to automatically approve or borrow English/parallel prices. See [full recording audit](docs/SELLER_HOME_104_PRICE_REVIEW_20261016.md).

## 16 October 2026 — Seller Hub full-tile details, concise historical value (release checks pending)

Founder screenshot: mobile card titles, conditions and prices were buried under an oversized **Manage** button and long **Last known 08/10/2026** timestamp. Prepared native, keyboard-accessible full-tile open action (no Manage CTA), compact GBP values labelled **Historical reference** when stale, exact checked date retained in the existing detail modal, refresh icon repositioned over artwork without accidentally opening a detail view, and iPhone Safari asset cache bust. No seller ownership, pricing caches, store price, grading, listing eligibility, Shopify or archival SQL changed. Reference history retention audit: all 50,378 current rows are from 15 Oct; a 30-day raw retention window would retain almost all ~77MB and cannot clear 400MB Free-plan guard. Actual cold backup + compressed recent-history design remains separate and must pass verified Drive/typed-restore safeguards before any deletion. See [UI+retention decision](docs/SELLER_TAPPABLE_INVENTORY_20261016.md).

## 16 October 2026 — Archived-data SLA watchdog in existing Railway worker (release verification pending)

Daily 04:00 UK market-history archival remains an **enabled ChatGPT automation**, but not a native Railway/Supabase cron and has **no successful unattended archival receipt yet**. To make failure observable without purchasing a new service or exposing private Google Drive credentials, added `backend/app/archive_backlog.py` and a once-per-day **07:00 UK** overdue-history check to the existing authorised FastAPI catalogue worker. It read-only counts any `tcg.reference_market_history` recorded at/before the 04:00 UK cutoff and logs a structured warning if the daily archive did not clear it after a three-hour grace. It does NOT claim Drive backup success, delete rows, alter current prices, pause/unpause any other work, or bypass 400MB guard. Separate ChatGPT *Drop Rate Archive Watch* conditional task verifies archive registry and private Drive metadata after the daily window. First run 17 October. Original 50,378 history records, ~405.5MB Free database, 614 inventory copies remain intact unless a later fully verified archive completes. See [monitoring/runbook](docs/ARCHIVE_BACKLOG_WATCH_20261016.md).

## 16 October 2026 — Daily archival schedule versus weekly bulk pricing (release gates pending)

Founder authorised **daily 04:00 UK ChatGPT archive**, enabled starting **17 October**, and **weekly Monday 03:00 UK heavy market updates**, first eligible **19 October**. A ChatGPT schedule is **not** a Railway cron or proof of successful cloud archiving. Prepared deterministic `weekly_price_due` and `weekly_price_slot` in the existing Railway FastAPI worker for `REFERENCE_PRICES`, `SEALED_REFERENCE_PRICES`, `CATALOGUE_VALUES` and `CARDMARKET_VALUES`, preserving daily reference identity ingestion and independent Shopify reconciliation. Incomplete pages/failures retain their existing retry paths; IANA London DST respected. **400MB capacity guard and all 7-day quote validity remain unchanged**. Supabase still has 50,378 unarchived records / 405.5MB; do not run bulk refresh or delete history until complete correct-Drive archive/restore/readback succeeds. No paid sources, scraping, new services, migrations, stock or price changes in this release. See [cadence/runbook](docs/WEEKLY_BULK_PRICING_DAILY_ARCHIVE_20261016.md).

## 15 October 2026 — Honest Pokémon missing-art reference display (release checks pending)

Source audit: **10,904 TCGdex reference cards lack an image URL** (9,124 Japanese / 1,780 English). No already-approved exact canonical media matches were available. To avoid a broken-looking Seller Hub while protecting card identity, references with no real artwork (or with failed exact TCGdex low/high images) now show Drop Rate's *existing local Pokémon game mark*, explicitly labelled **Card image not yet available · Reference only**. It is not a replacement card photograph or a physical SKU approval. This does **not** add image URLs to the database and does not count as image-coverage growth. Mobile Safari JS/CSS cache versions bumped, with targeted functional/UI regressions. Details in [artwork fallback design](docs/POKEMON_REFERENCE_IMAGE_FALLBACK_20261015.md).

## 15 October 2026 — Official Kayou Naruto sealed pilot (release verification pending)

Prepared a hand-curated **four-product** official Kayou sealed reference import with source-backed manufacturer model numbers and exact box pack counts (Heaven Scroll Series 1, Earth Scroll Series 2, Chapter Jin Series 3, Ninja Age Premium Collector Box). No paid source, site scraping, invented package, standalone pack SKU, unauthorised image, sales estimate or copy/Store Price change. Reference language remains Unknown until a seller explicitly confirms it, exact release day is not invented, every manufacturer model is collision-checked, and all price fields stay absent. Seller Hub will show a truthful image-rights pending placeholder and clickable, host-validated manufacturer page, within the existing unified Naruto browse family. Implemented an opt-in admin-only atomic reference importer with offline dry-run and adversarial tests. **No production references added until tests and verified import/readback**. See [pilot manifest and test plan](docs/VERIFIED_KAYOU_NARUTO_SEALED_20261015.md).

## 15 October 2026 — Seller Hub video: visible sorts, truthful Naruto sealed gap, Dragon Ball variant labels (release checks pending)

The founder's 20:40 iPhone capture showed hidden sort controls, generic empty Naruto sealed results, visually repeated Dragon Ball cards, and missing price/artwork. The shared catalogue page now exposes compact Sort/Filters controls including Name A–Z/Z–A, Latest/Oldest, Number, GBP Value high/low; value sorting continues server-side before pagination, unknown prices last. Source-identified Dragon Ball `_pN` records display explicit `Printing variant pN` without merging distinct artwork/editions or borrowing the base-card quote. Naruto sealed shows an explicit verified-catalogue gap and a working card-browse action instead of an unhelpful no-match message. Read-only live audit: **0 Naruto sealed references**, **1,584 Fusion World repeated-number groups all with distinct image URLs**, and **10,904 TCGdex Pokémon records with no image URL** (9,124 JP / 1,780 EN). Price coverage and publisher SAMPLE artwork are **not fixed** by this UI release; no source, image or price data changed. See [video review and safety](docs/SELLER_SEARCH_RECORDING_AUDIT_20261015.md) and release PR.

## 15 October 2026 — Free first-party Cardmarket 30-day fallback (release checks pending)

Without any paid source or retailer scraping, exact matched singles may use the official public Cardmarket `avg30` statistic where `trend` is missing/zero, retaining source date/FX, explicit 30-day aggregate provenance and `physical_valuation_eligible=false`. Nonfinite/corrupt trend cannot fall through; parallel, language and duplicate identities remain blocked. Applies to One Piece/Dragon Ball and English Pokémon bulk references, with foil slots only where individually supported. No new prices have been imported yet; do **not** count hypothetical matches as live gains or force the scheduled refresh while Supabase Free storage remains near the limit. See [design and tests](docs/FREE_CARDMARKET_30DAY_GUIDE_FALLBACK_20261015.md) and release PR.

## 15 October 2026 — Free database bulk-pricing capacity guard (release checks pending)

Read-only checks confirm database **405,499,027 bytes** (Free allowance 500 MB), and 50,378 fresh history rows from the latest complete reference job. To protect current values, ownership and checkout, the existing operations monitor now warns from **400 MB** and reports a critical failure from **450 MB** or read-only state. The existing daily catalogue refresh skips bulk imports at **≥400 MB** rather than risking another data-capacity shutdown; it resumes below the threshold after verified archive cleanup. No history is deleted, archived or rewritten by this guard. Temporary stale prices are preferable to corrupt/unwritable inventory; the original seven-day source-age labels stay truthful. No new paid service/DB migration/worker. See [guard and verification](docs/FREE_DB_PRICING_CAPACITY_GUARD_20261015.md) and existing [history archive runbook](docs/REFERENCE_HISTORY_ARCHIVE_RUNBOOK.md).

## 15 October 2026 — 95% global physical-card pricing acceptance target

The founder set a **95% credible GBP price coverage** requirement across the entire global card reference library, not just owned inventory. Live evidence baseline: **40,443 / 67,060 physical references (60.31%)**; at least **63,707** priced identities are required, so **23,264** additional eligible prices are needed. The excluded digital Pokémon Pocket cohort contains 2,480 references. Missing: 13,064 needing permitted external evidence (including 7,166 Naruto), 9,358 unresolved exact provider mappings, 4,167 without exact quotes, and 28 US-only contexts. Existing daily coverage reports now calculate the exact target, shortfall and per-game/language progress without counting fabricated/stale/USD asking prices or changing physical stock. **Target is NOT met; this PR does not add new source prices.** See [scope, safety and source plan](docs/PRICING_95_PERCENT_COVERAGE_20261015.md). CI/deployment verification must finish before claiming release.

## 15 October 2026 — Unified inventory copy quantities

Matching raw cards and sealed products now share one inventory entry with a quantity in Seller Hub and Founder HQ. Exact printing/language/condition/seal boundaries remain; graded or certificate-bearing copies stay individual. Groups paginate before copy loading, and management still selects a physical copy. Market values render immediately per copy with their existing evidence labels. Read-only production audit: **614 copies → 557 entries**, removing **57 repeated tiles** across **43 groups** without merging/deleting stock or changing channel quantities. Full local backend/JSDOM checks passed; PostgreSQL, Chromium/WebKit and deployment gates tracked on the release PR. See [rules and evidence](docs/INVENTORY_COPY_QUANTITIES_20261015.md).

## 15 October 2026 — Immediate shared prices across search, sets and inventory

Inventory grid/table now render the shared price already in their first response. Search and set cards reuse eligible existing evidence across exact canonical/reference identities; explicit SuperRare/SR and SecretRare/SEC spelling aliases no longer block matches. Production-data comparison restores **27 additional catalogue displays** (24 provider entries, 3 canonical entries), without inventing values, choosing parallels or assigning ownership. Value sorts resolve these references before pagination. Indexed OP11-101 lookup returned the same five rows in **14 ms**, versus **3,036 ms** before (database execution sample). Existing global source gaps remain; no all-card completion or upstream quota recovery is claimed. See [evidence and release gates](docs/IMMEDIATE_MARKET_PRICES_20261015.md); final CI/deployment receipt is on the release PR.

## 15 October 2026 — Missing inventory reference display repaired (release checks pending)

The inventory resolver did not read the catalogue guide caches and hid near-mint comparisons for unfinished copies. A separate display-only reference now surfaces eligible dated guides/ranges and near-mint comparisons, while preserving physical valuation, recommendation and Store Price fields. Historical values remain visible with a **Last known** date when stale. Live-data replay restores **7** previously blank copy displays, including both Capone copies: **340/614** now have a current value or labelled comparison; **333** remain in existing valuation totals. **274 inventory copies and 26,617 physical catalogue references still lack eligible current values.** No all-card completion is claimed. No source subscription, schema or production financial write. Full local backend suite: **5,884 passed**; CI/deployment gates tracked on the PR. See [audit and acceptance](docs/INVENTORY_MARKET_DISPLAY_20261015.md).

## 14 October 2026 — Inventory cards and mobile actions cleaned up

The seller screenshot exposed unstyled native buttons and card contents wider than their clipped containers. Inventory cards now use one compact **Manage** action plus an accessible 44px refresh control where available. Text stays inside each card, actions align at the bottom, market/store prices have a clearer hierarchy, and the inventory panel no longer receives duplicate mobile padding. The search/import/view toolbar also keeps its controls in deliberate rows instead of stretching the refresh button across desktop.

The existing real-browser check now loads the collector presentation, exercises 320/390/430/1440px layouts, checks each card's internal bounds and touch targets, and verifies refresh failure/retry behavior. The inventory CI workflow covers Chromium and WebKit. Local seller interaction checks (31 scenarios) and focused portal/sealed tests (48) pass. This is a presentation change in the existing Seller Hub; release verification is recorded on the associated PR and Railway deployment.

## 14 October 2026 — Archive moved to the correct Drop Rate account

The price-history archive is now private to **dropratetcg@gmail.com**, in the [Drop Rate archive folder](https://drive.google.com/drive/folders/1NhFIsWesgxlf059UMdx65ps9kFMqQeO9). The complete 70,408,023-byte / 722,511-record archive passed a fresh download SHA-256 and ZIP CRC check at **17:54:22 UTC**. The earlier part and corrected receipt also passed readback checks. The database archive registry now points to the new file with original content/restore evidence preserved; misplaced JUSO copies were removed afterward. The runbook requires explicit connection-email and destination-owner verification before future uploads. No current-price, inventory, schema or runtime change. See [account correction evidence](docs/DATABASE_READ_ONLY_INCIDENT_20261014.md).

## 14 October 2026 — Free database archive and space recovery verified

All **722,511** original price-history records are preserved in a private **70.4 MB Google Drive archive**, with full typed restore verification and fresh upload/download SHA-256 verification. Guarded reclamation committed at **17:04:18 UTC**. Database usage is **321,334,419 bytes (321 MB)**, down from **1.51 GB**; **1,189,609,472 bytes** of history storage reclaimed. All **614 inventory rows**, **69,538 card references**, and all three current-price caches are preserved; full-row cache/inventory checksums match. Supabase remains on **Free**, with normal default read-write mode. The FX-only duplicate-history guard and admin-only archive registry are applied. PR #643 merged; its readiness deployment exposed a pre-existing environment-dependent adapter test, now isolated and rechecked in this follow-up. Runtime deployment verification remains the final release gate. See [incident and archive receipt](docs/DATABASE_READ_ONLY_INCIDENT_20261014.md).

## 14 October 2026 — Missing-price sources checked; access trial prepared

Read-only source research reconfirms **40,423 priced / 26,635 unpriced physical references**; **zero new prices imported in this pass**. PriceCharting has exact Japanese sample pages but requires separate commercial display permission. Flipzi's tested Japanese Web Ivysaur exists in its catalogue with no returned RAW/UK quote; other Japanese quote coverage remains unverified. Naruto's public price index contains US asking prices, not eligible UK sold evidence. The existing Trawl feed's latest recorded failure is HTTP 429 after the measured free allowance exhaustion. Prepared 100 real unpriced discovery candidates and a bounded 100-query / 200-credit trial; **not executed, no paid plan activated**. Proposed Trawl Basic is USD $20/month, renewing monthly; commercial spend still requires founder approval. No runtime/schema/service/stock changes. See [source audit and access decision](docs/PRICING_SOURCE_AUDIT_20261014.md) and [candidate manifest](docs/PRICING_SOURCE_PILOT_20261014.json).

## 14 October 2026 — Masters rarity and leader pricing; printed-number search (verified live)

Worker revisions **21–22** recovered **745 additional GBP catalogue guide records / 670 distinct products**: 595 ordinary printings plus 150 faces for 75 two-sided leaders. Independent coverage **39,678 → 40,423/69,538**; Masters **4,416 → 5,161/9,002**. The remaining physical gap is **26,635/67,058 (39.72%)**; 2,480 digital records remain N/A. **All-card pricing is incomplete** where exact printing identities or eligible source evidence are unavailable. Printed-number Seller Hub searches now find Masters parallel printings with separate prices; changed rarity invalidates stale guides. PRs #638/#639, final pricing code `3ec3692ff6d95ecfcfd30a781184a3b5f9505410`; all seven final-head CI workflows passed, 5,854 local backend tests passed. Railway `55b50ac6-129b-4eb7-b8af-aed5e64e2910` SUCCESS; revision 22 COMPLETE at **07:01:26.380611 UTC**, zero provider failures/conflicts. Live readiness and production catalogue SQL readbacks pass. Inventory **614 / 327 stored values** and owner/status/Store Price fingerprint unchanged. No new service, source subscription, schema or stock publication. Detailed counts, exact product proofs and remaining requirements: [14 October live receipt](docs/PRICING_RECOVERY_LIVE_RESULTS_20261014.md).

## 13 October 2026 — Expansion and deck pricing recovery (verified live)

Reference worker revision **20** recognises 28 Masters expansion/anniversary/expert releases and nine exact One Piece deck labels that the earlier parser skipped. **Verified live gain: 471 supported GBP references** (396 Masters, 75 One Piece), from **39,204 to 39,675/69,538**. Cumulative recovery **5,703** from 33,972. Remaining physical gap **27,383/67,058 (40.83%)**; 2,480 digital records are N/A. Full reference identity, release/category, printed number and ambiguity checks remain required; all new quotes are explicitly excluded from physical-copy valuation. PR #636 / `e3a2ff802daf361fab748b983785d23d87c29ca0`, all four applicable CI workflows and **5,805 local tests** passed. Railway `737c3c71-8901-42a3-a1f7-d434995a0664` SUCCESS; revision 20 COMPLETE at **23:32:25.882622 UTC**, zero provider failures. Seller Hub's shared catalogue SQL returns recovered examples with original source timestamps. Inventory **614 / 327 stored values**; owner/status/Store Price fingerprint unchanged. No new source, schema, service or subscription. See docs/SUPPLEMENTAL_RELEASE_PRICE_RECOVERY_20261013.md and docs/PRICING_RECOVERY_LIVE_RESULTS_20261013.md. All-card pricing remains incomplete where exact mappings or eligible source quotes are unavailable.

## 13 October 2026 — Pricing recovery verified: 5,056 additional records

The session's deployed repairs are verified live at **39,028/69,538** priced card references, up **5,056** from 33,972. English physical Pokemon is **20,472/21,290 (96.2%)**. Remaining: **28,030 physical references** without eligible values and **2,480 digital Pocket records** explicitly N/A. **All-card pricing is not complete**: unresolved exact printings and missing source evidence are recorded in docs/PRICING_RECOVERY_LIVE_RESULTS_20261013.md with per-game counts and concrete requirements. Existing daily workers contain the fixes; no new services/subscriptions. Owner/Store Price/status fingerprint unchanged, physical inventory **613 / 327 valued**.

## 13 October 2026 — Masters paired leader-face reference recovery (verified live)

Worker revision **18** adds a separate guide matcher for official English Masters leader front/back records. Both exact names must appear together on one Cardmarket product in the independently confirmed release. Both official records must share the exact collector number/rarity, declare LEADER/OFFICIAL_CHECKLIST, and use the matching official `.png` / `_b.png` image identities. All same-name, third-face, parallel, product and release collisions still block. Current export replay finds **344 matched face records**, including **314 previously unpriced positive candidates (157 two-sided cards)**; read-only production checks confirm required official metadata for all 314. These are reference records, not 314 new physical cards. New quotes record both face IDs and remain ineligible for physical valuation. Baseline **38,684/69,538**; actual live lift remains an acceptance gate. See docs/MASTERS_PAIRED_LEADER_PRICE_RECOVERY_20261013.md.

**Verified:** PR #631 / `9a7096e498c59019bdd2a57c750a46a7655eac1c`; all four applicable CI workflows and **5,750 local tests** passed. Railway `3904737b-3d75-463d-b3b4-1f238a52cc13` SUCCESS. Revision 18 COMPLETE at **18:06:15 UTC** with no provider failures. Actual net lift **344 face records / 172 paired card identities**, including 30 with eligible foil-field quotes beyond the conservative normal-trend replay. All 344 are excluded from physical valuation. Global **39,028/69,538** and owner/Store Price fingerprint unchanged.

## 13 October 2026 — Pokemon numeric-level and explicit product-ID recovery (verified live)

Worker revision **17** fixes numeric `Lv.50` name metadata while preserving `Lv.X` and printing suffixes: real-source replay identifies **612** additional previously unpriced candidates. The verified existing CardTrader connection now supplies explicit collector-number/singleton Cardmarket product-ID mappings across complete English Pokemon checklists, replacing the read-only eight-set probe. Prices still use the current Cardmarket export and ECB FX; all new quotes remain reference-only. Duplicate prints, conflicting cross-IDs and cross-release reuse fail closed; outages preserve prior dated bridge evidence. No subscription, source credential, schema or service added. Baseline **35,152/69,538**; bridge net gain requires live readback. See docs/POKEMON_IDENTITY_PRICE_RECOVERY_20261013.md.

**Verified:** PR #630 / `9047b2acb4e0ae3bed120feba8d85d63853b1c63`, all four applicable CI workflows successful. Railway `e4e015a0-d9ff-42c3-bdc4-01ca075159bc`, revision 17 COMPLETE at **17:54:00 UTC**, no provider failures. CardTrader checked 100 releases with 103 calls; one cross-source conflict rejected. Actual global coverage **38,684/69,538**, net release gain **3,532**, cumulative session gain **4,712**. English physical Pokemon **20,472/21,290 (96.2%)**. Remaining physical gap **28,374**, digital references **2,480**. Inventory **613 / 327 valued** and owner/Store Price fingerprint unchanged.

## 13 October 2026 — Existing CardTrader identity coverage verification (verified)

Before introducing a paid feed, worker revision **16** adds a bounded read-only probe of the existing CardTrader connection for eight high-gap English Pokemon releases. At most ten read requests verify explicit collector numbers, singleton Cardmarket cross-IDs and exact source identities. Reports contain only public identity examples/counts, no credentials, and the probe writes **zero prices or mappings**. This is coverage investigation, not a claim of new values. See docs/CARDTRADER_REFERENCE_COVERAGE_PROBE.md.

**Verified:** PR #629 / `bf6911c0f5c7fa86eecc5e11088ada569c121858`, all five CI workflows successful, Railway `edc25f5c-3a59-4f62-937b-e72139200ba0` SUCCESS. Revision 16 completed at 17:29:42 UTC, ten provider calls, zero diagnostic price writes. Existing CardTrader exposes exact number/cross-ID data, including 207 XY and 90 BW promo identity candidates. These counts are not price gains.

## 13 October 2026 — Fusion World exact-number guide recovery (verified live)

Found and fixed a second coverage defect: the existing general name matcher rejects distinct Fusion World collector numbers sharing a character name. An additional reference-only matcher uses exact English release/name/number, counts all official and market printing collisions, rejects unsupported source suffixes and requires the official base identity. Read-only replay finds **422 previously unpriced positive guides** across FB01–10 and SB01–02; **475** additional exact matches include currently absent quotes. Reuses existing source downloads and worker revision **15**, with explicit recovery/conflict receipts. New guides cannot value physical stock. Full backend suite **5,675 passed**; live release gates pending. See docs/FUSION_NUMBER_PRICE_RECOVERY_20261013.md.

**Verified:** PR #628, commit `65c887a6e3e9a1d718dea3d1d8f386a1255a2c98`, all four CI workflows successful, Railway `b2751be0-4c09-4d24-b48b-c8042e7648ce` SUCCESS. Revision 15 COMPLETE at 17:15:57 UTC with **422** new Fusion prices and no provider failures. Global **35,152/69,538**, total session gain **1,180**. Physical gap **31,906**, digital references **2,480**. Inventory 613 / 327 valued and owner/Store Price fingerprint unchanged.

## 13 October 2026 — Catalogue release aliases and physical/digital coverage (verified live)

Current live baseline **33,972/69,538** positive GBP card references/guides. Full read-only replay of existing Cardmarket exports and original database checklists found **758 previously unpriced candidates**: 416 Pokemon EX, 300 Dragon Ball release-title corrections, 42 One Piece PRB reprints. Scoped release aliases preserve game/language/printing uniqueness and original quote identity; newly recovered guide types stay outside physical-copy valuation. Existing worker revision **14**, no new service/provider/schema or owner/Store Price/Shopify writes. Coverage explicitly identifies **2,480 TCG Pocket digital records** and provides a separate physical denominator without removing records or counting N/A as priced. Full CI, deployment, revision-14 receipt and post-write counts remain acceptance gates. Details: docs/CATALOGUE_RELEASE_PRICE_RECOVERY_20261013.md.

**Verified:** PR #627, commit `99f8a18564df969deb3f8f93ce05dcc0f6788b3d`, all four CI workflows successful, Railway `02253a7a-5418-4d2c-a69e-8c0fbcf649ee` SUCCESS and readiness healthy. Revision 14 COMPLETE at 17:05:55 UTC with zero provider failures. Actual coverage **34,730/69,538**, gain **758**; **32,328** physical references still unpriced plus **2,480** digital. Inventory **613 / 327 valued** and owner/Store Price fingerprint unchanged.

## 13 October 2026 — English Dragon Ball Masters high-gap Cardmarket price recovery (release checks pending)

A separate exact-identity adapter for seven previously unpriced Bandai English Masters release families (Draft Box 04–06, three Themed Boosters, Battle Evolution Booster) reuses the *existing* Cardmarket game-13 daily products/price-guide and ECB FX. Verified read-only replay of **902 official reference records** against Cardmarket's 13 October product export found **579** unique market product matches and **558** eligible positive GBP guide candidates: 85 Dragon Brawl, 156 Divine Multiverse, 122 Giant Force, 58 Tournament of Power, 38 World Martial Arts, 50 Clash of Fates and 49 Battle Evolution. Original printed collector number (including two-digit EB1), exact official full set/name, both card/market uniqueness, independent release expansion/category and alternate/promo/front-back collision checks remain mandatory. This is a *source guide*, not an independently verified sold/graded/condition price. The reference job advances revision **12→13**; no new source, scraper, service, schema, Shopify publishing or owner/asking-price changes. The pre-release global denominator was **33,393/69,538** references with positive GBP quote/guide and **613 physical items / 327 valued**. **The 558 are replay candidates; do not claim live coverage gain until reference refresh, full CI, deployment and readback.** See docs/MASTERS_HIGH_GAP_CARDMARKET_BATCH_20261013.md.

## 13 October 2026 — Larger pricing batches: multi-set Fusion World (implementation; release evidence in PR)

Moved from one-set FB01 matching to **ten official Japanese Fusion World FB02–FB11 releases in one bounded batch**, processing 1,585 global reference identities (1,263 independently identified base-print candidates) using existing first-party Cardmarket game-13 source downloads and existing daily reference worker revision 12. Original English/Japanese Bandai IDs, printed numbers, official titles, unique source region IDs and exact market products are all required; alternate arts, promos, malformed/unpriced duplicates and conflicting expansions fail closed. Each resulting GBP quote remains `MIXED_NON_ENGLISH_REFERENCE`, physical valuation ineligible, *not* a verified Japanese sold/condition price.

Actual source snapshot before release has positive regional prices largely for FB02–FB05; FB06–FB10 Non-English region expansions have no listed singles and FB11 has no positive guide trends. **Processed volume is not newly priced output** and this batch cannot honestly promise 1,000–2,000 new valuations without genuine upstream data. Per-set receipt separates `checked`, `base_candidate_count`, `unique_market_matches` and `priced`. No new provider, service, schema, workflow, owner, Store Price, Shopify or settlement write. Prior global GBP references: 33,096 of 69,538. Full source and acceptance: docs/MARKET_VALUATION_BATCH_02_1585_JP_FUSION.md. Do not claim production coverage lift until the actual reference job completes and the database is re-read.

## 13 October 2026 — Market value in batches: Batch 1 (Japanese Fusion World FB01)

This intentionally limited recovery reads existing Cardmarket game-13 first-party guides, matches only exact official Bandai FB01 Japanese base-print references and independent English counterparts, then selects a uniquely identified **Non-English** regional marketplace product. Quote provenance explicitly states `MIXED_NON_ENGLISH_REFERENCE`, `physical_language_confirmed=false`, `physical_valuation_eligible=false`. No Japanese sold or graded value is claimed. Prior global measured coverage **33,010/69,538** cards, JP Fusion World **0/3,227**; up to 88 unique positive-priced Non-English regional marketplace products could potentially qualify before strict official double-checklist matching, which must be measured in actual production readback. Existing reference job revision 10→11, no new providers, paid APIs, services, workflows, stock owner edits, store-price change or Shopify publishing. Tests/rollout/remaining gaps: docs/VALUATION_BATCH_01_JP_FUSION_FB01_20261013.md; **not complete until CI, deployed job and real reference increase are verified**.

## 13 October 2026 — CRITICAL One Piece source-language isolation and data containment (release gates separate)

After PR #620's Japanese/non-English guide backfill, read-only live pricing evidence exposed a collision: **454** Japanese cards had inadvertently inherited **English Cardmarket guide products** via the fallback dictionary keyed on the same provider ID. We caught it before signing off the 1,424 legitimate regional source matches. **Contained in production:** the 454 erroneous current quote values were atomically nulled with exact-source/role/match-basis criteria, historical provenance preserved by the existing audit trigger, and a newer checked_at preventing stale imports from restoring them. Verified current Japanese One Piece: **1,424** legitimate distinct Non-English/Asia-region guides, **0** English-only fallback quote rows; 454 invalid historical records retained for audit (do not use them as legitimate market history). No owner/Store Price/Shopify/finance mutation.

Permanent fix: explicit separate EN vs JP product selection (an unmatched Japanese record cannot inherit an English price), plus new PostgreSQL CHECK requiring explicit Japanese-language provenance for **Japanese One Piece Cardmarket bulk price guides**. Add regressions for real starter and wrong-release provider-ID collisions; bump maintenance revision 9→10 to re-evaluate 4,480 JP rows. The migration must be applied with Supabase.apply_migration only after CI and a zero-violations read-only production preflight. The constraint persists across application rollbacks as a safety guard. See docs/JAPANESE_SOURCE_LANGUAGE_ISOLATION_20261013.md. All PR/CI/deploy/later receipt evidence recorded separately.

## 13 October 2026 — One Piece Japanese reference-guide recovery from existing Cardmarket public feeds (release acceptance separate)

Measured a new high-yield, independent regional source match instead of assigning English prices to Japanese cards. An actual **read-only replay** of 3,931 Japanese/English official One Piece base references against current first-party Cardmarket game-18 downloads identified **1,424 unique positive-priced Non-English/Asia-region marketplace products** across EB01–03 and OP01–14. Every match requires an exact official printed set code/card number/rarity, unique English label counterpart in official release, independently Non-English market expansion and one exact marketplace product; no pricing to ambiguity, parallels/reprints/promos or incorrect language. Source provenance is `MIXED_NON_ENGLISH_REFERENCE`, `physical_language_confirmed=false`, `physical_valuation_eligible=false` and displayed as "Non-English regional guide (Japanese language not verified)", **not a confirmed Japanese sold value**.

This reuses the existing One Piece Cardmarket importer, immutable `tcg.reference_market_prices`, shared account-level catalogue view and maintenance worker revision **9**, without another data provider, scraping, paid API, database migration, marketing workflow, physical inventory/ownership/Store Price or Shopify changes. Baseline before production: 69,538 global card references / 31,586 with positive GBP quote or guide; Japanese One Piece **0/4,480** priced, physical copies 613 / 327 valued. **The 1,424 read-only matches are potential additions, not live production coverage until an actual revision-9 refresh and readback.** The official public guide does not guarantee Japanese-only prices or license public commercial redistribution; confirm Cardmarket display rights. See docs/JAPANESE_ONE_PIECE_REGIONAL_PRICE_BACKFILL_20261013.md. All final CI/deploy/post-write evidence in PR release notes; ambiguity and remaining 37k+ unpriced records remain Action Required.

## 13 October 2026 — Price-engine source integrity hardening (PR release status separately)

Hardened existing v4 FastAPI/GBP algorithm without schema/provider/Shopify/ownership changes: reject invalid, stale, future and duplicate market observations; require UK eBay **SOLD** / regional Cardmarket non-ACTIVE price anchors; count independent source sale IDs instead of claimed sample size; fail closed on contradictory IDs, missing physical-language/condition, nonfinite policies and active-only price data; detect volatility across sales inside a single eBay source. Reference guides remain labelled estimates; no guide/active-only automatic publishing even when multiple sources agree. Include `ruleset_revision=2026-10-13-source-integrity-1` in future calculation evidence while preserving database-compatible `algorithm_version=drop-rate-market-v4`. Local price-engine and 4,096 deterministic adversarial stress cases pass. Live acceptance requires exact-head backend/DB CI, successful Railway deploy/readiness, unchanged owner/Store Price/status fingerprints and no mass repricing. This does **not** raise existing 31,581/69,538 reference GBP guide coverage by itself; missing exact data remains a separate issue. Details: docs/PRICING_SOURCE_INTEGRITY_20261013.md.

## 12 October 2026 — Measured Cardmarket coverage recovery and quota discipline (release verification pending)

Read-only public-provider replay against 90 existing **One Piece EB-03 Heroines Edition English** catalogue references: **0 → 44** uniquely proven Cardmarket product matches, all 44 with a published trend quote, English expansion 6449 only; the remaining 46 are ambiguous or unmatched. This repairs the exact EB03 release-name mismatch without relaxing printed set-code, product-category, full name/collector number, language, regional or multiple-variant checks. The existing reference maintenance revision increases to 8 to run the public-source refresh at the next normal worker pass. **44 is a replay candidate count, not yet a verified production row-count increase.** The prior 69,538-card global denominator and 286 missing physical inventory values remain the baseline until production readback.

The non-business-critical social eBay sold-data probe is now opt-in (`DROP_RATE_SOCIAL_SOLD_PROBE_OPT_IN=1`), preventing unrelated production deployments from burning exhausted Trawl provider credits. Actual eBay pricing/429 backoff remains unchanged. No new provider, paid subscription, Collectr price redistribution, secrets, n8n, ownership, Store Price, settlement, Shopify publication or database migration. See docs/ONE_PIECE_EB03_REFERENCE_PRICE_REPAIR_20261012.md; CI, deployment and live daily receipt verification are separate gates.

## 12 October 2026 — Remaining market-source gaps: global triage (no invented prices)

Read-only reference audit reconfirmed 69,538 card records, 31,537 with current positive GBP value or labelled guide, and 38,001 without one; sealed 2,726 / 3,879. At least **14,873** of the missing card references belong to Japanese One Piece (4,480), Japanese Fusion World (3,227), Naruto Legacy (4,487) or Kayou (2,679), for which no connected approved exact market GBP price feed currently exists. Daily reference-price jobs had completed; missing market data cannot be fixed through account-specific copying or arbitrary AI estimates.

This bounded release extends the existing source-independent catalogue coverage API with explicit `SOURCE_ACCESS_REQUIRED`, `missing_by_reason`, `by_status` and per-game status totals so owners/admins can distinguish licensing gaps from exact matching, quote-unavailable, stale and US-context-only records. Strictly positive fresh market references alone count as covered. No data mutation, external API expense, paid provider, migration, new workflow/service or Shopify publication. Commercial source evaluation and actual 100%-pricing ambition remain **blocked on permitted sources and real market observations**; see docs/MARKET_SOURCE_GAP_TRIAGE_20261012.md. Merging, CI and Railway verification need separate release evidence.

## 12 October 2026 — Seller manual search shared market follow-up (PR; deploy/acceptance tracked separately)

Corrected the existing owner card-correction search to read the same catalogue market selector as the global browser and scanner; exact unmapped provider references now return eligible GBP guides from already-persisted source rows, with source/freshness/identity checks and explicit "Shared guide" labelling. Both owners see the same underlying reference or the same unavailable status; their ownership and asking prices remain private and unchanged. No new feed, provider, data backfill, schema, service or Shopify write. This does **not** close the 38,001-card genuine source-coverage gap. See docs/OWNER_SEARCH_SHARED_MARKET_20261012.md. Exact-head CI, deploy and physical signed-in tests are separate evidence.

## 12 October 2026 — Shared reference market values across accounts (implementation; final release checks pending)

- Read-only database audit: 69,538 reference cards, 613 owned inventory items, 464 canonical products. 31,537 references have a positive GBP reference or guide; 38,001 do not. Guide availability is not verified exact-condition/sold value. Daily market and coverage jobs already run.
- Scanner previously only read canonical snapshots; 35 earlier unmapped provider candidates could have used existing positive reference quotes. This patch reads eligible owner-independent exact provider-print reference prices with source/identity/freshness checks and labels estimates as guides. Signed-in catalogue coverage API now returns global missing/priced counts.
- Zero-coverage card families include JP One Piece, JP Dragon Ball Fusion World and both Naruto systems. Truly verified 100% exact-value coverage needs permitted market observations; no placeholder, cross-language borrowing, unlicensed scraper or owner asking-price substitute. No database migration, new service, n8n workflow, Shopify changes, automated listing approval, ownership or financial writes.
- See docs/SHARED_CATALOGUE_MARKET_COVERAGE_20261012.md. An implementation entry is not evidence of deployment or signed-in multi-owner acceptance.

## 12 October 2026 — Scanner video regressions (implementation; release evidence in PR)

Bounded repair of existing raw/toploader/slab/sealed journey: server-side slab suggestion corroboration rather than bare-number first match; strict displayed-grade normalization with literal evidence preserved; explicit unverified manual certificate fallback when PSA API is unconfigured; shared authenticated reference artwork; manual capture/removal latch, same-item replacement photos, immutable save retries, cleared stale slab evidence and shared request deadline; readable candidate metadata and iPhone-sized form inputs. No model/provider/service, migration, data/price/ownership/finance write or Shopify publication. Missing translated catalogue aliases, reference images and valuation evidence remain unresolved rather than guessed. See `docs/SCANNER_VIDEO_REGRESSIONS_20261012.md`. CI/deployment and physical iPhone acceptance must be recorded separately; this entry alone proves neither.

## Current correction — automatic retail recommendation summary (12 October 2026)

## 12 October 2026 — Existing journey bug-fix QA (release verification in PR)

- Reproduce/fix late-account request replay and response/profile races in both hubs; preserve same-account token refresh and backend authorization.
- Fix stuck reopened imports, stale commit/resume/search completions and session-expiry cleanup without resetting real batches or changing idempotency.
- Use shared exact-profile artwork/market/recommendation reads in Channels as well as inventory; reflect unchanged eBay scope rather than displaying unsupported sync controls.
- Restore untouched retail suggestions after condition round trips; preserve manually chosen prices and collection-first intent.
- Add actual-script Chromium/WebKit race regressions, extend restricted PostgreSQL/signed test HTTP channel consistency checks, run existing Business and shipping/pooling safety suites. No production data/price/ownership/publication writes.
- See `docs/JOURNEY_REGRESSION_QA.md`. Full real-phone/scanner/checkout and signed-in production acceptance are NOT claimed by this pass. Release status requires exact-head CI and Railway/served-source verification recorded in the PR.


Recommendations now reuse the same eligible algorithm snapshot as the shared market value, rather than an empty per-copy cache. Overview sums recommendations independently of saved asking prices, with explicit copy/guide coverage; item details show and prefill eligible suggestions without overwriting chosen prices or publishing. Null/stale/wrong-profile evidence never becomes a guessed recommendation. Existing daily catalogue jobs already run; no new provider, scheduler, service, migration, rate-limit bypass or stock/price/ownership/finance backfill. #609 shared imagery and #608 collection-first intent are preserved. See docs/AUTOMATIC_RETAIL_RECOMMENDATIONS.md; exact tests, deployment and live readback belong in the release comment. This entry alone is not acceptance evidence.

## Current work — shared inventory references (12 October 2026)

Owner-independent catalogue image/value resolution is being consolidated for founder and seller inventory, details and current totals. Read-only response enrichment reuses existing catalogue snapshots/media, matches exact language/condition/grader/grade/seal, labels guides and stale/missing evidence, and preserves own costs, selling prices, history and physical photo privacy. No migration, provider/service, account merge, stock reconciliation, image approval or Shopify publication. Implementation/tests and deployment must be distinguished; exact release evidence is recorded on the associated PR after verification. See `docs/SHARED_INVENTORY_REFERENCES.md`. Unresolved exact artwork and missing market evidence remain explicit exceptions, not fabricated completion.

# Drop Rate — Live Build Status

## 11 October 2026 — Collection-first confirmation / separate selling (implementation; release evidence pending)

The existing scanner now saves a confirmed selection immediately, without a second whole-queue save or waiting for uncertain neighbours. Newly added scan/manual/CSV physical copies explicitly start DRAFT / PERSONAL_COLLECTION. Missing raw condition, acquisition cost, selling price or market value does not block collection admission. Canonical language is reused with conflict checks; owner/request locking and retry receipts prevent duplicate submissions. Pricing is no longer awaited inside the scan save transaction.

Seller inventory keeps selling fields and channel controls under an optional List for sale disclosure. Raw condition can be supplied in that explicit versioned listing request; existing raw/slab selling review and channel publication guards remain. Approved sealed selling is unchanged. No account merge, existing-row rewrite, overlapping-import reconciliation, media-policy relaxation, channel activation, product/theme publication, migration, new service or n8n flow. The existing overlapping Draft import and explicit hold remain separate work. #607 shared-artwork loading is preserved.

See docs/COLLECTION_FIRST_INTAKE.md. Source checks, real restricted PostgreSQL/signed HTTP, mocked browser tests, exact deployment/readback and real physical-device acceptance are distinct. PR release comment must record actual results; this entry is not evidence that deployment or signed-in production acceptance passed.


## 11 October 2026 — Shared inventory artwork delivery (implementation; release verification pending)

Founder HQ and Seller Hub now use the same bounded authenticated image route for provider-hosted inventory artwork. Catalogue artwork is selected by exact catalogue identity, independent of the uploading owner; physical photos remain restricted to the exact owned copy. Seller images load near the viewport, use trusted CDN fast paths, and fall back through the shared route/reference endpoint without forwarding credentials to providers. An additive SELECT-only policy covers approved shared CANONICAL_PRODUCT media, matching the already shared card-art concept. No inventory, import, price, ownership, listing or finance write. See docs/SHARED_INVENTORY_IMAGES.md. Real database and browser tests, migration, deployment, live source checks and real signed-in acceptance are separately reported.

## 11 October 2026 — Founder-only Business area (implementation; release evidence pending)

The user selected the Seller Hub visual approach with a dedicated Business area for the three verified founder accounts only. The first bounded release replaces the existing Accounts presentation with Overview, Sellers, Stock ownership and recorded Sales & payouts. Search active accounts by name/username and inspect their exact physical inventory; retain IDs, owners, history and private API/RLS boundaries. Ordinary sellers get no Business entry or API access; generic admin/metadata claims do not bypass the verified founder roster.

Reuses existing founder account APIs, adds explicit Business capability/guard and richer read-only stock fields. No new service, database migration, role enrollment, account merge, ownership change, import commit, publishing, money movement or n8n workflow. Counts are labelled stock records, not a deduplicated portfolio valuation; known overlapping Draft imports remain unreconciled. Existing founder tools remain linked with their existing scope. See `docs/FOUNDER_BUSINESS_AREA.md`; exact-head CI, deployment and real-session acceptance are separate evidence categories. Account consolidation and further editing functions remain later work.

## 11 October 2026 — Immediate recognised Seller Hub intake (implementation branch; release verification pending)

New explicit founder decision supersedes the all-rows-reviewed/manual-whole-batch rule: an intentional collection upload adds eligible >=95% matches directly to individually owned **Draft** inventory; uncertain rows remain for explicit confirmation and are added independently when confirmed. No Shopify publication, invented values, automatic owner transfer or financial changes.

The first admission method is unique complete exact catalogue identity, recorded as a deterministic rule result, NOT an empirically calibrated probability. No fuzzy/AI/CSV confidence is trusted. Grade, language, variant and physical safety checks remain. Replays/partial imports use the existing candidate receipts and unique physical source keys. One incremental Collectr snapshot per owner remains open until exceptions are confirmed/skipped; newer files cannot bypass it.

Fixes include narrow batch-processing column grants, replacing the invalid ownership-row lock with a transaction advisory lock, shared physical-copy insertion, clearer source/added/review counts and immediate inventory refresh. Existing pending real previews are not imported by deployment; their owner must explicitly choose Import/Add recognised cards. See `docs/IMMEDIATE_OWNER_IMPORTS.md` and #599. Exact-head CI, migration/deployment readback and authenticated production acceptance are separate gates; do not mark them passed merely from this entry.

## 11 October 2026 — Automatic owner NET Shopify shipping charge policy (in development)

- Founder confirmed **seller sees ONLY net shipping charge**. For customer-paid shipping (UK Tracked48 below £50, paid Tracked24, paid EU/international), Drop Rate retains checkout shipping and absorbs the carrier postage; seller postage debit **£0**. For **free UK Tracked48 at £50+**, actual verified Royal Mail label cost is deducted automatically from the responsible seller, no per-order consent button. Unknown actual label cost displays *Pending automatic charge*. No customer/label amounts disclosed to seller. Final carrier label purchase remains disabled until reliable carrier receipt journal/custody/FO split pilot.
- Added immutable company-only `tcg.shopify_delivery_accounts` (one true paid customer checkout charge/order), `tcg.shopify_delivery_refunds` (unique refund evidence), and `tcg.shopify_postage_actual_costs` (unique verified carrier cost and owner net charge), all restricted by platform-admin RLS, audit triggers and immutability triggers. `tcg.owner_net_shopify_postage` SECURITY DEFINER returns only one member's actual net charge/status.
- New `orders/paid` Shopify webhook classifies discounted real delivery + GB/Tracked48/service and net merchandise, creating **no owner SHIPPING_REVENUE**. Legacy existing orders retain their original accounting. Verified founder postage reconciliation automatically posts owner SHIPPING_COST only on eligible free UK Tracked48; company pays customer-paid labels, zero owner postage debit. Partially refunded/cancelled orders cannot add new seller postage cost.
- Seller Hub Fulfill displays one Net shipping charge, £0 for paid or pending automatic fee for qualifying free delivery until verified; no per-order seller approval. This change needs migration-first deployment, full CI and safe pilot. See [shipping finance policy](docs/SHOPIFY_AUTOMATIC_OWNER_NET_SHIPPING.md).

## 11 October 2026 — Seller Hub collection CSV/TSV Import

- User requested **Inventory → Import** menu supporting Collectr, Holodex and Other. Reviewed existing founder bulk CSV importer and found it already had deterministic Collectr snapshot deltas, candidate preview, exact-file fingerprint, manually resolved/skip rows and Draft physical item commit, but all import routes were founder-admin-only and its UI was never included in Seller Hub.
- Added an independent Seller Hub import menu + mobile-friendly lazy modal, per-format CSV/TSV upload, optional column mapping and game/language defaults, full paginated candidate preview, exact catalogue search and resolve/skip, owner-scope versioned commit, resume history and refresh inventory. Reuses the existing PostgreSQL import tables and business functions, not a new uploader.
- New **OWNER-only** `/api/v1/owner/imports` allowlist uses `require_owner_portal_request`; original founder `/api/v1/imports` and enrichment remain platform-admin. Collectr unmatched canonical identities are held for human review for Seller Hub users; no restricted seller can create a shared canonical card silently. Skipped new Collectr rows are excluded from future snapshot baseline to prevent false duplicate/imported quantities.
- Every committed physical copy remains owned by the importing account with a unique Inventory ID, state **DRAFT**, identity unconfirmed. No listing/Shopify sync, market valuation override, settlement payment, external seller activation, DB migration or automation created. Holodex formats may require manual header mapping; XLSX and remote account sync are not claimed. See [CSV import operating note](docs/SELLER_CSV_IMPORTS.md).
- Tests: owner authorization, Collectr re-export/duplicate/baseline behaviour, role-scoped catalogue creation, CSV/TSV mapping, live DOM import/review flow, existing real PostgreSQL and dashboard suites. CI/deployment pending before marking live.

## 11 October 2026 — Verify discounted Shopify delivery payment in seller shipping preview

- Corrected the owner shipping breakdown to read `ShippingLine.discountedPriceSet` (buyer delivery payment **after** shipping promotions) and `Order.currentShippingPriceSet` (current price **after discounts and refunds**), validating against Shopify's refunded total and each current shipping line. `Order.totalShippingPriceSet` can retain an original higher rate and must not be assumed to be what was paid when Standard becomes free from £50.
- Added regressions for free shipping discounted from a £3.95 original rate to **£0**, as well as mismatched current order/shipping line values blocking review. No carrier label, seller deduction, checkout setting or automated fulfilment was changed.

## 11 October 2026 — Seller Fulfill shipping cost visibility

- Founder's instruction: sellers must **see the amount they are being charged**, while customer shipping may have been paid at checkout. Added an owner-authenticated read-only preview that fetches **actual Shopify order shipping price/refunded price/service** and the seller's exact allocated `SHIPPING_REVENUE` / `SHIPPING_REFUND` ledger share. It displays a **verified** carrier expense and net shipping adjustment only if the existing postage reconciliation is complete; otherwise shows **Pending — not approved**, never £0 or a guessed carrier quote. Supports UK Tracked 48 free from £50, paid Tracked 24, paid Europe and paid selected International without hard-coding customer fees.
- In Seller Hub `Fulfill`, seller sees customer's whole checkout delivery charge separately from **their allocated share** (one Shopify shipping payment is not copied to multiple owners), alongside true verified label cost or Pending. Pure finance / SQL owner-scope / browser tests cover free/paid, mixed owners, partial refund and missing postage.
- **No new seller deductions, carrier label purchasing, new Shopify orders, payments or quote provider.** Shopify Shipping's supported Admin API does not provide a guaranteed upfront merchant label-price quote: this remains a transaction gate. Existing ledger rules may produce a postage shortfall on customer-paid orders with multiple senders; business policy for platform-funded shortfalls and seller charges on free-delivery orders requires explicit founder approval before changing settlement behaviour. See [seller dispatch design](docs/SELLER_DISPATCH_REVIEW_V1.md).

## 11 October 2026 — Seller Hub Fulfill wizard and Shopify packing slip (print stage)

- Founder requested **Fulfill** next to each seller's Shopify order, then printing both an official Shopify Shipping label and a Shopify-based packing slip, followed by dispatch. Added `Fulfill` to existing Sales → To Ship, displaying a four-stage mobile-friendly wizard (verify the exact Shopify paid order/allocated copy, print owner-only Shopify packing slip, Shopify carrier label, confirm dispatched). This reuses FastAPI, existing Shopify Admin credentials and Supabase physical allocations; no new primary navigation or service.
- `GET /api/v1/fulfilment/to-ship/{order_item_id}/packing-slip` rechecks current Shopify Order.lineItems and open remaining FulfillmentOrder quantities, queries only the active seller's exact physical order lines and constructs a **Shopify-order-derived** print document. Native Shopify Admin's packing-slip PDF is **not publicly exposed through the supported API**, so the document is generated by Drop Rate from Shopify order identity/title/SKU without buyer addresses or other sellers' inventory. Browser prints the document directly, with no unsafe HTML interpolation.
- **Important incomplete phase:** Shopify carrier-issued label purchasing, printing label PDF, post-print dispatch confirmation/tracking and verified postage allocation are still disabled. The native shipping label purchase API is integrated internally but cannot safely expose company-funded purchases before real rate/charge reconciliation, seller custody verification, durable duplicate-purchase protection and mixed-owner FulfillmentOrder split pilot. Printing the packing slip alone never alters Shopify or pays for a label.
- Add backend and UI tests for paid/refunded/closed/mixed-owner cases, one-of-two pooled variant physical owner, cross-owner privacy, print-generated DOM escaping, and duplicate identities; full CI and production proof pending. No database mutation, label purchases, Shopify orders, seller balances, auto-synced fulfilments, themes or n8n flows were changed by this phase.

## 11 October 2026 — Direct Shopify Shipping integration: live order verification and guarded label adapter

- Founder confirmed native Royal Mail labels are purchasable inside **Drop Rate Shopify Admin**, so selected **Shopify Shipping** (no separate carrier integration). The backend already uses Shopify Admin API **2026-07**; the ChatGPT connector's older 2026-01 GraphQL schema does not expose label purchasing. Official `shippingLabelPurchase` / `ShippingLabelPurchaseResult` adapter is implemented and unit-tested **without any public purchase route**.
- New owner-authenticated `GET /api/v1/fulfilment/shopify-status` checks the backend Shopify app credentials, store, scopes and API version. New exact-item `GET /api/v1/fulfilment/to-ship/{order_item_id}/shopify` verifies paid/cancel status and exact remaining Shopify FulfillmentOrder lines against the owner's PostgreSQL allocations; mixed-owner FO, same pooled variant sharing, partial refunds, invalid location and physical custody are blocked. No buyer address, secret, or other owner's data is exposed.
- Existing Seller Hub **Sales → To ship** gains real **Verify Shopify** and per-card **Check Shopify** actions with authenticated read-only API, no fake Buy label or Dispatch action. A real historical Shopify order was independently read as REFUNDED/CLOSED/0 remaining; no current live PAID orders exist to perform a purchased-label pilot. More validations in [dispatch design](docs/SELLER_DISPATCH_REVIEW_V1.md).
- **Purchase, print, tracking write and seller postage ledger remain disabled.** Shopify label purchase is an actual charge, async and may duplicate on blind retry; the Shopify Shipping label object has no auditable direct postage price. Need per-owner custody/origin, quoted-cost confirmation, persisted idempotent purchase journal, label PDF access permissions, split-owner fulfillment tests and real-order pilot before any billing or seller settlement change. CI must be green and production deployment independently verified. No Supabase schema migration, new Railway service, n8n activation or Shopify theme changes.

## 10 October 2026 — Shopify owner dispatch review v1 (PR in progress)

- Added owner-scoped read-only **Sales → To ship** queue inside existing Seller Hub. It lists exact paid or partly refunded Shopify physical order items from the canonical `orders → order_items → inventory_items → shopify_order_item_links` path, scopes every row to the active owner membership, and does **not** expose buyer shipping addresses or customer details.
- Every candidate remains **REVIEW_REQUIRED** or **AWAITING_DISPATCH_SETUP**; missing exact Shopify line, partially refunded order or inconsistent physical SOLD status creates explicit review blockers. A physical storage location does not prove dispatch custody. No fake Buy label, Dispatch, PDF or tracking action; public API capabilities are explicitly false until carrier, seller identity and remote Shopify FulfillmentOrder preflights are implemented.
- Current live database has **no eligible paid Shopify orders** (2 cancelled / 1 refunded); real end-to-end dispatch and mobile acceptance are still unverified. Adds pure blocker tests, fake owner-scoped SQL/PII tests and responsive Sales UI guard tests. No new DB migration, provider, Railway service, n8n workflow or storefront theme. See [seller dispatch v1](docs/SELLER_DISPATCH_REVIEW_V1.md).
- Future phase: custody/address policy, carrier-issued label quote/purchase, private PDF, verified tracking/partial Shopify fulfillment, exact postage reconciliation and controlled real-order pilot. **Do not mark full fulfilment complete** until those gates pass.

## 10 October 2026 — Launch shipping tariff agreed, Shopify API blocked

- Founder superseded the former **free UK shipping from £10** idea: launch target is **UK Standard £3.95 below £50 and FREE from £50**, UK Express £6.99, EU £14.99 and existing International £23.99, with *no free international threshold initially*. Shopify remains the sole source of buyer checkout rates. The £50 UK free condition and paid international options already exist.
- Attempted an exact UK-only `deliveryProfileUpdate` (4.99 → 3.95, preserving all other rates). Shopify rejected the write: `This method definition cannot be updated because it uses new configurations that are only available through Shopify's updated APIs.` The connected schema exposes legacy fields only. **No Shopify price was changed**: live UK Standard still **£4.99**, free from £50, Express £6.99, EU £14.99, International £23.99, confirmed by full independent readback. Admin/updated-API edit and UK £49.99/£50 checkout tests remain mandatory.
- Added pure multi-seller/postage examples to existing deterministic finance tests. Seller-funded *actual* label expense is assigned only to the verified physical sender; customer shipping revenue is allocated once; a missing invoice blocks settlement. The shown Royal Mail 50g/£2.95 calculator is illustrative, not an approved packing weight/quote: 25×2.3g cards alone are 57.5g. No carrier labels/accounts, addresses, owner deductions, payments, production database, shipping configurations or new automation were changed. See [shipping plan](docs/SELLER_WHATNOT_AND_SHIPPING_FULFILLMENT_PLAN.md).

## 10 October 2026 — Seller Hub quantity-control video bug: proposed count and actual save

- In the supplied 9.6s signed-in iPhone recording, the OP17 group shows saved Qty 2. Tapping + or − only swaps a confirmation message; the central number remains 2, looking broken. Root cause: `owner-inventory.js` renders `copies.length` as immutable text and never shows the proposed adjustment. The confirmation routes exist, but this presentation hid the pending state.
- Fix the existing item dialog (no new API/DB): + previews **3, not saved**, − previews **1, not saved** for two owned copies; opposite arrow or Cancel returns to **2** with no network mutation. Exactly **one** separately tracked physical copy is changed per confirmation. Save returns from the owner-scoped existing `POST /copies` or `POST /withdraw`, then re-fetches saved quantity. Failed/ambiguous saves re-read actual owner stock and preserve the existing idempotent add-copy retry key.
- Newly added copies remain separate **DRAFT / PERSONAL_COLLECTION** items awaiting per-copy approval; quantity **on Shopify does not rise merely by pressing +**. The details view distinguishes awaiting approval from approved physical units, and Shopify stock is still governed by existing publication verification. Withdrawal continues through sale-intent protection and Shopify/other-channel reconciliation, not a guessed counter decrement.
- Unit/JSDOM, Android-sized and iPhone-sized Chromium fixture cases cover immediate preview, cancel/undo, no request until confirmation, owner-specific physical withdrawal, after-save server reread, no duplicate POST and failure replay. No live physical stock, Shopify inventory, payments, other owners, theme or settings are mutated during testing. Exact-head CI and deployment/read-back are separate acceptance gates.

## 10 October 2026 — Fresh Phase 2 system audit and shipping API boundary

- Updated the existing [Phase 2 production system map](docs/PHASE2_SYSTEM_MAP.md) rather than creating a duplicate: seven Railway services; 90 `tcg` Supabase base tables; 511 tracked physical items, 327 stored valuations and 507 PUBLISHED physical Shopify links. Both PSA-labelled prototype services remain retained per the founder's previous decision; diagnostics are not silently deleted.
- Independently verified the OP17 Shopify quantity-two listing at £10 with distinct preserved owner/inventory IDs and historic variant aliases. Reconfirmed UK delivery at £4.99 Standard, £6.99 Express, and free Standard at **£50 (not yet £10)**. The connected Shopify API is not suitable for a safe legacy-condition in-place change; documented a UK-only settings/API gate with £9.99/£10.00 checkout acceptance. No production state, customer orders, delivery zones, payouts or storefront publication changed.

## 10 October 2026 — Customer-paid delivery and actual seller postage allocation

- Founder confirmed: Shopify sets the customer's delivery charge; under £10 orders pay delivery, and when shipping is free the **actual carrier label price** is deducted from the responsible seller's proceeds. Customer-paid shipping contributes `SHIPPING_REVENUE` and actual label costs `SHIPPING_COST`, never a duplicate flat £4.99 debit. Existing deterministic finance functions already support this model; new pure regression tests cover free, paid, multiple-owner, shared-vs-separate parcels and still-unreconciled postage.
- Read-only Shopify live audit: General profile, UK Standard **£4.99**, Express **£6.99**, free Standard **currently £50**; EU **£14.99**, other international **£23.99**. **£10 threshold NOT live**. Shopify rejected the narrow `deliveryProfileUpdate` condition edit, and no shipping rates have been changed; UK versus worldwide applicability requires user confirmation before another live attempt.
- Shopify's stable API 2026-07 adds official asynchronous `shippingLabelPurchase` support, but the connected Shopify GraphQL schema does **not** expose the mutation; merchant terms, label purchase permission, shipping origin/custody and cost-before-purchase controls remain unsatisfied. The Seller Hub carrier-issued label and Shopify fulfilment workflow is still **NOT IMPLEMENTED** and must not be presented as operational. No address exposure, label charge, fulfilment mutation or vendor app installation occurred.
- Details in [shipping and Whatnot integration design](docs/SELLER_WHATNOT_AND_SHIPPING_FULFILLMENT_PLAN.md); no new DB tables, secrets, n8n workflows or inventory changes in this policy/test release.

## 10 October 2026 — Whatnot seller-account connection correction and shipping decision gate

- Removed the misleading Seller Hub Whatnot **Set up** action pointing to the Shopify app for the **company's unified Drop Rate store**. Owners must eventually authorise **their own Whatnot accounts** via seller-specific OAuth. Official Seller API is developer preview and does not accept new applicants; no credentials or merchant API access are available. Current state reports `DEVELOPER_ACCESS_REQUIRED`, `SELLER_OAUTH`, `sync_enabled=false`, with honest `Not available yet` UI. No fake connected listings or user credentials collected.
- Completed a read-only Shopify/DB shipping audit: Shopify grants `write_merchant_managed_fulfillment_orders`/read scopes, ownership and order-item allocation are deterministic in Supabase; however, there is **no owner shipment/label ledger**, no UK label provider/credentials on Railway, no approved label cost bearer, and no independent custody/dispatch policy for seller-held vs Drop Rate-held consignments. Real label purchase, PDF printing, carrier tracking and Shopify partial fulfilment remain **NOT IMPLEMENTED** and must not be presented as operational.
- The Phase 2 storefront-first launch/efficiency gates still apply; any activated shipping integration requires provider, payer, owner custody, permissions, quotes, refund/duplicate testing and explicit pilot authorisation. Plan: [seller Whatnot and shipping fulfilment design](docs/SELLER_WHATNOT_AND_SHIPPING_FULFILLMENT_PLAN.md). No new Railway service, automation, DB schema, Shopify theme or third-party owner activation.

## 10 October 2026 — Set artwork coverage audit and backend identity contract

- PR #577 previously corrected Seller Hub set-tile layout and removed the random-card-image fallback. A 10 October read-only Supabase audit still found only **161 / 1,449 provider/language set records** with matching exact-title logos: Pokémon English 159/220, Japanese 0/186, CardTrader unknown-language 0/459, One Piece 2/201, Dragon Ball 0/302, Naruto 0/81. These are catalogue *source records*, not deduplicated physical releases. The generic Eevee Grove A3b title image is due to a missing TCGdex logo mapping, despite external official artwork.
- The follow-up adds a registry mirroring existing permitted TCGdex and checked-in publisher set images, a deterministic backend set-artwork resolver, typed catalogue responses, and founder-only `/api/v1/catalogue-browser/set-artwork-coverage` diagnostics. New indexed images still require explicit set/game/language matching. Unknown assets fail safely to the game mark/Drop Rate placeholder. Original source/provenance is **not** a commercial licence grant. No DB, Shopify, inventory, theme, payout or new provider changes.
- The existing TCGdex refresh updates both backend registry and browser lookup; parity, RBAC, URL safety, no-card-preview and UI regressions have added tests. The source-by-source backlog, especially Japanese Pokémon, One Piece, Dragon Ball and Naruto, remains **open**, not falsely claimed complete. Eevee Grove's archived official logo is listed for rights review rather than silently embedded from a fair-use host. See [coverage and sourcing record](docs/CATALOGUE_SET_ARTWORK_COVERAGE.md).
- The unrelated two-identical-OP17-packs issue is still tracked separately in #576; quantity pooling must not be simulated by archiving a Shopify product without deterministic Supabase/order allocations. This work does not modify OP17.
- The Brand Redesign publishing gate remains in place. CI, production deployment/readback and signed-in handset checks remain required for the new continuation.

## 10 October 2026 — Two OP-17 packs published and branding verified

- Both requested Japanese OP-17 packs are **ACTIVE and published to Online Store**, at **£10 each**, with available/on-hand quantity **1 per exact listing** and zero committed. Shopify readback confirms the original product/variant IDs and SKUs, the single approved official image, and Sealed/One Piece collection membership. Backend links and the automatic worker are COMPLETE / PUBLISHED, with zero publication failures.
- The original copy remains `d715b0e9-b3c4-451b-a909-5fa233f8a0e5`; the one explicitly requested additional copy is `55fe97fc-7bfa-4a73-a269-664ec56d3004`. Both remain with owner `cba99d5c-fedf-4544-86aa-ab9a2785860f`, with unknown cost/storage preserved. The 509 unrelated inventory records retain fingerprint `b6c8fdfacd3b3c5b2890f44ec4adcf8e`.
- PR #574 merged as `a5adc8d46a7b0e0b3c144a6668c9d3714ad7ebc2` after all five exact-head CI jobs passed, including actual SQL publication/owner/actor tests. Migration `20261010154057_shopify_publication_actor` is applied with runtime execute retained and anonymous execute denied. Railway `000c5590-7fba-4ecb-bc6f-b51f2ffa2069` reached SUCCESS at 15:42:03 UTC; pre-deploy passed **5,070 tests** and readiness returned 200.
- The [listing brand standard](docs/SHOPIFY_BRAND_STANDARD.md) matches existing sealed-product copy and image presentation. Publication rejects changed copy/SEO/markup and any missing or unexpected image. The exact artwork was visually reviewed against representative existing products; no whole-store visual-audit claim is made.
- **Remaining setup:** Drop Rate Backend lacks Shopify `write_files`. Existing approved associations are safely reused; automatic attachment of new files requires a merchant permission grant and otherwise records PERMISSION_REQUIRED. No permission was silently granted, no new services or theme launch occurred, and no fresh signed-in phone acceptance is claimed. Full [publication evidence](docs/SELLER_HELD_SEALED_PUBLICATION.md) retains the failures and repairs.

## 10 October 2026 — Seller publication actor correction

- PR #573 deployed as `6062f10aae62067056b4a1048011329070c68b66`; all six CI jobs passed, Railway `6c1afe0d-755e-4942-a2f4-5f61dd5798bf` reached SUCCESS at 15:32:37 UTC, 5,070 pre-deploy tests passed and readiness returned 200. The exact OP-17 drafts now pass remote brand/stock verification with the approved image, £10 and quantity one.
- Persistence then correctly refused the founder actor under an obsolete rule requiring a PLATFORM_ADMIN membership inside the seller's owner account. The existing platform authority deliberately requires a founder to have exactly one founder membership, so adding a seller membership would invalidate it.
- Align both draft/published link functions with `tcg.is_platform_admin()` and require the supplied actor to equal the authenticated `tcg.current_user_id()`. Retain exact item/owner/version/sale-intent, remote product identity, event authorization and audit guards. No memberships, owners, RLS policies, grants or historical links change.
- Extend the disposable PostgreSQL gate to reproduce the original failure and exercise actual link functions as `tcg_api`, including cross-owner founder publication, spoofed actors, disabled founders, wrong owners, stale versions, changed intent, wrong remote IDs, retries and audits. Migration application and final publication remain pending. See [evidence](docs/SELLER_HELD_SEALED_PUBLICATION.md).

## 10 October 2026 — Approved-image retry and Shopify permission diagnosis

- PR #572 is deployed as `fb952da10921d26b8766aa8e4753af56887cf6c2`; all eight CI jobs passed, Railway `96921431-1654-488d-a929-ae3a82b89415` reached SUCCESS at 15:22:10 UTC, pre-deploy passed 5,063 tests and readiness returned 200. Branding uses the shared existing copy template and an exact approved-gallery check, including Shopify-equivalent HTML serialization.
- The resumed two-pack attempt exposed a separate missing permission: installed **Drop Rate Backend** lacks `write_files`. The explicitly approved file was attached to both existing drafts through the authorized Shopify connection and read back with its original media ID. No new products/copies or backend permission grants were made.
- Publication now reads existing product-media associations before writing. An exact existing association is reused; a missing association still requires `write_files`, otherwise the worker records `PERMISSION_REQUIRED` / `MISSING_WRITE_FILES_SCOPE` and remains incomplete. Exact full-gallery and copy readback still gate publication. This does not grant or bypass the missing scope; automatic attachment of new media needs the merchant to grant it.
- Follow-up tests/deployment and final two-pack publication remain pending. See [release evidence](docs/SELLER_HELD_SEALED_PUBLICATION.md).

## 10 October 2026 — OP-17 release resumed; automatic collection repair

- The seller requires strict consistency with existing Shopify products. Compared the OP-17 title/copy and exact artwork with live sealed-product references; preserve the shared template and clean product-led imagery. Add a durable [listing brand standard](docs/SHOPIFY_BRAND_STANDARD.md) and reject any unexpected Shopify gallery media, in addition to the existing title/description/SEO checks. Regression cases cover copy drift and missing/additional images.
- PR #571 merged as `5759a8b4a7b28ba68f6f3045a0570421d943e628`; all five CI gates passed. Migration `20261010145452_seller_held_sealed_publication` is applied. Railway `80f7bf34-ee2d-4c9f-9cb0-c308828b9e1f` reached SUCCESS; pre-deploy passed 5,050 backend tests, readiness returned 200 and live Seller Hub HTML/JS matched the release.
- Registered the exact READY OP-17 official catalogue image for the requesting seller. Added only the missing second physical copy under a persisted receipt; both are APPROVED / FOR_SALE at 1000p with unknown acquisition costs/storage retained. The exact-product shipping profile records a **15 g nominal product-weight estimate**, including measurement-source URLs and its exclusion of mailing packaging.
- The first live sync created two drafts but Shopify rejected manual assignment to the rule-based Sealed/One Piece collections. Those drafts remain unpublished, have zero stock, and are reused by deterministic handles on retry. Repair collection discovery to identify automatic collections and leave membership to Shopify; the existing draft/final readback must still verify every required collection. Heartbeats now report incomplete publication passes rather than healthy price-only results.
- Regression coverage includes automatic versus manual collections, missing automatic membership failing before publication, existing draft reuse and publication failures reflected in the heartbeat. Release/readback for this follow-up remains pending. No extra physical copies, store-price changes, unrelated seller activation or theme launch. See [evidence](docs/SELLER_HELD_SEALED_PUBLICATION.md).

## 10 October 2026 — Seller-held sealed publication correction

- The seller explicitly confirmed two Japanese OP-17 packs at the saved £10 price and reuse of the exact Seller Hub image. Replace warehouse-intake review with owner-scoped self-approval for verified intact sealed consignments; retain exact physical ownership, identity, media readiness and sale intent.
- Unknown acquisition cost/location remain unknown. Shopify omits cost; a restricted database exception preserves NULL in the immutable sale snapshot, and finance reports unknown profit without changing commission or payout proceeds. No historical financial records are rewritten.
- All 5,050 backend tests and 24 inventory UI scenarios pass locally. Exact-head CI, real PostgreSQL finance/owner checks, migration, deployment and two-copy publication remain pending. The exact official image is READY in Shopify; the owner/product shipping configuration is still being resolved. See [scope and evidence](docs/SELLER_HELD_SEALED_PUBLICATION.md).
- The Brand Redesign hold and other sellers remain unchanged.

## 10 October 2026 — Seller inventory controls deployed and verified

- The reported seller Inventory screen was read-only: no item details, price/approval actions or stock controls. Add an accessible detail dialog from grid/list views, exact reference artwork fallback, seller price editing, sale approval/review requests and the existing Shopify sync action. Keep founder-only physical approval and listing-media checks intact.
- Quantity changes create separately tracked unapproved copies with persisted retry receipts or withdraw the exact selected copy through existing channel protection before reducing active stock. Reject stale versions, cross-owner access and sold/reserved edits; never duplicate graded certificates or delete history.
- The pictured OP-17 Japanese pack has no assigned media, selling price, acquisition cost or storage location. An idempotent profile-only migration attaches the inspected official single-pack reference image; it does not approve a listing photo. Readiness blockers are visible in the detail view.
- PR #569 merged as `a40b733b7b0ab8d741840bcf5d57d2c965d1545b`. All five exact-head CI jobs passed: **5,030 backend tests**, full dashboard UI (23 new inventory scenarios), n8n image, real PostgreSQL/RLS and Chromium at 430px/1440px. Railway `ed11d7e3-3f23-4558-ac56-d9e881a88cb5` reached SUCCESS at 14:18:49 UTC, including the unchanged pre-deploy gates. Same-account token refresh preserves inventory reload; logout/account changes discard stale responses.
- The reviewed artwork migration is recorded as `20261010141736_inventory_op17_reference_artwork`. The exact live reference query now returns the official Japanese single-pack image. After release, all **510** physical items retain the same ownership/Store Price/status/sale-intent fingerprint; **447** media approvals remain unchanged. Health/readiness and page/assets return 200; deployed JS/CSS exactly match the release, and unauthenticated detail/artwork requests return 401.
- The reported copy still requires a selling price, intake review and an approved listing photo before publication. Browser checks used isolated fixtures; no fresh signed-in iPhone acceptance or real inventory mutation is claimed. See [scope and release evidence](docs/SELLER_INVENTORY_CONTROLS.md). No new service/provider or theme publication.

## 10 October 2026 — Market continuation deployed and verified

- PR #567 merged as `926745d2186ea37429601fa48c9c78fc8e6df257`. Railway `01247982-7743-422c-929f-9d5faf9c1bd2` reached SUCCESS at 13:29:36 UTC; readiness is 200 and unauthenticated catalogue coverage is rejected with 401. All four exact-head CI workflows / six jobs passed, including three real PostgreSQL suites. CI and unchanged pre-deploy gates passed **4,995 backend tests**; all dashboard suites passed.
- Revision 7 completed at 13:32:37 UTC with zero provider failures: all 23,770 English Pokémon, 4,527 English One Piece and 13,362 English Dragon Ball references were rechecked. Live coverage is **31,537 / 69,538 cards** (up 1,686) and **2,725 / 3,879 sealed references**. The actual Seller Hub catalogue query returns the recovered guides on four previously unpriced, unowned example cards. All reference identity fields remain complete.
- Physical valuation completed at 13:33:05 UTC: 244 guide bases across 463 canonical products, zero provider calls and zero Store Price updates. Exact before/after comparison finds **327 / 510 inventory items valued**, three newly valued copies, zero ownership/Store Price/status changes and zero changes to previously valued amounts or recommended prices. The receipt's 76 inventory updates include refreshed existing evidence, not 76 newly valued copies.
- The Shopify worker is healthy. Fresh remote checks of eight active listings across all four games match their exact linked variant/SKU and approved Store Price; the database records no selling-price differences. Daily refresh remains at 03:00 Europe/London, with immediate processing after seller For Sale approval and the minute recovery sweep.
- Remaining: **38,001 card references and 183 inventory copies lack usable values**; missing exact printing/language/grade sources, unsupported Japanese/Naruto references and eBay quota remain explicit. No fresh signed-in iPhone acceptance is claimed. The Brand Redesign launch hold, financial controls and seller asking-price policy remain intact. See [verified continuation evidence](docs/CATALOGUE_MARKET_CONTINUATION.md).

## 10 October 2026 — Market continuation: numbered and supplemental Dragon Ball releases

- Verified the previous handoff: PR #566 (`2267946`) is live on Railway `d6001a3d-c949-4254-8f10-8df8b347aa4c`, SUCCESS. Revision 6 finished at 12:53:20 UTC with no provider failures; coverage is **29,851 / 69,538 card references** and **2,725 / 3,879 sealed references**. All reference identity fields are present. Physical inventory remains 324/510 valued. The latest Shopify receipt is healthy, with no recorded approved Store Price differences.
- Fixed omitted `Series N Booster` names and full-release joins through ordinary Dragon Ball booster/box packaging. Added explicit Fusion World Manga/Story release/code parsing with reference-only physical guards. A full read-only replay finds **1,686 additional priced references** (1,587 Masters, 99 Fusion), retaining every one of the existing 1,841 Dragon Ball matches with identical marketplace IDs. No Story Booster increase is claimed.
- Coverage now rejects changed-identity bulk guides using the same condition as Seller Hub. Revision 7 resumes the existing daily worker using persisted detailed-cache progress. No new provider, service, migration, seller asking-price policy or storefront publication.
- Local verification: **4,995 backend tests**, all dashboard suites (39 catalogue scenarios), and the current first-party export/ECB replay passed. Exact-head CI, real PostgreSQL and production read-back remain required at this checkpoint. See [continuation evidence](docs/CATALOGUE_MARKET_CONTINUATION.md).

## 10 October 2026 — Starter references and full-catalogue catch-up

- A further read-only replay identifies 214 English One Piece and 86 Masters starter-card references omitted by booster-only release matching. Extend exact full-release/category matching for starter catalogues; duplicate expansions, regional products, alternate printings and incorrect numbers remain blocked. Starter guides explicitly stay outside physical valuation authority because deck finish distributions differ.
- Reference job revision 6 adds those matches. Successful bounded pages continue on the next worker tick rather than waiting the failure backoff; actual provider failures and interrupted work still wait an hour. Previously completed revision-3 card checks are reused after deployment.
- Follow-up exact-head CI and production read-back are required; the preceding database-wide deployment and measured checkpoint remain documented below.

## 10 October 2026 — Database-wide reference fix live

- PR #565 deployed as `5b991e959a25ecd2912e4da892dc7d1a61a67849`, Railway `ad6fb48b-897c-4771-a69c-14e3c8f63c7a` SUCCESS at 12:23 UTC. All six exact-head checks passed, including three real PostgreSQL jobs. CI and unchanged Railway pre-deploy gates each passed **4,929 backend tests**; dashboard UI includes 39 catalogue scenarios.
- The independent direct pass checked **all 23,770 English Pokémon references** and cached **9,258 guides**. Live total card-reference pricing rose **24,928 → 29,185 of 69,538**, including **4,257 newly priced references**. These counts describe the shared database, not inventory. All 69,538 card references and 3,879 sealed references have complete identifying/source fields in the full coverage receipt.
- Readiness is 200, the deployed catalogue JavaScript exactly matches the tested source and is served with `no-store`, and unauthenticated coverage access is rejected with 401. The new guide table has forced RLS and no anonymous/authenticated reads or API deletes; security findings are unchanged. No Railway changes remain staged.
- The revised detailed TCGdex pass is still RUNNING; 2,600 revision-3 checks had persisted at read-back. Do not claim the full detailed backfill is finished. Live read-only provider replay recovered labelled unlimited/stamped Charizard, Pikachu and Servine references. The existing eBay sold probe still reports a provider credit/rate limit.
- All owner/Store Price/status fields retain fingerprint `7db86dd9fbdb662b3f766ea08c14cee8`. Daily schedules, Shopify approval gates and the unpublished theme are unchanged. **40,353 card references still lack a GBP guide at this checkpoint**; unsupported sources, unresolved printing mappings and digital Pocket references remain explicit. See [full evidence and scope](docs/DATABASE_WIDE_REFERENCE_PRICING.md).

## 10 October 2026 — Entire reference catalogue pricing correction

- The acceptance scope is all 69,538 card references and 3,879 sealed references, independent of inventory. All card references have provider/printing/set/name/number/source fields; baseline GBP coverage is 24,928 cards. The 463 canonical products are not the whole database.
- Add independent daily Cardmarket Pokémon catalogue guides for unique names in complete matching releases, plus named TCGdex variant references. Preserve original source/FX evidence, separate physical pricing authority, immutable history and RLS. The complete English source replay finds 9,258 guides, including 4,257 previously unpriced references; deployment read-back remains required.
- Product Details exposes card/set references, marketplace IDs and variant labels. An authenticated full-catalogue coverage read reports every game/language, including unsupported and stale records. Existing eBay/physical valuation, Store Prices, Shopify approval gates and unpublished Brand Redesign are unchanged.
- Verification and exact-head CI/deployment gates are in progress. See [database-wide reference pricing](docs/DATABASE_WIDE_REFERENCE_PRICING.md) for matching rules, tests and the remaining Japanese/Naruto/digital-reference limits.

## 10 October 2026 — Pricing repairs verified in production

- PRs #562 and #563 are merged. Final application `6248f03f1820ad8485dfb0b47297f837f1c61860` is live on Railway `38d759f7-4cf4-4216-b284-015fab10e0f2` (SUCCESS, readiness 200). All four follow-up CI workflows passed, including actual PostgreSQL; both CI and pre-deploy passed **4,893 backend tests**. Infrastructure configuration and original financial/social checks are unchanged, with nothing staged.
- Cardmarket revision 4 completed at 01:24:35 UTC: 463 canonical products checked, 241 guide bases, eight further shared snapshots and six additional inventory estimates. Overall inventory coverage improved **251 → 324 of 510** (73 newly valued copies). Exact comparison confirms zero owner/Store Price/status changes across all 510 and zero value/recommended-price/snapshot changes among all prior 251 or the intermediate 318 valued copies.
- Reference pricing has **24,928 priced card references**, including 1,823 One Piece and 1,755 Dragon Ball. Sealed revision 3 completed at 01:24:55 UTC: all 3,878 sealed references checked, **2,717 priced**, including 246 Masters and 66 Fusion World, zero provider failures. The complete 73,416-reference coverage audit followed at 01:25:01 UTC.
- **186 physical copies remain pending:** One Piece 139, Masters 16, Fusion World 6 and Pokémon 25. Exact printing/grade/language mappings, source quotes and eBay sold-feed capacity remain gaps; no universal-pricing claim. Guides retain the existing v4 calculation and explicit Cardmarket estimate label, original source dates, no invented sold transactions and no automatic publication eligibility.
- Daily refresh remains at 03:00 Europe/London with recovery; approved seller Shopify processing is unchanged. No new paid service, selling-price change or theme publication. No fresh signed-in iPhone acceptance is claimed. See [complete release evidence](docs/CARDMARKET_MULTIGAME_REPAIR.md).

## 10 October 2026 — Multi-game prices live; sealed follow-up in review

- PR #562 deployed as `377c571a262332d962c5b9a3bf07b179c0b5f3fc` on Railway `25a62932-d944-428d-bbd8-423e9696682f` (SUCCESS, readiness 200). All five exact-head CI workflows passed, including PostgreSQL; CI and Railway each passed 4,874 backend tests. The additive migration is applied with SECURITY INVOKER, fixed search paths and no anonymous/authenticated execute grant. Security findings are unchanged from baseline.
- The reference refresh completed at 01:15:51 UTC: **1,823 One Piece, 1,124 Masters and 631 Fusion World references priced**, with zero provider failures. The full 463-product Cardmarket calculation completed at 01:16:15 UTC: 233 guide bases, 69 new snapshots, **67 newly valued inventory copies**, zero provider calls and zero Store Price updates.
- Inventory is now **318/510 valued**, up from 251. All 510 owner/Store Price/status fields and all 251 prior value/recommended-price/snapshot fields are identical in an exact row comparison. The remaining 192 copies are One Piece 145, Masters 16, Fusion World 6 and Pokémon 25; this is not universal pricing coverage.
- Follow-up repairs the existing sealed worker's Dragon Ball exclusion using already-saved explicit CardTrader/Cardmarket IDs, matching packaging categories and one shared game-13 download. A source replay finds 312 guides; production read-back is still required. Repeated matching collector numbers in imported card titles are normalized for comparison only; conflicting numbers, edition qualifiers and duplicate printing candidates remain blocked. No canonical identity is edited.
- Daily refresh remains 03:00 Europe/London with recovery. Seller prices/publication gates are unchanged, with no new paid provider, service or storefront launch. See [repair evidence and limits](docs/CARDMARKET_MULTIGAME_REPAIR.md).

## 10 October 2026 — Multi-game pricing repair: release candidate

- Confirmed Pokémon-only physical Cardmarket fallback, excluded older One Piece checklists and absent Dragon Ball bulk-price ingestion. Extend the existing daily pipeline with full-release/unique-print checks and separate normal/foil fields. Preserve One Piece rarity from existing full-pack downloads.
- Source replay finds 1,823 One Piece and 1,755 Dragon Ball reference guides. Physical estimates stay limited to exact supported English printings and confirmed ungraded Near Mint stock, with existing eBay priority. Ambiguous variants, Japanese translation/mapping gaps, slabs and inconsistent imported finishes remain unknown.
- Add a SECURITY INVOKER reference-cache/identity guard and enforce review mappings across providers. Original EUR/ECB evidence, zero-sale guide labels, owner isolation and seller Store Prices remain intact. No new service, paid plan or theme publication.
- Targeted and full backend tests passed locally before the final added foil-rarity guard; final CI, real PostgreSQL, migration, deployment and live read-back are release gates. See [multi-game repair evidence](docs/CARDMARKET_MULTIGAME_REPAIR.md).

## 10 October 2026 — Recorded catalogue repair deployed and verified

- PR #560 is merged as `e64a41122dc01c7862d19a0fbe4a1135ee5df070`. Railway deployment `b569a463-a4c8-4d53-991a-ec69dbbc30ca` is SUCCESS; readiness is 200 and the deployed browser asset matches the repository. Four current-head CI workflows passed, including real PostgreSQL; CI and Railway each passed 4,842 backend tests. Catalogue UI coverage is 37 scenarios, with 2,048 generated price-identity collision cases in the backend suite.
- Official discovery completed at 00:23:09 UTC: 520 printings across OP-15/EB04, OP-16 and OP-17, adding 365 missing English references. Daily reference pricing completed at 00:23:19 UTC with 316 Cardmarket guides and no provider failures. Per-set priced counts are 122/196, 97/155 and 97/169. Database-wide reference scope is 69,538 cards plus 3,878 sealed products.
- The recorded `Eb04 007` query now returns three English and two Japanese Zoro printings without the unrelated Bonney. The English SP has a £277.01 Cardmarket reference (product 904150, expansion 6492), independently of inventory. Ambiguous variants remain unavailable. Original EUR, source time and ECB conversion are preserved.
- Inventory stays 510 copies / 251 valued, with owner/Store Price/status fingerprint unchanged at `ab62e1122c7e51df7a2288288a3c3005`. The existing daily Pokémon worker refreshed 95 guide snapshots for the new UTC day; an audit confirms zero amount or quote-evidence changes. No new service, paid plan, schema migration or theme publication occurred.
- Image payloads sampled are 71–82% smaller; loaded nodes persist during pagination. The available browser remains signed out, so fresh iPhone end-to-end timing is outstanding. Older One Piece, Dragon Ball, Naruto and ambiguous printing mappings remain explicit pricing work. See [production evidence and limits](docs/CATALOGUE_MOBILE_REPAIR.md).

## 10 October 2026 — Recorded catalogue failures: release candidate

- Reproduced the two iPhone recordings against matching Railway request logs: reference images had a 1,728 ms median, the English EB04-007 Zoro printings were absent, and the newest reference rows had no pricing source. The earlier Pokémon price fill is now COMPLETE: 11,910 English and 9,440 Japanese references priced.
- Fixes preserve images on pagination, add bounded authenticated WebP thumbnails and shared HTTP connections, discover released OP-15+ English boosters, accept promo numbers and make full collector-number search exact. Rarity is searchable. Daily Cardmarket reference pricing now has an unambiguous release/printing matcher and protects against changed identities.
- Live source dry run: 520 official printings across three sets, 316 unambiguous Cardmarket matches, including the English Zoro SP. These are not yet production-refresh counts. Images tested are 71–82% smaller; cold mobile timing still requires deployed verification.
- Local full backend/UI suites pass, including 2,048 generated identity/collision cases and 37 catalogue UI scenarios. Current-head CI, real PostgreSQL and production read-back remain required before claiming release. No inventory/Store Price changes, new service, schema migration or theme publication are intended. See [recorded catalogue repair](docs/CATALOGUE_MOBILE_REPAIR.md) for evidence and the remaining multi-game price gaps.

## 9 October 2026 — Cardmarket fallback released and verified

- PRs #557 and #558 are merged. Final application commit `2d3d519e6624195581a56d191e5f15d1eb73e25a` is live on Railway deployment `526cd73a-947d-4aaa-a06a-c9b4153c8e8c` with SUCCESS status and readiness 200. Current-head backend/UI and real PostgreSQL checks passed, as did all 2,759 pre-deploy tests and the original financial checks. Original infrastructure configuration remains intact and nothing is staged.
- Revision 2's CARDMARKET_VALUES receipt completed at 20:10:23 UTC: all 463 canonical products checked, 164 exact guide bases/snapshots saved, 95 inventory copies updated, zero provider calls and zero Store Price updates. Current inventory coverage is **251/510**, up from 156/510. Shared catalogue evidence now covers 224 distinct products across both sources; guides remain independent of ownership.
- All 156 previously valued copies retained the same amounts and snapshot IDs (fingerprint `0f4f76adfd4a711cd0e1735c8ab66e4b`). All 510 copies retain owner/Store Price/status fingerprint `ab62e1122c7e51df7a2288288a3c3005`. The 95 new estimates have zero sold observations, no automatic publication, confidence 0.4904, matching current catalogue digests and valid shared-snapshot links. Their original source times remain 09:52 UTC, not the calculation time. The 164 new public observations retain unspecified source language/condition and are PRICE_GUIDE evidence.
- Pending physical copies remain **259**: One Piece 199, Dragon Ball Super 29, Pokémon 25 and Fusion World 6. Other-game mappings, grades, unsupported finishes and missing exact guides remain explicit gaps. The cache contains Cardmarket guides for 11,910 English and 4,590 Japanese Pokémon references plus 2,403 sealed references. The expanded reference fill is still incomplete after deployment interruption; its existing hourly continuation remains scheduled.
- Daily maintenance remains due at 03:00 Europe/London; approved For-sale Shopify processing retains its immediate wake-up and minute recovery pass. Cardmarket changes did not change seller asking prices or trigger price publication. Shopify read-back confirms Brand Redesign UNPUBLISHED and Horizon MAIN. No fresh signed-in/iPhone acceptance is claimed. See [Cardmarket release evidence](docs/CARDMARKET_VALUATIONS.md).

## 9 October 2026 — Cardmarket production permission correction

- PR #557 deployed successfully as `b0e9668` on `999d9e89-b8fd-4c45-be4c-8b172531a5bd` after all four current-head workflows, 2,759 backend tests and UI suites passed. The migration is applied, readiness is 200 and Brand Redesign remains UNPUBLISHED.
- The first calculation exposed a fixture/production grant mismatch: a catalogue `FOR SHARE` requires UPDATE, while canonical products are read-only to the API. The first product transaction rolled back; inventory remains 156/510 valued and there are zero committed Cardmarket catalogue snapshots. The failed receipt is retained.
- Revision 2 retains inventory locking and adds a catalogue ID/digest condition to the final owner/version-checked update, without expanding permissions. The real PostgreSQL fixture now uses production-style limited grants and checks a printing changed between selection and saving. The corrected head still requires CI, deployment and actual coverage read-back.

## 9 October 2026 — Cardmarket valuation fallback implementation

- The founder requested Cardmarket as an additional valuation source. The existing v4 engine now receives exact cached Cardmarket printing/finish guides through a catalogue-wide calculation and a labelled physical-inventory fallback. Fresh exact eBay values take priority; slabs, worn/unknown-condition copies, mismatched languages, ambiguous references and pending provider mappings are excluded. No new paid API, canonical approval or Store Price change.
- Cardmarket guides retain EUR/ECB provenance, mixed-language/condition limitations and original dates. They have zero sold transactions, confidence capped at 0.60 and automatic publication disabled. Public catalogue snapshots remain independent of inventory. Cached intake/manual recalculation works without another provider request, and daily receipts make coverage explicit.
- Inventory rows and portfolio totals label/count Cardmarket estimates. The source-labelled catalogue reader is security-invoker; the prior eBay helper remains intact. A pre-release read-only match check found 165 candidate catalogue guides before the final rarity check; actual post-deploy inventory coverage must be measured separately.
- Focused and full backend tests plus 34 catalogue UI scenarios pass locally. Expanded real PostgreSQL CI covers both workers, unowned products, stale updates, owner isolation, retry deduplication and immutable history. Current-head CI, migration, deployment and live read-back remain release gates. See [Cardmarket valuations](docs/CARDMARKET_VALUATIONS.md).

## 9 October 2026 — Catalogue refresh release verified

- PRs #551–#555 are merged. Final application commit `18c5a4e2272f948962840581337335037aa753de` deployed successfully as `4280c6a4-87b7-4a6a-9ea3-ba59c2fa159b`. Current-head Backend checks, Catalogue maintenance persistence and Independent catalogue valuations passed. Railway pre-deploy passed 2,728 tests; readiness returned 200 in deployment logs. Original financial/social checks and infrastructure configuration remain intact, with no staged changes.
- The revision-2 shared calculation completed at 19:16:47 UTC: 463 canonical products checked, 129 valued products/bases, 334 without sufficient current exact evidence, zero inventory rows read and zero provider calls. The 125 raw/sealed catalogue identities available before activation exactly matched the new reader's identities (zero lost). After that verification, `activate_catalogue_reference_values` was applied from `20261009185130_activate_catalogue_reference_values.sql`.
- Live function read-back uses shared snapshots and contains no inventory lookup. Forced RLS remains enabled; anonymous/authenticated Supabase roles cannot call the helper, and the API role cannot update/delete snapshots. Original provider-check timestamps remain 8–9 October, not the recalculation clock. All 510 physical inventory rows retain owner/Store Price/status fingerprint `ab62e1122c7e51df7a2288288a3c3005` (colon-delimited fields, pipe-delimited rows).
- All eight scheduled catalogue sources have a COMPLETE latest receipt. Current scope is 69,173 card references, 1,447 provider sets and 3,878 sealed references, all sealed references with artwork URLs. Current cached GBP guides cover 11,910 English and 2,510 Japanese cards, plus 2,403 sealed products. These are reference guides, not five-sale physical eBay valuations. The first expanded Pokémon fill was interrupted by deployment and is due to resume after its one-hour backoff; no claim of a completed full price backfill.
- Daily work remains due at 03:00 Europe/London; seller-approved For-sale transactions wake Shopify processing after commit, with the minute sweep for recovery. The latest idle Shopify receipt completed without candidates/failures; no new publication was manufactured. Brand Redesign remains UNPUBLISHED and Horizon remains MAIN. The current browser session is signed out, so this final release has backend/database/automated UI evidence, not fresh signed-in or iPhone acceptance.
- Remaining universal-pricing gaps are explicit: exhausted Trawl capacity, insufficient exact sold depth, missing product/finish/language mappings and a catalogue-only external eBay acquisition path. The new independent calculation reuses saved evidence; external eBay collection is still inventory-driven. TCGplayer exact-variant parsing is tested, including a read-only live response, but the production quote cache still contains zero TCGplayer rows until the expanded fill reaches eligible English references. No paid upgrade, asking-price change or eBay listing activation occurred. See [valuation review](docs/CATALOGUE_VALUATION_REVIEW.md).

## 9 October 2026 — Legacy catalogue evidence-basis compatibility

- PR #554 deployed successfully as `9777749` on `de7415b5-1687-4704-9b8d-063b05177faa`. All three current-head checks passed; the additive snapshot migration is applied. The reference-helper activation is deliberately held until coverage read-back is satisfactory.
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

# Product search and set browser

## Status — 2 October 2026

Released to both hubs at 15:03 BST through PR #498, after scanner PR #497.
The deployed main commit is `725fb745d5857a9a5ed51b2e46ad638091b2f8d2`.
The user requested the product-list/search structure in
their 77-second Collectr recording, in Drop Rate colours. The recording starts
with Sealed Only already selected; the cleared Quick Filters screen is the
default, not the initial filtered frame.

## Behaviour

- Both hubs expose Search and a Search products & sets shortcut beside scanning.
  Primary navigation is Home, Search, Scan, Inventory and More. Sales remains
  accessible under More; existing account and founder tools are retained.
- The unfiltered search screen shows game tiles. Selecting a game opens a
  two-column mobile product grid, with removable filter chips and Show Sets.
- Search browses the master catalogue by default, including items the current
  owner has never held. Ownership is an optional filter and a per-owner overlay;
  it never decides which games or default set tiles exist.
- Sets have a separate search, available language tabs, release dates when known,
  owned/known checklist progress and known inventory value. Sets without loaded
  card records remain visible with zero ownership and a checklist-unavailable
  note. Selecting a set scopes the product query by game, set, language and
  provider, and resets hidden product/watchlist/ownership filters.
- Product cards show artwork, identity, language/finish, available reference value,
  own quantity and an add button. Sort and Filter open sheets. Cards/Sealed and
  Owned/Not Owned are mutually exclusive choices; Clear filters returns to the
  unfiltered game tiles.
- Watchlist stars are stored per signed-in account on this device, up to 100
  product identities. This is not a synchronized cross-device watchlist.
- Adding requires explicit exact-product confirmation, condition for raw cards
  or sealed confirmation, and quantity. Each physical copy enters the existing
  manual intake as Draft with identity confirmation false. Graded additions route
  to the existing shared GRADED scanner/certificate confirmation flow.

`catalogue-browser.js` shares the scanner's account-bound request/refresh client.
Both entry points recreate clients after account changes. Pending reads are
aborted or ignored when the query/account changes. Logout destroys both surfaces.
Uncertain additions retain immutable per-copy request keys/bodies for retry;
confirmed copies are skipped. Finishing a batch permits a later fresh addition
of the same product. Pending additions are held in memory; refreshing or closing
the page discards them.

## Data and authorization

`/api/v1/catalogue-browser/{games,sets,products}` reads released reference cards
and existing canonical cards/sealed products. A canonical COLLECTION is displayed
as SEALED only when its stored profile identifies it as a sealed collectible.
This retains existing tins and sealed collections as well as packs.

Every route resolves active membership and founder roster authorization on the
server. Owned quantities and set values are restricted to that resolved owner's
inventory. No browser owner ID, price, grading or approval field is accepted by
the new intake request. Searches use bound literal terms and whitelisted sorts.
Reference printings share canonical owned counts only through verified provider
links or their complete exact previously selected identity. Ambiguous links are
not merged. No name/number-only shortcut combines parallels or languages.

Intake re-reads product facts from the released catalogue. A reference-only card
uses the existing manual catalogue/intake transaction and requires review;
incomplete reference identity returns a review message. Idempotent receipts are
checked before the reference is re-read, so later source updates cannot change
an already committed retry. The confirmation digest lives in the same atomic
inventory/receipt transaction. No post-commit metadata write is required.

The catalogue exposes five primary browse destinations, with Naruto combining its two underlying systems. Artwork, complete set names, release
dates and market coverage vary; some One Piece sets still have provider pack
labels. Game and set tiles use the publisher artwork described below. Unknown
values remain pending. Set totals use the larger of the provider's declared
checklist count and loaded entries; missing/partial checklists are labelled.
This is not a claim of complete physical-printing coverage. Collectr's prices, percentage changes and wider
catalogue are not imported or invented. Product cards display approved canonical
images or labelled reference artwork. No storefront media is promoted here.

## Official title artwork

- All six game tiles now use official artwork, including Pokémon TCG. The two
  Naruto systems share the franchise logo with distinct Kayou/Bandai Legacy
  captions. Drop Rate's navy/blue/cyan surfaces and existing layouts are preserved;
  logos retain their original colours and proportions.
- Exact set-title artwork covers 30 English Pokémon expansions plus the English
  and Japanese One Piece OP13 titles. Matching requires the correct game and
  language, then an exact normalized name, set code or whitelisted provider ID.
  English Pokémon logos are not substituted for Japanese set titles.
- The existing TCGdex provider contributes 157 English set-logo URLs, matched by
  exact provider, language and set ID, with publisher-bundled artwork preferred.
  Its current Japanese index supplies no logos; those titles use the game-mark
  fallback. `backend/scripts/refresh_catalogue_logos.py` refreshes the checked-in
  lookup and source hashes from the two public indexes. It makes no database or
  inventory changes. These extra original logos load from the already permitted
  `assets.tcgdex.net` host and restore text if unavailable.
- Unmapped sets show the official game logo with the real set name and code.
  Failed image loads restore the text fallback. Unknown set values display
  Pending once; partially priced holdings retain the known sum plus pending.
- The 37 original publisher assets are bundled locally (about 1.5 MB in total),
  so browsing does not depend on publisher hotlinks. `catalogue-title-art.js`
  provides the small lookup. `backend/app/static/title-art/sources.json` records
  the source pages, original URLs, retrieval date, byte counts and SHA-256 hashes.
  This navigation artwork does not change product-media approval rules.

No database migration, permission policy, founder roster, pricing/provider setup,
recognition model, paid service or publishing flag was changed. This adds an
authenticated self-intake path using existing Draft/review rules, not approval or
other-account write authority.

## Verification and limits

- Live release: Railway deployment `46762407-3faf-4198-919a-b1f99a5c3c10`
  succeeded, including 2,372 backend tests and the readiness health check. Public
  HTTPS checks confirm both health endpoints and all three entry pages return
  200, the new scanner/catalogue assets match the release, and unauthenticated
  catalogue access returns 401. Existing open tabs need a reload.
- Empty-portfolio verification on 2 October: read-only queries of the actual
  database return all 810 current set/language/provider groups across six games,
  with every owned count zero. This includes 739 reference set records and 71
  additional canonical groups, not 810 distinct worldwide expansions. All 72
  previously hidden Pokémon reference sets (4 English, 68 Japanese) are now
  returned; their missing card checklists are explicitly unavailable, not
  fabricated. Current reference data holds 67,996 card records; complete worldwide
  catalogue coverage and every sealed release are still not established.
- Follow-up verification: 23 existing browser backend tests pass; the browser UI
  suite now has 9 scenarios, including empty ownership, empty set checklists,
  pagination, filter reset and provider/language-safe logo lookup. The exact
  paginated SQL also returns an empty known set and unowned Base Set cards.
  No production data was written.
- Full backend suite passed at 2,371 tests before the final incomplete-reference
  error check; the final browser-specific suite has 23 passing tests. It covers
  both roles, unauthorized founders/memberships, owner scoping, literal search,
  physical/authority-field rejection, incomplete reference handling and committed
  retry replay/conflicts.
- Existing dashboard/account suites, 20 scanner scenarios and 7 browser scenarios
  pass. Browser scenarios cover clear/reset, exact set/language scope, stale reads,
  account-isolated stars, mutually exclusive filters and uncertain multi-copy saves.
- Actual app assets were exercised in Chromium using simulated API/camera data:
  Seller Hub at 390×844 and both hubs at 320×568 and 1366×900. Search, sets,
  Japanese tab, filters, clear, own addition/re-add, scanner entry and graded
  manual details completed with no page errors or horizontal overflow.
- The artwork follow-up passed the existing UI suites and Chromium checks for
  both hubs at 320px/1366px and the 390px seller flow. All six game marks loaded;
  Pokémon and OP13 language matching, exact provider IDs and broken-image text
  fallback were checked. No page errors or horizontal overflow were observed.
- Read-only SQL checks against the existing database returned live games, sets,
  products and all three current sealed catalogue entries, including the two
  COLLECTION records. These checks were not authenticated live API acceptance.
- Preview screenshots contain official navigation logos, public SAMPLE card
  artwork where products are shown, and example responses/counts.
  No production inventory was added. No physical camera, real certificate lookup,
  production API latency or recognition accuracy claim is made.

The user clarified that they expected to test the changes in the actual hubs;
the previous baseline hold ended and both reviewed PRs were merged and deployed.
Complete physical-device/account/API acceptance on the live app. The rollback
target is API deployment `c408306f-8aef-4ec2-87d8-6bbf51e7c44d`; no migration or
production inventory write accompanied the release.

## Performance follow-up — 2–3 October 2026

Known-game/search entry no longer waits for the game directory. The product query allows early reference filtering and calculates prices only for the selected page unless sorting by value. Global exact-link deduplication, per-owner counts and full before/after result parity are preserved. Measured database medians and validation limits are in `docs/CATALOGUE_BROWSER_PERFORMANCE.md`.

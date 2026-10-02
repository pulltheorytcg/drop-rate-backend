# Product search and set browser

## Status — 2 October 2026

Implemented on `feat/collectr-product-browser`, stacked on the scanner PR #497.
Not merged or deployed. The user requested the product-list/search structure in
their 77-second Collectr recording, in Drop Rate colours. The recording starts
with Sealed Only already selected; the cleared Quick Filters screen is the
default, not the initial filtered frame.

## Behaviour

- Both hubs expose Search and a Search products & sets shortcut beside scanning.
  Primary navigation is Home, Search, Scan, Inventory and More. Sales remains
  accessible under More; existing account and founder tools are retained.
- The unfiltered search screen shows game tiles. Selecting a game opens a
  two-column mobile product grid, with removable filter chips and Show Sets.
- Sets have a separate search, available language tabs, release dates when known,
  owned/indexed progress and known inventory value. Selecting a set scopes the
  product query by game, set, language and provider.
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

The current catalogue has six game systems. Artwork, complete set names, release
dates and market coverage vary; some One Piece sets still have provider pack
labels. Game and set tiles use the publisher artwork described below. Unknown
values remain pending, and progress means indexed products rather than a claim
of complete master-set coverage. Collectr's prices, percentage changes and wider
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

Before rollout: review both draft PRs, incorporate the user's baseline scanner
test, and complete physical-device/account/API acceptance. Keep production on
the existing scanner during that baseline test.

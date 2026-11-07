# Comic and manga catalogue and saved artwork

The seller reported missing covers on previously saved books. The database held
14 publisher editions and two seller-entered Deadpool/Batman copies. Neither copy
had a saved artwork receipt. Five reviewed scanner covers were absent from product
search. Catalogue browsing and saved-copy artwork used different read paths.

## Change

The canonical catalogue now has a reviewed, replayable 32-edition expansion:
26 English VIZ manga volumes, five previously reviewed Marvel/DC issues, and the
Deadpool/Batman #1 Ryan Stegman second-print variant. Combined with the existing
14 editions, this gives 46 publisher editions: 36 manga and 10 comics. Manga
coverage is volumes 1–6 of One Piece, Naruto, Dragon Ball Z, Hunter x Hunter,
Jujutsu Kaisen and Death Note. This is a bounded foundation, not a comprehensive
comic/variant database.

Each new record has canonical identity, publisher/distributor source, language,
ISBN/UPC where established, release information, image URL, decoded dimensions
and SHA-256. Unknown printing remains unknown. Five older comics retain only
their evidenced release year; no release day is fabricated. The exact second
printing has an explicit source for the variant. All remain STRUCTURED with
pending storefront media rights; physical copy approval and prices are untouched.

The shared saved-artwork reader checks an explicit owner receipt, the exact
catalogue edition, then a unique nonconflicting reviewed barcode. The legacy
barcode `75960621349800112` matches PRH's Stegman variant and restores its reference
cover on read, with no production inventory rewrite. The second saved copy has no
barcode or cover variant and is intentionally not silently assigned that art.
Owners can use **Choose cover** in Item details to attach a compatible reviewed
cover to their existing Inventory ID. Choice requires seeing the image and an
explicit tap; metadata, ownership, identity approval, condition and prices stay
unchanged. No rescanning or duplicate intake is required.

Choices and private thumbnails enforce owner membership, RLS, current item
version and identity digest. Concurrent/retried identical choices are no-ops.
Changed choices preserve earlier evidence receipts under history keys in the same
transaction. A changed printing/language, source revocation or mismatched cover
artist invalidates artwork. Approved physical photos retain presentation priority.

## Provenance and operations

- VIZ facts and each declared `og:image` were read from linked public volume pages
  on 21 October. All 26 new images were decoded and visually inspected.
- The five older comic facts/images come from the reviewed 18 October manifest,
  now represented in the canonical product database as well as scanner choices.
- [PRH's exact variant record](https://prhcomics.com/book/?isbn=75960621349800112)
  identifies Ryan Stegman, second printing, UPC and 29 October 2025 release.
  The indexed record was available during research; subsequent page retrieval
  returned 404. Its public image service still returned the correct decoded JPEG,
  visually verified against the cover. The distributor image URL follows its
  [documented identifier-based image API](https://developer.penguinrandomhouse.com/docs/read/enhanced_prh_api/concepts/Images).
  Only exact numeric cover paths are allowed, bound to that source's ISBN/UPC.
- No new paid API, environment variable, service, schema or scheduler is added.
  Existing publisher research remains available beyond the reviewed catalogue.
  Adding another batch requires reviewed facts/bytes, tests and a normal PR.

Render the reviewed SQL with:

```sh
PYTHONPATH=backend python -m scripts.seed_book_catalogue backend/data/book_catalogue_expansion_20261021.json
```

Apply the rendered bounded data transaction only after CI passes. It takes an
advisory lock, inserts only catalogue/profile/book-detail rows, rejects conflicting
existing identities, and adds zero rows on replay. It never inserts inventory,
prices, media approvals or external listings. RLS and database storage guards
remain unchanged. Storefront use of these reference covers is not approved here.

## Verification and rollout

Regression tests cover all 46 edition covers; intake identity reuse; malformed
sources, barcode, artist, variant and language conflicts; missing scanner receipts;
no write during legacy repair; concurrent choice/replay; stale versions/digests;
cross-owner and anonymous denial; provider failure; and retained receipt history.
Disposable PostgreSQL runs both seed batches twice and verifies shared restricted
reads. Browser tests exercise saved-copy choice/readback at 390/1440 widths in
Chromium and WebKit. Existing scan/save and full Python/Node gates also apply.

### Release receipt: database applied, deployment blocked

[PR #695](https://github.com/pulltheorytcg/drop-rate-backend/pull/695) merged as
`a0ae3add367ff44b40b84ca3eb1e0e671573d3ab`. Its final head
`a7e6f11035b6accf1e47193675f9c82b36e6d13d` passed all six PR workflows:
Backend checks, Collection-first confirmation, Seller inventory persistence,
Shared inventory images, Immediate owner imports and Shared reference consistency.
The complete Python suite passed 6,216 tests. Browser checks passed in Chromium
and WebKit at both widths; inspected screenshots show saved reference artwork
after the physical-photo route returns 404. Those images use synthetic fixtures,
not an authenticated live seller session.

Final browser artifact `12335747037` (workflow `39578836803`) has SHA-256
`7d2b2312a5be3a3a56d137b93f2843d58663148dc9d109466a4821e7fe877b12`.
The reviewed 32-edition transaction was applied to the existing database on
21 October. Rendered SQL SHA-256:
`7891c9ebd9fc904725c9045d59df4d41fdd57dfb09d4a33d5c3049b49747a038`.
Readback found 46 official editions (36 manga, six Marvel, four DC), 48 total book
products, and 32/32 new references with source/hash evidence. All new identities
remain STRUCTURED with pending storefront media approval. Duplicate identity
groups: zero. Both physical inventory rows are unchanged, with before/after
digest `a667a4d499a44a780951a7a840ee2535`. Database size is 402,295,955 bytes.

**The new artwork code is not deployed.** Railway reported `Deploys have been
paused temporarily` when the existing API service's same repository/main source
was asked to build. Its [status page](https://status.railway.com/) reported an
active outage, with all-region builds paused (latest update 21 October 09:28 UTC).
No new deployment was created. The API remains on the healthy 18 October build
`c69c96da-0209-4665-975d-0ee200e5449e`, commit
`7558fd27374638f5dc8ad7548b330d5cbe97e661`. The newer catalogue metadata is stored,
but the new artwork registry and saved-copy picker need the pending app release.

Main Backend checks passed. Main Shared inventory images (`39579357110`) and
Collection-first confirmation (`39579357163`) passed their PostgreSQL/browser
jobs but failed their production readbacks on expected/deployed asset mismatch.
Those failures are retained; they have not been bypassed or labelled successful.
The [production diagnostic](evidence/book-library-release-status-20261021.json)
records current/expected asset hashes, readiness and database counts.

After Railway restores builds: build the merged main source through the existing
API service, preserve all predeploy gates, wait for SUCCESS, verify readiness and
all three `book-library-v1` asset hashes/entrypoint URLs, then rerun the two failed
production readback jobs. Verify anonymous cover/image denial and inspect the
seller's actual inventory using their normal session. The barcode-bearing saved
copy should receive its reference cover on read; the other requires **Item
details → Choose cover** because its variant remains unknown. Do not rescan,
duplicate or silently infer the second physical copy. The imported seed needs no
repeat application. Update this receipt only after the release is verified live.

Rollback: revert the code PR or restore Railway deployment
`c69c96da-0209-4665-975d-0ee200e5449e`. Keep additive catalogue rows and evidence
history; do not delete physical inventory or receipts. If an individual cover is
withdrawn, mark its existing source/rights status revoked through the normal
review process; the read paths fail closed.

# Default-camera comic routing

The founder's 16:03 iPhone recording loaded the current `book-cover-v5` assets,
then scanned eight physical comics with the default Cards tab still selected.
The eight owner-scoped receipts at 15:03–15:05 UTC all used
`/api/v1/recognition/resolve`; none reached the book reader or publisher lookup.
The generic vision schema did not permit BOOK. Its notes correctly identified
comic books, but its NONE/UNKNOWN classification produced an empty card review.
This was a routing defect, not a stale browser or a missing user confirmation.

The default camera is now labelled Auto. Its structured vision response accepts
BOOK and the same evidence-only book fields as the dedicated reader. One normal
vision request supplies the book details. The backend attaches a private book
receipt to the original run and returns the existing book review contract.
Legacy NONE/UNKNOWN responses that explicitly describe a comic book request one
bounded book-only read; those free-text notes never supply identity fields.
Cards and sealed products keep their existing matching and confirmation gates.
The recognition engine version advances to v1.10.0 to invalidate old replays.

Reviewed, compatible publisher references now arrive with the initial OCR
response in both entry points, avoiding a second lookup for those editions.
Uncached references still use the existing progressive publisher research.
The selected cover/details open the book form, with Add and optional Change cover.
The mixed queue retains each item's detected type, removal and late-response guards.

Automatic book receipts retain owner/RLS checks, original-image digest binding,
single-claim research and the existing shared 20/hour book allowance. A detected
book does not create inventory, approve identity/media, verify printing/condition
or generate a value. No schema or production configuration change is required.

## Market data is still unavailable

Read-only production checks on 18 October found 14 STRUCTURED and two NEEDS_REVIEW
book identities, no VERIFIED book identities and zero positive book market
snapshots. The latest eBay/Trawl provider receipt is HTTP 429 from 17 October
17:39:35 UTC, with its next permitted check at 18 October 17:39:35 UTC.
The provider pause has not been reset or bypassed. No new provider, subscription,
credit purchase, artificial sold evidence or unverified price is introduced.

Book review now checks stored values automatically after identification or copy
detail changes. A debounced read keeps owner/revision/save guards and never sets
asking price or acquisition cost. Missing data retains its stated reason and a
direct eBay UK completed/sold search, including the known edition and condition.
This comparison link does not import listings or establish a numeric valuation.
Provider recovery alone cannot price an unverified printing without eligible sales.

## Verification and limits

- Eight sanitized historical model observations reproduce the exact default-tab
  failure and reach the fallback book reader. No user/account IDs or source
  photographs are committed. These are routing regressions, not fresh OCR results.
- A mocked single vision request verifies typed book extraction and immediate
  selection of the existing Amazing Spider-Man #795 publisher reference.
- Real PostgreSQL/HTTP tests cover generic entry, receipt replay, owner isolation,
  original-photo research, one lookup, legacy recovery, shared cap and no stock write.
- Browser fixtures start in Auto, capture a book, open its populated book form,
  and show a stored fixture value after condition changes without a Check tap.
  Existing save/retry/artwork/editing checks and an eight-item mixed queue remain.
- Real phone OCR accuracy, current numeric book price coverage and universal
  publisher-cover coverage are not established by these fixtures. The corrected
  schema has not been evaluated against the recording using the live vision key;
  connected infrastructure access exposes variable names only.

## Release evidence

PR [#693](https://github.com/pulltheorytcg/drop-rate-backend/pull/693) merged as
`7558fd27374638f5dc8ad7548b330d5cbe97e661`. All six workflows passed on final PR
head `60d5043ba2ba55979b31192e23fcd2095bbc72d4`:

- Backend checks: run `39140626416`, including 6,196 Python tests and the complete
  Node suite (64 scanner scenarios).
- Collection-first confirmation: run `39140626453`, including real PostgreSQL
  receipt/RLS/digest/quota/no-write checks and Chromium/WebKit at 390/1440 widths.
- Shared inventory reference consistency: run `39140626420`.
- Shared inventory images: run `39140626469`.
- Immediate owner imports: run `39140626401`.
- Seller inventory persistence: run `39140626417`.

Final-head browser artifact `12141442654` was inspected: mobile Auto capture,
populated book review and automatically selected artwork with visible Add and
optional Change cover. Screens use synthetic test data, not new live OCR evidence.

Railway deployment `c69c96da-0209-4665-975d-0ee200e5449e` reached SUCCESS at
18 October 2026 15:34:05 UTC (16:34:05 BST), serving main `7558fd27`. Its predeploy
suite passed all 6,196 tests. Independent production readback at 15:34:29 UTC
confirmed all four scanner/book asset byte hashes match this release, both owner
and founder entrypoints reference `book-auto-v6`, readiness reports the database
connected, and anonymous book receipt/cover requests return 401.

All three main workflows passed: Backend checks `39140944155`, Collection-first
confirmation `39140944151` (including production readback), and Business production
readback `39140944149`. These checks establish deployed code and guarded behavior;
fresh phone OCR accuracy and live comic price coverage remain unverified/unavailable
as described above. Earlier saved items are not rewritten.

Rollback: revert this PR and redeploy through the unchanged pipeline. There is
no schema migration or financial/ownership write to reverse.

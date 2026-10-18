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

Deployment and CI receipts will be appended after the release gates complete.
Rollback: revert this PR and redeploy through the unchanged pipeline. There is
no schema migration or financial/ownership write to reverse.

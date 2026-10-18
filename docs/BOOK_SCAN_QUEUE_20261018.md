# Continuous book scanning and progressive review

Follow-up to PR #687 after the founder's 14:58 phone recording. Deletion worked,
but its floating control looked poor, capture stopped at two active reads, and
book details waited for a slow publisher search. Eight production HTTP requests
at 13:57–14:02 UTC took 22–42 seconds or disconnected; observed vision portions
were about 11–22 seconds. All eight receipts lacked cover URLs. These are measured
pre-change timings, not a claim about post-change phone performance.

## Changes

- Photos enter a bounded FIFO queue (50 waiting). Two recognition requests run
  concurrently; capture remains available while they finish. Removed queued photos
  never reach the API. Removing an active photo cancels its request and ignores its
  late response. Saved copies and uncertain saves keep their existing protection.
- The remove icon is integrated into the scan tile, with a 44px touch target and
  a specific accessible label. The extra floating row is removed.
- Book OCR returns first using `defer_research`; its fields can be reviewed while
  an independent queue of at most two publisher lookups completes. Existing API
  clients retain the single-request behavior. User edits and copy details are
  preserved when background results arrive. No partial result saves automatically.
- Research is claimed once under an owner-scoped row lock and uses the original
  photo digest. Retries read the same receipt; interrupted responses do not launch
  repeated paid lookups. Existing owner authorization, RLS and 20/hour cap remain.
  No database migration or new subscription is required.
- Publisher references already reviewed for the 14 catalogue books are available
  without another model/web search. Three additional verified issue previews cover
  Amazing Spider-Man #528, The Amazing Spider-Man #795, and Batman #463. Conflicting
  year/language/identity rejects a suggestion. Physical printing, variant and final
  Add remain for collector confirmation; the preview alone never selects a cover.
- Marvel portrait/detail/background image formats are accepted on the same narrow
  publisher CDN path. Canonical slug changes retain their exact numeric issue ID;
  other issue IDs, foreign hosts, arbitrary query strings and denial pages remain
  rejected. A sole reference can preview in the queue before the user selects it.

## Publisher evidence and remaining coverage

The additional JSON references store exact source/asset URLs, observation hashes
and dimensions; no customer photos or publisher image binaries are committed.
Marvel #528 and #795 images were found in the public image index tied to their
publisher issue pages. The same publisher asset's portrait renditions returned
HTTP 200, decoded at 300×450, and were visually checked. DC #463's public issue
metadata and UUID-bound cover were fetched and visually checked in the prior repair.
The references are edition previews, not permission to publish listing media.

Some Marvel HTML pages still return 403. Spectacular Spider-Man #11 and #114 do
not have a verified publisher image in this reference set; those covers are not
claimed fixed or substituted with seller photos. Superman's issue was uncertain
in the recording, so no guessed issue or artwork was added. Other books continue
through the bounded publisher lookup, with missing artwork reported honestly.

## Verification and release

Local targeted Python and scanner tests pass. The scanner suite includes seven
queued photos, bounded workers, removing a queued item, first results before cover
research, interrupted-response receipt recovery, owner changes and pending-save
protection. Added real PostgreSQL tests for staged receipt ownership, original-photo
binding and concurrent research claim. Browser tests exercise seven real shutter
clicks, usable remove targets at 390/1440 widths, and background artwork arriving
without overwriting edited identity or condition. Their camera/API are fixtures;
a physical iPhone recognition pass must not be inferred from these tests.

Required release gates: complete Python/Node suites, existing GitHub PostgreSQL
and Chromium/WebKit workflows, Railway predeploy, deployed asset/readiness/auth
readback. No environment, worker, price, inventory or publication settings change.
Cache versions are `book-queue-v4` in owner/founder entrypoints.

Rollback: revert this change or restore successful API deployment
`c4c41407-aee4-49c9-9751-96fd9d9e5c99` (main `b3819857`). No schema or inventory
rewrite is needed. Keep existing collection copies and scan receipts.

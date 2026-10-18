# Book scan recognition and queue removal

The 18 October 2026 founder recording asks for automatic comic/manga identification,
publisher artwork, a short add flow, and working removal of scans. This repair
reuses the existing vision/research account, authenticated thumbnail service and
owner-bound draft intake. No schema, production data repair, pricing, stock,
provider subscription, schedules, feature flags, worker configuration or Shopify
publication changes are included.

## Verified diagnosis

Read-only production query on `tcg.recognition_runs`, restricted to `book-scan:%`
and 18 October 13:08–13:16 UTC, returned eight scan receipts. Two lookups were
skipped because neither a reliable issue nor barcode survived OCR filtering.
Four scans had publisher metadata candidates but no image URL. Superman's tentative
issue reading was 304 at 0.8 confidence; it was not promoted to a confirmed value.
The founder entered 384 manually in the recording. Neither number is assumed true.
The scanner's `thumb` method forced every book to the captured photograph.
Removal controls were absent from camera tiles and disabled during recognition;
book review itself offered no queue-removal action.

## Behaviour and integrity

- A readable series plus cover can be researched even without a readable issue.
  Tentative issue OCR is a search clue only. Missing identity requires visual
  support or the collector's explicit choice; conflicting confirmed fields reject
  a publisher candidate. Existing OCR thresholds and hourly cap are unchanged.
- DC Universe Infinite's public issue catalogue is part of the existing official
  publisher search. Its cover preview is bound to the same book UUID; interior
  pages, foreign hosts and arbitrary transformations are rejected. A digital
  record never establishes the physical printing or barcode.
- When search returns metadata but no cover link, one public HTML request can
  recover the page's declared Open Graph/Twitter preview. Its canonical URL,
  title/issue and publisher image family must match. Reads have a six-second
  deadline and 1.5 MB decoded limit. Denials, redirects, unrelated pages and
  missing evidence fail closed. No credentials go to publishers.
- A single anchored publisher record fills metadata without pretending its cover
  was visually confirmed. A cover is selected automatically only when the research
  reported a visual match. Otherwise the collector chooses the displayed cover.
  Final Add remains an explicit draft collection action; no listing approval.
- The selected publisher cover appears in scan results and stays after a successful
  save. The existing owner/identity-bound receipt supplies collection artwork.
  Complete OCR also opens a short summary with optional details collapsed.
- Camera tiles, batch review and book review expose Remove scan. Cancelling an
  in-flight read releases its queue slot and ignores late responses. Card, sealed,
  graded and book paths share this rule. Pending saves are protected; saved scans
  can be dismissed from the queue without deleting their collection copies.

## Source evidence and limitations

The public official record
https://www.dcuniverseinfinite.com/comics/book/batman-1940-463/cd396b6b-50f5-4741-99df-16c0f1f26fa9
was read on 18 October. Its declared cover was fetched and decoded through the
actual bounded thumbnail service (WEBP, 56,100 bytes) and visually checked against
the founder's recording. No publisher or user image was committed to this repo.

The Marvel #795 source in the live receipt returned HTTP 403 from this environment.
The implementation does not bypass denial or borrow another issue/printing cover.
Live provider accuracy across every photographed issue remains unmeasured; passing
synthetic UI tests is not a real-phone recognition success claim. User photographs
are not persisted in research journals or source control.

## Verification and release

Targeted Python and JS tests cover missing-issue research, tentative OCR isolation,
source metadata recovery, wrong issue/host/redirect/oversize refusal, DC preview
identity, compact confirmation, removal, late responses, pending save protection,
selected artwork and owner reset. Existing full backend, PostgreSQL owner isolation,
immutable retries, browser phone/desktop and n8n build gates remain required.
The local Playwright browser download was blocked; actual browser checks must run
in the existing GitHub workflow before release. Deployment and readback evidence
will be added to this entry after verification.

Rollback: revert this code change or restore the previously successful API release
`cf4b00cd-2915-410c-8299-3b13f08291fc` (4a3cfe56). No schema rollback or inventory
rewrite is needed. Preserve all already-saved collection copies and receipts.

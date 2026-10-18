# Automatic book artwork selection

The founder asked for the same simple collection flow as cards: show the matched
artwork and filled details, then Add. PR #689 showed a sole publisher preview but
did not carry its artwork into the saved copy without a separate cover-choice tap.
This follow-up removes that extra step for a matched book.

## Behavior

- The backend selects the best eligible publisher reference automatically, preferring
  a visual match and then available artwork. Equal matches keep provider order.
  Existing source verification and observed-identity conflict checks still apply.
  An observed issue/ISBN or visual match is required; an unreadable, unmatched
  issue is not silently replaced with an arbitrary issue from search.
- Metadata comes from the same selected reference. Selection does not change
  `cover_matches_photo`, manufacture a printing number or price, or save inventory.
  A lookup without artwork can still fill supported book details.
- Review shows the selected cover, with alternatives behind **Change cover**.
  A single-cover result also offers another photo there. **Add to collection**
  carries the selected owner-bound research receipt into the saved copy without
  a separate cover confirmation. The scan queue labels a selected result Ready
  to add. No additional network search or provider is introduced.
- Background artwork selects itself when the collector has not edited identity;
  copy condition/cost/notes remain intact. Editing identity clears stale artwork.
  An explicit cover change fills that cover's details and is retained. Uncertain
  save retries keep their exact original payload and idempotency key.
- Save still creates a Draft personal-collection copy. Exact identity confirmation,
  listing media approval, publication and pricing are unchanged.

## Verification and release

Regression coverage includes default selection for reviewed publisher references,
best-candidate ranking, no invented printing/value/auto-save, missing identity and
missing artwork. The existing PostgreSQL test now saves an automatically selected
reference with `cover_matches_photo=false`, verifies owner/RLS restrictions,
retry identity, saved artwork and invalidation after a printing change.

Chromium/WebKit tests at 390/1440 widths cover one-tap Add with default artwork,
optional alternative selection, another photo, background artwork with copy edits,
manual identity edits and a disconnected save/reopen/retry. Synthetic camera and
publisher responses do not measure physical-phone recognition speed or coverage.

Release gates: complete Python/Node tests, existing PostgreSQL/browser CI,
production predeploy, deployed asset hashes, readiness and anonymous access denial.
Cache versions: `book-cover-v5`. No schema, provider, environment or production
data changes. Earlier scan receipts and saved copies are not rewritten.

Rollback: revert the follow-up or restore Railway
`3b0dd56c-26e1-4e77-96de-9abf6af1060c` (main `cfbcb756`). No data rewrite is needed.

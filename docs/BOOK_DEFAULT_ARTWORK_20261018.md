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
  to add. The Add action stays visible while optional fields scroll. No additional
  network search or provider is introduced.
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

## Live verification receipt

- PR [#691](https://github.com/pulltheorytcg/drop-rate-backend/pull/691), tested
  head `75f3ec73e54ff465065117a0c8e9d32c73a96f8c`, merged main
  `fc439fe657baee4194cd80211d3274ef57248d61`.
- All six final-head workflows passed. [Backend checks](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/39138091773)
  passed the complete Python/Node suites (6,180 Python tests, 63 scanner scenarios).
  [Collection confirmation](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/39138091799)
  passed PostgreSQL and Chromium/WebKit at 390/1440 widths. Artifact `12141000428`
  SHA-256 `988b50db60c0dea5667ab69496d456974ebfb44317bb735234a526a29c811ea7`;
  phone default-cover/alternative-cover and desktop default screenshots inspected.
  The first browser run exposed a test wait accessing an unloaded image; a later
  layout check caught shared CSS reducing a touch target to 42px. Both were fixed
  before the final all-green run; book action targets are now at least 44px.
- Railway deployment `8d7cc901-ced5-4121-8d20-c4aa3c7b0f37` reached SUCCESS
  at 14:58:45 UTC. The existing predeploy passed 6,180 Python tests.
- GET-only readback at 14:58:58 UTC matched all four scanner/book JS/CSS files,
  owner/founder cache versions, ready/connected database status and anonymous
  receipt/cover 401. See [readback evidence](evidence/book-default-artwork-readback-20261018.json).
  The main-branch production-readback job also passed in
  [run 39138302480](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/39138302480).
- Refresh and start a fresh scan. This does not rewrite earlier receipts or
  saved copies. Browser fixtures verify the interaction and save payload, not
  physical iPhone recognition timing or universal publisher coverage.

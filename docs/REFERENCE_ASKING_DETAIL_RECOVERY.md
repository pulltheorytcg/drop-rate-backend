# Reference asking-price detail recovery — 29 October 2026

## Observed failure

Cloud run `ce1f435a-3a1c-4a94-889d-8fe887da7147` finished at
2026-10-29 00:36:05 UTC with `INCOMPLETE / REQUEST_LIMIT`: 1,000 charged
searches, 3,976 references scanned, 513 item summaries, zero matched/written
estimates. The cursor is `[Bandai Official, DRAGON_BALL_SUPER_MASTERS,
English, 428021:BT21-079.png]`.

Summary rejections were 186 game, 139 language, 119 graded/slab, 37 name,
14 set, 13 multiple-item/nonphysical and five number conflicts. A further
2,976 references were excluded before search as unresolved parallels.
These counts describe distinct checks; they are not additional priced cards.
The last verified full-denominator coverage is 43,454/67,065 (64.7939%),
with 16,234 additional supported prices needed to reach the 59,688 threshold.

## Repair

Search summaries were passed directly to a validator that needs exact listing
aspects. Official Browse documentation distinguishes discovery summaries from
the full details returned by `getItem`. The worker now hydrates at most six
plausible item IDs per reference and validates the returned detail alone.

- Search no longer requires the language word in the title. The listing must
  still explicitly establish the same language in its actual details/title.
- Masters discovery uses `Dragon Ball Super`. Acceptance recognises the
  official former full name `Dragon Ball Super Card Game` only for canonical
  Masters references with an exact BT/TB/EX/SD collector number. Fusion World
  conflicts, unknown families, set/printing and variant checks remain.
- Six exact English Bandai Masters releases accept their verified official
  short names alongside full catalogue labels: Wild Resurgence, Critical Blow,
  Perfect Combination, Beyond Generations, Legend of the Dragon Balls and
  Ultimate Advent. Aliases require the exact provider/game/language/set ID and
  canonical name; explicit curated terms retain precedence. A wrong structured
  set or printing conflict still rejects the listing.
- Browse `conditionDescriptors[].values[].content` and `additionalInfo` are
  read alongside aspects. Ungraded alone does not establish Near Mint.
- Returned item IDs must match discovery IDs. Missing fields are never filled
  from an earlier search summary. Explicitly unavailable or now-ended listings
  are excluded, including when a detail is reused within the invocation.
- Only a small in-memory detail cache is used; cached evidence retains its
  original acquisition time. Accepted comparable evidence includes the actual
  normalized game/language/number/set/finish/condition fields used to match.

Every search and every detail GET is durably charged before HTTP and shares
the existing one-request-per-second limiter, actual provider quota windows,
500-request headroom, 2,000/day allowance, 45-minute deadline, global lock and
400,000,000-byte database guard. **`--max-queries 1000` now means at most 1,000
total Browse requests, not 1,000 distinct cards.** Reports separate search and
detail requests. Failed and uncertain calls remain charged; no ledger resets.

The current three-independent-seller estimate, outlier handling, labelled
asking basis, three-day expiry and catalogue-only write path remain intact.
No canonical identities or physical inventory are changed by this repair.

## Primary evidence

- [eBay Browse overview](https://developer.ebay.com/api-docs/buy/static/api-browse.html)
  distinguishes search summaries, refinement histograms and complete `getItem`.
- [Current eBay inventory-discovery guide](https://developer.ebay.com/develop/guides/buy/inventory-discovery-and-refresh-guide)
  documents full item details; bulk `getItems` is restricted to selected partners
  and is not introduced here.
- [eBay Connect 2023 Buy APIs, condition grading](https://developer.ebay.com/cms/files/connect-2023/buy_apis.pdf)
  documents the exact Browse descriptor shape and Near Mint example.
- [Bandai's official Masters description](https://www.dbs-cardgame.com/europe-en/about/)
  states that the original game was renamed Masters in March 2024.
- Official [BT21 card list](https://www.dbs-cardgame.com/europe-en/cardlist/?category=428021&search=true),
  [TB1 card list](https://www.dbs-cardgame.com/europe-en/cardlist/?category=428101&search=true),
  [EX21 card list](https://www.dbs-cardgame.com/europe-en/cardlist/?category=428421&search=true),
  and [original SD1 product](https://www.dbs-cardgame.com/europe-en/product/dbs-sd01.php)
  establish the scoped collector-number families. These are game evidence,
  never sufficient proof of original release: starters may contain reprints.
- The exact set-name aliases are evidenced by Bandai category pages
  [428021](https://www.dbs-cardgame.com/us-en/cardlist/?search=true&category=428021),
  [428022](https://www.dbs-cardgame.com/us-en/cardlist/?search=true&category=428022),
  [428023](https://www.dbs-cardgame.com/us-en/cardlist/?search=true&category=428023),
  [428024](https://www.dbs-cardgame.com/us-en/cardlist/?search=true&category=428024),
  [428025](https://www.dbs-cardgame.com/us-en/cardlist/?search=true&category=428025),
  [428026](https://www.dbs-cardgame.com/us-en/cardlist/?search=true&category=428026).

## Validation and rollout

322 focused tests pass locally, including realistic summary/detail separation,
conditions, language contradictions, exact ID binding, availability, known
end-time crossing, original-name Masters mapping, independent sellers, budget
refresh across search/detail calls, provider failures and retained evidence.
The normal backend/UI/n8n CI and disposable PostgreSQL asking-price contract
must pass on the PR head before deployment. No migration is required.

Before restarting the dedicated cloud worker, verify the predecessor receipt,
no active competing process, remaining daily allowance and current database
capacity. Use a fresh run ID, the saved cursor via `--resume-run`, the same
English/apply scope and a unique checkpoint. A bounded live canary must verify
actual detail shape and rejection evidence before spending the remaining
allowance. Keep `restartPolicyType=NEVER` and no public endpoint.

This implementation and its synthetic tests do not establish a price gain.
Record actual live accepted writes, full coverage and inventory readback after
execution. Unconfigured set aliases remain a separate narrow issue: do not
replace explicit release evidence with a collector-number prefix.

## Live detail canary and resulting corrections

All seven applicable PR workflows passed at `c8c2450476494c632f2c7a438bc79ade9c0c7a8a`,
including 8,264 backend tests (18 skipped), UI/n8n checks and the native
PostgreSQL asking-price contract. Dedicated-worker deployment
`d629e96e-5369-48e7-b3c4-3611bff9e764` succeeded after two source-triggered
attempts were skipped by Railway; the manual redeploy built the pinned source.

Canary `52c5b0da-4dec-4255-9910-631466236065` ran from 07:36:52 to
07:37:45 UTC, resuming the original cursor. Its 40 total requests were 26
searches and 14 item-detail GETs. It retrieved 592 summaries and all 14 details,
with no provider failures and zero accepted/written estimates. Detail
rejections: five language, three finish, two set, two graded/slab, one number
and one multiple-item/nonphysical. This proves full-detail retrieval, not a
coverage gain. Cursor: `[Bandai Official, DRAGON_BALL_SUPER_MASTERS, English,
428022:BT22-092_PR.png]`. The daily ledger is 1,040 requests, leaving 960.

The next correction excludes unresolved official Masters `_PR` special
printings before search. Bandai's official cardlist identifies `BT21-102_PR`
as Championship 2024 Finals ZENKAI Pack, while adjacent `_PR` cards belong to
ZENKAI premium pack. These must never be stripped to the base number/price.
It also recognises the literal negative grading value `Not Professionally
Graded`, while retaining every positive grading contradiction. Full-detail
rejection examples replace less useful search-only examples within the same
bounded receipt. The follow-up code requires its own exact-head CI before use.

At 07:35 UTC the catalogue denominator had independently grown by one to
67,066. Supported existing prices remain 43,454; zero asking estimates.
The updated 89% threshold is 59,689 and the gap is 16,235. At 07:34:55 UTC,
database size was 372,853,907 bytes and all 616 physical inventory rows still
matched `47a316ca0609fbbfedcd32f002c4c335`.

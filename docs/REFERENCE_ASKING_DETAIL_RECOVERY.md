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

## Validation and rollout

273 focused tests pass locally, including realistic summary/detail separation,
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
execution. Set aliases remain a separate narrow issue: do not replace explicit
release evidence with a collector-number prefix.

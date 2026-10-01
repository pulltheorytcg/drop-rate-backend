# Recognition reference library

The scanner can retrieve card identities before any owner has scanned or stocked
them. Provider checklists live in `tcg.reference_sets` and `tcg.reference_cards`,
separate from inventory, canonical printings, media approvals and verified learning.
Both authenticated Founder HQ and Seller Hub scanners query the same library.

## Current import scope

| Game line | Source | Initial reference records | Scope |
|---|---|---:|---|
| Pokémon | TCGdex | 36,776 | English/Japanese set checklists |
| One Piece | Punk Records | 8,480 | English/Japanese index, including distinct provider variants |
| Dragon Ball Super Masters | Bandai official checklist | 8,982 | English; card faces and set appearances count separately |
| Dragon Ball Super Fusion World | Bandai official checklist | 6,585 | English/Japanese; one empty English source checklist remains a gap |
| Naruto Kayou | Naruto Card Game Archive | 2,679 | Tier/wave/box/variant metadata retained |
| Naruto Bandai Legacy | Naruto Card Game Archive | 4,487 | 38 legacy set references |

Total prepared: **67,989 reference records / 734 set-language records**.
Pokémon/One Piece snapshots were collected on 29 September 2026; Dragon Ball and
Naruto on 30 September. These counts are not unique physical printings, complete
worldwide coverage, or measured photo-recognition accuracy. The coverage API is
the authority for records actually loaded, with the latest sync status and dates.
Riftbound, Disney Lorcana and other game lines remain deferred for this expansion.

Sources:
- https://api.tcgdex.net/v2/en/sets
- https://github.com/Kuroro1990/OPTCG
- https://www.dbs-cardgame.com/us-en/cardlist/
- https://www.dbs-cardgame.com/fw/en/cardlist/
- https://www.dbs-cardgame.com/fw/jp/cardlist/
- https://narutocardgame.gg/archive/kayou/cards
- https://narutocardgame.gg/archive/classic-ccg/cards

## Recognition contract

Game/system and known language scope the indexed lookup. Collector-number keys
normalize zero padding but preserve fraction boundaries and special printing
symbols. Pokémon local-number-only retrieval is supported; the missing set or
denominator remains uncertainty, not evidence of an exact match.

Unmapped references participate as provider candidates. An unseen card can return
`NEEDS_REVIEW` with its source identity rather than `NO_MATCH`.

For a provider candidate with no canonical row, Seller Hub may offer **New to Drop
Rate** human confirmation only when the persisted evidence is already strong enough
to satisfy the exact identity threshold, exact card-number/language checks, strong
provider identity, and no OCR-number conflict. Confirmation calls the narrowly
scoped database materialisation function; the database independently rechecks the
current owner, run/candidate, provider reference and duplicate mapping before it
creates review-gated canonical data. The resulting profile remains
`NEEDS_REVIEW`; the physical item remains DRAFT / unverified.

A bulk reference import still cannot create owned inventory, certify a printing,
approve media, publish a product, or self-train. Provider/reference data cannot
materialise itself without the explicit human confirmation path.
Checklist evidence is excluded from local exact-printing score support. New game
lines remain review-only until validated with a game-specific evaluation set.

Naruto archive pages use English display names but do not prove physical card
language. These rows deliberately store `Unknown`, and retrieval allows them as
review candidates for the appropriate Naruto line. No language is inferred from
the website's interface. Edition and finish remain unresolved.

Bandai records retain official image URLs, face and alternate-art identifiers.
The library stores image references, not copies of image binaries. Source release
dates are used only when supplied. Unknown dates are visible as unverified, and
known future releases are excluded from scan matching.

## Operations

Apply the canonical `recognition_master_library` migration before deploying the
scanner integration. The applied production migration version is
`20260930153431`; its matching SQL is in `database/migrations`.

To refresh the six priority feeds using the deployed backend's normal database
configuration and an existing platform administrator:

```sh
PYTHONPATH=backend python backend/scripts/sync_reference_library.py --actor-user-id UUID
```

Use repeated `--source` options to select `tcgdex`, `punk`,
`dragon_ball_masters`, `dragon_ball_fusion`, `naruto_kayou`, or `naruto_bandai`.
The command returns nonzero for incomplete imports. Each set is upserted in its
own transaction and a durable `tcg.reference_sync_runs` record reports outcome,
counts and source failures. Restarting is idempotent; successful earlier sets
survive a later error. Existing records are never deleted on a partial feed.
No startup import or recurring scheduler is enabled by this change.

The empty English Fusion World checklist is category `583902`. Other sets and
the Japanese catalogue are imported despite that gap. A successful feed walk
only means that walk completed; it is not a completeness claim for the franchise.

## Verification

Regression tests cover padding, fraction collisions, Kayou symbols, alternate
images, empty/truncated checklist detection, unknown-language retrieval and
unseen-card review candidates across all six game lines. Existing exact-printing,
owner access and recognition-learning tests remain required. Live verification
must check row counts, RLS, indexed retrieval and scanner deployment separately.
Real customer-photo recognition accuracy remains unmeasured for the new library.


## 1 October 2026 live regression finding

A production Seller Hub session exposed the difference between **reference coverage**
and **canonical coverage**. The engine correctly read Japanese Trafalgar Law
`OP05-069` and ranked the matching Punk Records provider printing at roughly 0.93,
but `tcg.catalogue_products` had no OP05-069 row. All returned candidates therefore
had `catalogue_id = NULL`, and the old Seller Hub UI filtered them out.

The v1.6.1 repair keeps those safe provider candidates visible and adds the
human-confirmed review-gated materialisation flow described above. It also aligns
the OpenAI structured-output JSON schema with the local Pydantic limits so harmless
provider overflows (for example a slightly-out-of-range confidence or an oversized
OCR list/text field) do not discard an otherwise usable observation.

This does not relax exact-printing gates and does not make reference-library
coverage equivalent to verified catalogue coverage.

# Catalogue continuation — 27 October 2026

## Completed release

The last unfinished branch was PR [#749](https://github.com/pulltheorytcg/drop-rate-backend/pull/749),
which had three failing scheduler tests and had not been deployed. The corrected
head is `8b9d5449b5fe437eef42b36aaf6f20c6c51ba8e1`; the squash merge is
`674bcb56d4df35420e6bba3c6b01c6bffa16f72a`.

- Hourly approved-source pricing jobs run before daily metadata work. Failed or
  interrupted work records INCOMPLETE and preserves bounded retry/cursor behavior.
- New-set receipts count identities newly committed to the database, distinguish
  provider/game/language, preserve unknown release dates, and cap examples while
  retaining the full count. Refreshed existing sets are not new discoveries.
- The prepared, disabled TCGCSV adapter checks number tokens in both product names
  and number fields so malformed or differently cased alternate variants cannot
  disappear from ambiguity checks. Acceptance still requires the exact identity.
- TCGCSV evidence and price writes carry the import receipt ID. Committed readback
  determines the write count; rollback, uncertain commit acknowledgement and
  failed readback cannot be represented as successful attempted writes.

Validation: **6,924 backend tests passed locally**, and all eight GitHub workflows
passed on the corrected head. The [backend workflow](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/40487798576)
is one of those eight runs. Targeted coverage includes hourly failure/retry order,
capacity gates, disabled-feed behavior, variant ambiguity, rollback and uncertain
commit outcomes, and committed new-set receipt counts.

Railway API deployment `95ca326e-10cb-4030-8a55-262be89b6fde` reached **SUCCESS**,
observed at **10:26:13 UTC**, running merge `674bcb56`. Its normal predeploy gates
passed all 6,924 tests, the Stripe sandbox check and cleanup, and the financial
read-only self-test. The transfer self-test and social evidence probe reported
SKIPPED under their existing configuration; they are not recorded as passed.
The app completed startup and public `/health/ready` returned HTTP 200 with
`{"status":"ready","database":"connected"}`.

## Verified catalogue state

The Supabase readback was taken at **2026-10-27 10:25:10.695499 UTC**. The latest
successful coverage receipt in that readback is dated **10:07:21.502472 UTC**.
Coverage is a receipt snapshot, not a claim that every reference has been
re-fetched or individually inspected during this continuation.

| Measure | Verified value | Scope |
| --- | ---: | --- |
| Physical card references covered | 43,033 / 67,065 (64.17%) | Supported values and explicitly labelled marketplace guides |
| Physical card references missing | 24,032 | No supported value/guide in the coverage receipt |
| Additional covered references required for 90% | 17,326 | Target is 60,359 of the unchanged physical denominator |
| All card references | 69,545 | Includes 2,480 digital Pocket references, consistently excluded from physical coverage |
| Sealed references covered | 2,740 / 3,891 (70.42%) | Separate from physical-card coverage |
| Populated artwork URLs | 62,512 / 69,545 | URL presence; not a fresh successful fetch of every external URL |
| Missing artwork URLs | 7,033 | Artwork remains incomplete |
| Approved R2 media mirrors | 401 | Verified approved-media records; zero eligible queue backlog |
| Broad reference-image mirrors | 0 | Source-permission hold remains |
| Comic/manga editions | 95 | Factual edition metadata; full catalogue, covers and valuations remain incomplete |
| Verified private R2 history archives | 20 | Registry-backed verified archives |
| Verified archived history rows | 39,542 | Historical observations, not additional currently priced references |
| Database size | 357,608,595 bytes | Writable; below the unchanged 400,000,000-byte refresh guard |
| Inventory rows | 616 | Count readback only; no new full-row checksum verification claimed here |
| TCGCSV price rows | 0 | Feature flag absent; code default false |

The previous handover had 42,962 covered physical references. The increase of
**71** came from the existing imports before this release. No manual additional
price values are attributed to this continuation. Refresh/write counts from
individual jobs are not counts of newly covered references.

### Physical coverage by game

| Game / language | Covered | Total physical | Missing |
| --- | ---: | ---: | ---: |
| Pokémon English | 20,765 | 21,290 | 525 |
| Pokémon Japanese | 10,397 | 13,006 | 2,609 |
| One Piece English | 2,334 | 4,527 | 2,193 |
| One Piece Japanese | 2,156 | 4,480 | 2,324 |
| Dragon Ball Super Masters English | 5,582 | 9,002 | 3,420 |
| Fusion World English | 1,400 | 4,365 | 2,965 |
| Fusion World Japanese | 399 | 3,229 | 2,830 |
| Naruto Bandai legacy | 0 | 4,487 | 4,487 |
| Naruto Kayou | 0 | 2,679 | 2,679 |

English Pokémon has 23,770 total references in the raw receipt; its 2,480 digital
Pocket references are removed consistently to obtain 21,290 physical references.
Guide coverage does not mean exact condition-specific UK sold comparables.

### Core catalogue information present on the same card

A second live query at **10:32:18.133884 UTC** checked the intersection, rather
than combining unrelated percentages. It reused the production coverage query's
source/identity/recency joins and excluded the same 2,480 digital references.
Basic identity presence required nonblank provider ID, name, set ID and set name,
collector number, source URL and system, plus a recognised recorded language.

**38,819 / 67,065 physical references (57.88%)** have those basic identity fields,
a populated artwork URL, and a current supported value or labelled guide on the
same record. **4,214** priced references lack an artwork URL. This is a data-presence
measure, not a fully verified completion certificate: it does not re-fetch every
image, visually verify every printing, or turn a mixed-language guide into an
exact physical-copy valuation.

| Game / language | Identity + artwork URL + supported value/guide | Percentage of imported physical references |
| --- | ---: | ---: |
| Pokémon English | 19,886 / 21,290 | 93.41% |
| Pokémon Japanese | 7,062 / 13,006 | 54.30% |
| One Piece English | 2,334 / 4,527 | 51.56% |
| One Piece Japanese | 2,156 / 4,480 | 48.13% |
| Dragon Ball Super Masters English | 5,582 / 9,002 | 62.01% |
| Fusion World English | 1,400 / 4,365 | 32.07% |
| Fusion World Japanese | 399 / 3,229 | 12.36% |
| Naruto Bandai legacy | 0 / 4,487 | 0% |
| Naruto Kayou | 0 / 2,679 | 0% |

Physical references have **60,191 / 67,065 artwork URLs (89.75%)**; this denominator
differs from the all-reference 89.89% above. Of the priced records with URLs, 540
English Pokémon records use CardTrader images. They are valid direct-image
candidates under the current browser's display fallback and CSP even though the
TCGdex-specific reference proxy does not accept that different host. Proxy-route
eligibility alone must not be mistaken for all artwork display availability.

The two Naruto catalogues have **7,166** unpriced references and no verified
permitted pricing feed. Even covering every other physical reference would yield
59,899 / 67,065, or **89.31%**. Reaching 90% therefore also requires supported
Naruto coverage; excluding those catalogues to improve the percentage would
change the agreed denominator.

### Comics and manga completeness

A read-only join of `comic_printing_details`, `catalogue_products` and
`catalogue_product_profiles` at **10:36:53.305566 UTC** split the 95 editions and
checked for any positive `catalogue_market_snapshots` value. Even that weaker
ever-positive test returned zero; current eligible shared book values therefore
also remain zero.

| Measure | Comics | Manga |
| --- | ---: | ---: |
| Imported edition records | 37 | 58 |
| Basic edition fields present | 35 / 37 (94.59%) | 58 / 58 (100%) |
| Printing number recorded | 3 | 0 |
| Book and profile printing identities both VERIFIED | 0 | 0 |
| Any positive catalogue market snapshot, including historical | 0 | 0 |
| Identity + cover + supported value complete | 0 / 37 (0%) | 0 / 58 (0%) |

The basic edition test requires title, series, issue/volume, publisher, language
and release year. It does not establish the exact printing or cover variant.
These are percentages of the **editions currently imported**, not of all comics
or manga ever published. The intended external catalogue universe and its total
have not been established, so a worldwide catalogue-coverage percentage cannot
be calculated from 95 entries. Covers, even where available, cannot make a record
complete while its required value and exact-printing evidence are absent.

The project's Action Pack (18 October), sections 3.1 and 3.2 T4/T6, requires exact
identity, correct usable artwork and honest source-backed prices/guide labels.
It distinguishes catalogue guides from physical-copy-eligible valuations. The
Phase 2 Operating Manual, page 2 section 2, also requires exact-print identity;
neither document supplies a universal field-by-field comic/manga completeness
schema. This checkpoint's field-presence tests are explicit operational measures,
not a substitute for those stricter verification requirements.

## Running automation and source hold

The existing hourly allowance remains 10 One Piece, 18 Dragon Ball and 7 Pokémon
requests: 35 per hour, at most 840/day under normal scheduling, within the shared
1,000/day provider allowance. Existing locks, cursor state, reserve checks and
capacity guards remain in force. The eight daily reference syncs completed in
the 03:12–03:20 UTC window. Processed records in those jobs are not all new cards.

The last verified history archive in the database readback was committed at
**10:19:23.579562 UTC**. Archival verifies downloaded content and typed restoration
before guarded cleanup. Current prices, inventory ownership, acquisition costs
and Store Prices remain authoritative in Supabase.

The hourly **Drop Rate Catalogue Watch** remains enabled. Its prompt now carries
the source hold and requires committed readback before reporting new additions.
The existing separate archive watch is unchanged.

**TCGCSV remains disabled.** Its [FAQ](https://tcgcsv.com/faq) identifies TCGplayer
API data as its source. TCGplayer's [published API terms](https://help.tcgplayer.com/hc/en-us/articles/360061115874-TCGplayer-API-Terms-Conditions)
restrict downstream third-party data acquisition and commercial/competitive reuse.
No permission covering Drop Rate's intended use has been verified. Technical
readiness, public availability and a successful R2 verification do not establish
that permission. Keep `TCG_TCGCSV_FREE_ENABLED=false` unless the hold is explicitly
resolved and documented. See the [automation runbook](FREE_CATALOGUE_AUTOMATION.md).

## Pending Fusion guides and approval outcome

The existing importer filled four of the ten previously pending SB01 references
at about 03:21 UTC: SB01-018, SB01-019, SB01-045 and SB01-049. They retain the
`POKEWALLET_DBS_CARDMARKET_CATALOGUE` source label.

Six references in reference set `583201` still had no value on readback:

| Reference ID | Card |
| --- | --- |
| `583201:SB01-030` | Dabura |
| `583201:SB01-033` | Majin Buu |
| `583201:SB01-036` | Majin Buu: Evil |
| `583201:SB01-050` | Master Roshi |
| `583201:SB01-051` | Krillin |
| `583201:SB01-057` | Bulma / Son Goku: Childhood |

A bounded dry preview using the existing reviewed operator was prepared. Railway's
`railway_accept_deploy` returned: **"Cancelled — the user did not approve this
action. No changes were made."** The preview was not executed and no provider
calls or price writes from that operator are claimed. The normal predeploy
command was restored before the separate scheduler release deployed.

Operational detail: Railway retains staged patch
`06e57c47-c3fc-486d-83ea-ff1f262d883b`, containing the restored normal predeploy
command with identical effective before/after configuration. No one-off operator
command remains in the desired or staged configuration. No further attempt was
made to accept that declined deployment. The six guides remain eligible for the
existing importer; a separate one-off preview still requires the approval that
Railway declined.

## Resume order

1. Read actual hourly receipts after this deployment. Confirm incomplete/error
   reporting, bounded cursor progress and committed coverage changes. Do not
   describe scheduled attempts as added prices.
2. Resolve exact provider mappings and use the existing permitted sources for
   missing values, retaining game, language, release, number, finish and edition
   identity. Respect shared quotas and do not substitute asking prices for sold
   comparables or invent values where sources have none.
3. Continue artwork repair only from permitted sources. Reconcile missing URLs,
   successful image delivery and approved R2 mirrors as separate measurements.
4. Expand comics/manga with a proper permitted bulk metadata workflow; the full
   Open Library monthly-dump importer is not deployed. Metadata alone does not
   supply market values or blanket cover-reproduction permission.
5. Establish permitted Naruto pricing coverage and resolve any proposed feed's
   downstream rights before activation. The 90% target, full artwork and complete
   comic/manga catalogue remain unfinished.
